"""Tests for production security hardening — R-01, R-02, R-04.

Coverage
--------
R-01  Billing webhook signature verification (Stripe + iyzico)
R-02  Rate limiting (auth:login, auth:signup, public endpoints)
R-04  JWT revocation + logout endpoint

Test design
-----------
* Each test class is hermetic — fresh in-memory SQLite, no global state.
* Rate-limiter store is explicitly reset between test methods to avoid
  cross-contamination (the global counter dict is shared within a process).
* Rate-limit checks are exercised with a real settings override (a minimal
  Settings instance with rate_limit_enabled=True and a small limit).
* Token revocation tests use a real SQLite DB + the service functions directly
  as well as the FastAPI TestClient for endpoint-level checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.auth  # noqa: F401

from ayaz.api.deps import get_current_membership, get_current_user, get_db
from ayaz.api.v1 import auth as auth_module
from ayaz.api.v1 import billing as billing_module
from ayaz.config import settings
from ayaz.database import get_db as real_get_db
from ayaz.models.auth import RevokedToken
from ayaz.models.base import Base
from ayaz.models.billing import BillingEvent, Subscription
from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
)
from ayaz.security.rate_limit import _check_rate_limit, _reset_store
from ayaz.security.webhook_sig import verify_iyzico_signature, verify_stripe_signature
from ayaz.services.auth import (
    cleanup_revoked_tokens,
    create_access_token,
    decode_access_token,
    hash_password,
    is_token_revoked,
    revoke_token,
)


# ── Shared DB fixture ─────────────────────────────────────────────────────────


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


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name="Security Test Tenant",
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
        email=f"security-{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Security Test User",
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


# ══════════════════════════════════════════════════════════════════════════════
# R-01  Webhook signature verification
# ══════════════════════════════════════════════════════════════════════════════


class TestStripeSignatureVerification:
    """Unit tests for verify_stripe_signature (no HTTP, no DB)."""

    _SECRET = "whsec_test_secret_key_for_pytest"
    _BODY = b'{"type":"invoice.paid","tenant_id":"abc"}'

    def _make_header(
        self,
        body: bytes = _BODY,
        secret: str = _SECRET,
        ts: int | None = None,
    ) -> str:
        ts = ts or int(time.time())
        signed = f"{ts}.{body.decode()}"
        sig = hmac.new(
            secret.encode(), signed.encode(), hashlib.sha256
        ).hexdigest()
        return f"t={ts},v1={sig}"

    def test_valid_signature_accepted(self) -> None:
        header = self._make_header()
        assert verify_stripe_signature(self._BODY, header, self._SECRET) is True

    def test_wrong_secret_rejected(self) -> None:
        header = self._make_header(secret="wrong_secret")
        assert verify_stripe_signature(self._BODY, header, self._SECRET) is False

    def test_tampered_body_rejected(self) -> None:
        header = self._make_header()
        tampered = b'{"type":"subscription.upgraded","tenant_id":"hacked"}'
        assert verify_stripe_signature(tampered, header, self._SECRET) is False

    def test_old_timestamp_rejected(self) -> None:
        old_ts = int(time.time()) - 400  # older than 300 s tolerance
        header = self._make_header(ts=old_ts)
        assert verify_stripe_signature(self._BODY, header, self._SECRET) is False

    def test_missing_header_rejected(self) -> None:
        assert verify_stripe_signature(self._BODY, "", self._SECRET) is False

    def test_malformed_header_rejected(self) -> None:
        assert verify_stripe_signature(self._BODY, "garbage", self._SECRET) is False

    def test_empty_secret_skips_verification(self) -> None:
        """No secret → stub mode; always True."""
        assert verify_stripe_signature(self._BODY, "", "") is True

    def test_custom_tolerance_injectable_now(self) -> None:
        """Simulate clock injection for testing timestamp window."""
        ts = 1_000_000
        header = self._make_header(ts=ts)
        # With _now = ts (exact), should pass
        assert (
            verify_stripe_signature(self._BODY, header, self._SECRET, _now=float(ts))
            is True
        )
        # With _now = ts + 301 (over tolerance), should fail
        assert (
            verify_stripe_signature(
                self._BODY, header, self._SECRET, _now=float(ts + 301)
            )
            is False
        )


class TestIyzicoSignatureVerification:
    """Unit tests for verify_iyzico_signature (no HTTP, no DB)."""

    _SECRET = "iyzico_test_secret_key"
    _BODY = b'{"type":"checkout.completed","tenant_id":"abc"}'

    def _make_sig(self, body: bytes = _BODY, secret: str = _SECRET) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepted(self) -> None:
        sig = self._make_sig()
        assert verify_iyzico_signature(self._BODY, sig, self._SECRET) is True

    def test_wrong_secret_rejected(self) -> None:
        sig = self._make_sig(secret="wrong")
        assert verify_iyzico_signature(self._BODY, sig, self._SECRET) is False

    def test_tampered_body_rejected(self) -> None:
        sig = self._make_sig()
        tampered = b'{"type":"spoofed"}'
        assert verify_iyzico_signature(tampered, sig, self._SECRET) is False

    def test_empty_header_rejected(self) -> None:
        assert verify_iyzico_signature(self._BODY, "", self._SECRET) is False

    def test_empty_secret_skips_verification(self) -> None:
        assert verify_iyzico_signature(self._BODY, "", "") is True


class TestBillingWebhookSignatureEndpoint:
    """Integration: HTTP endpoint rejects bad signatures when secret is configured."""

    _STRIPE_SECRET = "whsec_pytest_endpoint_secret"
    _IYZICO_SECRET = "iyzico_pytest_endpoint_secret"

    @pytest.fixture()
    def billing_app(self, db_session: Session, monkeypatch):
        """Minimal billing app with monkeypatched secrets."""
        monkeypatch.setattr(settings, "stripe_webhook_secret", self._STRIPE_SECRET)
        monkeypatch.setattr(settings, "iyzico_webhook_secret", self._IYZICO_SECRET)

        app = FastAPI()
        app.include_router(billing_module.router, prefix="/api/v1")

        tenant = _make_tenant(db_session)
        db_session.commit()

        def override_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        return TestClient(app, raise_server_exceptions=False), tenant

    def _stripe_header(self, body: bytes, secret: str) -> str:
        ts = int(time.time())
        signed = f"{ts}.{body.decode()}"
        sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def _iyzico_sig(self, body: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_stripe_valid_signature_accepted(self, billing_app) -> None:
        client, tenant = billing_app
        payload = {"tenant_id": str(tenant.id), "type": "invoice.paid"}
        body = json.dumps(payload).encode()
        header = self._stripe_header(body, self._STRIPE_SECRET)
        resp = client.post(
            "/api/v1/billing/webhook/stripe",
            content=body,
            headers={"Content-Type": "application/json", "stripe-signature": header},
        )
        assert resp.status_code == 200

    def test_stripe_invalid_signature_rejected(self, billing_app) -> None:
        client, tenant = billing_app
        payload = {"tenant_id": str(tenant.id), "type": "invoice.paid"}
        body = json.dumps(payload).encode()
        resp = client.post(
            "/api/v1/billing/webhook/stripe",
            content=body,
            headers={
                "Content-Type": "application/json",
                "stripe-signature": "t=1234,v1=badsig",
            },
        )
        assert resp.status_code == 400

    def test_stripe_missing_signature_rejected(self, billing_app) -> None:
        client, tenant = billing_app
        payload = {"tenant_id": str(tenant.id), "type": "invoice.paid"}
        resp = client.post(
            "/api/v1/billing/webhook/stripe",
            json=payload,
        )
        assert resp.status_code == 400

    def test_iyzico_valid_signature_accepted(self, billing_app) -> None:
        client, tenant = billing_app
        payload = {"tenant_id": str(tenant.id), "type": "checkout.completed"}
        body = json.dumps(payload).encode()
        sig = self._iyzico_sig(body, self._IYZICO_SECRET)
        resp = client.post(
            "/api/v1/billing/webhook/iyzico",
            content=body,
            headers={"Content-Type": "application/json", "x-iyzico-signature": sig},
        )
        assert resp.status_code == 200

    def test_iyzico_invalid_signature_rejected(self, billing_app) -> None:
        client, tenant = billing_app
        payload = {"tenant_id": str(tenant.id), "type": "checkout.completed"}
        body = json.dumps(payload).encode()
        resp = client.post(
            "/api/v1/billing/webhook/iyzico",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-iyzico-signature": "badsignature",
            },
        )
        assert resp.status_code == 400

    def test_stub_mode_no_secret_accepts_all(self, db_session: Session, monkeypatch) -> None:
        """When secrets are empty (stub mode), all payloads are accepted."""
        monkeypatch.setattr(settings, "stripe_webhook_secret", "")
        monkeypatch.setattr(settings, "iyzico_webhook_secret", "")

        app = FastAPI()
        app.include_router(billing_module.router, prefix="/api/v1")
        tenant = _make_tenant(db_session)
        db_session.commit()

        def override_db():
            yield db_session

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)

        payload = {"tenant_id": str(tenant.id), "type": "invoice.paid"}
        resp = client.post("/api/v1/billing/webhook/stripe", json=payload)
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# R-02  Rate limiting
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimiterCore:
    """Unit tests for _check_rate_limit with injectable clock."""

    def setup_method(self) -> None:
        _reset_store()

    def test_first_request_allowed(self) -> None:
        # Should not raise
        _check_rate_limit("1.2.3.4", "test:route", limit=5, window_seconds=60, now=0.0)

    def test_requests_within_limit_allowed(self) -> None:
        for i in range(5):
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=5, window_seconds=60, now=float(i)
            )

    def test_request_over_limit_raises_429(self) -> None:
        from fastapi import HTTPException

        for i in range(5):
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=5, window_seconds=60, now=0.0
            )
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=5, window_seconds=60, now=0.5
            )
        assert exc_info.value.status_code == 429

    def test_window_reset_allows_again(self) -> None:
        for i in range(5):
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=5, window_seconds=60, now=0.0
            )
        # Advance time past the window — should reset
        _check_rate_limit(
            "1.2.3.4", "test:route", limit=5, window_seconds=60, now=61.0
        )

    def test_different_ips_are_independent_buckets(self) -> None:
        from fastapi import HTTPException

        # Fill the bucket for 1.2.3.4
        for _ in range(3):
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=3, window_seconds=60, now=0.0
            )
        # Exceed for 1.2.3.4
        with pytest.raises(HTTPException):
            _check_rate_limit(
                "1.2.3.4", "test:route", limit=3, window_seconds=60, now=0.0
            )
        # 5.6.7.8 should still be fine
        _check_rate_limit(
            "5.6.7.8", "test:route", limit=3, window_seconds=60, now=0.0
        )

    def test_different_keys_are_independent_buckets(self) -> None:
        from fastapi import HTTPException

        for _ in range(3):
            _check_rate_limit("1.2.3.4", "route:a", limit=3, window_seconds=60, now=0.0)
        # Exceed for route:a
        with pytest.raises(HTTPException):
            _check_rate_limit("1.2.3.4", "route:a", limit=3, window_seconds=60, now=0.0)
        # route:b still fine
        _check_rate_limit("1.2.3.4", "route:b", limit=3, window_seconds=60, now=0.0)

    def test_429_message_is_turkish(self) -> None:
        from fastapi import HTTPException

        for _ in range(3):
            _check_rate_limit("1.2.3.4", "test:rl", limit=3, window_seconds=60, now=0.0)
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit("1.2.3.4", "test:rl", limit=3, window_seconds=60, now=0.0)
        assert "çok fazla" in exc_info.value.detail.lower()

    def test_reset_store_clears_all_buckets(self) -> None:
        for _ in range(5):
            _check_rate_limit("1.2.3.4", "reset:test", limit=5, window_seconds=60, now=0.0)
        _reset_store()
        # After reset, counter starts fresh
        _check_rate_limit("1.2.3.4", "reset:test", limit=5, window_seconds=60, now=0.0)


class TestRateLimitDisabledInTests:
    """rate_limit_enabled=False means no 429s."""

    def setup_method(self) -> None:
        _reset_store()

    def test_disabled_never_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        from ayaz.security.rate_limit import rate_limit
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.get("/test")
        def _test(_rl=None) -> dict:
            return {"ok": True}

        # patch Depends to inject the rate_limit dep
        from ayaz.security.rate_limit import rate_limit as rl_factory

        dep = rl_factory("test:key", limit=1, window_seconds=60)

        @app.get("/limited")
        def _limited(req=None, _rl=None) -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Direct call: rate_limit_enabled=False → no HTTPException
        from unittest.mock import MagicMock
        fake_req = MagicMock()
        fake_req.headers = {}
        fake_req.client = MagicMock()
        fake_req.client.host = "127.0.0.1"
        dep(fake_req)  # should not raise even if called many times
        dep(fake_req)
        dep(fake_req)


# ══════════════════════════════════════════════════════════════════════════════
# R-04  JWT revocation + logout
# ══════════════════════════════════════════════════════════════════════════════


class TestJtiInToken:
    """Tokens must contain a jti claim after the hardening change."""

    def test_token_has_jti_claim(self) -> None:
        token = create_access_token(user_id="u1", tenant_id="t1")
        payload = decode_access_token(token)
        assert "jti" in payload, "jti claim missing from access token"

    def test_jti_is_a_valid_uuid_string(self) -> None:
        token = create_access_token(user_id="u1", tenant_id="t1")
        payload = decode_access_token(token)
        jti = payload["jti"]
        # Should be parseable as UUID
        parsed = uuid.UUID(jti)
        assert str(parsed) == jti

    def test_two_tokens_have_different_jtis(self) -> None:
        t1 = create_access_token(user_id="u1", tenant_id="t1")
        t2 = create_access_token(user_id="u1", tenant_id="t1")
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]

    def test_existing_claims_still_present(self) -> None:
        token = create_access_token(user_id="user-abc", tenant_id="tenant-xyz")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-abc"
        assert payload["tid"] == "tenant-xyz"
        assert "exp" in payload
        assert "iat" in payload


class TestTokenRevocationService:
    """Service-layer tests for revoke_token / is_token_revoked / cleanup."""

    def test_newly_issued_token_not_revoked(self, db_session: Session) -> None:
        token = create_access_token(user_id="u1", tenant_id="t1")
        payload = decode_access_token(token)
        assert is_token_revoked(db_session, payload["jti"]) is False

    def test_revoked_token_detected(self, db_session: Session) -> None:
        token = create_access_token(user_id="u1", tenant_id="t1")
        payload = decode_access_token(token)
        revoke_token(db_session, payload)
        assert is_token_revoked(db_session, payload["jti"]) is True

    def test_revoke_same_token_twice_is_idempotent(self, db_session: Session) -> None:
        """Second revoke of the same jti must not raise."""
        token = create_access_token(user_id="u1", tenant_id="t1")
        payload = decode_access_token(token)
        revoke_token(db_session, payload)
        revoke_token(db_session, payload)  # no error
        assert is_token_revoked(db_session, payload["jti"]) is True

    def test_only_revoked_token_is_in_deny_list(self, db_session: Session) -> None:
        t1 = create_access_token(user_id="u1", tenant_id="t1")
        t2 = create_access_token(user_id="u1", tenant_id="t1")
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        revoke_token(db_session, p1)
        assert is_token_revoked(db_session, p1["jti"]) is True
        assert is_token_revoked(db_session, p2["jti"]) is False

    def test_cleanup_removes_expired_entries(self, db_session: Session) -> None:
        """cleanup_revoked_tokens removes rows whose expires_at is in the past."""
        _make_tenant(db_session)
        db_session.commit()

        # Create a token with expires_delta=-1 so expires_at is in the past
        token = create_access_token(
            user_id="u1",
            tenant_id="t1",
            expires_delta=timedelta(seconds=-1),
        )
        # We can't decode an expired token normally, so build a row manually
        from datetime import datetime, timezone

        past_iso = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        row = RevokedToken(
            jti=str(uuid.uuid4()),
            tenant_id=None,
            revoked_at=datetime.now(timezone.utc).isoformat(),
            expires_at=past_iso,
        )
        db_session.add(row)
        db_session.commit()

        count = cleanup_revoked_tokens(db_session)
        assert count >= 1
        assert is_token_revoked(db_session, row.jti) is False

    def test_cleanup_keeps_not_yet_expired_entries(self, db_session: Session) -> None:
        from datetime import datetime, timezone

        future_iso = (
            datetime.now(timezone.utc) + timedelta(hours=2)
        ).isoformat()
        jti = str(uuid.uuid4())
        row = RevokedToken(
            jti=jti,
            tenant_id=None,
            revoked_at=datetime.now(timezone.utc).isoformat(),
            expires_at=future_iso,
        )
        db_session.add(row)
        db_session.commit()

        cleanup_revoked_tokens(db_session)
        assert is_token_revoked(db_session, jti) is True


class TestLogoutEndpoint:
    """HTTP-level tests for POST /auth/logout."""

    @pytest.fixture()
    def auth_app(self, db_session: Session):
        """Minimal auth app wired to test DB."""
        app = FastAPI()
        app.include_router(auth_module.router, prefix="/api/v1")

        tenant = _make_tenant(db_session)
        user = _make_user(db_session)
        membership = _make_membership(db_session, user, tenant)
        db_session.commit()

        def override_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_db

        # Disable rate limiting for auth endpoint tests
        import ayaz.config as cfg_module
        original = settings.rate_limit_enabled
        settings.__dict__["rate_limit_enabled"] = False

        client = TestClient(app)
        yield client, user, tenant, membership

        settings.__dict__["rate_limit_enabled"] = original
        app.dependency_overrides.clear()

    def test_logout_returns_200(self, auth_app) -> None:
        client, user, tenant, _ = auth_app
        token = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_logout_response_has_turkish_detail(self, auth_app) -> None:
        client, user, tenant, _ = auth_app
        token = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.json()
        assert "çıkış" in body.get("detail", "").lower()

    def test_revoked_token_rejected_on_me_endpoint(
        self, auth_app, db_session: Session
    ) -> None:
        client, user, tenant, _ = auth_app
        token = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        # Logout — revoke the token
        logout_resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert logout_resp.status_code == 200

        # Now try to use the same token on /me — should get 401
        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 401

    def test_logout_without_token_returns_401(self, auth_app) -> None:
        client, _, _, _ = auth_app
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 401

    def test_second_logout_with_same_token_returns_401(
        self, auth_app
    ) -> None:
        """After logout, re-using the same token (even on logout) fails 401."""
        client, user, tenant, _ = auth_app
        token = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        # First logout
        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Second attempt to logout with the revoked token
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        # The /logout endpoint calls get_current_user (via Depends) which will
        # reject the revoked token
        assert resp.status_code == 401

    def test_different_token_still_valid_after_one_revoked(
        self, auth_app
    ) -> None:
        client, user, tenant, _ = auth_app
        token_a = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        token_b = create_access_token(
            user_id=str(user.id), tenant_id=str(tenant.id)
        )
        # Revoke token_a
        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        # token_b should still be accepted on /me
        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert me_resp.status_code == 200


class TestAuthServiceBackwardCompat:
    """Ensure existing auth service tests still pass after jti addition."""

    def test_create_and_decode_token(self) -> None:
        token = create_access_token(user_id="user-1", tenant_id="tenant-1")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-1"
        assert payload["tid"] == "tenant-1"

    def test_token_contains_all_required_claims(self) -> None:
        token = create_access_token(user_id="abc", tenant_id="xyz")
        payload = decode_access_token(token)
        for claim in ("sub", "tid", "iat", "exp", "jti"):
            assert claim in payload, f"Missing claim: {claim}"
