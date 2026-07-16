"""Cross-channel Budget Optimizer API.

Endpoint
--------
GET /api/v1/optimizer/budget?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
                             [&max_shift_pct=0.20]

Given current spend and ROAS per channel for the requested date range, returns:
  * The current allocation (spend, ROAS, share-of-spend per channel).
  * Read-only reallocation suggestions: which channels to move budget from/to,
    how much to move, and a first-order estimate of the resulting uplift.
  * A top-level summary and an explicit caveat about the projection limits.

Auth
----
Requires a valid JWT (Bearer token).  Tenant context is resolved via
``get_current_membership`` — every query is explicitly scoped to
``membership.tenant_id``.

Read-only guarantee
-------------------
This endpoint NEVER executes or schedules any budget changes.  All output is
advisory.  The ``caveat`` field in every suggestion and in the top-level
response makes the heuristic limits explicit to callers.

Numbers
-------
All monetary and count fields are returned as JSON numbers (float).  Decimal
arithmetic is used inside the service layer; conversion to float happens at
this boundary.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.optimizer import current_allocation, suggest_reallocation

router = APIRouter(prefix="/optimizer", tags=["optimizer"])


# ── Response schemas ──────────────────────────────────────────────────────────


class ChannelAllocation(BaseModel):
    """Current allocation for one channel."""

    channel: str
    spend: float
    conversions: float
    conversion_value: float
    roas: float
    share_of_spend: float = Field(
        description="This channel's spend as a fraction of total spend (0.0–1.0)."
    )


class BudgetSuggestion(BaseModel):
    """One proposed budget move from a low-ROAS channel to a high-ROAS channel."""

    from_channel: str
    to_channel: str
    amount: float = Field(description="Budget to move (base currency).")
    from_roas: float
    to_roas: float
    projected_conversion_value_delta: float = Field(
        description=(
            "Estimated incremental conversion value if this amount is moved. "
            "First-order estimate only — see caveat."
        )
    )
    projected_conversion_delta: float = Field(
        description=(
            "Estimated incremental conversions. "
            "First-order estimate only — see caveat."
        )
    )
    rationale: str = Field(description="Human-readable rationale (Turkish).")
    caveat: str = Field(
        description=(
            "Explicit warning that the projection assumes constant marginal ROAS "
            "and does not account for diminishing returns. "
            "Real uplift will be lower for large shifts."
        )
    )


class OptimizerSummary(BaseModel):
    """Aggregate summary of the proposed reallocation."""

    total_shift: float = Field(
        description="Total budget proposed to move across all suggestions."
    )
    projected_total_uplift: float = Field(
        description="Sum of projected_conversion_value_delta across all suggestions."
    )
    projected_conversion_uplift: float = Field(
        description="Sum of projected_conversion_delta across all suggestions."
    )
    channels_evaluated: int
    suggestions_count: int
    caveat: str


class BudgetOptimizerResponse(BaseModel):
    """Full response for GET /optimizer/budget."""

    date_from: date
    date_to: date
    max_shift_pct: float
    current_allocation: list[ChannelAllocation]
    suggestions: list[BudgetSuggestion]
    summary: OptimizerSummary
    caveat: str = Field(
        description=(
            "Top-level caveat: projections use the current average ROAS as a "
            "linear marginal-rate estimate and do not model diminishing returns, "
            "auction dynamics, or creative fatigue."
        )
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/budget",
    response_model=BudgetOptimizerResponse,
    summary="Cross-channel budget reallocation suggestions (read-only)",
)
def budget_optimizer(
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    max_shift_pct: Annotated[
        float,
        Query(
            ge=0.0,
            le=1.0,
            description=(
                "Maximum fraction of total spend to reallocate (0.0–1.0). "
                "Default: 0.20 (20%). "
                "E.g. 0.10 = at most 10% of total spend may be moved."
            ),
        ),
    ] = 0.20,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BudgetOptimizerResponse:
    """Return current channel allocation and read-only reallocation suggestions.

    The optimizer ranks channels by ROAS and proposes moving budget from the
    lowest-efficiency channels to the highest-efficiency ones, bounded by
    ``max_shift_pct``.

    Projections use each recipient channel's current average ROAS as a
    first-order marginal rate.  The ``caveat`` fields in every suggestion and
    in the top-level response make the heuristic limits explicit: real uplift
    will be smaller than estimated for large shifts because advertising
    efficiency degrades with scale (diminishing returns, auction pressure,
    audience saturation).

    This endpoint is READ-ONLY.  No budget changes are executed or scheduled.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be <= date_to",
        )

    tenant_id = membership.tenant_id

    allocation = current_allocation(db, tenant_id, date_from, date_to)

    reallocation = suggest_reallocation(
        db,
        tenant_id,
        date_from,
        date_to,
        max_shift_pct=max_shift_pct,
    )

    return BudgetOptimizerResponse(
        date_from=date_from,
        date_to=date_to,
        max_shift_pct=max_shift_pct,
        current_allocation=[ChannelAllocation(**ch) for ch in allocation],
        suggestions=[BudgetSuggestion(**s) for s in reallocation["suggestions"]],
        summary=OptimizerSummary(**reallocation["summary"]),
        caveat=reallocation["caveat"],
    )
