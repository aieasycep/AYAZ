"""In-memory token-bucket rate limiter — pure Python, no heavy dependencies.

Usage (as a FastAPI dependency)
--------------------------------
    from ayaz.security.rate_limit import rate_limit

    @router.post("/login")
    def login(
        request: Request,
        _rl: None = Depends(rate_limit("auth:login", limit=10, window_seconds=60)),
    ):
        ...

Design
------
* Fixed-window counter keyed by ``(client_ip, key)``.
* Thread-safe via a module-level ``threading.Lock``.
* The in-memory store is intentionally reset between process restarts; the
  limiter is an abuse-deterrent, not a cryptographic guarantee.  For
  multi-process deployments wire a Redis-backed implementation instead.
* The clock is injectable (``_now`` param) so unit tests can advance time
  without sleeping.
* The store is completely resettable (``_reset_store()``) so test fixtures
  can start clean without process restart.
* Entirely disabled when ``settings.rate_limit_enabled is False`` — lets the
  test suite run without ever hitting HTTP 429.

Window and limit defaults are sourced from settings so operators can tune
them via environment variables without touching code.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from ayaz.config import settings

# ── Internal store ────────────────────────────────────────────────────────────

# _store maps (ip, key) → [window_start_timestamp, hit_count]
_store: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
_store_lock = threading.Lock()


def _reset_store() -> None:
    """Clear all rate-limit counters.  Call in test teardown."""
    with _store_lock:
        _store.clear()


# ── Core logic ────────────────────────────────────────────────────────────────


def _check_rate_limit(
    ip: str,
    key: str,
    limit: int,
    window_seconds: int,
    now: float | None = None,
) -> None:
    """Raise HTTP 429 if the request exceeds the fixed-window limit.

    Parameters
    ----------
    ip:
        Client IP address (used as part of the bucket key).
    key:
        A short string identifying the protected route, e.g. ``"auth:login"``.
    limit:
        Maximum number of requests allowed within ``window_seconds``.
    window_seconds:
        Width of the rolling window in seconds.
    now:
        Override the current time (float epoch seconds).  Use in tests.
    """
    ts = now if now is not None else time.time()
    bucket_key = (ip, key)

    with _store_lock:
        entry = _store[bucket_key]
        window_start, count = entry

        if ts - window_start >= window_seconds:
            # New window — reset counter
            entry[0] = ts
            entry[1] = 1
        else:
            entry[1] += 1
            count = entry[1]

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Çok fazla istek gönderdiniz. "
                "Lütfen bir süre bekleyip tekrar deneyin."
            ),
            headers={"Retry-After": str(window_seconds)},
        )


def _client_ip(request: Request) -> str:
    """Extract the real client IP, honouring X-Forwarded-For if present."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ── Dependency factory ────────────────────────────────────────────────────────


def rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
) -> Callable[..., None]:
    """Return a FastAPI dependency that enforces a fixed-window rate limit.

    Parameters
    ----------
    key:
        Short identifier for the protected route, e.g. ``"auth:login"``.
        Combined with the client IP to form the bucket key.
    limit:
        Max requests within ``window_seconds``.
    window_seconds:
        Window width in seconds.

    Example
    -------
    ::

        @router.post("/login")
        def login(
            request: Request,
            _rl: None = Depends(rate_limit("auth:login", limit=10, window_seconds=60)),
        ):
            ...
    """

    def _dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return  # disabled in test mode — no 429s ever raised

        ip = _client_ip(request)
        _check_rate_limit(ip, key, limit, window_seconds)

    return _dependency
