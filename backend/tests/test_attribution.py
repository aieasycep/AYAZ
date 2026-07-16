"""Tests for the attribution (kaynak-mutabakatı) service and API endpoint.

Strategy
--------
Part 1 — Pure/service-level tests for ``build_attribution_summary`` (DB-backed,
  no HTTP). Validates:
  - ad-only totals (platform_claimed_*) come exclusively from 'ad' channels
  - analytics-only totals (ga4_*) come exclusively from 'analytics' channels
  - inflation_factor math + None-guard when GA4 is absent/zero
  - blended_roas = ga4_revenue / ad_spend, with NO ad-only fallback
  - per-channel breakdown shape + ordering (spend descending)
  - tenant isolation (a second tenant's data never leaks in)

Part 2 — HTTP endpoint tests for GET /api/v1/attribution/summary.
  - 200 happy path + response shape
  - auth required (401 without membership override)
  - days query param drives the lookback window
  - tenant isolation via the endpoint
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.main import app
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
from ayaz.services.attribution import build_attribution_summary
from ayaz.services.auth import hash_password

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Attribution Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="USD", country="US", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "attr@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(), email=email,
        hashed_password=hash_password("test1234"), full_name="Attr User",
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


def _make_connected_account(
    db: Session, tenant: Tenant, platform: Platform = Platform.google_ads
) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=platform, external_account_id=str(uuid.uuid4()),
        display_name=f"{platform.value} test", vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str = "Camp"
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant.id,
        channel_id=channel.id, external_id=str(uuid.uuid4()), name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant.id,
        campaign_id=campaign.id, external_id=str(uuid.uuid4()), name="AdSet",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant.id,
        ad_set_id=adset.id, external_id=str(uuid.uuid4()), name="Ad",
    )
    db.add(ad)
    db.flush()
    return ad


def _ensure_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week,
        day_of_week=d.weekday(), is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


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
    impressions: int = 0,
    clicks: int = 0,
    spend: str = "0",
    conversions: str = "0",
    cv: str = "0",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(spend)
    fact = FactDailyMetrics(
        id=uuid.uuid4(), tenant_id=tenant.id, connected_account_id=acct.id,
        channel_id=channel.id, campaign_id=campaign.id, adset_id=adset.id,
        ad_id=ad.id, date_key=d, impressions=impressions, clicks=clicks,
        cost_raw=cost, cost_ccy="USD",
        conversions=Decimal(conversions), conversion_value_raw=Decimal(cv),
        conversion_value_ccy="USD",
        cost_base_ccy=cost, conv_value_base_ccy=Decimal(cv),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


def _seed_mixed_warehouse(db: Session, tenant: Tenant, d: date) -> None:
    """google_ads (ad, spend=1000, conv=20, cv=4000) + ga4 (analytics,
    conv=15, cv=3000, spend=0), both on date ``d``.

    The GA4 campaign is named ``"Paid Search"`` — a member of
    ``PAID_CHANNEL_GROUPS`` — so in this fixture ``ga4_paid_* == ga4_*``
    (single, entirely-paid GA4 channel group). This keeps the pre-existing
    inflation_factor / blended_roas assertions meaningful under the new
    paid-vs-total split (see ``TestGa4PaidVsTotalSplit`` for a fixture that
    actually mixes paid + organic GA4 rows).
    """
    acct = _make_connected_account(db, tenant, Platform.google_ads)
    ch_ads = _make_channel(db, "google_ads")
    camp_ads = _make_campaign(db, tenant, ch_ads)
    adset_ads = _make_adset(db, tenant, camp_ads)
    ad_ads = _make_ad(db, tenant, adset_ads)

    ch_ga4 = _make_channel(db, "ga4")
    camp_ga4 = _make_campaign(db, tenant, ch_ga4, name="Paid Search")
    adset_ga4 = _make_adset(db, tenant, camp_ga4)
    ad_ga4 = _make_ad(db, tenant, adset_ga4)

    _insert_fact(
        db, tenant, acct, ch_ads, camp_ads, adset_ads, ad_ads, d,
        impressions=10000, clicks=500, spend="1000.00",
        conversions="20", cv="4000.00",
    )
    _insert_fact(
        db, tenant, acct, ch_ga4, camp_ga4, adset_ga4, ad_ga4, d,
        impressions=0, clicks=0, spend="0",
        conversions="15", cv="3000.00",
    )
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1 — Service-level tests (DB-backed, no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildAttributionSummary:
    _d = date(2024, 6, 1)

    def test_platform_claimed_is_ad_only(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["platform_claimed_conversions"] == pytest.approx(20.0)
        assert result["platform_claimed_revenue"] == pytest.approx(4000.0)

    def test_ga4_is_analytics_only(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["ga4_conversions"] == pytest.approx(15.0)
        assert result["ga4_revenue"] == pytest.approx(3000.0)

    def test_inflation_factor_correct(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        # 20 / 15 = 1.333...
        assert result["inflation_factor"] == pytest.approx(20 / 15, rel=1e-4)

    def test_inflation_factor_none_when_no_ga4(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Ad Only Tenant")
        acct = _make_connected_account(db_session, tenant, Platform.google_ads)
        ch = _make_channel(db_session, "google_ads")
        camp = _make_campaign(db_session, tenant, ch)
        adset = _make_adset(db_session, tenant, camp)
        ad = _make_ad(db_session, tenant, adset)
        _insert_fact(
            db_session, tenant, acct, ch, camp, adset, ad, self._d,
            spend="500.00", conversions="10", cv="2000.00",
        )
        db_session.commit()

        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["inflation_factor"] is None
        assert result["ga4_conversions"] == pytest.approx(0.0)

    def test_ad_spend_excludes_analytics(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["ad_spend"] == pytest.approx(1000.0)

    def test_blended_roas_uses_ga4_revenue_over_ad_spend(
        self, db_session: Session
    ) -> None:
        """blended_roas = ga4_revenue / ad_spend = 3000/1000 = 3.0 — NOT the
        blind (4000+3000)/1000 = 7.0 that the pre-fix panel would compute."""
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["blended_roas"] == pytest.approx(3.0)
        assert result["blended_roas"] != pytest.approx(7.0)

    def test_blended_roas_zero_when_no_ga4_no_fallback(
        self, db_session: Session
    ) -> None:
        """Unlike the dashboard's headline ROAS, this endpoint's blended_roas
        must NOT fall back to ad revenue when GA4 is absent — it should be
        honestly 0, signalling 'no verified attribution data available'."""
        tenant = _make_tenant(db_session, "Ad Only Tenant 2")
        acct = _make_connected_account(db_session, tenant, Platform.google_ads)
        ch = _make_channel(db_session, "google_ads")
        camp = _make_campaign(db_session, tenant, ch)
        adset = _make_adset(db_session, tenant, camp)
        ad = _make_ad(db_session, tenant, adset)
        _insert_fact(
            db_session, tenant, acct, ch, camp, adset, ad, self._d,
            spend="500.00", conversions="10", cv="2000.00",
        )
        db_session.commit()

        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["blended_roas"] == 0.0

    def test_channel_breakdown_shape_and_ordering(self, db_session: Session) -> None:
        """Channels ordered by spend descending; google_ads (spend=1000)
        before ga4 (spend=0)."""
        tenant = _make_tenant(db_session)
        _seed_mixed_warehouse(db_session, tenant, self._d)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        channels = result["channels"]
        assert len(channels) == 2
        assert channels[0]["key"] == "google_ads"
        assert channels[0]["source_type"] == "ad"
        assert channels[0]["spend"] == pytest.approx(1000.0)
        assert channels[0]["roas"] == pytest.approx(4.0)  # 4000/1000
        assert channels[1]["key"] == "ga4"
        assert channels[1]["source_type"] == "analytics"
        assert channels[1]["spend"] == pytest.approx(0.0)
        assert channels[1]["roas"] == pytest.approx(0.0)  # spend=0 guard

    def test_empty_warehouse_all_zero_no_crash(self, db_session: Session) -> None:
        """Scenario (c) — GA4-less (fully empty) tenant: existing fields keep
        their pre-fix defaults, and every new field also has a sane default."""
        tenant = _make_tenant(db_session, "Empty Attribution Tenant")
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["platform_claimed_conversions"] == 0.0
        assert result["ga4_conversions"] == 0.0
        assert result["inflation_factor"] is None
        assert result["blended_roas"] == 0.0
        assert result["channels"] == []
        # New fields — geriye uyumlu defaults.
        assert result["ga4_paid_conversions"] == 0.0
        assert result["ga4_paid_revenue"] == 0.0
        assert result["mer"] == 0.0
        assert result["data_quality"]["ga4_connected"] is False
        assert result["data_quality"]["ga4_paid_tracked"] is False
        assert result["data_quality"]["note"] is None

    def test_tenant_isolation(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")
        _seed_mixed_warehouse(db_session, tenant_a, self._d)

        # Tenant B: distinct huge numbers on a distinct channel key.
        acct_b = _make_connected_account(db_session, tenant_b, Platform.meta_ads)
        ch_b = _make_channel(db_session, "meta_ads")
        camp_b = _make_campaign(db_session, tenant_b, ch_b)
        adset_b = _make_adset(db_session, tenant_b, camp_b)
        ad_b = _make_ad(db_session, tenant_b, adset_b)
        _insert_fact(
            db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b, self._d,
            spend="999999", conversions="999999", cv="999999",
        )
        db_session.commit()

        result_a = build_attribution_summary(db_session, tenant_a.id, self._d, self._d)
        assert result_a["platform_claimed_conversions"] == pytest.approx(20.0)
        assert result_a["ad_spend"] == pytest.approx(1000.0)
        assert len(result_a["channels"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# GA4 TOPLAM vs GA4 ÜCRETLİ split — apples-to-apples reconciliation
# ═══════════════════════════════════════════════════════════════════════════════


class TestGa4PaidVsTotalSplit:
    """Covers the second elma-armut trap: GA4's own total (all channel
    groups — organic, direct, paid, ...) is not directly comparable to what
    an ad platform claims. Only the GA4 rows tagged with a paid channel
    group (``PAID_CHANNEL_GROUPS``) are apples-to-apples."""

    _d = date(2024, 6, 1)

    def _seed_paid_plus_organic_ga4(self, db: Session, tenant: Tenant) -> None:
        """google_ads (ad, spend=1000, conv=50, cv=5000) + GA4 split across
        two channel groups on the same day:
          - "Paid Search" (paid):    conv=30, cv=3000
          - "Organic Search" (not paid): conv=70, cv=7000
        GA4 TOTAL: conv=100, cv=10000. GA4 PAID: conv=30, cv=3000.
        """
        acct = _make_connected_account(db, tenant, Platform.google_ads)
        ch_ads = _make_channel(db, "google_ads")
        camp_ads = _make_campaign(db, tenant, ch_ads)
        adset_ads = _make_adset(db, tenant, camp_ads)
        ad_ads = _make_ad(db, tenant, adset_ads)
        _insert_fact(
            db, tenant, acct, ch_ads, camp_ads, adset_ads, ad_ads, self._d,
            impressions=20000, clicks=1000, spend="1000.00",
            conversions="50", cv="5000.00",
        )

        ch_ga4 = _make_channel(db, "ga4")

        camp_paid = _make_campaign(db, tenant, ch_ga4, name="Paid Search")
        adset_paid = _make_adset(db, tenant, camp_paid)
        ad_paid = _make_ad(db, tenant, adset_paid)
        _insert_fact(
            db, tenant, acct, ch_ga4, camp_paid, adset_paid, ad_paid, self._d,
            conversions="30", cv="3000.00",
        )

        camp_organic = _make_campaign(db, tenant, ch_ga4, name="Organic Search")
        adset_organic = _make_adset(db, tenant, camp_organic)
        ad_organic = _make_ad(db, tenant, adset_organic)
        _insert_fact(
            db, tenant, acct, ch_ga4, camp_organic, adset_organic, ad_organic,
            self._d, conversions="70", cv="7000.00",
        )

        db.commit()

    def test_ga4_total_includes_both_groups(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Paid+Organic Tenant")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["ga4_conversions"] == pytest.approx(100.0)
        assert result["ga4_revenue"] == pytest.approx(10000.0)

    def test_ga4_paid_excludes_organic(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Paid+Organic Tenant 2")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["ga4_paid_conversions"] == pytest.approx(30.0)
        assert result["ga4_paid_revenue"] == pytest.approx(3000.0)

    def test_inflation_factor_uses_paid_not_total(self, db_session: Session) -> None:
        """50 (ad-claimed) / 30 (GA4 PAID) = 1.666..., NOT 50/100 = 0.5 (which
        the old total-GA4-denominator bug would have produced — and which
        would nonsensically claim ad platforms UNDER-report vs GA4)."""
        tenant = _make_tenant(db_session, "Paid+Organic Tenant 3")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["inflation_factor"] == pytest.approx(50 / 30, rel=1e-4)
        assert result["inflation_factor"] != pytest.approx(0.5)

    def test_blended_roas_uses_paid_ga4_revenue(self, db_session: Session) -> None:
        """blended_roas = ga4_paid_revenue / ad_spend = 3000/1000 = 3.0."""
        tenant = _make_tenant(db_session, "Paid+Organic Tenant 4")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["blended_roas"] == pytest.approx(3.0)

    def test_mer_uses_total_ga4_revenue(self, db_session: Session) -> None:
        """mer = ga4_revenue (TOTAL) / ad_spend = 10000/1000 = 10.0 — a
        distinct, larger number than blended_roas (3.0); never conflated."""
        tenant = _make_tenant(db_session, "Paid+Organic Tenant 5")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["mer"] == pytest.approx(10.0)
        assert result["mer"] != pytest.approx(result["blended_roas"])

    def test_data_quality_ga4_connected_and_paid_tracked(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session, "Paid+Organic Tenant 6")
        self._seed_paid_plus_organic_ga4(db_session, tenant)
        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        dq = result["data_quality"]
        assert dq["ga4_connected"] is True
        assert dq["ga4_paid_tracked"] is True
        assert dq["note"] is None

    def test_ga4_connected_but_no_paid_channel_group(
        self, db_session: Session
    ) -> None:
        """Scenario (b) — GA4 is connected (has rows) but none of them fall
        into a paid channel group (e.g. only "Organic Search", "Direct").
        inflation_factor must be None and data_quality.note must explain why,
        even though ga4_conversions (TOTAL) is nonzero."""
        tenant = _make_tenant(db_session, "Organic Only Tenant")
        acct = _make_connected_account(db_session, tenant, Platform.google_ads)
        ch_ads = _make_channel(db_session, "google_ads")
        camp_ads = _make_campaign(db_session, tenant, ch_ads)
        adset_ads = _make_adset(db_session, tenant, camp_ads)
        ad_ads = _make_ad(db_session, tenant, adset_ads)
        _insert_fact(
            db_session, tenant, acct, ch_ads, camp_ads, adset_ads, ad_ads,
            self._d, spend="500.00", conversions="10", cv="2000.00",
        )

        ch_ga4 = _make_channel(db_session, "ga4")
        camp_organic = _make_campaign(db_session, tenant, ch_ga4, name="Organic Search")
        adset_organic = _make_adset(db_session, tenant, camp_organic)
        ad_organic = _make_ad(db_session, tenant, adset_organic)
        _insert_fact(
            db_session, tenant, acct, ch_ga4, camp_organic, adset_organic,
            ad_organic, self._d, conversions="40", cv="800.00",
        )
        db_session.commit()

        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        # Total GA4 is nonzero (organic conversions exist)...
        assert result["ga4_conversions"] == pytest.approx(40.0)
        # ...but the PAID slice is zero, so inflation_factor/blended_roas
        # honestly reflect "no comparable data", not a misleading number.
        assert result["ga4_paid_conversions"] == 0.0
        assert result["inflation_factor"] is None
        assert result["blended_roas"] == 0.0
        dq = result["data_quality"]
        assert dq["ga4_connected"] is True
        assert dq["ga4_paid_tracked"] is False
        assert dq["note"] is not None
        assert "ücretli kanal" in dq["note"].lower() or "GA4" in dq["note"]

    def test_paid_tracked_but_no_purchases_gets_non_ecommerce_note(
        self, db_session: Session
    ) -> None:
        """Scenario (c) — a paid channel group IS tracked (a "Paid Search" row
        exists, e.g. sessions>0) but ecommercePurchases is 0 for it (lead-gen /
        non-ecommerce property). This must NOT be mislabeled as a broken
        connection (adversarial review finding #1): inflation stays None (no
        purchases to compare), ga4_paid_tracked is True (a paid row exists —
        distinguishes it from scenario b), and the note explains it is expected
        for non-ecommerce properties rather than telling the user to fix a link."""
        tenant = _make_tenant(db_session, "Non-Ecommerce Paid Tenant")
        acct = _make_connected_account(db_session, tenant, Platform.google_ads)
        ch_ads = _make_channel(db_session, "google_ads")
        camp_ads = _make_campaign(db_session, tenant, ch_ads)
        adset_ads = _make_adset(db_session, tenant, camp_ads)
        ad_ads = _make_ad(db_session, tenant, adset_ads)
        _insert_fact(
            db_session, tenant, acct, ch_ads, camp_ads, adset_ads, ad_ads,
            self._d, spend="500.00", conversions="10", cv="2000.00",
        )

        ch_ga4 = _make_channel(db_session, "ga4")
        camp_paid = _make_campaign(db_session, tenant, ch_ga4, name="Paid Search")
        adset_paid = _make_adset(db_session, tenant, camp_paid)
        ad_paid = _make_ad(db_session, tenant, adset_paid)
        # Paid channel group row EXISTS (row_count>0) but zero purchases.
        _insert_fact(
            db_session, tenant, acct, ch_ga4, camp_paid, adset_paid, ad_paid,
            self._d, conversions="0", cv="0.00",
        )
        db_session.commit()

        result = build_attribution_summary(db_session, tenant.id, self._d, self._d)
        assert result["ga4_paid_conversions"] == 0.0
        assert result["inflation_factor"] is None
        dq = result["data_quality"]
        assert dq["ga4_connected"] is True
        assert dq["ga4_paid_tracked"] is True  # a paid row exists → not scenario (b)
        assert dq["note"] is not None
        assert (
            "ecommerce" in dq["note"].lower() or "e-ticaret" in dq["note"].lower()
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2 — HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def attribution_client(db_session: Session):
    """TestClient seeded with the mixed ad+ga4 warehouse on TODAY (so the
    default 30-day lookback window covers it)."""
    tenant = _make_tenant(db_session, "Endpoint Tenant")
    user = _make_user(db_session, "endpoint_attr@ayaz.app")
    membership = _make_membership(db_session, user, tenant)
    today = datetime.now(timezone.utc).date()
    _seed_mixed_warehouse(db_session, tenant, today)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


class TestAttributionSummaryEndpoint:
    def test_returns_200(self, attribution_client: TestClient) -> None:
        resp = attribution_client.get("/api/v1/attribution/summary")
        assert resp.status_code == 200

    def test_response_shape(self, attribution_client: TestClient) -> None:
        body = attribution_client.get("/api/v1/attribution/summary").json()
        for key in (
            "date_from", "date_to",
            "platform_claimed_conversions", "platform_claimed_revenue",
            "ga4_conversions", "ga4_revenue",
            "ga4_paid_conversions", "ga4_paid_revenue",
            "inflation_factor", "ad_spend", "blended_roas", "mer",
            "data_quality", "channels",
        ):
            assert key in body, f"Missing key: {key}"
        for key in ("ga4_connected", "ga4_paid_tracked", "note"):
            assert key in body["data_quality"], f"Missing data_quality key: {key}"

    def test_values_correct(self, attribution_client: TestClient) -> None:
        body = attribution_client.get("/api/v1/attribution/summary").json()
        assert body["platform_claimed_conversions"] == pytest.approx(20.0)
        assert body["ga4_conversions"] == pytest.approx(15.0)
        assert body["ga4_paid_conversions"] == pytest.approx(15.0)
        assert body["blended_roas"] == pytest.approx(3.0)
        assert body["mer"] == pytest.approx(3.0)
        assert body["inflation_factor"] == pytest.approx(20 / 15, rel=1e-4)
        assert body["data_quality"]["ga4_connected"] is True
        assert body["data_quality"]["ga4_paid_tracked"] is True
        assert body["data_quality"]["note"] is None

    def test_channels_present(self, attribution_client: TestClient) -> None:
        body = attribution_client.get("/api/v1/attribution/summary").json()
        keys = {c["key"] for c in body["channels"]}
        assert keys == {"google_ads", "ga4"}

    def test_days_param_controls_window(self, attribution_client: TestClient) -> None:
        """days=1 covers only today (where data was seeded) → still 200 with data."""
        resp = attribution_client.get(
            "/api/v1/attribution/summary", params={"days": 1}
        )
        assert resp.status_code == 200
        assert resp.json()["platform_claimed_conversions"] == pytest.approx(20.0)

    def test_days_out_of_range_returns_422(self, attribution_client: TestClient) -> None:
        resp = attribution_client.get(
            "/api/v1/attribution/summary", params={"days": 0}
        )
        assert resp.status_code == 422
        resp2 = attribution_client.get(
            "/api/v1/attribution/summary", params={"days": 91}
        )
        assert resp2.status_code == 422

    def test_no_auth_returns_401(self, db_session: Session) -> None:
        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            resp = client.get("/api/v1/attribution/summary")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
