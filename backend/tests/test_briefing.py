"""Tests for the Proactive AI Daily Briefing feature.

Strategy
--------
* SQLite in-memory DB via StaticPool — matches the rest of the test suite.
* All service functions are tested directly (no live network).
* The Claude path is exercised via a mock http_client that returns a canned
  response; no real Anthropic API calls are made.
* API endpoints use FastAPI TestClient with dependency overrides.

Coverage
--------
1.  generate_briefing: performance deltas computed correctly.
2.  generate_briefing: body sections populated (top_insights, top_recommendation
    plumbing, goals_status present, performance_delta shape).
3.  generate_briefing: headline is grounded (contains a real number or keyword).
4.  Idempotency: calling generate_briefing twice for same date updates, not duplicates.
5.  Tenant isolation: tenant A's briefing not visible to tenant B.
6.  API GET /briefings — list, newest first.
7.  API GET /briefings/latest — returns most recent; 404 when none.
8.  API POST /briefings/generate — creates and returns a briefing.
9.  Claude path: mock http_client headline replaces template output.
10. Template headline: ROAS drop triggers "dustu" phrase.
11. Template headline: spend spike triggers "artti" phrase.
12. deliver_briefing: runs without error (notifier stubs only log).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.database import get_db
from ayaz.api.deps import get_current_membership
from ayaz.api.v1.briefing import router as briefing_router

# Build a minimal test app — does not touch main.py
_test_app = FastAPI()
_test_app.include_router(briefing_router, prefix="/api/v1")

from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
from ayaz.models.briefing import Briefing
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
from ayaz.services.briefing import (
    _build_deterministic_headline,
    deliver_briefing,
    generate_briefing,
)

_SQLITE_URL = "sqlite://"


# ── DB + fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session — creates all tables, drops on teardown."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Force all model modules to be imported so Base.metadata is complete
    import ayaz.models  # noqa: F401

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


def _make_channel(db: Session, key: str = "google_ads") -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel,
                   name: str = "Camp Alpha") -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant.id,
        channel_id=channel.id, external_id="CAMP-1", name=name,
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
    spend: str = "100",
    conversions: str = "10",
    conversion_value: str = "500",
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
        impressions=10000,
        clicks=500,
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


def _seed_two_days(
    db: Session,
    tenant: Tenant,
    as_of_date: date,
    *,
    yesterday_spend: str = "200",
    yesterday_conversions: str = "20",
    yesterday_value: str = "1000",
    prior_spend: str = "100",
    prior_conversions: str = "10",
    prior_value: str = "500",
):
    """Seed fact rows for yesterday and prior_day relative to as_of_date."""
    acct = _make_connected_account(db, tenant)
    channel = _make_channel(db)
    campaign = _make_campaign(db, tenant, channel)
    adset = _make_adset(db, tenant, campaign)
    ad = _make_ad(db, tenant, adset)

    yesterday = as_of_date - __import__("datetime").timedelta(days=1)
    prior_day = as_of_date - __import__("datetime").timedelta(days=2)

    _insert_fact(db, tenant, acct, channel, campaign, adset, ad, yesterday,
                 spend=yesterday_spend, conversions=yesterday_conversions,
                 conversion_value=yesterday_value)
    _insert_fact(db, tenant, acct, channel, campaign, adset, ad, prior_day,
                 spend=prior_spend, conversions=prior_conversions,
                 conversion_value=prior_value)
    db.flush()


# ── Service tests ─────────────────────────────────────────────────────────────


class TestGenerateBriefing:
    """Unit-level tests for generate_briefing service function."""

    def test_body_shape_has_required_sections(self, db_session: Session):
        """Body JSON must contain the four required top-level keys."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)
        db_session.commit()

        body = briefing.body
        assert "performance_delta" in body
        assert "top_insights" in body
        assert "top_recommendation" in body
        assert "goals_status" in body

    def test_performance_delta_computed(self, db_session: Session):
        """Delta metrics should reflect the seeded spend/ROAS difference."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        # yesterday: spend=200, conv_value=800 → ROAS=4.0
        # prior_day: spend=100, conv_value=800 → ROAS=8.0 (ROAS halved)
        _seed_two_days(
            db_session, tenant, as_of,
            yesterday_spend="200", yesterday_value="800",
            prior_spend="100", prior_value="800",
        )
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)

        delta = briefing.body["performance_delta"]
        assert delta["yesterday"]["spend"] == pytest.approx(200.0)
        assert delta["prior_day"]["spend"] == pytest.approx(100.0)
        # Spend doubled → delta should be +1.0 (100%)
        assert delta["delta"]["spend_pct"] == pytest.approx(1.0, abs=0.01)
        # ROAS dropped: prior=8.0, yesterday=4.0 → delta = -0.5
        assert delta["delta"]["roas_pct"] == pytest.approx(-0.5, abs=0.01)

    def test_headline_non_empty_and_grounded(self, db_session: Session):
        """Headline must be a non-empty string containing a real number or keyword."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of,
                       yesterday_spend="150", yesterday_value="300",
                       prior_spend="100", prior_value="500")
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)
        headline = briefing.headline

        assert isinstance(headline, str)
        assert len(headline) > 5
        # Headline should contain at least one digit (grounded in numbers)
        assert any(ch.isdigit() for ch in headline), (
            f"Headline not grounded in numbers: {headline!r}"
        )

    def test_idempotency_same_date_updates_not_duplicates(self, db_session: Session):
        """Calling generate_briefing twice for the same date must update, not insert."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        b1 = generate_briefing(db_session, tenant.id, as_of)
        db_session.commit()

        b2 = generate_briefing(db_session, tenant.id, as_of)
        db_session.commit()

        from sqlalchemy import select, func

        count = db_session.scalar(
            select(func.count()).where(
                Briefing.tenant_id == tenant.id,
                Briefing.briefing_date == as_of.isoformat(),
            )
        )
        assert count == 1, "Expected exactly one briefing row (upsert, not insert)"
        assert b1.id == b2.id, "Idempotent call should return the same row"

    def test_tenant_isolation(self, db_session: Session):
        """Tenant A's briefing must not appear in Tenant B's queries."""
        tenant_a = _make_tenant(db_session, name="Tenant A")
        tenant_b = _make_tenant(db_session, name="Tenant B")
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant_a, as_of)
        db_session.commit()

        generate_briefing(db_session, tenant_a.id, as_of)
        db_session.commit()

        from sqlalchemy import select

        b_rows = db_session.scalars(
            select(Briefing).where(Briefing.tenant_id == tenant_b.id)
        ).all()
        assert b_rows == [], "Tenant B should have no briefings"

    def test_top_insights_list_present(self, db_session: Session):
        """top_insights must be a list (may be empty when no insights exist)."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)
        assert isinstance(briefing.body["top_insights"], list)

    def test_goals_status_list_present(self, db_session: Session):
        """goals_status must be a list (may be empty when no goals exist)."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)
        assert isinstance(briefing.body["goals_status"], list)

    def test_no_data_still_returns_briefing(self, db_session: Session):
        """generate_briefing must not raise even when there is no fact data."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        db_session.commit()

        briefing = generate_briefing(db_session, tenant.id, as_of)
        db_session.commit()

        assert briefing is not None
        assert briefing.briefing_date == as_of.isoformat()

    def test_claude_path_headline_used(self, db_session: Session):
        """When a mock http_client is provided, its response replaces the template."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        claude_headline = "Claude urettigi Turkce baslik: ROAS %15 artti, harika!"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"text": claude_headline}]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        # Temporarily set anthropic_api_key so ClaudeBriefingNarrator is used
        import ayaz.config as _cfg
        original_key = _cfg.settings.anthropic_api_key
        _cfg.settings.anthropic_api_key = "sk-test-key-for-briefing"
        try:
            briefing = generate_briefing(
                db_session, tenant.id, as_of, http_client=mock_client
            )
        finally:
            _cfg.settings.anthropic_api_key = original_key

        assert briefing.headline == claude_headline
        mock_client.post.assert_called_once()

    def test_claude_path_falls_back_on_error(self, db_session: Session):
        """When Claude raises, template fallback must still produce a headline."""
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        _seed_two_days(db_session, tenant, as_of)
        db_session.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        import ayaz.config as _cfg
        original_key = _cfg.settings.anthropic_api_key
        _cfg.settings.anthropic_api_key = "sk-test-key-for-briefing"
        try:
            briefing = generate_briefing(
                db_session, tenant.id, as_of, http_client=mock_client
            )
        finally:
            _cfg.settings.anthropic_api_key = original_key

        # Should still have a non-empty headline from template fallback
        assert isinstance(briefing.headline, str)
        assert len(briefing.headline) > 5


# ── Deterministic headline unit tests ─────────────────────────────────────────


class TestDeterministicHeadline:
    """Test _build_deterministic_headline directly — pure function, no DB."""

    def _perf(self, yest_roas=5.0, prior_roas=5.0, yest_spend=100.0, prior_spend=100.0):
        roas_pct = (yest_roas - prior_roas) / prior_roas if prior_roas else 0.0
        spend_pct = (yest_spend - prior_spend) / prior_spend if prior_spend else 0.0
        return {
            "yesterday": {"spend": yest_spend, "conversions": 10.0, "roas": yest_roas},
            "prior_day": {"spend": prior_spend, "conversions": 10.0, "roas": prior_roas},
            "delta": {"spend_pct": spend_pct, "conversions_pct": 0.0, "roas_pct": roas_pct},
        }

    def test_roas_drop_headline_contains_dustu(self):
        perf = self._perf(yest_roas=3.0, prior_roas=5.0)  # -40% drop
        headline = _build_deterministic_headline(perf, [], None, [])
        assert "dustu" in headline.lower()

    def test_spend_spike_headline_contains_artti(self):
        perf = self._perf(yest_spend=150.0, prior_spend=100.0)  # +50% rise
        headline = _build_deterministic_headline(perf, [], None, [])
        assert "artti" in headline.lower()

    def test_critical_insight_title_used(self):
        perf = self._perf()  # no significant delta
        insights = [
            {"severity": "critical", "title": "Kritik: kampanya durdu", "score": 90}
        ]
        headline = _build_deterministic_headline(perf, insights, None, [])
        assert "Kritik" in headline

    def test_off_track_goal_mentioned(self):
        perf = self._perf()
        goals = [{"name": "Mart ROAS Hedefi", "status": "off_track",
                  "pct_to_target": 0.5, "metric": "roas"}]
        headline = _build_deterministic_headline(perf, [], None, goals)
        assert "Mart ROAS Hedefi" in headline or "hedefe" in headline.lower()

    def test_fallback_positive_contains_digit(self):
        perf = self._perf(yest_roas=5.0, prior_roas=5.0)  # flat, no signal
        headline = _build_deterministic_headline(perf, [], None, [])
        assert any(ch.isdigit() for ch in headline)


# ── deliver_briefing tests ────────────────────────────────────────────────────


class TestDeliverBriefing:
    """Verify deliver_briefing runs without raising (stubs only log)."""

    def test_deliver_does_not_raise(self, db_session: Session):
        tenant = _make_tenant(db_session)
        as_of = date(2026, 6, 26)
        db_session.commit()

        briefing = Briefing(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            briefing_date=as_of.isoformat(),
            headline="Dun ROAS %10 dustu. Butceyi gozden gecirin.",
            body={
                "performance_delta": {},
                "top_insights": [],
                "top_recommendation": None,
                "goals_status": [],
            },
        )
        db_session.add(briefing)
        db_session.flush()

        # Must not raise
        deliver_briefing(db_session, briefing)


# ── API tests ─────────────────────────────────────────────────────────────────


def _make_api_client(db_session: Session) -> tuple[TestClient, Tenant, Membership]:
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
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
    return TestClient(_test_app), tenant, membership


class TestBriefingAPI:
    """Integration tests for the briefing API endpoints."""

    def teardown_method(self):
        _test_app.dependency_overrides.clear()

    def test_list_briefings_empty(self, db_session: Session):
        client, tenant, _ = _make_api_client(db_session)
        resp = client.get("/api/v1/briefings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_briefings_returns_newest_first(self, db_session: Session):
        client, tenant, _ = _make_api_client(db_session)

        # Insert two briefings manually
        for d_str in ["2026-06-24", "2026-06-25"]:
            b = Briefing(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                briefing_date=d_str,
                headline=f"Brifing {d_str}",
                body={},
            )
            db_session.add(b)
        db_session.commit()

        resp = client.get("/api/v1/briefings")
        assert resp.status_code == 200
        dates = [r["briefing_date"] for r in resp.json()]
        assert dates == ["2026-06-25", "2026-06-24"], "Should be newest first"

    def test_get_latest_404_when_none(self, db_session: Session):
        client, _, _ = _make_api_client(db_session)
        resp = client.get("/api/v1/briefings/latest")
        assert resp.status_code == 404

    def test_get_latest_returns_most_recent(self, db_session: Session):
        client, tenant, _ = _make_api_client(db_session)

        for d_str in ["2026-06-23", "2026-06-25", "2026-06-24"]:
            b = Briefing(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                briefing_date=d_str,
                headline=f"Brifing {d_str}",
                body={},
            )
            db_session.add(b)
        db_session.commit()

        resp = client.get("/api/v1/briefings/latest")
        assert resp.status_code == 200
        assert resp.json()["briefing_date"] == "2026-06-25"

    def test_generate_creates_briefing(self, db_session: Session):
        client, tenant, _ = _make_api_client(db_session)

        resp = client.post("/api/v1/briefings/generate")
        assert resp.status_code == 200
        data = resp.json()
        assert "briefing_date" in data
        assert "headline" in data
        assert "body" in data
        assert "performance_delta" in data["body"]

    def test_generate_is_idempotent(self, db_session: Session):
        client, tenant, _ = _make_api_client(db_session)

        r1 = client.post("/api/v1/briefings/generate")
        r2 = client.post("/api/v1/briefings/generate")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

    def test_tenant_isolation_in_api(self, db_session: Session):
        """Briefings from tenant A must not leak to tenant B's list endpoint."""
        # Create tenant A briefing
        tenant_a = _make_tenant(db_session, name="Tenant A")
        b_a = Briefing(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            briefing_date="2026-06-25",
            headline="A brifing",
            body={},
        )
        db_session.add(b_a)
        db_session.commit()

        # Now query as tenant B
        client, tenant_b, _ = _make_api_client(db_session)
        resp = client.get("/api/v1/briefings")
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert str(b_a.id) not in ids

    def test_response_schema_fields(self, db_session: Session):
        """API response must include all documented fields."""
        client, tenant, _ = _make_api_client(db_session)
        resp = client.post("/api/v1/briefings/generate")
        data = resp.json()

        required_fields = {"id", "tenant_id", "briefing_date", "headline",
                           "body", "created_at", "updated_at"}
        assert required_fields.issubset(data.keys())

    def test_body_sections_in_api_response(self, db_session: Session):
        """All four body sections must be present in the API response."""
        client, tenant, _ = _make_api_client(db_session)
        resp = client.post("/api/v1/briefings/generate")
        body = resp.json()["body"]
        for key in ("performance_delta", "top_insights", "top_recommendation",
                    "goals_status"):
            assert key in body, f"Missing body section: {key}"
