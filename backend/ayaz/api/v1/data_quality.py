"""Data Quality API — DATA-TRUST layer endpoints.

Endpoints
---------
GET  /data-quality/duplicate-accounts
    List ConnectedAccount groups that share (platform, external_account_id).
    A duplicate group means the same external ad account was linked more than once,
    causing silent double-counting in every SUM/ROAS aggregation.

GET  /data-quality/drill-down
    "Bu sayı neden böyle?" — given a metric + period, return the per-account
    breakdown of which connected accounts/rows contribute to the total.
    Query params: metric (str, required), date_from (date), date_to (date).

GET  /data-quality/kpi-check
    List KPI inconsistency rows for the tenant in the last 30 days.
    Returns rows that violate: clicks>impressions, conversions>clicks, spend+zero-imp.

POST /data-quality/detect
    Run all data-quality detectors now and persist results as Insight rows
    with category="data_quality". Returns counts by severity.

Auth
----
All endpoints require a valid JWT.  Tenant context is resolved via
``get_current_membership`` — every query is explicitly scoped to tenant_id.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.analytics import FactDailyMetrics
from ayaz.models.insights import Insight
from ayaz.models.oltp import Membership
from ayaz.services.data_quality import (
    detect_duplicate_accounts,
    detect_kpi_inconsistencies,
    get_metric_breakdown,
    run_data_quality_detectors,
)

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


# ── Response schemas ──────────────────────────────────────────────────────────


class DuplicateAccountGroup(BaseModel):
    """One group of ConnectedAccounts sharing the same external identity."""

    platform: str
    external_account_id: str
    count: int
    account_ids: list[str]
    display_names: list[str]


class BreakdownEntry(BaseModel):
    """Per-account contribution to a metric total."""

    connected_account_id: str
    platform: str
    external_account_id: str
    display_name: str
    channel: str
    value: float
    pct_of_total: float
    impressions: int
    clicks: int
    spend: float
    conversions: float


class MetricBreakdownResponse(BaseModel):
    """Response for the drill-down endpoint."""

    metric: str
    date_from: str
    date_to: str
    total: float
    breakdown: list[BreakdownEntry]
    duplicate_warning: bool
    duplicate_groups: list[DuplicateAccountGroup]


class KpiInconsistencyRow(BaseModel):
    """One row that violates a KPI sanity rule."""

    rule: str
    date_key: str
    connected_account_id: str
    channel_id: str
    details: dict[str, Any]


class DetectResponse(BaseModel):
    """Response for POST /data-quality/detect."""

    as_of_date: date
    new_info: int
    new_warning: int
    new_critical: int
    skipped: int


# ── Helpers ───────────────────────────────────────────────────────────────────

_ALLOWED_METRICS = frozenset(
    {"impressions", "clicks", "spend", "conversions", "roas", "ctr", "cpc"}
)


def _latest_fact_date(db: Session, tenant_id: uuid.UUID) -> date | None:
    return db.scalar(
        select(func.max(FactDailyMetrics.date_key)).where(
            FactDailyMetrics.tenant_id == tenant_id
        )
    )


def _insight_exists_dq(
    db: Session,
    tenant_id: uuid.UUID,
    metric: str,
    entity_id: str | None,
    period_start: date,
    period_end: date,
) -> bool:
    """Deduplication check for data_quality insights."""
    stmt = select(Insight.id).where(
        Insight.tenant_id == tenant_id,
        Insight.category == "data_quality",
        Insight.metric == metric,
        Insight.period_start == period_start,
        Insight.period_end == period_end,
        Insight.status.in_(["new", "seen"]),
    )
    if entity_id is not None:
        stmt = stmt.where(Insight.entity_id == entity_id)
    else:
        stmt = stmt.where(Insight.entity_id.is_(None))
    return db.scalar(stmt) is not None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/duplicate-accounts",
    response_model=list[DuplicateAccountGroup],
    summary="List duplicate ConnectedAccount groups for the current tenant",
)
def list_duplicate_accounts(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[DuplicateAccountGroup]:
    """Return all ConnectedAccount groups that share (platform, external_account_id).

    Any group with count >= 2 means the same external ad/analytics account was
    linked more than once, creating a silent double-count in every SUM.
    Use the ``DELETE /connectors/accounts/{id}`` endpoint to remove extras.

    Tenant isolation: results are scoped to the caller's tenant.
    """
    dupes = detect_duplicate_accounts(db, membership.tenant_id)
    return [DuplicateAccountGroup(**d) for d in dupes]


@router.get(
    "/drill-down",
    response_model=MetricBreakdownResponse,
    summary="Break down a metric total by connected account ('Bu sayı neden böyle?')",
)
def metric_drill_down(
    metric: Annotated[
        str,
        Query(
            description=(
                "Metric to break down. One of: "
                "impressions, clicks, spend, conversions, roas, ctr, cpc"
            )
        ),
    ],
    date_from: Annotated[
        date,
        Query(description="Start date (inclusive), ISO 8601 e.g. 2026-06-01"),
    ],
    date_to: Annotated[
        date,
        Query(description="End date (inclusive), ISO 8601 e.g. 2026-06-30"),
    ],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> MetricBreakdownResponse:
    """Return the per-account breakdown that adds up to the given metric total.

    Each entry in ``breakdown`` shows one (connected account × channel) pair with
    its raw metric values and its percentage contribution to the total.

    When ``duplicate_warning`` is True, some contributing accounts share the same
    external identity, meaning the total is being double-counted.

    Tenant isolation: all queries are scoped to the caller's tenant_id.
    """
    if metric not in _ALLOWED_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Geçersiz metrik: {metric!r}. "
                f"İzin verilenler: {sorted(_ALLOWED_METRICS)}"
            ),
        )
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from, date_to'dan önce olmalı.",
        )

    result = get_metric_breakdown(
        db, membership.tenant_id, metric, date_from, date_to
    )

    return MetricBreakdownResponse(
        metric=result["metric"],
        date_from=result["date_from"],
        date_to=result["date_to"],
        total=result["total"],
        breakdown=[BreakdownEntry(**e) for e in result["breakdown"]],
        duplicate_warning=result["duplicate_warning"],
        duplicate_groups=[DuplicateAccountGroup(**d) for d in result["duplicate_groups"]],
    )


@router.get(
    "/kpi-check",
    response_model=list[KpiInconsistencyRow],
    summary="List KPI inconsistency rows for the last 30 days",
)
def list_kpi_inconsistencies(
    lookback_days: Annotated[
        int,
        Query(description="Number of days to look back (1–90)", ge=1, le=90),
    ] = 30,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[KpiInconsistencyRow]:
    """Return rows in fact_daily_metrics that violate KPI sanity rules.

    Rules checked:
    - clicks_exceed_impressions  — clicks > impressions (physically impossible)
    - conversions_exceed_clicks  — conversions > clicks (both > 0)
    - spend_without_impressions  — cost_base_ccy > 0 AND impressions == 0

    Each row includes the rule name, date, account, channel, and the offending values.

    Tenant isolation: all queries are scoped to the caller's tenant_id.
    """
    today = date.today()
    period_start = today - timedelta(days=lookback_days - 1)
    inconsistencies = detect_kpi_inconsistencies(
        db, membership.tenant_id, period_start, today
    )
    return [KpiInconsistencyRow(**i) for i in inconsistencies]


@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Run data-quality detectors and persist results as insights",
)
def run_detect(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> DetectResponse:
    """Run all data-quality detectors for the current tenant and persist new Insight rows.

    Uses the latest date in fact_daily_metrics as ``as_of_date``.
    Deduplicates against existing open (new/seen) insights with the same
    (category, metric, entity_id, period_start, period_end).

    Returns counts by severity (same shape as POST /insights/generate).

    Tenant isolation: every query and every inserted row is scoped to tenant_id.
    """
    from ayaz.services.narrator import TemplateNarrator

    tenant_id = membership.tenant_id
    as_of = _latest_fact_date(db, tenant_id)

    if as_of is None:
        return DetectResponse(
            as_of_date=date.today(),
            new_info=0,
            new_warning=0,
            new_critical=0,
            skipped=0,
        )

    results = run_data_quality_detectors(db, tenant_id, as_of)
    narrator = TemplateNarrator()

    counts = {"new_info": 0, "new_warning": 0, "new_critical": 0, "skipped": 0}

    for result in results:
        if _insight_exists_dq(
            db,
            tenant_id,
            metric=result.metric,
            entity_id=result.entity_id,
            period_start=result.period_start,
            period_end=result.period_end,
        ):
            counts["skipped"] += 1
            continue

        try:
            title, body = narrator.narrate(result)
        except Exception:
            title = result.category
            body = str(result.data)

        insight = Insight(
            tenant_id=tenant_id,
            category=result.category,
            severity=result.severity,
            title=title,
            body=body,
            metric=result.metric,
            channel=result.channel,
            entity_type=result.entity_type,
            entity_id=result.entity_id,
            entity_name=result.entity_name,
            period_start=result.period_start,
            period_end=result.period_end,
            status="new",
            score=result.score,
            data=result.data,
        )
        db.add(insight)

        severity_key = f"new_{result.severity}"
        if severity_key in counts:
            counts[severity_key] += 1
        else:
            counts["new_info"] += 1

    db.flush()
    db.commit()

    return DetectResponse(
        as_of_date=as_of,
        new_info=counts["new_info"],
        new_warning=counts["new_warning"],
        new_critical=counts["new_critical"],
        skipped=counts["skipped"],
    )
