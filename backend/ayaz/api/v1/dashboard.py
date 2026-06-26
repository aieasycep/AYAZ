"""Dashboard API — cross-channel marketing metrics.

Endpoints
---------
GET /api/v1/dashboard/summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    Aggregate totals + breakdown by channel for the tenant and date range.

GET /api/v1/dashboard/timeseries?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&metric=spend
    Daily time-series for one metric across all channels for the tenant.

Auth
----
Both endpoints require a valid JWT (Bearer token).  Tenant context is resolved
via ``get_current_membership`` — every query explicitly filters by
``membership.tenant_id`` to enforce isolation until Postgres RLS is active.

Numbers
-------
All monetary and count fields are returned as JSON numbers (float), not strings.
Decimal values from the DB are converted to float at the serialisation boundary
inside this module.  This keeps the Pydantic schemas clean and avoids the
client having to parse strings.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.oltp import Membership
from ayaz.services.metrics import compute_derived_metrics, effective_spend

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Supported metric names for the timeseries endpoint.
_TIMESERIES_METRICS = frozenset(
    {"spend", "impressions", "clicks", "conversions", "conversion_value", "roas"}
)


# ── Response schemas ──────────────────────────────────────────────────────────


class ChannelMetrics(BaseModel):
    channel: str
    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class SummaryTotals(BaseModel):
    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class SummaryResponse(BaseModel):
    date_from: date
    date_to: date
    totals: SummaryTotals
    by_channel: list[ChannelMetrics]


class TimeseriesPoint(BaseModel):
    date: date
    value: float


class TimeseriesResponse(BaseModel):
    metric: str
    points: list[TimeseriesPoint]


# ── Internal helpers ──────────────────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, or None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def _channel_row_to_metrics(channel_key: str, row: dict) -> ChannelMetrics:
    """Build a ChannelMetrics object from a raw SQL aggregation row dict."""
    impressions = _d(row["impressions"])
    clicks = _d(row["clicks"])
    spend = _d(row["spend"])
    conversions = _d(row["conversions"])
    conv_value = _d(row["conversion_value"])

    derived = compute_derived_metrics(
        impressions=impressions,
        clicks=clicks,
        spend=spend,
        conversions=conversions,
        conversion_value=conv_value,
    )
    return ChannelMetrics(
        channel=channel_key,
        spend=float(spend),
        impressions=float(impressions),
        clicks=float(clicks),
        conversions=float(conversions),
        conversion_value=float(conv_value),
        ctr=float(derived["ctr"]),
        cpc=float(derived["cpc"]),
        cpa=float(derived["cpa"]),
        roas=float(derived["roas"]),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="Cross-channel summary for a date range",
)
def summary(
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SummaryResponse:
    """Return aggregated totals and a per-channel breakdown.

    Both ``date_from`` and ``date_to`` are inclusive UTC calendar dates.
    All monetary values use ``cost_base_ccy`` when available; falls back to
    ``cost_raw`` (i.e. the effective_spend rule from the metric layer).

    The SQL aggregation uses a CASE expression to pick the correct spend column.
    Derived metrics (CTR / CPC / CPA / ROAS) are computed in Python from the
    aggregated sums via ``compute_derived_metrics``.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )

    tenant_id = membership.tenant_id

    # spend column: prefer cost_base_ccy when non-zero, else cost_raw
    spend_col = func.sum(
        func.coalesce(
            # Use CASE: when cost_base_ccy > 0 use it, else use cost_raw
            FactDailyMetrics.cost_base_ccy,
            FactDailyMetrics.cost_raw,
        )
    )

    # ── Per-channel aggregation ───────────────────────────────────────────

    channel_rows = db.execute(
        select(
            DimChannel.key.label("channel_key"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(DimChannel.key)
        .order_by(DimChannel.key)
    ).mappings().all()

    by_channel: list[ChannelMetrics] = []
    for row in channel_rows:
        by_channel.append(
            _channel_row_to_metrics(
                channel_key=str(row["channel_key"]),
                row={
                    "impressions": row["impressions"],
                    "clicks": row["clicks"],
                    "spend": row["spend"],
                    "conversions": row["conversions"],
                    "conversion_value": row["conversion_value"],
                },
            )
        )

    # ── Overall totals (sum of all channels) ─────────────────────────────

    total_impressions = sum(_d(c.impressions) for c in by_channel)
    total_clicks = sum(_d(c.clicks) for c in by_channel)
    total_spend = sum(_d(c.spend) for c in by_channel)
    total_conversions = sum(_d(c.conversions) for c in by_channel)
    total_conv_value = sum(_d(c.conversion_value) for c in by_channel)

    total_derived = compute_derived_metrics(
        impressions=total_impressions,
        clicks=total_clicks,
        spend=total_spend,
        conversions=total_conversions,
        conversion_value=total_conv_value,
    )

    totals = SummaryTotals(
        spend=float(total_spend),
        impressions=float(total_impressions),
        clicks=float(total_clicks),
        conversions=float(total_conversions),
        conversion_value=float(total_conv_value),
        ctr=float(total_derived["ctr"]),
        cpc=float(total_derived["cpc"]),
        cpa=float(total_derived["cpa"]),
        roas=float(total_derived["roas"]),
    )

    return SummaryResponse(
        date_from=date_from,
        date_to=date_to,
        totals=totals,
        by_channel=by_channel,
    )


@router.get(
    "/timeseries",
    response_model=TimeseriesResponse,
    summary="Daily time-series for a single metric across all channels",
)
def timeseries(
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    metric: Annotated[
        str,
        Query(
            description=(
                "Metric to plot. One of: "
                "spend | impressions | clicks | conversions | conversion_value | roas"
            )
        ),
    ],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> TimeseriesResponse:
    """Return daily totals of ``metric`` across all channels for the tenant.

    Supported metrics: ``spend``, ``impressions``, ``clicks``,
    ``conversions``, ``conversion_value``, ``roas``.

    ``roas`` is computed daily from the summed conversion_value / spend for
    that day.  All other metrics are raw sums.

    Points are ordered by date ascending.  Dates with no data are NOT included
    in the response (gaps are the caller's responsibility to fill).
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )
    if metric not in _TIMESERIES_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported metric {metric!r}. "
                f"Choose from: {sorted(_TIMESERIES_METRICS)}"
            ),
        )

    tenant_id = membership.tenant_id

    # Always aggregate both spend and conversion_value so we can compute ROAS.
    rows = db.execute(
        select(
            FactDailyMetrics.date_key.label("date_key"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(FactDailyMetrics.date_key)
        .order_by(FactDailyMetrics.date_key)
    ).mappings().all()

    points: list[TimeseriesPoint] = []
    for row in rows:
        d_key = row["date_key"]
        if metric == "roas":
            spend_val = _d(row["spend"])
            conv_val = _d(row["conversion_value"])
            from ayaz.services.metrics import roas as _roas
            value = float(_roas(conv_val, spend_val))
        elif metric == "spend":
            value = float(_d(row["spend"]))
        elif metric == "impressions":
            value = float(_d(row["impressions"]))
        elif metric == "clicks":
            value = float(_d(row["clicks"]))
        elif metric == "conversions":
            value = float(_d(row["conversions"]))
        elif metric == "conversion_value":
            value = float(_d(row["conversion_value"]))
        else:  # pragma: no cover — validated above
            value = 0.0

        points.append(TimeseriesPoint(date=d_key, value=value))

    return TimeseriesResponse(metric=metric, points=points)
