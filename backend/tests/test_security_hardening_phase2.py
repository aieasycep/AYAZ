"""Security hardening phase-2 tests — Items A, B, C, D.

Item A  — Timezone validation in PATCH /auth/preferences
Item B  — Symmetry guard in copilot get_top_movers (date_from > date_to)
Item C  — Session invalidation on password change (iat vs credentials_changed_at)
Item D  — Generic error message in copilot tool dispatch

Test strategy
-------------
* Item A and C use FastAPI TestClient with an in-memory SQLite DB.
* Item B and D exercise the service layer directly (no HTTP needed).
* All tests are hermetic — no shared state between test classes.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules so Base.metadata is complete
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.auth  # noqa: F401

from ayaz.database import get_db
from ayaz.main import app
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import create_access_token, decode_access_token, hash_password


# ── Shared DB fixture ─────────────────────────────────────────────────────────


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
    email: str | None = None,
    password: str = "password123",
) -> User:
    if email is None:
        email = f"user-{uuid.uuid4().hex[:6]}@test.example"
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        full_name="Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name="Test Tenant",
        country="TR",
        base_currency="TRY",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


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


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_db():
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
    """Create one user+tenant+membership, return (user, tenant, headers, client)."""
    user = _make_user(db_session)
    tenant = _make_tenant(db_session)
    _make_membership(db_session, user, tenant)
    db_session.commit()
    token = create_access_token(str(user.id), str(tenant.id))
    headers = {"Authorization": f"Bearer {token}"}
    return user, tenant, headers, client


# ══════════════════════════════════════════════════════════════════════════════
# Item A — Timezone validation in PATCH /auth/preferences
# ══════════════════════════════════════════════════════════════════════════════


class TestTimezoneValidation:
    """PATCH /auth/preferences must reject unknown timezone strings with 422."""

    def test_valid_timezone_europe_istanbul_accepted(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "Europe/Istanbul"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["timezone"] == "Europe/Istanbul"

    def test_valid_timezone_utc_accepted(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "UTC"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["timezone"] == "UTC"

    def test_valid_timezone_america_new_york_accepted(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "America/New_York"},
            headers=headers,
        )
        assert resp.status_code == 200

    def test_invalid_timezone_returns_422(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "Not/AValid/Timezone"},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_invalid_timezone_arbitrary_string_returns_422(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "banana"},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_invalid_timezone_error_has_turkish_message(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "Invalid/Zone"},
            headers=headers,
        )
        assert resp.status_code == 422
        body = resp.json()
        # Pydantic wraps our ValueError; the message should appear in detail
        detail_str = str(body.get("detail", ""))
        assert "Geçersiz saat dilimi" in detail_str

    def test_none_timezone_not_validated(self, seeded) -> None:
        """Omitting timezone entirely should not trigger timezone validation."""
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"locale": "en"},  # no timezone field
            headers=headers,
        )
        assert resp.status_code == 200

    def test_valid_timezone_asia_tokyo_accepted(self, seeded) -> None:
        _, _, headers, client = seeded
        resp = client.patch(
            "/api/v1/auth/preferences",
            json={"timezone": "Asia/Tokyo"},
            headers=headers,
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Item B — Symmetry guard in copilot get_top_movers
# ══════════════════════════════════════════════════════════════════════════════


class TestGetTopMoversSymmetryGuard:
    """date_from > date_to must not crash — the tool should swap and return."""

    @pytest.fixture()
    def minimal_db(self):
        """Minimal in-memory DB for copilot tool dispatch calls."""
        engine = create_engine(
            "sqlite://",
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
        import ayaz.models.auth  # noqa: F401

        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()
            Base.metadata.drop_all(engine)

    def test_inverted_dates_do_not_raise(self, minimal_db: Session) -> None:
        """date_from after date_to must not raise an exception."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch("get_top_movers", minimal_db, tenant_id, {
            "date_from": "2024-05-14",   # later
            "date_to": "2024-05-01",     # earlier
        })
        # No exception — result is a dict (not necessarily an "error" key)
        assert isinstance(result, dict)

    def test_inverted_dates_return_movers_key(self, minimal_db: Session) -> None:
        """Swapped dates still return a valid result dict with 'movers'."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch("get_top_movers", minimal_db, tenant_id, {
            "date_from": "2024-06-01",
            "date_to": "2024-05-01",
        })
        assert "movers" in result, f"Expected 'movers' key, got: {result}"

    def test_inverted_dates_no_error_key(self, minimal_db: Session) -> None:
        """With inverted dates the result must NOT contain 'error'."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch("get_top_movers", minimal_db, tenant_id, {
            "date_from": "2025-01-31",
            "date_to": "2025-01-01",
        })
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

    def test_normal_date_order_still_works(self, minimal_db: Session) -> None:
        """Correctly-ordered dates continue to work as before."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch("get_top_movers", minimal_db, tenant_id, {
            "date_from": "2024-05-01",
            "date_to": "2024-05-14",
        })
        assert "movers" in result


# ══════════════════════════════════════════════════════════════════════════════
# Item C — Session invalidation on password change
# ══════════════════════════════════════════════════════════════════════════════


class TestCredentialsChangedAt:
    """tokens issued before credentials_changed_at are rejected."""

    def test_credentials_changed_at_is_none_by_default(
        self, db_session: Session
    ) -> None:
        user = _make_user(db_session)
        db_session.commit()
        db_session.refresh(user)
        assert user.credentials_changed_at is None

    def test_token_valid_when_credentials_changed_at_is_none(
        self, db_session: Session, client: TestClient
    ) -> None:
        """No cutoff set → any valid token is accepted."""
        user = _make_user(db_session)
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        token = create_access_token(str(user.id), str(tenant.id))
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_token_issued_before_change_is_rejected(
        self, db_session: Session, client: TestClient
    ) -> None:
        """A token issued before credentials_changed_at must be rejected with 401.

        We set credentials_changed_at to 2 seconds in the future relative to the
        token's iat, ensuring iat_dt < cca_seconds (after truncation to seconds).
        """
        user = _make_user(db_session)
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        # Issue a token now
        old_token = create_access_token(str(user.id), str(tenant.id))

        # Set credentials_changed_at to 2 seconds AFTER the token was issued.
        # After truncating both to seconds: iat_epoch+0 < iat_epoch+2 → rejected.
        db_session.refresh(user)
        iat_epoch = decode_access_token(old_token)["iat"]
        iat_dt = datetime.fromtimestamp(float(iat_epoch), tz=timezone.utc)
        user.credentials_changed_at = iat_dt + timedelta(seconds=2)
        db_session.commit()

        # The old token must now be rejected
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert resp.status_code == 401

    def test_token_issued_after_change_is_accepted(
        self, db_session: Session, client: TestClient
    ) -> None:
        """A token issued after credentials_changed_at must be accepted.

        credentials_changed_at is set to 2 full seconds ago so that the new
        token's iat (epoch seconds, now) is strictly >= cca_seconds.
        """
        user = _make_user(db_session)
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        # Set credentials_changed_at to 2 seconds in the past
        db_session.refresh(user)
        user.credentials_changed_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        db_session.commit()

        # Issue a fresh token — its iat is at 'now', >= cca_seconds
        new_token = create_access_token(str(user.id), str(tenant.id))
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert resp.status_code == 200

    def test_change_password_endpoint_sets_credentials_changed_at(
        self, db_session: Session, client: TestClient
    ) -> None:
        """POST /auth/change-password must set credentials_changed_at on the user row."""
        user = _make_user(db_session, password="password123")
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        token = create_access_token(str(user.id), str(tenant.id))
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        db_session.refresh(user)
        assert user.credentials_changed_at is not None

    def test_change_password_invalidates_prior_tokens(
        self, db_session: Session, client: TestClient
    ) -> None:
        """After POST /auth/change-password, old tokens are rejected on the next request.

        We manually set credentials_changed_at to 2 seconds ahead of the token's
        iat so the cutoff comparison is deterministic without sleeping.
        """
        user = _make_user(db_session, password="password123")
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        # Issue a token before the password change
        old_token = create_access_token(str(user.id), str(tenant.id))

        # Verify old token works before the change
        pre_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert pre_resp.status_code == 200

        # Change the password using the old token; this sets credentials_changed_at
        change_resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "brandnew789",
            },
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert change_resp.status_code == 200

        # Manually push credentials_changed_at 2 seconds past the token's iat
        # to guarantee iat_dt < cca_seconds after truncation.
        db_session.refresh(user)
        iat_epoch = decode_access_token(old_token)["iat"]
        iat_dt = datetime.fromtimestamp(float(iat_epoch), tz=timezone.utc)
        user.credentials_changed_at = iat_dt + timedelta(seconds=2)
        db_session.commit()

        # Old token must now be rejected (iat < credentials_changed_at)
        post_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert post_resp.status_code == 401

    def test_fresh_login_token_accepted_after_password_change(
        self, db_session: Session, client: TestClient
    ) -> None:
        """A token issued after the change (fresh login) must be accepted.

        We set credentials_changed_at to 2 seconds in the past so any token
        issued 'now' has iat >= cca_seconds, making it valid.
        """
        user = _make_user(db_session, password="password123")
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        # Set credentials_changed_at to 2 seconds in the past
        db_session.refresh(user)
        user.credentials_changed_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        db_session.commit()

        # Issue a fresh token — its iat is at 'now', which is >= cca_seconds
        new_token = create_access_token(str(user.id), str(tenant.id))
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert resp.status_code == 200

    def test_iat_claim_is_present_in_token(self) -> None:
        """All issued tokens must carry an 'iat' claim (epoch seconds)."""
        token = create_access_token("user-abc", "tenant-xyz")
        payload = decode_access_token(token)
        assert "iat" in payload
        # iat must be a numeric type
        assert isinstance(payload["iat"], (int, float))

    def test_normal_flows_unaffected_when_no_credentials_changed_at(
        self, db_session: Session, client: TestClient
    ) -> None:
        """Existing login/me/preferences flows work when credentials_changed_at is NULL."""
        user = _make_user(db_session)
        tenant = _make_tenant(db_session)
        _make_membership(db_session, user, tenant)
        db_session.commit()

        token = create_access_token(str(user.id), str(tenant.id))
        headers = {"Authorization": f"Bearer {token}"}

        # Multiple endpoints should all work
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.get("/api/v1/auth/preferences", headers=headers).status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Item D — Generic error message in copilot dispatch
# ══════════════════════════════════════════════════════════════════════════════


class TestCopilotDispatchGenericError:
    """dispatch() must return a generic Turkish error, never expose internals."""

    @pytest.fixture()
    def minimal_db(self):
        """Minimal in-memory DB for copilot dispatch calls."""
        engine = create_engine(
            "sqlite://",
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
        import ayaz.models.auth  # noqa: F401

        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()
            Base.metadata.drop_all(engine)

    def test_bad_arg_returns_generic_error_message(
        self, minimal_db: Session
    ) -> None:
        """Passing an unexpected kwarg raises TypeError — must return generic message."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch(
            "get_performance_summary",
            minimal_db,
            tenant_id,
            {
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
                "__injected__": "evil",  # unexpected kwarg → TypeError
            },
        )
        assert result.get("error") == "Araç çalıştırılamadı."

    def test_generic_error_does_not_expose_signature(
        self, minimal_db: Session
    ) -> None:
        """The error value must not contain Python internals like 'got an unexpected'."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch(
            "get_timeseries",
            minimal_db,
            tenant_id,
            {
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
                "metric": "spend",
                "unexpected_kwarg": "x",  # TypeError
            },
        )
        error_msg = result.get("error", "")
        assert "unexpected" not in error_msg.lower()
        assert "argument" not in error_msg.lower()
        assert "got an" not in error_msg.lower()

    def test_generic_error_is_turkish(self, minimal_db: Session) -> None:
        """The generic error message must be in Turkish."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch(
            "get_insights",
            minimal_db,
            tenant_id,
            {"bad_kwarg": True},  # TypeError
        )
        # Must be the exact generic Turkish string
        assert result.get("error") == "Araç çalıştırılamadı."

    def test_unknown_tool_still_returns_its_own_error(
        self, minimal_db: Session
    ) -> None:
        """An unknown tool name returns the 'unknown tool' error, not the generic one."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch("nonexistent_tool", minimal_db, tenant_id, {})
        # Unknown tool has its own message path
        assert "error" in result
        assert "nonexistent_tool" in result["error"]

    def test_successful_call_not_affected(self, minimal_db: Session) -> None:
        """A valid call to a tool must still return its real result."""
        from ayaz.services.copilot_tools import dispatch

        tenant_id = uuid.uuid4()
        result = dispatch(
            "get_performance_summary",
            minimal_db,
            tenant_id,
            {"date_from": "2024-01-01", "date_to": "2024-01-31"},
        )
        # No error, valid structure
        assert "error" not in result
        assert "totals" in result
