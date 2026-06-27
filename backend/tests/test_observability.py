"""Tests for the observability layer added to the AYAZ FastAPI backend.

Covers:
- Every response carries an ``X-Request-ID`` response header.
- A supplied ``X-Request-ID`` request header is echoed back unchanged.
- An absent ``X-Request-ID`` generates a valid UUID4.
- ``GET /health/ready`` returns 200 with ``{"status": "ready"}`` against the
  working in-memory SQLite test DB.
- ``GET /health/ready`` returns 503 with ``{"status": "not_ready"}`` when the
  DB is broken (monkeypatched engine.connect raises).
- ``GET /health`` still returns the original shape (backward-compat guard).
- A request log line is emitted with the expected fields (caplog).
- Health-probe paths are logged at DEBUG, not INFO.
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ayaz.database import get_db
from ayaz.main import app


# ── Shared lightweight client (no DB override needed for header/liveness tests)

@pytest.fixture()
def client() -> TestClient:
    """Plain TestClient — no DB override.  Suitable for middleware + liveness tests."""
    return TestClient(app)


# ── In-memory SQLite DB fixture for readiness probe ───────────────────────────

_SQLITE_URL = "sqlite://"


@pytest.fixture()
def db_client():
    """TestClient with get_db overridden to use an in-memory SQLite session.

    Used for the /health/ready success path so the SELECT 1 probe works
    without a live Postgres instance.
    """
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Ensure at least the base metadata is importable (no tables needed for SELECT 1).
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), engine
    session.close()
    app.dependency_overrides.clear()


# ── X-Request-ID header propagation ──────────────────────────────────────────


class TestRequestIDMiddleware:
    def test_response_always_has_request_id_header(self, client: TestClient) -> None:
        """Every response must carry X-Request-ID, regardless of endpoint."""
        resp = client.get("/health")
        assert "x-request-id" in resp.headers or "X-Request-ID" in resp.headers

    def test_supplied_request_id_is_echoed(self, client: TestClient) -> None:
        """A client-supplied X-Request-ID must appear unchanged on the response."""
        supplied = "my-trace-id-abc123"
        resp = client.get("/health", headers={"X-Request-ID": supplied})
        returned = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
        assert returned == supplied

    def test_generated_request_id_is_valid_uuid(self, client: TestClient) -> None:
        """When X-Request-ID is absent, the generated value must be a valid UUID4."""
        resp = client.get("/health")
        returned = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
        assert returned is not None
        # Must parse as a UUID without error.
        parsed = uuid.UUID(returned)
        assert parsed.version == 4

    def test_unique_id_per_request(self, client: TestClient) -> None:
        """Each request without a client-supplied ID should get a distinct UUID."""
        ids = {
            (resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID"))
            for resp in (client.get("/health") for _ in range(5))
        }
        assert len(ids) == 5

    def test_request_id_on_non_health_endpoint(self, client: TestClient) -> None:
        """The header is present on endpoints other than /health too."""
        resp = client.post("/api/v1/auth/login", json={})
        # 422 from validation is fine — we only care about the header.
        returned = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
        assert returned is not None

    def test_empty_request_id_header_generates_uuid(self, client: TestClient) -> None:
        """An empty X-Request-ID header should be treated as absent."""
        resp = client.get("/health", headers={"X-Request-ID": ""})
        returned = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
        # Should be a freshly generated UUID (not an empty string).
        assert returned  # truthy
        parsed = uuid.UUID(returned)
        assert parsed.version == 4


# ── /health liveness backward-compatibility ───────────────────────────────────


class TestLivenessProbe:
    def test_liveness_returns_200(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_liveness_response_shape(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_liveness_version_value(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["version"] == app.version


# ── /health/ready readiness probe ────────────────────────────────────────────


class TestReadinessProbe:
    def test_readiness_returns_200_with_sqlite(self, db_client) -> None:
        """Success path: SELECT 1 on the in-memory SQLite engine must return 200."""
        tc, _engine = db_client
        # The readiness probe imports engine from ayaz.database — we need to
        # point it at our test engine.
        import ayaz.main as main_module
        import ayaz.database as db_module

        original_engine = db_module.engine
        db_module.engine = _engine
        try:
            resp = tc.get("/health/ready")
        finally:
            db_module.engine = original_engine

        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_readiness_returns_503_on_db_failure(self, client: TestClient) -> None:
        """Failure path: when engine.connect() raises, probe must return 503."""
        import ayaz.database as db_module

        broken_engine = MagicMock()
        broken_engine.connect.side_effect = Exception("simulated DB unreachable")

        original_engine = db_module.engine
        db_module.engine = broken_engine
        try:
            resp = client.get("/health/ready")
        finally:
            db_module.engine = original_engine

        assert resp.status_code == 503
        assert resp.json() == {"status": "not_ready"}

    def test_readiness_503_does_not_leak_exception(self, client: TestClient) -> None:
        """The 503 body must not contain the exception message or traceback."""
        import ayaz.database as db_module

        broken_engine = MagicMock()
        broken_engine.connect.side_effect = RuntimeError("super secret connection string here")

        original_engine = db_module.engine
        db_module.engine = broken_engine
        try:
            resp = client.get("/health/ready")
        finally:
            db_module.engine = original_engine

        body_text = resp.text
        assert "super secret" not in body_text
        assert "RuntimeError" not in body_text
        assert "Traceback" not in body_text

    def test_readiness_has_request_id_header(self, db_client) -> None:
        """The readiness endpoint must also carry the X-Request-ID header."""
        tc, _engine = db_client
        import ayaz.database as db_module

        original_engine = db_module.engine
        db_module.engine = _engine
        try:
            resp = tc.get("/health/ready")
        finally:
            db_module.engine = original_engine

        returned = resp.headers.get("x-request-id") or resp.headers.get("X-Request-ID")
        assert returned is not None


# ── Request logging ───────────────────────────────────────────────────────────


class TestRequestLoggingMiddleware:
    def test_info_log_emitted_for_normal_request(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-health request must produce an INFO log on ayaz.request."""
        with caplog.at_level(logging.INFO, logger="ayaz.request"):
            resp = client.post("/api/v1/auth/login", json={})

        log_messages = [r.getMessage() for r in caplog.records if r.name == "ayaz.request"]
        assert log_messages, "Expected at least one ayaz.request log record"

        msg = log_messages[-1]
        assert "method=POST" in msg
        assert "path=/api/v1/auth/login" in msg
        assert "status=" in msg
        assert "duration_ms=" in msg
        assert "request_id=" in msg

    def test_log_contains_no_query_string(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Query parameters must never appear in the log line."""
        with caplog.at_level(logging.INFO, logger="ayaz.request"):
            client.get("/health", params={"secret": "topsecret"})

        log_messages = [r.getMessage() for r in caplog.records if r.name == "ayaz.request"]
        for msg in log_messages:
            assert "topsecret" not in msg
            assert "secret=" not in msg

    def test_health_probe_logged_at_debug_not_info(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """/health requests must be logged at DEBUG level."""
        # Capture DEBUG and above to see all records.
        with caplog.at_level(logging.DEBUG, logger="ayaz.request"):
            client.get("/health")

        health_records = [
            r for r in caplog.records
            if r.name == "ayaz.request" and "/health" in r.getMessage()
        ]
        assert health_records, "Expected at least one /health log record"
        for rec in health_records:
            assert rec.levelno == logging.DEBUG, (
                f"/health should log at DEBUG, got {rec.levelname}"
            )

    def test_non_health_request_logged_at_info(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-probe endpoints must be logged at INFO level."""
        with caplog.at_level(logging.INFO, logger="ayaz.request"):
            client.get("/api/v1/auth/me")

        info_records = [
            r for r in caplog.records
            if r.name == "ayaz.request" and r.levelno == logging.INFO
        ]
        assert info_records, "Expected at least one INFO-level log for /api/v1/auth/me"

    def test_log_contains_request_id(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The log line must include the request_id field."""
        supplied_id = "test-req-id-xyz"
        with caplog.at_level(logging.INFO, logger="ayaz.request"):
            client.post(
                "/api/v1/auth/login",
                json={},
                headers={"X-Request-ID": supplied_id},
            )

        log_messages = [r.getMessage() for r in caplog.records if r.name == "ayaz.request"]
        assert any(supplied_id in msg for msg in log_messages), (
            f"Expected '{supplied_id}' in log; got: {log_messages}"
        )
