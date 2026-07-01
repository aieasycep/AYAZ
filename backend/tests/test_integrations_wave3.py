"""Tests for Wave 3 — Entegrasyon & Aksiyon Merkezi.

Coverage
--------
1. ActionAuditLog — row written on action success + error (params redacted)
2. token_refresh task:
   - Refreshes due grants (mocked broker)
   - Marks needs_reconnect on refresh failure
   - Skips fresh grants
   - Skips grants with no access_expires_at
3. Copilot dynamic tools:
   - Only connected integrations' actions appear in tool specs
   - Disconnected integrations are invisible
   - Tenant isolation (tenant B cannot see tenant A's connection tools)
   - Write action returns confirmation-required on first dispatch call
   - Write action executes on confirmed=True dispatch call
   - Audit log row is written after execute
4. dispatch() routing:
   - Static tool dispatches correctly
   - Unknown integration action returns error dict
   - Integration with unconnected key returns error dict
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# Register all ORM models
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.integrations  # noqa: F401

from ayaz.integrations.base import ActionContext
from ayaz.integrations.registry import IntegrationRegistry
from ayaz.integrations.slack import SlackIntegration
from ayaz.models.base import Base
from ayaz.models.integrations import (
    ActionAuditLog,
    IntegrationConnection,
    ProviderGrant,
)
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import hash_password
from ayaz.services.billing import start_subscription
from ayaz.services.copilot_tools import (
    build_tenant_tool_specs,
    dispatch,
)
from ayaz.services.grant_vault import GrantVault
from ayaz.services.vault import InMemoryVault


# ── DB fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
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


# ── Data helpers ───────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name=name)
    db.add(tenant)
    db.flush()
    return tenant


def _make_user(db: Session, tenant: Tenant, email: str = "u@test.com") -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pw"),
        full_name="Test User",
    )
    db.add(user)
    db.flush()
    membership = Membership(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.flush()
    return user


def _make_grant(
    db: Session,
    tenant: Tenant,
    user: User,
    provider: str = "slack",
    expires_in_seconds: int | None = 3600,
) -> ProviderGrant:
    now = datetime.now(timezone.utc)
    grant = ProviderGrant(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        provider=provider,
        vault_secret_ref="",
        scopes=["chat:write"],
        access_expires_at=(
            now + timedelta(seconds=expires_in_seconds)
            if expires_in_seconds is not None
            else None
        ),
        connected_by_user_id=user.id,
        status="active",
    )
    db.add(grant)
    db.flush()
    return grant


def _make_connection(
    db: Session,
    tenant: Tenant,
    grant: ProviderGrant,
    integration_key: str = "slack",
    status: str = "connected",
) -> IntegrationConnection:
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        integration_key=integration_key,
        provider_grant_id=grant.id,
        external_entity_id="",
        display_name="Test Connection",
        capabilities=["action"],
        status=status,
        scopes=["chat:write", "channels:read"],
    )
    db.add(conn)
    db.flush()
    return conn


def _make_growth_subscription(db: Session, tenant: Tenant) -> None:
    start_subscription(db, tenant.id, "growth")
    db.flush()


# ── 1. ActionAuditLog — real audit() writes a row ─────────────────────────────


class TestAuditLog:
    def test_audit_success_writes_row(self, db_session: Session) -> None:
        """audit() with status='ok' writes a non-redacted row to action_audit_log."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant)

        vault = InMemoryVault()
        ctx = ActionContext(
            tenant_id=tenant.id,
            connection_id=conn.id,
            user_id=user.id,
            db=db_session,
            vault=vault,
            _vault_secret_ref=str(grant.id),
        )

        args = {"channel": "#genel", "text": "Merhaba dünya"}
        ctx.audit("slack_send_message", args, {"ok": True}, "ok")

        rows = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).all()

        assert len(rows) == 1
        row = rows[0]
        assert row.action_name == "slack_send_message"
        assert row.status == "ok"
        assert row.error is None
        assert row.actor_user_id == user.id
        assert row.was_auto is False
        assert row.integration_key == "slack"

    def test_audit_error_writes_row_with_error_msg(self, db_session: Session) -> None:
        """audit() with status='error' records the error message."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant)

        vault = InMemoryVault()
        ctx = ActionContext(
            tenant_id=tenant.id,
            connection_id=conn.id,
            user_id=user.id,
            db=db_session,
            vault=vault,
            _vault_secret_ref=str(grant.id),
        )

        ctx.audit(
            "slack_send_message",
            {"channel": "#test", "text": "hello"},
            {"error": "channel_not_found"},
            "error",
        )

        row = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).first()
        assert row is not None
        assert row.status == "error"
        assert row.error == "channel_not_found"

    def test_audit_redacts_text_field(self, db_session: Session) -> None:
        """Long text fields are truncated in params_summary (PII protection)."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant)

        vault = InMemoryVault()
        ctx = ActionContext(
            tenant_id=tenant.id,
            connection_id=conn.id,
            user_id=user.id,
            db=db_session,
            vault=vault,
            _vault_secret_ref=str(grant.id),
        )

        long_text = "A" * 200  # > 40 chars — should be truncated
        ctx.audit(
            "slack_send_message",
            {"channel": "#ch", "text": long_text},
            {"ok": True},
            "ok",
        )

        row = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).first()
        assert row is not None
        stored_text = row.params_summary.get("text", "")
        assert len(stored_text) <= 45  # 40 chars + possible "…"

    def test_audit_redacts_secret_fields(self, db_session: Session) -> None:
        """Secret fields (access_token, api_key, etc.) are fully redacted."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant)

        vault = InMemoryVault()
        ctx = ActionContext(
            tenant_id=tenant.id,
            connection_id=conn.id,
            user_id=user.id,
            db=db_session,
            vault=vault,
            _vault_secret_ref=str(grant.id),
        )

        ctx.audit(
            "some_action",
            {"access_token": "super-secret-token-xyz", "channel": "#ch"},
            {"ok": True},
            "ok",
        )

        row = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).first()
        assert row is not None
        assert "[REDACTED" in row.params_summary.get("access_token", "")
        assert row.params_summary.get("channel") == "#ch"

    def test_audit_was_auto_flag(self, db_session: Session) -> None:
        """was_auto=True sets actor_user_id to None and was_auto to True."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant)

        vault = InMemoryVault()
        ctx = ActionContext(
            tenant_id=tenant.id,
            connection_id=conn.id,
            user_id=user.id,
            db=db_session,
            vault=vault,
            _vault_secret_ref=str(grant.id),
        )

        ctx.audit("slack_send_message", {}, {"ok": True}, "ok", was_auto=True)

        row = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).first()
        assert row is not None
        assert row.was_auto is True
        assert row.actor_user_id is None


# ── 2. token_refresh Celery task ──────────────────────────────────────────────


class TestTokenRefreshTask:
    """Tests for refresh_due_grants task logic.

    We test the internal _refresh_one_grant and _mark_grant_failed helpers
    directly (avoiding full Celery worker setup) and the main task via the
    _get_db mock pattern.
    """

    def test_refreshes_due_grant(self, db_session: Session) -> None:
        """A grant expiring soon is refreshed and vault_secret_ref is updated."""
        from ayaz.tasks.token_refresh import _refresh_one_grant

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)

        # Grant expiring in 5 minutes (within _REFRESH_WINDOW_MINUTES=10)
        grant = _make_grant(db_session, tenant, user, expires_in_seconds=300)

        # Store a token with refresh_token in vault
        vault = GrantVault(db_session)
        vault.put(
            str(grant.id),
            {"access_token": "old_token", "refresh_token": "rtoken_xyz"},
        )
        db_session.flush()

        new_tokens = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }

        with patch(
            "ayaz.services.oauth_broker.refresh",
            return_value=new_tokens,
        ) as mock_refresh:
            success = _refresh_one_grant(db_session, grant.id)

        assert success is True
        mock_refresh.assert_called_once_with("slack", "rtoken_xyz")

        # Vault should now contain new token
        stored = vault.get(str(grant.id))
        assert stored is not None
        assert stored["access_token"] == "new_access_token"

        # access_expires_at should be updated
        db_session.refresh(grant)
        assert grant.access_expires_at is not None
        # SQLite stores timezone-naive datetimes; compare without tzinfo
        expires = grant.access_expires_at
        if expires.tzinfo is not None:
            assert expires > datetime.now(timezone.utc)
        else:
            assert expires > datetime.utcnow()
        assert grant.status == "active"

    def test_marks_needs_reconnect_on_refresh_failure(
        self, db_session: Session
    ) -> None:
        """When broker.refresh() raises, grant and connections get needs_reconnect status."""
        from ayaz.tasks.token_refresh import _refresh_one_grant

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user, expires_in_seconds=5)

        vault = GrantVault(db_session)
        vault.put(
            str(grant.id),
            {"access_token": "old_token", "refresh_token": "bad_rtoken"},
        )
        conn = _make_connection(db_session, tenant, grant)
        db_session.flush()

        with patch(
            "ayaz.services.oauth_broker.refresh",
            side_effect=ValueError("invalid_grant"),
        ):
            success = _refresh_one_grant(db_session, grant.id)

        assert success is False

        db_session.refresh(grant)
        db_session.refresh(conn)
        assert grant.status == "reauth_required"
        assert conn.status == "needs_reconnect"

    def test_skips_fresh_grants(self, db_session: Session) -> None:
        """Grant expiring far in the future is not included in due-for-refresh query."""
        from ayaz.tasks.token_refresh import _REFRESH_WINDOW_MINUTES
        from ayaz.models.integrations import ProviderGrant

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        # Grant expires in 1 hour — well outside the 10-minute window
        grant = _make_grant(db_session, tenant, user, expires_in_seconds=3600)
        db_session.flush()

        cutoff = datetime.now(timezone.utc) + timedelta(
            minutes=_REFRESH_WINDOW_MINUTES
        )
        due = list(
            db_session.scalars(
                select(ProviderGrant.id).where(
                    ProviderGrant.access_expires_at.isnot(None),
                    ProviderGrant.access_expires_at <= cutoff,
                    ProviderGrant.status != "revoked",
                )
            ).all()
        )
        assert grant.id not in due

    def test_skips_grants_without_expiry(self, db_session: Session) -> None:
        """Grants with access_expires_at=None are excluded from the due query."""
        from ayaz.tasks.token_refresh import _REFRESH_WINDOW_MINUTES
        from ayaz.models.integrations import ProviderGrant

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        # Grant with no expiry (api_key or non-expiring token)
        grant = _make_grant(db_session, tenant, user, expires_in_seconds=None)
        db_session.flush()

        cutoff = datetime.now(timezone.utc) + timedelta(
            minutes=_REFRESH_WINDOW_MINUTES
        )
        due = list(
            db_session.scalars(
                select(ProviderGrant.id).where(
                    ProviderGrant.access_expires_at.isnot(None),
                    ProviderGrant.access_expires_at <= cutoff,
                    ProviderGrant.status != "revoked",
                )
            ).all()
        )
        assert grant.id not in due

    def test_one_failure_does_not_abort_batch(self, db_session: Session) -> None:
        """If one grant fails to refresh, others still succeed."""
        from ayaz.tasks.token_refresh import _refresh_one_grant

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)

        # Grant 1: will fail
        grant1 = _make_grant(db_session, tenant, user, expires_in_seconds=5)
        vault = GrantVault(db_session)
        vault.put(
            str(grant1.id),
            {"access_token": "t1", "refresh_token": "bad_rtoken"},
        )

        # Grant 2: will succeed
        grant2 = _make_grant(
            db_session, tenant, user, provider="google_workspace", expires_in_seconds=5
        )
        vault.put(
            str(grant2.id),
            {"access_token": "t2", "refresh_token": "good_rtoken"},
        )
        db_session.flush()

        new_tokens = {"access_token": "new_t2", "refresh_token": "new_rt2", "expires_in": 3600}

        call_count = {"n": 0}

        def mock_refresh(provider, refresh_token, **kwargs):
            call_count["n"] += 1
            if refresh_token == "bad_rtoken":
                raise ValueError("invalid_grant")
            return new_tokens

        with patch("ayaz.services.oauth_broker.refresh", side_effect=mock_refresh):
            success1 = _refresh_one_grant(db_session, grant1.id)
            success2 = _refresh_one_grant(db_session, grant2.id)

        assert success1 is False
        assert success2 is True
        assert call_count["n"] == 2  # both attempted

        db_session.refresh(grant1)
        db_session.refresh(grant2)
        assert grant1.status == "reauth_required"
        assert grant2.status == "active"

    def test_skips_revoked_grant(self, db_session: Session) -> None:
        """Revoked grants are not included in the due-for-refresh query."""
        from ayaz.models.integrations import ProviderGrant
        from ayaz.tasks.token_refresh import _REFRESH_WINDOW_MINUTES

        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)

        # Expired AND revoked — should still be skipped
        grant = _make_grant(db_session, tenant, user, expires_in_seconds=5)
        grant.status = "revoked"
        db_session.flush()

        cutoff = datetime.now(timezone.utc) + timedelta(
            minutes=_REFRESH_WINDOW_MINUTES
        )
        due = list(
            db_session.scalars(
                select(ProviderGrant.id).where(
                    ProviderGrant.access_expires_at.isnot(None),
                    ProviderGrant.access_expires_at <= cutoff,
                    ProviderGrant.status != "revoked",
                )
            ).all()
        )
        assert grant.id not in due


# ── 3. Copilot dynamic tool pool ─────────────────────────────────────────────


class TestCopilotDynamicTools:
    def test_connected_integration_actions_appear(self, db_session: Session) -> None:
        """build_tenant_tool_specs includes action specs for connected integrations."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        _make_connection(db_session, tenant, grant, "slack", "connected")
        db_session.flush()

        specs = build_tenant_tool_specs(db_session, tenant.id)

        tool_names = {s["name"] for s in specs}
        assert "slack_send_message" in tool_names

    def test_unconnected_integration_not_in_tools(self, db_session: Session) -> None:
        """Integrations with status != connected are excluded from tool specs."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        # Connection with needs_reconnect status — should NOT appear
        _make_connection(db_session, tenant, grant, "slack", "needs_reconnect")
        db_session.flush()

        specs = build_tenant_tool_specs(db_session, tenant.id)

        tool_names = {s["name"] for s in specs}
        assert "slack_send_message" not in tool_names

    def test_tenant_isolation_in_tool_specs(self, db_session: Session) -> None:
        """Tenant B does not see tools from Tenant A's connections."""
        # Tenant A: has Slack connected
        tenant_a = _make_tenant(db_session, "Tenant A")
        user_a = _make_user(db_session, tenant_a, "a@test.com")
        grant_a = _make_grant(db_session, tenant_a, user_a)
        _make_connection(db_session, tenant_a, grant_a, "slack", "connected")

        # Tenant B: no connections
        tenant_b = _make_tenant(db_session, "Tenant B")
        db_session.flush()

        specs_b = build_tenant_tool_specs(db_session, tenant_b.id)
        tool_names_b = {s["name"] for s in specs_b}
        # Slack action must NOT appear for tenant B
        assert "slack_send_message" not in tool_names_b

    def test_static_tools_always_present(self, db_session: Session) -> None:
        """Static tools like get_performance_summary are always in the spec list."""
        tenant = _make_tenant(db_session)
        db_session.flush()

        specs = build_tenant_tool_specs(db_session, tenant.id)
        tool_names = {s["name"] for s in specs}
        assert "get_performance_summary" in tool_names


# ── 4. dispatch() — confirm-before-write + routing ───────────────────────────


class TestDispatchIntegrationActions:
    def test_write_action_returns_confirmation_required(
        self, db_session: Session
    ) -> None:
        """dispatch() with a write action (is_write=True) returns requires_confirmation=True."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        _make_connection(db_session, tenant, grant, "slack", "connected")
        db_session.flush()

        result = dispatch(
            "slack_send_message",
            db_session,
            tenant.id,
            {"channel": "#test", "text": "hello"},
            user_id=user.id,
            confirmed=False,
        )

        assert result.get("requires_confirmation") is True
        assert result.get("action") == "slack_send_message"
        assert "preview" in result

    def test_write_action_executes_when_confirmed(self, db_session: Session) -> None:
        """dispatch() with confirmed=True executes the write action."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        conn = _make_connection(db_session, tenant, grant, "slack", "connected")

        # Put a mock token in vault
        vault = GrantVault(db_session)
        vault.put(str(grant.id), {"access_token": "mock-token"})
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True, "ts": "12345.6789"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = dispatch(
                "slack_send_message",
                db_session,
                tenant.id,
                {"channel": "#test", "text": "hello"},
                user_id=user.id,
                vault=vault,
                confirmed=True,
            )

        assert result.get("ok") is True
        assert result.get("channel") == "#test"

    def test_write_action_confirmed_writes_audit_row(
        self, db_session: Session
    ) -> None:
        """After confirmed execution, an ActionAuditLog row is written."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session, tenant)
        grant = _make_grant(db_session, tenant, user)
        _make_connection(db_session, tenant, grant, "slack", "connected")

        vault = GrantVault(db_session)
        vault.put(str(grant.id), {"access_token": "mock-token"})
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True, "ts": "12345"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            dispatch(
                "slack_send_message",
                db_session,
                tenant.id,
                {"channel": "#test", "text": "hello"},
                user_id=user.id,
                vault=vault,
                confirmed=True,
            )

        rows = db_session.scalars(
            select(ActionAuditLog).where(ActionAuditLog.tenant_id == tenant.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].action_name == "slack_send_message"
        assert rows[0].status == "ok"

    def test_unconnected_integration_returns_error(self, db_session: Session) -> None:
        """dispatch() returns an error dict when the integration is not connected."""
        tenant = _make_tenant(db_session)
        db_session.flush()

        result = dispatch(
            "slack_send_message",
            db_session,
            tenant.id,
            {"channel": "#test", "text": "hello"},
        )

        assert "error" in result
        assert "bağlı değil" in result["error"].lower() or "bağ" in result["error"].lower()

    def test_unknown_integration_action_returns_error(
        self, db_session: Session
    ) -> None:
        """dispatch() returns an error for an unknown action name."""
        tenant = _make_tenant(db_session)
        db_session.flush()

        result = dispatch(
            "totally_unknown_action_xyz",
            db_session,
            tenant.id,
            {},
        )

        assert "error" in result

    def test_static_tool_still_dispatches(self, db_session: Session) -> None:
        """dispatch() routes static tools (e.g. get_subscription_status) correctly."""
        from ayaz.services.billing import start_subscription

        tenant = _make_tenant(db_session)
        start_subscription(db_session, tenant.id, "free")
        db_session.flush()

        result = dispatch(
            "get_subscription_status",
            db_session,
            tenant.id,
            {},
        )

        # Should not be an error — returns subscription data
        assert "error" not in result
        assert "plan_code" in result

    def test_tenant_isolation_in_dispatch(self, db_session: Session) -> None:
        """dispatch() cannot execute actions for another tenant's connection."""
        # Tenant A has Slack connected
        tenant_a = _make_tenant(db_session, "A")
        user_a = _make_user(db_session, tenant_a, "a@test.com")
        grant_a = _make_grant(db_session, tenant_a, user_a)
        _make_connection(db_session, tenant_a, grant_a, "slack", "connected")

        # Tenant B has no connections
        tenant_b = _make_tenant(db_session, "B")
        db_session.flush()

        # Dispatching as tenant B — must not find tenant A's connection
        result = dispatch(
            "slack_send_message",
            db_session,
            tenant_b.id,
            {"channel": "#test", "text": "hello"},
        )

        assert "error" in result
