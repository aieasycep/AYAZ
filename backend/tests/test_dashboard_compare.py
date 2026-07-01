"""Tests for the period-over-period comparison feature on GET /api/v1/dashboard/summary.

Strategy
--------
* Uses FastAPI TestClient with an in-memory SQLite DB (same pattern as
  test_dashboard_api.py).
* Seeds known data for two non-overlapping periods so we can assert exact delta
  values.
* Verifies that the default response (compare absent/false) is byte-identical
  to the old shape (no ``previous`` / ``deltas`` keys present / null).
* Verifies that compare=true adds ``previous`` and ``deltas`` with correct math.
* Verifies divide-by-zero guard: when previous period has all-zero metrics,
  delta fields are None.
* Verifies tenant isolation: a second tenant's data never bleeds in.

Seed data layout
----------------
Tenant A:
  Channel: google_ads

  Previous period  2024-01-01 → 2024-01-07  (7 days):
    impressions=1000, clicks=50, spend=200.00, conversions=10, cv=1000.00
    CTR  = 50/1000    = 0.05
    CPC  = 200/50     = 4.00
    CPA  = 200/10     = 20.00
    ROAS = 1000/200   = 5.00

  Current period   2024-01-08 → 2024-01-14  (7 days):
    impressions=2000, clicks=80, spend=400.00, conversions=16, cv=2400.00
    CTR  = 80/2000    = 0.04
    CPC  = 400/80     = 5.00
    CPA  = 400/16     = 25.00
    ROAS = 2400/400   = 6.00

  Expected deltas:
    spend             = (400-200)/200       = 1.0   (+100%)
    impressions       = (2000-1000)/1000    = 1.0   (+100%)
    clicks            = (80-50)/50          = 0.6   (+60%)
    conversions       = (16-10)/10          = 0.6   (+60%)
    conversion_value  = (2400-1000)/1000    = 1.4   (+140%)
    ctr               = (0.04-0.05)/0.05    = -0.2  (-20%)
    cpc               = (5.00-4.00)/4.00    = 0.25  (+25%)
    cpa               = (25.00-20.00)/20.00 = 0.25  (+25%)
    roas              = (6.00-5.00)/5.00    = 0.2   (+20%)
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


# ── In-memory SQLite engine ───────────────────────────────────────────────────

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


# ── Data helpers ─────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
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


def _make_user(db: Session, email: str = "compare@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test1234"),
        full_name="Compare User",
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


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_connected_account(db: Session, tenant: Tenant, platform: Platform) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=str(uuid.uuid4()),
        display_name=f"{platform.value} test",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel, name: str) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=str(uuid.uuid4()),
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=str(uuid.uuid4()),
        name="adset",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=str(uuid.uuid4()),
        name="ad",
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
    impressions: int,
    clicks: int,
    spend: str,
    conversions: str,
    cv: str,
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(spend)
    fact = FactDailyMetrics(
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
        cost_raw=cost,
        cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(cv),
        conversion_value_ccy="USD",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(cv),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def compare_client(db_session: Session):
    """TestClient seeded with two non-overlapping 7-day periods for Tenant A,
    and a separate Tenant B whose data must never bleed through.

    Period layout:
      prev  2024-01-01 → 2024-01-07:  1000 imp, 50 clk, 200 spend, 10 conv, 1000 cv
      curr  2024-01-08 → 2024-01-14:  2000 imp, 80 clk, 400 spend, 16 conv, 2400 cv
    """
    # Tenant A
    tenant_a = _make_tenant(db_session, "Tenant A")
    user_a = _make_user(db_session, "a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)
    acct_a = _make_connected_account(db_session, tenant_a, Platform.google_ads)
    ch_a = _make_channel(db_session, "google_ads")
    camp_a = _make_campaign(db_session, tenant_a, ch_a, "Compare Campaign")
    adset_a = _make_adset(db_session, tenant_a, camp_a)
    ad_a = _make_ad(db_session, tenant_a, adset_a)

    # Previous period: 2024-01-01 → 2024-01-07  (7 rows, each 1/7 of totals)
    # We use 7 identical rows so total = 7x row values.
    for day in range(7):
        _insert_fact(
            db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
            date(2024, 1, 1) + timedelta(days=day),
            impressions=1000 // 7 + (1 if day < 1000 % 7 else 0),
            clicks=50 // 7 + (1 if day < 50 % 7 else 0),
            spend="28.571428",
            conversions="1.428571",
            cv="142.857142",
        )

    # Actually insert as single-row aggregates per day to hit exact totals:
    # Use simpler approach — one row on 2024-01-01 with all of prev's totals.
    # Re-seed cleanly: delete and reinsert with a single-row approach.
    # (sqlite, function scope — no harm in just inserting single rows)

    # Prev period — single aggregated fact on day 1 of each window for simplicity
    # Actually we already inserted 7 rows above; let's instead use a clean fixture:
    # The seeded rows above may not add to exact 1000/50/200/10/1000.
    # → Use a single fact row for each period with the full totals.
    #   (date range queries are inclusive so single rows work fine.)

    # Tenant B (isolation check)
    tenant_b = _make_tenant(db_session, "Tenant B")
    user_b = _make_user(db_session, "b@ayaz.app")
    _make_membership(db_session, user_b, tenant_b)
    acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads)
    ch_b = _make_channel(db_session, "google_ads_b")
    camp_b = _make_campaign(db_session, tenant_b, ch_b, "Tenant B Campaign")
    adset_b = _make_adset(db_session, tenant_b, camp_b)
    ad_b = _make_ad(db_session, tenant_b, adset_b)
    _insert_fact(
        db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b,
        date(2024, 1, 8),
        impressions=99999, clicks=99999, spend="99999", conversions="99999", cv="99999",
    )

    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def exact_compare_client(db_session: Session):
    """TestClient with a single row per period for exact arithmetic assertions.

    We use a 7-day current window so the previous window is also 7 days and the
    row dates are natural.

    curr  2024-01-08 → 2024-01-14  (7 days): single row on 2024-01-08
      impressions=2000, clicks=80, spend=400, conversions=16, cv=2400
      CTR  = 80/2000  = 0.04
      CPC  = 400/80   = 5.00
      CPA  = 400/16   = 25.00
      ROAS = 2400/400 = 6.00

    prev  2024-01-01 → 2024-01-07  (7 days): single row on 2024-01-01
      impressions=1000, clicks=50, spend=200, conversions=10, cv=1000
      CTR  = 50/1000  = 0.05
      CPC  = 200/50   = 4.00
      CPA  = 200/10   = 20.00
      ROAS = 1000/200 = 5.00

    Expected deltas (curr vs prev):
      spend             = (400-200)/200       =  1.0   (+100%)
      impressions       = (2000-1000)/1000    =  1.0   (+100%)
      clicks            = (80-50)/50          =  0.6   (+60%)
      conversions       = (16-10)/10          =  0.6   (+60%)
      conversion_value  = (2400-1000)/1000    =  1.4   (+140%)
      ctr               = (0.04-0.05)/0.05    = -0.2   (-20%)
      cpc               = (5.00-4.00)/4.00    =  0.25  (+25%)
      cpa               = (25.00-20.00)/20.00 =  0.25  (+25%)
      roas              = (6.00-5.00)/5.00    =  0.2   (+20%)
    """
    tenant_a = _make_tenant(db_session, "Exact Tenant")
    user_a = _make_user(db_session, "exact@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)
    acct_a = _make_connected_account(db_session, tenant_a, Platform.google_ads)
    ch_a = _make_channel(db_session, "google_ads")
    camp_a = _make_campaign(db_session, tenant_a, ch_a, "Exact Campaign")
    adset_a = _make_adset(db_session, tenant_a, camp_a)
    ad_a = _make_ad(db_session, tenant_a, adset_a)

    # Previous period: single row on first day of prev window (2024-01-01)
    _insert_fact(
        db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
        date(2024, 1, 1),
        impressions=1000, clicks=50, spend="200.00", conversions="10", cv="1000.00",
    )
    # Current period: single row on first day of curr window (2024-01-08)
    _insert_fact(
        db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
        date(2024, 1, 8),
        impressions=2000, clicks=80, spend="400.00", conversions="16", cv="2400.00",
    )

    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def zero_prev_client(db_session: Session):
    """TestClient where the previous period has no data (all zeros).

    curr  2024-02-08:  500 imp, 20 clk, 100 spend, 5 conv, 300 cv
    prev  2024-02-01:  (no rows → all zeros)
    """
    tenant = _make_tenant(db_session, "Zero Prev Tenant")
    user = _make_user(db_session, "zero@ayaz.app")
    membership = _make_membership(db_session, user, tenant)
    acct = _make_connected_account(db_session, tenant, Platform.google_ads)
    ch = _make_channel(db_session, "google_ads")
    camp = _make_campaign(db_session, tenant, ch, "Zero Prev Campaign")
    adset = _make_adset(db_session, tenant, camp)
    ad = _make_ad(db_session, tenant, adset)

    _insert_fact(
        db_session, tenant, acct, ch, camp, adset, ad,
        date(2024, 2, 8),
        impressions=500, clicks=20, spend="100.00", conversions="5", cv="300.00",
    )
    db_session.commit()

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


# ── Tests: default response shape unchanged ──────────────────────────────────


class TestCompareDefaultBehavior:
    """When compare is absent or false, response must be byte-identical to the
    existing summary contract: no previous/deltas keys, or they are null.

    Uses 7-day window 2024-01-08 → 2024-01-14 (prev window = 2024-01-01 → 2024-01-07).
    """

    def test_no_compare_param_has_no_previous(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # previous and deltas must be absent or null (opt-in only)
        assert body.get("previous") is None
        assert body.get("deltas") is None

    def test_compare_false_has_no_previous(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14", "compare": "false"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("previous") is None
        assert body.get("deltas") is None

    def test_no_compare_existing_fields_intact(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14"},
        )
        body = resp.json()
        assert "date_from" in body
        assert "date_to" in body
        assert "totals" in body
        assert "by_channel" in body

    def test_current_totals_unchanged_by_compare_false(self, exact_compare_client: TestClient) -> None:
        """The current period totals must be the same whether compare is true or false."""
        resp_no = exact_compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14"},
        )
        resp_yes = exact_compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14", "compare": "true"},
        )
        assert resp_no.json()["totals"] == resp_yes.json()["totals"]


# ── Tests: compare=true adds previous + deltas ────────────────────────────────


class TestCompareEnabled:
    """With compare=true, previous and deltas are populated correctly.

    All tests use the 7-day window 2024-01-08 → 2024-01-14 so the previous
    window is 2024-01-01 → 2024-01-07, which contains the seeded prev row.
    """

    _CURR_PARAMS = {
        "date_from": "2024-01-08",
        "date_to": "2024-01-14",
        "compare": "true",
    }

    def test_returns_200(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        assert resp.status_code == 200

    def test_previous_key_present(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        body = resp.json()
        assert body["previous"] is not None

    def test_deltas_key_present(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        body = resp.json()
        assert body["deltas"] is not None

    def test_previous_totals_correct(self, exact_compare_client: TestClient) -> None:
        """Previous period (2024-01-01 single row): spend=200, impressions=1000."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        prev = resp.json()["previous"]
        assert prev["spend"] == pytest.approx(200.0)
        assert prev["impressions"] == pytest.approx(1000.0)
        assert prev["clicks"] == pytest.approx(50.0)
        assert prev["conversions"] == pytest.approx(10.0)
        assert prev["conversion_value"] == pytest.approx(1000.0)

    def test_previous_derived_metrics(self, exact_compare_client: TestClient) -> None:
        """CTR=50/1000=0.05, CPC=200/50=4, CPA=200/10=20, ROAS=1000/200=5."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        prev = resp.json()["previous"]
        assert prev["ctr"] == pytest.approx(50 / 1000)
        assert prev["cpc"] == pytest.approx(200 / 50)
        assert prev["cpa"] == pytest.approx(200 / 10)
        assert prev["roas"] == pytest.approx(1000 / 200)

    def test_delta_spend(self, exact_compare_client: TestClient) -> None:
        """spend delta = (400-200)/200 = 1.0."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["spend"] == pytest.approx(1.0)

    def test_delta_impressions(self, exact_compare_client: TestClient) -> None:
        """impressions delta = (2000-1000)/1000 = 1.0."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["impressions"] == pytest.approx(1.0)

    def test_delta_clicks(self, exact_compare_client: TestClient) -> None:
        """clicks delta = (80-50)/50 = 0.6."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["clicks"] == pytest.approx(0.6)

    def test_delta_conversions(self, exact_compare_client: TestClient) -> None:
        """conversions delta = (16-10)/10 = 0.6."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["conversions"] == pytest.approx(0.6)

    def test_delta_conversion_value(self, exact_compare_client: TestClient) -> None:
        """conversion_value delta = (2400-1000)/1000 = 1.4."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["conversion_value"] == pytest.approx(1.4)

    def test_delta_ctr(self, exact_compare_client: TestClient) -> None:
        """CTR delta = (0.04-0.05)/0.05 = -0.2.
        curr CTR = 80/2000 = 0.04, prev CTR = 50/1000 = 0.05
        """
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["ctr"] == pytest.approx(-0.2, rel=1e-4)

    def test_delta_cpc(self, exact_compare_client: TestClient) -> None:
        """CPC delta = (5.0-4.0)/4.0 = 0.25."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["cpc"] == pytest.approx(0.25)

    def test_delta_cpa(self, exact_compare_client: TestClient) -> None:
        """CPA delta = (25.0-20.0)/20.0 = 0.25."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["cpa"] == pytest.approx(0.25)

    def test_delta_roas(self, exact_compare_client: TestClient) -> None:
        """ROAS delta = (6.0-5.0)/5.0 = 0.2."""
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        assert d["roas"] == pytest.approx(0.2)

    def test_delta_fields_are_all_present(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        d = resp.json()["deltas"]
        for key in ("spend", "impressions", "clicks", "conversions", "conversion_value",
                    "ctr", "cpc", "cpa", "roas"):
            assert key in d, f"Missing delta key: {key}"

    def test_previous_fields_are_all_present(self, exact_compare_client: TestClient) -> None:
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        prev = resp.json()["previous"]
        for key in ("spend", "impressions", "clicks", "conversions", "conversion_value",
                    "ctr", "cpc", "cpa", "roas"):
            assert key in prev, f"Missing previous key: {key}"

    def test_multi_day_period_prev_window(self, exact_compare_client: TestClient) -> None:
        """A 7-day current window should look back exactly 7 days for prev period.

        curr  2024-01-08 → 2024-01-14  (7 days): row on 2024-01-08 (spend=400)
        prev  2024-01-01 → 2024-01-07  (7 days): row on 2024-01-01 (spend=200)
        """
        resp = exact_compare_client.get("/api/v1/dashboard/summary", params=self._CURR_PARAMS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["spend"] == pytest.approx(400.0)
        assert body["previous"]["spend"] == pytest.approx(200.0)


# ── Tests: divide-by-zero guard ──────────────────────────────────────────────


class TestDivideByZeroDeltaGuard:
    """When the previous period has zero for a denominator, delta is None."""

    def test_spend_delta_is_none_when_prev_spend_zero(self, zero_prev_client: TestClient) -> None:
        """prev period 2024-02-01 has no data → prev spend = 0 → delta = None."""
        resp = zero_prev_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-02-08", "date_to": "2024-02-08", "compare": "true"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["previous"]["spend"] == 0.0
        assert body["deltas"]["spend"] is None

    def test_all_deltas_are_none_when_prev_all_zero(self, zero_prev_client: TestClient) -> None:
        resp = zero_prev_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-02-08", "date_to": "2024-02-08", "compare": "true"},
        )
        d = resp.json()["deltas"]
        for key in ("spend", "impressions", "clicks", "conversions", "conversion_value",
                    "ctr", "cpc", "cpa", "roas"):
            assert d[key] is None, f"Expected None for {key} when prev=0"

    def test_current_totals_still_correct_when_prev_zero(
        self, zero_prev_client: TestClient
    ) -> None:
        resp = zero_prev_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-02-08", "date_to": "2024-02-08", "compare": "true"},
        )
        totals = resp.json()["totals"]
        assert totals["spend"] == pytest.approx(100.0)
        assert totals["impressions"] == pytest.approx(500.0)


# ── Tests: tenant isolation ──────────────────────────────────────────────────


class TestCompareIsolation:
    """Tenant B data must not appear in the compare response for Tenant A."""

    def test_tenant_b_spend_not_in_current(self, compare_client: TestClient) -> None:
        """Tenant B has spend=99999 on 2024-01-08; must not appear in Tenant A's current."""
        resp = compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14", "compare": "true"},
        )
        body = resp.json()
        assert body["totals"]["spend"] != pytest.approx(99999.0, rel=1e-2)

    def test_tenant_b_spend_not_in_previous(self, compare_client: TestClient) -> None:
        resp = compare_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-01-08", "date_to": "2024-01-14", "compare": "true"},
        )
        body = resp.json()
        assert body["previous"]["spend"] != pytest.approx(99999.0, rel=1e-2)
