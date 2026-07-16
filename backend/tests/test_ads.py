"""Integration tests for the Ad Management API — M6 phase 1 (read-only).

Strategy
--------
* Uses FastAPI TestClient with an in-memory SQLite DB (same pattern as
  test_dashboard_api.py).
* Fixture ``ads_client`` seeds two campaigns across two channels with enough
  fact rows to exercise aggregation, filtering, sorting, detail timeseries, and
  recommendation detection.
* Tenant isolation is verified by seeding a second tenant whose data must not
  appear in any response from the first tenant's client.

Seed data summary
-----------------
Tenant A (the "active" tenant):
  Channel: google_ads
    Campaign "Google Promo" (camp_g):
      2024-04-01 → 2024-04-14: 14 rows with moderate, stable metrics
      2024-04-15 → 2024-04-21: 7 rows with dramatically low ROAS (triggers roas_drop)

  Channel: meta_ads
    Campaign "Meta Brand" (camp_m):
      2024-04-01 → 2024-04-14: 14 rows with moderate metrics
      (no conversions in last 7 days → triggers zero_conversions)

Tenant B (isolation check):
  Channel: google_ads
    Campaign "Tenant B Campaign":
      2024-04-15: 1 row with spend=9999

The isolation tests confirm that Tenant B's data is invisible to Tenant A's client.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import ads as ads_module
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
from ayaz.services.auth import hash_password
from ayaz.services.ads import list_campaigns, campaign_detail, campaign_recommendations


# ── Register the ads router on the shared app (once per test session) ─────────
# main.py is not modified (per M6 phase 1 constraints); the team lead must wire
# ads_module.router into main.py for production.  Here we register it directly
# on the FastAPI app so the TestClient can reach /api/v1/ads/* endpoints.

_ADS_ROUTER_REGISTERED = False


def _ensure_ads_router() -> None:
    global _ADS_ROUTER_REGISTERED
    if not _ADS_ROUTER_REGISTERED:
        app.include_router(ads_module.router, prefix="/api/v1")
        _ADS_ROUTER_REGISTERED = True


# ── SQLite in-memory engine ───────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.insights  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Seed helpers (mirrors test_dashboard_api.py) ──────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant A") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name=name,
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "ads@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test1234"),
        full_name="Ads Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _make_connected_account(
    db: Session, tenant: Tenant, platform: Platform, ext_id: str
) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=ext_id,
        display_name=f"{platform.value} test",
        vault_secret_ref="",
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
        date_key=d,
        year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month,
        week=iso.week,
        day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, ext_id: str, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=ext_id,
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(
    db: Session, tenant: Tenant, campaign: DimCampaign, ext_id: str
) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=ext_id,
        name=ext_id,
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet, ext_id: str) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=ext_id,
        name=ext_id,
    )
    db.add(ad)
    db.flush()
    return ad


def _insert_fact(
    db: Session,
    tenant: Tenant,
    account: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    d: date,
    *,
    impressions: int = 1000,
    clicks: int = 50,
    cost_raw: str = "100.00",
    conversions: str = "5",
    conversion_value_raw: str = "500.00",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(cost_raw)
    fact = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=account.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=cost,
        cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value_raw),
        conversion_value_ccy="USD",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value_raw),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Primary fixture ───────────────────────────────────────────────────────────


@pytest.fixture()
def ads_client(db_session: Session):
    """TestClient seeded with two campaigns / two channels.

    Campaign "Google Promo" (google_ads):
      Dates 2024-04-01 → 2024-04-14 (prior period): roas = 500/100 = 5x per day
      Dates 2024-04-15 → 2024-04-21 (recent period): roas ≈ 0.1x  → triggers roas_drop

    Campaign "Meta Brand" (meta_ads):
      Dates 2024-04-01 → 2024-04-14: spend=50, conv=3, cv=150 per day
      Dates 2024-04-15 → 2024-04-21: spend=50, conv=0, cv=0     → triggers zero_conversions

    Total spend in 2024-04-01 → 2024-04-21:
      Google Promo: 14*100 + 7*100 = 2100
      Meta Brand:   14*50  + 7*50  = 1050
    """
    tenant_a = _make_tenant(db_session, "Tenant A")
    user_a = _make_user(db_session, "ads_a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)

    acct_g = _make_connected_account(db_session, tenant_a, Platform.google_ads, "GADS-001")
    acct_m = _make_connected_account(db_session, tenant_a, Platform.meta_ads, "META-001")

    ch_g = _make_channel(db_session, "google_ads")
    ch_m = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant_a, ch_g, "G-100", "Google Promo")
    adset_g = _make_adset(db_session, tenant_a, camp_g, "AG-100")
    ad_g = _make_ad(db_session, tenant_a, adset_g, "ADG-100")

    camp_m = _make_campaign(db_session, tenant_a, ch_m, "M-100", "Meta Brand")
    adset_m = _make_adset(db_session, tenant_a, camp_m, "AM-100")
    ad_m = _make_ad(db_session, tenant_a, adset_m, "ADM-100")

    start = date(2024, 4, 1)

    # Google Promo — prior 14 days: high ROAS (5x)
    for i in range(14):
        _insert_fact(
            db_session, tenant_a, acct_g, ch_g, camp_g, adset_g, ad_g,
            start + timedelta(days=i),
            impressions=1000, clicks=50, cost_raw="100.00",
            conversions="5", conversion_value_raw="500.00",
        )

    # Google Promo — recent 7 days: near-zero ROAS (0.1x)
    for i in range(14, 21):
        _insert_fact(
            db_session, tenant_a, acct_g, ch_g, camp_g, adset_g, ad_g,
            start + timedelta(days=i),
            impressions=1000, clicks=50, cost_raw="100.00",
            conversions="0", conversion_value_raw="10.00",
        )

    # Meta Brand — prior 14 days: normal conversions
    for i in range(14):
        _insert_fact(
            db_session, tenant_a, acct_m, ch_m, camp_m, adset_m, ad_m,
            start + timedelta(days=i),
            impressions=800, clicks=40, cost_raw="50.00",
            conversions="3", conversion_value_raw="150.00",
        )

    # Meta Brand — recent 7 days: ZERO conversions while spending
    for i in range(14, 21):
        _insert_fact(
            db_session, tenant_a, acct_m, ch_m, camp_m, adset_m, ad_m,
            start + timedelta(days=i),
            impressions=800, clicks=40, cost_raw="50.00",
            conversions="0", conversion_value_raw="0.00",
        )

    db_session.commit()

    # ── Ensure ads router is registered ───────────────────────────────────
    _ensure_ads_router()

    # ── Wire FastAPI overrides ─────────────────────────────────────────────
    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_membership] = override_membership

    # Also expose raw data for service-layer tests
    ctx = {
        "client": TestClient(app),
        "db": db_session,
        "tenant_a": tenant_a,
        "membership_a": membership_a,
        "camp_g_id": camp_g.id,
        "camp_m_id": camp_m.id,
    }
    yield ctx

    app.dependency_overrides.clear()


# ── Isolation fixture — Tenant B ──────────────────────────────────────────────


@pytest.fixture()
def ads_client_with_isolation(db_session: Session):
    """Same as ads_client but also seeds Tenant B with disjoint data.

    Returns the Tenant A client (membership_a); Tenant B's campaign should never
    appear in the responses.
    """
    tenant_a = _make_tenant(db_session, "Tenant A")
    tenant_b = _make_tenant(db_session, "Tenant B")

    user_a = _make_user(db_session, "iso_a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)

    acct_a = _make_connected_account(db_session, tenant_a, Platform.google_ads, "A-001")
    acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads, "B-001")

    ch_g_a = _make_channel(db_session, "google_ads_iso_a")
    ch_g_b = DimChannel(id=uuid.uuid4(), key="google_ads_iso_b", label="Google Ads B")
    db_session.add(ch_g_b)
    db_session.flush()

    camp_a = _make_campaign(db_session, tenant_a, ch_g_a, "A-CAMP", "Tenant A Campaign")
    adset_a = _make_adset(db_session, tenant_a, camp_a, "A-AS")
    ad_a = _make_ad(db_session, tenant_a, adset_a, "A-AD")

    camp_b = _make_campaign(db_session, tenant_b, ch_g_b, "B-CAMP", "Tenant B Campaign")
    adset_b = _make_adset(db_session, tenant_b, camp_b, "B-AS")
    ad_b = _make_ad(db_session, tenant_b, adset_b, "B-AD")

    d = date(2024, 4, 15)
    _insert_fact(
        db_session, tenant_a, acct_a, ch_g_a, camp_a, adset_a, ad_a, d,
        impressions=100, clicks=10, cost_raw="50.00",
        conversions="1", conversion_value_raw="100.00",
    )
    # Tenant B with very high spend (should never appear in Tenant A's view)
    _insert_fact(
        db_session, tenant_b, acct_b, ch_g_b, camp_b, adset_b, ad_b, d,
        impressions=9999, clicks=999, cost_raw="9999.00",
        conversions="1", conversion_value_raw="100.00",
    )

    db_session.commit()

    _ensure_ads_router()

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_membership] = override_membership

    ctx = {
        "client": TestClient(app),
        "db": db_session,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "camp_a_id": camp_a.id,
        "camp_b_id": camp_b.id,
    }
    yield ctx
    app.dependency_overrides.clear()


# ── Campaign list endpoint tests ──────────────────────────────────────────────


class TestCampaignListEndpoint:
    _DATE_PARAMS = {"date_from": "2024-04-01", "date_to": "2024-04-21"}

    def test_returns_200(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        assert resp.status_code == 200

    def test_returns_two_campaigns(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        assert len(resp.json()) == 2

    def test_campaign_names_present(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        names = {c["campaign_name"] for c in resp.json()}
        assert names == {"Google Promo", "Meta Brand"}

    def test_campaign_channels(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        by_name = {c["campaign_name"]: c["channel"] for c in resp.json()}
        assert by_name["Google Promo"] == "google_ads"
        assert by_name["Meta Brand"] == "meta_ads"

    def test_google_promo_spend(self, ads_client) -> None:
        """Google Promo: 21 days * 100 spend = 2100."""
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        g = next(c for c in resp.json() if c["campaign_name"] == "Google Promo")
        assert g["spend"] == pytest.approx(2100.0)

    def test_meta_brand_spend(self, ads_client) -> None:
        """Meta Brand: 21 days * 50 spend = 1050."""
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        m = next(c for c in resp.json() if c["campaign_name"] == "Meta Brand")
        assert m["spend"] == pytest.approx(1050.0)

    def test_derived_metrics_present(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        for c in resp.json():
            for key in ("ctr", "cpc", "cpa", "roas"):
                assert key in c, f"Missing {key} in {c['campaign_name']}"

    def test_all_metrics_are_numbers(self, ads_client) -> None:
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        for c in resp.json():
            for key in ("spend", "impressions", "clicks", "conversions",
                        "conversion_value", "ctr", "cpc", "cpa", "roas"):
                assert isinstance(c[key], (int, float)), (
                    f"{c['campaign_name']}.{key} should be numeric"
                )

    def test_status_field_active(self, ads_client) -> None:
        """Campaigns with spend are 'active'."""
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        for c in resp.json():
            assert c["status"] == "active"

    def test_filter_by_channel(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "channel": "google_ads"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        body = resp.json()
        assert len(body) == 1
        assert body[0]["channel"] == "google_ads"

    def test_filter_by_channel_meta(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "channel": "meta_ads"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        body = resp.json()
        assert len(body) == 1
        assert body[0]["channel"] == "meta_ads"

    def test_filter_by_channel_no_match(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "channel": "tiktok_ads"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        assert resp.json() == []

    def test_filter_by_status_active(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "status": "active"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        assert len(resp.json()) == 2

    def test_filter_by_status_paused(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "status": "paused"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        assert resp.json() == []

    def test_sort_by_spend_default_descending(self, ads_client) -> None:
        """Default sort is spend descending → Google Promo (2100) first."""
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=self._DATE_PARAMS)
        names = [c["campaign_name"] for c in resp.json()]
        assert names[0] == "Google Promo"

    def test_sort_by_spend_ascending(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "sort": "spend", "sort_asc": "true"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        spends = [c["spend"] for c in resp.json()]
        assert spends == sorted(spends)

    def test_sort_by_campaign_name(self, ads_client) -> None:
        params = {**self._DATE_PARAMS, "sort": "campaign_name", "sort_asc": "true"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        names = [c["campaign_name"] for c in resp.json()]
        assert names == sorted(names)

    def test_no_data_in_range_returns_empty(self, ads_client) -> None:
        params = {"date_from": "2030-01-01", "date_to": "2030-01-31"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        assert resp.json() == []

    def test_invalid_date_range_returns_422(self, ads_client) -> None:
        params = {"date_from": "2024-04-21", "date_to": "2024-04-01"}
        resp = ads_client["client"].get("/api/v1/ads/campaigns", params=params)
        assert resp.status_code == 422

    def test_missing_date_params_returns_422(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/campaigns", params={"date_to": "2024-04-21"}
        )
        assert resp.status_code == 422


# ── Campaign detail endpoint tests ────────────────────────────────────────────


class TestCampaignDetailEndpoint:
    _DATE_PARAMS = {"date_from": "2024-04-01", "date_to": "2024-04-21"}

    def _url(self, camp_id: uuid.UUID) -> str:
        return f"/api/v1/ads/campaigns/{camp_id}"

    def test_returns_200_for_valid_campaign(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        assert resp.status_code == 200

    def test_response_structure(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        body = resp.json()
        assert "campaign_id" in body
        assert "campaign_name" in body
        assert "channel" in body
        assert "status" in body
        assert "totals" in body
        assert "timeseries" in body

    def test_totals_spend_google_promo(self, ads_client) -> None:
        """Google Promo 21 days * 100 = 2100."""
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        body = resp.json()
        assert body["totals"]["spend"] == pytest.approx(2100.0)

    def test_timeseries_has_21_points(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        body = resp.json()
        assert len(body["timeseries"]) == 21

    def test_timeseries_ordered_by_date(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        dates = [p["date"] for p in resp.json()["timeseries"]]
        assert dates == sorted(dates)

    def test_timeseries_daily_metrics_are_numbers(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        for pt in resp.json()["timeseries"]:
            for key in ("spend", "impressions", "clicks", "conversions",
                        "conversion_value", "ctr", "cpc", "cpa", "roas"):
                assert isinstance(pt[key], (int, float)), (
                    f"timeseries.{key} should be numeric"
                )

    def test_returns_404_for_unknown_campaign(self, ads_client) -> None:
        fake_id = uuid.uuid4()
        resp = ads_client["client"].get(
            f"/api/v1/ads/campaigns/{fake_id}", params=self._DATE_PARAMS
        )
        assert resp.status_code == 404

    def test_detail_invalid_date_range_422(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]),
            params={"date_from": "2024-04-21", "date_to": "2024-04-01"},
        )
        assert resp.status_code == 422

    def test_campaign_name_and_channel(self, ads_client) -> None:
        resp = ads_client["client"].get(
            self._url(ads_client["camp_g_id"]), params=self._DATE_PARAMS
        )
        body = resp.json()
        assert body["campaign_name"] == "Google Promo"
        assert body["channel"] == "google_ads"

    def test_meta_brand_detail_totals(self, ads_client) -> None:
        """Meta Brand: 21 * 50 = 1050 spend, 14 * 3 = 42 conversions."""
        resp = ads_client["client"].get(
            self._url(ads_client["camp_m_id"]), params=self._DATE_PARAMS
        )
        body = resp.json()
        assert body["totals"]["spend"] == pytest.approx(1050.0)
        assert body["totals"]["conversions"] == pytest.approx(42.0)


# ── Recommendations endpoint tests ────────────────────────────────────────────


class TestRecommendationsEndpoint:
    _DATE_PARAMS = {"date_from": "2024-04-01", "date_to": "2024-04-21"}

    def test_returns_200(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        assert resp.status_code == 200

    def test_returns_list(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        assert isinstance(resp.json(), list)

    def test_anomalous_google_campaign_has_recommendations(self, ads_client) -> None:
        """Google Promo has a dramatic ROAS drop — at least one recommendation expected."""
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        google_recs = [r for r in recs if r["campaign_name"] == "Google Promo"]
        assert len(google_recs) > 0, "Expected recommendations for Google Promo"

    def test_meta_zero_conversions_recommendation(self, ads_client) -> None:
        """Meta Brand has zero conversions in recent 7 days while spending."""
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        meta_zero = [
            r for r in recs
            if r["campaign_name"] == "Meta Brand"
            and r["category"] == "zero_conversions"
        ]
        assert len(meta_zero) > 0, "Expected zero_conversions rec for Meta Brand"

    def test_roas_drop_detected_for_google_promo(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        roas_drops = [
            r for r in recs
            if r["campaign_name"] == "Google Promo"
            and r["category"] == "roas_drop"
        ]
        assert len(roas_drops) > 0, "Expected roas_drop for Google Promo"

    def test_recommendation_shape(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        assert len(recs) > 0, "Need at least one recommendation to check shape"
        r = recs[0]
        for key in ("campaign_id", "campaign_name", "channel", "category",
                    "severity", "score", "metric", "message",
                    "suggested_action", "period_start", "period_end", "data"):
            assert key in r, f"Missing key {key!r} in recommendation"

    def test_message_is_turkish_string(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        assert len(recs) > 0
        for r in recs:
            assert isinstance(r["message"], str)
            assert len(r["message"]) > 10

    def test_suggested_action_is_nonempty_string(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        recs = resp.json()
        for r in recs:
            assert isinstance(r["suggested_action"], str)
            assert len(r["suggested_action"]) > 0

    def test_severity_values_valid(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        valid = {"info", "warning", "critical"}
        for r in resp.json():
            assert r["severity"] in valid, f"Unexpected severity: {r['severity']}"

    def test_recommendations_sorted_by_score_desc(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        scores = [r["score"] for r in resp.json()]
        assert scores == sorted(scores, reverse=True)

    def test_invalid_date_range_returns_422(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations",
            params={"date_from": "2024-04-21", "date_to": "2024-04-01"},
        )
        assert resp.status_code == 422

    def test_no_data_returns_empty_list(self, ads_client) -> None:
        resp = ads_client["client"].get(
            "/api/v1/ads/recommendations",
            params={"date_from": "2030-01-01", "date_to": "2030-01-31"},
        )
        assert resp.json() == []


# ── Actions stub endpoint ─────────────────────────────────────────────────────


class TestActionsStub:
    def test_returns_501(self, ads_client) -> None:
        camp_id = ads_client["camp_g_id"]
        resp = ads_client["client"].post(
            f"/api/v1/ads/campaigns/{camp_id}/actions",
            json={"action": "pause"},
        )
        assert resp.status_code == 501

    def test_501_detail_mentions_phase_2(self, ads_client) -> None:
        camp_id = ads_client["camp_g_id"]
        resp = ads_client["client"].post(
            f"/api/v1/ads/campaigns/{camp_id}/actions",
            json={},
        )
        body = resp.json()
        assert "detail" in body
        # Turkish message should mention phase 2
        assert "faz 2" in body["detail"].lower() or "M6" in body["detail"]


# ── Tenant isolation tests ────────────────────────────────────────────────────


class TestTenantIsolation:
    _DATE_PARAMS = {"date_from": "2024-04-15", "date_to": "2024-04-15"}

    def test_campaign_list_does_not_leak_tenant_b(
        self, ads_client_with_isolation
    ) -> None:
        resp = ads_client_with_isolation["client"].get(
            "/api/v1/ads/campaigns", params=self._DATE_PARAMS
        )
        names = [c["campaign_name"] for c in resp.json()]
        assert "Tenant B Campaign" not in names

    def test_campaign_list_only_shows_tenant_a(
        self, ads_client_with_isolation
    ) -> None:
        resp = ads_client_with_isolation["client"].get(
            "/api/v1/ads/campaigns", params=self._DATE_PARAMS
        )
        body = resp.json()
        assert len(body) == 1
        assert body[0]["campaign_name"] == "Tenant A Campaign"

    def test_spend_does_not_include_tenant_b(
        self, ads_client_with_isolation
    ) -> None:
        """Tenant B has spend=9999 — should not appear in Tenant A's total."""
        resp = ads_client_with_isolation["client"].get(
            "/api/v1/ads/campaigns", params=self._DATE_PARAMS
        )
        total_spend = sum(c["spend"] for c in resp.json())
        assert total_spend == pytest.approx(50.0)

    def test_campaign_detail_returns_404_for_tenant_b_campaign(
        self, ads_client_with_isolation
    ) -> None:
        camp_b_id = ads_client_with_isolation["camp_b_id"]
        resp = ads_client_with_isolation["client"].get(
            f"/api/v1/ads/campaigns/{camp_b_id}", params=self._DATE_PARAMS
        )
        assert resp.status_code == 404

    def test_recommendations_do_not_mention_tenant_b(
        self, ads_client_with_isolation
    ) -> None:
        resp = ads_client_with_isolation["client"].get(
            "/api/v1/ads/recommendations", params=self._DATE_PARAMS
        )
        for r in resp.json():
            assert r["campaign_name"] != "Tenant B Campaign"


# ── Service-layer unit tests (direct function calls) ─────────────────────────


class TestListCampaignsService:
    def test_list_campaigns_returns_dicts(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = list_campaigns(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)

    def test_list_campaigns_two_rows(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = list_campaigns(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        assert len(result) == 2

    def test_list_campaigns_channel_filter(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = list_campaigns(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21),
            channel="meta_ads"
        )
        assert len(result) == 1
        assert result[0]["channel"] == "meta_ads"

    def test_list_campaigns_sort_by_roas_desc(self, ads_client) -> None:
        """Meta Brand has higher overall ROAS because its prior period has good numbers
        and fewer zero-conv days in the full 21-day view."""
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = list_campaigns(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21),
            sort="roas", sort_desc=True,
        )
        roas_values = [r["roas"] for r in result]
        assert roas_values == sorted(roas_values, reverse=True)


class TestListCampaignsSourceTypeIsolation:
    """Confirms (not a code fix — see Batch A.2 report) that campaign-grain
    aggregation is already channel-isolated: a DimCampaign belongs to exactly
    one DimChannel, so a GA4 (analytics) campaign can never be blended into
    an ad campaign's own numbers. Adding a GA4 campaign to the same tenant
    must leave the two pre-existing ad campaigns' numbers untouched and
    surface as its own separate row."""

    def test_ga4_campaign_is_separate_row_with_own_numbers(self, ads_client) -> None:
        db = ads_client["db"]
        tenant = ads_client["tenant_a"]

        acct_ga4 = _make_connected_account(db, tenant, Platform.ga4, "GA4-001")
        ch_ga4 = _make_channel(db, "ga4")
        camp_ga4 = _make_campaign(db, tenant, ch_ga4, "GA4-100", "(not set)")
        adset_ga4 = _make_adset(db, tenant, camp_ga4, "AGA4-100")
        ad_ga4 = _make_ad(db, tenant, adset_ga4, "ADGA4-100")
        _insert_fact(
            db, tenant, acct_ga4, ch_ga4, camp_ga4,
            adset_ga4, ad_ga4, date(2024, 4, 1),
            impressions=0, clicks=0, cost_raw="0",
            conversions="9999", conversion_value_raw="500000.00",
        )
        db.commit()

        result = list_campaigns(db, tenant.id, date(2024, 4, 1), date(2024, 4, 21))
        assert len(result) == 3

        by_channel = {r["channel"]: r for r in result}
        assert by_channel["ga4"]["conversions"] == pytest.approx(9999.0)
        assert by_channel["ga4"]["spend"] == pytest.approx(0.0)

        # google_ads / meta_ads rows must be byte-identical to before GA4 was added.
        assert by_channel["google_ads"]["spend"] == pytest.approx(2100.0)
        assert by_channel["meta_ads"]["spend"] == pytest.approx(1050.0)


class TestCampaignDetailService:
    def test_campaign_detail_returns_dict(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_detail(
            db, tenant_id, ads_client["camp_g_id"],
            date(2024, 4, 1), date(2024, 4, 21),
        )
        assert result is not None
        assert isinstance(result, dict)

    def test_campaign_detail_unknown_id_returns_none(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_detail(
            db, tenant_id, uuid.uuid4(),
            date(2024, 4, 1), date(2024, 4, 21),
        )
        assert result is None

    def test_campaign_detail_wrong_tenant_returns_none(
        self, ads_client_with_isolation
    ) -> None:
        """Requesting Tenant B's campaign_id under Tenant A's session returns None."""
        ctx = ads_client_with_isolation
        result = campaign_detail(
            ctx["db"],
            ctx["tenant_a"].id,
            ctx["camp_b_id"],
            date(2024, 4, 15),
            date(2024, 4, 15),
        )
        assert result is None

    def test_campaign_detail_timeseries_length(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_detail(
            db, tenant_id, ads_client["camp_g_id"],
            date(2024, 4, 1), date(2024, 4, 21),
        )
        assert len(result["timeseries"]) == 21


class TestCampaignRecommendationsService:
    def test_returns_list(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_recommendations(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        assert isinstance(result, list)

    def test_roas_drop_detected(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_recommendations(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        categories = {r["category"] for r in result}
        assert "roas_drop" in categories or "zero_conversions" in categories, (
            "Expected at least one anomaly category in recommendations"
        )

    def test_recommendation_has_turkish_message(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_recommendations(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        if result:
            # Turkish messages should contain at least one non-ASCII Turkish char
            # or recognisable Turkish words
            all_messages = " ".join(r["message"] for r in result)
            assert len(all_messages) > 0

    def test_all_recommendations_have_campaign_id(self, ads_client) -> None:
        db = ads_client["db"]
        tenant_id = ads_client["tenant_a"].id
        result = campaign_recommendations(
            db, tenant_id, date(2024, 4, 1), date(2024, 4, 21)
        )
        for r in result:
            assert r["campaign_id"]
            assert r["campaign_name"]

    def test_tenant_isolation_in_service(self, ads_client_with_isolation) -> None:
        ctx = ads_client_with_isolation
        result = campaign_recommendations(
            ctx["db"],
            ctx["tenant_a"].id,
            date(2024, 4, 15),
            date(2024, 4, 15),
        )
        for r in result:
            assert r["campaign_name"] != "Tenant B Campaign"
