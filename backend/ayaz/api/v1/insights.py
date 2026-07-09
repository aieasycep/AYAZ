"""Insights & Alerts API — M4.

Endpoints
---------
GET  /api/v1/insights
    List insights for the caller's tenant, optionally filtered by severity
    and/or status.  Ordered by score descending (highest priority first).

PATCH /api/v1/insights/{insight_id}
    Update an insight's status (seen | dismissed).

POST /api/v1/insights/generate
    Trigger on-demand insight generation for the caller's tenant.
    Uses the latest date with fact data as ``as_of_date``.
    Returns counts by severity.

GET  /api/v1/insights/alert-rules
    List all AlertRules for the tenant.

POST /api/v1/insights/alert-rules
    Create a new AlertRule.

GET  /api/v1/insights/alert-rules/{rule_id}
    Fetch a single AlertRule.

PATCH /api/v1/insights/alert-rules/{rule_id}
    Update an AlertRule (partial update).

DELETE /api/v1/insights/alert-rules/{rule_id}
    Delete an AlertRule.

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant context is resolved
via ``get_current_membership`` — every query explicitly filters by
``membership.tenant_id``.

Numbers
-------
``score`` is returned as a float.  All dates are ISO 8601 strings.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.analytics import FactDailyMetrics
from ayaz.models.insights import AlertRule, Insight
from ayaz.models.oltp import Membership
from ayaz.services.insights import generate_insights

router = APIRouter(prefix="/insights", tags=["insights"])


# ── Fixes schemas ─────────────────────────────────────────────────────────────


class FixActionOut(BaseModel):
    """One one-click fix action."""

    label: str
    action_type: str
    payload: dict[str, Any]


class FixSuggestionOut(BaseModel):
    """Root cause + fix list for a single insight."""

    insight_id: uuid.UUID
    root_cause: str
    fixes: list[FixActionOut]


class ApplyFixRequest(BaseModel):
    """Payload for POST /insights/{id}/fixes/apply."""

    action_type: str = Field(
        ...,
        description=(
            "One of: create_automation_rule | create_goal | "
            "view_campaign | dismiss_insight"
        ),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Ready-to-apply parameters for the action.",
    )


class ApplyFixResponse(BaseModel):
    """Result of applying a fix action."""

    action_type: str
    success: bool
    message: str
    entity_id: str | None = None
    entity_type: str | None = None


# ── Response schemas ──────────────────────────────────────────────────────────


class InsightOut(BaseModel):
    """Public representation of an Insight row."""

    id: uuid.UUID
    category: str
    severity: str
    title: str
    body: str
    metric: str
    channel: str | None
    entity_type: str | None
    entity_id: str | None
    entity_name: str | None
    period_start: date
    period_end: date
    status: str
    score: float
    data: dict[str, Any]
    created_at: Any  # datetime serialised as ISO string by Pydantic
    # Feedback fields (closed feedback loop — Dalga 46)
    applied_at: Any | None = None  # datetime or None
    reaction: str | None = None    # "up" | "down" | null

    model_config = {"from_attributes": True}


class InsightStatusUpdate(BaseModel):
    """Payload for PATCH /insights/{id}."""

    status: str = Field(
        ...,
        description="New status: 'seen' or 'dismissed'",
        pattern="^(seen|dismissed)$",
    )


class GenerateResponse(BaseModel):
    """Response for POST /insights/generate."""

    as_of_date: date
    new_info: int
    new_warning: int
    new_critical: int
    skipped: int


class AlertRuleOut(BaseModel):
    """Public representation of an AlertRule row."""

    id: uuid.UUID
    name: str
    metric: str
    comparator: str
    threshold: float | None
    channel_filter: str | None
    delivery: str
    destination: str | None
    is_active: bool
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class AlertRuleCreate(BaseModel):
    """Payload for POST /insights/alert-rules."""

    name: str = Field(..., max_length=200)
    metric: str = Field(..., max_length=50)
    comparator: str = Field(
        ...,
        pattern="^(pct_drop|pct_rise|below|above|anomaly)$",
    )
    threshold: float | None = None
    channel_filter: str | None = None
    delivery: str = Field(
        "none",
        pattern="^(email|slack|none)$",
    )
    destination: str | None = None
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    """Payload for PATCH /insights/alert-rules/{id} (all fields optional)."""

    name: str | None = Field(None, max_length=200)
    metric: str | None = Field(None, max_length=50)
    comparator: str | None = Field(
        None,
        pattern="^(pct_drop|pct_rise|below|above|anomaly)$",
    )
    threshold: float | None = None
    channel_filter: str | None = None
    delivery: str | None = Field(
        None,
        pattern="^(email|slack|none)$",
    )
    destination: str | None = None
    is_active: bool | None = None



class ApplyRecommendationRequest(BaseModel):
    """Payload for POST /insights/{id}/apply."""

    applied: bool = Field(
        ...,
        description="True to mark recommendation as applied (sets applied_at); False to clear it.",
    )


class ReactRequest(BaseModel):
    """Payload for POST /insights/{id}/react."""

    reaction: str | None = Field(
        ...,
        description="Thumbs feedback: 'up' | 'down' | null (null clears the reaction).",
    )

    model_config = {"from_attributes": True}

    def validate_reaction(self) -> None:
        """Raise ValueError if reaction is not a valid value."""
        if self.reaction is not None and self.reaction not in ("up", "down"):
            raise ValueError(f"Invalid reaction {self.reaction!r}; must be 'up', 'down', or null.")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_insight_or_404(
    db: Session, insight_id: uuid.UUID, tenant_id: uuid.UUID
) -> Insight:
    insight = db.scalar(
        select(Insight).where(
            Insight.id == insight_id,
            Insight.tenant_id == tenant_id,
        )
    )
    if insight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight bulunamadi.",
        )
    return insight


def _get_rule_or_404(
    db: Session, rule_id: uuid.UUID, tenant_id: uuid.UUID
) -> AlertRule:
    rule = db.scalar(
        select(AlertRule).where(
            AlertRule.id == rule_id,
            AlertRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert kuralı bulunamadı.",
        )
    return rule


def _latest_fact_date(db: Session, tenant_id: uuid.UUID) -> date | None:
    """Return the most recent date_key in fact_daily_metrics for the tenant."""
    return db.scalar(
        select(func.max(FactDailyMetrics.date_key)).where(
            FactDailyMetrics.tenant_id == tenant_id
        )
    )


# ── Insight endpoints ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[InsightOut],
    summary="List insights for the current tenant",
)
def list_insights(
    severity: Annotated[
        str | None,
        Query(description="Filter by severity: info | warning | critical"),
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by status: new | seen | dismissed"),
    ] = None,
    applied: Annotated[
        bool | None,
        Query(
            description=(
                "Filter by applied state: true = only applied recommendations "
                "(applied_at IS NOT NULL); false = only unapplied."
            )
        ),
    ] = None,
    reaction_filter: Annotated[
        str | None,
        Query(
            alias="reaction",
            description="Filter by reaction: 'up' | 'down'",
            pattern="^(up|down)$",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Maximum number of results (1–200)", ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[InsightOut]:
    """Return insights ordered by score descending (highest priority first).

    Optionally filter by ``severity``, ``status``, ``applied``, and/or ``reaction``.
    All filters are optional and backward compatible — omitting them returns all insights
    as before.
    """
    stmt = (
        select(Insight)
        .where(Insight.tenant_id == membership.tenant_id)
        .order_by(Insight.score.desc())
        .limit(limit)
    )
    if severity:
        stmt = stmt.where(Insight.severity == severity)
    if status_filter:
        stmt = stmt.where(Insight.status == status_filter)
    if applied is True:
        stmt = stmt.where(Insight.applied_at.isnot(None))
    elif applied is False:
        stmt = stmt.where(Insight.applied_at.is_(None))
    if reaction_filter:
        stmt = stmt.where(Insight.reaction == reaction_filter)

    rows = db.scalars(stmt).all()
    return [InsightOut.model_validate(r) for r in rows]


@router.patch(
    "/{insight_id}",
    response_model=InsightOut,
    summary="Update an insight's status (seen | dismissed)",
)
def update_insight_status(
    insight_id: uuid.UUID,
    payload: InsightStatusUpdate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> InsightOut:
    """Mark an insight as ``seen`` or ``dismissed``."""
    insight = _get_insight_or_404(db, insight_id, membership.tenant_id)
    insight.status = payload.status
    db.flush()
    db.refresh(insight)
    return InsightOut.model_validate(insight)


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Run insight generation for the current tenant",
)
def trigger_generate(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> GenerateResponse:
    """Run all detectors against the tenant's latest fact data.

    The ``as_of_date`` is automatically determined as the latest date present
    in ``fact_daily_metrics`` for this tenant.  If no data exists, returns
    all-zero counts.
    """
    tenant_id = membership.tenant_id
    as_of = _latest_fact_date(db, tenant_id)

    if as_of is None:
        return GenerateResponse(
            as_of_date=date.today(),
            new_info=0,
            new_warning=0,
            new_critical=0,
            skipped=0,
        )

    counts = generate_insights(db, tenant_id, as_of_date=as_of)
    db.commit()

    return GenerateResponse(
        as_of_date=as_of,
        new_info=counts.get("new_info", 0),
        new_warning=counts.get("new_warning", 0),
        new_critical=counts.get("new_critical", 0),
        skipped=counts.get("skipped", 0),
    )



@router.post(
    "/{insight_id}/apply",
    response_model=InsightOut,
    summary="Mark or unmark a recommendation as applied",
)
def apply_recommendation(
    insight_id: uuid.UUID,
    body: ApplyRecommendationRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> InsightOut:
    """Mark a recommendation as applied (sets applied_at to utcnow) or
    unmark it (clears applied_at to null).

    Tenant isolation: the insight must belong to the caller's tenant — 404 otherwise.
    """
    insight = _get_insight_or_404(db, insight_id, membership.tenant_id)
    if body.applied:
        insight.applied_at = datetime.now(timezone.utc)
    else:
        insight.applied_at = None
    db.flush()
    db.refresh(insight)
    db.commit()
    return InsightOut.model_validate(insight)


@router.post(
    "/{insight_id}/react",
    response_model=InsightOut,
    summary="Set or clear the thumbs reaction on an insight",
)
def react_to_insight(
    insight_id: uuid.UUID,
    body: ReactRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> InsightOut:
    """Set the user's thumbs reaction ('up' | 'down') or clear it (null).

    Tenant isolation: the insight must belong to the caller's tenant — 404 otherwise.
    Validation: reaction must be 'up', 'down', or null — 422 for any other value.
    """
    # Validate reaction value
    if body.reaction is not None and body.reaction not in ("up", "down"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Geçersiz reaksiyon: {body.reaction!r}. İzin verilenler: 'up', 'down' veya null.",
        )
    insight = _get_insight_or_404(db, insight_id, membership.tenant_id)
    insight.reaction = body.reaction
    db.flush()
    db.refresh(insight)
    db.commit()
    return InsightOut.model_validate(insight)


# ── AlertRule endpoints ───────────────────────────────────────────────────────


@router.get(
    "/alert-rules",
    response_model=list[AlertRuleOut],
    summary="List alert rules for the current tenant",
)
def list_alert_rules(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[AlertRuleOut]:
    """Return all AlertRules for the tenant, ordered by name."""
    rows = db.scalars(
        select(AlertRule)
        .where(AlertRule.tenant_id == membership.tenant_id)
        .order_by(AlertRule.name)
    ).all()
    return [AlertRuleOut.model_validate(r) for r in rows]


@router.post(
    "/alert-rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new alert rule",
)
def create_alert_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AlertRuleOut:
    """Create an AlertRule scoped to the caller's tenant."""
    rule = AlertRule(
        tenant_id=membership.tenant_id,
        name=payload.name,
        metric=payload.metric,
        comparator=payload.comparator,
        threshold=payload.threshold,
        channel_filter=payload.channel_filter,
        delivery=payload.delivery,
        destination=payload.destination,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.flush()
    db.refresh(rule)
    db.commit()
    return AlertRuleOut.model_validate(rule)


@router.get(
    "/alert-rules/{rule_id}",
    response_model=AlertRuleOut,
    summary="Fetch a single alert rule",
)
def get_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AlertRuleOut:
    """Return a single AlertRule by ID."""
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    return AlertRuleOut.model_validate(rule)


@router.patch(
    "/alert-rules/{rule_id}",
    response_model=AlertRuleOut,
    summary="Update an alert rule (partial update)",
)
def update_alert_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AlertRuleOut:
    """Apply a partial update to an AlertRule.

    Only fields explicitly set in the request body are updated.
    """
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)

    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(rule, field_name, value)

    db.flush()
    db.refresh(rule)
    db.commit()
    return AlertRuleOut.model_validate(rule)


@router.delete(
    "/alert-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert rule",
)
def delete_alert_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Permanently delete an AlertRule."""
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    db.delete(rule)
    db.flush()
    db.commit()


# ── Insight fixes endpoints ───────────────────────────────────────────────────


@router.get(
    "/{insight_id}/fixes",
    response_model=FixSuggestionOut,
    summary="Get root-cause explanation and one-click fix suggestions for an insight",
)
def get_insight_fixes(
    insight_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FixSuggestionOut:
    """Return a Turkish root-cause analysis and a list of one-click fix actions
    for the given insight.

    The insight must belong to the caller's tenant.  Tenant isolation is
    enforced by the WHERE clause in _get_insight_or_404.

    Fix actions are ready-to-apply; their payloads can be submitted to
    POST /insights/{id}/fixes/apply.
    """
    from ayaz.services.fixes import suggested_fixes_for_insight

    insight = _get_insight_or_404(db, insight_id, membership.tenant_id)
    suggestion = suggested_fixes_for_insight(db, membership.tenant_id, insight)

    return FixSuggestionOut(
        insight_id=suggestion.insight_id,
        root_cause=suggestion.root_cause,
        fixes=[
            FixActionOut(
                label=f.label,
                action_type=f.action_type,
                payload=f.payload,
            )
            for f in suggestion.fixes
        ],
    )


@router.post(
    "/{insight_id}/fixes/apply",
    response_model=ApplyFixResponse,
    summary="Apply a one-click fix action for an insight",
)
def apply_insight_fix(
    insight_id: uuid.UUID,
    body: ApplyFixRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ApplyFixResponse:
    """Execute a safe one-click fix action associated with an insight.

    Allowed action types:
    - ``create_automation_rule`` — persists an AutomationRule (no live ad write)
    - ``create_goal``            — persists a Goal
    - ``dismiss_insight``        — sets the insight status to 'dismissed'
    - ``view_campaign``          — no-op navigational (returns success)

    The insight must belong to the caller's tenant.  All entity creations are
    scoped to the same tenant.
    """
    from ayaz.services.fixes import apply_fix

    _ALLOWED = frozenset(
        {"create_automation_rule", "create_goal", "view_campaign", "dismiss_insight"}
    )
    if body.action_type not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Geçersiz eylem türü: {body.action_type!r}. "
                f"İzin verilenler: {sorted(_ALLOWED)}"
            ),
        )

    insight = _get_insight_or_404(db, insight_id, membership.tenant_id)
    result = apply_fix(
        db=db,
        tenant_id=membership.tenant_id,
        insight=insight,
        action_type=body.action_type,
        payload=body.payload,
    )
    db.commit()

    return ApplyFixResponse(
        action_type=result.action_type,
        success=result.success,
        message=result.message,
        entity_id=result.entity_id,
        entity_type=result.entity_type,
    )
