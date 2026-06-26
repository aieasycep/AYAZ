"""Daily Briefing API — /api/v1/briefings.

Endpoints
---------
GET  /briefings          List briefings for the tenant (newest first).
GET  /briefings/latest   The most recent briefing, or 404 if none.
POST /briefings/generate Generate a briefing for the latest fact date (idempotent).

Auth
----
All endpoints require a valid JWT Bearer token.  Tenant context is resolved
via ``get_current_membership``; every service call is scoped to
``membership.tenant_id``.

Numbers
-------
All numeric values in the body JSON are already floats (serialised by the service
layer).  The body is returned as-is inside the BriefingResponse schema.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.briefing import Briefing
from ayaz.models.oltp import Membership

router = APIRouter(prefix="/briefings", tags=["briefings"])


# ── Response schema ───────────────────────────────────────────────────────────


class BriefingResponse(BaseModel):
    """Serialised Briefing row."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    briefing_date: str
    headline: str
    body: Any = Field(
        description=(
            "Structured JSON: performance_delta, top_insights, "
            "top_recommendation, goals_status"
        )
    )
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _to_response(b: Briefing) -> BriefingResponse:
    return BriefingResponse(
        id=b.id,
        tenant_id=b.tenant_id,
        briefing_date=b.briefing_date,
        headline=b.headline,
        body=b.body,
        created_at=b.created_at.isoformat(),
        updated_at=b.updated_at.isoformat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[BriefingResponse],
    summary="List daily briefings for the current tenant (newest first)",
)
def list_briefings(
    limit: int = Query(default=30, ge=1, le=100, description="Max rows to return"),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[BriefingResponse]:
    """Return up to ``limit`` briefings for the authenticated tenant, newest first."""
    rows = db.scalars(
        select(Briefing)
        .where(Briefing.tenant_id == membership.tenant_id)
        .order_by(desc(Briefing.briefing_date))
        .limit(limit)
    ).all()
    return [_to_response(b) for b in rows]


@router.get(
    "/latest",
    response_model=BriefingResponse,
    summary="Fetch the most recent briefing for the current tenant",
)
def get_latest_briefing(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BriefingResponse:
    """Return the most recent briefing.  Returns 404 when none have been generated."""
    row = db.scalar(
        select(Briefing)
        .where(Briefing.tenant_id == membership.tenant_id)
        .order_by(desc(Briefing.briefing_date))
        .limit(1)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No briefing found for this tenant.",
        )
    return _to_response(row)


@router.post(
    "/generate",
    response_model=BriefingResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate (or refresh) the briefing for the latest fact date",
)
def generate_briefing_endpoint(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BriefingResponse:
    """Trigger briefing generation for today (as_of=today).

    The operation is idempotent — calling it twice on the same day updates
    the existing row rather than creating a duplicate.

    The headline uses the Claude API when ``ANTHROPIC_API_KEY`` is configured;
    otherwise falls back to a deterministic Turkish template grounded in the
    actual numbers.
    """
    from ayaz.services.briefing import generate_briefing

    as_of = date.today()
    try:
        briefing = generate_briefing(db, membership.tenant_id, as_of_date=as_of)
        db.commit()
        db.refresh(briefing)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Briefing generation failed: {exc}",
        )
    return _to_response(briefing)
