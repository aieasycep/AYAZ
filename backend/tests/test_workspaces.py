"""Tests for M8 Agency / Multi-Workspace + White-label module.

Coverage
--------
* create_workspace: creates Tenant + owner Membership.
* list_workspaces: returns all workspaces for the user.
* switch_workspace: issues a valid JWT for the target tenant; rejects non-members.
* branding: update_branding persists fields; GET /workspaces/current returns them.
* invite → accept: creates a pending invitation; accept creates Membership.
* role guards: non-admin blocked from invite/remove/change-role.
* last-owner guard: cannot remove or demote last owner.
* tenant isolation: listing members only returns members of the active tenant.
* API layer: all HTTP endpoints exercise the full request/response cycle.

Strategy
--------
* FastAPI TestClient backed by an in-memory SQLite DB (StaticPool).
* The workspace router is mounted on a minimal FastAPI app for isolation.
* For tenant-scoped endpoints, ``get_current_membership`` is overridden to return
  a fixed Membership as in other test modules.
* For user-only endpoints (list workspaces, create workspace, switch, accept),
  real JWTs are issued via ``create_access_token`` so the Bearer-token flow is
  exercised end-to-end.
* No live network calls; email notification is stubbed (print only).
"""

from __future__ import annotations

import uuid
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
    WorkspaceInvitation,
)
from ayaz.api.deps import get_current_membership, get_current_user
from ayaz.api.v1 import workspaces as workspaces_module
from ayaz.services.auth import create_access_token, hash_password
from ayaz.services.workspaces import (
    accept_invitation,
    change_role,
    create_workspace,
    invite_member,
    list_members,
    list_workspaces,
    remove_member,
    switch_workspace,
    update_branding,
)


# ── Minimal test app ──────────────────────────────────────────────────────────

_app = FastAPI(title="AYAZ Workspaces Test App")
_app.include_router(workspaces_module.router, prefix="/api/v1")


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
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


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_user(db: Session, email: str = "owner@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("password123"),
        full_name="Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_tenant(db: Session, name: str = "Test Workspace") -> Tenant:
    t = Tenant(id=uuid.uuid4(), name=name, country="TR", base_currency="TRY")
    db.add(t)
    db.flush()
    return t


def _make_membership(
    db: Session,
    user: User,
    tenant: Tenant,
    role: MembershipRole = MembershipRole.owner,
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


def _auth_header(user: User, tenant: Tenant) -> dict[str, str]:
    token = create_access_token(str(user.id), str(tenant.id))
    return {"Authorization": f"Bearer {token}"}


def _client_with_membership(db: Session, membership: Membership) -> TestClient:
    """Return a TestClient with DB + membership overrides."""

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_membership():
        return membership

    _app.dependency_overrides[get_db] = override_db
    _app.dependency_overrides[get_current_membership] = override_membership
    return TestClient(_app, raise_server_exceptions=True)


def _client_with_user(db: Session, user: User) -> TestClient:
    """Return a TestClient with DB override only (real JWT auth)."""

    def override_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = override_db
    _app.dependency_overrides.pop(get_current_membership, None)
    return TestClient(_app, raise_server_exceptions=True)


# ── Service-layer tests ───────────────────────────────────────────────────────


class TestCreateWorkspace:
    def test_creates_tenant_and_owner_membership(self, db_session: Session) -> None:
        user = _make_user(db_session)
        db_session.commit()

        tenant = create_workspace(db_session, user.id, "Agency HQ")

        assert tenant.id is not None
        assert tenant.name == "Agency HQ"

        # Membership must exist with owner role
        m = db_session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(Membership).where(
                Membership.user_id == user.id,
                Membership.tenant_id == tenant.id,
            )
        ).first()
        assert m is not None
        assert m.role == MembershipRole.owner

    def test_brand_fields_default_to_none(self, db_session: Session) -> None:
        user = _make_user(db_session)
        db_session.commit()
        tenant = create_workspace(db_session, user.id, "No Brand")
        assert tenant.brand_name is None
        assert tenant.logo_url is None
        assert tenant.primary_color is None


class TestListWorkspaces:
    def test_returns_all_workspaces(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t1 = _make_tenant(db_session, "Alpha")
        t2 = _make_tenant(db_session, "Beta")
        _make_membership(db_session, user, t1, MembershipRole.owner)
        _make_membership(db_session, user, t2, MembershipRole.member)
        db_session.commit()

        workspaces = list_workspaces(db_session, user.id)
        names = {w["name"] for w in workspaces}
        assert "Alpha" in names
        assert "Beta" in names

    def test_includes_role(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session)
        _make_membership(db_session, user, t, MembershipRole.admin)
        db_session.commit()

        workspaces = list_workspaces(db_session, user.id)
        assert workspaces[0]["role"] == "admin"

    def test_empty_for_new_user(self, db_session: Session) -> None:
        user = _make_user(db_session)
        db_session.commit()
        assert list_workspaces(db_session, user.id) == []


class TestSwitchWorkspace:
    def test_returns_valid_jwt(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session)
        _make_membership(db_session, user, t)
        db_session.commit()

        token = switch_workspace(db_session, user.id, t.id)
        assert isinstance(token, str)
        assert len(token) > 20

        # Decode and verify claims
        from ayaz.services.auth import decode_access_token
        payload = decode_access_token(token)
        assert payload["sub"] == str(user.id)
        assert payload["tid"] == str(t.id)

    def test_rejects_non_member(self, db_session: Session) -> None:
        user = _make_user(db_session)
        other_tenant = _make_tenant(db_session, "Other")
        db_session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            switch_workspace(db_session, user.id, other_tenant.id)
        assert exc_info.value.status_code == 403


class TestUpdateBranding:
    def test_persists_brand_fields(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        db_session.commit()

        updated = update_branding(
            db_session,
            t.id,
            brand_name="ACME Marketing",
            logo_url="https://cdn.acme.com/logo.png",
            primary_color="#FF5733",
        )
        assert updated.brand_name == "ACME Marketing"
        assert updated.logo_url == "https://cdn.acme.com/logo.png"
        assert updated.primary_color == "#FF5733"

    def test_partial_update_leaves_other_fields(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        db_session.commit()
        update_branding(db_session, t.id, brand_name="First Brand")
        updated = update_branding(db_session, t.id, primary_color="#000")
        assert updated.brand_name == "First Brand"
        assert updated.primary_color == "#000"

    def test_clearing_with_empty_string(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        db_session.commit()
        update_branding(db_session, t.id, brand_name="Brand")
        updated = update_branding(db_session, t.id, brand_name="")
        assert updated.brand_name is None


class TestInviteAndAccept:
    def test_invite_creates_pending_invitation(self, db_session: Session) -> None:
        inviter = _make_user(db_session, "owner@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, inviter, t)
        db_session.commit()

        inv = invite_member(db_session, t.id, "newbie@acme.com", "member", inviter.id)
        assert inv.status == "pending"
        assert inv.email == "newbie@acme.com"
        assert inv.role == "member"
        assert len(inv.token) >= 10

    def test_accept_creates_membership(self, db_session: Session) -> None:
        inviter = _make_user(db_session, "owner@acme.com")
        invitee = _make_user(db_session, "invitee@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, inviter, t)
        db_session.commit()

        inv = invite_member(db_session, t.id, invitee.email, "admin", inviter.id)
        new_m = accept_invitation(db_session, inv.token, invitee.id)

        assert new_m.tenant_id == t.id
        assert new_m.user_id == invitee.id
        assert new_m.role == MembershipRole.admin

        # Invitation status should now be accepted
        db_session.refresh(inv)
        assert inv.status == "accepted"
        assert inv.accepted_at is not None

    def test_accept_invalid_token_raises_404(self, db_session: Session) -> None:
        user = _make_user(db_session)
        db_session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            accept_invitation(db_session, "totally-fake-token", user.id)
        assert exc_info.value.status_code == 404

    def test_reinvite_revokes_old_token(self, db_session: Session) -> None:
        inviter = _make_user(db_session, "owner@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, inviter, t)
        db_session.commit()

        inv1 = invite_member(db_session, t.id, "bob@acme.com", "member", inviter.id)
        token1 = inv1.token
        inv2 = invite_member(db_session, t.id, "bob@acme.com", "admin", inviter.id)

        db_session.refresh(inv1)
        assert inv1.status == "revoked"
        assert inv2.status == "pending"
        assert inv2.token != token1

    def test_invite_already_member_raises_409(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, owner, t)
        db_session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            invite_member(db_session, t.id, owner.email, "member", owner.id)
        assert exc_info.value.status_code == 409


class TestRemoveMember:
    def test_removes_non_owner(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, owner, t, MembershipRole.owner)
        m = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        remove_member(db_session, t.id, m.id)
        members = list_members(db_session, t.id)
        assert not any(x["user_id"] == member_user.id for x in members)

    def test_last_owner_cannot_be_removed(self, db_session: Session) -> None:
        owner = _make_user(db_session)
        t = _make_tenant(db_session)
        m = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            remove_member(db_session, t.id, m.id)
        assert exc_info.value.status_code == 422


class TestChangeRole:
    def test_changes_member_to_admin(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, owner, t, MembershipRole.owner)
        m = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        updated = change_role(db_session, t.id, m.id, "admin")
        assert updated.role == MembershipRole.admin

    def test_last_owner_cannot_be_demoted(self, db_session: Session) -> None:
        owner = _make_user(db_session)
        t = _make_tenant(db_session)
        m = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            change_role(db_session, t.id, m.id, "member")
        assert exc_info.value.status_code == 422

    def test_promotes_member_to_owner(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        _make_membership(db_session, owner, t, MembershipRole.owner)
        m = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        updated = change_role(db_session, t.id, m.id, "owner")
        assert updated.role == MembershipRole.owner

        # Now owner can also be demoted (two owners exist)
        owner_m = db_session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(Membership).where(
                Membership.user_id == owner.id,
                Membership.tenant_id == t.id,
            )
        ).first()
        demoted = change_role(db_session, t.id, owner_m.id, "admin")
        assert demoted.role == MembershipRole.admin


class TestTenantIsolation:
    def test_list_members_scoped_to_tenant(self, db_session: Session) -> None:
        user_a = _make_user(db_session, "a@acme.com")
        user_b = _make_user(db_session, "b@acme.com")
        t1 = _make_tenant(db_session, "Tenant A")
        t2 = _make_tenant(db_session, "Tenant B")
        _make_membership(db_session, user_a, t1, MembershipRole.owner)
        _make_membership(db_session, user_b, t2, MembershipRole.owner)
        db_session.commit()

        members_t1 = list_members(db_session, t1.id)
        assert len(members_t1) == 1
        assert members_t1[0]["email"] == "a@acme.com"

        members_t2 = list_members(db_session, t2.id)
        assert len(members_t2) == 1
        assert members_t2[0]["email"] == "b@acme.com"


# ── API-layer tests ───────────────────────────────────────────────────────────


class TestGetWorkspacesEndpoint:
    def test_returns_200_with_workspaces(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session, "My Workspace")
        m = _make_membership(db_session, user, t)
        db_session.commit()

        client = _client_with_user(db_session, user)
        headers = _auth_header(user, t)
        resp = client.get("/api/v1/workspaces", headers=headers)
        _app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["name"] == "My Workspace"
        assert body[0]["role"] == "owner"

    def test_returns_401_without_token(self, db_session: Session) -> None:
        def override_db():
            yield db_session
        _app.dependency_overrides[get_db] = override_db
        client = TestClient(_app, raise_server_exceptions=True)
        resp = client.get("/api/v1/workspaces")
        _app.dependency_overrides.clear()
        assert resp.status_code == 401


class TestCreateWorkspaceEndpoint:
    def test_creates_workspace_returns_201(self, db_session: Session) -> None:
        user = _make_user(db_session)
        # Need an existing tenant for the initial JWT
        t = _make_tenant(db_session, "Initial")
        _make_membership(db_session, user, t)
        db_session.commit()

        client = _client_with_user(db_session, user)
        headers = _auth_header(user, t)
        resp = client.post(
            "/api/v1/workspaces",
            json={"name": "New Client"},
            headers=headers,
        )
        _app.dependency_overrides.clear()

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "New Client"
        assert body["role"] == "owner"

    def test_empty_name_returns_422(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session, "Initial")
        _make_membership(db_session, user, t)
        db_session.commit()

        client = _client_with_user(db_session, user)
        headers = _auth_header(user, t)
        resp = client.post(
            "/api/v1/workspaces",
            json={"name": "   "},
            headers=headers,
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 422


class TestSwitchWorkspaceEndpoint:
    def test_returns_new_token(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t1 = _make_tenant(db_session, "Workspace 1")
        t2 = _make_tenant(db_session, "Workspace 2")
        _make_membership(db_session, user, t1)
        _make_membership(db_session, user, t2)
        db_session.commit()

        client = _client_with_user(db_session, user)
        headers = _auth_header(user, t1)
        resp = client.post(
            "/api/v1/workspaces/switch",
            json={"tenant_id": str(t2.id)},
            headers=headers,
        )
        _app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["tenant_id"] == str(t2.id)

        # Verify the returned JWT is valid and scoped to t2
        from ayaz.services.auth import decode_access_token
        payload = decode_access_token(body["access_token"])
        assert payload["tid"] == str(t2.id)

    def test_switch_to_non_member_returns_403(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t1 = _make_tenant(db_session, "Mine")
        other = _make_tenant(db_session, "Not Mine")
        _make_membership(db_session, user, t1)
        db_session.commit()

        client = _client_with_user(db_session, user)
        headers = _auth_header(user, t1)
        resp = client.post(
            "/api/v1/workspaces/switch",
            json={"tenant_id": str(other.id)},
            headers=headers,
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestBrandingEndpoints:
    def test_get_current_returns_branding(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session, "ACME")
        t.brand_name = "ACME Corp"
        t.primary_color = "#123456"
        m = _make_membership(db_session, user, t)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.get("/api/v1/workspaces/current")
        _app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["brand_name"] == "ACME Corp"
        assert body["primary_color"] == "#123456"

    def test_patch_branding_persists(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session, "ACME")
        m = _make_membership(db_session, user, t, MembershipRole.admin)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.patch(
            "/api/v1/workspaces/current",
            json={"brand_name": "New Brand", "primary_color": "#AABBCC"},
        )
        _app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["brand_name"] == "New Brand"
        assert body["primary_color"] == "#AABBCC"

    def test_patch_branding_blocked_for_member(self, db_session: Session) -> None:
        user = _make_user(db_session)
        t = _make_tenant(db_session, "ACME")
        m = _make_membership(db_session, user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.patch(
            "/api/v1/workspaces/current",
            json={"brand_name": "Should Fail"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestMembersEndpoint:
    def test_list_members_returns_all(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m_owner)
        resp = client.get("/api/v1/workspaces/members")
        _app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        emails = {m["email"] for m in body}
        assert "owner@acme.com" in emails
        assert "member@acme.com" in emails


class TestInvitationsEndpoint:
    def test_invite_returns_201(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        t = _make_tenant(db_session)
        m = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.post(
            "/api/v1/workspaces/invitations",
            json={"email": "newmember@acme.com", "role": "member"},
        )
        _app.dependency_overrides.clear()

        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert "token" in body

    def test_invite_blocked_for_regular_member(self, db_session: Session) -> None:
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.post(
            "/api/v1/workspaces/invitations",
            json={"email": "outsider@acme.com", "role": "member"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_invite_and_accept_flow(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        invitee = _make_user(db_session, "newbie@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        # Admin invites via API
        client = _client_with_membership(db_session, m_owner)
        resp = client.post(
            "/api/v1/workspaces/invitations",
            json={"email": invitee.email, "role": "admin"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 201
        token = resp.json()["token"]

        # Invitee accepts via API
        invitee_client = _client_with_user(db_session, invitee)
        headers = _auth_header(invitee, t)
        accept_resp = invitee_client.post(
            "/api/v1/workspaces/invitations/accept",
            json={"token": token},
            headers=headers,
        )
        _app.dependency_overrides.clear()
        assert accept_resp.status_code == 200
        body = accept_resp.json()
        assert body["role"] == "admin"
        assert body["tenant_id"] == str(t.id)


class TestRemoveMemberEndpoint:
    def test_removes_member(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        m_member = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m_owner)
        resp = client.delete(f"/api/v1/workspaces/members/{m_member.id}")
        _app.dependency_overrides.clear()
        assert resp.status_code == 204

    def test_last_owner_cannot_be_removed(self, db_session: Session) -> None:
        owner = _make_user(db_session)
        t = _make_tenant(db_session)
        m = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.delete(f"/api/v1/workspaces/members/{m.id}")
        _app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_member_cannot_remove(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        m_member = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m_member)
        resp = client.delete(f"/api/v1/workspaces/members/{m_owner.id}")
        _app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestChangeRoleEndpoint:
    def test_changes_role_returns_updated(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        m_member = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m_owner)
        resp = client.patch(
            f"/api/v1/workspaces/members/{m_member.id}",
            json={"role": "admin"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_last_owner_cannot_be_demoted(self, db_session: Session) -> None:
        owner = _make_user(db_session)
        t = _make_tenant(db_session)
        m = _make_membership(db_session, owner, t, MembershipRole.owner)
        db_session.commit()

        client = _client_with_membership(db_session, m)
        resp = client.patch(
            f"/api/v1/workspaces/members/{m.id}",
            json={"role": "member"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_regular_member_blocked_from_changing_role(self, db_session: Session) -> None:
        owner = _make_user(db_session, "owner@acme.com")
        member_user = _make_user(db_session, "member@acme.com")
        t = _make_tenant(db_session)
        m_owner = _make_membership(db_session, owner, t, MembershipRole.owner)
        m_member = _make_membership(db_session, member_user, t, MembershipRole.member)
        db_session.commit()

        client = _client_with_membership(db_session, m_member)
        resp = client.patch(
            f"/api/v1/workspaces/members/{m_owner.id}",
            json={"role": "member"},
        )
        _app.dependency_overrides.clear()
        assert resp.status_code == 403
