"""Tests for M7 tracking delivery-health stats + filterable event log.

Coverage
--------
1. compute_tracking_stats (pure unit tests — no HTTP)
   - totals: total_events, total_errors, by_status, consent_blocked
   - by_event: aggregation and descending-count sort
   - daily trend: zero-fill, ascending, correct counts
2. GET /sources/{source_id}/stats
   - happy path: date defaults + explicit date_from/date_to
   - date filtering: events outside range excluded
   - date_from > date_to returns 422
   - unauthenticated returns 401
   - other tenant's source returns 404
   - source with no events returns all-zero totals and zero-filled daily
3. GET /sources/{source_id}/events (filterable debug console)
   - filter by status
   - filter by event_name
   - combined filter
   - limit parameter
   - no filters → backward-compatible (all events, up to default limit)
   - auth required (401)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata.create_all works
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
from ayaz.models.tracking import ConversionEvent, TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import tracking as tracking_module
from ayaz.api.v1.tracking import compute_tracking_stats
from ayaz.services.auth import hash_password

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Tracking Stats Test App")
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
        name="Stats Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="stats_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Stats Test User",
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


# ── Unauthenticated client ────────────────────────────────────────────────────


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override (tests 401 behaviour)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()

    def override_db():
        try:
            yield session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(engine)


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


def _make_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    event_name: str = "Purchase",
    status: str = "forwarded",
    created_at: str,  # "YYYY-MM-DDTHH:MM:SS+00:00"
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
        error="oops" if status == "failed" else None,
        created_at=created_at,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return evt


# ── Helpers for building fake ConversionEvent-like objects for pure unit tests ─


class _FakeEvent:
    """Minimal stand-in for ConversionEvent for pure aggregation unit tests."""

    def __init__(
        self,
        event_name: str = "Purchase",
        status: str = "forwarded",
        created_at: str = "2026-01-15T10:00:00+00:00",
        consent: bool = True,
    ) -> None:
        self.event_name = event_name
        self.status = status
        self.created_at = created_at
        self.consent = consent


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compute_tracking_stats — pure unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeTrackingStats:
    """Unit-test the pure aggregation helper with fake event objects."""

    def _range(self) -> tuple[date, date]:
        return date(2026, 1, 10), date(2026, 1, 20)

    def test_empty_events(self) -> None:
        d_from, d_to = self._range()
        result = compute_tracking_stats([], d_from, d_to)
        assert result["totals"]["total_events"] == 0
        assert result["totals"]["total_errors"] == 0
        assert result["totals"]["consent_blocked"] == 0
        assert result["totals"]["by_status"] == {}
        assert result["by_event"] == []
        # daily should still be zero-filled for 11 days
        assert len(result["daily"]) == 11
        for day in result["daily"]:
            assert day["count"] == 0
            assert day["errors"] == 0

    def test_totals_correct(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("Purchase", "forwarded", "2026-01-12T10:00:00+00:00"),
            _FakeEvent("AddToCart", "failed", "2026-01-13T10:00:00+00:00"),
            _FakeEvent("Purchase", "skipped_no_consent", "2026-01-14T10:00:00+00:00", consent=False),
            _FakeEvent("PageView", "received", "2026-01-15T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        totals = result["totals"]
        assert totals["total_events"] == 5
        assert totals["total_errors"] == 1          # only "failed"
        assert totals["consent_blocked"] == 1       # only "skipped_no_consent"
        assert totals["by_status"]["forwarded"] == 2
        assert totals["by_status"]["failed"] == 1
        assert totals["by_status"]["skipped_no_consent"] == 1
        assert totals["by_status"]["received"] == 1

    def test_by_event_sorted_desc_by_count(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("Purchase", "forwarded", "2026-01-12T10:00:00+00:00"),
            _FakeEvent("Purchase", "forwarded", "2026-01-13T10:00:00+00:00"),
            _FakeEvent("AddToCart", "forwarded", "2026-01-14T10:00:00+00:00"),
            _FakeEvent("AddToCart", "failed", "2026-01-15T10:00:00+00:00"),
            _FakeEvent("PageView", "forwarded", "2026-01-15T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        names = [e["event_name"] for e in result["by_event"]]
        counts = [e["count"] for e in result["by_event"]]
        assert names[0] == "Purchase"
        assert counts == sorted(counts, reverse=True)

    def test_by_event_errors_correctly_mapped(self) -> None:
        d_from, d_to = self._range()
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("Purchase", "failed", "2026-01-12T10:00:00+00:00"),
            _FakeEvent("AddToCart", "failed", "2026-01-13T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        by_event = {e["event_name"]: e for e in result["by_event"]}
        assert by_event["Purchase"]["errors"] == 1
        assert by_event["AddToCart"]["errors"] == 1

    def test_daily_zero_filled_ascending(self) -> None:
        d_from, d_to = date(2026, 1, 10), date(2026, 1, 12)
        events = [
            _FakeEvent("Purchase", "forwarded", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("Purchase", "failed", "2026-01-11T11:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        daily = result["daily"]
        assert len(daily) == 3  # Jan 10, 11, 12
        assert daily[0] == {"date": "2026-01-10", "count": 0, "errors": 0}
        assert daily[1] == {"date": "2026-01-11", "count": 2, "errors": 1}
        assert daily[2] == {"date": "2026-01-12", "count": 0, "errors": 0}

    def test_single_day_range(self) -> None:
        d = date(2026, 1, 15)
        events = [_FakeEvent("X", "forwarded", "2026-01-15T09:00:00+00:00")]
        result = compute_tracking_stats(events, d, d)
        assert len(result["daily"]) == 1
        assert result["daily"][0]["date"] == "2026-01-15"
        assert result["daily"][0]["count"] == 1

    def test_status_failed_is_error_only(self) -> None:
        """Verify that 'received', 'forwarded', 'duplicate', 'skipped_no_consent'
        do NOT count as total_errors — only 'failed' does."""
        d_from, d_to = self._range()
        events = [
            _FakeEvent("X", "received", "2026-01-11T10:00:00+00:00"),
            _FakeEvent("X", "forwarded", "2026-01-12T10:00:00+00:00"),
            _FakeEvent("X", "duplicate", "2026-01-13T10:00:00+00:00"),
            _FakeEvent("X", "skipped_no_consent", "2026-01-14T10:00:00+00:00"),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        assert result["totals"]["total_errors"] == 0
        assert result["totals"]["consent_blocked"] == 1

    def test_consent_blocked_counts_skipped_no_consent_only(self) -> None:
        """consent=False with status='received' is NOT consent_blocked."""
        d_from, d_to = self._range()
        # A hypothetical event that arrived with consent=False but was received
        # (e.g. no destinations configured): NOT consent_blocked because status
        # is not skipped_no_consent.
        events = [
            _FakeEvent("X", "received", "2026-01-11T10:00:00+00:00", consent=False),
            _FakeEvent("X", "skipped_no_consent", "2026-01-12T10:00:00+00:00", consent=False),
        ]
        result = compute_tracking_stats(events, d_from, d_to)
        assert result["totals"]["consent_blocked"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET /sources/{source_id}/stats — HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceStatsEndpoint:
    def _seed_source_and_events(
        self, db: Session, tenant_id: uuid.UUID
    ) -> tuple[TrackingSource, list[ConversionEvent]]:
        src = _make_source(db, tenant_id)
        today = datetime.now(timezone.utc).date()
        # Day 1: 2 forwarded Purchase, 1 failed AddToCart
        day1 = (today - timedelta(days=5)).isoformat()
        # Day 2: 1 skipped_no_consent Purchase, 1 received PageView
        day2 = (today - timedelta(days=3)).isoformat()

        events = [
            _make_event(db, tenant_id=tenant_id, source_id=src.id, event_name="Purchase",
                        status="forwarded", created_at=f"{day1}T10:00:00+00:00"),
            _make_event(db, tenant_id=tenant_id, source_id=src.id, event_name="Purchase",
                        status="forwarded", created_at=f"{day1}T11:00:00+00:00"),
            _make_event(db, tenant_id=tenant_id, source_id=src.id, event_name="AddToCart",
                        status="failed", created_at=f"{day1}T12:00:00+00:00"),
            _make_event(db, tenant_id=tenant_id, source_id=src.id, event_name="Purchase",
                        status="skipped_no_consent", created_at=f"{day2}T10:00:00+00:00",
                        consent=False),
            _make_event(db, tenant_id=tenant_id, source_id=src.id, event_name="PageView",
                        status="received", created_at=f"{day2}T11:00:00+00:00"),
        ]
        return src, events

    def test_happy_path_default_date_range(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Read membership tenant_id from the app's dependency override
        membership = _test_app.dependency_overrides[get_current_membership]()
        src, _ = self._seed_source_and_events(db_session, membership.tenant_id)

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        body = resp.json()

        assert body["source_id"] == str(src.id)
        assert "date_from" in body
        assert "date_to" in body

        totals = body["totals"]
        assert totals["total_events"] == 5
        assert totals["total_errors"] == 1          # 1 failed
        assert totals["consent_blocked"] == 1       # 1 skipped_no_consent
        assert totals["by_status"]["forwarded"] == 2
        assert totals["by_status"]["failed"] == 1
        assert totals["by_status"]["skipped_no_consent"] == 1
        assert totals["by_status"]["received"] == 1

    def test_by_event_sorted_and_correct(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src, _ = self._seed_source_and_events(db_session, membership.tenant_id)

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        by_event = resp.json()["by_event"]

        # Purchase has 3 occurrences, AddToCart 1, PageView 1 → Purchase first
        assert by_event[0]["event_name"] == "Purchase"
        assert by_event[0]["count"] == 3
        assert by_event[0]["errors"] == 0  # Purchase failures are 0 here

        add_to_cart = next(e for e in by_event if e["event_name"] == "AddToCart")
        assert add_to_cart["errors"] == 1  # the failed one

        # All entries sorted descending by count
        counts = [e["count"] for e in by_event]
        assert counts == sorted(counts, reverse=True)

    def test_daily_trend_zero_filled(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)
        today = datetime.now(timezone.utc).date()
        d_from = today - timedelta(days=2)
        d_to = today

        # One event on d_from
        _make_event(db_session, tenant_id=membership.tenant_id, source_id=src.id,
                    status="forwarded", created_at=f"{d_from.isoformat()}T10:00:00+00:00")

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/stats",
            params={"date_from": d_from.isoformat(), "date_to": d_to.isoformat()},
        )
        assert resp.status_code == 200
        daily = resp.json()["daily"]
        assert len(daily) == 3  # 3 days inclusive

        # First day has 1 event, rest zero
        assert daily[0]["date"] == d_from.isoformat()
        assert daily[0]["count"] == 1
        assert daily[1]["count"] == 0
        assert daily[2]["count"] == 0

        # Ascending by date
        dates = [d["date"] for d in daily]
        assert dates == sorted(dates)

    def test_date_filtering_excludes_out_of_range(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)

        # Insert event on 2026-01-01 and on 2026-01-20
        _make_event(db_session, tenant_id=membership.tenant_id, source_id=src.id,
                    status="forwarded", created_at="2026-01-01T10:00:00+00:00")
        _make_event(db_session, tenant_id=membership.tenant_id, source_id=src.id,
                    status="failed", created_at="2026-01-20T10:00:00+00:00")

        # Filter to only Jan 1
        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/stats",
            params={"date_from": "2026-01-01", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["total_events"] == 1
        assert body["totals"]["total_errors"] == 0

    def test_date_from_after_date_to_returns_422(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/stats",
            params={"date_from": "2026-01-20", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unknown_source_returns_404(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/tracking/sources/{uuid.uuid4()}/stats")
        assert resp.status_code == 404

    def test_other_tenant_source_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Create a source under a different tenant directly in DB
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id, public_token=f"other-{uuid.uuid4().hex}")

        resp = client.get(f"/api/v1/tracking/sources/{other_src.id}/stats")
        assert resp.status_code == 404

    def test_no_events_returns_zero_totals(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/stats",
            params={"date_from": "2026-01-01", "date_to": "2026-01-03"},
        )
        assert resp.status_code == 200
        body = resp.json()
        totals = body["totals"]
        assert totals["total_events"] == 0
        assert totals["total_errors"] == 0
        assert totals["consent_blocked"] == 0
        assert totals["by_status"] == {}
        assert body["by_event"] == []
        # 3 zero-filled daily entries
        assert len(body["daily"]) == 3
        for d in body["daily"]:
            assert d["count"] == 0

    def test_unauthenticated_returns_401(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get(f"/api/v1/tracking/sources/{uuid.uuid4()}/stats")
        # No auth → 401 or 403 (depends on HTTPBearer auto_error=False path)
        assert resp.status_code in (401, 403)

    def test_response_schema_fields_present(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = _make_source(db_session, membership.tenant_id)
        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/stats",
            params={"date_from": "2026-01-01", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"source_id", "date_from", "date_to", "totals", "by_event", "daily"}
        assert set(body["totals"].keys()) >= {"total_events", "total_errors", "by_status", "consent_blocked"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET /sources/{source_id}/events — filterable debug console
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventListFilters:
    def _setup(self, db: Session, tenant_id: uuid.UUID) -> TrackingSource:
        src = _make_source(db, tenant_id)
        today = datetime.now(timezone.utc).date().isoformat()
        _make_event(db, tenant_id=tenant_id, source_id=src.id,
                    event_name="Purchase", status="forwarded",
                    created_at=f"{today}T10:00:00+00:00", event_id="fwd-1")
        _make_event(db, tenant_id=tenant_id, source_id=src.id,
                    event_name="Purchase", status="failed",
                    created_at=f"{today}T11:00:00+00:00", event_id="fld-1")
        _make_event(db, tenant_id=tenant_id, source_id=src.id,
                    event_name="AddToCart", status="forwarded",
                    created_at=f"{today}T12:00:00+00:00", event_id="fwd-2")
        _make_event(db, tenant_id=tenant_id, source_id=src.id,
                    event_name="PageView", status="skipped_no_consent",
                    created_at=f"{today}T13:00:00+00:00", event_id="skp-1",
                    consent=False)
        return src

    def test_no_filters_returns_all(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/events")
        assert resp.status_code == 200
        assert len(resp.json()) == 4

    def test_filter_by_status_forwarded(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"status": "forwarded"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 2
        assert all(e["status"] == "forwarded" for e in events)

    def test_filter_by_status_failed(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"status": "failed"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["status"] == "failed"

    def test_filter_by_status_skipped_no_consent(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"status": "skipped_no_consent"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["status"] == "skipped_no_consent"

    def test_filter_by_event_name(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"event_name": "Purchase"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 2
        assert all(e["event_name"] == "Purchase" for e in events)

    def test_filter_combined_status_and_event_name(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"status": "forwarded", "event_name": "Purchase"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event_name"] == "Purchase"
        assert events[0]["status"] == "forwarded"
        assert events[0]["event_id"] == "fwd-1"

    def test_filter_nonexistent_status_returns_empty(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"status": "nonexistent_status"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_limit_parameter_respected(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)  # 4 events

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"limit": 2},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_limit_max_500(self, client: TestClient, db_session: Session) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"limit": 501},
        )
        assert resp.status_code == 422  # FastAPI validation error

    def test_limit_min_1(self, client: TestClient, db_session: Session) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(
            f"/api/v1/tracking/sources/{src.id}/events",
            params={"limit": 0},
        )
        assert resp.status_code == 422

    def test_events_returned_most_recent_first(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        src = self._setup(db_session, membership.tenant_id)

        resp = client.get(f"/api/v1/tracking/sources/{src.id}/events")
        assert resp.status_code == 200
        events = resp.json()
        created_ats = [e["created_at"] for e in events]
        assert created_ats == sorted(created_ats, reverse=True)

    def test_events_unauthenticated_returns_401(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get(f"/api/v1/tracking/sources/{uuid.uuid4()}/events")
        assert resp.status_code in (401, 403)

    def test_events_other_tenant_source_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        other_src = _make_source(db_session, other_tenant_id, public_token=f"xother-{uuid.uuid4().hex}")

        resp = client.get(f"/api/v1/tracking/sources/{other_src.id}/events")
        assert resp.status_code == 404
