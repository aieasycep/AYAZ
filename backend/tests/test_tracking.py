"""Tests for Server-side Tracking / Conversions API — M7.

Strategy
--------
* FastAPI TestClient with a minimal test app that includes only the tracking
  router (same pattern as test_feeds_api.py).  main.py is untouched.
* get_db overridden to an in-memory SQLite session.
* get_current_membership overridden to a pre-built Membership (no auth).
* No live network calls — httpx.Client is mocked in forward tests.
* All existing tests remain green; this file adds only new test classes.

Coverage
--------
1. hash_identity — deterministic SHA-256, normalization (email/phone).
2. ingest_event — dedup by event_id; consent-skip when destination requires it.
3. forward_event — correct URL + payload shape for each of the three platforms.
4. Public collect endpoint — happy path + unknown/inactive token 404.
5. TrackingSource CRUD — create/list/get/patch/delete + tenant isolation.
6. EventDestination CRUD — create/list/get/patch/delete.
7. Snippet endpoint — returns collect_url and js_snippet.
8. Event log endpoint — returns events for a source.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401
import ayaz.models.insights  # noqa: F401
import ayaz.models.reports  # noqa: F401
import ayaz.models.automation  # noqa: F401
import ayaz.models.tracking  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import tracking as tracking_module
from ayaz.services.auth import hash_password
from ayaz.services.tracking import (
    forward_event,
    hash_identity,
    ingest_event,
    _sha256,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Tracking Test App")
_test_app.include_router(tracking_module.router, prefix="/api/v1")

# ── DB fixture ────────────────────────────────────────────────────────────────


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


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Tracking Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="tracking_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Tracking Test User",
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


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_source(db: Session, tenant_id: uuid.UUID, **kwargs: Any) -> TrackingSource:
    src = TrackingSource(
        tenant_id=tenant_id,
        name=kwargs.get("name", "Test Source"),
        domain=kwargs.get("domain", None),
        public_token=kwargs.get("public_token", f"tok-{uuid.uuid4().hex}"),
        is_active=kwargs.get("is_active", True),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_destination(
    db: Session,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    platform: str = "meta_capi",
    config: dict | None = None,
    consent_required: bool = True,
    **kwargs: Any,
) -> EventDestination:
    dest = EventDestination(
        tenant_id=tenant_id,
        tracking_source_id=source_id,
        platform=platform,
        config=config or {"pixel_id": "TEST_PIXEL", "_secrets": {"access_token": "tok-test"}},
        vault_secret_ref="",
        consent_required=consent_required,
        is_active=kwargs.get("is_active", True),
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return dest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. hash_identity
# ═══════════════════════════════════════════════════════════════════════════════


class TestHashIdentity:
    def test_email_lowercased_and_trimmed(self) -> None:
        result = hash_identity({"email": "  Alice@Example.COM  "})
        expected = hashlib.sha256("alice@example.com".encode()).hexdigest()
        assert result["email_hash"] == expected

    def test_email_deterministic(self) -> None:
        r1 = hash_identity({"email": "user@test.com"})
        r2 = hash_identity({"email": "user@test.com"})
        assert r1["email_hash"] == r2["email_hash"]

    def test_phone_digits_only(self) -> None:
        result = hash_identity({"phone": "+90 (532) 123-4567"})
        expected = hashlib.sha256("905321234567".encode()).hexdigest()
        assert result["phone_hash"] == expected

    def test_phone_deterministic(self) -> None:
        r1 = hash_identity({"phone": "5321234567"})
        r2 = hash_identity({"phone": "532 123 4567"})
        assert r1["phone_hash"] == r2["phone_hash"]

    def test_both_email_and_phone(self) -> None:
        result = hash_identity({"email": "a@b.com", "phone": "5001112233"})
        assert "email_hash" in result
        assert "phone_hash" in result
        assert len(result) == 2

    def test_empty_input_returns_empty(self) -> None:
        result = hash_identity({})
        assert result == {}

    def test_passthrough_already_hashed(self) -> None:
        existing_hash = "abc123" + "0" * 58  # 64-char hex
        result = hash_identity({"fbp_hash": existing_hash})
        assert result["fbp_hash"] == existing_hash

    def test_raw_values_not_in_output(self) -> None:
        result = hash_identity({"email": "secret@x.com", "phone": "1234"})
        assert "email" not in result
        assert "phone" not in result

    def test_sha256_helper(self) -> None:
        assert _sha256("hello") == hashlib.sha256(b"hello").hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ingest_event — dedup and consent
# ═══════════════════════════════════════════════════════════════════════════════


class TestIngestEvent:
    def test_basic_ingest_received(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "order-001",
            "user_data": {"email": "buyer@test.com"},
            "custom_data": {"value": 99.0, "currency": "TRY"},
            "consent": True,
        }

        event = ingest_event(db_session, src, payload)
        assert event.event_name == "Purchase"
        assert event.event_id == "order-001"
        assert event.consent is True
        # PII must be hashed, not raw
        assert "email" not in event.user_data
        assert "email_hash" in event.user_data

    def test_dedup_returns_duplicate_status(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "order-dedup-001",
            "user_data": {},
            "custom_data": {},
            "consent": True,
        }

        first = ingest_event(db_session, src, payload)
        # Ingest the same event_id again
        second = ingest_event(db_session, src, payload)

        assert second.id == first.id
        assert second.status == "duplicate"

    def test_consent_skip_when_required(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            consent_required=True,
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "no-consent-001",
            "user_data": {},
            "custom_data": {},
            "consent": False,  # no consent
        }

        event = ingest_event(db_session, src, payload)
        assert event.status == "skipped_no_consent"
        assert event.forwarded_count == 0

    def test_no_destinations_stays_received(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        # No destinations

        payload = {
            "event_name": "ViewContent",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "view-001",
            "user_data": {},
            "custom_data": {},
            "consent": True,
        }

        event = ingest_event(db_session, src, payload)
        assert event.status == "received"

    def test_missing_required_fields_raises(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        with pytest.raises(ValueError, match="Missing required fields"):
            ingest_event(db_session, src, {"event_name": "Purchase"})

    def test_forwarded_status_with_mock(self, db_session: Session) -> None:
        """When a destination is active and consent given, event should be forwarded."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            consent_required=True,
            config={
                "pixel_id": "123456",
                "_secrets": {"access_token": "test-token"},
            },
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "order-fwd-001",
            "user_data": {},
            "custom_data": {},
            "consent": True,
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        assert event.status == "forwarded"
        assert event.forwarded_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. forward_event — payload shape per platform
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeEvent:
    """Lightweight stand-in for ConversionEvent used in forward-only unit tests.

    We don't persist these; they just need the attribute shape that
    ``forward_event`` reads.
    """
    def __init__(
        self,
        *,
        source_id: uuid.UUID,
        tenant_id: uuid.UUID,
        event_name: str = "Purchase",
        event_id: str = "evt-001",
        event_time: str = "2026-06-26T10:00:00Z",
        user_data: dict | None = None,
        custom_data: dict | None = None,
        consent: bool = True,
    ) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.tracking_source_id = source_id
        self.event_name = event_name
        self.event_id = event_id
        self.event_time = event_time
        self.user_data = user_data if user_data is not None else {"email_hash": "a" * 64}
        self.custom_data = custom_data if custom_data is not None else {"value": 50.0, "currency": "TRY"}
        self.consent = consent
        self.status = "received"
        self.forwarded_count = 0
        self.error = None
        self.created_at = "2026-06-26T10:00:00+00:00"


class _FakeDestination:
    """Lightweight stand-in for EventDestination used in forward-only unit tests."""
    def __init__(self, platform: str, config: dict) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.tracking_source_id = uuid.uuid4()
        self.platform = platform
        self.config = config
        self.vault_secret_ref = ""
        self.consent_required = True
        self.is_active = True


def _make_event(
    source_id: uuid.UUID,
    tenant_id: uuid.UUID,
    **kwargs: Any,
) -> _FakeEvent:
    return _FakeEvent(source_id=source_id, tenant_id=tenant_id, **kwargs)


def _make_dest_obj(platform: str, config: dict) -> _FakeDestination:
    return _FakeDestination(platform=platform, config=config)


class TestForwardMetaCapi:
    def test_posts_to_correct_url(self) -> None:
        pixel_id = "111222333"
        dest = _make_dest_obj(
            "meta_capi",
            {
                "pixel_id": pixel_id,
                "_secrets": {"access_token": "meta-tok"},
            },
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        call_args = mock_client.post.call_args
        url: str = call_args[0][0]
        assert f"/{pixel_id}/events" in url
        assert "graph.facebook.com" in url

    def test_payload_shape(self) -> None:
        pixel_id = "444555666"
        dest = _make_dest_obj(
            "meta_capi",
            {
                "pixel_id": pixel_id,
                "action_source": "website",
                "_secrets": {"access_token": "meta-tok"},
            },
        )
        email_hash = _sha256("buyer@example.com")
        evt = _make_event(
            uuid.uuid4(),
            uuid.uuid4(),
            event_name="Purchase",
            event_id="ord-42",
            user_data={"email_hash": email_hash},
            custom_data={"value": 120.0, "currency": "USD"},
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        body: dict = mock_client.post.call_args[1]["json"]
        assert body["access_token"] == "meta-tok"
        data_row = body["data"][0]
        assert data_row["event_name"] == "Purchase"
        assert data_row["event_id"] == "ord-42"
        assert data_row["action_source"] == "website"
        assert data_row["user_data"]["em"] == [email_hash]
        assert data_row["custom_data"]["value"] == 120.0

    def test_missing_pixel_id_raises(self) -> None:
        dest = _make_dest_obj(
            "meta_capi",
            {"_secrets": {"access_token": "tok"}},
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(RuntimeError, match="pixel_id"):
            forward_event(evt, dest, http_client=MagicMock())


class TestForwardTikTokEvents:
    def test_posts_to_correct_url(self) -> None:
        dest = _make_dest_obj(
            "tiktok_events",
            {
                "pixel_id": "TKTOK_PIX",
                "_secrets": {"access_token": "tt-tok"},
            },
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        call_args = mock_client.post.call_args
        url: str = call_args[0][0]
        assert "business-api.tiktok.com" in url
        assert "event/track" in url

    def test_payload_shape(self) -> None:
        dest = _make_dest_obj(
            "tiktok_events",
            {
                "pixel_id": "TKTOK_PIX_2",
                "_secrets": {"access_token": "tt-tok"},
            },
        )
        phone_hash = _sha256("5321234567")
        evt = _make_event(
            uuid.uuid4(),
            uuid.uuid4(),
            event_name="AddToCart",
            event_id="cart-7",
            user_data={"phone_hash": phone_hash},
            custom_data={"contents": [{"id": "SKU-1"}]},
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        body: dict = mock_client.post.call_args[1]["json"]
        assert body["pixel_code"] == "TKTOK_PIX_2"
        assert body["event"] == "AddToCart"
        assert body["event_id"] == "cart-7"
        assert body["context"]["user"]["phone"] == phone_hash
        assert body["properties"]["contents"] == [{"id": "SKU-1"}]

    def test_access_token_in_header(self) -> None:
        dest = _make_dest_obj(
            "tiktok_events",
            {
                "pixel_id": "PIX",
                "_secrets": {"access_token": "my-tt-token"},
            },
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        headers: dict = mock_client.post.call_args[1]["headers"]
        assert headers.get("Access-Token") == "my-tt-token"

    def test_missing_pixel_id_raises(self) -> None:
        dest = _make_dest_obj(
            "tiktok_events",
            {"_secrets": {"access_token": "tok"}},
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(RuntimeError, match="pixel_id"):
            forward_event(evt, dest, http_client=MagicMock())


class TestForwardGA4Mp:
    def test_posts_to_correct_url(self) -> None:
        dest = _make_dest_obj(
            "ga4_mp",
            {
                "measurement_id": "G-ABCDEF1234",
                "_secrets": {"api_secret": "ga4-sec"},
            },
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        call_args = mock_client.post.call_args
        url: str = call_args[0][0]
        assert "google-analytics.com/mp/collect" in url
        assert "G-ABCDEF1234" in url
        assert "ga4-sec" in url

    def test_payload_shape(self) -> None:
        dest = _make_dest_obj(
            "ga4_mp",
            {
                "measurement_id": "G-XYZ987",
                "_secrets": {"api_secret": "sec-xyz"},
            },
        )
        evt = _make_event(
            uuid.uuid4(),
            uuid.uuid4(),
            event_name="purchase",
            event_id="ga4-ord-5",
            user_data={"client_id": "GA1.2.123456789.1700000000"},
            custom_data={"value": 75.5, "currency": "EUR"},
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        forward_event(evt, dest, http_client=mock_client)

        body: dict = mock_client.post.call_args[1]["json"]
        assert body["client_id"] == "GA1.2.123456789.1700000000"
        ga4_event = body["events"][0]
        assert ga4_event["name"] == "purchase"
        params = ga4_event["params"]
        assert params["event_id"] == "ga4-ord-5"
        assert params["transaction_id"] == "ga4-ord-5"
        assert params["value"] == 75.5
        assert params["currency"] == "EUR"

    def test_missing_measurement_id_raises(self) -> None:
        dest = _make_dest_obj(
            "ga4_mp",
            {"_secrets": {"api_secret": "s"}},
        )
        evt = _make_event(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(RuntimeError, match="measurement_id"):
            forward_event(evt, dest, http_client=MagicMock())

    def test_unknown_platform_raises(self) -> None:
        dest = _make_dest_obj("unknown_platform", {})
        evt = _make_event(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(ValueError, match="Unknown platform"):
            forward_event(evt, dest, http_client=MagicMock())


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Public collect endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestPublicCollect:
    def test_happy_path_no_destinations(self, client: TestClient, db_session: Session) -> None:
        # Create a source first via the API
        create_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "My Site"},
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["public_token"]

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "pub-ord-001",
            "user_data": {"email": "shopper@test.com"},
            "custom_data": {"value": 50.0, "currency": "TRY"},
            "consent": True,
        }
        resp = client.post(f"/api/v1/tracking/collect/{token}", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["event_id"] == "pub-ord-001"
        # No destinations → "received"
        assert body["status"] == "received"

    def test_unknown_token_returns_404(self, client: TestClient) -> None:
        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "x",
            "user_data": {},
            "custom_data": {},
            "consent": False,
        }
        resp = client.post("/api/v1/tracking/collect/UNKNOWN_TOKEN_XYZ", json=payload)
        assert resp.status_code == 404

    def test_inactive_source_returns_404(self, client: TestClient, db_session: Session) -> None:
        create_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Inactive Source"},
        )
        assert create_resp.status_code == 201
        data = create_resp.json()
        token = data["public_token"]
        source_id = data["id"]

        # Deactivate
        patch_resp = client.patch(
            f"/api/v1/tracking/sources/{source_id}",
            json={"is_active": False},
        )
        assert patch_resp.status_code == 200

        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "inactive-001",
            "user_data": {},
            "custom_data": {},
            "consent": False,
        }
        resp = client.post(f"/api/v1/tracking/collect/{token}", json=payload)
        assert resp.status_code == 404

    def test_dedup_via_collect(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Dedup Test"},
        )
        token = create_resp.json()["public_token"]

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "dedup-via-api-001",
            "user_data": {},
            "custom_data": {},
            "consent": False,
        }
        r1 = client.post(f"/api/v1/tracking/collect/{token}", json=payload)
        r2 = client.post(f"/api/v1/tracking/collect/{token}", json=payload)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["status"] == "duplicate"

    def test_missing_fields_returns_422(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "422 Test"},
        )
        token = create_resp.json()["public_token"]

        # Missing event_id
        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
        }
        resp = client.post(f"/api/v1/tracking/collect/{token}", json=payload)
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TrackingSource CRUD + tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrackingSourceCRUD:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/tracking/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "E-commerce Site", "domain": "shop.example.com"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "E-commerce Site"
        assert body["domain"] == "shop.example.com"
        assert body["is_active"] is True
        assert len(body["public_token"]) > 0

    def test_get(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "GetTest"},
        )
        src_id = create.json()["id"]
        resp = client.get(f"/api/v1/tracking/sources/{src_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == src_id

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/tracking/sources/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patch(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Old Name"},
        )
        src_id = create.json()["id"]
        resp = client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"name": "New Name", "is_active": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "New Name"
        assert body["is_active"] is False

    def test_delete(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "ToDelete"},
        )
        src_id = create.json()["id"]
        del_resp = client.delete(f"/api/v1/tracking/sources/{src_id}")
        assert del_resp.status_code == 204
        get_resp = client.get(f"/api/v1/tracking/sources/{src_id}")
        assert get_resp.status_code == 404

    def test_list_returns_only_tenant_sources(
        self, db_session: Session, client: TestClient
    ) -> None:
        """Sources created by another tenant must not appear in the list."""
        # Create a source under a different tenant directly in DB
        other_tenant_id = uuid.uuid4()
        other_src = TrackingSource(
            tenant_id=other_tenant_id,
            name="Other Tenant Source",
            public_token="other-tok-xyz",
            is_active=True,
        )
        db_session.add(other_src)
        db_session.commit()

        # List via the API (client's tenant)
        resp = client.get("/api/v1/tracking/sources")
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()]
        assert "Other Tenant Source" not in names

    def test_public_token_unique_per_source(self, client: TestClient) -> None:
        r1 = client.post("/api/v1/tracking/sources", json={"name": "S1"})
        r2 = client.post("/api/v1/tracking/sources", json={"name": "S2"})
        assert r1.json()["public_token"] != r2.json()["public_token"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. EventDestination CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventDestinationCRUD:
    def _create_source(self, client: TestClient) -> str:
        resp = client.post("/api/v1/tracking/sources", json={"name": "Dest CRUD Src"})
        return resp.json()["id"]

    def test_create_meta_capi(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={
                "platform": "meta_capi",
                "config": {"pixel_id": "123456"},
                "vault_secret_ref": "secret/tenants/t1/meta",
                "consent_required": True,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["platform"] == "meta_capi"
        assert body["config"]["pixel_id"] == "123456"
        assert body["consent_required"] is True
        # _secrets must not be exposed
        assert "_secrets" not in body["config"]

    def test_create_invalid_platform(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "invalid_platform", "config": {}},
        )
        assert resp.status_code == 422

    def test_list_destinations(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "ga4_mp", "config": {"measurement_id": "G-TEST"}},
        )
        resp = client.get(f"/api/v1/tracking/sources/{src_id}/destinations")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_destination(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        create = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "tiktok_events", "config": {"pixel_id": "TKTOK"}},
        )
        dest_id = create.json()["id"]
        resp = client.get(f"/api/v1/tracking/destinations/{dest_id}")
        assert resp.status_code == 200
        assert resp.json()["platform"] == "tiktok_events"

    def test_patch_destination(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        create = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "meta_capi", "config": {"pixel_id": "OLD"}},
        )
        dest_id = create.json()["id"]
        resp = client.patch(
            f"/api/v1/tracking/destinations/{dest_id}",
            json={"config": {"pixel_id": "NEW"}, "is_active": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["pixel_id"] == "NEW"
        assert body["is_active"] is False

    def test_delete_destination(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        create = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "ga4_mp", "config": {"measurement_id": "G-DEL"}},
        )
        dest_id = create.json()["id"]
        del_resp = client.delete(f"/api/v1/tracking/destinations/{dest_id}")
        assert del_resp.status_code == 204
        get_resp = client.get(f"/api/v1/tracking/destinations/{dest_id}")
        assert get_resp.status_code == 404

    def test_destination_not_found_other_tenant(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Destinations belonging to another tenant return 404."""
        other_tenant_id = uuid.uuid4()
        other_src = TrackingSource(
            tenant_id=other_tenant_id,
            name="Other",
            public_token="other-tok-1",
            is_active=True,
        )
        db_session.add(other_src)
        db_session.commit()
        other_dest = EventDestination(
            tenant_id=other_tenant_id,
            tracking_source_id=other_src.id,
            platform="meta_capi",
            config={"pixel_id": "HIDDEN"},
            vault_secret_ref="",
            consent_required=True,
            is_active=True,
        )
        db_session.add(other_dest)
        db_session.commit()

        resp = client.get(f"/api/v1/tracking/destinations/{other_dest.id}")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Snippet endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestSnippet:
    def test_snippet_contains_collect_url(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Snippet Test"},
        )
        src_id = create.json()["id"]
        token = create.json()["public_token"]

        resp = client.get(f"/api/v1/tracking/sources/{src_id}/snippet")
        assert resp.status_code == 200
        body = resp.json()
        assert token in body["collect_url"]
        assert "/tracking/collect/" in body["collect_url"]

    def test_snippet_contains_js(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "JS Snippet Test"},
        )
        src_id = create.json()["id"]

        resp = client.get(f"/api/v1/tracking/sources/{src_id}/snippet")
        body = resp.json()
        assert "<script>" in body["js_snippet"]
        assert "fetch" in body["js_snippet"]
        assert "PageView" in body["js_snippet"]

    def test_snippet_not_found_other_tenant(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_src = TrackingSource(
            tenant_id=uuid.uuid4(),
            name="Hidden",
            public_token="hidden-tok-snip",
            is_active=True,
        )
        db_session.add(other_src)
        db_session.commit()

        resp = client.get(f"/api/v1/tracking/sources/{other_src.id}/snippet")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Event log endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventLog:
    def test_event_log_empty(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Log Test"},
        )
        src_id = create.json()["id"]
        resp = client.get(f"/api/v1/tracking/sources/{src_id}/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_event_log_after_collect(self, client: TestClient) -> None:
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Log Collect Test"},
        )
        src_id = create.json()["id"]
        token = create.json()["public_token"]

        client.post(
            f"/api/v1/tracking/collect/{token}",
            json={
                "event_name": "ViewContent",
                "event_time": "2026-06-26T12:00:00Z",
                "event_id": "log-evt-001",
                "user_data": {},
                "custom_data": {},
                "consent": False,
            },
        )

        resp = client.get(f"/api/v1/tracking/sources/{src_id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event_name"] == "ViewContent"
        assert events[0]["event_id"] == "log-evt-001"
        # user_data should have no raw PII
        assert "email" not in events[0]["user_data"]

    def test_event_log_tenant_isolation(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Event log for another tenant's source returns 404."""
        other_src = TrackingSource(
            tenant_id=uuid.uuid4(),
            name="Other Tenant Src",
            public_token="other-tok-evts",
            is_active=True,
        )
        db_session.add(other_src)
        db_session.commit()

        resp = client.get(f"/api/v1/tracking/sources/{other_src.id}/events")
        assert resp.status_code == 404
