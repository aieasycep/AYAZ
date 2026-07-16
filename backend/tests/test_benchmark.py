"""Self-contained tests for Sektör Kıyaslama (Benchmark).

Coverage
--------
1. Pure position logic (no DB)
   - _classify_position: higher_is_better (below/within/above thresholds)
   - _classify_position: lower_is_better  (cpc / cpm — inverted logic)

2. build_benchmark — service-level tests (with DB)
   - empty warehouse → zeros, "weak" positions, graceful headline
   - seeded high-CTR / high-ROAS data → "strong" positions
   - metrics returned in canonical order: ctr, cpc, roas, conversion_rate, cpm
   - channels sorted by spend desc
   - summary_counts totals match individual metric positions
   - div-by-zero guards (all-zero impressions / clicks)
   - per-channel roas_position and ctr_position reflect channel data

3. HTTP endpoint
   - 200 happy path — correct response shape
   - default date range (date_to today, date_from today-29d)
   - date_from > date_to → 422
   - missing auth → 401 or 403
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
from ayaz.api.v1 import benchmark as benchmark_module
from ayaz.services.auth import hash_password
from ayaz.services.benchmark import (
    _METRIC_ORDER,
    _REFERENCE_RANGES,
    _build_insights,
    _classify_position,
    build_benchmark,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Benchmark Test App")
_test_app.include_router(benchmark_module.router, prefix="/api/v1")


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
        name="Benchmark Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="bench_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Benchmark Test User",
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


def _make_tenant(db: Session, name: str = "Bench Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=Platform.sample, external_account_id="BENCH-ACC-001",
        display_name="Bench Account", vault_secret_ref="",
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


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel, name: str = "Camp") -> DimCampaign:
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
        # cost_base_ccy and conv_value_base_ccy must be set because
        # _aggregate_by_channel_raw uses COALESCE(cost_base_ccy, cost_raw)
        cost_base_ccy=Decimal(spend),
        conv_value_base_ccy=Decimal(conversion_value),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _seed_strong_performer(
    db: Session,
    tenant: Tenant,
    d: date,
) -> tuple[DimChannel, DimChannel]:
    """Seed two channels with metrics that yield strong CTR and ROAS.

    Google: spend=1000, impressions=20000, clicks=600, conversions=30,
            conversion_value=8000
    Meta:   spend=2000, impressions=50000, clicks=700, conversions=20,
            conversion_value=12000

    Account totals:
        impressions=70000, clicks=1300, spend=3000, conversions=50,
        conv_value=20000
        ctr  = 1300/70000*100 = 1.857%  → average
        cpc  = 3000/1300 = 2.308₺       → strong (< 2 is strong? no: 2.308 >= 2.0 but <= 8.0 → average)
        roas = 20000/3000 = 6.667x       → strong (> 5.0)
        cr   = 50/1300*100 = 3.846%     → strong (> 4.0? no: 3.846 < 4.0 → average)
        cpm  = 3000/70000*1000 = 42.857₺ → average (30 ≤ 42.857 ≤ 90)

    We deliberately choose data that makes roas clearly "strong".
    """
    acct = _make_connected_account(db, tenant)
    google = _make_channel(db, "google_ads_bench", "Google Ads")
    meta = _make_channel(db, "meta_ads_bench", "Meta Ads")

    g_camp = _make_campaign(db, tenant, google)
    g_adset = _make_adset(db, tenant, g_camp)
    g_ad = _make_ad(db, tenant, g_adset)

    m_camp = _make_campaign(db, tenant, meta)
    m_adset = _make_adset(db, tenant, m_camp)
    m_ad = _make_ad(db, tenant, m_adset)

    _insert_fact(
        db, tenant, acct, google, g_camp, g_adset, g_ad, d,
        spend="1000", conversion_value="8000", conversions="30",
        impressions=20000, clicks=600,
    )
    _insert_fact(
        db, tenant, acct, meta, m_camp, m_adset, m_ad, d,
        spend="2000", conversion_value="12000", conversions="20",
        impressions=50000, clicks=700,
    )
    db.commit()
    return google, meta


def _seed_high_ctr_channel(
    db: Session,
    tenant: Tenant,
    d: date,
) -> DimChannel:
    """Seed a channel with CTR = 5% (> 2.5 → strong)."""
    acct = _make_connected_account(db, tenant)
    ch = _make_channel(db, "high_ctr_ch", "High CTR Channel")
    camp = _make_campaign(db, tenant, ch)
    adset = _make_adset(db, tenant, camp)
    ad = _make_ad(db, tenant, adset)

    _insert_fact(
        db, tenant, acct, ch, camp, adset, ad, d,
        spend="500", conversion_value="3000", conversions="10",
        # 5000 clicks out of 100000 impressions = 5% CTR
        impressions=100000, clicks=5000,
    )
    db.commit()
    return ch


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure position logic unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyPosition:
    """Tests for _classify_position — covers both higher_is_better directions."""

    # ── higher_is_better = True (ctr, roas, conversion_rate) ──────────────

    def test_higher_is_better_below_low_is_weak(self) -> None:
        assert _classify_position(0.5, low=1.0, high=4.0, higher_is_better=True) == "weak"

    def test_higher_is_better_at_low_boundary_is_average(self) -> None:
        assert _classify_position(1.0, low=1.0, high=4.0, higher_is_better=True) == "average"

    def test_higher_is_better_within_range_is_average(self) -> None:
        assert _classify_position(2.5, low=1.0, high=4.0, higher_is_better=True) == "average"

    def test_higher_is_better_at_high_boundary_is_average(self) -> None:
        assert _classify_position(4.0, low=1.0, high=4.0, higher_is_better=True) == "average"

    def test_higher_is_better_above_high_is_strong(self) -> None:
        assert _classify_position(5.5, low=1.0, high=4.0, higher_is_better=True) == "strong"

    # ── higher_is_better = False (cpc, cpm) ───────────────────────────────

    def test_lower_is_better_below_low_is_strong(self) -> None:
        # value < low → cost cheaper than "good" threshold → strong
        assert _classify_position(1.5, low=2.0, high=8.0, higher_is_better=False) == "strong"

    def test_lower_is_better_at_low_boundary_is_average(self) -> None:
        assert _classify_position(2.0, low=2.0, high=8.0, higher_is_better=False) == "average"

    def test_lower_is_better_within_range_is_average(self) -> None:
        assert _classify_position(5.0, low=2.0, high=8.0, higher_is_better=False) == "average"

    def test_lower_is_better_at_high_boundary_is_average(self) -> None:
        assert _classify_position(8.0, low=2.0, high=8.0, higher_is_better=False) == "average"

    def test_lower_is_better_above_high_is_weak(self) -> None:
        # value > high → cost more expensive than "poor" threshold → weak
        assert _classify_position(10.0, low=2.0, high=8.0, higher_is_better=False) == "weak"


# ═══════════════════════════════════════════════════════════════════════════════
# 1b. Insight generation unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildInsights:
    """Deterministic cross-metric insight rules."""

    def _all_average(self) -> tuple[dict, dict]:
        # Values that sit within every reference band → all "average".
        values = {"ctr": 1.5, "cpc": 4.0, "roas": 3.5, "conversion_rate": 2.5, "cpm": 60.0}
        positions = {k: "average" for k in _METRIC_ORDER}
        return values, positions

    def test_biggest_opportunity_picks_largest_gap(self) -> None:
        values, positions = self._all_average()
        # roas far below its low threshold (2.0) → weak, biggest opportunity.
        values["roas"] = 0.5
        positions["roas"] = "weak"
        insights = _build_insights(values, positions, [])
        assert insights, "expected at least one insight"
        top = insights[0]
        assert top["severity"] == "opportunity"
        assert "Getiri" in top["title"] or "ROAS" in top["title"]

    def test_traffic_but_no_conversion_diagnostic(self) -> None:
        values, positions = self._all_average()
        positions["ctr"] = "strong"
        positions["conversion_rate"] = "weak"
        values["conversion_rate"] = 0.4
        insights = _build_insights(values, positions, [])
        assert any(i["severity"] == "diagnostic" for i in insights)
        diag = next(i for i in insights if i["severity"] == "diagnostic")
        assert "dönüş" in diag["title"].lower()

    def test_channel_reallocation_when_roas_gap_large(self) -> None:
        values, positions = self._all_average()
        channels = [
            {"label": "Google Ads", "roas": 6.0},
            {"label": "Meta Ads", "roas": 1.5},
        ]
        insights = _build_insights(values, positions, channels)
        strength = [i for i in insights if i["severity"] == "strength"]
        assert strength, "expected a channel-reallocation insight"
        assert "Google Ads" in strength[0]["detail"]
        assert "Meta Ads" in strength[0]["detail"]

    def test_no_insights_when_all_average_single_channel(self) -> None:
        values, positions = self._all_average()
        # One channel → no reallocation; all average → no opportunity/diagnostic.
        insights = _build_insights(values, positions, [{"label": "Google", "roas": 3.5}])
        assert insights == []

    def test_capped_at_three(self) -> None:
        values, positions = self._all_average()
        for k in _METRIC_ORDER:
            positions[k] = "weak"
            values[k] = 0.1
        channels = [
            {"label": "A", "roas": 8.0},
            {"label": "B", "roas": 1.0},
        ]
        insights = _build_insights(values, positions, channels)
        assert len(insights) <= 3


# ═══════════════════════════════════════════════════════════════════════════════
# 2. build_benchmark — service-level tests (with DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildBenchmark:
    _date_from = date(2026, 1, 1)
    _date_to = date(2026, 1, 30)

    def test_empty_warehouse_returns_zero_values(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Bench")
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        for m in result["metrics"]:
            assert m["your_value"] == 0.0, f"{m['key']} should be 0 when no data"

    def test_empty_warehouse_positions_weak(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Bench 2")
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        for m in result["metrics"]:
            assert m["position"] == "weak", f"{m['key']} should be weak when no data"

    def test_empty_warehouse_graceful_headline(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Bench 3")
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert "yeterli" in result["headline"].lower() or "veri" in result["headline"].lower()

    def test_empty_warehouse_channels_empty(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Bench 4")
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert result["channels"] == []

    def test_metrics_in_canonical_order(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        keys = [m["key"] for m in result["metrics"]]
        assert keys == _METRIC_ORDER

    def test_high_roas_data_yields_strong_position(self, db_session: Session) -> None:
        """
        Seeded: spend=3000, conversion_value=20000 → roas=6.67 > 5.0 → strong.
        """
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        roas_metric = next(m for m in result["metrics"] if m["key"] == "roas")
        assert roas_metric["position"] == "strong"
        assert roas_metric["your_value"] == pytest.approx(6.667, abs=0.01)

    def test_high_ctr_data_yields_strong_position(self, db_session: Session) -> None:
        """
        Seeded: 5000 clicks / 100000 impressions = 5% CTR > 2.5 → strong.
        """
        tenant = _make_tenant(db_session)
        _seed_high_ctr_channel(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        ctr_metric = next(m for m in result["metrics"] if m["key"] == "ctr")
        assert ctr_metric["position"] == "strong"
        assert ctr_metric["your_value"] == pytest.approx(5.0, abs=0.01)

    def test_channels_sorted_by_spend_desc(self, db_session: Session) -> None:
        """
        google spend=1000, meta spend=2000 → meta should appear first.
        """
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert len(result["channels"]) == 2
        # Meta has higher spend (2000 vs 1000) → meta first
        assert result["channels"][0]["channel"] == "meta_ads_bench"
        assert result["channels"][1]["channel"] == "google_ads_bench"

    def test_summary_counts_match_metric_positions(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        counts = result["summary_counts"]
        # Recount from the metrics list
        expected = {"strong": 0, "average": 0, "weak": 0}
        for m in result["metrics"]:
            expected[m["position"]] += 1
        assert counts == expected

    def test_channel_roas_position_strong(self, db_session: Session) -> None:
        """
        Google: 8000/1000 = 8x > 5.0 → strong roas_position.
        """
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        google_ch = next(c for c in result["channels"] if c["channel"] == "google_ads_bench")
        assert google_ch["roas_position"] == "strong"
        assert google_ch["roas"] == pytest.approx(8.0)

    def test_summary_counts_total_equals_five(self, db_session: Session) -> None:
        """summary_counts values must always sum to exactly 5 (one per metric)."""
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        counts = result["summary_counts"]
        assert counts["strong"] + counts["average"] + counts["weak"] == len(_METRIC_ORDER)

    def test_vertical_is_eticaret(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert result["vertical"] == "E-ticaret"

    def test_period_matches_input(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert result["period"]["date_from"] == str(self._date_from)
        assert result["period"]["date_to"] == str(self._date_to)

    def test_result_exposes_insights_list(self, db_session: Session) -> None:
        """build_benchmark always returns an ``insights`` list (empty when no data)."""
        tenant = _make_tenant(db_session, "Insights Bench")
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        assert "insights" in result
        assert isinstance(result["insights"], list)
        # No data → no insights.
        assert result["insights"] == []

    def test_metric_ref_ranges_match_constants(self, db_session: Session) -> None:
        """Each metric row must expose ref_low/mid/high matching _REFERENCE_RANGES."""
        tenant = _make_tenant(db_session)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        for m in result["metrics"]:
            ref = _REFERENCE_RANGES[m["key"]]
            assert m["ref_low"] == ref["low"]
            assert m["ref_mid"] == ref["mid"]
            assert m["ref_high"] == ref["high"]
            assert m["higher_is_better"] == ref["higher_is_better"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2b. build_benchmark — kaynak-tipi mutabakatı (ad + analytics) regression tests
# ═══════════════════════════════════════════════════════════════════════════════


def _seed_ad_and_analytics_warehouse(
    db: Session,
    tenant: Tenant,
    d: date,
) -> tuple[DimChannel, DimChannel, DimChannel]:
    """Seed google_ads (ad) + ga4 (analytics) + search_console (analytics).

    google_ads:      spend=1000, impressions=20000, clicks=500,
                      conversions=20, conversion_value=4000
                      -> ad CTR = 500/20000*100 = 2.5%, ad CVR = 20/500*100 = 4.0%
                      -> ad-only ROAS = 4000/1000 = 4.0
    ga4:              spend=0, clicks=0 (GA4 measures sessions, not clicks),
                      conversions=100, conversion_value=50000
                      (deliberately huge — would massively distort any metric
                      it leaked into if channel isolation were broken)
    search_console:   spend=0, clicks=5000 (real ORGANIC clicks),
                      impressions=200000, conversions=0
                      (deliberately huge clicks — would dilute ad CTR/CVR if
                      blended into ad-only denominators)
    """
    acct = _make_connected_account(db, tenant)

    google = _make_channel(db, "google_ads", "Google Ads")
    g_camp = _make_campaign(db, tenant, google)
    g_adset = _make_adset(db, tenant, g_camp)
    g_ad = _make_ad(db, tenant, g_adset)
    _insert_fact(
        db, tenant, acct, google, g_camp, g_adset, g_ad, d,
        spend="1000", conversion_value="4000", conversions="20",
        impressions=20000, clicks=500,
    )

    ga4 = _make_channel(db, "ga4", "Google Analytics 4")
    a_camp = _make_campaign(db, tenant, ga4)
    a_adset = _make_adset(db, tenant, a_camp)
    a_ad = _make_ad(db, tenant, a_adset)
    _insert_fact(
        db, tenant, acct, ga4, a_camp, a_adset, a_ad, d,
        spend="0", conversion_value="50000", conversions="100",
        impressions=0, clicks=0,
    )

    gsc = _make_channel(db, "search_console", "Search Console")
    s_camp = _make_campaign(db, tenant, gsc)
    s_adset = _make_adset(db, tenant, s_camp)
    s_ad = _make_ad(db, tenant, s_adset)
    _insert_fact(
        db, tenant, acct, gsc, s_camp, s_adset, s_ad, d,
        spend="0", conversion_value="0", conversions="0",
        impressions=200000, clicks=5000,
    )

    db.commit()
    return google, ga4, gsc


class TestBuildBenchmarkSourceTypeSplit:
    _date_from = date(2026, 3, 1)
    _date_to = date(2026, 3, 1)

    def test_roas_is_ad_only_spend_with_ga4_revenue_not_double_counted(
        self, db_session: Session
    ) -> None:
        """Historically-buggy ROAS would be (4000+50000)/1000 = 54.0. Correct
        blended ROAS = ga4_revenue / ad_spend = 50000/1000 = 50.0 (GA4 wins as
        source of truth over the ad platform's own 4000)."""
        tenant = _make_tenant(db_session)
        _seed_ad_and_analytics_warehouse(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        roas_metric = next(m for m in result["metrics"] if m["key"] == "roas")
        assert roas_metric["your_value"] == pytest.approx(50.0)
        assert roas_metric["your_value"] != pytest.approx(54.0)

    def test_ctr_is_ad_only_not_diluted_by_organic_search_console_clicks(
        self, db_session: Session
    ) -> None:
        """Search Console's 5000 organic clicks / 200000 impressions must NOT
        blend into the ad CTR. Ad-only CTR = 500/20000*100 = 2.5%."""
        tenant = _make_tenant(db_session)
        _seed_ad_and_analytics_warehouse(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        ctr_metric = next(m for m in result["metrics"] if m["key"] == "ctr")
        assert ctr_metric["your_value"] == pytest.approx(2.5, abs=0.01)

    def test_conversion_rate_uses_ga4_conversions_over_ad_clicks(
        self, db_session: Session
    ) -> None:
        """Dönüşüm Oranı numerator = source-of-truth conversions (GA4's 100,
        since it's non-zero) ÷ ad-only clicks (500) = 20.0%. NOT (20+100)/500
        = 24% (blind sum) and NOT 20/500=4% (ignoring GA4 entirely)."""
        tenant = _make_tenant(db_session)
        _seed_ad_and_analytics_warehouse(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        cr_metric = next(m for m in result["metrics"] if m["key"] == "conversion_rate")
        assert cr_metric["your_value"] == pytest.approx(20.0)

    def test_channel_rows_exclude_analytics_channels(self, db_session: Session) -> None:
        """GA4 and Search Console must never appear in the per-channel ad
        benchmark comparison table — they have no ad spend and would show a
        misleading 0-ROAS/0-CTR 'weak' row."""
        tenant = _make_tenant(db_session)
        _seed_ad_and_analytics_warehouse(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        channel_keys = {c["channel"] for c in result["channels"]}
        assert channel_keys == {"google_ads"}
        assert "ga4" not in channel_keys
        assert "search_console" not in channel_keys

    def test_has_data_based_on_ad_only_spend(self, db_session: Session) -> None:
        """A tenant with ONLY GA4 connected (no ad spend at all) has no ad
        benchmark to compute — has_data must be False, not True from GA4's
        non-zero conversion_value."""
        tenant = _make_tenant(db_session, "GA4 Only Tenant")
        acct = _make_connected_account(db_session, tenant)
        ga4 = _make_channel(db_session, "ga4", "Google Analytics 4")
        camp = _make_campaign(db_session, tenant, ga4)
        adset = _make_adset(db_session, tenant, camp)
        ad = _make_ad(db_session, tenant, adset)
        _insert_fact(
            db_session, tenant, acct, ga4, camp, adset, ad, self._date_from,
            spend="0", conversion_value="10000", conversions="50",
            impressions=0, clicks=0,
        )
        db_session.commit()

        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        for m in result["metrics"]:
            assert m["position"] == "weak"
        assert result["channels"] == []

    def test_ad_only_tenant_unaffected_by_fix(self, db_session: Session) -> None:
        """Regression guard: an ad-only tenant (no analytics channel at all,
        via the pre-existing _seed_strong_performer fixture) must produce
        IDENTICAL results to before this fix."""
        tenant = _make_tenant(db_session)
        _seed_strong_performer(db_session, tenant, self._date_from)
        result = build_benchmark(db_session, tenant.id, self._date_from, self._date_to)
        roas_metric = next(m for m in result["metrics"] if m["key"] == "roas")
        assert roas_metric["your_value"] == pytest.approx(6.667, abs=0.01)
        assert roas_metric["position"] == "strong"
        assert len(result["channels"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBenchmarkEndpoint:
    _date_from = date(2026, 1, 1)
    _date_to = date(2026, 1, 30)

    def _get_tenant_id(self) -> uuid.UUID:
        return _test_app.dependency_overrides[get_current_membership]().tenant_id

    def test_happy_path_200(self, client: TestClient, db_session: Session) -> None:
        resp = client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": str(self._date_from), "date_to": str(self._date_to)},
        )
        assert resp.status_code == 200

    def test_response_shape_correct(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {
            "period", "vertical", "metrics", "channels", "headline", "summary_counts"
        }
        assert set(body["period"].keys()) >= {"date_from", "date_to"}
        assert isinstance(body["metrics"], list)
        assert len(body["metrics"]) == len(_METRIC_ORDER)
        assert isinstance(body["channels"], list)
        assert isinstance(body["headline"], str)
        counts = body["summary_counts"]
        assert set(counts.keys()) >= {"strong", "average", "weak"}
        # Verify each metric has the required fields
        for m in body["metrics"]:
            assert set(m.keys()) >= {
                "key", "label", "unit", "your_value",
                "ref_low", "ref_mid", "ref_high",
                "higher_is_better", "position", "verdict",
            }
            assert m["position"] in ("strong", "average", "weak")

    def test_default_date_range(self, client: TestClient) -> None:
        """No date params → defaults to last 30 days."""
        today = datetime.now(timezone.utc).date()
        expected_date_to = today.isoformat()
        expected_date_from = (today - timedelta(days=29)).isoformat()

        resp = client.get("/api/v1/benchmark/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"]["date_to"] == expected_date_to
        assert body["period"]["date_from"] == expected_date_from

    def test_date_from_after_date_to_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": "2026-01-30", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code in (401, 403)

    def test_metrics_order_in_response(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code == 200
        keys = [m["key"] for m in resp.json()["metrics"]]
        assert keys == _METRIC_ORDER

    def test_seeded_strong_roas_reflected_in_response(
        self, client: TestClient, db_session: Session
    ) -> None:
        tenant_id = self._get_tenant_id()
        tenant = db_session.get(Tenant, tenant_id)
        _seed_strong_performer(db_session, tenant, self._date_from)

        resp = client.get(
            "/api/v1/benchmark/overview",
            params={"date_from": str(self._date_from), "date_to": str(self._date_to)},
        )
        assert resp.status_code == 200
        body = resp.json()
        roas_metric = next(m for m in body["metrics"] if m["key"] == "roas")
        assert roas_metric["position"] == "strong"
