"""Tests for Creative / Ad-level Performance Analysis.

Strategy
--------
* Uses FastAPI TestClient with an in-memory SQLite DB (same pattern as test_ads.py).
* Fixture ``creatives_client`` seeds 3 ads across 2 campaigns / 2 channels:
    - ad_winner  (google_ads, "Marka Kampanya"): high ROAS winner
    - ad_mid     (google_ads, "Marka Kampanya"): moderate performer
    - ad_loser   (meta_ads,  "Meta Retargeting"): spends but zero conversions

  This lets us assert:
    - Aggregation correctness (spend, conversions, ROAS).
    - top=[winner], bottom=[loser] ordering by ROAS.
    - Commentary names winner and loser by real ad_name.
    - Tenant isolation: a second tenant's ad never appears.

Seed data summary (Tenant A)
-----------------------------
  google_ads / "Marka Kampanya":
    ad_winner: 7 days * spend=200, conv=20, cv=2000  → ROAS = 10x
    ad_mid:    7 days * spend=200, conv=4,  cv=400   → ROAS = 2x

  meta_ads / "Meta Retargeting":
    ad_loser:  7 days * spend=300, conv=0,  cv=0     → ROAS = 0x (budget waster)

Tenant B:
  google_ads / "Tenant B Ad": 1 day * spend=9999 (must never appear in A's view)
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
from ayaz.api.v1 import creatives as creatives_module
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
from ayaz.services.creatives import ad_performance


# ── Register creatives router once per session ────────────────────────────────

_CREATIVES_ROUTER_REGISTERED = False


def _ensure_creatives_router() -> None:
    global _CREATIVES_ROUTER_REGISTERED
    if not _CREATIVES_ROUTER_REGISTERED:
        app.include_router(creatives_module.router, prefix="/api/v1")
        _CREATIVES_ROUTER_REGISTERED = True


# ── In-memory SQLite engine ───────────────────────────────────────────────────


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


# ── Seed helpers (mirror test_ads.py) ────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Creative Test Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name, base_currency="TRY",
        country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "creatives@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(), email=email,
        hashed_password=hash_password("test1234"),
        full_name="Creatives Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _make_connected_account(
    db: Session, tenant: Tenant, platform: Platform, ext_id: str
) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=platform,
        external_account_id=ext_id, display_name=f"{platform.value} test",
        vault_secret_ref="", sync_status=SyncStatus.idle,
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
        date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week, day_of_week=d.weekday(),
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
        id=uuid.uuid4(), tenant_id=tenant.id, channel_id=channel.id,
        external_id=ext_id, name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(
    db: Session, tenant: Tenant, campaign: DimCampaign, ext_id: str, name: str = ""
) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant.id, campaign_id=campaign.id,
        external_id=ext_id, name=name or ext_id,
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(
    db: Session, tenant: Tenant, adset: DimAdSet, ext_id: str, name: str
) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant.id, ad_set_id=adset.id,
        external_id=ext_id, name=name,
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
    impressions: int = 5000,
    clicks: int = 100,
    cost_raw: str = "200.00",
    conversions: str = "10",
    conversion_value_raw: str = "1000.00",
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
        cost_ccy="TRY",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value_raw),
        conversion_value_ccy="TRY",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value_raw),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Primary fixture ───────────────────────────────────────────────────────────

# Date range: 2024-05-01 → 2024-05-07 (7 days)
_START = date(2024, 5, 1)
_END = date(2024, 5, 7)
_DATE_PARAMS = {"date_from": "2024-05-01", "date_to": "2024-05-07"}

# Expected aggregates over 7 days:
#   ad_winner : spend=1400, conv=140, cv=14000  → ROAS=10x
#   ad_mid    : spend=1400, conv=28,  cv=2800   → ROAS=2x
#   ad_loser  : spend=2100, conv=0,   cv=0      → ROAS=0x
_WINNER_SPEND = 7 * 200.0
_MID_SPEND = 7 * 200.0
_LOSER_SPEND = 7 * 300.0


@pytest.fixture()
def creatives_client(db_session: Session):
    """TestClient seeded with 3 ad-level fixtures across 2 channels."""
    tenant = _make_tenant(db_session, "Tenant A")
    user = _make_user(db_session, "cr_a@ayaz.app")
    membership = _make_membership(db_session, user, tenant)

    acct_g = _make_connected_account(db_session, tenant, Platform.google_ads, "G-CR-001")
    acct_m = _make_connected_account(db_session, tenant, Platform.meta_ads, "M-CR-001")

    ch_g = _make_channel(db_session, "google_ads")
    ch_m = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant, ch_g, "CG-CR-001", "Marka Kampanya")
    adset_g = _make_adset(db_session, tenant, camp_g, "AG-CR-001")

    camp_m = _make_campaign(db_session, tenant, ch_m, "CM-CR-001", "Meta Retargeting")
    adset_m = _make_adset(db_session, tenant, camp_m, "AM-CR-001")

    # Three real ads
    ad_winner = _make_ad(db_session, tenant, adset_g, "ADG-WIN", "Video — Indirim")
    ad_mid = _make_ad(db_session, tenant, adset_g, "ADG-MID", "Statik — Marka")
    ad_loser = _make_ad(db_session, tenant, adset_m, "ADM-LOSE", "Carousel — Urun")

    for i in range(7):
        d = _START + timedelta(days=i)
        # Winner: ROAS=10x
        _insert_fact(
            db_session, tenant, acct_g, ch_g, camp_g, adset_g, ad_winner, d,
            impressions=5000, clicks=100, cost_raw="200.00",
            conversions="20", conversion_value_raw="2000.00",
        )
        # Mid: ROAS=2x
        _insert_fact(
            db_session, tenant, acct_g, ch_g, camp_g, adset_g, ad_mid, d,
            impressions=5000, clicks=100, cost_raw="200.00",
            conversions="4", conversion_value_raw="400.00",
        )
        # Loser: spend=300, zero conversions
        _insert_fact(
            db_session, tenant, acct_m, ch_m, camp_m, adset_m, ad_loser, d,
            impressions=8000, clicks=160, cost_raw="300.00",
            conversions="0", conversion_value_raw="0.00",
        )

    db_session.commit()

    _ensure_creatives_router()

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_membership] = override_membership

    ctx = {
        "client": TestClient(app),
        "db": db_session,
        "tenant": tenant,
        "membership": membership,
        "ad_winner_name": "Video — Indirim",
        "ad_mid_name": "Statik — Marka",
        "ad_loser_name": "Carousel — Urun",
    }
    yield ctx
    app.dependency_overrides.clear()


# ── Tenant isolation fixture ──────────────────────────────────────────────────


@pytest.fixture()
def creatives_isolation_client(db_session: Session):
    """Tenant A + Tenant B seeded; client authenticates as Tenant A."""
    tenant_a = _make_tenant(db_session, "Tenant A Iso")
    tenant_b = _make_tenant(db_session, "Tenant B Iso")

    user_a = _make_user(db_session, "cr_iso_a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)

    acct_a = _make_connected_account(db_session, tenant_a, Platform.google_ads, "A-CR-ISO")
    acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads, "B-CR-ISO")

    ch_a = _make_channel(db_session, "google_ads_cr_iso_a")
    ch_b = DimChannel(id=uuid.uuid4(), key="google_ads_cr_iso_b", label="Google Ads B")
    db_session.add(ch_b)
    db_session.flush()

    camp_a = _make_campaign(db_session, tenant_a, ch_a, "A-CAMP-CR", "Tenant A Creative Camp")
    adset_a = _make_adset(db_session, tenant_a, camp_a, "A-AS-CR")
    ad_a = _make_ad(db_session, tenant_a, adset_a, "A-AD-CR", "Tenant A Ad")

    camp_b = _make_campaign(db_session, tenant_b, ch_b, "B-CAMP-CR", "Tenant B Creative Camp")
    adset_b = _make_adset(db_session, tenant_b, camp_b, "B-AS-CR")
    ad_b = _make_ad(db_session, tenant_b, adset_b, "B-AD-CR", "Tenant B Ad")

    d = date(2024, 5, 1)
    _insert_fact(
        db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a, d,
        impressions=1000, clicks=50, cost_raw="100.00",
        conversions="5", conversion_value_raw="500.00",
    )
    # Tenant B high spend — must never appear in Tenant A's view
    _insert_fact(
        db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b, d,
        impressions=99999, clicks=9999, cost_raw="9999.00",
        conversions="1", conversion_value_raw="10.00",
    )

    db_session.commit()

    _ensure_creatives_router()

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
    }
    yield ctx
    app.dependency_overrides.clear()


# ── Endpoint tests ────────────────────────────────────────────────────────────


class TestAdPerformanceEndpoint:
    def test_returns_200(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        assert resp.status_code == 200

    def test_response_has_required_keys(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        body = resp.json()
        for key in ("ads", "top", "bottom", "commentary"):
            assert key in body, f"Missing top-level key: {key}"

    def test_returns_three_ads(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        assert len(resp.json()["ads"]) == 3

    def test_ad_names_present(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        names = {a["ad_name"] for a in resp.json()["ads"]}
        assert names == {"Video — Indirim", "Statik — Marka", "Carousel — Urun"}

    def test_winner_spend_correct(self, creatives_client) -> None:
        """Video — Indirim: 7 days * 200 = 1400."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        winner = next(
            a for a in resp.json()["ads"] if a["ad_name"] == "Video — Indirim"
        )
        assert winner["spend"] == pytest.approx(_WINNER_SPEND)

    def test_loser_spend_correct(self, creatives_client) -> None:
        """Carousel — Urun: 7 days * 300 = 2100."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        loser = next(
            a for a in resp.json()["ads"] if a["ad_name"] == "Carousel — Urun"
        )
        assert loser["spend"] == pytest.approx(_LOSER_SPEND)

    def test_winner_roas_correct(self, creatives_client) -> None:
        """Video — Indirim: conv_value=14000, spend=1400 → ROAS=10."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        winner = next(
            a for a in resp.json()["ads"] if a["ad_name"] == "Video — Indirim"
        )
        assert winner["roas"] == pytest.approx(10.0)

    def test_loser_roas_is_zero(self, creatives_client) -> None:
        """Carousel — Urun has zero conversions → ROAS=0."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        loser = next(
            a for a in resp.json()["ads"] if a["ad_name"] == "Carousel — Urun"
        )
        assert loser["roas"] == pytest.approx(0.0)

    def test_loser_conversions_are_zero(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        loser = next(
            a for a in resp.json()["ads"] if a["ad_name"] == "Carousel — Urun"
        )
        assert loser["conversions"] == pytest.approx(0.0)

    def test_all_metrics_are_numbers(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        for ad in resp.json()["ads"]:
            for key in ("spend", "impressions", "clicks", "conversions",
                        "conversion_value", "roas", "ctr", "cpc", "cpa"):
                assert isinstance(ad[key], (int, float)), (
                    f"{ad['ad_name']}.{key} should be numeric"
                )

    def test_ad_has_campaign_info(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        for ad in resp.json()["ads"]:
            assert "campaign_name" in ad
            assert "channel" in ad
            assert len(ad["campaign_name"]) > 0

    def test_no_data_returns_empty_commentary(self, creatives_client) -> None:
        params = {"date_from": "2030-01-01", "date_to": "2030-01-31"}
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=params
        )
        body = resp.json()
        assert body["ads"] == []
        assert body["top"] == []
        assert body["bottom"] == []
        assert isinstance(body["commentary"], str)

    def test_invalid_date_range_returns_422(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance",
            params={"date_from": "2024-05-07", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 422

    def test_missing_date_params_returns_422(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params={"date_to": "2024-05-07"}
        )
        assert resp.status_code == 422

    def test_sort_by_spend_default_descending(self, creatives_client) -> None:
        """Default sort=spend desc: loser (2100) first, winner and mid (1400) follow."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        spends = [a["spend"] for a in resp.json()["ads"]]
        assert spends == sorted(spends, reverse=True)

    def test_sort_by_roas(self, creatives_client) -> None:
        params = {**_DATE_PARAMS, "sort": "roas"}
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=params
        )
        roas_vals = [a["roas"] for a in resp.json()["ads"]]
        assert roas_vals == sorted(roas_vals, reverse=True)


# ── Top / Bottom ordering tests ───────────────────────────────────────────────


class TestTopBottomOrdering:
    def test_top_is_winner(self, creatives_client) -> None:
        """Top #1 must be the ad with highest ROAS: 'Video — Indirim' at 10x."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        top = resp.json()["top"]
        assert len(top) >= 1
        assert top[0]["ad_name"] == "Video — Indirim"

    def test_top_at_most_three(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        assert len(resp.json()["top"]) <= 3

    def test_top_ordered_by_roas_desc(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        top = resp.json()["top"]
        roas_vals = [a["roas"] for a in top]
        assert roas_vals == sorted(roas_vals, reverse=True)

    def test_bottom_is_loser(self, creatives_client) -> None:
        """Bottom #1 must be the ad with lowest ROAS among spenders: 'Carousel — Urun' at 0x."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        bottom = resp.json()["bottom"]
        assert len(bottom) >= 1
        assert bottom[0]["ad_name"] == "Carousel — Urun"

    def test_bottom_at_most_three(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        assert len(resp.json()["bottom"]) <= 3

    def test_bottom_ordered_by_roas_asc(self, creatives_client) -> None:
        """Bottom list: lowest ROAS first."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        bottom = resp.json()["bottom"]
        roas_vals = [a["roas"] for a in bottom]
        assert roas_vals == sorted(roas_vals)

    def test_bottom_only_includes_spenders(self, creatives_client) -> None:
        """All bottom ads must have spend > 0 (no-spend ads with ROAS=0 are excluded)."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        for ad in resp.json()["bottom"]:
            assert ad["spend"] > 0, f"Non-spender in bottom: {ad['ad_name']}"


# ── Commentary tests ──────────────────────────────────────────────────────────


class TestCommentary:
    def test_commentary_is_string(self, creatives_client) -> None:
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        assert isinstance(resp.json()["commentary"], str)
        assert len(resp.json()["commentary"]) > 10

    def test_commentary_mentions_winner(self, creatives_client) -> None:
        """Commentary must name the best creative by ad_name."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        commentary = resp.json()["commentary"]
        assert "Video — Indirim" in commentary, (
            f"Commentary should mention winner 'Video — Indirim': {commentary}"
        )

    def test_commentary_mentions_loser(self, creatives_client) -> None:
        """Commentary must name the worst spender by ad_name."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        commentary = resp.json()["commentary"]
        assert "Carousel — Urun" in commentary, (
            f"Commentary should mention loser 'Carousel — Urun': {commentary}"
        )

    def test_commentary_mentions_roas(self, creatives_client) -> None:
        """Commentary for winner should include ROAS figure."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        commentary = resp.json()["commentary"]
        # ROAS=10.00x should appear in Turkish decimal format as "10,00x"
        assert "10,00x" in commentary, (
            f"Commentary should include ROAS '10,00x': {commentary}"
        )

    def test_commentary_mentions_durdur_for_zero_conversions(
        self, creatives_client
    ) -> None:
        """For a zero-conversion loser, commentary suggests durdurmayı."""
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=_DATE_PARAMS
        )
        commentary = resp.json()["commentary"]
        # Turkish for "consider stopping" — present when loser has zero conversions
        assert "dönüşüm yok" in commentary.lower() or "durdurmay" in commentary.lower(), (
            f"Commentary should mention durdurmayı/dönüşüm yok: {commentary}"
        )

    def test_no_data_commentary_is_informative(self, creatives_client) -> None:
        params = {"date_from": "2030-01-01", "date_to": "2030-01-31"}
        resp = creatives_client["client"].get(
            "/api/v1/creatives/performance", params=params
        )
        commentary = resp.json()["commentary"]
        assert len(commentary) > 5


# ── Tenant isolation tests ────────────────────────────────────────────────────


class TestTenantIsolation:
    _PARAMS = {"date_from": "2024-05-01", "date_to": "2024-05-01"}

    def test_ads_list_does_not_leak_tenant_b(
        self, creatives_isolation_client
    ) -> None:
        resp = creatives_isolation_client["client"].get(
            "/api/v1/creatives/performance", params=self._PARAMS
        )
        ad_names = [a["ad_name"] for a in resp.json()["ads"]]
        assert "Tenant B Ad" not in ad_names

    def test_ads_list_shows_only_tenant_a(
        self, creatives_isolation_client
    ) -> None:
        resp = creatives_isolation_client["client"].get(
            "/api/v1/creatives/performance", params=self._PARAMS
        )
        ads = resp.json()["ads"]
        assert len(ads) == 1
        assert ads[0]["ad_name"] == "Tenant A Ad"

    def test_spend_does_not_include_tenant_b(
        self, creatives_isolation_client
    ) -> None:
        """Tenant B has spend=9999 — must not appear in Tenant A's total."""
        resp = creatives_isolation_client["client"].get(
            "/api/v1/creatives/performance", params=self._PARAMS
        )
        total_spend = sum(a["spend"] for a in resp.json()["ads"])
        assert total_spend == pytest.approx(100.0)


# ── Service-layer unit tests (direct function calls) ─────────────────────────


class TestAdPerformanceService:
    def test_returns_dict(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert isinstance(result, dict)
        assert "ads" in result
        assert "top" in result
        assert "bottom" in result
        assert "commentary" in result

    def test_three_ads_returned(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert len(result["ads"]) == 3

    def test_winner_spend_aggregated(self, creatives_client) -> None:
        """winner: 7 * 200 = 1400 spend."""
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        winner = next(a for a in result["ads"] if a["ad_name"] == "Video — Indirim")
        assert winner["spend"] == pytest.approx(_WINNER_SPEND)

    def test_winner_roas_ten(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        winner = next(a for a in result["ads"] if a["ad_name"] == "Video — Indirim")
        assert winner["roas"] == pytest.approx(10.0)

    def test_loser_roas_zero(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        loser = next(a for a in result["ads"] if a["ad_name"] == "Carousel — Urun")
        assert loser["roas"] == pytest.approx(0.0)

    def test_top_first_is_winner(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert result["top"][0]["ad_name"] == "Video — Indirim"

    def test_bottom_first_is_loser(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert result["bottom"][0]["ad_name"] == "Carousel — Urun"

    def test_commentary_names_winner(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert "Video — Indirim" in result["commentary"]

    def test_commentary_names_loser(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        assert "Carousel — Urun" in result["commentary"]

    def test_empty_range_returns_empty_collections(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, date(2030, 1, 1), date(2030, 1, 31))
        assert result["ads"] == []
        assert result["top"] == []
        assert result["bottom"] == []

    def test_sort_roas_descending(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END, sort="roas")
        roas_vals = [a["roas"] for a in result["ads"]]
        assert roas_vals == sorted(roas_vals, reverse=True)

    def test_all_ad_dicts_have_required_keys(self, creatives_client) -> None:
        db = creatives_client["db"]
        tenant_id = creatives_client["tenant"].id
        result = ad_performance(db, tenant_id, _START, _END)
        required = {
            "ad_id", "ad_name", "campaign_id", "campaign_name", "channel",
            "spend", "impressions", "clicks", "conversions", "conversion_value",
            "roas", "ctr", "cpc", "cpa",
        }
        for ad in result["ads"]:
            missing = required - set(ad.keys())
            assert not missing, f"Ad dict missing keys: {missing}"

    def test_tenant_isolation_in_service(
        self, creatives_isolation_client
    ) -> None:
        ctx = creatives_isolation_client
        result = ad_performance(
            ctx["db"], ctx["tenant_a"].id,
            date(2024, 5, 1), date(2024, 5, 1),
        )
        for ad in result["ads"]:
            assert ad["ad_name"] != "Tenant B Ad"

    def test_ga4_channel_excluded_and_does_not_affect_ad_totals(
        self, creatives_client
    ) -> None:
        """Confirms (not a code fix — see Batch A.2 report) that GA4 rows
        can never appear here: the GA4 connector always writes ad_id/ad_name
        as the "(not set)" sentinel (no creative grain), which
        ``_query_ad_aggregates`` already excludes. Adding a GA4 row must
        leave the ads/top/bottom results completely unchanged."""
        db = creatives_client["db"]
        tenant = creatives_client["tenant"]

        acct_ga4 = _make_connected_account(db, tenant, Platform.ga4, "GA4-CR-001")
        ch_ga4 = _make_channel(db, "ga4")
        camp_ga4 = _make_campaign(db, tenant, ch_ga4, "CGA4-CR-001", "(not set)")
        adset_ga4 = _make_adset(db, tenant, camp_ga4, "AGA4-CR-001")
        ad_ga4 = _make_ad(db, tenant, adset_ga4, "ADGA4-CR-001", "(not set)")
        for i in range(7):
            d = _START + timedelta(days=i)
            _insert_fact(
                db, tenant, acct_ga4, ch_ga4, camp_ga4, adset_ga4, ad_ga4, d,
                impressions=0, clicks=0, cost_raw="0",
                conversions="9999", conversion_value_raw="500000.00",
            )
        db.commit()

        tenant_id = tenant.id
        result = ad_performance(db, tenant_id, _START, _END)
        assert len(result["ads"]) == 3
        assert all(a["ad_name"] != "(not set)" for a in result["ads"])
        winner = next(a for a in result["ads"] if a["ad_name"] == "Video — Indirim")
        assert winner["spend"] == pytest.approx(_WINNER_SPEND)
        assert winner["roas"] == pytest.approx(10.0)
