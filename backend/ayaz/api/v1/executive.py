"""Executive Overview API — Yönetici (CMO) Görünümü.

Single read-only endpoint that assembles a high-level, one-screen marketing
summary for a CEO/CMO from existing warehouse data.

    GET /executive/overview?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

Defaults: date_to = today (UTC), date_from = today - 29 days (last 30 days).
Returns 422 if date_from > date_to.

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All data is filtered
to the requesting tenant — no cross-tenant leakage is possible.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.executive import build_overview

router = APIRouter(prefix="/executive", tags=["executive"])


# ── Response models ────────────────────────────────────────────────────────────


class PeriodInfo(BaseModel):
    date_from: str
    date_to: str
    prev_date_from: str
    prev_date_to: str


class KpiDeltas(BaseModel):
    spend_pct: float | None = None
    revenue_pct: float | None = None
    conversions_pct: float | None = None
    roas_pct: float | None = None


class KpiSummary(BaseModel):
    spend: float
    revenue: float
    conversions: float
    clicks: float
    roas: float
    deltas: KpiDeltas


class ChannelRow(BaseModel):
    channel: str
    label: str
    spend: float
    revenue: float
    roas: float
    share_pct: float


class GoalRow(BaseModel):
    name: str
    metric: str
    current_value: float
    target_value: float
    pct_to_target: float
    status: str


class InsightRow(BaseModel):
    severity: str
    title: str
    channel: str | None = None


class ExecutiveOverviewResponse(BaseModel):
    period: PeriodInfo
    kpis: KpiSummary
    channels: list[ChannelRow]
    goals: list[GoalRow]
    insights: list[InsightRow]
    headline: str


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=ExecutiveOverviewResponse,
    summary=(
        "Yönetici (CMO/CEO) pazarlama özeti — tek ekranlık KPI panosu. "
        "Belirtilen dönem için harcama, gelir, ROAS, kanal dağılımı, "
        "hedef ilerlemesi ve öne çıkan içgörüleri döndürür."
    ),
)
def get_executive_overview(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: date | None = Query(
        default=None,
        description="Dönem başlangıç tarihi (YYYY-MM-DD, dahil). "
                    "Belirtilmezse bugünden 29 gün öncesi (son 30 gün).",
    ),
    date_to: date | None = Query(
        default=None,
        description="Dönem bitiş tarihi (YYYY-MM-DD, dahil). "
                    "Belirtilmezse bugün (UTC).",
    ),
) -> ExecutiveOverviewResponse:
    """Return a high-level marketing executive overview for the tenant.

    Aggregates cross-channel KPIs (spend, revenue, ROAS), MoM-style deltas
    vs the immediately preceding equal-length period, per-channel breakdown,
    goal progress (top 5), and top insights (top 5 by severity) into a single
    response shaped for a CMO one-pager.

    Date range defaults
    -------------------
    * ``date_to`` defaults to today UTC if omitted.
    * ``date_from`` defaults to ``date_to - 29 days`` (last 30 days inclusive).

    Raises
    ------
    422 — if ``date_from > date_to``.
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim in the JWT does not match an active membership.
    """
    today = datetime.now(timezone.utc).date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=29)

    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from, date_to'dan sonra olamaz.",
        )

    overview = build_overview(
        db=db,
        tenant_id=membership.tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    return ExecutiveOverviewResponse(
        period=PeriodInfo(**overview["period"]),
        kpis=KpiSummary(
            spend=overview["kpis"]["spend"],
            revenue=overview["kpis"]["revenue"],
            conversions=overview["kpis"]["conversions"],
            clicks=overview["kpis"]["clicks"],
            roas=overview["kpis"]["roas"],
            deltas=KpiDeltas(**overview["kpis"]["deltas"]),
        ),
        channels=[ChannelRow(**c) for c in overview["channels"]],
        goals=[GoalRow(**g) for g in overview["goals"]],
        insights=[InsightRow(**i) for i in overview["insights"]],
        headline=overview["headline"],
    )
