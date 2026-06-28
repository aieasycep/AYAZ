"""Server-side Tracking / Conversions API service layer — M7.

This module is the heart of AYAZ's first-party data gateway.  It handles:

1. Identity hashing    — SHA-256 normalize-then-hash per Meta/TikTok CAPI spec.
2. Event ingestion     — validate, hash, dedup, persist.
3. Consent enforcement — KVKK/GDPR: skip forwarding when consent is absent and
                         at least one active destination requires it.
4. Platform forwarding — build the correct per-platform payload and POST it via
                         an injectable httpx client (never live in tests).

PII policy
----------
Raw PII (email, phone) MUST NOT survive past ``hash_identity()``.  The function
returns only hashed values; the caller must not log or persist the ``raw`` dict.

Platform payload mappings
-------------------------

meta_capi (Graph API v21.0):
  POST https://graph.facebook.com/v21.0/{pixel_id}/events
  Body: {
    "data": [{
      "event_name":   <event_name>,
      "event_time":   <unix_timestamp>,
      "event_id":     <event_id>,          # dedup key
      "action_source": "website",
      "user_data":    {
        "em": [<sha256(lower(trim(email)))>],
        "ph": [<sha256(digits_only(phone))>],
        ...passthrough hashed fields...
      },
      "custom_data":  <custom_data dict>
    }],
    "access_token": <from vault>
  }
  Vault key: "access_token"

tiktok_events (Business API v1.3):
  POST https://business-api.tiktok.com/open_api/v1.3/event/track/
  Header: Access-Token: <from vault>
  Body: {
    "pixel_code": <pixel_id from config>,
    "event":      <event_name>,
    "timestamp":  <unix_timestamp as str>,
    "context": {
      "user": {
        "email":    <hashed email if present>,
        "phone":    <hashed phone if present>,
      }
    },
    "properties": <custom_data dict>,
    "event_id":   <event_id>              # dedup key
  }
  Vault key: "access_token"

ga4_mp (Measurement Protocol):
  POST https://www.google-analytics.com/mp/collect
       ?measurement_id=<measurement_id>&api_secret=<from vault>
  Body: {
    "client_id":  <client_id from user_data or "server-side">,
    "events": [{
      "name":   <event_name>,
      "params": {
        "event_id":        <event_id>,
        "transaction_id":  <event_id>,  # GA4 purchase dedup
        "currency":        <custom_data.currency if present>,
        "value":           <custom_data.value if present>,
        ...other custom_data...
      }
    }]
  }
  Vault key: "api_secret"

Rate limits / vendor notes
--------------------------
meta_capi:     200 events/batch max; 80k events/hour per pixel; API version v21.0.
tiktok_events: 1 000 events/request max; use event_id for dedup.
ga4_mp:        25 events/request max (we send 1); no official RPS limit;
               validation endpoint: /debug/mp/collect (use in dev).
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_META_CAPI_URL = "https://graph.facebook.com/v21.0/{pixel_id}/events"
_TIKTOK_EVENTS_URL = (
    "https://business-api.tiktok.com/open_api/v1.3/event/track/"
)
_GA4_MP_URL = "https://www.google-analytics.com/mp/collect"

_VALID_PLATFORMS = {"meta_capi", "tiktok_events", "ga4_mp"}
_VALID_STATUSES = {
    "received",
    "forwarded",
    "failed",
    "skipped_no_consent",
    "duplicate",
    "disabled",
}


# ── Identity hashing ──────────────────────────────────────────────────────────


def hash_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize and SHA-256 hash PII fields from an identity dict.

    Only the fields ``email`` and ``phone`` receive special normalization before
    hashing.  All other fields whose keys end with ``_hash`` are passed through
    unchanged (already hashed by the caller).  Unknown non-PII fields are
    dropped.

    Normalization rules (per Meta CAPI and TikTok CAPI spec):
    - email  → lower-case, strip surrounding whitespace, then SHA-256
    - phone  → keep digits only, then SHA-256

    Parameters
    ----------
    raw:
        Dict that MAY contain ``email`` and/or ``phone`` (plain text) and
        optionally pre-hashed fields suffixed with ``_hash``.
        MUST NOT be logged or persisted; treated as ephemeral here.

    Returns
    -------
    dict
        A new dict with hashed values only.  Keys:
        ``email_hash``  – present if ``email`` was in ``raw``
        ``phone_hash``  – present if ``phone`` was in ``raw``
        Plus any ``*_hash`` passthroughs from the input.

    Security
    --------
    The function intentionally does NOT log the ``raw`` parameter.
    Callers MUST NOT log the return value of this function when debugging,
    as the hash is a deterministic fingerprint that can be reversed by
    dictionary attack on common values.
    """
    result: dict[str, Any] = {}

    email: str | None = raw.get("email")
    if email is not None:
        normalized = email.strip().lower()
        result["email_hash"] = _sha256(normalized)

    phone: str | None = raw.get("phone")
    if phone is not None:
        digits_only = re.sub(r"\D", "", str(phone))
        result["phone_hash"] = _sha256(digits_only)

    # Passthrough: any field already named *_hash
    for key, value in raw.items():
        if key.endswith("_hash") and isinstance(value, str):
            result[key] = value

    return result


def _sha256(value: str) -> str:
    """Return the lowercase hex SHA-256 digest of a UTF-8 string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ── Event ingestion ───────────────────────────────────────────────────────────


def ingest_event(
    db: Session,
    source: TrackingSource,
    payload: dict[str, Any],
) -> ConversionEvent:
    """Validate, hash, dedup, persist, and optionally forward a conversion event.

    Flow
    ----
    1. Extract fields from ``payload``.
    2. Hash any raw PII in ``user_data`` via ``hash_identity()``.
    3. Dedup: if an event with the same (tracking_source_id, event_id) already
       exists, return that row immediately with status "duplicate".
    4. Determine consent from ``payload.get("consent", False)``.
    5. Persist the event with status "received".
    6. Disabled check: if the event_name is in ``source.disabled_events``,
       update status → "disabled" and return without forwarding.
       Order rationale: dedup is always first (consistent re-submission
       behaviour); disabled is checked before loading destinations and before
       the consent check, as it is a source-level configuration gate that
       makes forwarding intent irrelevant regardless of consent state.
    7. Check active destinations:
       a. If any destination requires consent and the event has no consent,
          update status → "skipped_no_consent" and return.
       b. Otherwise forward to each active destination via ``forward_event()``.
       c. Update status → "forwarded" if all succeeded, "failed" if any errored.
    8. Commit and return the event.

    Parameters
    ----------
    db:
        SQLAlchemy session (caller owns the transaction boundary for the outer
        request; this function commits internally after status updates).
    source:
        The ``TrackingSource`` resolved from the public_token.
    payload:
        Raw inbound JSON body.  Expected shape::

            {
              "event_name":  str,                  # required
              "event_time":  str,                  # ISO-8601; required
              "event_id":    str,                  # required; dedup key
              "user_data":   dict,                 # may contain raw PII
              "custom_data": dict,                 # non-PII event payload
              "consent":     bool                  # KVKK/GDPR; default false
            }

    Returns
    -------
    ConversionEvent
        The persisted (possibly pre-existing duplicate) event row.

    Raises
    ------
    ValueError
        If any required field is missing from ``payload``.
    """
    # ── 1. Field extraction & validation ──────────────────────────────────────
    event_name: str | None = payload.get("event_name")
    event_time: str | None = payload.get("event_time")
    event_id: str | None = payload.get("event_id")

    missing = [f for f, v in [
        ("event_name", event_name),
        ("event_time", event_time),
        ("event_id", event_id),
    ] if not v]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    # Guaranteed non-None after validation above
    assert event_name and event_time and event_id  # noqa: S101

    raw_user_data: dict[str, Any] = payload.get("user_data") or {}
    custom_data: dict[str, Any] = payload.get("custom_data") or {}
    consent: bool = bool(payload.get("consent", False))

    # ── 2. Hash PII ───────────────────────────────────────────────────────────
    hashed_user_data = hash_identity(raw_user_data)

    # ── 3. Dedup ──────────────────────────────────────────────────────────────
    existing = db.scalar(
        select(ConversionEvent).where(
            ConversionEvent.tracking_source_id == source.id,
            ConversionEvent.event_id == event_id,
        )
    )
    if existing is not None:
        logger.info(
            "Duplicate event_id=%r for source=%s — returning existing event %s",
            event_id,
            source.id,
            existing.id,
        )
        existing.status = "duplicate"
        db.add(existing)
        db.commit()
        return existing

    # ── 4. Persist ────────────────────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    event = ConversionEvent(
        tenant_id=source.tenant_id,
        tracking_source_id=source.id,
        event_name=event_name,
        event_time=event_time,
        event_id=event_id,
        user_data=hashed_user_data,
        custom_data=custom_data,
        consent=consent,
        status="received",
        forwarded_count=0,
        error=None,
        created_at=now_iso,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # ── 5. Disabled check ─────────────────────────────────────────────────────
    # Order: dedup → disabled → consent → forward.
    # Checked before loading destinations to avoid unnecessary DB queries for
    # known-disabled event names.  A disabled event is recorded (persisted
    # above) but never forwarded; forwarded_count stays 0.
    disabled_events: list = source.disabled_events or []
    if event_name in disabled_events:
        event.status = "disabled"
        db.add(event)
        db.commit()
        logger.info(
            "Event %s skipped: event_name=%r is disabled for source=%s",
            event.id,
            event_name,
            source.id,
        )
        return event

    # ── 6. Load active destinations ───────────────────────────────────────────
    destinations: list[EventDestination] = list(
        db.scalars(
            select(EventDestination).where(
                EventDestination.tracking_source_id == source.id,
                EventDestination.is_active.is_(True),
            )
        )
    )

    if not destinations:
        # No destinations configured — event stays "received"
        return event

    # ── 7a. Consent check ─────────────────────────────────────────────────────
    consent_required_any = any(d.consent_required for d in destinations)
    if consent_required_any and not consent:
        event.status = "skipped_no_consent"
        db.add(event)
        db.commit()
        logger.info(
            "Event %s skipped: no consent; source=%s", event.id, source.id
        )
        return event

    # ── 7b. Forward ───────────────────────────────────────────────────────────
    errors: list[str] = []
    forwarded = 0

    for dest in destinations:
        # Skip individual destination if it requires consent and event has none
        if dest.consent_required and not consent:
            continue
        try:
            forward_event(event, dest)
            forwarded += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"[{dest.platform}] {exc}"
            errors.append(msg)
            logger.error(
                "Failed to forward event %s to destination %s: %s",
                event.id,
                dest.id,
                msg,
            )

    # ── 7c. Status update ─────────────────────────────────────────────────────
    event.forwarded_count = forwarded
    if errors:
        event.status = "failed"
        event.error = "; ".join(errors)
    else:
        event.status = "forwarded"

    db.add(event)
    db.commit()
    return event


# ── Platform forwarding ───────────────────────────────────────────────────────


def forward_event(
    event: ConversionEvent,
    destination: EventDestination,
    *,
    http_client: httpx.Client | None = None,
) -> None:
    """Build the platform-specific payload and POST to the destination API.

    The ``http_client`` parameter is injectable so tests can pass a mock
    without any live network calls.  When ``None``, a fresh ``httpx.Client``
    is created and closed for the single request.

    Parameters
    ----------
    event:
        The ``ConversionEvent`` to forward.  ``user_data`` must contain only
        hashed identifiers at this point.
    destination:
        The ``EventDestination`` describing the platform and its config.
    http_client:
        Optional pre-constructed httpx.Client (used in tests for mocking).

    Raises
    ------
    ValueError
        For unknown platform values.
    httpx.HTTPStatusError
        If the platform API returns a non-2xx response.
    RuntimeError
        If required Vault secret is missing for the destination.
    """
    platform = destination.platform

    if platform == "meta_capi":
        _forward_meta_capi(event, destination, http_client=http_client)
    elif platform == "tiktok_events":
        _forward_tiktok_events(event, destination, http_client=http_client)
    elif platform == "ga4_mp":
        _forward_ga4_mp(event, destination, http_client=http_client)
    else:
        raise ValueError(
            f"Unknown platform {platform!r}. "
            f"Must be one of {sorted(_VALID_PLATFORMS)}."
        )


def _get_secret(destination: EventDestination, key: str) -> str:
    """Retrieve a secret from the destination's Vault ref.

    In production the vault_secret_ref is resolved by the application's
    SecretsVault.  For the forwarding layer we accept the ref as a
    dot-separated path: ``<ref>.<key>`` (e.g. ``dest_uuid.access_token``).

    For simplicity in this service layer we look for the secret directly
    in ``destination.config`` under the key ``_secrets.<key>`` — this
    allows test mocks to inject secrets without a real Vault.

    In production, the caller should inject secrets via the Vault dependency
    before calling ``forward_event()``.  The recommended pattern is:

        secrets = vault.get(destination.vault_secret_ref) or {}
        # Then pass secrets via destination.config["_secrets"] for the call.

    Note: ``_secrets`` is NEVER persisted to the database — it is only
    present in the in-memory object during a forwarding call.
    """
    # Check in-memory injection first (tests and vault-injected path)
    injected: dict[str, Any] = destination.config.get("_secrets", {})
    if key in injected:
        return str(injected[key])

    raise RuntimeError(
        f"Secret {key!r} not found for destination {destination.id}. "
        "Inject via destination.config['_secrets'] after Vault lookup."
    )


def _event_time_to_unix(event_time_iso: str) -> int:
    """Parse an ISO-8601 datetime string and return a Unix timestamp (int).

    Accepts both UTC-with-Z and offset-aware formats.  Falls back to current
    time if parsing fails, to avoid dropping events over a malformed timestamp.
    """
    try:
        # Python 3.11+ fromisoformat handles Z; for compat, replace Z with +00:00
        dt = datetime.fromisoformat(event_time_iso.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        logger.warning(
            "Could not parse event_time %r — using current UTC time",
            event_time_iso,
        )
        return int(datetime.now(timezone.utc).timestamp())


def _forward_meta_capi(
    event: ConversionEvent,
    destination: EventDestination,
    *,
    http_client: httpx.Client | None,
) -> None:
    """Forward a conversion event to the Meta Conversions API (Graph API v21.0).

    Mapping
    -------
    AYAZ field                 → Meta CAPI field
    event.event_name           → data[0].event_name
    event.event_time (ISO)     → data[0].event_time (Unix int)
    event.event_id             → data[0].event_id
    event.user_data.email_hash → data[0].user_data.em (list)
    event.user_data.phone_hash → data[0].user_data.ph (list)
    event.custom_data          → data[0].custom_data
    config.action_source       → data[0].action_source (default "website")
    vault:access_token         → query param access_token

    Reference: https://developers.facebook.com/docs/marketing-api/conversions-api/
    """
    pixel_id: str = destination.config.get("pixel_id", "")
    if not pixel_id:
        raise RuntimeError(
            f"meta_capi destination {destination.id} missing config.pixel_id"
        )

    access_token = _get_secret(destination, "access_token")

    # Build user_data in Meta format: arrays of hashes
    meta_user_data: dict[str, Any] = {}
    if "email_hash" in event.user_data:
        meta_user_data["em"] = [event.user_data["email_hash"]]
    if "phone_hash" in event.user_data:
        meta_user_data["ph"] = [event.user_data["phone_hash"]]
    # Pass through any extra hashed fields (fbc, fbp, etc.)
    for k, v in event.user_data.items():
        if k not in ("email_hash", "phone_hash"):
            meta_user_data[k] = v

    action_source: str = destination.config.get("action_source", "website")

    body: dict[str, Any] = {
        "data": [
            {
                "event_name": event.event_name,
                "event_time": _event_time_to_unix(event.event_time),
                "event_id": event.event_id,
                "action_source": action_source,
                "user_data": meta_user_data,
                "custom_data": event.custom_data,
            }
        ],
        "access_token": access_token,
    }

    url = _META_CAPI_URL.format(pixel_id=pixel_id)
    _post_json(url, body, headers={}, http_client=http_client)
    logger.info(
        "meta_capi forward OK: event=%s pixel=%s", event.id, pixel_id
    )


def _forward_tiktok_events(
    event: ConversionEvent,
    destination: EventDestination,
    *,
    http_client: httpx.Client | None,
) -> None:
    """Forward a conversion event to the TikTok Events API (v1.3).

    Mapping
    -------
    AYAZ field                   → TikTok field
    event.event_name             → event
    event.event_time (ISO)       → timestamp (str of Unix int)
    event.event_id               → event_id
    event.user_data.email_hash   → context.user.email
    event.user_data.phone_hash   → context.user.phone
    event.custom_data            → properties
    config.pixel_id              → pixel_code
    vault:access_token           → Access-Token header

    Reference: https://business-api.tiktok.com/portal/docs?id=1771101027431425
    """
    pixel_id: str = destination.config.get("pixel_id", "")
    if not pixel_id:
        raise RuntimeError(
            f"tiktok_events destination {destination.id} missing config.pixel_id"
        )

    access_token = _get_secret(destination, "access_token")

    user_ctx: dict[str, Any] = {}
    if "email_hash" in event.user_data:
        user_ctx["email"] = event.user_data["email_hash"]
    if "phone_hash" in event.user_data:
        user_ctx["phone"] = event.user_data["phone_hash"]

    body: dict[str, Any] = {
        "pixel_code": pixel_id,
        "event": event.event_name,
        "timestamp": str(_event_time_to_unix(event.event_time)),
        "event_id": event.event_id,
        "context": {"user": user_ctx},
        "properties": event.custom_data,
    }

    headers = {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }

    _post_json(_TIKTOK_EVENTS_URL, body, headers=headers, http_client=http_client)
    logger.info(
        "tiktok_events forward OK: event=%s pixel=%s", event.id, pixel_id
    )


def _forward_ga4_mp(
    event: ConversionEvent,
    destination: EventDestination,
    *,
    http_client: httpx.Client | None,
) -> None:
    """Forward a conversion event to the GA4 Measurement Protocol.

    Mapping
    -------
    AYAZ field               → GA4 MP field
    event.event_name         → events[0].name
    event.event_id           → events[0].params.event_id
    event.event_id           → events[0].params.transaction_id  (purchase dedup)
    event.custom_data.value  → events[0].params.value
    event.custom_data.currency → events[0].params.currency
    user_data.client_id      → client_id (default: "server-side")
    config.measurement_id    → query param measurement_id
    vault:api_secret         → query param api_secret

    Reference: https://developers.google.com/analytics/devguides/collection/protocol/ga4
    """
    measurement_id: str = destination.config.get("measurement_id", "")
    if not measurement_id:
        raise RuntimeError(
            f"ga4_mp destination {destination.id} missing config.measurement_id"
        )

    api_secret = _get_secret(destination, "api_secret")

    client_id: str = str(
        event.user_data.get("client_id", "server-side")
    )

    # Build event params: include all custom_data fields + dedup ids
    params: dict[str, Any] = {
        "event_id": event.event_id,
        "transaction_id": event.event_id,
    }
    params.update(event.custom_data)

    body: dict[str, Any] = {
        "client_id": client_id,
        "events": [
            {
                "name": event.event_name,
                "params": params,
            }
        ],
    }

    url = (
        f"{_GA4_MP_URL}"
        f"?measurement_id={measurement_id}&api_secret={api_secret}"
    )

    _post_json(url, body, headers={}, http_client=http_client)
    logger.info(
        "ga4_mp forward OK: event=%s measurement_id=%s", event.id, measurement_id
    )


def _post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    http_client: httpx.Client | None,
) -> httpx.Response:
    """POST JSON to ``url``.  Uses ``http_client`` if provided, else creates one."""
    merged_headers = {"Content-Type": "application/json", **headers}
    if http_client is not None:
        resp = http_client.post(url, json=body, headers=merged_headers)
    else:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=body, headers=merged_headers)
    resp.raise_for_status()
    return resp
