"""Consent Mode v2 / granular KVKK consent tests — M7 migration 0019.

Strategy
--------
* FastAPI TestClient with in-memory SQLite (same pattern as test_tracking.py).
* No live network calls — httpx.Client mocked in forwarding tests.
* All tests are ADDITIVE; existing tracking tests pass unchanged.

Coverage
--------
1. normalize_consent — boolean expands correctly; granular dict; missing keys default to False.
2. Backward compat — plain consent:true/false behaves exactly as before.
3. Granular consent stored — consent_signals persisted correctly.
4. Per-destination satisfaction — ad_user_data required: skipped when only analytics_storage;
   forwarded when ad_user_data granted.
5. Platform defaults — required_consent=None/empty applies per-platform default.
6. consent_cookie_var in snippet — appears when set; absent when not set.
7. Endpoint: PATCH destination required_consent — updates and returns correctly.
8. Endpoint: PATCH source consent_cookie_var — updates and returns correctly.
9. Tenant isolation — cannot read/write another tenant's source or destination.
10. GCS passthrough — GA4 URL includes gcs param when consent_signals present.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules so Base.metadata includes all tables
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
    normalize_consent,
    ingest_event,
    forward_event,
    _is_consent_satisfied,
    _destination_required_signals,
    _sha256,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Consent Mode Test App")
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
        name="Consent Mode Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="consent_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Consent Test User",
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
        consent_cookie_var=kwargs.get("consent_cookie_var", None),
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
    required_consent: list | None = None,
    **kwargs: Any,
) -> EventDestination:
    dest = EventDestination(
        tenant_id=tenant_id,
        tracking_source_id=source_id,
        platform=platform,
        config=config or {"pixel_id": "TEST_PIXEL", "_secrets": {"access_token": "tok-test"}},
        vault_secret_ref="",
        consent_required=consent_required,
        required_consent=required_consent,
        is_active=kwargs.get("is_active", True),
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return dest


def _mock_http_client():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    return mock_client


# ═══════════════════════════════════════════════════════════════════════════════
# 1. normalize_consent
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeConsent:
    def test_true_expands_all_signals_granted(self) -> None:
        overall, signals = normalize_consent(True)
        assert overall is True
        assert signals == {
            "ad_storage": True,
            "ad_user_data": True,
            "ad_personalization": True,
            "analytics_storage": True,
        }

    def test_false_expands_all_signals_denied(self) -> None:
        overall, signals = normalize_consent(False)
        assert overall is False
        assert signals == {
            "ad_storage": False,
            "ad_user_data": False,
            "ad_personalization": False,
            "analytics_storage": False,
        }

    def test_granular_only_ad_user_data(self) -> None:
        overall, signals = normalize_consent({"ad_user_data": True})
        assert signals["ad_user_data"] is True
        assert signals["ad_storage"] is False
        assert signals["ad_personalization"] is False
        assert signals["analytics_storage"] is False
        # overall = ad_user_data OR analytics_storage
        assert overall is True

    def test_granular_only_analytics_storage(self) -> None:
        overall, signals = normalize_consent({"analytics_storage": True})
        assert signals["analytics_storage"] is True
        assert signals["ad_user_data"] is False
        assert overall is True

    def test_granular_neither_relevant_signal(self) -> None:
        # only ad_storage and ad_personalization granted — neither drives overall
        overall, signals = normalize_consent(
            {"ad_storage": True, "ad_personalization": True}
        )
        assert overall is False
        assert signals["ad_storage"] is True
        assert signals["ad_user_data"] is False

    def test_granular_all_four(self) -> None:
        overall, signals = normalize_consent(
            {
                "ad_storage": True,
                "ad_user_data": True,
                "ad_personalization": True,
                "analytics_storage": True,
            }
        )
        assert overall is True
        assert all(signals.values())

    def test_granular_empty_dict(self) -> None:
        overall, signals = normalize_consent({})
        assert overall is False
        assert all(not v for v in signals.values())

    def test_missing_keys_default_false(self) -> None:
        # Only ad_user_data provided; other three should be False
        _, signals = normalize_consent({"ad_user_data": True})
        assert len(signals) == 4
        assert signals["ad_storage"] is False
        assert signals["ad_personalization"] is False

    def test_truthy_value_coerced_to_bool(self) -> None:
        # Non-bool truthy value in dict
        overall, signals = normalize_consent({"ad_user_data": 1})
        assert signals["ad_user_data"] is True

    def test_falsy_value_coerced_to_bool(self) -> None:
        overall, signals = normalize_consent({"ad_user_data": 0})
        assert signals["ad_user_data"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Backward compatibility — plain boolean consent
# ═══════════════════════════════════════════════════════════════════════════════


class TestBooleanConsentBackwardCompat:
    """A plain consent:true/false must behave EXACTLY as before migration 0019."""

    def test_consent_true_with_consent_required_dest_forwards(
        self, db_session: Session
    ) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            config={"pixel_id": "PIX", "_secrets": {"access_token": "tok"}},
            consent_required=True,
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "back-compat-001",
            "user_data": {},
            "custom_data": {},
            "consent": True,  # plain boolean
        }

        mock_client = _mock_http_client()
        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        assert event.status == "forwarded"
        assert event.forwarded_count == 1
        assert event.consent is True

    def test_consent_false_with_consent_required_dest_skipped(
        self, db_session: Session
    ) -> None:
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
            "event_id": "back-compat-002",
            "user_data": {},
            "custom_data": {},
            "consent": False,  # plain boolean — no consent
        }

        event = ingest_event(db_session, src, payload)
        assert event.status == "skipped_no_consent"
        assert event.forwarded_count == 0
        assert event.consent is False

    def test_consent_false_dest_not_required_still_forwards(
        self, db_session: Session
    ) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="ga4_mp",
            config={"measurement_id": "G-TEST", "_secrets": {"api_secret": "sec"}},
            consent_required=False,  # no consent required
        )

        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "back-compat-003",
            "user_data": {},
            "custom_data": {},
            "consent": False,
        }

        mock_client = _mock_http_client()
        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        assert event.status == "forwarded"
        assert event.forwarded_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Granular consent signals stored in DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestConsentSignalsStored:
    def test_boolean_true_stores_all_granted(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "sig-store-001",
            "user_data": {},
            "custom_data": {},
            "consent": True,
        }
        event = ingest_event(db_session, src, payload)

        assert event.consent_signals is not None
        assert event.consent_signals["ad_user_data"] is True
        assert event.consent_signals["analytics_storage"] is True
        assert event.consent_signals["ad_storage"] is True
        assert event.consent_signals["ad_personalization"] is True

    def test_boolean_false_stores_all_denied(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "sig-store-002",
            "user_data": {},
            "custom_data": {},
            "consent": False,
        }
        event = ingest_event(db_session, src, payload)

        assert event.consent_signals is not None
        assert all(not v for v in event.consent_signals.values())

    def test_granular_dict_stored_correctly(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Subscribe",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "sig-store-003",
            "user_data": {},
            "custom_data": {},
            "consent": {
                "ad_user_data": True,
                "analytics_storage": True,
                "ad_storage": False,
                "ad_personalization": False,
            },
        }
        event = ingest_event(db_session, src, payload)

        assert event.consent_signals["ad_user_data"] is True
        assert event.consent_signals["analytics_storage"] is True
        assert event.consent_signals["ad_storage"] is False
        assert event.consent_signals["ad_personalization"] is False
        # overall consent = True (ad_user_data OR analytics_storage)
        assert event.consent is True

    def test_partial_granular_stored_with_defaults(self, db_session: Session) -> None:
        """Missing keys in granular dict default to False in the stored signals."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        payload = {
            "event_name": "Lead",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "sig-store-004",
            "user_data": {},
            "custom_data": {},
            "consent": {"analytics_storage": True},  # only analytics
        }
        event = ingest_event(db_session, src, payload)

        assert event.consent_signals["analytics_storage"] is True
        assert event.consent_signals["ad_user_data"] is False
        assert event.consent_signals["ad_storage"] is False
        assert event.consent_signals["ad_personalization"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Per-destination granular consent satisfaction
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerDestinationConsentSatisfaction:
    def test_ad_user_data_required_skipped_when_only_analytics_granted(
        self, db_session: Session
    ) -> None:
        """meta_capi requires ad_user_data; only analytics_storage granted → skip."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            config={"pixel_id": "P1", "_secrets": {"access_token": "tok"}},
            consent_required=True,
            required_consent=["ad_user_data"],
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "per-dest-001",
            "user_data": {},
            "custom_data": {},
            "consent": {"analytics_storage": True},  # ad_user_data NOT granted
        }
        event = ingest_event(db_session, src, payload)
        assert event.status == "skipped_no_consent"
        assert event.forwarded_count == 0

    def test_ad_user_data_required_forwarded_when_granted(
        self, db_session: Session
    ) -> None:
        """meta_capi requires ad_user_data; ad_user_data granted → forward."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            config={"pixel_id": "P2", "_secrets": {"access_token": "tok"}},
            consent_required=True,
            required_consent=["ad_user_data"],
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "per-dest-002",
            "user_data": {},
            "custom_data": {},
            "consent": {"ad_user_data": True},
        }

        mock_client = _mock_http_client()
        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        assert event.status == "forwarded"
        assert event.forwarded_count == 1

    def test_analytics_storage_required_skipped_when_only_ad_user_data_granted(
        self, db_session: Session
    ) -> None:
        """ga4_mp requires analytics_storage; only ad_user_data granted → skip."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="ga4_mp",
            config={"measurement_id": "G-TEST", "_secrets": {"api_secret": "sec"}},
            consent_required=True,
            required_consent=["analytics_storage"],
        )

        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "per-dest-003",
            "user_data": {},
            "custom_data": {},
            "consent": {"ad_user_data": True},  # analytics_storage NOT granted
        }
        event = ingest_event(db_session, src, payload)
        assert event.status == "skipped_no_consent"

    def test_multi_destination_partial_satisfaction(
        self, db_session: Session
    ) -> None:
        """Two destinations: one satisfied (ga4), one not (meta → ad_user_data).
        Aggregate: forwarded (not skipped) because at least one dest is satisfied."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)

        # meta_capi requires ad_user_data
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            config={"pixel_id": "P3", "_secrets": {"access_token": "tok"}},
            consent_required=True,
            required_consent=["ad_user_data"],
        )

        # ga4_mp requires analytics_storage
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="ga4_mp",
            config={"measurement_id": "G-T2", "_secrets": {"api_secret": "s"}},
            consent_required=True,
            required_consent=["analytics_storage"],
        )

        # Only analytics_storage granted → meta skipped, ga4 forwarded
        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "per-dest-004",
            "user_data": {},
            "custom_data": {},
            "consent": {"analytics_storage": True},
        }

        mock_client = _mock_http_client()
        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        # forwarded to ga4 only (1 dest satisfied)
        assert event.status == "forwarded"
        assert event.forwarded_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Platform defaults applied when required_consent is None/empty
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlatformDefaults:
    def test_meta_capi_default_is_ad_user_data(self, db_session: Session) -> None:
        """meta_capi with required_consent=None → default ["ad_user_data"]."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        dest = _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            consent_required=True,
            required_consent=None,  # no explicit — use platform default
        )
        required = _destination_required_signals(dest)
        assert required == ["ad_user_data"]

    def test_tiktok_events_default_is_ad_user_data(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        dest = _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="tiktok_events",
            config={"pixel_id": "TT_PIX", "_secrets": {"access_token": "tok"}},
            consent_required=True,
            required_consent=None,
        )
        required = _destination_required_signals(dest)
        assert required == ["ad_user_data"]

    def test_ga4_mp_default_is_analytics_storage(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        dest = _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="ga4_mp",
            config={"measurement_id": "G-X", "_secrets": {"api_secret": "s"}},
            consent_required=True,
            required_consent=None,
        )
        required = _destination_required_signals(dest)
        assert required == ["analytics_storage"]

    def test_meta_capi_default_skips_analytics_only_consent(
        self, db_session: Session
    ) -> None:
        """meta_capi with required_consent=None: analytics_storage only → skipped."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="meta_capi",
            config={"pixel_id": "DEF_PIX", "_secrets": {"access_token": "tok"}},
            consent_required=True,
            required_consent=None,
        )

        payload = {
            "event_name": "Purchase",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "default-001",
            "user_data": {},
            "custom_data": {},
            "consent": {"analytics_storage": True},  # only analytics — no ad_user_data
        }
        event = ingest_event(db_session, src, payload)
        assert event.status == "skipped_no_consent"

    def test_ga4_mp_default_forwarded_when_analytics_storage_granted(
        self, db_session: Session
    ) -> None:
        """ga4_mp with required_consent=None: analytics_storage granted → forwarded."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        _make_destination(
            db_session,
            tenant_id,
            src.id,
            platform="ga4_mp",
            config={"measurement_id": "G-DEF", "_secrets": {"api_secret": "s"}},
            consent_required=True,
            required_consent=None,
        )

        payload = {
            "event_name": "PageView",
            "event_time": "2026-06-26T10:00:00Z",
            "event_id": "default-002",
            "user_data": {},
            "custom_data": {},
            "consent": {"analytics_storage": True},
        }

        mock_client = _mock_http_client()
        with patch("ayaz.services.tracking.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_client
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            event = ingest_event(db_session, src, payload)

        assert event.status == "forwarded"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. consent_cookie_var in snippet
# ═══════════════════════════════════════════════════════════════════════════════


class TestConsentCookieVarSnippet:
    def test_snippet_contains_cookie_var_when_set(self, client: TestClient) -> None:
        """When consent_cookie_var is set, snippet reads window[varName]."""
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Cookie Var Site"},
        )
        assert create.status_code == 201
        src_id = create.json()["id"]

        # Set consent_cookie_var via PATCH
        patch_resp = client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": "ayazConsent"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["consent_cookie_var"] == "ayazConsent"

        # Get snippet
        snippet_resp = client.get(f"/api/v1/tracking/sources/{src_id}/snippet")
        assert snippet_resp.status_code == 200
        js = snippet_resp.json()["js_snippet"]

        # The snippet must read the window variable
        assert "ayazConsent" in js
        assert "window['ayazConsent']" in js
        assert "_ayazConsent" in js
        # consent field must use the variable, not a hardcoded false
        assert "consent: _ayazConsent" in js

    def test_snippet_has_static_false_when_no_cookie_var(
        self, client: TestClient
    ) -> None:
        """Without consent_cookie_var, snippet has consent: false (existing behaviour)."""
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "No Cookie Var Site"},
        )
        src_id = create.json()["id"]

        snippet_resp = client.get(f"/api/v1/tracking/sources/{src_id}/snippet")
        js = snippet_resp.json()["js_snippet"]

        assert "consent: _ayazConsent" in js
        # _ayazConsent should be assigned to false when no var
        assert "_ayazConsent = false" in js

    def test_snippet_cookie_var_cleared_to_none(self, client: TestClient) -> None:
        """Setting consent_cookie_var to null clears it; snippet returns to static false."""
        create = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Clear Cookie Var"},
        )
        src_id = create.json()["id"]

        client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": "someVar"},
        )
        clear_resp = client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": None},
        )
        assert clear_resp.status_code == 200
        assert clear_resp.json()["consent_cookie_var"] is None

        snippet_resp = client.get(f"/api/v1/tracking/sources/{src_id}/snippet")
        js = snippet_resp.json()["js_snippet"]
        assert "_ayazConsent = false" in js


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Endpoint: PATCH destination required_consent
# ═══════════════════════════════════════════════════════════════════════════════


class TestPatchDestinationRequiredConsent:
    def test_patch_required_consent_updates_correctly(
        self, client: TestClient
    ) -> None:
        """PATCH destination with required_consent list — returned in response."""
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Dest Consent Test"},
        )
        src_id = src_resp.json()["id"]

        dest_resp = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={
                "platform": "meta_capi",
                "config": {"pixel_id": "PATCH_PIX"},
                "consent_required": True,
            },
        )
        assert dest_resp.status_code == 201
        dest_id = dest_resp.json()["id"]
        assert dest_resp.json()["required_consent"] is None

        # Patch with explicit required_consent
        patch_resp = client.patch(
            f"/api/v1/tracking/destinations/{dest_id}",
            json={"required_consent": ["ad_user_data", "analytics_storage"]},
        )
        assert patch_resp.status_code == 200
        body = patch_resp.json()
        assert set(body["required_consent"]) == {"ad_user_data", "analytics_storage"}

    def test_patch_required_consent_invalid_key_returns_422(
        self, client: TestClient
    ) -> None:
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Invalid Key Test"},
        )
        src_id = src_resp.json()["id"]
        dest_resp = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={"platform": "ga4_mp", "config": {"measurement_id": "G-X"}},
        )
        dest_id = dest_resp.json()["id"]

        patch_resp = client.patch(
            f"/api/v1/tracking/destinations/{dest_id}",
            json={"required_consent": ["not_a_real_signal"]},
        )
        assert patch_resp.status_code == 422

    def test_patch_required_consent_cleared_to_platform_default(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Patching with empty list clears required_consent (platform default applies at runtime)."""
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Clear Required Consent"},
        )
        src_id = src_resp.json()["id"]
        dest_resp = client.post(
            f"/api/v1/tracking/sources/{src_id}/destinations",
            json={
                "platform": "meta_capi",
                "config": {"pixel_id": "CLR_PIX"},
                "required_consent": ["ad_user_data"],
            },
        )
        dest_id = dest_resp.json()["id"]
        assert dest_resp.json()["required_consent"] == ["ad_user_data"]

        # Clear by patching with empty list
        patch_resp = client.patch(
            f"/api/v1/tracking/destinations/{dest_id}",
            json={"required_consent": []},
        )
        assert patch_resp.status_code == 200
        # Empty list → stored as None
        assert patch_resp.json()["required_consent"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Endpoint: PATCH source consent_cookie_var
# ═══════════════════════════════════════════════════════════════════════════════


class TestPatchSourceConsentCookieVar:
    def test_set_consent_cookie_var(self, client: TestClient) -> None:
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Cookie Var Test"},
        )
        src_id = src_resp.json()["id"]
        assert src_resp.json().get("consent_cookie_var") is None

        patch_resp = client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": "myConsentVar"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["consent_cookie_var"] == "myConsentVar"

    def test_get_source_returns_consent_cookie_var(self, client: TestClient) -> None:
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Get Cookie Var"},
        )
        src_id = src_resp.json()["id"]

        client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": "readBack"},
        )

        get_resp = client.get(f"/api/v1/tracking/sources/{src_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["consent_cookie_var"] == "readBack"

    def test_other_patch_fields_dont_clear_cookie_var(
        self, client: TestClient
    ) -> None:
        """Patching name only must not reset consent_cookie_var."""
        src_resp = client.post(
            "/api/v1/tracking/sources",
            json={"name": "Isolation Test"},
        )
        src_id = src_resp.json()["id"]
        client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"consent_cookie_var": "sticky"},
        )

        # Now patch only the name
        patch_resp = client.patch(
            f"/api/v1/tracking/sources/{src_id}",
            json={"name": "New Name"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["consent_cookie_var"] == "sticky"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_cannot_read_other_tenant_source(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id, name="Other")
        resp = client.get(f"/api/v1/tracking/sources/{other_src.id}")
        assert resp.status_code == 404

    def test_cannot_patch_other_tenant_source(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id)
        resp = client.patch(
            f"/api/v1/tracking/sources/{other_src.id}",
            json={"consent_cookie_var": "injected"},
        )
        assert resp.status_code == 404

    def test_cannot_read_other_tenant_destination(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id)
        other_dest = _make_destination(db_session, other_tenant_id, other_src.id)
        resp = client.get(f"/api/v1/tracking/destinations/{other_dest.id}")
        assert resp.status_code == 404

    def test_cannot_patch_other_tenant_destination(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id)
        other_dest = _make_destination(db_session, other_tenant_id, other_src.id)
        resp = client.patch(
            f"/api/v1/tracking/destinations/{other_dest.id}",
            json={"required_consent": ["ad_user_data"]},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 10. GCS passthrough in GA4 forward
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeEventWithSignals:
    """Minimal stand-in for ConversionEvent with consent_signals."""
    def __init__(self, *, consent_signals: dict | None = None) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.tracking_source_id = uuid.uuid4()
        self.event_name = "purchase"
        self.event_id = "gcs-test-001"
        self.event_time = "2026-06-26T10:00:00Z"
        self.user_data = {}
        self.custom_data = {"value": 10.0}
        self.consent = True
        self.consent_signals = consent_signals
        self.status = "received"
        self.forwarded_count = 0
        self.error = None
        self.created_at = "2026-06-26T10:00:00+00:00"


class _FakeGa4Dest:
    """Minimal stand-in for EventDestination (ga4_mp)."""
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.tracking_source_id = uuid.uuid4()
        self.platform = "ga4_mp"
        self.config = {
            "measurement_id": "G-GCS123",
            "_secrets": {"api_secret": "gcs-sec"},
        }
        self.vault_secret_ref = ""
        self.consent_required = True
        self.required_consent = None
        self.is_active = True


class TestGa4GcsPassthrough:
    def test_gcs_g111_when_both_granted(self) -> None:
        """Both ad_storage and analytics_storage granted → gcs=G111 in URL."""
        evt = _FakeEventWithSignals(
            consent_signals={
                "ad_storage": True,
                "ad_user_data": True,
                "ad_personalization": True,
                "analytics_storage": True,
            }
        )
        dest = _FakeGa4Dest()
        mock_client = _mock_http_client()

        forward_event(evt, dest, http_client=mock_client)

        url: str = mock_client.post.call_args[0][0]
        assert "gcs=G111" in url

    def test_gcs_g101_when_analytics_only(self) -> None:
        """analytics_storage granted, ad_storage denied → gcs=G101."""
        evt = _FakeEventWithSignals(
            consent_signals={
                "ad_storage": False,
                "ad_user_data": False,
                "ad_personalization": False,
                "analytics_storage": True,
            }
        )
        dest = _FakeGa4Dest()
        mock_client = _mock_http_client()

        forward_event(evt, dest, http_client=mock_client)

        url: str = mock_client.post.call_args[0][0]
        assert "gcs=G101" in url

    def test_gcs_g100_when_both_denied(self) -> None:
        """Both denied → gcs=G100."""
        evt = _FakeEventWithSignals(
            consent_signals={
                "ad_storage": False,
                "ad_user_data": False,
                "ad_personalization": False,
                "analytics_storage": False,
            }
        )
        dest = _FakeGa4Dest()
        mock_client = _mock_http_client()

        forward_event(evt, dest, http_client=mock_client)

        url: str = mock_client.post.call_args[0][0]
        assert "gcs=G100" in url

    def test_no_gcs_when_consent_signals_none(self) -> None:
        """Legacy event with consent_signals=None → no gcs param in URL."""
        evt = _FakeEventWithSignals(consent_signals=None)
        dest = _FakeGa4Dest()
        mock_client = _mock_http_client()

        forward_event(evt, dest, http_client=mock_client)

        url: str = mock_client.post.call_args[0][0]
        assert "gcs=" not in url

    def test_gcs_g110_when_ad_storage_only(self) -> None:
        """ad_storage granted, analytics_storage denied → gcs=G110."""
        evt = _FakeEventWithSignals(
            consent_signals={
                "ad_storage": True,
                "ad_user_data": False,
                "ad_personalization": False,
                "analytics_storage": False,
            }
        )
        dest = _FakeGa4Dest()
        mock_client = _mock_http_client()

        forward_event(evt, dest, http_client=mock_client)

        url: str = mock_client.post.call_args[0][0]
        assert "gcs=G110" in url
