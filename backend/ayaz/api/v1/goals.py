"""Goal Tracking & Forecasting API — /api/v1/goals.

Endpoints
---------
GET    /goals                    List active goals for the tenant.
POST   /goals                    Create a new goal.
GET    /goals/{id}               Fetch a single goal (with optional progress).
PATCH  /goals/{id}               Update goal fields.
DELETE /goals/{id}               Hard-delete a goal.
GET    /goals/{id}/progress      Pacing, forecast, and Turkish recommendation.

Auth
----
All endpoints require a valid JWT Bearer token.  Tenant context is resolved
via ``get_current_membership``; every service call is explicitly scoped to
``membership.tenant_id`` to enforce isolation.

Numbers
-------
Numeric fields are returned as JSON numbers (float).  ``pct_to_target`` and
``forecast_value`` are computed floats from the service layer.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.goals import (
    ALL_METRICS,
    VALID_PERIODS,
    compute_progress,
    create_goal,
    delete_goal,
    get_goal,
    list_goals,
    update_goal,
)

router = APIRouter(prefix="/goals", tags=["goals"])


# ── Request / Response schemas ────────────────────────────────────────────────


class GoalCreate(BaseModel):
    """Request body for creating a goal."""

    name: str = Field(..., min_length=1, max_length=255)
    metric: str = Field(
        ..., description="spend | roas | conversions | conversion_value"
    )
    target_value: float = Field(..., gt=0)
    period: str = Field("month", description="Tracking period grain (currently: month)")
    period_start: str = Field(..., description="ISO-8601 date: YYYY-MM-DD")
    period_end: str = Field(..., description="ISO-8601 date: YYYY-MM-DD")
    channel_filter: str | None = Field(
        None, description="dim_channel.key to restrict metric to; null = all channels"
    )
    is_active: bool = Field(True)


class GoalUpdate(BaseModel):
    """Request body for partial update (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    metric: str | None = None
    target_value: float | None = Field(None, gt=0)
    period: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    channel_filter: str | None = None
    is_active: bool | None = None


class GoalResponse(BaseModel):
    """Serialised Goal row."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    metric: str
    target_value: float
    period: str
    period_start: str
    period_end: str
    channel_filter: str | None
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ProgressResponse(BaseModel):
    """Pacing and forecast payload for a goal at a given date."""

    goal_id: uuid.UUID
    current_value: float
    target_value: float
    pct_to_target: float = Field(
        description="current_value / target_value (0–1+)"
    )
    days_elapsed: int
    days_total: int
    expected_pace_value: float = Field(
        description="Linear-target pace value to-date"
    )
    forecast_value: float = Field(
        description=(
            "Projected end-of-period value. "
            "Additive metrics: run-rate * days_total. "
            "ROAS: current period-average held constant."
        )
    )
    status: str = Field(
        description="on_track | at_risk | off_track"
    )
    recommendation: str = Field(description="Turkish actionable guidance")


def _goal_to_response(goal: Any) -> GoalResponse:
    """Map ORM Goal to GoalResponse, serialising datetimes to ISO strings."""
    return GoalResponse(
        id=goal.id,
        tenant_id=goal.tenant_id,
        name=goal.name,
        metric=goal.metric,
        target_value=float(goal.target_value),
        period=goal.period,
        period_start=goal.period_start,
        period_end=goal.period_end,
        channel_filter=goal.channel_filter,
        is_active=goal.is_active,
        created_at=goal.created_at.isoformat(),
        updated_at=goal.updated_at.isoformat(),
    )


def _validate_dates(period_start: str, period_end: str) -> None:
    """Parse and cross-validate date strings; raise HTTP 422 on error."""
    try:
        ps = date.fromisoformat(period_start)
        pe = date.fromisoformat(period_end)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid date format: {exc}",
        )
    if ps > pe:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="period_start must be <= period_end",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[GoalResponse],
    summary="List goals for the current tenant",
)
def list_goals_endpoint(
    active_only: Annotated[
        bool,
        Query(description="When true (default), only return is_active=True goals"),
    ] = True,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[GoalResponse]:
    """Return goals for the authenticated tenant.

    Pass ``active_only=false`` to include soft-deleted / inactive goals.
    Results are ordered by creation date descending.
    """
    goals = list_goals(db, membership.tenant_id, active_only=active_only)
    return [_goal_to_response(g) for g in goals]


@router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new goal",
)
def create_goal_endpoint(
    body: GoalCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> GoalResponse:
    """Create a goal for the authenticated tenant.

    ``metric`` must be one of: ``spend``, ``roas``, ``conversions``,
    ``conversion_value``.

    ``period`` must be ``"month"`` (only supported value currently).

    ``target_value`` must be positive.
    """
    if body.metric not in ALL_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid metric {body.metric!r}. Choose from: {sorted(ALL_METRICS)}",
        )
    if body.period not in VALID_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid period {body.period!r}. Choose from: {sorted(VALID_PERIODS)}",
        )
    _validate_dates(body.period_start, body.period_end)

    try:
        goal = create_goal(
            db=db,
            tenant_id=membership.tenant_id,
            name=body.name,
            metric=body.metric,
            target_value=body.target_value,
            period=body.period,
            period_start=body.period_start,
            period_end=body.period_end,
            channel_filter=body.channel_filter,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    db.commit()
    db.refresh(goal)
    return _goal_to_response(goal)


@router.get(
    "/{goal_id}",
    response_model=GoalResponse,
    summary="Fetch a single goal",
)
def get_goal_endpoint(
    goal_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> GoalResponse:
    """Return a single goal by ID, scoped to the current tenant."""
    goal = get_goal(db, membership.tenant_id, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found.",
        )
    return _goal_to_response(goal)


@router.patch(
    "/{goal_id}",
    response_model=GoalResponse,
    summary="Partially update a goal",
)
def update_goal_endpoint(
    goal_id: uuid.UUID,
    body: GoalUpdate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> GoalResponse:
    """Update one or more fields of an existing goal.

    Only the fields explicitly set in the request body are changed.
    """
    # Cross-validate dates if both provided
    ps = body.period_start
    pe = body.period_end
    if ps is not None and pe is not None:
        _validate_dates(ps, pe)

    updates = body.model_dump(exclude_none=True)
    try:
        goal = update_goal(db, membership.tenant_id, goal_id, **updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found.",
        )

    db.commit()
    db.refresh(goal)
    return _goal_to_response(goal)


@router.delete(
    "/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a goal",
)
def delete_goal_endpoint(
    goal_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Hard-delete a goal.  Returns 204 on success, 404 if not found."""
    found = delete_goal(db, membership.tenant_id, goal_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found.",
        )
    db.commit()


@router.get(
    "/{goal_id}/progress",
    response_model=ProgressResponse,
    summary="Pacing, forecast, and recommendation for a goal",
)
def goal_progress_endpoint(
    goal_id: uuid.UUID,
    as_of: Annotated[
        date | None,
        Query(
            description=(
                "Date to evaluate progress as of (YYYY-MM-DD). "
                "Defaults to today (UTC)."
            )
        ),
    ] = None,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ProgressResponse:
    """Return pacing data, a forecast, and a Turkish recommendation.

    The ``as_of`` query parameter sets the evaluation date.  When omitted,
    today's UTC date is used.

    Forecast semantics
    ------------------
    Additive metrics (spend, conversions, conversion_value):
        daily_rate = current_value / days_elapsed
        forecast   = daily_rate * days_total   (straight-line run-rate)

    Ratio metrics (roas):
        forecast = current ROAS held constant to period end

    Status thresholds
    -----------------
        on_track   forecast >= 95 % of target
        at_risk    80 % <= forecast < 95 % of target
        off_track  forecast < 80 % of target
    """
    goal = get_goal(db, membership.tenant_id, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found.",
        )

    evaluation_date = as_of if as_of is not None else date.today()

    payload = compute_progress(db=db, goal=goal, as_of_date=evaluation_date)

    return ProgressResponse(
        goal_id=payload.goal_id,
        current_value=payload.current_value,
        target_value=payload.target_value,
        pct_to_target=payload.pct_to_target,
        days_elapsed=payload.days_elapsed,
        days_total=payload.days_total,
        expected_pace_value=payload.expected_pace_value,
        forecast_value=payload.forecast_value,
        status=payload.status,
        recommendation=payload.recommendation,
    )
