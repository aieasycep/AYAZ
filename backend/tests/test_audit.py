"""Self-contained tests for Hesap Sağlık Taraması (Account Health Audit).

Coverage
--------
1. Empty tenant
   - run_account_audit runs without error
   - returns a valid score (integer, 0-100)
   - grade is one of the four valid values
   - counts keys are present and consistent with checks
   - some warns/fails expected (no tracking, no budget plan)

2. Score formula
   - each fail deducts 12, each warn deducts 4; floor at 0
   - pure helper _compute_score verified directly

3. Seeded scenarios
   - TrackingSource with no active destination → tracking fail present
   - BudgetPlan present → budget category is pass
   - TrackingSource with failed events → tracking warn present

4. HTTP endpoint
   - GET /audit/run → 200 with correct response shape
   - missing auth → 401 / 403
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

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
from ayaz.models.insights import Insight
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import audit as audit_module
from ayaz.services.audit import _compute_score, _grade, run_account_audit
from ayaz.services.auth import hash_password

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Audit Test App")
_test_app.include_router(audit_module.router, prefix="/api/v1")


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
        name="Audit Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="audit_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Audit Test User",
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


def _make_tenant(db: Session, name: str = "Audit Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_tracking_source(db: Session, tenant: Tenant, name: str = "Test Source") -> TrackingSource:
    src = TrackingSource(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=name,
        domain="example.com",
        public_token=secrets.token_urlsafe(32),
        is_active=True,
        disabled_events=[],
    )
    db.add(src)
    db.flush()
    return src


def _make_destination(db: Session, tenant: Tenant, source: TrackingSource) -> EventDestination:
    dest = EventDestination(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tracking_source_id=source.id,
        platform="meta_capi",
        config={"pixel_id": "TEST123"},
        vault_secret_ref="vault/test",
        consent_required=True,
        is_active=True,
    )
    db.add(dest)
    db.flush()
    return dest


def _make_event(
    db: Session,
    tenant: Tenant,
    source: TrackingSource,
    status: str = "forwarded",
    created_at: str | None = None,
) -> ConversionEvent:
    now = created_at or datetime.now(timezone.utc).isoformat()
    event = ConversionEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tracking_source_id=source.id,
        event_name="Purchase",
        event_time=now,
        event_id=str(uuid.uuid4()),
        user_data={},
        custom_data={},
        consent=True,
        status=status,
        forwarded_count=1 if status == "forwarded" else 0,
        error="Connection refused" if status == "failed" else None,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return event


def _make_budget_plan(db: Session, tenant: Tenant) -> BudgetPlan:
    plan = BudgetPlan(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Temmuz 2026 Planı",
        period_month="2026-07",
        total_budget=50000,
        currency="TRY",
        objective="balanced",
        status="active",
    )
    db.add(plan)
    db.flush()
    return plan


def _make_insight(
    db: Session,
    tenant: Tenant,
    severity: str = "warning",
) -> Insight:
    today = date.today()
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="roas_drop",
        severity=severity,
        title="Test İçgörü",
        body="Test body.",
        metric="roas",
        channel="google_ads",
        period_start=today,
        period_end=today,
        status="new",
        score=0.8,
        data={},
    )
    db.add(ins)
    db.flush()
    return ins


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure helper unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeScore:
    def test_no_checks_returns_100(self) -> None:
        assert _compute_score([]) == 100

    def test_single_fail_deducts_12(self) -> None:
        checks = [{"severity": "fail"}]
        assert _compute_score(checks) == 88

    def test_single_warn_deducts_4(self) -> None:
        checks = [{"severity": "warn"}]
        assert _compute_score(checks) == 96

    def test_pass_has_no_effect(self) -> None:
        checks = [{"severity": "pass"}, {"severity": "pass"}]
        assert _compute_score(checks) == 100

    def test_mixed_fails_and_warns(self) -> None:
        checks = [
            {"severity": "fail"},   # -12
            {"severity": "fail"},   # -12
            {"severity": "warn"},   # -4
            {"severity": "pass"},   # 0
        ]
        # 100 - 12 - 12 - 4 = 72
        assert _compute_score(checks) == 72

    def test_score_floors_at_zero(self) -> None:
        checks = [{"severity": "fail"}] * 10  # 10 * 12 = 120 → floor at 0
        assert _compute_score(checks) == 0


class TestGrade:
    def test_100_is_mukemmel(self) -> None:
        assert _grade(100) == "mukemmel"

    def test_85_is_mukemmel(self) -> None:
        assert _grade(85) == "mukemmel"

    def test_84_is_iyi(self) -> None:
        assert _grade(84) == "iyi"

    def test_65_is_iyi(self) -> None:
        assert _grade(65) == "iyi"

    def test_64_is_orta(self) -> None:
        assert _grade(64) == "orta"

    def test_40_is_orta(self) -> None:
        assert _grade(40) == "orta"

    def test_39_is_zayif(self) -> None:
        assert _grade(39) == "zayif"

    def test_0_is_zayif(self) -> None:
        assert _grade(0) == "zayif"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Empty tenant — run_account_audit (service level)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyTenantAudit:
    def test_runs_without_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Audit Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        assert isinstance(result, dict)

    def test_score_is_valid_integer(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Score Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_grade_is_valid(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Grade Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        assert result["grade"] in {"mukemmel", "iyi", "orta", "zayif"}

    def test_counts_are_consistent_with_checks(self, db_session: Session) -> None:
        """counts must equal the actual per-severity tally across all checks."""
        tenant = _make_tenant(db_session, "Counts Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)

        all_checks = [c for cat in result["categories"] for c in cat["checks"]]
        expected_pass = sum(1 for c in all_checks if c["severity"] == "pass")
        expected_warn = sum(1 for c in all_checks if c["severity"] == "warn")
        expected_fail = sum(1 for c in all_checks if c["severity"] == "fail")

        assert result["counts"]["pass"] == expected_pass
        assert result["counts"]["warn"] == expected_warn
        assert result["counts"]["fail"] == expected_fail

    def test_score_matches_formula(self, db_session: Session) -> None:
        """score must equal 100 - 12*fails - 4*warns, floored at 0."""
        tenant = _make_tenant(db_session, "Formula Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)

        all_checks = [c for cat in result["categories"] for c in cat["checks"]]
        fails = sum(1 for c in all_checks if c["severity"] == "fail")
        warns = sum(1 for c in all_checks if c["severity"] == "warn")
        expected_score = max(0, 100 - 12 * fails - 4 * warns)
        assert result["score"] == expected_score

    def test_has_six_categories(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Category Count Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        category_keys = {cat["key"] for cat in result["categories"]}
        assert category_keys == {"ads", "tracking", "budget", "content", "goals", "insights", "data_quality"}

    def test_empty_tenant_has_tracking_fail(self, db_session: Session) -> None:
        """No TrackingSource → tracking category must emit a fail."""
        tenant = _make_tenant(db_session, "No Tracking Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)

        tracking_cat = next(c for c in result["categories"] if c["key"] == "tracking")
        severity_set = {c["severity"] for c in tracking_cat["checks"]}
        assert "fail" in severity_set

    def test_empty_tenant_has_budget_warn(self, db_session: Session) -> None:
        """No BudgetPlan → budget category must emit a warn."""
        tenant = _make_tenant(db_session, "No Budget Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)

        budget_cat = next(c for c in result["categories"] if c["key"] == "budget")
        severity_set = {c["severity"] for c in budget_cat["checks"]}
        assert "warn" in severity_set

    def test_summary_is_non_empty_string(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Summary Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_summary_mentions_score(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Summary Score Tenant")
        db_session.commit()
        result = run_account_audit(db_session, tenant.id)
        assert str(result["score"]) in result["summary"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Seeded scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestSeededScenarios:
    def test_source_with_no_destination_emits_tracking_fail(self, db_session: Session) -> None:
        """A TrackingSource that has no active EventDestination → tracking fail."""
        tenant = _make_tenant(db_session, "No Dest Tenant")
        _make_tracking_source(db_session, tenant, "Orphan Source")
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        tracking_cat = next(c for c in result["categories"] if c["key"] == "tracking")
        fail_ids = [c["id"] for c in tracking_cat["checks"] if c["severity"] == "fail"]
        assert "tracking_no_destination" in fail_ids

    def test_budget_plan_present_emits_budget_pass(self, db_session: Session) -> None:
        """BudgetPlan present → budget category emits pass."""
        tenant = _make_tenant(db_session, "Has Budget Tenant")
        _make_budget_plan(db_session, tenant)
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        budget_cat = next(c for c in result["categories"] if c["key"] == "budget")
        pass_checks = [c for c in budget_cat["checks"] if c["severity"] == "pass"]
        assert len(pass_checks) >= 1

    def test_source_with_destination_no_orphan_fail(self, db_session: Session) -> None:
        """TrackingSource with a proper active destination → no orphan fail."""
        tenant = _make_tenant(db_session, "With Dest Tenant")
        src = _make_tracking_source(db_session, tenant, "Proper Source")
        _make_destination(db_session, tenant, src)
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        tracking_cat = next(c for c in result["categories"] if c["key"] == "tracking")
        fail_ids = [c["id"] for c in tracking_cat["checks"] if c["severity"] == "fail"]
        assert "tracking_no_destination" not in fail_ids

    def test_failed_events_emit_tracking_warn(self, db_session: Session) -> None:
        """Failed events → tracking warn for failed transmissions."""
        tenant = _make_tenant(db_session, "Failed Events Tenant")
        src = _make_tracking_source(db_session, tenant, "Source With Errors")
        _make_destination(db_session, tenant, src)
        # Seed a failed event within the last 30 days
        _make_event(db_session, tenant, src, status="failed")
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        tracking_cat = next(c for c in result["categories"] if c["key"] == "tracking")
        warn_ids = [c["id"] for c in tracking_cat["checks"] if c["severity"] == "warn"]
        assert "tracking_failed_events" in warn_ids

    def test_critical_insight_emits_insights_fail(self, db_session: Session) -> None:
        """A critical insight → insights category emits fail."""
        tenant = _make_tenant(db_session, "Critical Insight Tenant")
        _make_insight(db_session, tenant, severity="critical")
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        insights_cat = next(c for c in result["categories"] if c["key"] == "insights")
        fail_ids = [c["id"] for c in insights_cat["checks"] if c["severity"] == "fail"]
        assert "insights_critical" in fail_ids

    def test_warning_insight_emits_insights_warn(self, db_session: Session) -> None:
        """A warning insight → insights category emits warn."""
        tenant = _make_tenant(db_session, "Warning Insight Tenant")
        _make_insight(db_session, tenant, severity="warning")
        db_session.commit()

        result = run_account_audit(db_session, tenant.id)
        insights_cat = next(c for c in result["categories"] if c["key"] == "insights")
        warn_ids = [c["id"] for c in insights_cat["checks"] if c["severity"] == "warn"]
        assert "insights_warnings" in warn_ids

    def test_budget_pass_raises_score_vs_no_plan(self, db_session: Session) -> None:
        """Adding a budget plan should not lower the score vs having none."""
        tenant_no_plan = _make_tenant(db_session, "NoPlan Score Tenant")
        db_session.commit()
        result_no_plan = run_account_audit(db_session, tenant_no_plan.id)

        tenant_with_plan = _make_tenant(db_session, "WithPlan Score Tenant")
        _make_budget_plan(db_session, tenant_with_plan)
        db_session.commit()
        result_with_plan = run_account_audit(db_session, tenant_with_plan.id)

        # Having a plan removes a warn → equal or higher score
        assert result_with_plan["score"] >= result_no_plan["score"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditEndpoint:
    def test_happy_path_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/audit/run")
        assert resp.status_code == 200

    def test_response_shape_correct(self, client: TestClient) -> None:
        resp = client.get("/api/v1/audit/run")
        assert resp.status_code == 200
        body = resp.json()
        assert "score" in body
        assert "grade" in body
        assert "summary" in body
        assert "counts" in body
        assert "categories" in body
        assert isinstance(body["score"], int)
        assert isinstance(body["grade"], str)
        assert isinstance(body["summary"], str)
        assert isinstance(body["counts"], dict)
        assert isinstance(body["categories"], list)

    def test_counts_in_response(self, client: TestClient) -> None:
        resp = client.get("/api/v1/audit/run")
        body = resp.json()
        counts = body["counts"]
        # All three keys present (pass is serialised differently in JSON)
        assert set(counts.keys()) >= {"pass", "warn", "fail"} or set(counts.keys()) >= {"pass_", "warn", "fail"}

    def test_categories_have_correct_structure(self, client: TestClient) -> None:
        resp = client.get("/api/v1/audit/run")
        body = resp.json()
        for cat in body["categories"]:
            assert "key" in cat
            assert "label" in cat
            assert "checks" in cat
            assert isinstance(cat["checks"], list)
            for check in cat["checks"]:
                assert "id" in check
                assert "severity" in check
                assert check["severity"] in {"pass", "warn", "fail"}
                assert "title" in check
                assert "finding" in check
                assert "recommendation" in check

    def test_unauthenticated_returns_401_or_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/audit/run")
        assert resp.status_code in (401, 403)
