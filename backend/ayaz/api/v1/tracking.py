"""Server-side Tracking / Conversions API — M7 (SignalSight-style).

Tenant-scoped endpoints (require JWT with ``tid`` claim):

    GET    /tracking/sources                          — list tracking sources
    POST   /tracking/sources                          — create a source
    GET    /tracking/sources/{id}                     — get one source
    PATCH  /tracking/sources/{id}                     — update a source
    DELETE /tracking/sources/{id}                     — delete a source
    GET    /tracking/sources/{id}/snippet             — JS snippet + collect URL
    GET    /tracking/sources/{id}/destinations        — list destinations
    POST   /tracking/sources/{id}/destinations        — create a destination
    GET    /tracking/destinations/{id}                — get one destination
    PATCH  /tracking/destinations/{id}                — update a destination
    DELETE /tracking/destinations/{id}                — delete a destination
    GET    /tracking/sources/{id}/events              — event log for a source

Public (no auth — token is the secret):

    POST /tracking/collect/{public_token}             — ingest a conversion event

Public URL scheme
-----------------
    https://<host>/api/v1/tracking/collect/<public_token>

The ``public_token`` is a URL-safe 32-byte random string generated at source
creation.  It is the sole secret protecting the collect endpoint — treat it
like an API key.  Rotate it by updating the TrackingSource.public_token.

Snippet
-------
``GET /tracking/sources/{id}/snippet`` returns a small JSON object with:

    collect_url:  The full POST endpoint URL to embed server-side or in a tag.
    js_snippet:   A minimal JavaScript loader that fires a ``page_view`` event.

The JS snippet is intentionally minimal — production users should extend it or
use a server-side call from their own backend.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.config import settings
from ayaz.models.oltp import Membership
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.security.rate_limit import rate_limit
from ayaz.services.tracking import ingest_event

router = APIRouter(prefix="/tracking", tags=["tracking"])

# ── Allowed platform values ───────────────────────────────────────────────────

_VALID_PLATFORMS = {"meta_capi", "tiktok_events", "ga4_mp"}


# ── Helper: require owned resources ──────────────────────────────────────────


def _require_source(
    source_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> TrackingSource:
    src = db.scalar(
        select(TrackingSource).where(
            TrackingSource.id == source_id,
            TrackingSource.tenant_id == tenant_id,
        )
    )
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking source not found.",
        )
    return src


def _require_destination(
    dest_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> EventDestination:
    dest = db.scalar(
        select(EventDestination).where(
            EventDestination.id == dest_id,
            EventDestination.tenant_id == tenant_id,
        )
    )
    if dest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event destination not found.",
        )
    return dest


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class TrackingSourceCreate(BaseModel):
    name: str
    domain: str | None = None


class TrackingSourcePatch(BaseModel):
    name: str | None = None
    domain: str | None = None
    is_active: bool | None = None


class TrackingSourceResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    domain: str | None
    public_token: str
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: TrackingSource) -> "TrackingSourceResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            domain=obj.domain,
            public_token=obj.public_token,
            is_active=obj.is_active,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class EventDestinationCreate(BaseModel):
    platform: str
    config: dict[str, Any] = {}
    vault_secret_ref: str = ""
    consent_required: bool = True

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v not in _VALID_PLATFORMS:
            raise ValueError(
                f"platform must be one of {sorted(_VALID_PLATFORMS)}"
            )
        return v


class EventDestinationPatch(BaseModel):
    platform: str | None = None
    config: dict[str, Any] | None = None
    vault_secret_ref: str | None = None
    consent_required: bool | None = None
    is_active: bool | None = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_PLATFORMS:
            raise ValueError(
                f"platform must be one of {sorted(_VALID_PLATFORMS)}"
            )
        return v


class EventDestinationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tracking_source_id: uuid.UUID
    platform: str
    config: dict[str, Any]
    vault_secret_ref: str
    consent_required: bool
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: EventDestination) -> "EventDestinationResponse":
        # Scrub any injected _secrets from the response — never expose to client
        safe_config = {
            k: v for k, v in obj.config.items() if k != "_secrets"
        }
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            tracking_source_id=obj.tracking_source_id,
            platform=obj.platform,
            config=safe_config,
            vault_secret_ref=obj.vault_secret_ref,
            consent_required=obj.consent_required,
            is_active=obj.is_active,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class ConversionEventResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tracking_source_id: uuid.UUID
    event_name: str
    event_time: str
    event_id: str
    user_data: dict[str, Any]
    custom_data: dict[str, Any]
    consent: bool
    status: str
    forwarded_count: int
    error: str | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: ConversionEvent) -> "ConversionEventResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            tracking_source_id=obj.tracking_source_id,
            event_name=obj.event_name,
            event_time=obj.event_time,
            event_id=obj.event_id,
            user_data=obj.user_data,
            custom_data=obj.custom_data,
            consent=obj.consent,
            status=obj.status,
            forwarded_count=obj.forwarded_count,
            error=obj.error,
            created_at=obj.created_at,
        )


class CollectResponse(BaseModel):
    status: str
    event_id: str


class SnippetResponse(BaseModel):
    collect_url: str
    js_snippet: str


# ── Stats response schemas ─────────────────────────────────────────────────────


class EventNameStat(BaseModel):
    event_name: str
    count: int
    errors: int
    enabled: bool  # True when event_name is NOT in source.disabled_events


class EventConfigBody(BaseModel):
    """Request body for the event-config toggle endpoint."""

    event_name: str
    enabled: bool


class EventConfigResponse(BaseModel):
    """Response for the event-config toggle endpoint."""

    disabled_events: list[str]


class DailyStat(BaseModel):
    date: str  # "YYYY-MM-DD"
    count: int
    errors: int


class StatsTotals(BaseModel):
    total_events: int
    total_errors: int
    by_status: dict[str, int]
    consent_blocked: int


class SourceStatsResponse(BaseModel):
    source_id: uuid.UUID
    date_from: str  # "YYYY-MM-DD"
    date_to: str    # "YYYY-MM-DD"
    totals: StatsTotals
    by_event: list[EventNameStat]
    daily: list[DailyStat]


# ── Pure stats aggregation helper (unit-testable without HTTP) ─────────────────


def compute_tracking_stats(
    events: list[ConversionEvent],
    date_from: date,
    date_to: date,
    disabled_events: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate a list of ConversionEvent objects into delivery-health stats.

    Parameters
    ----------
    events:
        All ConversionEvent rows for the source within [date_from, date_to],
        already filtered by the caller.
    date_from, date_to:
        Inclusive date range used to zero-fill the daily trend.
    disabled_events:
        List of event_name strings that are currently disabled on the source.
        When provided, each ``by_event`` entry gains an ``enabled`` field
        (True when the event_name is NOT in this list).  Defaults to ``[]``
        (all events enabled) when None.

    Returns
    -------
    dict matching SourceStatsResponse shape (without source_id/date fields).

    Status mapping
    --------------
    total_errors    = count where status == "failed"
    consent_blocked = count where status == "skipped_no_consent"
    """
    _disabled: set[str] = set(disabled_events) if disabled_events else set()
    # ── Totals ─────────────────────────────────────────────────────────────────
    total_events = len(events)
    total_errors = sum(1 for e in events if e.status == "failed")
    consent_blocked = sum(1 for e in events if e.status == "skipped_no_consent")

    by_status: dict[str, int] = {}
    for e in events:
        by_status[e.status] = by_status.get(e.status, 0) + 1

    # ── By event name ──────────────────────────────────────────────────────────
    event_counts: dict[str, int] = {}
    event_errors: dict[str, int] = {}
    for e in events:
        event_counts[e.event_name] = event_counts.get(e.event_name, 0) + 1
        if e.status == "failed":
            event_errors[e.event_name] = event_errors.get(e.event_name, 0) + 1

    by_event = sorted(
        [
            {
                "event_name": name,
                "count": cnt,
                "errors": event_errors.get(name, 0),
                "enabled": name not in _disabled,
            }
            for name, cnt in event_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    # ── Daily trend (zero-filled) ──────────────────────────────────────────────
    daily_counts: dict[str, int] = {}
    daily_errors: dict[str, int] = {}
    for e in events:
        # created_at is stored as ISO-8601 text; extract the date prefix
        try:
            day = e.created_at[:10]  # "YYYY-MM-DD"
        except (TypeError, IndexError):
            continue
        daily_counts[day] = daily_counts.get(day, 0) + 1
        if e.status == "failed":
            daily_errors[day] = daily_errors.get(day, 0) + 1

    daily: list[dict[str, Any]] = []
    current = date_from
    while current <= date_to:
        day_str = current.isoformat()
        daily.append(
            {
                "date": day_str,
                "count": daily_counts.get(day_str, 0),
                "errors": daily_errors.get(day_str, 0),
            }
        )
        current += timedelta(days=1)

    return {
        "totals": {
            "total_events": total_events,
            "total_errors": total_errors,
            "by_status": by_status,
            "consent_blocked": consent_blocked,
        },
        "by_event": by_event,
        "daily": daily,
    }


# ── TrackingSource CRUD ───────────────────────────────────────────────────────


@router.get(
    "/sources",
    response_model=list[TrackingSourceResponse],
    summary="List all tracking sources for the current tenant",
)
def list_sources(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[TrackingSourceResponse]:
    rows = list(
        db.scalars(
            select(TrackingSource).where(
                TrackingSource.tenant_id == membership.tenant_id
            )
        )
    )
    return [TrackingSourceResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/sources",
    response_model=TrackingSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tracking source (generates a public_token write key)",
)
def create_source(
    body: TrackingSourceCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> TrackingSourceResponse:
    src = TrackingSource(
        tenant_id=membership.tenant_id,
        name=body.name,
        domain=body.domain,
        public_token=secrets.token_urlsafe(32),
        is_active=True,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return TrackingSourceResponse.from_orm_obj(src)


@router.get(
    "/sources/{source_id}",
    response_model=TrackingSourceResponse,
    summary="Get one tracking source",
)
def get_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> TrackingSourceResponse:
    src = _require_source(source_id, membership.tenant_id, db)
    return TrackingSourceResponse.from_orm_obj(src)


@router.patch(
    "/sources/{source_id}",
    response_model=TrackingSourceResponse,
    summary="Update a tracking source",
)
def patch_source(
    source_id: uuid.UUID,
    body: TrackingSourcePatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> TrackingSourceResponse:
    src = _require_source(source_id, membership.tenant_id, db)
    if body.name is not None:
        src.name = body.name
    if body.domain is not None:
        src.domain = body.domain
    if body.is_active is not None:
        src.is_active = body.is_active
    db.add(src)
    db.commit()
    db.refresh(src)
    return TrackingSourceResponse.from_orm_obj(src)


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tracking source (and all its destinations and events)",
)
def delete_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    src = _require_source(source_id, membership.tenant_id, db)
    db.delete(src)
    db.commit()


@router.get(
    "/sources/{source_id}/snippet",
    response_model=SnippetResponse,
    summary="Return the collect URL and JS loader snippet for embedding",
)
def get_snippet(
    source_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SnippetResponse:
    """Return the collect URL and a minimal JS snippet.

    The ``collect_url`` is the full URL to POST events to.  The ``js_snippet``
    is a copy-pasteable JavaScript tag that fires a page_view event on load.
    The actual event payload should be extended server-side for richer data.
    """
    src = _require_source(source_id, membership.tenant_id, db)

    base_url = str(request.base_url).rstrip("/")
    collect_url = f"{base_url}/api/v1/tracking/collect/{src.public_token}"

    js_snippet = (
        f"<!-- AYAZ SignalSight — {src.name} -->\n"
        f"<script>\n"
        f"(function(){{ \n"
        f"  var _ayazCollect = '{collect_url}';\n"
        f"  fetch(_ayazCollect, {{\n"
        f"    method: 'POST',\n"
        f"    headers: {{'Content-Type': 'application/json'}},\n"
        f"    body: JSON.stringify({{\n"
        f"      event_name: 'PageView',\n"
        f"      event_time: new Date().toISOString(),\n"
        f"      event_id: crypto.randomUUID(),\n"
        f"      consent: false,\n"
        f"      user_data: {{}},\n"
        f"      custom_data: {{page: window.location.pathname}}\n"
        f"    }})\n"
        f"  }});\n"
        f"}})();\n"
        f"</script>"
    )

    return SnippetResponse(collect_url=collect_url, js_snippet=js_snippet)


@router.get(
    "/sources/{source_id}/events",
    response_model=list[ConversionEventResponse],
    summary="Event log for a tracking source (most recent first; filterable debug console)",
)
def list_events(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by event status (e.g. forwarded, failed, skipped_no_consent)",
    ),
    event_name: str | None = Query(
        default=None,
        description="Filter by event name (exact match, case-sensitive)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of events to return (default 100, max 500)",
    ),
) -> list[ConversionEventResponse]:
    src = _require_source(source_id, membership.tenant_id, db)
    q = (
        select(ConversionEvent)
        .where(ConversionEvent.tracking_source_id == src.id)
    )
    if status_filter is not None:
        q = q.where(ConversionEvent.status == status_filter)
    if event_name is not None:
        q = q.where(ConversionEvent.event_name == event_name)
    q = q.order_by(ConversionEvent.created_at.desc()).limit(limit)
    rows = list(db.scalars(q))
    return [ConversionEventResponse.from_orm_obj(r) for r in rows]


@router.get(
    "/sources/{source_id}/stats",
    response_model=SourceStatsResponse,
    summary=(
        "Delivery-health and per-event stats for a tracking source "
        "(SignalSight-style Event Configuration + tracker report)"
    ),
)
def get_source_stats(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: date | None = Query(
        default=None,
        description="Start date (inclusive, YYYY-MM-DD). Defaults to 30 days ago.",
    ),
    date_to: date | None = Query(
        default=None,
        description="End date (inclusive, YYYY-MM-DD). Defaults to today.",
    ),
) -> SourceStatsResponse:
    """Return aggregated delivery-health and per-event statistics for a source.

    Totals
    ------
    total_events    — all events ingested in the date range
    total_errors    — events with status == "failed"
    consent_blocked — events with status == "skipped_no_consent"
    by_status       — breakdown of all status values

    by_event
    --------
    Per-event-name counts and errors, sorted descending by count.
    Mirrors the SignalSight "Event Configuration" view.

    daily
    -----
    Day-by-day event and error counts, zero-filled across the full range,
    ascending by date.  Powers the trend sparkline.

    Date range
    ----------
    Uses ``created_at`` (ingest time, stored as ISO-8601 text).
    If omitted, defaults to the last 30 days.
    Returns 422 if date_from > date_to.
    Returns 404 if the source does not belong to the requesting tenant.
    """
    # ── Defaults and validation ────────────────────────────────────────────────
    today = datetime.now(timezone.utc).date()
    if date_from is None:
        date_from = today - timedelta(days=29)  # last 30 days inclusive
    if date_to is None:
        date_to = today

    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must not be later than date_to.",
        )

    # ── Tenant-scope check ─────────────────────────────────────────────────────
    src = _require_source(source_id, membership.tenant_id, db)

    # ── Fetch events in range ─────────────────────────────────────────────────
    # created_at is stored as ISO-8601 text ("YYYY-MM-DDTHH:MM:SS...").
    # String prefix comparison works correctly for ISO dates in SQLite and Postgres.
    date_from_str = date_from.isoformat()      # "YYYY-MM-DD"
    date_to_str = date_to.isoformat() + "T23:59:59"  # inclusive upper bound

    events = list(
        db.scalars(
            select(ConversionEvent).where(
                ConversionEvent.tracking_source_id == source_id,
                ConversionEvent.tenant_id == membership.tenant_id,
                ConversionEvent.created_at >= date_from_str,
                ConversionEvent.created_at <= date_to_str,
            )
        )
    )

    # ── Aggregate ─────────────────────────────────────────────────────────────
    agg = compute_tracking_stats(
        events, date_from, date_to, disabled_events=src.disabled_events or []
    )

    return SourceStatsResponse(
        source_id=source_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        totals=StatsTotals(**agg["totals"]),
        by_event=[EventNameStat(**e) for e in agg["by_event"]],
        daily=[DailyStat(**d) for d in agg["daily"]],
    )


# ── Per-event enable / disable toggle ────────────────────────────────────────


@router.post(
    "/sources/{source_id}/event-config",
    response_model=EventConfigResponse,
    summary=(
        "Enable or disable forwarding for a specific event name on a tracking source "
        "(SignalSight Event Configuration STATUS toggle)"
    ),
)
def set_event_config(
    source_id: uuid.UUID,
    body: EventConfigBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> EventConfigResponse:
    """Toggle per-event forwarding for a tracking source.

    When ``enabled=false`` the event_name is added to ``source.disabled_events``.
    When ``enabled=true`` it is removed.  The operation is idempotent — toggling
    the same state twice produces the same result.

    A disabled event is still **recorded** (persisted in conversion_events) but
    its status is set to ``"disabled"`` and it is NOT forwarded to any
    destination.  All other event names on the same source are unaffected.

    Returns the updated ``disabled_events`` list so the client can sync state.

    Raises
    ------
    404 – source does not belong to the current tenant
    422 – validation error on request body
    """
    src = _require_source(source_id, membership.tenant_id, db)

    # Work on a plain Python list; JSON column gives back a list already.
    disabled: list[str] = list(src.disabled_events or [])

    if body.enabled:
        # Enable: remove from disabled list if present
        disabled = [name for name in disabled if name != body.event_name]
    else:
        # Disable: add to list if not already present (idempotent)
        if body.event_name not in disabled:
            disabled.append(body.event_name)

    src.disabled_events = disabled
    db.add(src)
    db.commit()
    db.refresh(src)

    return EventConfigResponse(disabled_events=src.disabled_events or [])


# ── EventDestination CRUD ─────────────────────────────────────────────────────


@router.get(
    "/sources/{source_id}/destinations",
    response_model=list[EventDestinationResponse],
    summary="List event destinations for a tracking source",
)
def list_destinations(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[EventDestinationResponse]:
    _require_source(source_id, membership.tenant_id, db)
    rows = list(
        db.scalars(
            select(EventDestination).where(
                EventDestination.tracking_source_id == source_id,
                EventDestination.tenant_id == membership.tenant_id,
            )
        )
    )
    return [EventDestinationResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/sources/{source_id}/destinations",
    response_model=EventDestinationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event destination for a tracking source",
)
def create_destination(
    source_id: uuid.UUID,
    body: EventDestinationCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> EventDestinationResponse:
    _require_source(source_id, membership.tenant_id, db)
    dest = EventDestination(
        tenant_id=membership.tenant_id,
        tracking_source_id=source_id,
        platform=body.platform,
        config=body.config,
        vault_secret_ref=body.vault_secret_ref,
        consent_required=body.consent_required,
        is_active=True,
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return EventDestinationResponse.from_orm_obj(dest)


@router.get(
    "/destinations/{dest_id}",
    response_model=EventDestinationResponse,
    summary="Get one event destination",
)
def get_destination(
    dest_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> EventDestinationResponse:
    dest = _require_destination(dest_id, membership.tenant_id, db)
    return EventDestinationResponse.from_orm_obj(dest)


@router.patch(
    "/destinations/{dest_id}",
    response_model=EventDestinationResponse,
    summary="Update an event destination",
)
def patch_destination(
    dest_id: uuid.UUID,
    body: EventDestinationPatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> EventDestinationResponse:
    dest = _require_destination(dest_id, membership.tenant_id, db)
    if body.platform is not None:
        dest.platform = body.platform
    if body.config is not None:
        dest.config = body.config
    if body.vault_secret_ref is not None:
        dest.vault_secret_ref = body.vault_secret_ref
    if body.consent_required is not None:
        dest.consent_required = body.consent_required
    if body.is_active is not None:
        dest.is_active = body.is_active
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return EventDestinationResponse.from_orm_obj(dest)


@router.delete(
    "/destinations/{dest_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an event destination",
)
def delete_destination(
    dest_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    dest = _require_destination(dest_id, membership.tenant_id, db)
    db.delete(dest)
    db.commit()


# ── Public collect endpoint (no auth) ─────────────────────────────────────────


@router.post(
    "/collect/{public_token}",
    response_model=CollectResponse,
    summary="Ingest a server-side conversion event (public — token is the secret)",
    include_in_schema=True,
)
def collect(
    public_token: str,
    request: Request,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "tracking:collect",
            limit=settings.rate_limit_public_limit,
            window_seconds=settings.rate_limit_public_window,
        )
    ),
) -> CollectResponse:
    """Receive and ingest a server-side conversion event.

    This endpoint requires NO authentication.  The ``public_token`` in the URL
    is the sole secret — it acts as the write key for the tracking source.

    Returns HTTP 404 if the token is unknown or the source is inactive.

    On success returns ``{status, event_id}`` where ``status`` reflects the
    final disposition of the event (e.g. "forwarded", "skipped_no_consent",
    "duplicate").

    Rate limited: 120 requests/minute/IP (configurable via settings).
    """
    source = db.scalar(
        select(TrackingSource).where(
            TrackingSource.public_token == public_token,
            TrackingSource.is_active.is_(True),
        )
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking source not found or inactive.",
        )

    try:
        event = ingest_event(db, source, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return CollectResponse(status=event.status, event_id=event.event_id)
