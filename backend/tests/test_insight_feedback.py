"""Tests for the closed feedback loop on Insight recommendations (Dalga 46).

Covers:
- POST /api/v1/insights/{id}/apply  — mark applied, unmark (unapply)
- POST /api/v1/insights/{id}/react  — up / down / null reactions
- GET  /api/v1/insights              — list filters: applied=true/false, reaction=up/down
- Auth required (401) when no membership dep override
- Tenant isolation (404 when insight belongs to another tenant)
- Invalid reaction value (422)

Uses the same in-memory SQLite + TestClient fixture pattern as test_insights.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1.insights import router as insights_router
from ayaz.models.base import Base
from ayaz.models.insights import Insight
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import hash_password

# Minimal test app — same pattern as test_insights.py
_test_app = FastAPI()
_test_app.include_router(insights_router, prefix="/api/v1")

# Import all model modules so Base.metadata is populated
import ayaz.models.oltp       # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds      # noqa: F401
import ayaz.models.insights   # noqa: F401

_SQLITE_URL = "sqlite://"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite DB, yielded as a Session, dropped after the test."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_tenant(db: Session, name: str = "Feedback Test Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name=name,
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"feedback-{uuid.uuid4()}@ayaz.app",
        hashed_password=hash_password("pass1234"),
        full_name="Feedback User",
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


def _make_insight(
    db: Session,
    tenant: Tenant,
    *,
    category: str = "roas_drop",
    severity: str = "warning",
    title: str = "Test insight",
    body: str = "Test body",
    metric: str = "roas",
    status: str = "new",
    score: float = 75.0,
    applied_at: datetime | None = None,
    reaction: str | None = None,
) -> Insight:
    insight = Insight(
        tenant_id=tenant.id,
        category=category,
        severity=severity,
        title=title,
        body=body,
        metric=metric,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 7),
        status=status,
        score=score,
        data={"pct_drop": 0.25},
        applied_at=applied_at,
        reaction=reaction,
    )
    db.add(insight)
    db.flush()
    return insight


@pytest.fixture()
def feedback_client(db_session: Session):
    """TestClient with DB + membership overrides; pre-seeds one tenant/user/membership."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_get_db
    _test_app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(_test_app)
    yield client, tenant, membership, db_session

    _test_app.dependency_overrides.clear()


# ── Apply endpoint tests ──────────────────────────────────────────────────────


class TestApplyEndpoint:
    """POST /api/v1/insights/{id}/apply"""

    def test_apply_sets_applied_at(self, feedback_client) -> None:
        """Sending applied=true should populate applied_at with a UTC datetime."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/apply",
            json={"applied": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied_at"] is not None, "applied_at must be set after marking applied"
        # applied_at should be a parseable ISO timestamp
        parsed = datetime.fromisoformat(body["applied_at"].replace("Z", "+00:00"))
        assert parsed is not None

    def test_apply_returns_full_insight(self, feedback_client) -> None:
        """The apply response must include all standard insight fields."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/apply",
            json={"applied": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(insight.id)
        assert body["category"] == "roas_drop"
        assert body["severity"] == "warning"

    def test_unapply_clears_applied_at(self, feedback_client) -> None:
        """Sending applied=false should clear applied_at back to null."""
        client, tenant, _, db = feedback_client
        now = datetime.now(timezone.utc)
        insight = _make_insight(db, tenant, applied_at=now)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/apply",
            json={"applied": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied_at"] is None, "applied_at must be null after unapplying"

    def test_apply_then_unapply_idempotent(self, feedback_client) -> None:
        """Apply followed by unapply leaves applied_at as null."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        client.post(f"/api/v1/insights/{insight.id}/apply", json={"applied": True})
        resp = client.post(
            f"/api/v1/insights/{insight.id}/apply", json={"applied": False}
        )
        assert resp.status_code == 200
        assert resp.json()["applied_at"] is None

    def test_apply_404_for_wrong_tenant(self, feedback_client, db_session: Session) -> None:
        """An insight belonging to another tenant must return 404 (tenant isolation)."""
        client, _, _, db = feedback_client
        other_tenant = _make_tenant(db, name="Other Tenant")
        other_insight = _make_insight(db, other_tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{other_insight.id}/apply",
            json={"applied": True},
        )
        assert resp.status_code == 404

    def test_apply_404_for_nonexistent_insight(self, feedback_client) -> None:
        """A random UUID that doesn't exist must return 404."""
        client, *_ = feedback_client
        resp = client.post(
            f"/api/v1/insights/{uuid.uuid4()}/apply",
            json={"applied": True},
        )
        assert resp.status_code == 404

    def test_apply_auth_required(self, db_session: Session) -> None:
        """Without overriding get_current_membership the endpoint should 401/422/403."""
        # Build a fresh app with NO dependency override (no auth)
        bare_app = FastAPI()
        bare_app.include_router(insights_router, prefix="/api/v1")

        tenant = _make_tenant(db_session)
        insight = _make_insight(db_session, tenant)
        db_session.commit()

        # Override only DB, not membership — the real dep will fail without a token
        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        bare_app.dependency_overrides[get_db] = override_get_db
        bare_client = TestClient(bare_app, raise_server_exceptions=False)

        resp = bare_client.post(
            f"/api/v1/insights/{insight.id}/apply",
            json={"applied": True},
        )
        # Without a valid JWT the auth dependency raises 401
        assert resp.status_code in (401, 403, 422)

        bare_app.dependency_overrides.clear()


# ── React endpoint tests ──────────────────────────────────────────────────────


class TestReactEndpoint:
    """POST /api/v1/insights/{id}/react"""

    def test_react_up(self, feedback_client) -> None:
        """Sending reaction='up' should set reaction to 'up'."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "up"},
        )
        assert resp.status_code == 200
        assert resp.json()["reaction"] == "up"

    def test_react_down(self, feedback_client) -> None:
        """Sending reaction='down' should set reaction to 'down'."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "down"},
        )
        assert resp.status_code == 200
        assert resp.json()["reaction"] == "down"

    def test_react_null_clears_reaction(self, feedback_client) -> None:
        """Sending reaction=null should clear the existing reaction."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant, reaction="up")
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": None},
        )
        assert resp.status_code == 200
        assert resp.json()["reaction"] is None

    def test_react_returns_full_insight(self, feedback_client) -> None:
        """The react response must include all standard insight fields."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "up"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(insight.id)
        assert body["category"] == "roas_drop"

    def test_react_invalid_value_returns_422(self, feedback_client) -> None:
        """An invalid reaction value (not 'up' | 'down' | null) must return 422."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "meh"},
        )
        assert resp.status_code == 422

    def test_react_invalid_value_sideways_returns_422(self, feedback_client) -> None:
        """Another invalid value (not 'up' | 'down' | null) must return 422."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "thumbs_up"},
        )
        assert resp.status_code == 422

    def test_react_404_for_wrong_tenant(self, feedback_client, db_session: Session) -> None:
        """Tenant isolation: reacting to another tenant's insight must return 404."""
        client, _, _, db = feedback_client
        other_tenant = _make_tenant(db, name="Other Tenant B")
        other_insight = _make_insight(db, other_tenant)
        db.commit()

        resp = client.post(
            f"/api/v1/insights/{other_insight.id}/react",
            json={"reaction": "up"},
        )
        assert resp.status_code == 404

    def test_react_404_for_nonexistent_insight(self, feedback_client) -> None:
        """A random UUID that doesn't exist must return 404."""
        client, *_ = feedback_client
        resp = client.post(
            f"/api/v1/insights/{uuid.uuid4()}/react",
            json={"reaction": "down"},
        )
        assert resp.status_code == 404

    def test_react_auth_required(self, db_session: Session) -> None:
        """Without overriding get_current_membership the endpoint should 401/422/403."""
        bare_app = FastAPI()
        bare_app.include_router(insights_router, prefix="/api/v1")

        tenant = _make_tenant(db_session)
        insight = _make_insight(db_session, tenant)
        db_session.commit()

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        bare_app.dependency_overrides[get_db] = override_get_db
        bare_client = TestClient(bare_app, raise_server_exceptions=False)

        resp = bare_client.post(
            f"/api/v1/insights/{insight.id}/react",
            json={"reaction": "up"},
        )
        assert resp.status_code in (401, 403, 422)
        bare_app.dependency_overrides.clear()


# ── List endpoint filter tests ─────────────────────────────────────────────────


class TestListFilterFeedback:
    """GET /api/v1/insights?applied=...&reaction=..."""

    def _seed_insights(self, db: Session, tenant: Tenant) -> dict:
        """
        Create 4 insights:
        - applied_no_reaction   : applied_at set, no reaction
        - applied_up            : applied_at set, reaction='up'
        - unapplied_down        : applied_at null, reaction='down'
        - unapplied_no_reaction : applied_at null, no reaction
        """
        now = datetime.now(timezone.utc)
        applied_no_reaction = _make_insight(
            db, tenant,
            title="applied no reaction",
            applied_at=now,
            reaction=None,
            score=80.0,
        )
        applied_up = _make_insight(
            db, tenant,
            title="applied up",
            applied_at=now,
            reaction="up",
            score=70.0,
        )
        unapplied_down = _make_insight(
            db, tenant,
            title="unapplied down",
            applied_at=None,
            reaction="down",
            score=60.0,
        )
        unapplied_no_reaction = _make_insight(
            db, tenant,
            title="unapplied no reaction",
            applied_at=None,
            reaction=None,
            score=50.0,
        )
        db.commit()
        return {
            "applied_no_reaction": applied_no_reaction,
            "applied_up": applied_up,
            "unapplied_down": unapplied_down,
            "unapplied_no_reaction": unapplied_no_reaction,
        }

    def test_filter_applied_true_returns_only_applied(self, feedback_client) -> None:
        """applied=true should return only insights where applied_at IS NOT NULL."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get("/api/v1/insights", params={"applied": "true"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        titles = {r["title"] for r in body}
        assert "applied no reaction" in titles
        assert "applied up" in titles

    def test_filter_applied_false_returns_only_unapplied(self, feedback_client) -> None:
        """applied=false should return only insights where applied_at IS NULL."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get("/api/v1/insights", params={"applied": "false"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        titles = {r["title"] for r in body}
        assert "unapplied down" in titles
        assert "unapplied no reaction" in titles

    def test_filter_reaction_up_returns_only_up(self, feedback_client) -> None:
        """reaction=up should return only insights with reaction='up'."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get("/api/v1/insights", params={"reaction": "up"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "applied up"

    def test_filter_reaction_down_returns_only_down(self, feedback_client) -> None:
        """reaction=down should return only insights with reaction='down'."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get("/api/v1/insights", params={"reaction": "down"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "unapplied down"

    def test_filter_applied_and_reaction_combined(self, feedback_client) -> None:
        """applied=true&reaction=up should return only the one matching insight."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get(
            "/api/v1/insights", params={"applied": "true", "reaction": "up"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "applied up"
        assert body[0]["applied_at"] is not None
        assert body[0]["reaction"] == "up"

    def test_no_filter_returns_all(self, feedback_client) -> None:
        """Without applied/reaction filters all insights are returned (backward compat)."""
        client, tenant, _, db = feedback_client
        self._seed_insights(db, tenant)

        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        assert len(resp.json()) == 4

    def test_response_includes_feedback_fields(self, feedback_client) -> None:
        """Every insight in the list response must include applied_at and reaction fields."""
        client, tenant, _, db = feedback_client
        now = datetime.now(timezone.utc)
        _make_insight(db, tenant, applied_at=now, reaction="up")
        db.commit()

        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert "applied_at" in item
        assert "reaction" in item
        assert item["reaction"] == "up"
        assert item["applied_at"] is not None

    def test_list_reaction_invalid_value_422(self, feedback_client) -> None:
        """Passing an invalid reaction query param should return 422."""
        client, *_ = feedback_client
        resp = client.get("/api/v1/insights", params={"reaction": "sideways"})
        assert resp.status_code == 422

    def test_tenant_isolation_in_list(self, feedback_client, db_session: Session) -> None:
        """List must not return insights from a different tenant."""
        client, my_tenant, _, db = feedback_client
        other_tenant = _make_tenant(db, name="List Isolation Tenant")
        # Create insight for OTHER tenant
        _make_insight(db, other_tenant, title="other tenant insight")
        # Create insight for MY tenant
        _make_insight(db, my_tenant, title="my insight")
        db.commit()

        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "my insight"


# ── Existing field backward-compat tests ──────────────────────────────────────


class TestFeedbackFieldsOnExistingEndpoints:
    """Ensure existing endpoints (PATCH status, GET list) still work and include
    the new nullable fields with safe defaults."""

    def test_patch_status_response_includes_feedback_fields(
        self, feedback_client
    ) -> None:
        """PATCH /{id} still works and the response now includes applied_at/reaction."""
        client, tenant, _, db = feedback_client
        insight = _make_insight(db, tenant)
        db.commit()

        resp = client.patch(
            f"/api/v1/insights/{insight.id}",
            json={"status": "seen"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "seen"
        # New fields must be present (and null for a fresh insight)
        assert "applied_at" in body
        assert "reaction" in body
        assert body["applied_at"] is None
        assert body["reaction"] is None

    def test_list_insight_includes_null_feedback_by_default(
        self, feedback_client
    ) -> None:
        """Fresh insights (no feedback) must expose applied_at=null, reaction=null."""
        client, tenant, _, db = feedback_client
        _make_insight(db, tenant)
        db.commit()

        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["applied_at"] is None
        assert body[0]["reaction"] is None
