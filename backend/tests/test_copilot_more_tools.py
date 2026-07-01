"""Tests for the new Copilot read-only tools: get_notifications, get_goal_progress.

Coverage
--------
* Both tools are registered in _TOOLS and TOOL_SPECS.
* Neither tool is in ACTION_TOOLS.
* get_notifications: returns seeded notifications + correct unread_count.
* get_notifications: unread_only=True filters correctly.
* get_notifications: sync_from_insights runs lazily (new notifications from insights).
* get_goal_progress: returns progress for seeded goals.
* get_goal_progress: returns {goals: []} with a note when no goals exist.
* get_goal_progress: focuses on a single goal when goal_id is provided.
* Tenant isolation: get_notifications and get_goal_progress return only the
  requesting tenant's data even when another tenant has data in the same DB.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.goals import Goal
from ayaz.models.insights import Insight
from ayaz.models.notifications import Notification
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


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite DB with all AYAZ tables."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.copilot  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.goals  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.notifications  # noqa: F401
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.tracking  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Helper factories ──────────────────────────────────────────────────────────


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


def _make_user(db: Session, email: str = "test@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pass1234"),
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


def _make_notification(
    db: Session,
    tenant: Tenant,
    title: str = "Test Bildirimi",
    severity: str = "info",
    notif_type: str = "insight",
    read: bool = False,
) -> Notification:
    n = Notification(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        type=notif_type,
        severity=severity,
        title=title,
        body="Test gövde metni",
        link="/insights",
        source_ref=f"test:{uuid.uuid4()}",
        read_at=datetime.now(timezone.utc) if read else None,
    )
    db.add(n)
    db.flush()
    return n


def _make_insight(
    db: Session,
    tenant: Tenant,
    title: str = "Test İçgörüsü",
    severity: str = "warning",
) -> Insight:
    today = date.today()
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="performance",
        severity=severity,
        title=title,
        body="İçgörü açıklama metni",
        metric="roas",
        channel="google_ads",
        score=0.85,
        period_start=today - timedelta(days=7),
        period_end=today,
    )
    db.add(ins)
    db.flush()
    return ins


def _make_goal(
    db: Session,
    tenant: Tenant,
    name: str = "Test Hedefi",
    metric: str = "spend",
    target_value: float = 10000.0,
    is_active: bool = True,
) -> Goal:
    today = date.today()
    g = Goal(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=name,
        metric=metric,
        target_value=target_value,
        period="month",
        period_start=today.replace(day=1).isoformat(),
        period_end=(today.replace(day=1) + timedelta(days=30)).isoformat(),
        channel_filter=None,
        is_active=is_active,
    )
    db.add(g)
    db.flush()
    return g


# ── Registry tests ─────────────────────────────────────────────────────────────


class TestToolRegistry:
    """Both tools must appear in _TOOLS and TOOL_SPECS but NOT in ACTION_TOOLS."""

    def test_get_notifications_in_tools(self):
        from ayaz.services.copilot_tools import _TOOLS
        assert "get_notifications" in _TOOLS

    def test_get_goal_progress_in_tools(self):
        from ayaz.services.copilot_tools import _TOOLS
        assert "get_goal_progress" in _TOOLS

    def test_both_in_tool_specs(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        names = {t["name"] for t in TOOL_SPECS}
        assert "get_notifications" in names
        assert "get_goal_progress" in names

    def test_neither_in_action_tools(self):
        from ayaz.services.copilot_tools import ACTION_TOOLS
        assert "get_notifications" not in ACTION_TOOLS
        assert "get_goal_progress" not in ACTION_TOOLS

    def test_tool_specs_have_required_keys(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        for spec in TOOL_SPECS:
            if spec["name"] in {"get_notifications", "get_goal_progress"}:
                assert "name" in spec
                assert "description" in spec
                assert "input_schema" in spec
                assert len(spec["description"]) > 10, "Description should be non-trivial"


# ── get_notifications tests ────────────────────────────────────────────────────


class TestGetNotifications:
    def test_returns_seeded_notifications(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_notification(db, tenant, title="Bildirim 1", severity="info")
        _make_notification(db, tenant, title="Bildirim 2", severity="warning")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {})
        assert "notifications" in result
        assert "unread_count" in result
        assert len(result["notifications"]) == 2
        titles = {n["title"] for n in result["notifications"]}
        assert "Bildirim 1" in titles
        assert "Bildirim 2" in titles

    def test_unread_count_reflects_unread_notifications(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_notification(db, tenant, title="Okunmamış 1", read=False)
        _make_notification(db, tenant, title="Okunmamış 2", read=False)
        _make_notification(db, tenant, title="Okunmuş", read=True)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {})
        assert result["unread_count"] == 2

    def test_unread_only_filters_read_notifications(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_notification(db, tenant, title="Okunmamış", read=False)
        _make_notification(db, tenant, title="Okunmuş", read=True)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {"unread_only": True})
        assert len(result["notifications"]) == 1
        assert result["notifications"][0]["title"] == "Okunmamış"

    def test_notification_has_expected_fields(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_notification(db, tenant, title="Alan Testi", severity="critical")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {})
        n = result["notifications"][0]
        assert "id" in n
        assert "title" in n
        assert "severity" in n
        assert "type" in n
        assert "created_at" in n
        assert "read" in n
        assert n["severity"] == "critical"
        assert isinstance(n["read"], bool)

    def test_limit_respected(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        for i in range(15):
            _make_notification(db, tenant, title=f"Bildirim {i}")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {"limit": 5})
        assert len(result["notifications"]) == 5

    def test_sync_from_insights_creates_notifications_lazily(self, db_session: Session):
        """If insights exist but no notifications, the tool creates them on the fly."""
        db = db_session
        tenant = _make_tenant(db)
        _make_insight(db, tenant, title="ROAS Düştü")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        # No notifications exist yet
        from sqlalchemy import select
        count_before = db.scalar(
            select(Notification).where(Notification.tenant_id == tenant.id)
        )
        assert count_before is None  # no rows yet

        result = dispatch("get_notifications", db, tenant.id, {})
        # After the call, the insight should have been converted to a notification
        assert len(result["notifications"]) >= 1
        # The generated notification should mention the insight title or be present
        assert result["notifications"][0]["title"] is not None

    def test_empty_when_no_notifications_or_insights(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_notifications", db, tenant.id, {})
        assert result["unread_count"] == 0
        assert result["notifications"] == []

    def test_tenant_isolation(self, db_session: Session):
        db = db_session
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        _make_notification(db, tenant_a, title="Sadece A'nın Bildirimi")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result_b = dispatch("get_notifications", db, tenant_b.id, {})
        assert result_b["unread_count"] == 0
        assert result_b["notifications"] == []

        result_a = dispatch("get_notifications", db, tenant_a.id, {})
        assert len(result_a["notifications"]) == 1
        assert result_a["notifications"][0]["title"] == "Sadece A'nın Bildirimi"


# ── get_goal_progress tests ────────────────────────────────────────────────────


class TestGetGoalProgress:
    def test_returns_progress_for_seeded_goals(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_goal(db, tenant, name="Harcama Hedefi", metric="spend", target_value=50000.0)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {})
        assert "goals" in result
        assert len(result["goals"]) == 1

        g = result["goals"][0]
        assert g["name"] == "Harcama Hedefi"
        assert g["metric"] == "spend"
        assert g["target_value"] == pytest.approx(50000.0)

    def test_goal_progress_has_expected_fields(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_goal(db, tenant, name="ROAS Hedefi", metric="roas", target_value=4.0)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {})
        g = result["goals"][0]
        assert "goal_id" in g
        assert "name" in g
        assert "metric" in g
        assert "target_value" in g
        assert "current_value" in g
        assert "pct_to_target" in g
        assert "forecast_value" in g
        assert "status" in g
        assert "recommendation" in g
        assert g["status"] in {"on_track", "at_risk", "off_track"}

    def test_empty_goals_returns_empty_list_with_note(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {})
        assert result["goals"] == []
        assert "note" in result
        assert len(result["note"]) > 0

    def test_single_goal_focus_with_goal_id(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        goal1 = _make_goal(db, tenant, name="Hedef 1", metric="spend", target_value=10000.0)
        goal2 = _make_goal(db, tenant, name="Hedef 2", metric="conversions", target_value=500.0)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {"goal_id": str(goal1.id)})
        assert len(result["goals"]) == 1
        assert result["goals"][0]["name"] == "Hedef 1"

    def test_invalid_goal_id_returns_error(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {"goal_id": "not-a-uuid"})
        assert "error" in result

    def test_goal_id_not_found_returns_error(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        non_existent = str(uuid.uuid4())
        result = dispatch("get_goal_progress", db, tenant.id, {"goal_id": non_existent})
        assert "error" in result

    def test_inactive_goals_excluded(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_goal(db, tenant, name="Aktif Hedef", metric="spend", target_value=10000.0, is_active=True)
        _make_goal(db, tenant, name="Pasif Hedef", metric="roas", target_value=4.0, is_active=False)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {})
        assert len(result["goals"]) == 1
        assert result["goals"][0]["name"] == "Aktif Hedef"

    def test_multiple_goals_all_returned(self, db_session: Session):
        db = db_session
        tenant = _make_tenant(db)
        _make_goal(db, tenant, name="Hedef A", metric="spend", target_value=10000.0)
        _make_goal(db, tenant, name="Hedef B", metric="conversions", target_value=500.0)
        _make_goal(db, tenant, name="Hedef C", metric="roas", target_value=3.0)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_goal_progress", db, tenant.id, {})
        assert len(result["goals"]) == 3
        names = {g["name"] for g in result["goals"]}
        assert names == {"Hedef A", "Hedef B", "Hedef C"}

    def test_tenant_isolation(self, db_session: Session):
        db = db_session
        tenant_a = _make_tenant(db, "GA")
        tenant_b = _make_tenant(db, "GB")
        _make_goal(db, tenant_a, name="Sadece A'nın Hedefi")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result_b = dispatch("get_goal_progress", db, tenant_b.id, {})
        assert result_b["goals"] == []
        assert "note" in result_b

        result_a = dispatch("get_goal_progress", db, tenant_a.id, {})
        assert len(result_a["goals"]) == 1
        assert result_a["goals"][0]["name"] == "Sadece A'nın Hedefi"

    def test_goal_id_from_other_tenant_returns_error(self, db_session: Session):
        """A tenant cannot access another tenant's goal by ID."""
        db = db_session
        tenant_a = _make_tenant(db, "TA")
        tenant_b = _make_tenant(db, "TB")
        goal_a = _make_goal(db, tenant_a, name="A'nın Özel Hedefi")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        # Tenant B attempts to fetch Tenant A's goal by ID
        result = dispatch(
            "get_goal_progress", db, tenant_b.id, {"goal_id": str(goal_a.id)}
        )
        assert "error" in result
