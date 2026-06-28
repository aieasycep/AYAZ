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

# Consent Mode v2 — the four canonical signal keys (Google / IAB TCF mapping).
_CONSENT_SIGNAL_KEYS = (
    "ad_storage",
    "ad_user_data",
    "ad_personalization",
    "analytics_storage",
)

# Platform-level default required_consent when the column is NULL/empty.
# Applied at code time so that existing rows behave sensibly without a data
# migration.  Rationale:
#   meta_capi, tiktok_events  → require ad_user_data  (user-level ad targeting)
#   ga4_mp                    → require analytics_storage (analytics measurement)
_PLATFORM_REQUIRED_CONSENT: dict[str, list[str]] = {
    "meta_capi": ["ad_user_data"],
    "tiktok_events": ["ad_user_data"],
    "ga4_mp": ["analytics_storage"],
}

# GA4 Consent State → gcs parameter mapping (best-effort passthrough).
# Sent in the GA4 MP payload when consent_signals is available.
# Reference: https://developers.google.com/tag-platform/security/guides/consent
_GA4_GCS_GRANTED = "G111"   # ad_storage=granted, analytics_storage=granted
_GA4_GCS_DENIED  = "G100"   # ad_storage=denied,  analytics_storage=granted
_GA4_GCS_ANALYTICS_ONLY = "G101"  # analytics_storage=granted, ad_storage=denied


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


# ── Consent Mode v2 normalization ─────────────────────────────────────────────


def normalize_consent(raw_consent: Any) -> tuple[bool, dict[str, bool]]:
    """Normalize a raw consent value to a (overall_bool, signals_dict) pair.

    Accepts two forms (Consent Mode v2 / backward compat):

    Boolean (existing behaviour)
    ----------------------------
    ``True``  → all four signals granted; overall = True
    ``False`` → all four signals denied;  overall = False

    Granular object (Consent Mode v2)
    ---------------------------------
    A dict with any subset of the four signal keys.  Missing keys default to
    False (denied).  Example::

        {"ad_user_data": True, "analytics_storage": True}
        # → ad_storage=False, ad_user_data=True, ad_personalization=False,
        #   analytics_storage=True

    Overall consent rule (documented)
    ----------------------------------
    ``overall = ad_user_data OR analytics_storage``

    Rationale: ``ad_user_data`` covers ad-side targeting consent (Meta, TikTok)
    and ``analytics_storage`` covers measurement consent (GA4).  If either is
    granted the event carries meaningful consent and is not purely "no consent".
    A plain ``consent: true`` maps all four to True, so overall stays True —
    identical to the pre-existing behaviour.

    Parameters
    ----------
    raw_consent:
        The value of ``payload["consent"]`` — either a bool or a dict.

    Returns
    -------
    (overall: bool, signals: dict[str, bool])
        ``overall`` is the backward-compat consent bool.
        ``signals`` is the canonical four-key dict.
    """
    if isinstance(raw_consent, dict):
        signals: dict[str, bool] = {
            k: bool(raw_consent.get(k, False)) for k in _CONSENT_SIGNAL_KEYS
        }
    else:
        # Plain bool — expand to all four signals
        granted = bool(raw_consent)
        signals = {k: granted for k in _CONSENT_SIGNAL_KEYS}

    overall = signals["ad_user_data"] or signals["analytics_storage"]
    return overall, signals


def _destination_required_signals(destination: EventDestination) -> list[str]:
    """Return the effective required consent signal list for a destination.

    Uses ``destination.required_consent`` when set and non-empty; otherwise
    falls back to the platform default from ``_PLATFORM_REQUIRED_CONSENT``.

    Parameters
    ----------
    destination:
        The EventDestination ORM object (must have ``.platform`` and
        ``.required_consent`` attributes after migration 0019).

    Returns
    -------
    list[str]
        Non-empty list of signal key strings that must all be granted.
    """
    required = getattr(destination, "required_consent", None)
    if required:  # non-None, non-empty list
        return list(required)
    return _PLATFORM_REQUIRED_CONSENT.get(destination.platform, ["ad_user_data"])


def _is_consent_satisfied(
    destination: EventDestination,
    consent_signals: dict[str, bool] | None,
) -> bool:
    """Return True if the event's consent satisfies the destination's requirements.

    Logic
    -----
    1. If ``destination.consent_required`` is False → always satisfied (back-compat).
    2. If ``consent_signals`` is None (legacy event without granular signals) →
       fall back to the overall ``consent`` bool approach; satisfied only if the
       destination has no required_consent (uses default) AND the caller must
       have checked the overall bool upstream.  In practice, we treat None
       signals as all-False (deny everything) so that old codepaths that didn't
       store signals are not accidentally promoted to "granted".
    3. Otherwise: ALL signal keys in ``_destination_required_signals`` must be
       True in ``consent_signals``.

    Parameters
    ----------
    destination:
        The EventDestination to check.
    consent_signals:
        The normalized four-key dict from the inbound event, or None for
        legacy events.

    Returns
    -------
    bool
    """
    if not destination.consent_required:
        return True

    if consent_signals is None:
        # Legacy path: no granular signals stored → deny (safest default)
        return False

    required_keys = _destination_required_signals(destination)
    return all(consent_signals.get(k, False) for k in required_keys)


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

    # Normalize consent — accepts bool OR granular dict (Consent Mode v2).
    raw_consent = payload.get("consent", False)
    consent, consent_signals = normalize_consent(raw_consent)

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
        consent_signals=consent_signals,
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

    # ── 7a. Granular consent check ────────────────────────────────────────────
    # Per-destination satisfaction is computed using the granular consent_signals
    # dict.  A destination is satisfied iff ALL its required_consent signal keys
    # are granted.  If consent_required is False the destination is always
    # satisfied.  If no destination is satisfied → skipped_no_consent (aggregate
    # behaviour identical to the pre-existing boolean check).
    satisfied_dests = [
        d for d in destinations
        if _is_consent_satisfied(d, event.consent_signals)
    ]
    if not satisfied_dests:
        event.status = "skipped_no_consent"
        db.add(event)
        db.commit()
        logger.info(
            "Event %s skipped: no destination consent satisfied; source=%s",
            event.id,
            source.id,
        )
        return event

    # ── 7b. Forward (only to consent-satisfied destinations) ─────────────────
    errors: list[str] = []
    forwarded = 0

    for dest in satisfied_dests:
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

    # GCS (Google Consent State) passthrough — best-effort Consent Mode v2.
    # When consent_signals is available, include the `gcs` query param so GA4
    # can apply consent-mode modelling.  This is the standard way to communicate
    # consent state to the Measurement Protocol.
    # Reference: https://developers.google.com/tag-platform/security/guides/consent
    signals: dict[str, bool] | None = getattr(event, "consent_signals", None)
    gcs_param = ""
    if signals is not None:
        ad_granted = signals.get("ad_storage", False)
        an_granted = signals.get("analytics_storage", False)
        if ad_granted and an_granted:
            gcs_param = "&gcs=G111"   # both granted
        elif an_granted:
            gcs_param = "&gcs=G101"   # analytics only
        elif ad_granted:
            gcs_param = "&gcs=G110"   # ad storage only
        else:
            gcs_param = "&gcs=G100"   # both denied

    url = (
        f"{_GA4_MP_URL}"
        f"?measurement_id={measurement_id}&api_secret={api_secret}{gcs_param}"
    )

    _post_json(url, body, headers={}, http_client=http_client)
    logger.info(
        "ga4_mp forward OK: event=%s measurement_id=%s gcs=%s",
        event.id,
        measurement_id,
        gcs_param.lstrip("&") or "not-set",
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
