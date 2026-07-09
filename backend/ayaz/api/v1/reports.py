"""Advanced Reporting API — M3+.

Tenant-scoped endpoints (require auth JWT with ``tid`` claim):

    GET    /reports/definitions                          — list definitions
    POST   /reports/definitions                          — create definition
    GET    /reports/definitions/{id}                     — get one definition
    PATCH  /reports/definitions/{id}                     — update definition
    DELETE /reports/definitions/{id}                     — delete definition
    GET    /reports/definitions/{id}/preview             — JSON payload preview
    POST   /reports/definitions/{id}/share               — create a SharedReport

    GET    /reports/schedules                            — list schedules
    POST   /reports/schedules                            — create schedule
    GET    /reports/schedules/{id}                       — get one schedule
    PATCH  /reports/schedules/{id}                       — update schedule
    DELETE /reports/schedules/{id}                       — delete schedule

    GET    /reports/shares                               — list SharedReports
    DELETE /reports/shares/{id}                         — revoke SharedReport

Public (no auth — token is the secret):

    GET /reports/public/{public_token}                   — white-label HTML report

Public URL scheme
-----------------
    https://<host>/api/v1/reports/public/<public_token>

The public_token is a 32-byte urlsafe random string generated at share-creation
time and acts as the sole secret — no auth required.  Users paste or embed this
URL in client communications.  The response is text/html (white-label branded).

Notes for team lead
-------------------
Wire ``reports.router`` into main.py::

    from ayaz.api.v1 import reports as reports_module
    app.include_router(reports_module.router, prefix="/api/v1")
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.config import settings
from ayaz.models.oltp import Membership
from ayaz.models.reports import ReportDefinition, ReportSchedule, SharedReport
from ayaz.security.rate_limit import rate_limit
from ayaz.services.reports import build_report_payload, render_report_html

router = APIRouter(prefix="/reports", tags=["reports"])

# ── Valid values ──────────────────────────────────────────────────────────────

VALID_CADENCES = frozenset({"daily", "weekly", "monthly"})
VALID_DELIVERIES = frozenset({"email"})
VALID_SECTIONS = frozenset({"totals", "by_channel", "timeseries", "insights"})


# ── Helper: 404 guard ─────────────────────────────────────────────────────────


def _require_definition(
    definition_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: Session,
) -> ReportDefinition:
    obj = db.scalar(
        select(ReportDefinition).where(
            ReportDefinition.id == definition_id,
            ReportDefinition.tenant_id == tenant_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rapor tanımı bulunamadı.",
        )
    return obj


def _require_schedule(
    schedule_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: Session,
) -> ReportSchedule:
    obj = db.scalar(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id,
            ReportSchedule.tenant_id == tenant_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rapor zamanlaması bulunamadı.",
        )
    return obj


def _require_share(
    share_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: Session,
) -> SharedReport:
    obj = db.scalar(
        select(SharedReport).where(
            SharedReport.id == share_id,
            SharedReport.tenant_id == tenant_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paylaşılan rapor bulunamadı.",
        )
    return obj


# ── Pydantic schemas — ReportDefinition ──────────────────────────────────────


class ReportDefinitionCreate(BaseModel):
    name: str
    config: dict = {}


class ReportDefinitionPatch(BaseModel):
    name: str | None = None
    config: dict | None = None


class ReportDefinitionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    config: dict
    created_by: uuid.UUID | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: ReportDefinition) -> "ReportDefinitionResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            config=obj.config,
            created_by=obj.created_by,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


# ── Pydantic schemas — ReportSchedule ────────────────────────────────────────


class ReportScheduleCreate(BaseModel):
    report_definition_id: uuid.UUID
    cadence: str
    weekday: int | None = None
    hour: int = 8
    delivery: str = "email"
    recipients: list[str] = []

    @field_validator("cadence")
    @classmethod
    def validate_cadence(cls, v: str) -> str:
        if v not in VALID_CADENCES:
            raise ValueError(f"cadence must be one of {sorted(VALID_CADENCES)}")
        return v

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str) -> str:
        if v not in VALID_DELIVERIES:
            raise ValueError(f"delivery must be one of {sorted(VALID_DELIVERIES)}")
        return v

    @field_validator("hour")
    @classmethod
    def validate_hour(cls, v: int) -> int:
        if not (0 <= v <= 23):
            raise ValueError("hour must be 0-23")
        return v

    @field_validator("weekday")
    @classmethod
    def validate_weekday(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 6):
            raise ValueError("weekday must be 0 (Mon) to 6 (Sun)")
        return v


class ReportSchedulePatch(BaseModel):
    cadence: str | None = None
    weekday: int | None = None
    hour: int | None = None
    delivery: str | None = None
    recipients: list[str] | None = None
    is_active: bool | None = None

    @field_validator("cadence")
    @classmethod
    def validate_cadence(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CADENCES:
            raise ValueError(f"cadence must be one of {sorted(VALID_CADENCES)}")
        return v

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_DELIVERIES:
            raise ValueError(f"delivery must be one of {sorted(VALID_DELIVERIES)}")
        return v


class ReportScheduleResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    report_definition_id: uuid.UUID
    cadence: str
    weekday: int | None
    hour: int
    delivery: str
    recipients: list[str]
    is_active: bool
    last_sent_at: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: ReportSchedule) -> "ReportScheduleResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            report_definition_id=obj.report_definition_id,
            cadence=obj.cadence,
            weekday=obj.weekday,
            hour=obj.hour,
            delivery=obj.delivery,
            recipients=list(obj.recipients or []),
            is_active=obj.is_active,
            last_sent_at=obj.last_sent_at,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


# ── Pydantic schemas — SharedReport ──────────────────────────────────────────


class ShareCreate(BaseModel):
    expires_at: str | None = None  # ISO-8601 UTC datetime string, optional


class SharedReportResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    report_definition_id: uuid.UUID
    public_token: str
    public_url: str
    expires_at: str | None
    is_active: bool
    view_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: SharedReport, base_url: str = "") -> "SharedReportResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            report_definition_id=obj.report_definition_id,
            public_token=obj.public_token,
            public_url=f"{base_url}/api/v1/reports/public/{obj.public_token}",
            expires_at=obj.expires_at,
            is_active=obj.is_active,
            view_count=obj.view_count,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


# ── ReportDefinition CRUD ─────────────────────────────────────────────────────


@router.get(
    "/definitions",
    response_model=list[ReportDefinitionResponse],
    summary="List all report definitions for the current tenant",
)
def list_definitions(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[ReportDefinitionResponse]:
    rows = list(
        db.scalars(
            select(ReportDefinition).where(
                ReportDefinition.tenant_id == membership.tenant_id
            )
        )
    )
    return [ReportDefinitionResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/definitions",
    response_model=ReportDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new report definition",
)
def create_definition(
    body: ReportDefinitionCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportDefinitionResponse:
    obj = ReportDefinition(
        tenant_id=membership.tenant_id,
        name=body.name,
        config=body.config,
        created_by=membership.user_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ReportDefinitionResponse.from_orm_obj(obj)


@router.get(
    "/definitions/{definition_id}",
    response_model=ReportDefinitionResponse,
    summary="Get one report definition",
)
def get_definition(
    definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportDefinitionResponse:
    obj = _require_definition(definition_id, membership.tenant_id, db)
    return ReportDefinitionResponse.from_orm_obj(obj)


@router.patch(
    "/definitions/{definition_id}",
    response_model=ReportDefinitionResponse,
    summary="Update a report definition",
)
def patch_definition(
    definition_id: uuid.UUID,
    body: ReportDefinitionPatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportDefinitionResponse:
    obj = _require_definition(definition_id, membership.tenant_id, db)
    if body.name is not None:
        obj.name = body.name
    if body.config is not None:
        obj.config = body.config
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ReportDefinitionResponse.from_orm_obj(obj)


@router.delete(
    "/definitions/{definition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report definition and all its schedules and shares",
)
def delete_definition(
    definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    obj = _require_definition(definition_id, membership.tenant_id, db)
    db.delete(obj)
    db.commit()


# ── Preview (JSON payload) ────────────────────────────────────────────────────


@router.get(
    "/definitions/{definition_id}/preview",
    summary="Preview the JSON report payload for a date range (no HTML rendering)",
)
def preview_definition(
    definition_id: uuid.UUID,
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict:
    """Return the structured report payload as JSON (no HTML rendering).

    Useful for debugging or for custom frontend rendering.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be <= date_to",
        )
    obj = _require_definition(definition_id, membership.tenant_id, db)
    return build_report_payload(db, obj, date_from, date_to)


# ── Share (create shareable link) ─────────────────────────────────────────────


@router.post(
    "/definitions/{definition_id}/share",
    response_model=SharedReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shareable public link for a report definition",
)
def share_definition(
    definition_id: uuid.UUID,
    body: ShareCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SharedReportResponse:
    """Generate a public token for this report definition.

    The returned ``public_url`` can be shared directly with clients.  The link
    renders the white-label HTML report (no authentication required).

    Optionally set ``expires_at`` (ISO-8601 UTC) to make the link time-limited.
    """
    obj = _require_definition(definition_id, membership.tenant_id, db)

    share = SharedReport(
        tenant_id=membership.tenant_id,
        report_definition_id=obj.id,
        public_token=secrets.token_urlsafe(32),
        expires_at=body.expires_at,
        is_active=True,
        view_count=0,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return SharedReportResponse.from_orm_obj(share)


# ── ReportSchedule CRUD ───────────────────────────────────────────────────────


@router.get(
    "/schedules",
    response_model=list[ReportScheduleResponse],
    summary="List all report schedules for the current tenant",
)
def list_schedules(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[ReportScheduleResponse]:
    rows = list(
        db.scalars(
            select(ReportSchedule).where(
                ReportSchedule.tenant_id == membership.tenant_id
            )
        )
    )
    return [ReportScheduleResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/schedules",
    response_model=ReportScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new report schedule",
)
def create_schedule(
    body: ReportScheduleCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportScheduleResponse:
    # Ensure the definition belongs to this tenant
    _require_definition(body.report_definition_id, membership.tenant_id, db)

    sched = ReportSchedule(
        tenant_id=membership.tenant_id,
        report_definition_id=body.report_definition_id,
        cadence=body.cadence,
        weekday=body.weekday,
        hour=body.hour,
        delivery=body.delivery,
        recipients=body.recipients,
        is_active=True,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return ReportScheduleResponse.from_orm_obj(sched)


@router.get(
    "/schedules/{schedule_id}",
    response_model=ReportScheduleResponse,
    summary="Get one report schedule",
)
def get_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportScheduleResponse:
    sched = _require_schedule(schedule_id, membership.tenant_id, db)
    return ReportScheduleResponse.from_orm_obj(sched)


@router.patch(
    "/schedules/{schedule_id}",
    response_model=ReportScheduleResponse,
    summary="Update a report schedule",
)
def patch_schedule(
    schedule_id: uuid.UUID,
    body: ReportSchedulePatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ReportScheduleResponse:
    sched = _require_schedule(schedule_id, membership.tenant_id, db)
    if body.cadence is not None:
        sched.cadence = body.cadence
    if body.weekday is not None:
        sched.weekday = body.weekday
    if body.hour is not None:
        sched.hour = body.hour
    if body.delivery is not None:
        sched.delivery = body.delivery
    if body.recipients is not None:
        sched.recipients = body.recipients
    if body.is_active is not None:
        sched.is_active = body.is_active
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return ReportScheduleResponse.from_orm_obj(sched)


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report schedule",
)
def delete_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    sched = _require_schedule(schedule_id, membership.tenant_id, db)
    db.delete(sched)
    db.commit()


# ── SharedReport list/revoke ──────────────────────────────────────────────────


@router.get(
    "/shares",
    response_model=list[SharedReportResponse],
    summary="List all shared report links for the current tenant",
)
def list_shares(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[SharedReportResponse]:
    rows = list(
        db.scalars(
            select(SharedReport).where(
                SharedReport.tenant_id == membership.tenant_id
            )
        )
    )
    return [SharedReportResponse.from_orm_obj(r) for r in rows]


@router.delete(
    "/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a shared report link",
)
def revoke_share(
    share_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Set is_active=False on the SharedReport (soft revoke).

    The public token continues to exist in the DB but the public endpoint
    will return 404.  Hard-delete is available if the team lead wants it later.
    """
    share = _require_share(share_id, membership.tenant_id, db)
    share.is_active = False
    db.add(share)
    db.commit()


# ── Public white-label endpoint (no auth) ─────────────────────────────────────


@router.get(
    "/public/{public_token}",
    summary="Serve the white-label client report (no auth — token is the secret)",
    include_in_schema=True,
    response_class=HTMLResponse,
)
def public_report(
    public_token: str,
    request: Request,
    date_from: Annotated[
        date | None,
        Query(description="Inclusive start date (YYYY-MM-DD); defaults to 30 days ago"),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Inclusive end date (YYYY-MM-DD); defaults to today"),
    ] = None,
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "reports:public",
            limit=settings.rate_limit_public_limit,
            window_seconds=settings.rate_limit_public_window,
        )
    ),
) -> HTMLResponse:
    """Return the rendered white-label HTML report for the given public token.

    This endpoint requires NO authentication.  The public_token is a 32-byte
    urlsafe random string generated at share creation time and is the sole
    secret.

    The response is ``text/html`` — the complete self-contained branded report
    the client sees in their browser.

    Behavior:
    - 404 if the token is unknown, is_active=False, or has expired.
    - view_count is incremented atomically on each access.
    - date_from/date_to default to last 30 days when not provided.
    """
    share = db.scalar(
        select(SharedReport).where(
            SharedReport.public_token == public_token,
        )
    )

    if share is None or not share.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rapor bulunamadı veya devre dışı bırakıldı.",
        )

    # Check expiry
    if share.expires_at is not None:
        try:
            expires_dt = datetime.fromisoformat(
                share.expires_at.replace("Z", "+00:00")
            )
            # The field contract is "ISO-8601 UTC"; a naive value (no offset)
            # is interpreted as UTC so the comparison below never raises a
            # TypeError on aware-vs-naive operands.
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_dt:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Bu rapor linki süresi doldu.",
                )
        except ValueError:
            pass  # Malformed expires_at — treat as no expiry

    # Increment view counter
    share.view_count = (share.view_count or 0) + 1
    db.add(share)
    db.commit()

    # Resolve date range
    today = datetime.now(timezone.utc).date()
    from datetime import timedelta
    resolved_date_to = date_to or today
    resolved_date_from = date_from or (resolved_date_to - timedelta(days=29))

    # Load definition (may have been deleted — guard gracefully)
    defn = db.get(ReportDefinition, share.report_definition_id)
    if defn is None or defn.tenant_id != share.tenant_id:
        # Tenant-isolation guard: never render a definition that does not belong
        # to the same tenant as the share (defence-in-depth against a stale FK).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rapor tanımı artık mevcut değil.",
        )

    payload = build_report_payload(db, defn, resolved_date_from, resolved_date_to)
    html_content = render_report_html(payload, payload["branding"])

    return HTMLResponse(content=html_content, status_code=200)
