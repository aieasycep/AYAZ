"""Smoke test: the FastAPI app must import and expose its routes.

This guards against missing optional deps (e.g. pydantic[email]/email-validator)
and import-time errors in the API layer that unit tests on services/connectors
would not catch. We assert against the OpenAPI schema (the authoritative source of
served paths) and exercise an endpoint via TestClient.
"""

from fastapi.testclient import TestClient


def test_app_imports_and_serves_core_routes():
    from ayaz.main import app

    assert app.title
    paths = set(app.openapi().get("paths", {}).keys())
    for expected in (
        "/health",
        "/api/v1/auth/signup",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
    ):
        assert expected in paths, f"missing route: {expected}"


def test_health_and_validation_reachable():
    from ayaz.main import app

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    # endpoint is wired and validating (empty body -> 422, not 404)
    assert client.post("/api/v1/auth/signup", json={}).status_code == 422
