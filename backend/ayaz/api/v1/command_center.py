"""Komuta Merkezi (Command Center) API — tek ekranlık yönetim özeti.

Provides a single read-only endpoint that aggregates the most important
"what needs attention now" items across all AYAZ modules into one response.

    GET /command-center/overview

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All data is
filtered to the requesting tenant — no cross-tenant leakage is possible.

No query parameters.  The service layer picks sensible defaults (last 30
days for KPIs, current-month plan for budget pacing).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.command_center import build_command_center

router = APIRouter(prefix="/command-center", tags=["command-center"])


# ── Response models ────────────────────────────────────────────────────────────


class KpiDeltas(BaseModel):
    spend_pct: float | None = None
    revenue_pct: float | None = None
    roas_pct: float | None = None
    conversions_pct: float | None = None


class KpiBlock(BaseModel):
    spend: float
    revenue: float
    roas: float
    conversions: float
    deltas: KpiDeltas


class AttentionItem(BaseModel):
    severity: str  # "critical" | "warning" | "info"
    title: str
    detail: str
    module: str
    link: str


class BudgetModule(BaseModel):
    has_plan: bool
    period_month: str | None = None
    pace_pct: float | None = None
    pace_status: str | None = None  # "ahead" | "behind" | "on_track" | None


class InboxModule(BaseModel):
    total: int
    open: int
    pending: int
    negative: int


class ContentModule(BaseModel):
    draft: int
    pending_approval: int
    scheduled: int


class GoalsModule(BaseModel):
    total: int
    at_risk: int


class InsightsModule(BaseModel):
    critical: int
    warning: int


class RecommendationsModule(BaseModel):
    open: int
    high_impact_open: int
    total: int


class ConsentModule(BaseModel):
    score: int | None = None
    grade: str | None = None
    consent_rate_pct: float | None = None


class FunnelModule(BaseModel):
    overall_conversion_pct: float | None = None
    biggest_dropoff_label: str | None = None


class ModulesBlock(BaseModel):
    budget: BudgetModule
    inbox: InboxModule
    content: ContentModule
    goals: GoalsModule
    insights: InsightsModule
    recommendations: RecommendationsModule
    consent: ConsentModule
    funnel: FunnelModule


class CommandCenterOverviewResponse(BaseModel):
    headline: str
    kpis: KpiBlock
    attention: list[AttentionItem]
    modules: ModulesBlock


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=CommandCenterOverviewResponse,
    summary=(
        "Komuta Merkezi — 'Şu an neye dikkat etmem lazım?' özeti. "
        "KPI'lar, öncelikli dikkat gerektiren öğeler ve her modülün "
        "anlık durumunu tek bir istekte döndürür."
    ),
)
def get_command_center_overview(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> CommandCenterOverviewResponse:
    """Return the Command Center overview for the current tenant.

    Aggregates data from all AYAZ modules (budget, inbox, content, goals,
    insights, ad performance) into a single prioritised view.

    Attention items are sorted critical → warning → info and capped at 8.
    An empty attention list means all systems are healthy — the frontend
    should display an all-clear message in that case.

    Raises
    ------
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim in the JWT does not match an active membership.
    """
    data = build_command_center(db=db, tenant_id=membership.tenant_id)

    return CommandCenterOverviewResponse(
        headline=data["headline"],
        kpis=KpiBlock(
            spend=data["kpis"]["spend"],
            revenue=data["kpis"]["revenue"],
            roas=data["kpis"]["roas"],
            conversions=data["kpis"]["conversions"],
            deltas=KpiDeltas(**data["kpis"]["deltas"]),
        ),
        attention=[AttentionItem(**item) for item in data["attention"]],
        modules=ModulesBlock(
            budget=BudgetModule(**data["modules"]["budget"]),
            inbox=InboxModule(**data["modules"]["inbox"]),
            content=ContentModule(**data["modules"]["content"]),
            goals=GoalsModule(**data["modules"]["goals"]),
            insights=InsightsModule(**data["modules"]["insights"]),
            recommendations=RecommendationsModule(
                **data["modules"]["recommendations"]
            ),
            consent=ConsentModule(**data["modules"]["consent"]),
            funnel=FunnelModule(**data["modules"]["funnel"]),
        ),
    )
