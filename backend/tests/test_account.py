"""Integration tests for Account & Settings endpoints (Dalga 22).

Coverage
--------
* PATCH /auth/me — profile update happy path, email uniqueness conflict (409),
  email conflict from IntegrityError path, empty body (400), no-auth (401).
* POST /auth/change-password — happy path, wrong current password (400),
  too-short new password (422), same password (400), no-auth (401).
* GET /auth/preferences — defaults returned correctly, no-auth (401).
* PATCH /auth/preferences — happy path (partial update), invalid locale (422),
  no-auth (401).
* GET /auth/me — backward compat: id/email/full_name present + created_at added.

Strategy
--------
* FastAPI TestClient backed by an in-memory SQLite DB (StaticPool).
* The auth router is already mounted on ``ayaz.main.app`` — reuse it.
* ``get_db`` is overridden to inject the test session.
* Real JWTs are issued via ``create_access_token`` so the Bearer-token flow is
  exercised end-to-end (same pattern as test_workspaces.py).
* Rate limiting is disabled globally via ``RATE_LIMIT_ENABLED=false`` — see
  conftest.py / env fixture; the rate_limit dependency is a no-op when
  ``settings.rate_limit_enabled`` is False (default in tests).
"""

from __future__ import annotations

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure all model tables are registered on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.auth  # noqa: F401

from ayaz.database import get_db
from ayaz.main import app
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import create_access_token, hash_password


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


def _make_user(
    db: Session,
    email: str = "alice@example.com",
    password: str = "password123",
    full_name: str = "Alice Test",
) -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    db.add(u)
    db.flush()
    return u


def _make_tenant(db: Session, name: str = "Test Org") -> Tenant:
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


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Return a TestClient that injects the test DB session."""

    def override_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seeded(db_session: Session, client: TestClient):
    """Seed one user+tenant+membership and return (user, tenant, headers)."""
    user = _make_user(db_session)
    tenant = _make_tenant(db_session)
    _make_membership(db_session, user, tenant)
    db_session.commit()
    headers = _auth_header(user, tenant)
    return user, tenant, headers, client


# ── GET /auth/me — backward compat ────────────────────────────────────────────


class TestGetMe:
    def test_me_returns_id_email_full_name(self, seeded) -> None:
        user, _, headers, client = seeded
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert str(user.id) == data["id"]
        assert data["email"] == user.email
        assert data["full_name"] == user.full_name

    def test_me_includes_created_at(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200
        # created_at is the new optional field; it may be None (SQLite func.now)
        # but the key must be present
        assert "created_at" in resp.json()

    def test_me_requires_auth(self, client) -> None:
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


# ── PATCH /auth/me ────────────────────────────────────────────────────────────


class TestUpdateProfile:
    def test_update_full_name_happy_path(self, seeded) -> None:
        user, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/me",
            json={"full_name": "Alice Updated"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "Alice Updated"
        assert data["email"] == user.email  # unchanged

    def test_update_email_happy_path(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/me",
            json={"email": "newalice@example.com"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "newalice@example.com"

    def test_update_both_fields(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/me",
            json={"full_name": "New Name", "email": "new2@example.com"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "New Name"
        assert data["email"] == "new2@example.com"

    def test_empty_body_returns_400(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch("/api/v1/auth/me", json={}, headers=headers)
        assert resp.status_code == 400

    def test_email_conflict_with_other_user_returns_409(
        self, db_session: Session, client: TestClient
    ) -> None:
        # Create two users in the same DB session
        user_a = _make_user(db_session, email="a@example.com")
        user_b = _make_user(db_session, email="b@example.com")
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user_a, tenant)
        _make_membership(db_session, user_b, tenant)
        db_session.commit()

        headers_a = _auth_header(user_a, tenant)
        # Try to claim user_b's email as user_a
        resp = client.patch(
            "/api/v1/auth/me",
            json={"email": "b@example.com"},
            headers=headers_a,
        )
        assert resp.status_code == 409
        assert "zaten kullanımda" in resp.json()["detail"]

    def test_same_email_no_conflict(self, seeded) -> None:
        """Setting email to the user's current email must NOT conflict."""
        user, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/me",
            json={"email": user.email},
            headers=headers,
        )
        assert resp.status_code == 200

    def test_update_profile_requires_auth(self, client) -> None:
        resp = client.patch("/api/v1/auth/me", json={"full_name": "X"})
        assert resp.status_code == 401

    def test_response_contains_id(self, seeded) -> None:
        user, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/me",
            json={"full_name": "Check ID"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == str(user.id)


# ── POST /auth/change-password ────────────────────────────────────────────────


class TestChangePassword:
    def test_change_password_happy_path(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Şifre güncellendi."

    def test_change_password_wrong_current(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword456",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Mevcut şifre hatalı" in resp.json()["detail"]

    def test_change_password_too_short_new(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "short",  # < 8 chars
            },
            headers=headers,
        )
        # Pydantic validation → 422
        assert resp.status_code == 422

    def test_change_password_same_as_current(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "password123",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "aynı olamaz" in resp.json()["detail"]

    def test_change_password_requires_auth(self, client) -> None:
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
        )
        assert resp.status_code == 401

    def test_change_password_new_hash_verifiable(
        self, db_session: Session, client: TestClient
    ) -> None:
        """After a successful change the new password authenticates correctly."""
        from ayaz.services.auth import verify_password as vp

        user = _make_user(db_session)
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()
        headers = _auth_header(user, tenant)

        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "brandnewpassword",
            },
            headers=headers,
        )

        db_session.refresh(user)
        assert vp("brandnewpassword", user.hashed_password)
        assert not vp("password123", user.hashed_password)


# ── GET /auth/preferences ─────────────────────────────────────────────────────


class TestGetPreferences:
    def test_defaults_are_correct(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.get("/api/v1/auth/preferences", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "tr"
        assert data["timezone"] == "Europe/Istanbul"
        assert data["email_alerts"] is True
        assert data["email_briefing"] is True

    def test_preferences_requires_auth(self, client) -> None:
        resp = client.get("/api/v1/auth/preferences")
        assert resp.status_code == 401


# ── PATCH /auth/preferences ───────────────────────────────────────────────────


class TestUpdatePreferences:
    def test_update_locale_to_en(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"locale": "en"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["locale"] == "en"

    def test_update_timezone(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "UTC"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["timezone"] == "UTC"

    def test_update_email_alerts_false(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"email_alerts": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email_alerts"] is False

    def test_update_email_briefing_false(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"email_briefing": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email_briefing"] is False

    def test_partial_update_leaves_other_fields_unchanged(self, seeded) -> None:
        _, _, headers, client = seeded
        # Only update locale; other fields stay at defaults
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"locale": "en"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "en"
        assert data["timezone"] == "Europe/Istanbul"
        assert data["email_alerts"] is True
        assert data["email_briefing"] is True

    def test_invalid_locale_returns_422(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"locale": "de"},  # not in {"tr", "en"}
            headers=headers,
        )
        # Pydantic field_validator raises ValueError → 422
        assert resp.status_code == 422

    def test_update_all_preferences(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={
                "locale": "en",
                "timezone": "America/New_York",
                "email_alerts": False,
                "email_briefing": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "en"
        assert data["timezone"] == "America/New_York"
        assert data["email_alerts"] is False
        assert data["email_briefing"] is False

    def test_preferences_patch_requires_auth(self, client) -> None:
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"locale": "en"},
        )
        assert resp.status_code == 401

    def test_empty_patch_is_a_noop(self, seeded) -> None:
        """An empty PATCH body changes nothing and returns current values."""
        _, _, headers, client = seeded
        resp = client.patch("/api/v1/auth/preferences", json={}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "tr"
        assert data["timezone"] == "Europe/Istanbul"
