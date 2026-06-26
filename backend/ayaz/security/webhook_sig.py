"""Webhook signature verification helpers.

Stripe
------
Stripe signs webhook payloads with HMAC-SHA256 using the raw request body and
a timestamp embedded in the ``Stripe-Signature`` header.  The canonical
verification algorithm is:

    signed_payload = f"{timestamp}.{raw_body_str}"
    expected = hmac_sha256(webhook_secret, signed_payload)
    if not hmac.compare_digest(expected, received_sig): reject

iyzico
------
iyzico webhooks are signed with HMAC-SHA256 over the raw request body using
the ``iyzico_webhook_secret``.  The signature is sent in the
``X-Iyzico-Signature`` header as a hex digest.

Both providers
--------------
* If the relevant secret is empty (development / stub mode), verification is
  SKIPPED and the function returns ``True`` with a note in the docstring.
  This lets existing tests and the stub mode continue working unchanged.
* Timing-safe comparison (``hmac.compare_digest``) is used in all paths.

Security note (residual risk in test/stub mode)
------------------------------------------------
When no signing secret is configured the endpoint accepts any payload that
passes schema validation.  This means ``tenant_id`` is taken from the request
body — a spoofable field.  Never deploy without a signing secret in production.
This is explicitly documented in the caller (``billing.py`` webhook endpoint).
"""

from __future__ import annotations

import hashlib
import hmac
import time


# ── Stripe ────────────────────────────────────────────────────────────────────

_STRIPE_TOLERANCE_SECONDS = 300  # 5 minutes, matching Stripe's default


def verify_stripe_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance: int = _STRIPE_TOLERANCE_SECONDS,
    _now: float | None = None,
) -> bool:
    """Verify a Stripe webhook ``Stripe-Signature`` header.

    Returns True if the signature is valid and the timestamp is within
    ``tolerance`` seconds of now.  Returns False otherwise.

    If ``secret`` is empty the function returns True without checking
    (documented stub / test mode — caller must handle the residual risk).

    Parameters
    ----------
    raw_body:
        The raw HTTP request body bytes (before any JSON parsing).
    signature_header:
        The value of the ``Stripe-Signature`` header (e.g.
        ``"t=1234567890,v1=abc...,v1=def..."``).
    secret:
        The Stripe webhook signing secret (``whsec_...``).  Leave empty to
        skip verification (stub/test mode).
    tolerance:
        Maximum age of the webhook in seconds.  Stripe default is 300 (5 min).
    _now:
        Injectable current time (float epoch seconds) for testing.
    """
    if not secret:
        # Stub / test mode — no secret configured, accept all payloads.
        # SECURITY NOTE: tenant_id is taken from the request body and is
        # therefore spoofable.  Always configure a secret in production.
        return True

    # Parse the Stripe-Signature header: "t=...,v1=...,v1=..."
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        k, _, v = item.partition("=")
        parts.setdefault(k.strip(), []).append(v.strip())

    timestamp_strs = parts.get("t", [])
    v1_sigs = parts.get("v1", [])

    if not timestamp_strs or not v1_sigs:
        return False

    try:
        timestamp = int(timestamp_strs[0])
    except ValueError:
        return False

    current_time = _now if _now is not None else time.time()
    if abs(current_time - timestamp) > tolerance:
        return False  # replay attack — timestamp too old (or too new)

    # Compute HMAC-SHA256 over "timestamp.raw_body"
    signed_payload = f"{timestamp}.{raw_body.decode('utf-8', errors='replace')}"
    mac = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Accept if any v1 signature matches (Stripe may send multiple during rotation)
    return any(hmac.compare_digest(mac, sig) for sig in v1_sigs)


# ── iyzico ────────────────────────────────────────────────────────────────────


def verify_iyzico_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """Verify an iyzico webhook signature from the ``X-Iyzico-Signature`` header.

    iyzico signs the raw body with HMAC-SHA256 and sends the hex digest.
    Returns True if valid (or if ``secret`` is empty — stub / test mode).

    Parameters
    ----------
    raw_body:
        The raw HTTP request body bytes.
    signature_header:
        The hex-encoded HMAC-SHA256 digest sent by iyzico.
    secret:
        The iyzico webhook signing secret.  Leave empty to skip verification.
    """
    if not secret:
        # Stub / test mode — no secret configured, accept all payloads.
        # SECURITY NOTE: see the module docstring for residual risk.
        return True

    if not signature_header:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header.strip().lower())
