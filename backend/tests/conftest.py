"""Pytest configuration for the AYAZ backend test suite.

Global fixtures and session-level setup applied to ALL tests in this directory.

Rate limiting
-------------
Rate limiting is disabled for the entire test suite via a session-scoped
autouse fixture so existing tests never receive HTTP 429.  Individual security
tests that need to verify rate-limit behaviour use the lower-level
``_check_rate_limit`` function directly (bypassing the settings flag) or
re-enable the setting via ``monkeypatch``.
"""

from __future__ import annotations

import pytest

from ayaz.config import settings
from ayaz.security.rate_limit import _reset_store


@pytest.fixture(autouse=True, scope="session")
def _disable_rate_limiting_globally():
    """Disable the rate limiter for the entire test session.

    The ``settings`` singleton is shared across the process.  Setting
    ``rate_limit_enabled = False`` here ensures no test ever gets HTTP 429
    from the application-level rate limiter.

    Security hardening tests that exercise rate-limit logic call the low-level
    ``_check_rate_limit`` helper directly and are therefore unaffected by this
    override.
    """
    original = settings.rate_limit_enabled
    # Bypass pydantic frozen-model protection by writing to __dict__
    settings.__dict__["rate_limit_enabled"] = False
    yield
    settings.__dict__["rate_limit_enabled"] = original


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Guarantee FastAPI dependency overrides never leak between tests.

    Several modules install ``app.dependency_overrides`` in their TestClient
    fixtures; not all of them clear the map on teardown. A leaked override —
    often a ``get_db`` / ``get_current_membership`` closure bound to an
    already-closed Session — makes unrelated later tests flaky depending on
    collection/run order (e.g. an auth test that expects 401 instead sees the
    leaked membership). Clearing before and after every test guarantees each
    test starts and ends with a clean override map, making the whole suite
    order-independent.
    """
    from ayaz.main import app

    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clear_rate_limit_store():
    """Reset the in-memory rate-limit counter store before every test.

    Prevents counter state from leaking between tests even when rate limiting
    is disabled (the store still accumulates counts if a dependency path is
    reached via a non-monkeypatched route).
    """
    _reset_store()
    yield
    _reset_store()
