"""Dashboard API — cross-channel marketing metrics.

Endpoints
---------
GET /api/v1/dashboard/summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD[&compare=true]
    Aggregate totals + breakdown by channel for the tenant and date range.
    With compare=true adds ``previous`` (prior-period totals) and ``deltas``
    (fractional change for each metric).

GET /api/v1/dashboard/timeseries?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&metric=spend
    Daily time-series for one metric across all channels for the tenant.

GET /api/v1/dashboard/top-movers
    En çok değişen kanalları/kampanyaları döndürür (mutlak delta büyüklüğüne göre sıralı).

GET /api/v1/dashboard/export?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    CSV export: one totals row + one row per channel.  Turkish headers.
    Content-Type: text/csv; charset=utf-8-sig (BOM for Excel).

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant context is resolved
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

import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics
from ayaz.models.oltp import Membership
from ayaz.services.metrics import compute_derived_metrics, effective_spend, roas as _roas_metric

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


class PeriodDeltas(BaseModel):
    """Fractional change for each metric between current and previous period.

    Values represent (current - previous) / previous.  For example, 0.12 means
    +12%.  None is returned when the previous-period denominator is zero.
    """

    spend: float | None
    impressions: float | None
    clicks: float | None
    conversions: float | None
    conversion_value: float | None
    ctr: float | None
    cpc: float | None
    cpa: float | None
    roas: float | None


class SummaryResponse(BaseModel):
    date_from: date
    date_to: date
    totals: SummaryTotals
    by_channel: list[ChannelMetrics]
    # Optional comparison fields — present only when compare=true was requested.
    previous: SummaryTotals | None = None
    deltas: PeriodDeltas | None = None


class TimeseriesPoint(BaseModel):
    date: date
    value: float


class TimeseriesResponse(BaseModel):
    metric: str
    points: list[TimeseriesPoint]


class TopMoverItem(BaseModel):
    """Tek bir kanal veya kampanya için dönem karşılaştırması.

    ``delta_pct`` bir önceki dönem değeri sıfır olduğunda ``None`` döner
    (sıfıra bölme koruması).
    """

    key: str
    label: str
    current: float
    previous: float
    delta: float
    delta_pct: float | None
    direction: str  # "up" | "down"


class TopMoversResponse(BaseModel):
    """En çok değişen kanal/kampanya listesi — mutlak delta büyüklüğüne göre sıralı.

    ``previous_from`` / ``previous_to`` seçilen döneme hemen önceki eşit uzunluktaki
    karşılaştırma döneminin tarih aralığıdır.
    """

    dimension: str
    metric: str
    date_from: date
    date_to: date
    previous_from: date
    previous_to: date
    movers: list[TopMoverItem]


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


def _aggregate_period(
    db: Session,
    tenant_id: object,
    date_from: date,
    date_to: date,
) -> tuple[SummaryTotals, list[ChannelMetrics]]:
    """Run the per-channel aggregation for [date_from, date_to] and return
    (totals, by_channel).  Shared by summary and CSV export.
    """
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

    return totals, by_channel


def _fractional_delta(current: float, previous: float) -> float | None:
    """Return (current - previous) / previous, or None when previous == 0."""
    if previous == 0.0:
        return None
    return (current - previous) / previous


def _compute_deltas(current: SummaryTotals, prev: SummaryTotals) -> PeriodDeltas:
    """Build PeriodDeltas by comparing each field of current vs previous totals."""
    return PeriodDeltas(
        spend=_fractional_delta(current.spend, prev.spend),
        impressions=_fractional_delta(current.impressions, prev.impressions),
        clicks=_fractional_delta(current.clicks, prev.clicks),
        conversions=_fractional_delta(current.conversions, prev.conversions),
        conversion_value=_fractional_delta(current.conversion_value, prev.conversion_value),
        ctr=_fractional_delta(current.ctr, prev.ctr),
        cpc=_fractional_delta(current.cpc, prev.cpc),
        cpa=_fractional_delta(current.cpa, prev.cpa),
        roas=_fractional_delta(current.roas, prev.roas),
    )


# Desteklenen metrik isimleri — top-movers ve timeseries için.
_TOP_MOVERS_METRICS = frozenset(
    {"spend", "impressions", "clicks", "conversions", "conversion_value", "roas"}
)


def _aggregate_by_channel(
    db: Session,
    tenant_id: object,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Kanal bazlı ham metrik toplamlarını döndürür.

    Dönen sözlük: ``{channel_key: {"label": ..., "impressions": Decimal, ...}}``.
    """
    rows = db.execute(
        select(
            DimChannel.key.label("channel_key"),
            DimChannel.label.label("channel_label"),
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
        .group_by(DimChannel.key, DimChannel.label)
    ).mappings().all()

    return {
        str(row["channel_key"]): {
            "label": str(row["channel_label"]),
            "impressions": _d(row["impressions"]),
            "clicks": _d(row["clicks"]),
            "spend": _d(row["spend"]),
            "conversions": _d(row["conversions"]),
            "conversion_value": _d(row["conversion_value"]),
        }
        for row in rows
    }


def _aggregate_by_campaign(
    db: Session,
    tenant_id: object,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Kampanya bazlı ham metrik toplamlarını döndürür.

    Dönen sözlük: ``{str(campaign_id): {"label": campaign_name, ...}}``.
    """
    rows = db.execute(
        select(
            DimCampaign.id.label("campaign_id"),
            DimCampaign.name.label("campaign_name"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(DimCampaign.id, DimCampaign.name)
    ).mappings().all()

    return {
        str(row["campaign_id"]): {
            "label": str(row["campaign_name"]),
            "impressions": _d(row["impressions"]),
            "clicks": _d(row["clicks"]),
            "spend": _d(row["spend"]),
            "conversions": _d(row["conversions"]),
            "conversion_value": _d(row["conversion_value"]),
        }
        for row in rows
    }


def _extract_metric_value(row: dict, metric: str) -> Decimal:
    """Bir metrik toplamı sözlüğünden istenen metriğin değerini döndürür.

    ``roas`` için ROAS = conversion_value / spend formülü uygulanır.
    Diğer metrikler doğrudan toplanmış değer olarak döner.
    """
    if metric == "roas":
        return _roas_metric(row["conversion_value"], row["spend"])
    return row[metric]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="Cross-channel summary for a date range",
)
def summary(
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    compare: Annotated[
        bool,
        Query(
            description=(
                "When true, also compute the immediately-preceding period of equal "
                "length and add ``previous`` (totals) and ``deltas`` (fractional "
                "change per metric) to the response.  Default false — response is "
                "byte-identical to the no-compare case."
            )
        ),
    ] = False,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SummaryResponse:
    """Return aggregated totals and a per-channel breakdown.

    Both ``date_from`` and ``date_to`` are inclusive UTC calendar dates.
    All monetary values use ``cost_base_ccy`` when available; falls back to
    ``cost_raw`` (i.e. the effective_spend rule from the metric layer).

    Derived metrics (CTR / CPC / CPA / ROAS) are computed in Python from the
    aggregated sums via ``compute_derived_metrics``.

    When ``compare=true``, the response additionally includes:

    - ``previous``: same ``SummaryTotals`` shape for the preceding period
      [date_from - N, date_from - 1] where N = date_to - date_from + 1.
    - ``deltas``: fractional change per metric vs the previous period
      (0.12 = +12%).  None when the previous-period denominator is zero.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )

    tenant_id = membership.tenant_id

    # ── Current period ────────────────────────────────────────────────────
    totals, by_channel = _aggregate_period(db, tenant_id, date_from, date_to)

    # ── Optional prior period ─────────────────────────────────────────────
    previous: SummaryTotals | None = None
    deltas: PeriodDeltas | None = None

    if compare:
        period_len = (date_to - date_from).days + 1  # inclusive day count
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_len - 1)
        previous, _ = _aggregate_period(db, tenant_id, prev_from, prev_to)
        deltas = _compute_deltas(totals, previous)

    return SummaryResponse(
        date_from=date_from,
        date_to=date_to,
        totals=totals,
        by_channel=by_channel,
        previous=previous,
        deltas=deltas,
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


# ── Top movers endpoint ───────────────────────────────────────────────────────


@router.get(
    "/top-movers",
    response_model=TopMoversResponse,
    summary="En çok değişen kanallar/kampanyalar",
)
def top_movers(
    date_from: Annotated[date, Query(description="Mevcut dönem başlangıç tarihi (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Mevcut dönem bitiş tarihi (YYYY-MM-DD)")],
    dimension: Annotated[
        str,
        Query(description="Gruplama boyutu: 'channel' (varsayılan) veya 'campaign'"),
    ] = "channel",
    metric: Annotated[
        str,
        Query(
            description=(
                "Karşılaştırılacak metrik. "
                "spend | impressions | clicks | conversions | conversion_value | roas"
            )
        ),
    ] = "spend",
    limit: Annotated[
        int,
        Query(description="Döndürülecek maksimum kayıt sayısı (varsayılan 5, maksimum 20)", ge=1, le=20),
    ] = 5,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> TopMoversResponse:
    """Seçilen dönemde en çok değişen kanalları/kampanyaları döndürür.

    Karşılaştırma dönemi, seçilen dönemle aynı uzunlukta olup ``date_from``'dan
    hemen önceki güne kadar olan eşit uzunlukta dönemdir.  Bu, ``summary``
    endpoint'indeki ``compare=true`` mantığıyla örtüşür.

    Sıralama mutlak delta büyüklüğüne göre yapılır (hem kazananlar hem kaybedenler
    dahil edilir).

    ``roas`` için oran ortalaması alınmaz; dönem bazında toplam
    ``conversion_value / spend`` hesaplanır.

    ``delta_pct`` bir önceki dönem değeri sıfır olduğunda ``None`` döner.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )
    if dimension not in ("channel", "campaign"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="dimension must be 'channel' or 'campaign'",
        )
    if metric not in _TOP_MOVERS_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported metric {metric!r}. "
                f"Choose from: {sorted(_TOP_MOVERS_METRICS)}"
            ),
        )

    tenant_id = membership.tenant_id

    # Önceki dönem: seçilen dönemle aynı uzunluk, hemen öncesinde.
    period_len = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_len - 1)

    # Boyuta göre toplayıcı seç.
    if dimension == "channel":
        curr_data = _aggregate_by_channel(db, tenant_id, date_from, date_to)
        prev_data = _aggregate_by_channel(db, tenant_id, prev_from, prev_to)
    else:
        curr_data = _aggregate_by_campaign(db, tenant_id, date_from, date_to)
        prev_data = _aggregate_by_campaign(db, tenant_id, prev_from, prev_to)

    # Her iki dönemde görünen tüm varlıkların birleşimini oluştur.
    all_keys = set(curr_data) | set(prev_data)

    _zero_row: dict = {
        "label": "",
        "impressions": Decimal(0),
        "clicks": Decimal(0),
        "spend": Decimal(0),
        "conversions": Decimal(0),
        "conversion_value": Decimal(0),
    }

    items: list[TopMoverItem] = []
    for key in all_keys:
        curr_row = curr_data.get(key, _zero_row)
        prev_row = prev_data.get(key, _zero_row)

        label = curr_row["label"] or prev_row["label"]

        curr_val: Decimal = _extract_metric_value(curr_row, metric)
        prev_val: Decimal = _extract_metric_value(prev_row, metric)

        delta: Decimal = curr_val - prev_val

        if prev_val == Decimal(0):
            delta_pct: float | None = None
        else:
            delta_pct = float(delta / prev_val)

        items.append(
            TopMoverItem(
                key=key,
                label=label,
                current=float(curr_val),
                previous=float(prev_val),
                delta=float(delta),
                delta_pct=delta_pct,
                direction="up" if delta >= Decimal(0) else "down",
            )
        )

    # Mutlak delta büyüklüğüne göre azalan sırala; limit uygula.
    items.sort(key=lambda x: abs(x.delta), reverse=True)
    items = items[:limit]

    return TopMoversResponse(
        dimension=dimension,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
        previous_from=prev_from,
        previous_to=prev_to,
        movers=items,
    )


# ── CSV export ────────────────────────────────────────────────────────────────

# Turkish column headers for the dashboard CSV.
_CSV_HEADERS = [
    "Kanal",
    "Harcama",
    "Gösterim",
    "Tıklama",
    "Dönüşüm",
    "Dönüşüm Değeri",
    "ROAS",
    "CPC",
    "CTR",
]


def _totals_to_csv_row(label: str, t: SummaryTotals) -> list:
    return [
        label,
        round(t.spend, 4),
        round(t.impressions, 4),
        round(t.clicks, 4),
        round(t.conversions, 4),
        round(t.conversion_value, 4),
        round(t.roas, 4),
        round(t.cpc, 4),
        round(t.ctr, 4),
    ]


def _channel_to_csv_row(ch: ChannelMetrics) -> list:
    return [
        ch.channel,
        round(ch.spend, 4),
        round(ch.impressions, 4),
        round(ch.clicks, 4),
        round(ch.conversions, 4),
        round(ch.conversion_value, 4),
        round(ch.roas, 4),
        round(ch.cpc, 4),
        round(ch.ctr, 4),
    ]


@router.get(
    "/export",
    summary="Export dashboard summary as CSV (Turkish headers, UTF-8 BOM)",
    response_class=StreamingResponse,
)
def export_dashboard(
    date_from: Annotated[date, Query(description="Inclusive start date (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Inclusive end date (YYYY-MM-DD)")],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> StreamingResponse:
    """Return a UTF-8 BOM CSV with one totals row and one row per channel.

    Headers (Turkish): Kanal, Harcama, Gösterim, Tıklama, Dönüşüm,
    Dönüşüm Değeri, ROAS, CPC, CTR.

    Content-Disposition filename: ``ayaz-dashboard-<from>_<to>.csv``.
    The BOM (\\ufeff) ensures Excel correctly decodes Turkish characters.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )

    tenant_id = membership.tenant_id
    totals, by_channel = _aggregate_period(db, tenant_id, date_from, date_to)

    buf = io.StringIO()
    # Write UTF-8 BOM so Excel auto-detects the encoding.
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADERS)
    writer.writerow(_totals_to_csv_row("Toplam", totals))
    for ch in by_channel:
        writer.writerow(_channel_to_csv_row(ch))

    filename = f"ayaz-dashboard-{date_from}_{date_to}.csv"
    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
