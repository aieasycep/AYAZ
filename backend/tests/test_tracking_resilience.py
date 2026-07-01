"""Tests for M7 resilience: error classification, retry, deliverability (Dalga 60)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

import ayaz.models.oltp  # noqa: F401
import ayaz.models.tracking  # noqa: F401

from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import tracking as tracking_module
from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.services.tracking import classify_forward_error, retry_event


# ── classify_forward_error (pure) ─────────────────────────────────────────────


class TestClassifyForwardError:
    def test_none_and_empty(self) -> None:
        for v in (None, ""):
            r = classify_forward_error(v)
            assert r["category"] == "unknown"
            assert r["retryable"] is False

    def test_transient_http(self) -> None:
        for code in ("429", "500", "502", "503", "504"):
            r = classify_forward_error(f"[meta_capi] HTTP {code}: oops")
            assert r["category"] == "transient"
            assert r["retryable"] is True

    def test_permanent_http(self) -> None:
        for code in ("400", "401", "403", "404", "422"):
            r = classify_forward_error(f"[ga4_mp] HTTP {code}: bad")
            assert r["category"] == "permanent"
            assert r["retryable"] is False

    def test_keyword_transient(self) -> None:
        assert classify_forward_error("Connection timeout")["category"] == "transient"
        assert classify_forward_error("rate limit exceeded")["retryable"] is True

    def test_keyword_permanent(self) -> None:
        assert classify_forward_error("Invalid pixel_id")["category"] == "permanent"
        assert classify_forward_error("access token expired")["retryable"] is False

    def test_unknown_default(self) -> None:
        r = classify_forward_error("something weird happened")
        assert r["category"] == "unknown"
        assert r["retryable"] is False

    def test_http_code_beats_keyword(self) -> None:
        # 500 present → transient even though "invalid" keyword also present
        r = classify_forward_error("HTTP 500: invalid response body")
        assert r["category"] == "transient"


# ── retry_event + endpoint ────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def _setup(db: Session, tenant_id: uuid.UUID, *, status: str = "failed"):
    src = TrackingSource(
        tenant_id=tenant_id,
        name="S",
        public_token="resil-token-1",
        is_active=True,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    dest = EventDestination(
        tenant_id=tenant_id,
        tracking_source_id=src.id,
        platform="meta_capi",
        config={"pixel_id": "123", "_secrets": {"access_token": "t"}},
        consent_required=False,
        is_active=True,
    )
    db.add(dest)
    evt = ConversionEvent(
        tenant_id=tenant_id,
        tracking_source_id=src.id,
        event_name="Purchase",
        event_time="2026-06-25T10:00:00+00:00",
        event_id="resil-evt-1",
        user_data={"email_hash": "a" * 64},
        custom_data={},
        consent=True,
        status=status,
        forwarded_count=0,
        error="[meta_capi] HTTP 500: server error",
        created_at="2026-06-25T10:00:00+00:00",
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return src, dest, evt


class _OKResp:
    def raise_for_status(self) -> None:
        return None


class _OKClient:
    def post(self, *a, **k):
        return _OKResp()


class TestRetryEvent:
    def test_retry_increments_and_succeeds(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _, _, evt = _setup(db_session, tid)
        updated = retry_event(db_session, evt, http_client=_OKClient())
        assert updated.retry_count == 1
        assert updated.status == "forwarded"
        assert updated.error is None

    def test_retry_failure_keeps_failed(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _, _, evt = _setup(db_session, tid)

        class _BoomClient:
            def post(self, *a, **k):
                raise httpx.ConnectError("boom")

        updated = retry_event(db_session, evt, http_client=_BoomClient())
        assert updated.retry_count == 1
        assert updated.status == "failed"


class TestRetryEndpoint:
    def _client(self, db: Session, tenant_id: uuid.UUID) -> TestClient:
        app = FastAPI()
        app.include_router(tracking_module.router, prefix="/api/v1")
        membership = Membership(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            role=MembershipRole.owner,
        )

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_membership] = lambda: membership
        return TestClient(app)

    def test_retry_non_failed_returns_409(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _, _, evt = _setup(db_session, tid, status="forwarded")
        client = self._client(db_session, tid)
        resp = client.post(f"/api/v1/tracking/events/{evt.id}/retry")
        assert resp.status_code == 409

    def test_retry_unknown_event_404(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _setup(db_session, tid)
        client = self._client(db_session, tid)
        resp = client.post(f"/api/v1/tracking/events/{uuid.uuid4()}/retry")
        assert resp.status_code == 404


class TestDeliverabilityStats:
    def test_stats_deliverability_block(self, db_session: Session) -> None:
        from datetime import datetime, timezone

        tid = uuid.uuid4()
        src, _, _ = _setup(db_session, tid)
        today = datetime.now(timezone.utc).date().isoformat()
        # add a permanent + transient failed event in range
        for i, err in enumerate(
            ["[meta_capi] HTTP 400: invalid", "[ga4_mp] HTTP 503: down"]
        ):
            db_session.add(
                ConversionEvent(
                    tenant_id=tid,
                    tracking_source_id=src.id,
                    event_name="Purchase",
                    event_time=today + "T10:00:00+00:00",
                    event_id=f"deliv-{i}",
                    user_data={},
                    custom_data={},
                    consent=True,
                    status="failed",
                    error=err,
                    created_at=today + "T10:00:00+00:00",
                )
            )
        db_session.commit()

        app = FastAPI()
        app.include_router(tracking_module.router, prefix="/api/v1")
        membership = Membership(
            id=uuid.uuid4(),
            tenant_id=tid,
            user_id=uuid.uuid4(),
            role=MembershipRole.owner,
        )

        def _override_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_membership] = lambda: membership
        client = TestClient(app)
        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        deliv = resp.json()["deliverability"]
        assert deliv is not None
        assert deliv["permanent"] >= 1
        assert deliv["transient"] >= 1
        assert deliv["retryable"] == deliv["transient"]
