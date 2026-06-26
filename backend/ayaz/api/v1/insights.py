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
from datetime import date
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
    limit: Annotated[
        int,
        Query(description="Maximum number of results (1–200)", ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[InsightOut]:
    """Return insights ordered by score descending (highest priority first).

    Optionally filter by ``severity`` and/or ``status``.
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
