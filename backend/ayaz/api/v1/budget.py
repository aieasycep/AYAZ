"""Aylık Bütçe Planlayıcısı — M12 REST API.

Tenant-scoped endpoints (require JWT with ``tid`` claim):

    POST   /budget/preview               — live allocation preview (no DB write)
    POST   /budget/plans                 — create a budget plan (stores snapshot)
    GET    /budget/plans                 — list plans (most recent first)
    GET    /budget/plans/{id}            — get one plan
    PATCH  /budget/plans/{id}            — update plan (recomputes if params changed)
    DELETE /budget/plans/{id}            — delete plan (204)
    POST   /budget/plans/{id}/recompute  — recompute allocation from current params

All monetary values in the allocation response are plain floats.
Share values are 0-100 percentages rounded to 1 decimal place.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.models.budget import BudgetPlan, VALID_OBJECTIVES, VALID_STATUSES
from ayaz.services.budget_planner import allocate_budget

router = APIRouter(prefix="/budget", tags=["budget"])

# ── Regex for period_month validation ─────────────────────────────────────────

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


# ── Ownership guard (mirrors _require_source in tracking.py) ─────────────────


def _require_plan(
    plan_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> BudgetPlan:
    """Return the BudgetPlan row or raise HTTP 404.

    Filters by both ``id`` and ``tenant_id`` to enforce tenant isolation.
    """
    plan = db.scalar(
        select(BudgetPlan).where(
            BudgetPlan.id == plan_id,
            BudgetPlan.tenant_id == tenant_id,
        )
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bütçe planı bulunamadı.",
        )
    return plan


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class BudgetPreviewRequest(BaseModel):
    """Request body for POST /budget/preview."""

    total_budget: float
    objective: str = "balanced"
    lookback_days: int = 90
    currency: str = "TRY"

    @field_validator("total_budget")
    @classmethod
    def total_budget_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("total_budget 0'dan büyük olmalıdır.")
        return v

    @field_validator("objective")
    @classmethod
    def objective_valid(cls, v: str) -> str:
        if v not in VALID_OBJECTIVES:
            raise ValueError(
                f"objective şu değerlerden biri olmalıdır: {sorted(VALID_OBJECTIVES)}"
            )
        return v


class BudgetPlanCreate(BaseModel):
    """Request body for POST /budget/plans."""

    name: str
    period_month: str
    total_budget: float
    objective: str = "balanced"
    lookback_days: int = 90
    currency: str = "TRY"

    @field_validator("total_budget")
    @classmethod
    def total_budget_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("total_budget 0'dan büyük olmalıdır.")
        return v

    @field_validator("period_month")
    @classmethod
    def period_month_format(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period_month 'YYYY-AA' formatında olmalıdır (ör. '2026-07').")
        return v

    @field_validator("objective")
    @classmethod
    def objective_valid(cls, v: str) -> str:
        if v not in VALID_OBJECTIVES:
            raise ValueError(
                f"objective şu değerlerden biri olmalıdır: {sorted(VALID_OBJECTIVES)}"
            )
        return v


class BudgetPlanPatch(BaseModel):
    """Request body for PATCH /budget/plans/{id}.

    When total_budget, objective, or lookback_days changes AND no explicit
    allocations dict is provided, the allocation is recomputed automatically.
    """

    name: str | None = None
    status: str | None = None
    total_budget: float | None = None
    objective: str | None = None
    lookback_days: int | None = None
    allocations: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @field_validator("total_budget")
    @classmethod
    def total_budget_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("total_budget 0'dan büyük olmalıdır.")
        return v

    @field_validator("objective")
    @classmethod
    def objective_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_OBJECTIVES:
            raise ValueError(
                f"objective şu değerlerden biri olmalıdır: {sorted(VALID_OBJECTIVES)}"
            )
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(
                f"status şu değerlerden biri olmalıdır: {sorted(VALID_STATUSES)}"
            )
        return v


class BudgetPlanResponse(BaseModel):
    """API response shape for a BudgetPlan row."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    period_month: str
    total_budget: float
    currency: str
    objective: str
    lookback_days: int
    allocations: dict[str, Any] | None
    status: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: BudgetPlan) -> "BudgetPlanResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            period_month=obj.period_month,
            total_budget=float(obj.total_budget),
            currency=obj.currency,
            objective=obj.objective,
            lookback_days=obj.lookback_days,
            allocations=obj.allocations,
            status=obj.status,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/preview",
    summary="Bütçe dağılımını önizle (kaydetmez)",
)
def preview_allocation(
    body: BudgetPreviewRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Compute and return a budget allocation without persisting anything.

    Useful for live UI previews where the user is still tweaking parameters.
    The response shape matches the ``allocations`` JSON snapshot stored on a
    saved plan.
    """
    result = allocate_budget(
        db,
        membership.tenant_id,
        total_budget=body.total_budget,
        objective=body.objective,
        lookback_days=body.lookback_days,
        currency=body.currency,
    )
    return result


@router.post(
    "/plans",
    response_model=BudgetPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni bütçe planı oluştur (dağılımı hesaplar ve snapshot olarak kaydeder)",
)
def create_plan(
    body: BudgetPlanCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BudgetPlanResponse:
    """Create a new BudgetPlan, compute the allocation, store the snapshot."""
    allocation = allocate_budget(
        db,
        membership.tenant_id,
        total_budget=body.total_budget,
        objective=body.objective,
        lookback_days=body.lookback_days,
        currency=body.currency,
    )
    plan = BudgetPlan(
        tenant_id=membership.tenant_id,
        name=body.name,
        period_month=body.period_month,
        total_budget=body.total_budget,
        currency=body.currency,
        objective=body.objective,
        lookback_days=body.lookback_days,
        allocations=allocation,
        status="draft",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return BudgetPlanResponse.from_orm_obj(plan)


@router.get(
    "/plans",
    response_model=list[BudgetPlanResponse],
    summary="Kiracıya ait bütçe planlarını listele (en yeni önce)",
)
def list_plans(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[BudgetPlanResponse]:
    rows = list(
        db.scalars(
            select(BudgetPlan)
            .where(BudgetPlan.tenant_id == membership.tenant_id)
            .order_by(BudgetPlan.created_at.desc())
        )
    )
    return [BudgetPlanResponse.from_orm_obj(r) for r in rows]


@router.get(
    "/plans/{plan_id}",
    response_model=BudgetPlanResponse,
    summary="Bütçe planını getir",
)
def get_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BudgetPlanResponse:
    plan = _require_plan(plan_id, membership.tenant_id, db)
    return BudgetPlanResponse.from_orm_obj(plan)


@router.patch(
    "/plans/{plan_id}",
    response_model=BudgetPlanResponse,
    summary="Bütçe planını güncelle; parametreler değiştiyse dağılımı yeniden hesapla",
)
def patch_plan(
    plan_id: uuid.UUID,
    body: BudgetPlanPatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BudgetPlanResponse:
    """Update plan fields.

    If ``total_budget``, ``objective``, or ``lookback_days`` changed AND the
    caller did NOT supply an explicit ``allocations`` value, the allocation is
    recomputed automatically from the plan's new parameters.
    """
    plan = _require_plan(plan_id, membership.tenant_id, db)

    recompute_fields = {"total_budget", "objective", "lookback_days"}
    changed_params = recompute_fields & body.model_fields_set
    explicit_allocations = "allocations" in body.model_fields_set

    if body.name is not None:
        plan.name = body.name
    if body.status is not None:
        plan.status = body.status
    if body.total_budget is not None:
        plan.total_budget = body.total_budget
    if body.objective is not None:
        plan.objective = body.objective
    if body.lookback_days is not None:
        plan.lookback_days = body.lookback_days
    if explicit_allocations:
        plan.allocations = body.allocations

    # Auto-recompute when allocation-affecting params changed, unless caller
    # explicitly provided an allocations payload.
    if changed_params and not explicit_allocations:
        allocation = allocate_budget(
            db,
            membership.tenant_id,
            total_budget=float(plan.total_budget),
            objective=plan.objective,
            lookback_days=plan.lookback_days,
            currency=plan.currency,
        )
        plan.allocations = allocation

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return BudgetPlanResponse.from_orm_obj(plan)


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bütçe planını sil",
)
def delete_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    plan = _require_plan(plan_id, membership.tenant_id, db)
    db.delete(plan)
    db.commit()


@router.post(
    "/plans/{plan_id}/recompute",
    response_model=BudgetPlanResponse,
    summary="Planın mevcut parametrelerine göre dağılımı yeniden hesapla ve kaydet",
)
def recompute_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BudgetPlanResponse:
    """Recompute the allocation snapshot using the plan's stored parameters."""
    plan = _require_plan(plan_id, membership.tenant_id, db)
    allocation = allocate_budget(
        db,
        membership.tenant_id,
        total_budget=float(plan.total_budget),
        objective=plan.objective,
        lookback_days=plan.lookback_days,
        currency=plan.currency,
    )
    plan.allocations = allocation
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return BudgetPlanResponse.from_orm_obj(plan)
