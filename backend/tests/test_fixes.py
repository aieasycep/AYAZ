"""Tests for Root-cause + one-click fixes — M11 v2.

Coverage
--------
* suggested_fixes_for_insight: returns root_cause + fixes for each category.
* apply_fix: create_automation_rule persists the entity.
* apply_fix: create_goal persists the entity.
* apply_fix: dismiss_insight sets status to dismissed.
* apply_fix: view_campaign returns success without writing.
* apply_fix: invalid action_type returns error.
* Tenant isolation: GET /insights/{id}/fixes and POST /fixes/apply
  enforce tenant ownership (404 on cross-tenant access).
* API: GET /{id}/fixes endpoint returns root_cause + fixes.
* API: POST /{id}/fixes/apply creates rule/goal/dismiss; 404 on wrong tenant.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1.insights import router as insights_router
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.automation import AutomationRule
from ayaz.models.base import Base
from ayaz.models.goals import Goal
from ayaz.models.insights import Insight
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

# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(insights_router, prefix="/api/v1")

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
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.tracking  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.copilot  # noqa: F401
    import ayaz.models.goals  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Tenant") -> Tenant:
    t = Tenant(id=uuid.uuid4(), name=name, base_currency="TRY", country="TR", kvkk_region="TR")
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "test@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(), email=email,
        hashed_password=hash_password("pass1234"), full_name="Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id, role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _make_insight(
    db: Session,
    tenant: Tenant,
    category: str = "roas_drop",
    severity: str = "warning",
    channel: str | None = "google_ads",
    metric: str = "roas",
    data: dict | None = None,
) -> Insight:
    today = date.today()
    insight = Insight(
        tenant_id=tenant.id,
        category=category,
        severity=severity,
        title=f"Test Insight [{category}]",
        body="Test body.",
        metric=metric,
        channel=channel,
        entity_type=None,
        entity_id=None,
        entity_name=None,
        period_start=today - timedelta(days=7),
        period_end=today,
        status="new",
        score=75.0,
        data=data or {},
    )
    db.add(insight)
    db.flush()
    return insight


def _make_client(db: Session, membership: Membership) -> TestClient:
    def override_db():
        yield db

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    return TestClient(_test_app)


@pytest.fixture()
def seeded(db_session: Session):
    db = db_session
    tenant = _make_tenant(db, "Fix Tenant")
    user = _make_user(db)
    membership = _make_membership(db, user, tenant)
    db.commit()
    return db, tenant, user, membership


# ── Service: suggested_fixes_for_insight ─────────────────────────────────────


class TestSuggestedFixes:
    def test_roas_drop_returns_root_cause_and_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="roas_drop", metric="roas",
            channel="google_ads",
            data={
                "current_roas": 1.5,
                "prior_roas": 3.0,
                "pct_drop": 0.5,
                "current_spend": 5000.0,
                "current_conversion_value": 7500.0,
            },
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)

        assert suggestion.insight_id == insight.id
        # Root cause should reference actual measured values
        assert "1.5" in suggestion.root_cause or "ROAS" in suggestion.root_cause
        assert len(suggestion.fixes) >= 2
        # Should have create_automation_rule and create_goal actions
        action_types = {f.action_type for f in suggestion.fixes}
        assert "create_automation_rule" in action_types
        assert "create_goal" in action_types
        assert "dismiss_insight" in action_types

    def test_zero_conversions_returns_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="zero_conversions", metric="conversions",
            channel="facebook_ads",
            data={"spend": 1200.0, "conversions": 0},
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)

        assert suggestion.root_cause
        assert "facebook_ads" in suggestion.root_cause or "kanal" in suggestion.root_cause
        assert len(suggestion.fixes) >= 2

    def test_spend_spike_returns_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="spend_spike", metric="spend",
            data={"current_spend": 8000.0, "prior_spend": 4000.0, "pct_rise": 1.0},
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        assert suggestion.root_cause
        assert "create_automation_rule" in {f.action_type for f in suggestion.fixes}

    def test_ctr_drop_returns_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="ctr_drop", metric="ctr",
            data={
                "current_ctr": 0.01, "prior_ctr": 0.02, "pct_drop": 0.5,
                "current_impressions": 50000.0, "current_clicks": 500.0,
            },
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        assert suggestion.root_cause
        assert "create_automation_rule" in {f.action_type for f in suggestion.fixes}
        assert "view_campaign" in {f.action_type for f in suggestion.fixes}

    def test_cpc_rise_returns_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="cpc_rise", metric="cpc",
            data={
                "current_cpc": 1.5, "prior_cpc": 1.0, "pct_rise": 0.5,
                "current_spend": 750.0, "current_clicks": 500.0,
            },
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        assert suggestion.root_cause
        assert "CPC" in suggestion.root_cause or "maliyet" in suggestion.root_cause

    def test_anomaly_returns_fixes(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="anomaly", metric="spend",
            data={
                "candidate_value": 9999.0, "history_mean": 1000.0,
                "z_score": 3.5, "direction": "yuksek",
            },
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        assert suggestion.root_cause
        assert "anomal" in suggestion.root_cause.lower() or "sapma" in suggestion.root_cause.lower()
        assert "create_automation_rule" in {f.action_type for f in suggestion.fixes}

    def test_unknown_category_returns_generic(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="unknown_category", metric="spend",
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        # Should not raise; should return at least a dismiss action
        assert suggestion.root_cause
        assert len(suggestion.fixes) >= 1
        assert "dismiss_insight" in {f.action_type for f in suggestion.fixes}

    def test_fix_payload_has_tenant_safe_defaults(self, seeded):
        """Rule payloads must not include tenant_id — it's injected by apply_fix."""
        db, tenant, *_ = seeded
        from ayaz.services.fixes import suggested_fixes_for_insight

        insight = _make_insight(
            db, tenant, category="roas_drop", metric="roas",
            data={"current_roas": 1.0, "prior_roas": 2.0, "pct_drop": 0.5},
        )
        db.commit()

        suggestion = suggested_fixes_for_insight(db, tenant.id, insight)
        for fix in suggestion.fixes:
            # No tenant_id should leak into the payload (injected at apply time)
            assert "tenant_id" not in fix.payload


# ── Service: apply_fix ────────────────────────────────────────────────────────


class TestApplyFix:
    def test_create_automation_rule(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()

        payload = {
            "name": "Fix Rule",
            "scope": "account",
            "metric": "roas",
            "comparator": "pct_drop",
            "threshold": 20.0,
            "action": "alert",
            "window_days": 7,
        }
        result = apply_fix(db, tenant.id, insight, "create_automation_rule", payload)
        db.commit()

        assert result.success is True
        assert result.entity_type == "automation_rule"
        assert result.entity_id is not None
        rule = db.get(AutomationRule, uuid.UUID(result.entity_id))
        assert rule.tenant_id == tenant.id
        assert rule.name == "Fix Rule"

    def test_create_goal(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()

        today = date.today()
        payload = {
            "name": "Fix Goal",
            "metric": "roas",
            "target_value": 3.0,
            "period_start": today.replace(day=1).isoformat(),
            "period_end": today.isoformat(),
        }
        result = apply_fix(db, tenant.id, insight, "create_goal", payload)
        db.commit()

        assert result.success is True
        assert result.entity_type == "goal"
        goal = db.get(Goal, uuid.UUID(result.entity_id))
        assert goal.tenant_id == tenant.id
        assert goal.target_value == pytest.approx(3.0)

    def test_dismiss_insight(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()
        assert insight.status == "new"

        result = apply_fix(
            db, tenant.id, insight, "dismiss_insight",
            {"insight_id": str(insight.id)},
        )
        db.commit()

        assert result.success is True
        db.refresh(insight)
        assert insight.status == "dismissed"

    def test_view_campaign_is_noop(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()

        result = apply_fix(
            db, tenant.id, insight, "view_campaign",
            {"channel": "google_ads", "metric": "roas"},
        )
        assert result.success is True
        assert result.entity_id is None

    def test_invalid_action_type_returns_error(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()

        result = apply_fix(db, tenant.id, insight, "hack_the_ads_platform", {})
        assert result.success is False
        assert "bilinmeyen" in result.message.lower() or "invalid" in result.message.lower()

    def test_create_rule_with_invalid_metric_returns_error(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.fixes import apply_fix

        insight = _make_insight(db, tenant)
        db.commit()

        result = apply_fix(
            db, tenant.id, insight, "create_automation_rule",
            {
                "name": "Bad",
                "metric": "not_a_metric",
                "comparator": "pct_drop",
                "threshold": 10.0,
                "action": "alert",
            },
        )
        assert result.success is False
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 0


# ── API tests ─────────────────────────────────────────────────────────────────


class TestFixesAPI:
    def test_get_fixes_returns_root_cause_and_fixes(self, seeded):
        db, tenant, user, membership = seeded
        insight = _make_insight(
            db, tenant, category="roas_drop", metric="roas",
            data={
                "current_roas": 1.5, "prior_roas": 3.0, "pct_drop": 0.5,
                "current_spend": 2000.0, "current_conversion_value": 3000.0,
            },
        )
        db.commit()

        client = _make_client(db, membership)
        resp = client.get(f"/api/v1/insights/{insight.id}/fixes")
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["insight_id"] == str(insight.id)
        assert data["root_cause"]
        assert isinstance(data["fixes"], list)
        assert len(data["fixes"]) >= 1
        for fix in data["fixes"]:
            assert "label" in fix
            assert "action_type" in fix
            assert "payload" in fix

    def test_get_fixes_404_wrong_tenant(self, db_session: Session):
        db = db_session
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        user_b = _make_user(db, "b@test.com")
        membership_b = _make_membership(db, user_b, tenant_b)

        insight = _make_insight(db, tenant_a, category="roas_drop")
        db.commit()

        client = _make_client(db, membership_b)
        resp = client.get(f"/api/v1/insights/{insight.id}/fixes")
        assert resp.status_code == 404

    def test_apply_fix_create_rule(self, seeded):
        db, tenant, user, membership = seeded
        insight = _make_insight(db, tenant, category="roas_drop", metric="roas")
        db.commit()

        client = _make_client(db, membership)
        resp = client.post(
            f"/api/v1/insights/{insight.id}/fixes/apply",
            json={
                "action_type": "create_automation_rule",
                "payload": {
                    "name": "API Rule",
                    "scope": "account",
                    "metric": "roas",
                    "comparator": "pct_drop",
                    "threshold": 20.0,
                    "action": "alert",
                    "window_days": 7,
                },
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["entity_type"] == "automation_rule"
        assert data["entity_id"] is not None

        # Verify in DB
        rule = db.get(AutomationRule, uuid.UUID(data["entity_id"]))
        assert rule.tenant_id == tenant.id

    def test_apply_fix_create_goal(self, seeded):
        db, tenant, user, membership = seeded
        insight = _make_insight(db, tenant, category="zero_conversions", metric="conversions")
        db.commit()

        today = date.today()
        client = _make_client(db, membership)
        resp = client.post(
            f"/api/v1/insights/{insight.id}/fixes/apply",
            json={
                "action_type": "create_goal",
                "payload": {
                    "name": "API Goal",
                    "metric": "roas",
                    "target_value": 3.0,
                    "period_start": today.replace(day=1).isoformat(),
                    "period_end": today.isoformat(),
                },
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["entity_type"] == "goal"

    def test_apply_fix_dismiss(self, seeded):
        db, tenant, user, membership = seeded
        insight = _make_insight(db, tenant, category="roas_drop")
        db.commit()
        assert insight.status == "new"

        client = _make_client(db, membership)
        resp = client.post(
            f"/api/v1/insights/{insight.id}/fixes/apply",
            json={
                "action_type": "dismiss_insight",
                "payload": {"insight_id": str(insight.id)},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True

        db.refresh(insight)
        assert insight.status == "dismissed"

    def test_apply_fix_404_wrong_tenant(self, db_session: Session):
        db = db_session
        tenant_a = _make_tenant(db, "Ax")
        tenant_b = _make_tenant(db, "Bx")
        user_b = _make_user(db, "bx@test.com")
        membership_b = _make_membership(db, user_b, tenant_b)
        insight = _make_insight(db, tenant_a)
        db.commit()

        client = _make_client(db, membership_b)
        resp = client.post(
            f"/api/v1/insights/{insight.id}/fixes/apply",
            json={
                "action_type": "dismiss_insight",
                "payload": {"insight_id": str(insight.id)},
            },
        )
        assert resp.status_code == 404

    def test_apply_fix_invalid_action_type_422(self, seeded):
        db, tenant, user, membership = seeded
        insight = _make_insight(db, tenant)
        db.commit()

        client = _make_client(db, membership)
        resp = client.post(
            f"/api/v1/insights/{insight.id}/fixes/apply",
            json={
                "action_type": "delete_all_ads",
                "payload": {},
            },
        )
        assert resp.status_code == 422
