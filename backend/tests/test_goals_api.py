"""Integration tests for the Goal Tracking & Forecasting API.

Strategy
--------
* SQLite in-memory DB via StaticPool — matches the dashboard-test pattern.
* ``db_session`` fixture creates all tables; ``client`` fixture wires the
  app dependency overrides.
* ``seeded_client`` additionally inserts fact rows so compute_progress
  assertions can use known expected values.

Forecast assumptions (tested here)
-----------------------------------
Additive (spend, conversions, conversion_value):
    forecast = (current_value / days_elapsed) * days_total

Ratio (roas):
    forecast = current ROAS (period-average held constant)

Status thresholds:
    on_track   >= 95 % of target
    at_risk    80-95 % of target
    off_track  <  80 % of target

Test coverage
-------------
1.  CRUD: create, list, get, patch, delete (including 404 paths).
2.  Compute-progress math for spend (additive) run-rate forecast.
3.  Compute-progress math for ROAS (ratio) average forecast.
4.  Status thresholds: on_track, at_risk, off_track with seeded facts.
5.  Channel-filtered goal isolates to the correct channel's data.
6.  Tenant isolation: goal created for tenant A is not visible to tenant B.
7.  Recommendation is a non-empty Turkish string.
8.  as_of query parameter is respected.
9.  Validation: invalid metric / period returns 422.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.database import get_db
from ayaz.main import app
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import goals as goals_router_module

# Mount the goals router into the shared app instance if not already present.
# This is done here because main.py cannot be edited as part of this feature;
# the team lead must add the include_router call to main.py for production.
_GOALS_PREFIX = "/api/v1"
_router_already_mounted = any(
    getattr(r, "path", "").startswith("/api/v1/goals")
    for r in app.routes
)
if not _router_already_mounted:
    app.include_router(goals_router_module.router, prefix=_GOALS_PREFIX)
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

_SQLITE_URL = "sqlite://"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session — creates all tables, drops on teardown."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import all model modules so tables are registered on Base.metadata
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.goals  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name, base_currency="USD",
        country="US", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "test@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(), email=email,
        hashed_password=hash_password("pw"),
        full_name="Test User",
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


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=Platform.sample, external_account_id="ACC-001",
        display_name="Test Account", vault_secret_ref="",
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


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant.id,
        channel_id=channel.id, external_id="CAMP-1", name="Camp",
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant.id,
        campaign_id=campaign.id, external_id="ADSET-1", name="AdSet",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant.id,
        ad_set_id=adset.id, external_id="AD-1", name="Ad",
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
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(spend)
    f = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=0,
        clicks=0,
        cost_raw=cost,
        cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value),
        conversion_value_ccy="USD",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.flush()
    return f


def _make_client(db_session: Session, membership: Membership) -> TestClient:
    """Wire the app dependency overrides and return a TestClient."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership
    return TestClient(app)


@pytest.fixture()
def basic_client(db_session: Session):
    """Client with no fact data — for pure CRUD tests."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    client = _make_client(db_session, membership)
    yield client, tenant, membership
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_client(db_session: Session):
    """Client with fact data seeded for a known period.

    Period: 2026-06-01 to 2026-06-30 (30 days).

    Fact rows (channel: google_ads):
      2026-06-01: spend=100, conversions=10, conversion_value=500
      2026-06-02: spend=100, conversions=10, conversion_value=500
      2026-06-03: spend=100, conversions=10, conversion_value=500

    Totals to 2026-06-03 (3 days elapsed of 30):
      spend           = 300
      conversions     = 30
      conversion_value= 1500
      ROAS            = 1500 / 300 = 5.0

    Additive forecast (spend, as_of=2026-06-03, days_elapsed=3, days_total=30):
      daily_rate   = 300 / 3 = 100
      forecast     = 100 * 30 = 3000

    ROAS forecast:
      forecast     = 5.0  (current period-average held constant)

    Channel: meta_ads (separate channel for isolation test)
      2026-06-01: spend=50, conversions=5, conversion_value=250
    """
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    acct = _make_connected_account(db_session, tenant)

    ch_gads = _make_channel(db_session, "google_ads")
    ch_meta = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant, ch_gads)
    adset_g = _make_adset(db_session, tenant, camp_g)
    ad_g = _make_ad(db_session, tenant, adset_g)

    camp_m = _make_campaign(db_session, tenant, ch_meta)
    adset_m = _make_adset(db_session, tenant, camp_m)
    ad_m = _make_ad(db_session, tenant, adset_m)

    for day in (date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)):
        _insert_fact(
            db_session, tenant, acct, ch_gads, camp_g, adset_g, ad_g, day,
            spend="100", conversions="10", conversion_value="500",
        )

    _insert_fact(
        db_session, tenant, acct, ch_meta, camp_m, adset_m, ad_m, date(2026, 6, 1),
        spend="50", conversions="5", conversion_value="250",
    )

    db_session.commit()

    client = _make_client(db_session, membership)
    yield client, tenant, membership
    app.dependency_overrides.clear()


# ── CRUD tests ────────────────────────────────────────────────────────────────


class TestGoalCRUD:
    _BODY = {
        "name": "June ROAS Goal",
        "metric": "roas",
        "target_value": 4.0,
        "period": "month",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
    }

    def test_create_goal_returns_201(self, basic_client):
        client, _, _ = basic_client
        resp = client.post("/api/v1/goals", json=self._BODY)
        assert resp.status_code == 201

    def test_create_goal_returns_correct_fields(self, basic_client):
        client, _, _ = basic_client
        resp = client.post("/api/v1/goals", json=self._BODY)
        body = resp.json()
        assert body["name"] == "June ROAS Goal"
        assert body["metric"] == "roas"
        assert body["target_value"] == pytest.approx(4.0)
        assert body["period"] == "month"
        assert body["period_start"] == "2026-06-01"
        assert body["period_end"] == "2026-06-30"
        assert body["is_active"] is True
        assert "id" in body

    def test_list_goals_returns_created_goal(self, basic_client):
        client, _, _ = basic_client
        client.post("/api/v1/goals", json=self._BODY)
        resp = client.get("/api/v1/goals")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_goals_active_only_excludes_inactive(self, basic_client):
        client, _, _ = basic_client
        # Create one active and one inactive goal
        client.post("/api/v1/goals", json=self._BODY)
        inactive_body = {**self._BODY, "name": "Inactive Goal", "is_active": False}
        client.post("/api/v1/goals", json=inactive_body)

        resp_active = client.get("/api/v1/goals", params={"active_only": True})
        resp_all = client.get("/api/v1/goals", params={"active_only": False})

        assert len(resp_active.json()) == 1
        assert len(resp_all.json()) == 2

    def test_get_goal_returns_200(self, basic_client):
        client, _, _ = basic_client
        created = client.post("/api/v1/goals", json=self._BODY).json()
        resp = client.get(f"/api/v1/goals/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_goal_not_found_returns_404(self, basic_client):
        client, _, _ = basic_client
        resp = client.get(f"/api/v1/goals/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patch_goal_updates_name(self, basic_client):
        client, _, _ = basic_client
        created = client.post("/api/v1/goals", json=self._BODY).json()
        resp = client.patch(
            f"/api/v1/goals/{created['id']}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_patch_goal_updates_is_active(self, basic_client):
        client, _, _ = basic_client
        created = client.post("/api/v1/goals", json=self._BODY).json()
        resp = client.patch(
            f"/api/v1/goals/{created['id']}",
            json={"is_active": False},
        )
        assert resp.json()["is_active"] is False

    def test_patch_goal_not_found_returns_404(self, basic_client):
        client, _, _ = basic_client
        resp = client.patch(f"/api/v1/goals/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404

    def test_delete_goal_returns_204(self, basic_client):
        client, _, _ = basic_client
        created = client.post("/api/v1/goals", json=self._BODY).json()
        resp = client.delete(f"/api/v1/goals/{created['id']}")
        assert resp.status_code == 204

    def test_delete_goal_then_not_found(self, basic_client):
        client, _, _ = basic_client
        created = client.post("/api/v1/goals", json=self._BODY).json()
        client.delete(f"/api/v1/goals/{created['id']}")
        resp = client.get(f"/api/v1/goals/{created['id']}")
        assert resp.status_code == 404

    def test_delete_goal_not_found_returns_404(self, basic_client):
        client, _, _ = basic_client
        resp = client.delete(f"/api/v1/goals/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_create_invalid_metric_returns_422(self, basic_client):
        client, _, _ = basic_client
        body = {**self._BODY, "metric": "impressions"}
        resp = client.post("/api/v1/goals", json=body)
        assert resp.status_code == 422

    def test_create_invalid_period_returns_422(self, basic_client):
        client, _, _ = basic_client
        body = {**self._BODY, "period": "quarter"}
        resp = client.post("/api/v1/goals", json=body)
        assert resp.status_code == 422

    def test_create_invalid_date_order_returns_422(self, basic_client):
        client, _, _ = basic_client
        body = {**self._BODY, "period_start": "2026-06-30", "period_end": "2026-06-01"}
        resp = client.post("/api/v1/goals", json=body)
        assert resp.status_code == 422

    def test_create_zero_target_returns_422(self, basic_client):
        client, _, _ = basic_client
        body = {**self._BODY, "target_value": 0}
        resp = client.post("/api/v1/goals", json=body)
        assert resp.status_code == 422

    def test_channel_filter_stored_correctly(self, basic_client):
        client, _, _ = basic_client
        body = {**self._BODY, "channel_filter": "google_ads"}
        created = client.post("/api/v1/goals", json=body).json()
        assert created["channel_filter"] == "google_ads"


# ── Progress / forecast tests ─────────────────────────────────────────────────


class TestGoalProgress:
    """Tests for GET /goals/{id}/progress with seeded fact data."""

    # Period: 2026-06-01 to 2026-06-30 (30 days)
    # as_of:  2026-06-03  → 3 days elapsed of 30
    # google_ads totals: spend=300, conv=30, cv=1500, ROAS=5.0

    _PERIOD = {"period_start": "2026-06-01", "period_end": "2026-06-30"}
    _AS_OF = "2026-06-03"

    def _create_goal(self, client, metric: str, target: float, channel: str | None = None) -> dict:
        body: dict = {
            "name": f"Test {metric}",
            "metric": metric,
            "target_value": target,
            "period": "month",
            **self._PERIOD,
        }
        if channel:
            body["channel_filter"] = channel
        resp = client.post("/api/v1/goals", json=body)
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _progress(self, client, goal_id: str, as_of: str = _AS_OF) -> dict:
        resp = client.get(
            f"/api/v1/goals/{goal_id}/progress",
            params={"as_of": as_of},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # -- Spend (additive) forecast ----

    # NOTE: All tests below use channel_filter="google_ads" to get deterministic
    # values (300 spend / 30 conv / 1500 cv across 3 days).
    # An unfiltered goal aggregates both channels: google_ads (300) + meta_ads (50) = 350.

    def test_spend_current_value(self, seeded_client):
        """current_value for spend (google_ads only) = 300 (3 days * 100)."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(300.0)

    def test_spend_forecast_run_rate(self, seeded_client):
        """forecast = (300 / 3) * 30 = 3000."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["forecast_value"] == pytest.approx(3000.0)

    def test_spend_on_track(self, seeded_client):
        """Forecast 3000 vs target 3000 → on_track (100%)."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "on_track"

    def test_spend_at_risk(self, seeded_client):
        """Forecast 3000 vs target 3600 → 83.3% → at_risk."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3600.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "at_risk"

    def test_spend_off_track(self, seeded_client):
        """Forecast 3000 vs target 5000 → 60% → off_track."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 5000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "off_track"

    # -- Conversions (additive) forecast ----

    def test_conversions_forecast(self, seeded_client):
        """forecast = (30 / 3) * 30 = 300."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "conversions", 300.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(30.0)
        assert p["forecast_value"] == pytest.approx(300.0)

    def test_conversion_value_forecast(self, seeded_client):
        """forecast = (1500 / 3) * 30 = 15000."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "conversion_value", 15000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(1500.0)
        assert p["forecast_value"] == pytest.approx(15000.0)

    # -- ROAS (ratio) forecast ----

    def test_roas_current_value(self, seeded_client):
        """current ROAS (google_ads) = 1500 / 300 = 5.0."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "roas", 5.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(5.0, rel=1e-4)

    def test_roas_forecast_equals_current(self, seeded_client):
        """ROAS forecast = current period-average = 5.0."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "roas", 5.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["forecast_value"] == pytest.approx(5.0, rel=1e-4)

    def test_roas_on_track(self, seeded_client):
        """ROAS forecast 5.0 vs target 5.0 → on_track."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "roas", 5.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "on_track"

    def test_roas_at_risk(self, seeded_client):
        """ROAS forecast 5.0 vs target 5.8 → 86.2% → at_risk."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "roas", 5.8, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "at_risk"

    def test_roas_off_track(self, seeded_client):
        """ROAS forecast 5.0 vs target 7.0 → 71.4% → off_track."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "roas", 7.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["status"] == "off_track"

    # -- Days / pace fields ----

    def test_days_elapsed_and_total(self, seeded_client):
        """3 days elapsed of 30 total."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["days_elapsed"] == 3
        assert p["days_total"] == 30

    def test_expected_pace_value(self, seeded_client):
        """expected_pace = 3000 * (3/30) = 300."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["expected_pace_value"] == pytest.approx(300.0)

    def test_pct_to_target(self, seeded_client):
        """pct_to_target = 300 / 3000 = 0.1."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert p["pct_to_target"] == pytest.approx(0.1)

    # -- Channel filter ----

    def test_channel_filter_restricts_to_channel(self, seeded_client):
        """A google_ads-filtered goal should see only google_ads data (300 spend),
        not meta_ads (50 spend).  Total without filter would be 350."""
        client, _, _ = seeded_client
        goal_all = self._create_goal(client, "spend", 9999.0)
        goal_gads = self._create_goal(client, "spend", 9999.0, channel="google_ads")
        goal_meta = self._create_goal(client, "spend", 9999.0, channel="meta_ads")

        p_all = self._progress(client, goal_all["id"])
        p_gads = self._progress(client, goal_gads["id"])
        p_meta = self._progress(client, goal_meta["id"])

        # All channels: 300 (google) + 50 (meta) = 350
        assert p_all["current_value"] == pytest.approx(350.0)
        # google_ads only: 300
        assert p_gads["current_value"] == pytest.approx(300.0)
        # meta_ads only: 50
        assert p_meta["current_value"] == pytest.approx(50.0)

    # -- Recommendation ----

    def test_recommendation_is_string(self, seeded_client):
        """recommendation field must be a non-empty string."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        assert isinstance(p["recommendation"], str)
        assert len(p["recommendation"]) > 0

    def test_recommendation_on_track_message(self, seeded_client):
        """On-track goals get a Turkish positive message."""
        client, _, _ = seeded_client
        # Exactly on track: forecast=3000 vs target=3000
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"])
        # The recommendation should indicate success (Turkish: "yolunda")
        assert "yolunda" in p["recommendation"].lower() or "hedef" in p["recommendation"].lower()

    # -- as_of parameter ----

    def test_as_of_day_1_elapsed(self, seeded_client):
        """as_of=2026-06-01 → days_elapsed=1, current_value=100 (google_ads only)."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"], as_of="2026-06-01")
        assert p["days_elapsed"] == 1
        assert p["current_value"] == pytest.approx(100.0)

    def test_as_of_before_period_start_gives_zero(self, seeded_client):
        """as_of before period → days_elapsed=0, forecast=0."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"], as_of="2026-05-31")
        assert p["days_elapsed"] == 0
        assert p["forecast_value"] == pytest.approx(0.0)

    def test_as_of_after_period_end_clamps(self, seeded_client):
        """as_of after period_end → days_elapsed == days_total."""
        client, _, _ = seeded_client
        goal = self._create_goal(client, "spend", 3000.0, channel="google_ads")
        p = self._progress(client, goal["id"], as_of="2026-07-15")
        assert p["days_elapsed"] == p["days_total"]

    # -- Progress endpoint 404 ----

    def test_progress_not_found_returns_404(self, basic_client):
        client, _, _ = basic_client
        resp = client.get(
            f"/api/v1/goals/{uuid.uuid4()}/progress",
            params={"as_of": "2026-06-03"},
        )
        assert resp.status_code == 404


# ── Kaynak-tipi mutabakatı (ad + analytics) regression tests ──────────────────


@pytest.fixture()
def seeded_client_ga4(db_session: Session):
    """Client with google_ads (ad) + ga4 (analytics) fact data for the same
    3-day window, to regression-test the account-wide (no channel_filter)
    goal progress fix.

    google_ads: 2026-07-01..03, spend=100/day, conversions=10/day,
                conversion_value=500/day (ad totals: 300 / 30 / 1500)
    ga4:        2026-07-01..03, spend=0, clicks=0, conversions=200/day,
                conversion_value=45000/day (analytics totals: 0 / 600 / 135000)
    """
    tenant = _make_tenant(db_session, "GA4 Mixed Tenant")
    user = _make_user(db_session, "ga4_goals@ayaz.app")
    membership = _make_membership(db_session, user, tenant)
    acct = _make_connected_account(db_session, tenant)

    ch_gads = _make_channel(db_session, "google_ads")
    ch_ga4 = _make_channel(db_session, "ga4")

    camp_g = _make_campaign(db_session, tenant, ch_gads)
    adset_g = _make_adset(db_session, tenant, camp_g)
    ad_g = _make_ad(db_session, tenant, adset_g)

    camp_a = _make_campaign(db_session, tenant, ch_ga4)
    adset_a = _make_adset(db_session, tenant, camp_a)
    ad_a = _make_ad(db_session, tenant, adset_a)

    for day in (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)):
        _insert_fact(
            db_session, tenant, acct, ch_gads, camp_g, adset_g, ad_g, day,
            spend="100", conversions="10", conversion_value="500",
        )
        _insert_fact(
            db_session, tenant, acct, ch_ga4, camp_a, adset_a, ad_a, day,
            spend="0", conversions="200", conversion_value="45000",
        )

    db_session.commit()

    client = _make_client(db_session, membership)
    yield client, tenant, membership
    app.dependency_overrides.clear()


class TestGoalProgressSourceTypeSplit:
    """Account-wide (no channel_filter) goal progress must not double-count
    GA4's conversions/revenue on top of what google_ads already reports."""

    _PERIOD = {"period_start": "2026-07-01", "period_end": "2026-07-30"}
    _AS_OF = "2026-07-03"

    def _create_goal(self, client, metric: str, target: float) -> dict:
        resp = client.post(
            "/api/v1/goals",
            json={
                "name": f"Mixed {metric}",
                "metric": metric,
                "target_value": target,
                "period": "month",
                **self._PERIOD,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _progress(self, client, goal_id: str) -> dict:
        resp = client.get(
            f"/api/v1/goals/{goal_id}/progress",
            params={"as_of": self._AS_OF},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_conversions_not_double_counted(self, seeded_client_ga4):
        """Historically-buggy total = 30(ad)+600(ga4)=630. Correct: GA4 wins
        as source of truth -> 600 (NOT summed with the ad platform's own 30)."""
        client, _, _ = seeded_client_ga4
        goal = self._create_goal(client, "conversions", 6000.0)
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(600.0)
        assert p["current_value"] != pytest.approx(630.0)

    def test_conversion_value_ga4_wins(self, seeded_client_ga4):
        """ad conversion_value=1500, ga4=135000. Historically-buggy total
        would be 136500; correct is 135000 (GA4 wins)."""
        client, _, _ = seeded_client_ga4
        goal = self._create_goal(client, "conversion_value", 200000.0)
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(135000.0)
        assert p["current_value"] != pytest.approx(136500.0)

    def test_spend_is_ad_only_unaffected(self, seeded_client_ga4):
        """GA4 contributes 0 spend — total spend must equal google_ads' own
        300 (spend was never part of the double-counting bug)."""
        client, _, _ = seeded_client_ga4
        goal = self._create_goal(client, "spend", 3000.0)
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(300.0)

    def test_roas_is_blended_not_summed(self, seeded_client_ga4):
        """Historically-buggy ROAS = (1500+135000)/300 = 455.0. Correct
        blended ROAS = ga4_revenue / ad_spend = 135000/300 = 450.0."""
        client, _, _ = seeded_client_ga4
        goal = self._create_goal(client, "roas", 450.0)
        p = self._progress(client, goal["id"])
        assert p["current_value"] == pytest.approx(450.0, rel=1e-4)
        assert p["current_value"] != pytest.approx(455.0, rel=1e-4)

    def test_channel_filtered_goal_unaffected_by_split(self, seeded_client_ga4):
        """A goal explicitly filtered to channel='google_ads' must see only
        the ad platform's own numbers — untouched by the account-wide fix."""
        client, _, _ = seeded_client_ga4
        resp = client.post(
            "/api/v1/goals",
            json={
                "name": "Filtered",
                "metric": "conversions",
                "target_value": 300.0,
                "channel_filter": "google_ads",
                "period": "month",
                **self._PERIOD,
            },
        )
        assert resp.status_code == 201, resp.text
        p = self._progress(client, resp.json()["id"])
        assert p["current_value"] == pytest.approx(30.0)

    def test_channel_filtered_ga4_goal(self, seeded_client_ga4):
        """A goal filtered to channel='ga4' must see only GA4's own numbers."""
        client, _, _ = seeded_client_ga4
        resp = client.post(
            "/api/v1/goals",
            json={
                "name": "GA4 Filtered",
                "metric": "conversions",
                "target_value": 6000.0,
                "channel_filter": "ga4",
                "period": "month",
                **self._PERIOD,
            },
        )
        assert resp.status_code == 201, resp.text
        p = self._progress(client, resp.json()["id"])
        assert p["current_value"] == pytest.approx(600.0)


# ── Tenant isolation test ─────────────────────────────────────────────────────


class TestTenantIsolation:
    """Verify that goals and progress cannot be accessed cross-tenant."""

    def test_goal_not_visible_to_other_tenant(self, db_session: Session):
        """A goal created for tenant A is invisible to tenant B."""
        # Tenant A
        tenant_a = _make_tenant(db_session, "Tenant A")
        user_a = _make_user(db_session, "a@ayaz.app")
        mem_a = _make_membership(db_session, user_a, tenant_a)

        # Tenant B
        tenant_b = _make_tenant(db_session, "Tenant B")
        user_b = _make_user(db_session, "b@ayaz.app")
        mem_b = _make_membership(db_session, user_b, tenant_b)

        db_session.commit()

        # Create a goal as tenant A
        client_a = _make_client(db_session, mem_a)
        resp = client_a.post(
            "/api/v1/goals",
            json={
                "name": "Tenant A Goal",
                "metric": "spend",
                "target_value": 1000.0,
                "period": "month",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
            },
        )
        assert resp.status_code == 201
        goal_id = resp.json()["id"]

        app.dependency_overrides.clear()

        # Tenant B cannot see tenant A's goal
        client_b = _make_client(db_session, mem_b)
        resp_list = client_b.get("/api/v1/goals")
        assert resp_list.status_code == 200
        assert len(resp_list.json()) == 0

        resp_get = client_b.get(f"/api/v1/goals/{goal_id}")
        assert resp_get.status_code == 404

        app.dependency_overrides.clear()
