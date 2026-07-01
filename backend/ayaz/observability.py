"""Production-readiness observability for the AYAZ FastAPI backend.

Provides three concerns, all additive — zero changes to existing behaviour:

1. RequestIDMiddleware
   Reads the incoming ``X-Request-ID`` header; if absent, generates a UUID4.
   Stores the value on ``request.state.request_id`` so any downstream code
   (error handlers, background tasks) can reference it.  Sets the same value
   on the outgoing ``X-Request-ID`` response header.

2. RequestLoggingMiddleware
   After the response is complete, emits one structured INFO log line on the
   ``ayaz.request`` logger containing: method, path, status_code,
   duration_ms (rounded to 1 decimal place), request_id, and client_host.
   Health-probe paths (``/health``, ``/health/ready``) are logged at DEBUG
   so they do not flood production logs.
   Never logs: query strings, auth headers, request/response bodies, tokens.

3. configure_logging(level)
   One-shot helper that configures a consistent formatter on the root logger.
   Idempotent — safe to call multiple times; only adds a handler once.

These are imported and wired in ``ayaz/main.py`` at startup.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Paths whose requests are logged at DEBUG to avoid flooding production logs.
_QUIET_PATHS: frozenset[str] = frozenset({"/health", "/health/ready"})

_REQUEST_LOGGER = logging.getLogger("ayaz.request")

# ── Logging configuration ─────────────────────────────────────────────────────

_LOGGING_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a consistent formatter.

    Idempotent: subsequent calls are no-ops so it is safe to call at import
    time and in test fixtures without accumulating duplicate handlers.

    Args:
        level: stdlib logging level (e.g. ``logging.DEBUG``, ``logging.INFO``).
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Only add our handler if no handler is already present (e.g. pytest
    # installs its own caplog handler — we do not want to displace it).
    if not root.handlers:
        root.addHandler(handler)

    root.setLevel(level)
    _LOGGING_CONFIGURED = True


# ── Request-ID middleware ─────────────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate or generate a per-request correlation ID.

    Reads ``X-Request-ID`` from the incoming request (forwarded by a load
    balancer or set by the client for distributed tracing).  If the header is
    absent or empty a UUID4 is generated.

    The ID is available to all downstream handlers via
    ``request.state.request_id`` and is echoed on the response as
    ``X-Request-ID``.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ── Request logging middleware ────────────────────────────────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log one structured line per HTTP request after the response is sent.

    Logged fields (no secrets, no bodies):
    - method       — HTTP verb (GET, POST, …)
    - path         — URL path only (query string deliberately excluded)
    - status_code  — integer response status
    - duration_ms  — wall-clock time in milliseconds, rounded to 1 dp
    - request_id   — from ``request.state.request_id`` (set by
                     RequestIDMiddleware, which must run first)
    - client_host  — remote IP if available, else "-"

    Health-probe paths are logged at DEBUG to avoid flooding production logs.
    All other requests are logged at INFO.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        t0 = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)

        request_id: str = getattr(request.state, "request_id", "-")
        client_host: str = (
            request.client.host if request.client else "-"
        )
        path = request.url.path  # path only — no query string in logs

        msg = (
            f"method={request.method} path={path} "
            f"status={response.status_code} duration_ms={duration_ms} "
            f"request_id={request_id} client={client_host}"
        )

        if path in _QUIET_PATHS:
            _REQUEST_LOGGER.debug(msg)
        else:
            _REQUEST_LOGGER.info(msg)

        return response
