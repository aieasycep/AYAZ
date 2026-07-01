"""Tests for Wave 2 — Entegrasyon & Aksiyon Merkezi.

Coverage
--------
1. OAuth broker:
   - generate_pkce_pair: verifier is URL-safe, challenge is correct S256
   - _sign_state + parse_state: round-trip works
   - Tampered state raises ValueError
   - Expired state raises ValueError

2. Adapter action tests (mocked httpx):
   - SlackIntegration.execute_action — success path
   - SlackIntegration.execute_action — Slack error response
   - GoogleSheetsIntegration.execute_action — success path
   - GmailIntegration.execute_action — success path

3. Router endpoint tests (FastAPI TestClient + SQLite in-memory):
   - GET /api/v1/integrations/catalog — returns registered integrations
   - GET /api/v1/integrations/catalog?category=messaging — filters correctly
   - GET /api/v1/integrations/connections — returns empty for new tenant
   - POST /api/v1/integrations/slack/connect — operator_setup_required (no creds)
   - POST /api/v1/integrations/slack/connect — popup mode (creds patched in)
   - DELETE /api/v1/integrations/slack/connections/{id} — 404 for non-existent
   - Tenant isolation: tenant B cannot see tenant A's connections
   - Billing gate: Slack (min_plan=growth) → 402 on free plan
   - POST /api/v1/integrations/requests — returns 201
"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all ORM models so create_all works
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.integrations  # noqa: F401

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import integrations as integrations_module
from ayaz.config import settings
from ayaz.integrations.base import ActionContext
from ayaz.integrations.gmail import GmailIntegration
from ayaz.integrations.google_sheets import GoogleSheetsIntegration
from ayaz.integrations.slack import SlackIntegration
from ayaz.models.base import Base
from ayaz.models.integrations import IntegrationConnection, ProviderGrant
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import hash_password
from ayaz.services.billing import PLANS, start_subscription
from ayaz.services.oauth_broker import (
    _has_credentials,
    _sign_state,
    generate_pkce_pair,
    parse_state,
)
from ayaz.services.vault import InMemoryVault


# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Integration Test App")
_test_app.include_router(integrations_module.router, prefix="/api/v1")


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
    tenant = Tenant(
        id=uuid.uuid4(),
        name=name,
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(tenant)
    db.flush()
    return tenant


def _make_user(db: Session, email: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"test-{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Test User",
    )
    db.add(user)
    db.flush()
    return user


def _make_membership(
    db: Session, user: User, tenant: Tenant, role: MembershipRole = MembershipRole.owner
) -> Membership:
    m = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=role,
    )
    db.add(m)
    db.flush()
    return m


# ── Client fixture ─────────────────────────────────────────────────────────────


@pytest.fixture()
def api_client(db_session: Session):
    """TestClient with a single tenant, user, and membership."""
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

    client = TestClient(_test_app)
    yield client, tenant, membership, db_session

    _test_app.dependency_overrides.clear()


# ── Utility: mock ActionContext ────────────────────────────────────────────────


def _make_mock_ctx(token: str = "test_access_token") -> ActionContext:
    """Return an ActionContext backed by an InMemoryVault with a preset token."""
    vault = InMemoryVault()
    vault_ref = "test-ref"
    vault.put(vault_ref, {"access_token": token})

    db_mock = MagicMock()
    ctx = ActionContext(
        tenant_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        db=db_mock,
        vault=vault,
        _vault_secret_ref=vault_ref,
    )
    return ctx


# =============================================================================
# 1. OAuth BROKER TESTS
# =============================================================================


class TestGeneratePkcePair:
    def test_verifier_is_url_safe_base64(self):
        verifier, challenge = generate_pkce_pair()
        # URL-safe base64: only A-Z, a-z, 0-9, -, _  (no +, /, = padding)
        import re
        assert re.match(r"^[A-Za-z0-9\-_]+$", verifier), (
            f"verifier contains non-URL-safe chars: {verifier!r}"
        )

    def test_challenge_is_correct_s256(self):
        verifier, challenge = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .decode()
            .rstrip("=")
        )
        assert challenge == expected

    def test_generates_different_pairs(self):
        p1 = generate_pkce_pair()
        p2 = generate_pkce_pair()
        assert p1[0] != p2[0], "Two verifiers should be unique"
        assert p1[1] != p2[1], "Two challenges should be unique"


class TestSignStateAndParseState:
    def test_round_trip(self):
        aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        state = _sign_state(aid, tid)
        parsed_aid, parsed_tid = parse_state(state)
        assert parsed_aid == aid
        assert parsed_tid == tid

    def test_tampered_state_raises(self):
        aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        state = _sign_state(aid, tid)
        # Tamper: replace several chars in the middle of the MAC portion so
        # the decoded bytes are guaranteed to differ (avoid last-char padding
        # bit collision where flipping 'A'↔'B' has no effect on decoded bytes).
        parts = state.rsplit(".", 1)
        mac = parts[1]
        mid = len(mac) // 2
        # Replace 4 chars in the middle with chars that differ from the original
        tampered_segment = "".join(
            "Z" if c != "Z" else "Y" for c in mac[mid : mid + 4]
        )
        tampered_mac = mac[:mid] + tampered_segment + mac[mid + 4 :]
        tampered_state = parts[0] + "." + tampered_mac
        with pytest.raises(ValueError, match="MAC verification failed"):
            parse_state(tampered_state)

    def test_expired_state_raises(self, monkeypatch):
        aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        # Patch time to produce an already-expired token
        fake_past = int(time.time()) - 700  # 700 seconds ago (TTL is 600)
        with patch("ayaz.services.oauth_broker.time") as mock_time:
            mock_time.time.return_value = fake_past
            state = _sign_state(aid, tid)
        # Now parse with real current time — should be expired
        with pytest.raises(ValueError, match="expired"):
            parse_state(state)

    def test_state_without_separator_raises(self):
        with pytest.raises(ValueError, match="separator"):
            parse_state("nodotsinhere")

    def test_state_is_dot_separated(self):
        state = _sign_state("aid", "tid")
        assert "." in state, "State should be dot-separated payload.mac"


class TestHasCredentials:
    def test_google_missing_returns_false(self, monkeypatch):
        monkeypatch.setattr(settings, "google_client_id", "")
        monkeypatch.setattr(settings, "google_client_secret", "")
        assert not _has_credentials("google_workspace")

    def test_slack_missing_returns_false(self, monkeypatch):
        monkeypatch.setattr(settings, "slack_client_id", "")
        monkeypatch.setattr(settings, "slack_client_secret", "")
        assert not _has_credentials("slack")

    def test_slack_present_returns_true(self, monkeypatch):
        monkeypatch.setattr(settings, "slack_client_id", "Tclient123")
        monkeypatch.setattr(settings, "slack_client_secret", "secret456")
        assert _has_credentials("slack")


# =============================================================================
# 2. ADAPTER ACTION TESTS (mocked HTTP)
# =============================================================================


class TestSlackIntegration:
    def test_send_message_success(self):
        ctx = _make_mock_ctx("xoxb-test-token")

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True, "ts": "1234567890.123"}

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = SlackIntegration().execute_action(
                "slack_send_message",
                {"channel": "#test", "text": "Hello!"},
                ctx=ctx,
            )

        assert result["ok"] is True
        assert result["channel"] == "#test"
        assert result["ts"] == "1234567890.123"

    def test_send_message_slack_error(self):
        ctx = _make_mock_ctx("xoxb-test-token")

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "ok": False,
            "error": "channel_not_found",
        }

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = SlackIntegration().execute_action(
                "slack_send_message",
                {"channel": "#nonexistent", "text": "Hi"},
                ctx=ctx,
            )

        assert result["ok"] is False
        assert result["error"] == "channel_not_found"

    def test_unknown_action_raises(self):
        ctx = _make_mock_ctx()
        with pytest.raises(NotImplementedError):
            SlackIntegration().execute_action(
                "slack_unknown", {}, ctx=ctx
            )

    def test_metadata(self):
        meta = SlackIntegration.metadata
        assert meta.key == "slack"
        assert meta.min_plan == "growth"
        assert meta.provider == "slack"


class TestGoogleSheetsIntegration:
    def test_append_row_success(self):
        ctx = _make_mock_ctx("ya29-test-sheets-token")

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "updates": {"updatedRange": "Sheet1!A1:C1"}
        }

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = GoogleSheetsIntegration().execute_action(
                "gsheets_append_row",
                {
                    "spreadsheet_id": "abc123",
                    "sheet_name": "Sheet1",
                    "values": ["val1", "val2", "val3"],
                },
                ctx=ctx,
            )

        assert result["ok"] is True
        assert result["spreadsheet_id"] == "abc123"
        assert result["updated_range"] == "Sheet1!A1:C1"

    def test_metadata(self):
        meta = GoogleSheetsIntegration.metadata
        assert meta.key == "google_sheets"
        assert meta.min_plan == "starter"
        assert meta.provider == "google_workspace"


class TestGmailIntegration:
    def test_send_email_success(self):
        ctx = _make_mock_ctx("ya29-gmail-test-token")

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"id": "msg-xyz-123"}

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = GmailIntegration().execute_action(
                "gmail_send_email",
                {
                    "to": "test@example.com",
                    "subject": "Test Subject",
                    "body": "Hello, this is a test email.",
                },
                ctx=ctx,
            )

        assert result["ok"] is True
        assert result["message_id"] == "msg-xyz-123"

    def test_metadata(self):
        meta = GmailIntegration.metadata
        assert meta.key == "gmail"
        assert meta.min_plan == "starter"
        assert meta.provider == "google_workspace"


# =============================================================================
# 3. ROUTER ENDPOINT TESTS
# =============================================================================


class TestCatalogEndpoint:
    def test_returns_list(self, api_client):
        client, tenant, membership, db = api_client
        resp = client.get("/api/v1/integrations/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_contains_known_integrations(self, api_client):
        client, _, _, _ = api_client
        resp = client.get("/api/v1/integrations/catalog")
        keys = {item["key"] for item in resp.json()}
        # Should include all Wave 2 adapters
        assert "slack" in keys
        assert "google_sheets" in keys
        assert "gmail" in keys
        assert "google_workspace" in keys

    def test_filter_by_category_messaging(self, api_client):
        client, _, _, _ = api_client
        resp = client.get("/api/v1/integrations/catalog?category=messaging")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        for item in data:
            assert item["category"] == "messaging", (
                f"Expected category=messaging, got {item['category']!r} for {item['key']}"
            )

    def test_filter_by_category_ads(self, api_client):
        client, _, _, _ = api_client
        resp = client.get("/api/v1/integrations/catalog?category=ads")
        assert resp.status_code == 200
        data = resp.json()
        keys = {item["key"] for item in data}
        assert "google_ads" in keys

    def test_status_field_present(self, api_client):
        client, _, _, _ = api_client
        resp = client.get("/api/v1/integrations/catalog")
        for item in resp.json():
            assert "status" in item
            assert item["status"] in ("connected", "available", "coming_soon")


class TestConnectionsEndpoint:
    def test_empty_for_new_tenant(self, api_client):
        client, _, _, _ = api_client
        resp = client.get("/api/v1/integrations/connections")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_connection_after_create(self, api_client):
        client, tenant, membership, db = api_client
        # Manually create a connection
        grant = ProviderGrant(
            tenant_id=tenant.id,
            provider="slack",
            status="active",
            scopes=["chat:write"],
            connected_by_user_id=membership.user_id,
        )
        db.add(grant)
        db.flush()
        conn = IntegrationConnection(
            tenant_id=tenant.id,
            integration_key="slack",
            provider_grant_id=grant.id,
            status="connected",
            capabilities=["action"],
            scopes=["chat:write"],
            display_name="Slack",
        )
        db.add(conn)
        db.commit()

        resp = client.get("/api/v1/integrations/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["integration_key"] == "slack"


class TestConnectEndpoint:
    def test_operator_setup_required_when_no_creds(self, api_client, monkeypatch):
        """With no Slack credentials configured, returns operator_setup_required (not 500).

        The tenant must be on growth plan so the billing gate passes and we reach
        the credentials check.
        """
        client, tenant, membership, db = api_client
        # Upgrade to growth so billing gate passes
        start_subscription(db, tenant.id, "growth")
        monkeypatch.setattr(settings, "slack_client_id", "")
        monkeypatch.setattr(settings, "slack_client_secret", "")

        resp = client.post("/api/v1/integrations/slack/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "operator_setup_required"
        assert "message" in data

    def test_popup_mode_when_creds_present(self, api_client, monkeypatch):
        """With credentials configured, returns popup mode + authorize_url.

        Tenant must be on growth plan so billing gate passes.
        """
        client, tenant, membership, db = api_client
        # Upgrade to growth plan so billing gate passes
        start_subscription(db, tenant.id, "growth")
        monkeypatch.setattr(settings, "slack_client_id", "Tclient123")
        monkeypatch.setattr(settings, "slack_client_secret", "secret456")

        resp = client.post("/api/v1/integrations/slack/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "popup"
        assert "authorize_url" in data
        assert "slack.com" in data["authorize_url"]
        assert "grant_id" in data

    def test_unknown_integration_returns_404(self, api_client):
        client, _, _, _ = api_client
        resp = client.post("/api/v1/integrations/totally_fake_key/connect")
        assert resp.status_code == 404

    def test_billing_gate_free_plan_blocks_growth_integration(
        self, api_client, monkeypatch
    ):
        """Slack (min_plan=growth) should return 402 for a free-plan tenant."""
        client, _, _, _ = api_client
        # Free plan is the default when no subscription row exists — no action needed.
        # But ensure credentials look present so we pass that gate first.
        monkeypatch.setattr(settings, "slack_client_id", "Tclient123")
        monkeypatch.setattr(settings, "slack_client_secret", "secret456")

        resp = client.post("/api/v1/integrations/slack/connect")
        assert resp.status_code == 402

    def test_billing_gate_growth_plan_allows_slack(
        self, api_client, monkeypatch
    ):
        """On a growth plan, Slack connect should proceed (not 402)."""
        client, tenant, membership, db = api_client
        monkeypatch.setattr(settings, "slack_client_id", "Tclient123")
        monkeypatch.setattr(settings, "slack_client_secret", "secret456")
        # Upgrade tenant to growth plan
        start_subscription(db, tenant.id, "growth")

        resp = client.post("/api/v1/integrations/slack/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "popup"


class TestDisconnectEndpoint:
    def test_404_for_non_existent_connection(self, api_client):
        client, _, _, _ = api_client
        fake_id = str(uuid.uuid4())
        resp = client.delete(
            f"/api/v1/integrations/slack/connections/{fake_id}"
        )
        assert resp.status_code == 404

    def test_404_for_wrong_key(self, api_client):
        """Connection exists for slack but we request under different key → 404."""
        client, tenant, membership, db = api_client
        grant = ProviderGrant(
            tenant_id=tenant.id,
            provider="slack",
            status="active",
            scopes=["chat:write"],
            connected_by_user_id=membership.user_id,
        )
        db.add(grant)
        db.flush()
        conn = IntegrationConnection(
            tenant_id=tenant.id,
            integration_key="slack",
            provider_grant_id=grant.id,
            status="connected",
            capabilities=["action"],
            scopes=["chat:write"],
            display_name="Slack",
        )
        db.add(conn)
        db.commit()

        resp = client.delete(
            f"/api/v1/integrations/google_ads/connections/{conn.id}"
        )
        assert resp.status_code == 404

    def test_successful_disconnect(self, api_client):
        """Delete an existing connection → 204, connection gone from DB."""
        client, tenant, membership, db = api_client
        grant = ProviderGrant(
            tenant_id=tenant.id,
            provider="slack",
            status="active",
            scopes=["chat:write"],
            connected_by_user_id=membership.user_id,
        )
        db.add(grant)
        db.flush()
        conn = IntegrationConnection(
            tenant_id=tenant.id,
            integration_key="slack",
            provider_grant_id=grant.id,
            status="connected",
            capabilities=["action"],
            scopes=["chat:write"],
            display_name="Slack",
        )
        db.add(conn)
        db.commit()
        conn_id = str(conn.id)

        resp = client.delete(
            f"/api/v1/integrations/slack/connections/{conn_id}"
        )
        assert resp.status_code == 204

        # Verify connection is gone
        resp2 = client.get("/api/v1/integrations/connections")
        keys = [c["integration_key"] for c in resp2.json()]
        assert "slack" not in keys


class TestTenantIsolation:
    def test_tenant_b_cannot_see_tenant_a_connections(self, db_session: Session):
        """Tenant B's membership must not reveal Tenant A's connections."""
        # Create two tenants, users, memberships
        tenant_a = _make_tenant(db_session, "Tenant A")
        user_a = _make_user(db_session, "usera@ayaz.app")
        membership_a = _make_membership(db_session, user_a, tenant_a)

        tenant_b = _make_tenant(db_session, "Tenant B")
        user_b = _make_user(db_session, "userb@ayaz.app")
        membership_b = _make_membership(db_session, user_b, tenant_b)
        db_session.commit()

        # Create a connection for Tenant A
        grant = ProviderGrant(
            tenant_id=tenant_a.id,
            provider="slack",
            status="active",
            scopes=["chat:write"],
            connected_by_user_id=user_a.id,
        )
        db_session.add(grant)
        db_session.flush()
        conn = IntegrationConnection(
            tenant_id=tenant_a.id,
            integration_key="slack",
            provider_grant_id=grant.id,
            status="connected",
            capabilities=["action"],
            scopes=["chat:write"],
            display_name="Slack",
        )
        db_session.add(conn)
        db_session.commit()

        # Build two test apps with different membership overrides
        def override_db():
            try:
                yield db_session
            finally:
                pass

        # App for Tenant B
        app_b = FastAPI()
        app_b.include_router(integrations_module.router, prefix="/api/v1")
        app_b.dependency_overrides[get_db] = override_db
        app_b.dependency_overrides[get_current_membership] = lambda: membership_b

        client_b = TestClient(app_b)
        resp = client_b.get("/api/v1/integrations/connections")
        assert resp.status_code == 200
        # Tenant B should see zero connections (Tenant A's connection is isolated)
        assert resp.json() == []


class TestIntegrationRequestsEndpoint:
    def test_create_request_returns_201(self, api_client):
        client, _, _, _ = api_client
        resp = client.post(
            "/api/v1/integrations/requests",
            json={"integration_key": "trendyol"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["integration_key"] == "trendyol"
        assert "id" in data
        assert "tenant_id" in data

    def test_create_request_missing_key_returns_422(self, api_client):
        client, _, _, _ = api_client
        resp = client.post(
            "/api/v1/integrations/requests",
            json={},
        )
        assert resp.status_code == 422
