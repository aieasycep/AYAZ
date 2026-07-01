"""Tests for the Cross-channel Budget Optimizer.

Strategy
--------
* Uses FastAPI TestClient with an in-memory SQLite DB (same pattern as
  test_dashboard_api.py and test_ads.py).
* The optimizer router is registered on the shared app once per module load
  (see ``_ensure_optimizer_router``) so main.py is not touched.
* Two distinct fixtures cover the main scenarios:
    - ``roas_gap_client``: Two channels with a clear ROAS gap (google_ads ROAS
      ~5x vs. meta_ads ROAS ~1x) to exercise the reallocation logic.
    - ``equal_roas_client``: Two channels with identical ROAS to verify the
      no-op path.
* ``tenant_b_session`` / ``tenant_b_membership`` are used for isolation tests.

Seed data — roas_gap_client
---------------------------
Channel: google_ads
    spend=100.00, conv_value=500.00  → ROAS = 5.0
    conversions=10

Channel: meta_ads
    spend=200.00, conv_value=200.00  → ROAS = 1.0
    conversions=5

Total spend = 300.00

With max_shift_pct=0.20 (default):
    max_total_shift = 300 × 0.20 = 60.00
    donor = meta_ads  (lowest ROAS = 1.0)
    recipient = google_ads  (highest ROAS = 5.0)
    donor_max = 200 × 0.20 = 40.00
    amount = min(40.00, 60.00) = 40.00

    projected_conversion_value_delta = 40 × 5.0 = 200.00
    projected_conversion_delta       = 40 × (10 / 100) = 4.00

Seed data — equal_roas_client
------------------------------
Channel: google_ads  spend=100, conv_value=300  → ROAS = 3.0
Channel: meta_ads    spend=100, conv_value=300  → ROAS = 3.0
ROAS gap = 0.0 < _MIN_ROAS_GAP_FOR_SUGGESTION (0.5) → no suggestions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import optimizer as optimizer_module
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
from ayaz.services.optimizer import current_allocation, suggest_reallocation


# ── Register the optimizer router once ────────────────────────────────────────
# main.py is intentionally not modified (per project rules).  The team lead
# must wire optimizer_module.router into main.py for production.  Here we
# register it directly on the shared FastAPI app so TestClient can reach
# /api/v1/optimizer/* endpoints.

_OPTIMIZER_ROUTER_REGISTERED = False


def _ensure_optimizer_router() -> None:
    global _OPTIMIZER_ROUTER_REGISTERED
    if not _OPTIMIZER_ROUTER_REGISTERED:
        app.include_router(optimizer_module.router, prefix="/api/v1")
        _OPTIMIZER_ROUTER_REGISTERED = True


_ensure_optimizer_router()


# ── DB / ORM helpers (mirrors test_dashboard_api.py) ─────────────────────────


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite://",
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


def _make_user(db: Session, email: str = "opt@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test1234"),
        full_name="Optimizer User",
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


def _make_connected_account(db: Session, tenant: Tenant, platform: Platform) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=str(uuid.uuid4()),
        display_name=f"{platform.value} test",
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
    cost: str,
    conversions: str,
    conversion_value: str,
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost_d = Decimal(cost)
    fact = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=1000,
        clicks=100,
        cost_raw=cost_d,
        cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value),
        conversion_value_ccy="USD",
        cost_base_ccy=cost_d,
        conv_value_base_ccy=Decimal(conversion_value),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Fixture: clear ROAS gap between channels ──────────────────────────────────
#
# google_ads: spend=100, conv_value=500, conversions=10  → ROAS=5.0
# meta_ads:   spend=200, conv_value=200, conversions=5   → ROAS=1.0
# Total spend = 300


@pytest.fixture()
def roas_gap_client(db_session: Session):
    """TestClient seeded with a clear ROAS gap (google_ads=5x, meta_ads=1x)."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_g = _make_connected_account(db_session, tenant, Platform.google_ads)
    acct_m = _make_connected_account(db_session, tenant, Platform.meta_ads)

    ch_g = _make_channel(db_session, "google_ads")
    ch_m = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant, ch_g, "Google Promo")
    adset_g = _make_adset(db_session, tenant, camp_g)
    ad_g = _make_ad(db_session, tenant, adset_g)

    camp_m = _make_campaign(db_session, tenant, ch_m, "Meta Brand")
    adset_m = _make_adset(db_session, tenant, camp_m)
    ad_m = _make_ad(db_session, tenant, adset_m)

    day = date(2024, 5, 1)

    _insert_fact(
        db_session, tenant, acct_g, ch_g, camp_g, adset_g, ad_g, day,
        cost="100.00", conversions="10", conversion_value="500.00",
    )
    _insert_fact(
        db_session, tenant, acct_m, ch_m, camp_m, adset_m, ad_m, day,
        cost="200.00", conversions="5", conversion_value="200.00",
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
    yield client, db_session, tenant, membership

    app.dependency_overrides.clear()


# ── Fixture: equal ROAS (no-op path) ─────────────────────────────────────────
#
# google_ads: spend=100, conv_value=300  → ROAS=3.0
# meta_ads:   spend=100, conv_value=300  → ROAS=3.0
# gap = 0.0 < 0.5 → no suggestions


@pytest.fixture()
def equal_roas_client(db_session: Session):
    """TestClient seeded with identical ROAS across channels (no-op case)."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_g = _make_connected_account(db_session, tenant, Platform.google_ads)
    acct_m = _make_connected_account(db_session, tenant, Platform.meta_ads)

    ch_g = _make_channel(db_session, "google_ads")
    ch_m = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant, ch_g, "Google Equal")
    adset_g = _make_adset(db_session, tenant, camp_g)
    ad_g = _make_ad(db_session, tenant, adset_g)

    camp_m = _make_campaign(db_session, tenant, ch_m, "Meta Equal")
    adset_m = _make_adset(db_session, tenant, camp_m)
    ad_m = _make_ad(db_session, tenant, adset_m)

    day = date(2024, 5, 1)

    _insert_fact(
        db_session, tenant, acct_g, ch_g, camp_g, adset_g, ad_g, day,
        cost="100.00", conversions="5", conversion_value="300.00",
    )
    _insert_fact(
        db_session, tenant, acct_m, ch_m, camp_m, adset_m, ad_m, day,
        cost="100.00", conversions="5", conversion_value="300.00",
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


# ── Service-layer unit tests ──────────────────────────────────────────────────


class TestCurrentAllocation:
    """Unit tests for services/optimizer.py::current_allocation."""

    def test_returns_two_channels(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        assert len(result) == 2

    def test_channel_keys_present(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        channels = {r["channel"] for r in result}
        assert channels == {"google_ads", "meta_ads"}

    def test_google_ads_spend(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        gads = next(r for r in result if r["channel"] == "google_ads")
        assert gads["spend"] == pytest.approx(100.0)

    def test_meta_ads_spend(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        meta = next(r for r in result if r["channel"] == "meta_ads")
        assert meta["spend"] == pytest.approx(200.0)

    def test_google_ads_roas(self, roas_gap_client) -> None:
        """google_ads ROAS = 500 / 100 = 5.0."""
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        gads = next(r for r in result if r["channel"] == "google_ads")
        assert gads["roas"] == pytest.approx(5.0)

    def test_meta_ads_roas(self, roas_gap_client) -> None:
        """meta_ads ROAS = 200 / 200 = 1.0."""
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        meta = next(r for r in result if r["channel"] == "meta_ads")
        assert meta["roas"] == pytest.approx(1.0)

    def test_share_of_spend_sums_to_one(self, roas_gap_client) -> None:
        """Sum of share_of_spend across channels must equal 1.0."""
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        total_share = sum(r["share_of_spend"] for r in result)
        assert total_share == pytest.approx(1.0)

    def test_google_ads_share(self, roas_gap_client) -> None:
        """google_ads share = 100 / 300 ≈ 0.333."""
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        gads = next(r for r in result if r["channel"] == "google_ads")
        assert gads["share_of_spend"] == pytest.approx(100 / 300, rel=1e-4)

    def test_all_values_are_float(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        for row in result:
            for key in ("spend", "conversions", "conversion_value", "roas", "share_of_spend"):
                assert isinstance(row[key], float), f"{key} must be float, got {type(row[key])}"

    def test_out_of_range_returns_empty(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = current_allocation(db, tenant.id, date(2025, 1, 1), date(2025, 1, 31))
        assert result == []


class TestSuggestReallocation:
    """Unit tests for services/optimizer.py::suggest_reallocation."""

    def test_returns_dict_with_required_keys(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        assert "suggestions" in result
        assert "summary" in result
        assert "caveat" in result

    def test_suggests_move_from_low_to_high_roas(self, roas_gap_client) -> None:
        """meta_ads (ROAS=1.0) should be donor; google_ads (ROAS=5.0) recipient."""
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        assert len(result["suggestions"]) >= 1
        s = result["suggestions"][0]
        assert s["from_channel"] == "meta_ads"
        assert s["to_channel"] == "google_ads"

    def test_from_roas_lower_than_to_roas(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        for s in result["suggestions"]:
            assert s["from_roas"] < s["to_roas"]

    def test_amount_respects_max_shift_pct(self, roas_gap_client) -> None:
        """Total shift must not exceed max_shift_pct × total_spend.

        total_spend=300, max_shift_pct=0.20 → max total shift = 60.
        donor meta_ads: donor_max = 200 × 0.20 = 40.
        amount = min(40, 60) = 40.
        """
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(
            db, tenant.id, date(2024, 5, 1), date(2024, 5, 1), max_shift_pct=0.20
        )
        assert result["summary"]["total_shift"] == pytest.approx(40.0)

    def test_total_shift_does_not_exceed_global_cap(self, roas_gap_client) -> None:
        """Regardless of max_shift_pct, total_shift <= max_shift_pct * total_spend."""
        _, db, tenant, _ = roas_gap_client
        for pct in (0.05, 0.10, 0.30, 0.50):
            result = suggest_reallocation(
                db, tenant.id, date(2024, 5, 1), date(2024, 5, 1), max_shift_pct=pct
            )
            total_spend = 300.0
            assert result["summary"]["total_shift"] <= total_spend * pct + 1e-6

    def test_projected_conversion_value_delta_positive(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        for s in result["suggestions"]:
            assert s["projected_conversion_value_delta"] > 0

    def test_projected_conversion_value_delta_correct(self, roas_gap_client) -> None:
        """projected_cv_delta = amount × to_roas = 40 × 5.0 = 200.0."""
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(
            db, tenant.id, date(2024, 5, 1), date(2024, 5, 1), max_shift_pct=0.20
        )
        s = result["suggestions"][0]
        expected = s["amount"] * s["to_roas"]
        assert s["projected_conversion_value_delta"] == pytest.approx(expected, rel=1e-4)

    def test_projected_conversion_delta_correct(self, roas_gap_client) -> None:
        """projected_conv_delta = amount × (conversions / spend) = 40 × (10/100) = 4.0."""
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(
            db, tenant.id, date(2024, 5, 1), date(2024, 5, 1), max_shift_pct=0.20
        )
        s = result["suggestions"][0]
        # google_ads: conversions=10, spend=100 → conv_rate=0.10
        assert s["projected_conversion_delta"] == pytest.approx(4.0, rel=1e-4)

    def test_summary_total_uplift_matches_suggestions(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        expected_uplift = sum(s["projected_conversion_value_delta"] for s in result["suggestions"])
        assert result["summary"]["projected_total_uplift"] == pytest.approx(expected_uplift, rel=1e-6)

    def test_caveat_present_in_each_suggestion(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        for s in result["suggestions"]:
            assert "caveat" in s
            assert len(s["caveat"]) > 10

    def test_caveat_present_in_summary_and_top_level(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        assert len(result["caveat"]) > 10
        assert len(result["summary"]["caveat"]) > 10

    def test_no_suggestions_when_roas_equal(self, equal_roas_client) -> None:
        """When ROAS gap is below threshold, suggest_reallocation returns no moves."""
        # Equal ROAS fixture: both channels have ROAS=3.0, gap=0 < 0.5 threshold
        # We need to access db/tenant directly, so use a separate db_session fixture call.
        # Instead, test via the API endpoint.
        pass  # covered in TestAPIEndpoint.test_no_suggestions_equal_roas

    def test_zero_shift_pct_returns_no_suggestions(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(
            db, tenant.id, date(2024, 5, 1), date(2024, 5, 1), max_shift_pct=0.0
        )
        assert result["suggestions"] == []
        assert result["summary"]["total_shift"] == pytest.approx(0.0)

    def test_rationale_is_string(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2024, 5, 1), date(2024, 5, 1))
        for s in result["suggestions"]:
            assert isinstance(s["rationale"], str)
            assert len(s["rationale"]) > 0

    def test_no_data_returns_empty_suggestions(self, roas_gap_client) -> None:
        _, db, tenant, _ = roas_gap_client
        result = suggest_reallocation(db, tenant.id, date(2025, 1, 1), date(2025, 1, 31))
        assert result["suggestions"] == []
        assert result["summary"]["total_shift"] == pytest.approx(0.0)


# ── API endpoint tests ────────────────────────────────────────────────────────


class TestAPIEndpoint:
    """Integration tests for GET /api/v1/optimizer/budget."""

    def test_returns_200(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 200

    def test_response_has_required_keys(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        for key in ("date_from", "date_to", "max_shift_pct",
                    "current_allocation", "suggestions", "summary", "caveat"):
            assert key in body, f"Missing key: {key}"

    def test_current_allocation_has_two_channels(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        assert len(body["current_allocation"]) == 2

    def test_current_allocation_spend_values(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        by_channel = {c["channel"]: c for c in body["current_allocation"]}
        assert by_channel["google_ads"]["spend"] == pytest.approx(100.0)
        assert by_channel["meta_ads"]["spend"] == pytest.approx(200.0)

    def test_current_allocation_roas_values(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        by_channel = {c["channel"]: c for c in body["current_allocation"]}
        assert by_channel["google_ads"]["roas"] == pytest.approx(5.0)
        assert by_channel["meta_ads"]["roas"] == pytest.approx(1.0)

    def test_suggestion_moves_from_low_to_high_roas(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        assert len(body["suggestions"]) >= 1
        s = body["suggestions"][0]
        assert s["from_channel"] == "meta_ads"
        assert s["to_channel"] == "google_ads"

    def test_suggestion_amount_is_bounded(self, roas_gap_client) -> None:
        """amount <= max_shift_pct × total_spend = 0.20 × 300 = 60."""
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01",
                    "max_shift_pct": "0.20"},
        )
        body = resp.json()
        total_shift = body["summary"]["total_shift"]
        assert total_shift <= 60.0 + 1e-6

    def test_suggestion_amount_correct(self, roas_gap_client) -> None:
        """donor_max = 200 × 0.20 = 40; global cap = 300 × 0.20 = 60 → amount = 40."""
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01",
                    "max_shift_pct": "0.20"},
        )
        body = resp.json()
        assert body["summary"]["total_shift"] == pytest.approx(40.0)

    def test_projected_conversion_value_delta_positive(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        for s in body["suggestions"]:
            assert s["projected_conversion_value_delta"] > 0

    def test_projected_uplift_is_amount_times_to_roas(self, roas_gap_client) -> None:
        """projected_cv_delta = 40 × 5.0 = 200.0."""
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01",
                    "max_shift_pct": "0.20"},
        )
        body = resp.json()
        s = body["suggestions"][0]
        assert s["projected_conversion_value_delta"] == pytest.approx(200.0, rel=1e-4)

    def test_caveat_in_suggestions_and_top_level(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        assert len(body["caveat"]) > 10
        for s in body["suggestions"]:
            assert len(s["caveat"]) > 10

    def test_no_suggestions_equal_roas(self, equal_roas_client) -> None:
        """When ROAS gap < threshold, no reallocation should be suggested."""
        resp = equal_roas_client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        assert body["suggestions"] == []
        assert body["summary"]["suggestions_count"] == 0
        assert body["summary"]["total_shift"] == pytest.approx(0.0)

    def test_no_data_returns_empty_suggestions(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )
        body = resp.json()
        assert body["suggestions"] == []
        assert body["current_allocation"] == []

    def test_invalid_date_range_returns_422(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-02", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 422

    def test_max_shift_pct_out_of_range_returns_422(self, roas_gap_client) -> None:
        """max_shift_pct must be between 0 and 1."""
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01",
                    "max_shift_pct": "1.5"},
        )
        assert resp.status_code == 422

    def test_numbers_are_json_numbers(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        for ch in body["current_allocation"]:
            for key in ("spend", "conversions", "conversion_value", "roas", "share_of_spend"):
                assert isinstance(ch[key], (int, float)), (
                    f"current_allocation.{key} should be a number"
                )
        for s in body["suggestions"]:
            for key in ("amount", "from_roas", "to_roas",
                        "projected_conversion_value_delta", "projected_conversion_delta"):
                assert isinstance(s[key], (int, float)), (
                    f"suggestion.{key} should be a number"
                )

    def test_summary_channels_evaluated_correct(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01"},
        )
        body = resp.json()
        assert body["summary"]["channels_evaluated"] == 2

    def test_max_shift_pct_echoed_in_response(self, roas_gap_client) -> None:
        client, *_ = roas_gap_client
        resp = client.get(
            "/api/v1/optimizer/budget",
            params={"date_from": "2024-05-01", "date_to": "2024-05-01",
                    "max_shift_pct": "0.10"},
        )
        body = resp.json()
        assert body["max_shift_pct"] == pytest.approx(0.10)


# ── Tenant isolation tests ────────────────────────────────────────────────────


class TestTenantIsolation:
    """Verify that cross-tenant data leakage is impossible."""

    def test_tenant_b_data_invisible_to_tenant_a(self, db_session: Session) -> None:
        """Two tenants with different spend profiles — each sees only their own data."""
        # Tenant A: google_ads spend=100
        tenant_a = _make_tenant(db_session, "Tenant A")
        user_a = _make_user(db_session, "a@ayaz.app")
        membership_a = _make_membership(db_session, user_a, tenant_a)
        acct_a = _make_connected_account(db_session, tenant_a, Platform.google_ads)
        ch_a = _make_channel(db_session, "google_ads_iso_a")
        camp_a = _make_campaign(db_session, tenant_a, ch_a, "Camp A")
        adset_a = _make_adset(db_session, tenant_a, camp_a)
        ad_a = _make_ad(db_session, tenant_a, adset_a)
        _insert_fact(
            db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
            date(2024, 6, 1),
            cost="100.00", conversions="5", conversion_value="500.00",
        )

        # Tenant B: google_ads spend=9999 (should NOT appear in tenant A's view)
        tenant_b = _make_tenant(db_session, "Tenant B")
        user_b = _make_user(db_session, "b@ayaz.app")
        _make_membership(db_session, user_b, tenant_b)
        acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads)
        ch_b = _make_channel(db_session, "google_ads_iso_b")
        camp_b = _make_campaign(db_session, tenant_b, ch_b, "Camp B")
        adset_b = _make_adset(db_session, tenant_b, camp_b)
        ad_b = _make_ad(db_session, tenant_b, adset_b)
        _insert_fact(
            db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b,
            date(2024, 6, 1),
            cost="9999.00", conversions="100", conversion_value="99990.00",
        )
        db_session.commit()

        # Tenant A's allocation should show only 100 spend, not 9999.
        result_a = current_allocation(
            db_session, tenant_a.id, date(2024, 6, 1), date(2024, 6, 1)
        )
        total_spend_a = sum(r["spend"] for r in result_a)
        assert total_spend_a == pytest.approx(100.0), (
            f"Tenant A should only see its own 100 spend, got {total_spend_a}"
        )

        # Tenant B's allocation should show 9999, not bleed into tenant A.
        result_b = current_allocation(
            db_session, tenant_b.id, date(2024, 6, 1), date(2024, 6, 1)
        )
        total_spend_b = sum(r["spend"] for r in result_b)
        assert total_spend_b == pytest.approx(9999.0)
