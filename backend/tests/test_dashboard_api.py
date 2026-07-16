"""Integration tests for the dashboard API.

Strategy
--------
* Uses FastAPI TestClient (synchronous HTTPX transport) — no live Uvicorn.
* Replaces the production SQLAlchemy engine with an in-memory SQLite DB for
  the duration of the test session.  SQLite is fully compatible with the
  models used by the dashboard queries (no Postgres-only features are used).
* The ``db_session`` fixture creates all tables, yields a Session, and drops
  all tables on teardown.
* The FastAPI ``get_db`` dependency is overridden to return this test Session.
* The ``membership`` dependency is overridden to return a pre-built Membership
  so we don't need a full signup/login round-trip in every test.
* A ``seeded_client`` fixture inserts a known set of fact rows so assertions
  can use hard-coded expected values.

Hermeticity
-----------
* No live Postgres, no live network, no fixture files read by this module.
* All fact data is inserted directly into the SQLite DB using the ORM.

SQLite limitations
------------------
* SQLite does not support ``UUID`` columns natively; SQLAlchemy maps them to
  TEXT, which works because our models use Python ``uuid.UUID`` objects and
  SQLAlchemy handles the conversion.
* ``func.coalesce`` is supported by SQLite.
* Enum columns work as TEXT in SQLite.
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
from ayaz.services.auth import create_access_token, hash_password


# ── In-memory SQLite engine ───────────────────────────────────────────────────

_SQLITE_URL = "sqlite://"  # pure in-memory


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite DB, yield a Session, then drop everything."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import all model modules so their tables are registered on Base.metadata
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


# ── Demo data helpers ─────────────────────────────────────────────────────────


def _make_tenant(db: Session) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Test Tenant",
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    db.add(tenant)
    db.flush()
    return tenant


def _make_user(db: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email="test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Test User",
    )
    db.add(user)
    db.flush()
    return user


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
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=ext_id,
        display_name=f"{platform.value} test account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


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


def _make_ad(
    db: Session, tenant: Tenant, adset: DimAdSet, ext_id: str
) -> DimAd:
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
    connected_account: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    d: date,
    *,
    impressions: int = 0,
    clicks: int = 0,
    cost_raw: str = "0",
    conversions: str = "0",
    conversion_value_raw: str = "0",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(cost_raw)
    fact = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=connected_account.id,
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


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def seeded_client(db_session: Session):
    """Return a TestClient with:
    - DB dependency overridden to use the test SQLite session.
    - Membership dependency overridden to return a fixed membership.
    - A set of known fact rows inserted.

    Fact rows inserted
    ------------------
    Channel: sample
      2024-03-15: impressions=100, clicks=10, spend=50.00, conv=2, cv=200.00
      2024-03-16: impressions=200, clicks=20, spend=100.00, conv=4, cv=400.00

    Channel: google_ads
      2024-03-15: impressions=500, clicks=25, spend=75.00, conv=5, cv=375.00

    Summary totals for 2024-03-15 → 2024-03-16:
      impressions=800, clicks=55, spend=225.00, conv=11, cv=975.00
      CTR  = 55/800  = 0.06875
      CPC  = 225/55  ≈ 4.0909...
      CPA  = 225/11  ≈ 20.4545...
      ROAS = 975/225 ≈ 4.3333...
    """
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_sample = _make_connected_account(
        db_session, tenant, Platform.sample, "ACC-001"
    )
    acct_gads = _make_connected_account(
        db_session, tenant, Platform.google_ads, "1234567890"
    )

    ch_sample = _make_channel(db_session, "sample")
    ch_gads = _make_channel(db_session, "google_ads")

    camp_s = _make_campaign(db_session, tenant, ch_sample, "CAMP-100", "Spring Sale")
    adset_s = _make_adset(db_session, tenant, camp_s, "ADSET-200")
    ad_s = _make_ad(db_session, tenant, adset_s, "AD-300")

    camp_g = _make_campaign(db_session, tenant, ch_gads, "111000001", "Summer Promo")
    adset_g = _make_adset(db_session, tenant, camp_g, "(not set)")
    ad_g = _make_ad(db_session, tenant, adset_g, "(not set)")

    # sample rows
    _insert_fact(
        db_session, tenant, acct_sample, ch_sample, camp_s, adset_s, ad_s,
        date(2024, 3, 15),
        impressions=100, clicks=10, cost_raw="50.00",
        conversions="2", conversion_value_raw="200.00",
    )
    _insert_fact(
        db_session, tenant, acct_sample, ch_sample, camp_s, adset_s, ad_s,
        date(2024, 3, 16),
        impressions=200, clicks=20, cost_raw="100.00",
        conversions="4", conversion_value_raw="400.00",
    )
    # google_ads row
    _insert_fact(
        db_session, tenant, acct_gads, ch_gads, camp_g, adset_g, ad_g,
        date(2024, 3, 15),
        impressions=500, clicks=25, cost_raw="75.00",
        conversions="5", conversion_value_raw="375.00",
    )
    db_session.commit()

    # Override get_db to return our test session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # keep the session alive; closed by the fixture

    # Override membership dependency to return our fixed membership
    def override_get_membership():
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ── Summary endpoint tests ────────────────────────────────────────────────────


class TestSummaryEndpoint:
    def test_returns_200(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.status_code == 200

    def test_response_has_required_keys(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert "date_from" in body
        assert "date_to" in body
        assert "totals" in body
        assert "by_channel" in body

    def test_totals_spend(self, seeded_client: TestClient) -> None:
        """Total spend = 50 + 100 + 75 = 225."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["spend"] == pytest.approx(225.0)

    def test_totals_impressions(self, seeded_client: TestClient) -> None:
        """Total impressions = 100 + 200 + 500 = 800."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["impressions"] == pytest.approx(800.0)

    def test_totals_clicks(self, seeded_client: TestClient) -> None:
        """Total clicks = 10 + 20 + 25 = 55."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["clicks"] == pytest.approx(55.0)

    def test_totals_conversions(self, seeded_client: TestClient) -> None:
        """Total conversions = 2 + 4 + 5 = 11."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["conversions"] == pytest.approx(11.0)

    def test_totals_conversion_value(self, seeded_client: TestClient) -> None:
        """Total conv_value = 200 + 400 + 375 = 975."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["conversion_value"] == pytest.approx(975.0)

    def test_totals_ctr(self, seeded_client: TestClient) -> None:
        """CTR = 55 / 800 = 0.06875."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["ctr"] == pytest.approx(55 / 800)

    def test_totals_cpc(self, seeded_client: TestClient) -> None:
        """CPC = 225 / 55 ≈ 4.0909."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["cpc"] == pytest.approx(225 / 55, rel=1e-4)

    def test_totals_cpa(self, seeded_client: TestClient) -> None:
        """CPA = 225 / 11 ≈ 20.4545."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["cpa"] == pytest.approx(225 / 11, rel=1e-4)

    def test_totals_roas(self, seeded_client: TestClient) -> None:
        """ROAS = 975 / 225 ≈ 4.3333."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert body["totals"]["roas"] == pytest.approx(975 / 225, rel=1e-4)

    def test_by_channel_has_two_entries(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert len(body["by_channel"]) == 2

    def test_by_channel_keys(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        channel_names = {c["channel"] for c in body["by_channel"]}
        assert channel_names == {"sample", "google_ads"}

    def test_by_channel_google_ads_spend(self, seeded_client: TestClient) -> None:
        """google_ads channel has only 1 row with spend=75."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        gads = next(c for c in body["by_channel"] if c["channel"] == "google_ads")
        assert gads["spend"] == pytest.approx(75.0)

    def test_by_channel_sample_spend(self, seeded_client: TestClient) -> None:
        """sample channel: 50 + 100 = 150."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        sample = next(c for c in body["by_channel"] if c["channel"] == "sample")
        assert sample["spend"] == pytest.approx(150.0)

    def test_single_day_filter(self, seeded_client: TestClient) -> None:
        """Only 2024-03-15 rows: spend = 50 + 75 = 125."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-15"},
        )
        body = resp.json()
        assert body["totals"]["spend"] == pytest.approx(125.0)

    def test_out_of_range_returns_zeros(self, seeded_client: TestClient) -> None:
        """No data in 2025 → all totals are 0."""
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )
        body = resp.json()
        assert body["totals"]["spend"] == 0.0
        assert body["totals"]["impressions"] == 0.0
        assert body["by_channel"] == []

    def test_invalid_date_range_returns_422(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-16", "date_to": "2024-03-15"},
        )
        assert resp.status_code == 422

    def test_missing_date_from_returns_422(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_to": "2024-03-16"},
        )
        assert resp.status_code == 422

    def test_by_channel_has_derived_metrics(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        for ch in body["by_channel"]:
            for key in ("ctr", "cpc", "cpa", "roas"):
                assert key in ch, f"Missing {key} in channel {ch['channel']}"

    def test_numbers_are_json_numbers_not_strings(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        for key in ("spend", "impressions", "clicks", "conversions", "conversion_value",
                    "ctr", "cpc", "cpa", "roas"):
            assert isinstance(body["totals"][key], (int, float)), (
                f"totals.{key} should be a number, got {type(body['totals'][key])}"
            )


# ── Timeseries endpoint tests ─────────────────────────────────────────────────


class TestTimeseriesEndpoint:
    def test_returns_200_spend(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        assert resp.status_code == 200

    def test_response_structure(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        assert "metric" in body
        assert "points" in body
        assert body["metric"] == "spend"

    def test_spend_timeseries_two_points(self, seeded_client: TestClient) -> None:
        """2024-03-15 and 2024-03-16 should appear as two points."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        assert len(body["points"]) == 2

    def test_spend_day1_value(self, seeded_client: TestClient) -> None:
        """2024-03-15 total spend = 50 (sample) + 75 (google_ads) = 125."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        points_by_date = {p["date"]: p["value"] for p in body["points"]}
        assert points_by_date["2024-03-15"] == pytest.approx(125.0)

    def test_spend_day2_value(self, seeded_client: TestClient) -> None:
        """2024-03-16 total spend = 100 (sample only)."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        points_by_date = {p["date"]: p["value"] for p in body["points"]}
        assert points_by_date["2024-03-16"] == pytest.approx(100.0)

    def test_impressions_timeseries(self, seeded_client: TestClient) -> None:
        """2024-03-15 impressions = 100 + 500 = 600."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-15",
                "metric": "impressions",
            },
        )
        body = resp.json()
        assert body["points"][0]["value"] == pytest.approx(600.0)

    def test_clicks_timeseries(self, seeded_client: TestClient) -> None:
        """2024-03-15 clicks = 10 + 25 = 35."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-15",
                "metric": "clicks",
            },
        )
        body = resp.json()
        assert body["points"][0]["value"] == pytest.approx(35.0)

    def test_conversions_timeseries(self, seeded_client: TestClient) -> None:
        """2024-03-15 conversions = 2 + 5 = 7."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-15",
                "metric": "conversions",
            },
        )
        body = resp.json()
        assert body["points"][0]["value"] == pytest.approx(7.0)

    def test_conversion_value_timeseries(self, seeded_client: TestClient) -> None:
        """2024-03-15 conv_value = 200 + 375 = 575."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-15",
                "metric": "conversion_value",
            },
        )
        body = resp.json()
        assert body["points"][0]["value"] == pytest.approx(575.0)

    def test_roas_timeseries(self, seeded_client: TestClient) -> None:
        """2024-03-15 ROAS = (200+375) / (50+75) = 575/125 = 4.6."""
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-15",
                "metric": "roas",
            },
        )
        body = resp.json()
        assert body["points"][0]["value"] == pytest.approx(575 / 125, rel=1e-4)

    def test_unsupported_metric_returns_422(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "cpc",  # not a supported timeseries metric
            },
        )
        assert resp.status_code == 422

    def test_no_data_in_range_returns_empty_points(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "metric": "spend",
            },
        )
        body = resp.json()
        assert body["points"] == []

    def test_points_ordered_by_date(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        dates = [p["date"] for p in body["points"]]
        assert dates == sorted(dates)

    def test_point_value_is_number(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-15",
                "date_to": "2024-03-16",
                "metric": "spend",
            },
        )
        body = resp.json()
        for pt in body["points"]:
            assert isinstance(pt["value"], (int, float)), (
                f"point value should be a number, got {type(pt['value'])}"
            )

    def test_invalid_date_range_returns_422(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get(
            "/api/v1/dashboard/timeseries",
            params={
                "date_from": "2024-03-16",
                "date_to": "2024-03-15",
                "metric": "spend",
            },
        )
        assert resp.status_code == 422


# ── Kaynak-tipi mutabakatı: ad + analytics çift-sayım regresyon testleri ──────
#
# google_ads (ad, spend+conversions) ile ga4 (analytics, conversions, spend=0)
# aynı dönemde bulunduğunda, eski davranış ikisinin conversions/conversion_value
# toplamını "manşet" olarak gösterirdi (çift sayım). Bu testler artık GA4
# verisinin ad verisinin ÜSTÜNE eklenmediğini, kaynak-doğrusu kuralına göre
# çözüldüğünü kilitler.


@pytest.fixture()
def ga4_mixed_client(db_session: Session):
    """TestClient seeded with google_ads (ad) + ga4 (analytics) on the same day.

    google_ads: spend=1000, impressions=10000, clicks=500, conv=20, cv=4000
    ga4:        spend=0,    impressions=0,     clicks=0,   conv=15, cv=3000

    Expected (post-fix):
      ad_conversions=20, ad_conversion_value=4000
      analytics_conversions=15, analytics_conversion_value=3000
      headline conversions=15 (GA4 wins, NOT 35), conversion_value=3000
      ad_spend=total_spend=1000 (GA4 contributes 0 spend)
      blended_roas = 3000/1000 = 3.0 (NOT (4000+3000)/1000=7.0)
    """
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_gads = _make_connected_account(db_session, tenant, Platform.google_ads, "GADS-1")
    acct_ga4 = _make_connected_account(db_session, tenant, Platform.ga4, "GA4-1")

    ch_gads = _make_channel(db_session, "google_ads")
    ch_ga4 = _make_channel(db_session, "ga4")

    camp_g = _make_campaign(db_session, tenant, ch_gads, "CAMP-G", "Google Campaign")
    adset_g = _make_adset(db_session, tenant, camp_g, "ADSET-G")
    ad_g = _make_ad(db_session, tenant, adset_g, "AD-G")

    camp_a = _make_campaign(db_session, tenant, ch_ga4, "(not set)", "(not set)")
    adset_a = _make_adset(db_session, tenant, camp_a, "(not set)")
    ad_a = _make_ad(db_session, tenant, adset_a, "(not set)")

    _insert_fact(
        db_session, tenant, acct_gads, ch_gads, camp_g, adset_g, ad_g,
        date(2024, 4, 1),
        impressions=10000, clicks=500, cost_raw="1000.00",
        conversions="20", conversion_value_raw="4000.00",
    )
    _insert_fact(
        db_session, tenant, acct_ga4, ch_ga4, camp_a, adset_a, ad_a,
        date(2024, 4, 1),
        impressions=0, clicks=0, cost_raw="0",
        conversions="15", conversion_value_raw="3000.00",
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


class TestSummarySourceTypeSplit:
    _PARAMS = {"date_from": "2024-04-01", "date_to": "2024-04-01"}

    def test_ad_conversions_is_google_ads_only(self, ga4_mixed_client: TestClient) -> None:
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["ad_conversions"] == pytest.approx(20.0)
        assert body["totals"]["ad_conversion_value"] == pytest.approx(4000.0)

    def test_analytics_conversions_is_ga4_only(self, ga4_mixed_client: TestClient) -> None:
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["analytics_conversions"] == pytest.approx(15.0)
        assert body["totals"]["analytics_conversion_value"] == pytest.approx(3000.0)

    def test_headline_conversions_is_ga4_not_summed(
        self, ga4_mixed_client: TestClient
    ) -> None:
        """The historically-buggy assertion would be 35 (20+15). Post-fix it
        must be exactly the GA4 value (15) — analytics wins as source of truth."""
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["conversions"] == pytest.approx(15.0)
        assert body["totals"]["conversions"] != pytest.approx(35.0)

    def test_headline_conversion_value_is_ga4_not_summed(
        self, ga4_mixed_client: TestClient
    ) -> None:
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["conversion_value"] == pytest.approx(3000.0)
        assert body["totals"]["conversion_value"] != pytest.approx(7000.0)

    def test_blended_roas_uses_ga4_revenue_over_ad_spend_only(
        self, ga4_mixed_client: TestClient
    ) -> None:
        """Historically-buggy ROAS would be (4000+3000)/1000 = 7.0. Correct
        blended ROAS is ga4_revenue / ad_spend = 3000/1000 = 3.0."""
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["blended_roas"] == pytest.approx(3.0)
        assert body["totals"]["roas"] == pytest.approx(3.0)
        assert body["totals"]["roas"] != pytest.approx(7.0)

    def test_ad_spend_reflected_in_total_spend(self, ga4_mixed_client: TestClient) -> None:
        """GA4 contributes 0 spend, so total spend == ad spend."""
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        assert body["totals"]["spend"] == pytest.approx(1000.0)

    def test_per_channel_rows_unaffected(self, ga4_mixed_client: TestClient) -> None:
        """Per-channel breakdown was never double-counted — each channel keeps
        its own numbers regardless of the cross-channel headline fix."""
        body = ga4_mixed_client.get("/api/v1/dashboard/summary", params=self._PARAMS).json()
        by_channel = {c["channel"]: c for c in body["by_channel"]}
        assert by_channel["google_ads"]["conversions"] == pytest.approx(20.0)
        assert by_channel["ga4"]["conversions"] == pytest.approx(15.0)

    def test_ad_only_period_falls_back_to_ad_ratio_no_ga4(
        self, seeded_client: TestClient
    ) -> None:
        """Regression guard: tenants with no analytics channel connected at
        all (the seeded_client fixture — sample + google_ads, both 'ad') must
        see identical headline numbers to before this fix."""
        body = seeded_client.get(
            "/api/v1/dashboard/summary",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        ).json()
        assert body["totals"]["conversions"] == pytest.approx(11.0)
        assert body["totals"]["ad_conversions"] == pytest.approx(11.0)
        assert body["totals"]["analytics_conversions"] == pytest.approx(0.0)
        assert body["totals"]["roas"] == pytest.approx(975 / 225, rel=1e-4)
