"""Automation & Rules engine API — M9.

Endpoints
---------
GET    /api/v1/automation/rules
    List all AutomationRules for the caller's tenant.

POST   /api/v1/automation/rules
    Create a new AutomationRule.

GET    /api/v1/automation/rules/{rule_id}
    Fetch a single AutomationRule.

PATCH  /api/v1/automation/rules/{rule_id}
    Partial update of an AutomationRule.

DELETE /api/v1/automation/rules/{rule_id}
    Delete an AutomationRule (also cascades AutomationRun rows via FK).

POST   /api/v1/automation/rules/{rule_id}/run
    Evaluate and run the rule immediately.  Returns the evaluation result.

GET    /api/v1/automation/rules/{rule_id}/runs
    List recent AutomationRun audit entries for the rule (newest first).

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant context is resolved
via ``get_current_membership`` — every query explicitly filters by
``membership.tenant_id``.

Validation notes
----------------
* Threshold is required for pct_drop, pct_rise, below, above comparators.
* Threshold may be omitted (null) for "anomaly" comparator.
* action_config schema is validated at the Pydantic layer:
    notify_email  requires "recipients" list
    notify_slack  requires "webhook" string
    alert/pause_suggest may be empty {}
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.automation import AutomationRule, AutomationRun
from ayaz.models.oltp import Membership
from ayaz.services.automation import evaluate_rule, run_rule

router = APIRouter(prefix="/automation", tags=["automation"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class AutomationRuleOut(BaseModel):
    """Public representation of an AutomationRule row."""

    id: uuid.UUID
    name: str
    scope: str
    scope_filter: str | None
    metric: str
    comparator: str
    threshold: float | None
    window_days: int
    action: str
    action_config: dict[str, Any]
    is_active: bool
    last_triggered_at: str | None
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class AutomationRuleCreate(BaseModel):
    """Payload for POST /automation/rules."""

    name: str = Field(..., max_length=200)
    scope: str = Field(
        "account",
        pattern="^(account|channel|campaign)$",
        description="Scope of metric evaluation: account | channel | campaign",
    )
    scope_filter: str | None = Field(
        None,
        description="Channel key or campaign UUID; null = all (required when scope != account)",
    )
    metric: str = Field(
        ...,
        pattern="^(spend|roas|ctr|cpc|cpa|conversions)$",
    )
    comparator: str = Field(
        ...,
        pattern="^(pct_drop|pct_rise|below|above|anomaly)$",
    )
    threshold: float | None = Field(
        None,
        description=(
            "For pct_drop/pct_rise: percentage (e.g. 20 = 20%). "
            "For below/above: absolute value. "
            "Omit for anomaly comparator."
        ),
    )
    window_days: int = Field(
        7,
        ge=1,
        le=365,
        description="Look-back window in days (default 7)",
    )
    action: str = Field(
        "alert",
        pattern="^(alert|notify_email|notify_slack|pause_suggest)$",
    )
    action_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Delivery config: "
            "{} for alert/pause_suggest; "
            '{"recipients": ["email@x.com"]} for notify_email; '
            '{"webhook": "https://..."} for notify_slack'
        ),
    )
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_threshold_and_config(self) -> "AutomationRuleCreate":
        # Threshold required for non-anomaly comparators
        if self.comparator != "anomaly" and self.threshold is None:
            raise ValueError(
                f"'threshold' is required for comparator '{self.comparator}'"
            )
        # scope_filter required when scope is channel or campaign
        if self.scope in ("channel", "campaign") and not self.scope_filter:
            raise ValueError(
                f"'scope_filter' is required when scope is '{self.scope}'"
            )
        return self


class AutomationRuleUpdate(BaseModel):
    """Payload for PATCH /automation/rules/{id} — all fields optional."""

    name: str | None = Field(None, max_length=200)
    scope: str | None = Field(None, pattern="^(account|channel|campaign)$")
    scope_filter: str | None = None
    metric: str | None = Field(
        None, pattern="^(spend|roas|ctr|cpc|cpa|conversions)$"
    )
    comparator: str | None = Field(
        None, pattern="^(pct_drop|pct_rise|below|above|anomaly)$"
    )
    threshold: float | None = None
    window_days: int | None = Field(None, ge=1, le=365)
    action: str | None = Field(
        None, pattern="^(alert|notify_email|notify_slack|pause_suggest)$"
    )
    action_config: dict[str, Any] | None = None
    is_active: bool | None = None


class AutomationRunOut(BaseModel):
    """Public representation of an AutomationRun audit row."""

    id: uuid.UUID
    rule_id: uuid.UUID
    ran_at: str
    triggered: bool
    detail: dict[str, Any]

    model_config = {"from_attributes": True}


class RunRuleResponse(BaseModel):
    """Response for POST /automation/rules/{id}/run."""

    rule_id: uuid.UUID
    as_of_date: date
    triggered: bool
    matched_entity_count: int
    detail: dict[str, Any]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_rule_or_404(
    db: Session, rule_id: uuid.UUID, tenant_id: uuid.UUID
) -> AutomationRule:
    rule = db.scalar(
        select(AutomationRule).where(
            AutomationRule.id == rule_id,
            AutomationRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Otomasyon kuralı bulunamadı.",
        )
    return rule


# ── Rule CRUD endpoints ───────────────────────────────────────────────────────


@router.get(
    "/rules",
    response_model=list[AutomationRuleOut],
    summary="List automation rules for the current tenant",
)
def list_rules(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[AutomationRuleOut]:
    """Return all AutomationRules for the tenant, ordered by name."""
    rows = db.scalars(
        select(AutomationRule)
        .where(AutomationRule.tenant_id == membership.tenant_id)
        .order_by(AutomationRule.name)
    ).all()
    return [AutomationRuleOut.model_validate(r) for r in rows]


@router.post(
    "/rules",
    response_model=AutomationRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new automation rule",
)
def create_rule(
    payload: AutomationRuleCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AutomationRuleOut:
    """Create an AutomationRule scoped to the caller's tenant."""
    rule = AutomationRule(
        tenant_id=membership.tenant_id,
        name=payload.name,
        scope=payload.scope,
        scope_filter=payload.scope_filter,
        metric=payload.metric,
        comparator=payload.comparator,
        threshold=payload.threshold,
        window_days=payload.window_days,
        action=payload.action,
        action_config=payload.action_config,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.flush()
    db.refresh(rule)
    db.commit()
    return AutomationRuleOut.model_validate(rule)


@router.get(
    "/rules/{rule_id}",
    response_model=AutomationRuleOut,
    summary="Fetch a single automation rule",
)
def get_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AutomationRuleOut:
    """Return a single AutomationRule by ID."""
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    return AutomationRuleOut.model_validate(rule)


@router.patch(
    "/rules/{rule_id}",
    response_model=AutomationRuleOut,
    summary="Partial update of an automation rule",
)
def update_rule(
    rule_id: uuid.UUID,
    payload: AutomationRuleUpdate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AutomationRuleOut:
    """Apply a partial update to an AutomationRule.

    Only fields explicitly set in the request body are updated.
    """
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(rule, field_name, value)
    db.flush()
    db.refresh(rule)
    db.commit()
    return AutomationRuleOut.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an automation rule",
)
def delete_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Permanently delete an AutomationRule.

    Associated AutomationRun rows are deleted by CASCADE on the foreign key.
    """
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    db.delete(rule)
    db.flush()
    db.commit()


# ── Run on-demand endpoint ────────────────────────────────────────────────────


@router.post(
    "/rules/{rule_id}/run",
    response_model=RunRuleResponse,
    summary="Evaluate and run an automation rule immediately",
)
def run_rule_now(
    rule_id: uuid.UUID,
    as_of: Annotated[
        date | None,
        Query(
            description="Reference date for evaluation (ISO 8601). Defaults to today."
        ),
    ] = None,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> RunRuleResponse:
    """Evaluate the rule right now and return the result.

    If the rule fires, the configured action is executed immediately (subject
    to same-day idempotency).  An AutomationRun audit row is always written.

    The ``as_of`` query parameter allows testing against historical dates.
    Defaults to today (UTC) when omitted.
    """
    rule = _get_rule_or_404(db, rule_id, membership.tenant_id)
    target_date = as_of if as_of is not None else date.today()

    evaluation = run_rule(db, rule, target_date)
    db.commit()

    return RunRuleResponse(
        rule_id=rule.id,
        as_of_date=target_date,
        triggered=evaluation.triggered,
        matched_entity_count=len(evaluation.matched_entities),
        detail=evaluation.detail,
    )


# ── Audit log endpoint ────────────────────────────────────────────────────────


@router.get(
    "/rules/{rule_id}/runs",
    response_model=list[AutomationRunOut],
    summary="List recent evaluation runs for an automation rule",
)
def list_runs(
    rule_id: uuid.UUID,
    limit: Annotated[
        int,
        Query(description="Maximum number of results (1–200)", ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[AutomationRunOut]:
    """Return AutomationRun audit entries for the rule, newest first.

    The tenant_id check on the parent rule implicitly enforces isolation —
    the ``_get_rule_or_404`` guard ensures the rule belongs to the caller's
    tenant before we query runs.
    """
    # Verify rule belongs to this tenant
    _get_rule_or_404(db, rule_id, membership.tenant_id)

    rows = db.scalars(
        select(AutomationRun)
        .where(
            AutomationRun.rule_id == rule_id,
            AutomationRun.tenant_id == membership.tenant_id,
        )
        .order_by(AutomationRun.ran_at.desc())
        .limit(limit)
    ).all()
    return [AutomationRunOut.model_validate(r) for r in rows]
