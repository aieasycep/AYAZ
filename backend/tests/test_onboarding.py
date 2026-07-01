"""Self-contained tests for Kurulum Sihirbazı (Onboarding Wizard).

Coverage
--------
1. Service layer — build_onboarding_status
   - empty tenant → all steps done=false, completed_steps=0, percent=0, all_done=false
   - 5 steps present in canonical order with correct keys
   - seed Goal + TrackingSource → those two done=true, completed_steps=2, percent=40
   - seed all five models → all_done=true, percent=100

2. HTTP endpoint
   - 200 happy path with correct response shape
   - missing auth → 401 or 403
   - response fields: total_steps=5, steps list length=5, each step has all keys

3. Tenant isolation
   - another tenant's data does not affect the requesting tenant's status
"""

from __future__ import annotations

import uuid

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
from ayaz.models.base import Base
from ayaz.models.budget import BudgetPlan
from ayaz.models.content import ContentPost
from ayaz.models.goals import Goal
from ayaz.models.oltp import (
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
)
from ayaz.models.tracking import TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import onboarding as onboarding_module
from ayaz.services.auth import hash_password
from ayaz.services.onboarding import build_onboarding_status

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Onboarding Test App")
_test_app.include_router(onboarding_module.router, prefix="/api/v1")


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
        name="Onboarding Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="onboarding_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Onboarding Test User",
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
    """TestClient with NO membership override — tests 401/403 behaviour."""
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


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
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


def _make_user(db: Session, email: str = "user@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pw"),
        full_name="Test User",
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


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.sample,
        external_account_id=f"ACC-{uuid.uuid4().hex[:6]}",
        display_name="Test Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_goal(db: Session, tenant: Tenant) -> Goal:
    g = Goal(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Test ROAS Hedefi",
        metric="roas",
        target_value=3.5,
        period="month",
        period_start="2026-06-01",
        period_end="2026-06-30",
        channel_filter=None,
        is_active=True,
    )
    db.add(g)
    db.flush()
    return g


def _make_tracking_source(db: Session, tenant: Tenant) -> TrackingSource:
    ts = TrackingSource(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Test Tracking Source",
        public_token=f"tok-{uuid.uuid4().hex[:16]}",
    )
    db.add(ts)
    db.flush()
    return ts


def _make_budget_plan(db: Session, tenant: Tenant) -> BudgetPlan:
    bp = BudgetPlan(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Temmuz 2026 Planı",
        period_month="2026-07",
        total_budget=50000,
        currency="TRY",
        objective="balanced",
        lookback_days=90,
        allocations=None,
        status="draft",
    )
    db.add(bp)
    db.flush()
    return bp


def _make_content_post(db: Session, tenant: Tenant) -> ContentPost:
    cp = ContentPost(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="İlk İçerik Gönderisi",
        body="Test içerik metni.",
        channels=["instagram"],
        status="draft",
    )
    db.add(cp)
    db.flush()
    return cp


# ── Canonical step order ───────────────────────────────────────────────────────

_EXPECTED_STEP_KEYS = [
    "connect_accounts",
    "set_goal",
    "tracking",
    "budget_plan",
    "first_content",
]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Service layer — empty tenant
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyTenant:
    def test_all_steps_not_done(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        assert all(not s["done"] for s in result["steps"])

    def test_completed_steps_zero(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        assert result["completed_steps"] == 0

    def test_percent_zero(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        assert result["percent"] == 0

    def test_all_done_false(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        assert result["all_done"] is False

    def test_five_steps_in_canonical_order(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        assert result["total_steps"] == 5
        assert len(result["steps"]) == 5
        actual_keys = [s["key"] for s in result["steps"]]
        assert actual_keys == _EXPECTED_STEP_KEYS

    def test_each_step_has_required_fields(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_onboarding_status(db_session, tenant.id)
        required_fields = {"key", "title", "description", "done", "cta_label", "cta_link"}
        for step in result["steps"]:
            assert set(step.keys()) >= required_fields


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Service layer — partial completion (Goal + TrackingSource seeded)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPartialCompletion:
    def test_goal_and_tracking_done(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        step_map = {s["key"]: s for s in result["steps"]}

        assert step_map["set_goal"]["done"] is True
        assert step_map["tracking"]["done"] is True

    def test_other_steps_not_done(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        step_map = {s["key"]: s for s in result["steps"]}

        assert step_map["connect_accounts"]["done"] is False
        assert step_map["budget_plan"]["done"] is False
        assert step_map["first_content"]["done"] is False

    def test_completed_steps_is_two(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        assert result["completed_steps"] == 2

    def test_percent_is_40(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        assert result["percent"] == 40


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Service layer — all five steps seeded
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullCompletion:
    def test_all_done_true(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_connected_account(db_session, tenant)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        _make_budget_plan(db_session, tenant)
        _make_content_post(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        assert result["all_done"] is True

    def test_percent_100(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_connected_account(db_session, tenant)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        _make_budget_plan(db_session, tenant)
        _make_content_post(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        assert result["percent"] == 100

    def test_completed_steps_5(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _make_connected_account(db_session, tenant)
        _make_goal(db_session, tenant)
        _make_tracking_source(db_session, tenant)
        _make_budget_plan(db_session, tenant)
        _make_content_post(db_session, tenant)
        db_session.commit()

        result = build_onboarding_status(db_session, tenant.id)
        assert result["completed_steps"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_other_tenant_data_does_not_count(self, db_session: Session) -> None:
        """Seeding data for tenant_b must not affect tenant_a's wizard status."""
        tenant_a = _make_tenant(db_session, name="Tenant A")
        tenant_b = _make_tenant(db_session, name="Tenant B")

        # Seed all five steps for tenant_b only
        _make_connected_account(db_session, tenant_b)
        _make_goal(db_session, tenant_b)
        _make_tracking_source(db_session, tenant_b)
        _make_budget_plan(db_session, tenant_b)
        _make_content_post(db_session, tenant_b)
        db_session.commit()

        # tenant_a should still see zero completion
        result_a = build_onboarding_status(db_session, tenant_a.id)
        assert result_a["completed_steps"] == 0
        assert result_a["all_done"] is False
        assert all(not s["done"] for s in result_a["steps"])

        # tenant_b should see full completion
        result_b = build_onboarding_status(db_session, tenant_b.id)
        assert result_b["all_done"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOnboardingEndpoint:
    def test_happy_path_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/onboarding/status")
        assert resp.status_code == 200

    def test_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/onboarding/status")
        assert resp.status_code == 200
        body = resp.json()

        assert set(body.keys()) >= {
            "total_steps", "completed_steps", "percent", "all_done", "steps"
        }
        assert body["total_steps"] == 5
        assert isinstance(body["steps"], list)
        assert len(body["steps"]) == 5

        for step in body["steps"]:
            assert set(step.keys()) >= {
                "key", "title", "description", "done", "cta_label", "cta_link"
            }

    def test_steps_in_canonical_order(self, client: TestClient) -> None:
        resp = client.get("/api/v1/onboarding/status")
        assert resp.status_code == 200
        actual_keys = [s["key"] for s in resp.json()["steps"]]
        assert actual_keys == _EXPECTED_STEP_KEYS

    def test_unauthenticated_returns_401_or_403(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get("/api/v1/onboarding/status")
        assert resp.status_code in (401, 403)
