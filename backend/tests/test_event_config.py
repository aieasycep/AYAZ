"""Tests for per-event enable/disable — M7 SignalSight Event Configuration.

Coverage
--------
1. POST /sources/{id}/event-config
   - toggle off: event_name added to disabled_events
   - toggle on:  event_name removed from disabled_events
   - idempotent: toggling same state twice is safe
   - 401 for unauthenticated requests
   - 404 for source belonging to another tenant

2. Ingest behaviour
   - disabled event is recorded (status="disabled", forwarded_count=0)
   - disabled event is NOT forwarded to destinations
   - re-enabling the event resumes forwarding (next new event is forwarded)

3. Stats by_event[].enabled
   - enabled=True for non-disabled event names
   - enabled=False for event names in disabled_events
   - works even for event names not yet seen in events (not present in by_event,
     so no assertion needed there; but for names that DO appear, flag is correct)

4. compute_tracking_stats — pure unit test for enabled flag
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
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
from ayaz.api.v1.tracking import compute_tracking_stats
from ayaz.services.auth import hash_password
from ayaz.services.tracking import ingest_event

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Event Config Test App")
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


# ── Client fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="EventConfig Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="event_config_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="EventConfig Test User",
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


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override (tests 401 behaviour)."""

    def override_db():
        try:
            yield db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_source(
    db: Session,
    tenant_id: uuid.UUID,
    disabled_events: list[str] | None = None,
    **kwargs: Any,
) -> TrackingSource:
    src = TrackingSource(
        tenant_id=tenant_id,
        name=kwargs.get("name", "EventConfig Test Source"),
        domain=kwargs.get("domain", None),
        public_token=kwargs.get("public_token", f"tok-{uuid.uuid4().hex}"),
        is_active=kwargs.get("is_active", True),
        disabled_events=disabled_events or [],
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_destination(
    db: Session,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    secrets: dict[str, str] | None = None,
) -> EventDestination:
    """Create a minimal meta_capi destination with injected secrets for tests."""
    config: dict[str, Any] = {"pixel_id": "TEST_PIXEL", "action_source": "website"}
    if secrets:
        config["_secrets"] = secrets
    dest = EventDestination(
        tenant_id=tenant_id,
        tracking_source_id=source_id,
        platform="meta_capi",
        config=config,
        vault_secret_ref="test-ref",
        consent_required=False,
        is_active=True,
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return dest


def _make_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    event_name: str = "Purchase",
    status: str = "forwarded",
    created_at: str,
    consent: bool = True,
    event_id: str | None = None,
) -> ConversionEvent:
    evt = ConversionEvent(
        tenant_id=tenant_id,
        tracking_source_id=source_id,
        event_name=event_name,
        event_time="2026-01-01T10:00:00Z",
        event_id=event_id or f"evt-{uuid.uuid4().hex}",
        user_data={},
        custom_data={},
        consent=consent,
        status=status,
        forwarded_count=1 if status == "forwarded" else 0,
        error=None,
        created_at=created_at,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return evt


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# 1. compute_tracking_stats — pure unit tests for `enabled` field
# ══════════════════════════════════════════════════════════════════════════════


class _FakeEvent:
    """Minimal ConversionEvent stand-in for pure unit tests."""

    def __init__(
        self,
        event_name: str = "Purchase",
        status: str = "forwarded",
        created_at: str = "2026-01-15T10:00:00+00:00",
    ) -> None:
        self.event_name = event_name
        self.status = status
        self.created_at = created_at


class TestComputeTrackingStatsEnabled:
    """Unit-test the enabled flag in compute_tracking_stats."""

    def _range(self) -> tuple[date, date]:
        return date(2026, 1, 10), date(2026, 1, 20)

    def test_no_disabled_events_all_enabled(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("AddToCart", "forwarded", "2026-01-12T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to, disabled_events=[])
        by_event = {e["event_name"]: e for e in result["by_event"]}
        assert by_event["Purchase"]["enabled"] is True
        assert by_event["AddToCart"]["enabled"] is True

    def test_disabled_event_has_enabled_false(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("AddToCart", "disabled", "2026-01-12T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(
            events, d_from, d_to, disabled_events=["AddToCart"]
        )
        by_event = {e["event_name"]: e for e in result["by_event"]}
        assert by_event["Purchase"]["enabled"] is True
        assert by_event["AddToCart"]["enabled"] is False

    def test_default_none_disabled_events_all_enabled(self) -> None:
        """When disabled_events is None (default), all events are enabled."""
        d_from, d_to = self._range()
        events = [_FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00")]
        result = compute_tracking_stats(events, d_from, d_to)
        assert result["by_event"][0]["enabled"] is True

    def test_multiple_disabled_events(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("A", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("B", "disabled", "2026-01-12T10:00:00+00:00"),
            _FakeEvent("C", "disabled", "2026-01-13T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(
            events, d_from, d_to, disabled_events=["B", "C"]
        )
        by_event = {e["event_name"]: e for e in result["by_event"]}
        assert by_event["A"]["enabled"] is True
        assert by_event["B"]["enabled"] is False
        assert by_event["C"]["enabled"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. POST /sources/{id}/event-config — toggle endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestEventConfigToggle:
    def test_disable_event_adds_to_disabled_events(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)
        assert src.disabled_events == []

        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Purchase" in body["disabled_events"]

        # Verify persisted in DB
        db_session.refresh(src)
        assert "Purchase" in src.disabled_events

    def test_enable_event_removes_from_disabled_events(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(
            db_session, membership.tenant_id, disabled_events=["Purchase", "AddToCart"]
        )

        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Purchase", "enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Purchase" not in body["disabled_events"]
        assert "AddToCart" in body["disabled_events"]

        db_session.refresh(src)
        assert "Purchase" not in src.disabled_events
        assert "AddToCart" in src.disabled_events

    def test_disable_already_disabled_is_idempotent(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(
            db_session, membership.tenant_id, disabled_events=["Purchase"]
        )

        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should appear exactly once
        assert body["disabled_events"].count("Purchase") == 1

    def test_enable_already_enabled_is_idempotent(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id, disabled_events=[])

        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Purchase", "enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Purchase" not in body["disabled_events"]

    def test_toggle_off_then_on(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)

        # Disable
        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Checkout", "enabled": False},
        )
        assert resp.status_code == 200
        assert "Checkout" in resp.json()["disabled_events"]

        # Re-enable
        resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Checkout", "enabled": True},
        )
        assert resp.status_code == 200
        assert "Checkout" not in resp.json()["disabled_events"]

    def test_unauthenticated_returns_401(self, unauth_client: TestClient) -> None:
        resp = unauth_client.post(
            f"/api/v1/tracking/sources/{uuid.uuid4()}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert resp.status_code in (401, 403)

    def test_other_tenant_source_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(
            db_session,
            other_tenant_id,
            public_token=f"other-{uuid.uuid4().hex}",
        )

        resp = client.post(
            f"/api/v1/tracking/sources/{other_src.id}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert resp.status_code == 404

    def test_unknown_source_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            f"/api/v1/tracking/sources/{uuid.uuid4()}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 3. Ingest behaviour — disabled event recorded, not forwarded
# ══════════════════════════════════════════════════════════════════════════════


class TestIngestDisabledEvent:
    """Test that disabled events are recorded with status='disabled' and never forwarded."""

    def _make_payload(self, event_name: str = "Purchase", event_id: str | None = None) -> dict:
        return {
            "event_name": event_name,
            "event_time": "2026-06-28T10:00:00Z",
            "event_id": event_id or f"test-{uuid.uuid4().hex}",
            "user_data": {},
            "custom_data": {},
            "consent": True,
        }

    def test_disabled_event_status_is_disabled(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(
            db_session, tenant_id, disabled_events=["Purchase"]
        )

        with patch("ayaz.services.tracking.forward_event") as mock_fwd:
            event = ingest_event(db_session, src, self._make_payload("Purchase"))

        assert event.status == "disabled"
        assert event.forwarded_count == 0
        mock_fwd.assert_not_called()

    def test_disabled_event_is_persisted(self, db_session: Session) -> None:
        """The event row IS written to the DB even when disabled."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id, disabled_events=["Purchase"])

        with patch("ayaz.services.tracking.forward_event"):
            event = ingest_event(db_session, src, self._make_payload("Purchase"))

        # Should be in DB
        db_session.refresh(event)
        assert event.id is not None
        assert event.event_name == "Purchase"
        assert event.status == "disabled"

    def test_non_disabled_event_is_forwarded(self, db_session: Session) -> None:
        """An event NOT in disabled_events is forwarded as before."""
        tenant_id = uuid.uuid4()
        src = _make_source(
            db_session, tenant_id, disabled_events=["AddToCart"]
        )
        # Add a destination so forwarding is attempted
        _make_destination(
            db_session, tenant_id, src.id,
            secrets={"access_token": "test-token"},
        )

        with patch("ayaz.services.tracking.forward_event") as mock_fwd:
            mock_fwd.return_value = None  # success
            event = ingest_event(db_session, src, self._make_payload("Purchase"))

        assert event.status == "forwarded"
        assert event.forwarded_count == 1
        mock_fwd.assert_called_once()

    def test_disabled_event_not_forwarded_even_with_destinations(
        self, db_session: Session
    ) -> None:
        """Destinations exist but disabled event must NOT be forwarded."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id, disabled_events=["Purchase"])
        # Add a destination — it should never be called
        _make_destination(
            db_session, tenant_id, src.id,
            secrets={"access_token": "test-token"},
        )

        with patch("ayaz.services.tracking.forward_event") as mock_fwd:
            event = ingest_event(db_session, src, self._make_payload("Purchase"))

        assert event.status == "disabled"
        assert event.forwarded_count == 0
        mock_fwd.assert_not_called()

    def test_re_enabling_resumes_forwarding(self, db_session: Session) -> None:
        """After re-enabling an event, the NEXT ingested event is forwarded."""
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id, disabled_events=["Purchase"])
        _make_destination(
            db_session, tenant_id, src.id,
            secrets={"access_token": "test-token"},
        )

        # First ingest: disabled
        with patch("ayaz.services.tracking.forward_event") as mock_fwd:
            evt1 = ingest_event(db_session, src, self._make_payload("Purchase", "id-1"))
        assert evt1.status == "disabled"
        mock_fwd.assert_not_called()

        # Re-enable Purchase
        src.disabled_events = []
        db_session.add(src)
        db_session.commit()
        db_session.refresh(src)

        # Second ingest: should be forwarded
        with patch("ayaz.services.tracking.forward_event") as mock_fwd2:
            mock_fwd2.return_value = None
            evt2 = ingest_event(db_session, src, self._make_payload("Purchase", "id-2"))
        assert evt2.status == "forwarded"
        assert evt2.forwarded_count == 1
        mock_fwd2.assert_called_once()

    def test_dedup_checked_before_disabled(self, db_session: Session) -> None:
        """Duplicate detection happens BEFORE the disabled check.

        A re-submitted event_id that was previously recorded as 'disabled'
        should come back as 'duplicate', not re-evaluate the disabled state.
        """
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id, disabled_events=["Purchase"])
        payload = self._make_payload("Purchase", "shared-id")

        # First ingest: disabled
        with patch("ayaz.services.tracking.forward_event"):
            evt1 = ingest_event(db_session, src, payload)
        assert evt1.status == "disabled"

        # Second ingest with same event_id: dedup wins → duplicate
        with patch("ayaz.services.tracking.forward_event") as mock_fwd:
            evt2 = ingest_event(db_session, src, payload)
        assert evt2.status == "duplicate"
        assert evt2.id == evt1.id
        mock_fwd.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Stats by_event[].enabled via HTTP
# ══════════════════════════════════════════════════════════════════════════════


class TestStatsByEventEnabled:
    def test_by_event_enabled_reflects_disabled_events(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        today = _today_iso()
        src = _make_source(
            db_session,
            membership.tenant_id,
            disabled_events=["AddToCart"],
        )
        _make_event(
            db_session,
            tenant_id=membership.tenant_id,
            source_id=src.id,
            event_name="Purchase",
            status="forwarded",
            created_at=f"{today}T10:00:00+00:00",
        )
        _make_event(
            db_session,
            tenant_id=membership.tenant_id,
            source_id=src.id,
            event_name="AddToCart",
            status="disabled",
            created_at=f"{today}T11:00:00+00:00",
        )

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        by_event = {e["event_name"]: e for e in resp.json()["by_event"]}

        assert by_event["Purchase"]["enabled"] is True
        assert by_event["AddToCart"]["enabled"] is False

    def test_by_event_all_enabled_when_no_disabled_events(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        today = _today_iso()
        src = _make_source(db_session, membership.tenant_id, disabled_events=[])
        _make_event(
            db_session,
            tenant_id=membership.tenant_id,
            source_id=src.id,
            event_name="Purchase",
            status="forwarded",
            created_at=f"{today}T10:00:00+00:00",
        )

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        by_event = resp.json()["by_event"]
        assert all(e["enabled"] is True for e in by_event)

    def test_enabled_field_updates_after_toggle(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Toggling a source's disabled_events is reflected in the next stats call."""
        membership = _test_app.dependency_overrides[get_current_membership]()
        today = _today_iso()
        src = _make_source(db_session, membership.tenant_id, disabled_events=[])
        _make_event(
            db_session,
            tenant_id=membership.tenant_id,
            source_id=src.id,
            event_name="Purchase",
            status="forwarded",
            created_at=f"{today}T10:00:00+00:00",
        )

        # Initially enabled
        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        by_event = {e["event_name"]: e for e in resp.json()["by_event"]}
        assert by_event["Purchase"]["enabled"] is True

        # Toggle off
        toggle_resp = client.post(
            f"/api/v1/tracking/sources/{src.id}/event-config",
            json={"event_name": "Purchase", "enabled": False},
        )
        assert toggle_resp.status_code == 200

        # Stats should now show enabled=False
        resp2 = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp2.status_code == 200
        by_event2 = {e["event_name"]: e for e in resp2.json()["by_event"]}
        assert by_event2["Purchase"]["enabled"] is False
