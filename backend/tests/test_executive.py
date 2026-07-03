"""Self-contained tests for Yönetici (CMO) Görünümü — Executive Overview.

Coverage
--------
1. Pure helpers (no DB)
   - _compute_delta: positive change, negative change, zero previous → None
   - _compute_totals: correct summing across channels, roas calculation

2. build_overview (with seeded 2-channel warehouse)
   - totals correct (spend, revenue, roas)
   - channels sorted by spend descending
   - share_pct sums to ~100
   - MoM deltas computed correctly when previous-period data exists
   - goals surface (seeded Goal)
   - insights surface (seeded Insight)

3. Empty warehouse
   - zeros for all KPIs
   - sensible fallback headline ("yeterli veri yok")

4. HTTP endpoint
   - 200 happy path with correct response shape
   - default date range (date_to today, date_from today-29d)
   - date_from > date_to → 422
   - missing auth → 401
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Register all models so Base.metadata.create_all works ─────────────────────
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401
import ayaz.models.insights  # noqa: F401
import ayaz.models.reports  # noqa: F401
import ayaz.models.automation  # noqa: F401
import ayaz.models.tracking  # noqa: F401
import ayaz.models.goals  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.briefing  # noqa: F401
import ayaz.models.budget  # noqa: F401
import ayaz.models.content  # noqa: F401
import ayaz.models.notifications  # noqa: F401
import ayaz.models.social_inbox  # noqa: F401

from ayaz.database import get_db
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
from ayaz.models.goals import Goal
from ayaz.models.insights import Insight
from ayaz.models.oltp import (
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
)
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import executive as executive_module
from ayaz.services.auth import hash_password
from ayaz.services.executive import _compute_delta, _compute_totals, build_overview

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Executive Test App")
_test_app.include_router(executive_module.router, prefix="/api/v1")


# ── DB fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Client fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Exec Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="exec_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Exec Test User",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db_session.add(membership)
    db_session.commit()

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override — tests 401 behaviour."""
    def override_db():
        try:
            yield db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Exec Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "exec@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(), email=email,
        hashed_password=hash_password("pw"),
        full_name="Exec User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(), user_id=user.id,
        tenant_id=tenant.id, role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=Platform.sample, external_account_id="EXEC-ACC-001",
        display_name="Exec Account", vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _ensure_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d, year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week,
        day_of_week=d.weekday(), is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _make_channel(db: Session, key: str, label: str | None = None) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=label or key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str = "Camp"
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant.id,
        channel_id=channel.id, external_id=f"CAMP-{uuid.uuid4().hex[:6]}", name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant.id,
        campaign_id=campaign.id, external_id=f"ADSET-{uuid.uuid4().hex[:6]}", name="AdSet",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant.id,
        ad_set_id=adset.id, external_id=f"AD-{uuid.uuid4().hex[:6]}", name="Ad",
    )
    db.add(ad)
    db.flush()
    return ad


def _insert_fact(
    db: Session,
    tenant: Tenant,
    acct: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    d: date,
    *,
    spend: str = "0",
    conversions: str = "0",
    conversion_value: str = "0",
    impressions: int = 0,
    clicks: int = 0,
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    row = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=Decimal(spend),
        cost_ccy="TRY",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value),
        conversion_value_ccy="TRY",
        cost_base_ccy=Decimal(spend),
        conv_value_base_ccy=Decimal(conversion_value),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _seed_two_channel_warehouse(
    db: Session,
    tenant: Tenant,
    date_from: date,
    date_to: date,
    *,
    prev_spend_google: str = "0",
    prev_spend_meta: str = "0",
    prev_revenue_google: str = "0",
    prev_revenue_meta: str = "0",
) -> tuple[DimChannel, DimChannel]:
    """Seed two channels (google_ads, meta_ads) with fact rows.

    Current period: google spend=5000, revenue=20000; meta spend=3000, revenue=9000.
    Previous period uses provided kwargs (default 0 = no previous data).
    Returns (google_channel, meta_channel).
    """
    acct = _make_connected_account(db, tenant)
    google = _make_channel(db, "google_ads", "Google Ads")
    meta = _make_channel(db, "meta_ads", "Meta Ads")

    g_camp = _make_campaign(db, tenant, google, "Google Campaign")
    g_adset = _make_adset(db, tenant, g_camp)
    g_ad = _make_ad(db, tenant, g_adset)

    m_camp = _make_campaign(db, tenant, meta, "Meta Campaign")
    m_adset = _make_adset(db, tenant, m_camp)
    m_ad = _make_ad(db, tenant, m_adset)

    # Current period — insert on date_from
    _insert_fact(
        db, tenant, acct, google, g_camp, g_adset, g_ad, date_from,
        spend="5000", conversion_value="20000", conversions="50",
        impressions=100000, clicks=5000,
    )
    _insert_fact(
        db, tenant, acct, meta, m_camp, m_adset, m_ad, date_from,
        spend="3000", conversion_value="9000", conversions="30",
        impressions=80000, clicks=4000,
    )

    # Previous period — insert on prev_to (1 day before date_from)
    period_len = (date_to - date_from).days
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_len)

    if float(prev_spend_google) > 0 or float(prev_revenue_google) > 0:
        _insert_fact(
            db, tenant, acct, google, g_camp, g_adset, g_ad, prev_from,
            spend=prev_spend_google, conversion_value=prev_revenue_google,
            conversions="40", impressions=90000, clicks=4500,
        )
    if float(prev_spend_meta) > 0 or float(prev_revenue_meta) > 0:
        _insert_fact(
            db, tenant, acct, meta, m_camp, m_adset, m_ad, prev_from,
            spend=prev_spend_meta, conversion_value=prev_revenue_meta,
            conversions="25", impressions=70000, clicks=3500,
        )

    db.commit()
    return google, meta


def _seed_goal(db: Session, tenant: Tenant, date_from: date, date_to: date) -> Goal:
    """Seed one active Goal for the tenant."""
    goal = Goal(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Haziran ROAS Hedefi",
        metric="roas",
        target_value=3.5,
        period="month",
        period_start=str(date_from),
        period_end=str(date_to),
        channel_filter=None,
        is_active=True,
    )
    db.add(goal)
    db.commit()
    return goal


def _seed_insight(db: Session, tenant: Tenant, date_from: date) -> Insight:
    """Seed one Insight for the tenant."""
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="roas_drop",
        severity="warning",
        title="Google Ads ROAS düşüşü tespit edildi",
        body="ROAS geçen haftaya göre %15 geriledi.",
        metric="roas",
        channel="google_ads",
        period_start=date_from,
        period_end=date_from,
        status="new",
        score=0.8,
        data={},
    )
    db.add(ins)
    db.commit()
    return ins


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure helper unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeDelta:
    def test_positive_change(self) -> None:
        result = _compute_delta(110.0, 100.0)
        assert result == 10.0

    def test_negative_change(self) -> None:
        result = _compute_delta(80.0, 100.0)
        assert result == -20.0

    def test_zero_previous_returns_none(self) -> None:
        result = _compute_delta(50.0, 0.0)
        assert result is None

    def test_same_value_returns_zero(self) -> None:
        result = _compute_delta(100.0, 100.0)
        assert result == 0.0

    def test_rounding_to_one_decimal(self) -> None:
        result = _compute_delta(103.0, 100.0)
        assert result == 3.0

    def test_fractional_change_rounded(self) -> None:
        # 101 / 300 * 100 = 33.666... → 33.7
        result = _compute_delta(401.0, 300.0)
        assert result == pytest.approx(33.7, abs=0.05)


class TestComputeTotals:
    def test_empty_channel_data_returns_zeros(self) -> None:
        result = _compute_totals({})
        assert result["spend"] == 0.0
        assert result["revenue"] == 0.0
        assert result["conversions"] == 0.0
        assert result["roas"] == 0.0

    def test_single_channel(self) -> None:
        data = {
            "google_ads": {
                "label": "Google Ads",
                "spend": Decimal("1000"),
                "conversion_value": Decimal("4000"),
                "conversions": Decimal("20"),
                "clicks": Decimal("500"),
                "impressions": Decimal("10000"),
            }
        }
        result = _compute_totals(data)
        assert result["spend"] == pytest.approx(1000.0)
        assert result["revenue"] == pytest.approx(4000.0)
        assert result["roas"] == pytest.approx(4.0)

    def test_two_channels_summed(self) -> None:
        data = {
            "google_ads": {
                "label": "Google Ads",
                "spend": Decimal("5000"),
                "conversion_value": Decimal("20000"),
                "conversions": Decimal("50"),
                "clicks": Decimal("5000"),
                "impressions": Decimal("100000"),
            },
            "meta_ads": {
                "label": "Meta Ads",
                "spend": Decimal("3000"),
                "conversion_value": Decimal("9000"),
                "conversions": Decimal("30"),
                "clicks": Decimal("4000"),
                "impressions": Decimal("80000"),
            },
        }
        result = _compute_totals(data)
        assert result["spend"] == pytest.approx(8000.0)
        assert result["revenue"] == pytest.approx(29000.0)
        assert result["conversions"] == pytest.approx(80.0)
        # roas = 29000 / 8000 = 3.625
        assert result["roas"] == pytest.approx(3.625)

    def test_roas_zero_when_no_spend(self) -> None:
        data = {
            "ch": {
                "label": "CH",
                "spend": Decimal("0"),
                "conversion_value": Decimal("1000"),
                "conversions": Decimal("5"),
                "clicks": Decimal("100"),
                "impressions": Decimal("1000"),
            }
        }
        result = _compute_totals(data)
        assert result["roas"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. build_overview — service-level tests (with DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildOverview:
    _date_from = date(2026, 1, 1)
    _date_to = date(2026, 1, 30)  # 30-day window

    def test_totals_correct_two_channels(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        kpis = result["kpis"]
        # google: spend=5000, meta: spend=3000 → total=8000
        assert kpis["spend"] == pytest.approx(8000.0)
        # google: revenue=20000, meta: revenue=9000 → total=29000
        assert kpis["revenue"] == pytest.approx(29000.0)

    def test_roas_correct(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        # roas = 29000 / 8000 = 3.625
        assert result["kpis"]["roas"] == pytest.approx(3.625, abs=0.01)

    def test_channels_sorted_by_spend_desc(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        channels = result["channels"]
        assert len(channels) == 2
        # Google has 5000 spend, Meta has 3000 — google should be first
        assert channels[0]["channel"] == "google_ads"
        assert channels[1]["channel"] == "meta_ads"
        # Spend descending
        spends = [c["spend"] for c in channels]
        assert spends == sorted(spends, reverse=True)

    def test_share_pct_sums_to_approx_100(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        total_share = sum(c["share_pct"] for c in result["channels"])
        assert total_share == pytest.approx(100.0, abs=0.5)

    def test_mom_deltas_computed_with_previous_data(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to,
            prev_spend_google="4000",
            prev_spend_meta="2000",
            prev_revenue_google="16000",
            prev_revenue_meta="6000",
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        deltas = result["kpis"]["deltas"]
        # prev total spend = 6000, curr = 8000 → +33.3%
        assert deltas["spend_pct"] is not None
        assert deltas["spend_pct"] == pytest.approx(33.3, abs=0.2)
        # prev roas = 22000/6000 = 3.666, curr = 29000/8000 = 3.625
        # delta should be non-None
        assert deltas["roas_pct"] is not None

    def test_deltas_none_without_previous_data(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        deltas = result["kpis"]["deltas"]
        # No previous period data → all deltas None
        assert deltas["spend_pct"] is None
        assert deltas["revenue_pct"] is None
        assert deltas["roas_pct"] is None

    def test_goals_surface(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        _seed_goal(db_session, tenant, self._date_from, self._date_to)
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        assert len(result["goals"]) >= 1
        goal = result["goals"][0]
        assert goal["name"] == "Haziran ROAS Hedefi"
        assert goal["metric"] == "roas"
        assert goal["target_value"] == pytest.approx(3.5)
        assert "status" in goal

    def test_goal_pct_to_target_is_percent_scaled(self, db_session: Session) -> None:
        """Executive exposes pct_to_target on the 0-100+ PERCENT scale — the goal
        service's 0..1+ ratio multiplied by 100. Locks the ratio→percent
        conversion so the CMO progress bars never regress to the ~0% bug."""
        from ayaz.services.copilot_tools import _get_goal_progress

        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        _seed_goal(db_session, tenant, self._date_from, self._date_to)

        raw = _get_goal_progress(db_session, tenant.id)["goals"][0]
        ratio = raw["pct_to_target"] or 0.0

        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        exec_goal = result["goals"][0]

        assert exec_goal["pct_to_target"] == pytest.approx(round(ratio * 100, 1))

    def test_insights_surface(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        _seed_insight(db_session, tenant, self._date_from)
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        assert len(result["insights"]) >= 1
        insight = result["insights"][0]
        assert insight["severity"] == "warning"
        assert "ROAS" in insight["title"] or "roas" in insight["title"].lower()
        assert insight["channel"] == "google_ads"

    def test_headline_contains_numbers(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        headline = result["headline"]
        assert "₺" in headline
        assert "ROAS" in headline or "roas" in headline.lower()
        assert "Google" in headline

    def test_headline_includes_mom_direction_when_available(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to,
            prev_spend_google="4000",
            prev_revenue_google="12000",
        )
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        headline = result["headline"]
        # Should mention increase/decrease direction
        assert "arttı" in headline or "azaldı" in headline


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Empty warehouse tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyWarehouse:
    _date_from = date(2026, 1, 1)
    _date_to = date(2026, 1, 30)

    def test_empty_warehouse_kpis_are_zero(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        kpis = result["kpis"]
        assert kpis["spend"] == 0.0
        assert kpis["revenue"] == 0.0
        assert kpis["roas"] == 0.0
        assert kpis["conversions"] == 0.0

    def test_empty_warehouse_channels_empty(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant 2")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        assert result["channels"] == []

    def test_empty_warehouse_goals_empty(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant 3")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        assert result["goals"] == []

    def test_empty_warehouse_insights_empty(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant 4")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        assert result["insights"] == []

    def test_empty_warehouse_headline_sensible(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant 5")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        headline = result["headline"]
        assert "veri" in headline.lower() or "yeterli" in headline.lower()

    def test_empty_warehouse_deltas_all_none(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Tenant 6")
        result = build_overview(db_session, tenant.id, self._date_from, self._date_to)
        deltas = result["kpis"]["deltas"]
        assert deltas["spend_pct"] is None
        assert deltas["revenue_pct"] is None
        assert deltas["roas_pct"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutiveOverviewEndpoint:
    _date_from = date(2026, 1, 1)
    _date_to = date(2026, 1, 30)

    def _get_tenant_id(self) -> uuid.UUID:
        return _test_app.dependency_overrides[get_current_membership]().tenant_id

    def test_happy_path_200(self, client: TestClient, db_session: Session) -> None:
        tenant_id = self._get_tenant_id()
        tenant = db_session.get(Tenant, tenant_id)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        resp = client.get(
            "/api/v1/executive/overview",
            params={
                "date_from": str(self._date_from),
                "date_to": str(self._date_to),
            },
        )
        assert resp.status_code == 200

    def test_response_shape_correct(self, client: TestClient, db_session: Session) -> None:
        resp = client.get(
            "/api/v1/executive/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"period", "kpis", "channels", "goals", "insights", "headline"}
        assert set(body["period"].keys()) >= {
            "date_from", "date_to", "prev_date_from", "prev_date_to"
        }
        assert set(body["kpis"].keys()) >= {
            "spend", "revenue", "conversions", "clicks", "roas", "deltas"
        }
        assert set(body["kpis"]["deltas"].keys()) >= {
            "spend_pct", "revenue_pct", "conversions_pct", "roas_pct"
        }
        assert isinstance(body["channels"], list)
        assert isinstance(body["goals"], list)
        assert isinstance(body["insights"], list)
        assert isinstance(body["headline"], str)

    def test_default_date_range(self, client: TestClient) -> None:
        """No date params → defaults to last 30 days."""
        today = datetime.now(timezone.utc).date()
        expected_date_to = today.isoformat()
        expected_date_from = (today - timedelta(days=29)).isoformat()

        resp = client.get("/api/v1/executive/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"]["date_to"] == expected_date_to
        assert body["period"]["date_from"] == expected_date_from

    def test_date_from_after_date_to_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/executive/overview",
            params={"date_from": "2026-01-30", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get(
            "/api/v1/executive/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code in (401, 403)

    def test_channel_rows_have_expected_fields(
        self, client: TestClient, db_session: Session
    ) -> None:
        tenant_id = self._get_tenant_id()
        tenant = db_session.get(Tenant, tenant_id)
        _seed_two_channel_warehouse(
            db_session, tenant, self._date_from, self._date_to
        )
        resp = client.get(
            "/api/v1/executive/overview",
            params={"date_from": str(self._date_from), "date_to": str(self._date_to)},
        )
        assert resp.status_code == 200
        channels = resp.json()["channels"]
        assert len(channels) == 2
        for ch in channels:
            assert set(ch.keys()) >= {"channel", "label", "spend", "revenue", "roas", "share_pct"}
