"""Ad Management service — M6, phase 1 (READ-ONLY).

Public API
----------
    list_campaigns(db, tenant_id, date_from, date_to, *, channel, status, sort)
    campaign_detail(db, tenant_id, campaign_id, date_from, date_to)
    campaign_recommendations(db, tenant_id, date_from, date_to)

Design notes
------------
* All three functions are read-only; they aggregate FactDailyMetrics grouped by
  campaign and join DimCampaign / DimChannel for dimension attributes.
* Derived metrics (CTR, CPC, CPA, ROAS) are computed via the shared metric layer
  (ayaz.services.metrics) — no formula duplication here.
* Recommendations reuse the existing insights detectors from ayaz.services.insights,
  applied at campaign granularity rather than the channel granularity used by the
  scheduler.  The detectors accept plain ``DailyPoint`` lists, so we feed them
  per-campaign slices of fact data and collect DetectorResult objects without writing
  anything to the DB.
* Tenant isolation: every query carries an explicit ``tenant_id`` filter.
  Postgres RLS is a planned future safeguard (see models/analytics.py TODO).

Phase 2 note (M6 phase 2 — NOT implemented here)
-------------------------------------------------
Write/execution paths such as pausing, budget changes, and creative refresh will
be added in M6 phase 2.  The recommendation objects returned here include a
``suggested_action`` label so the frontend can show the affordance, but no
write API exists yet.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics
from ayaz.services.metrics import compute_derived_metrics, effective_spend
from ayaz.services.insights import (
    DailyPoint,
    DetectorResult,
    detect_anomaly,
    detect_cpc_rise,
    detect_ctr_drop,
    detect_roas_drop,
    detect_spend_spike,
    detect_zero_conversions,
    RECENT_DAYS,
)
from ayaz.services.metrics import (
    ctr as _ctr,
    cpc as _cpc,
    roas as _roas,
)


# ── Internal helpers ───────────────────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, or None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


# Valid sort columns for list_campaigns.
_SORT_COLUMNS: frozenset[str] = frozenset(
    {"spend", "impressions", "clicks", "conversions", "conversion_value",
     "ctr", "cpc", "cpa", "roas", "campaign_name", "channel"}
)

# Derived-status logic: a campaign is considered "active" when it had any spend
# in the requested date range; otherwise "paused" (best approximation without a
# status column on DimCampaign — the model has no status field as of M6 phase 1).
_ACTIVE_STATUS = "active"
_PAUSED_STATUS = "paused"


def _derive_status(spend: Decimal) -> str:
    """Return 'active' if spend > 0 else 'paused'.

    DimCampaign has no status column; campaign activity is inferred from spend
    in the requested period.  A more accurate status would require syncing the
    platform's campaign state into a DimCampaign.status column, which is planned
    for M6 phase 2.
    """
    return _ACTIVE_STATUS if spend > Decimal(0) else _PAUSED_STATUS


# ── Campaign aggregation helpers ───────────────────────────────────────────────


def _base_campaign_query(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
):
    """Build and return the base aggregation select for campaign-level metrics.

    Returns SQLAlchemy rows with columns:
        campaign_id, campaign_name, channel_key,
        impressions, clicks, spend, conversions, conversion_value
    """
    return db.execute(
        select(
            DimCampaign.id.label("campaign_id"),
            DimCampaign.name.label("campaign_name"),
            DimChannel.key.label("channel_key"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            DimCampaign.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(DimCampaign.id, DimCampaign.name, DimChannel.key)
        .order_by(DimCampaign.name)
    ).mappings().all()


def _row_to_campaign_dict(row: Any) -> dict:
    """Convert an aggregation row into the standard campaign dict shape."""
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

    return {
        "campaign_id": str(row["campaign_id"]),
        "campaign_name": row["campaign_name"],
        "channel": row["channel_key"],
        "status": _derive_status(spend),
        "spend": float(spend),
        "impressions": float(impressions),
        "clicks": float(clicks),
        "conversions": float(conversions),
        "conversion_value": float(conv_value),
        "ctr": float(derived["ctr"]),
        "cpc": float(derived["cpc"]),
        "cpa": float(derived["cpa"]),
        "roas": float(derived["roas"]),
    }


# ── Public service functions ───────────────────────────────────────────────────


def list_campaigns(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    channel: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    sort_desc: bool = True,
) -> list[dict]:
    """Return aggregated per-campaign metrics for the tenant and date range.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries issued).
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    date_from:
        Inclusive start of the date range.
    date_to:
        Inclusive end of the date range.
    channel:
        Optional DimChannel.key to restrict results (e.g. "google_ads").
    status:
        Optional derived status filter: "active" | "paused".
        Applied in Python after aggregation because status is inferred from spend.
    sort:
        Column name to sort by.  Must be one of the keys in _SORT_COLUMNS.
        Defaults to "spend" (descending).
    sort_desc:
        When True (default), sort descending.  Pass False for ascending.

    Returns
    -------
    list of dicts, each with keys:
        campaign_id, campaign_name, channel, status,
        spend, impressions, clicks, conversions, conversion_value,
        ctr, cpc, cpa, roas
    """
    rows = _base_campaign_query(db, tenant_id, date_from, date_to)
    campaigns = [_row_to_campaign_dict(r) for r in rows]

    # ── Apply filters ─────────────────────────────────────────────────────
    if channel is not None:
        campaigns = [c for c in campaigns if c["channel"] == channel]

    if status is not None:
        campaigns = [c for c in campaigns if c["status"] == status]

    # ── Apply sort ────────────────────────────────────────────────────────
    effective_sort = sort if (sort and sort in _SORT_COLUMNS) else "spend"
    campaigns.sort(
        key=lambda c: c.get(effective_sort, 0) or 0,
        reverse=sort_desc,
    )

    return campaigns


def campaign_detail(
    db: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict | None:
    """Return campaign totals and a daily timeseries for a single campaign.

    Parameters
    ----------
    db:
        SQLAlchemy Session.
    tenant_id:
        Tenant UUID — guards against cross-tenant access.
    campaign_id:
        UUID of the DimCampaign row.
    date_from:
        Inclusive start date.
    date_to:
        Inclusive end date.

    Returns
    -------
    dict with keys:
        campaign_id, campaign_name, channel, status,
        totals: {spend, impressions, clicks, conversions, conversion_value,
                 ctr, cpc, cpa, roas},
        timeseries: list of {date, spend, impressions, clicks, conversions,
                              conversion_value, ctr, cpc, cpa, roas}

    Returns None when the campaign does not exist or belongs to a different tenant.
    """
    # Verify the campaign belongs to this tenant
    campaign = db.scalar(
        select(DimCampaign).where(
            DimCampaign.id == campaign_id,
            DimCampaign.tenant_id == tenant_id,
        )
    )
    if campaign is None:
        return None

    # Get the channel key
    channel_row = db.scalar(
        select(DimChannel).where(DimChannel.id == campaign.channel_id)
    )
    channel_key = channel_row.key if channel_row else "unknown"

    # ── Daily timeseries ──────────────────────────────────────────────────
    daily_rows = db.execute(
        select(
            FactDailyMetrics.date_key,
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.campaign_id == campaign_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(FactDailyMetrics.date_key)
        .order_by(FactDailyMetrics.date_key)
    ).mappings().all()

    timeseries: list[dict] = []
    total_impressions = Decimal(0)
    total_clicks = Decimal(0)
    total_spend = Decimal(0)
    total_conversions = Decimal(0)
    total_conv_value = Decimal(0)

    for row in daily_rows:
        imp = _d(row["impressions"])
        clk = _d(row["clicks"])
        spd = _d(row["spend"])
        cvr = _d(row["conversions"])
        cvv = _d(row["conversion_value"])

        total_impressions += imp
        total_clicks += clk
        total_spend += spd
        total_conversions += cvr
        total_conv_value += cvv

        derived = compute_derived_metrics(
            impressions=imp,
            clicks=clk,
            spend=spd,
            conversions=cvr,
            conversion_value=cvv,
        )
        timeseries.append({
            "date": str(row["date_key"]),
            "spend": float(spd),
            "impressions": float(imp),
            "clicks": float(clk),
            "conversions": float(cvr),
            "conversion_value": float(cvv),
            "ctr": float(derived["ctr"]),
            "cpc": float(derived["cpc"]),
            "cpa": float(derived["cpa"]),
            "roas": float(derived["roas"]),
        })

    # ── Period totals ─────────────────────────────────────────────────────
    total_derived = compute_derived_metrics(
        impressions=total_impressions,
        clicks=total_clicks,
        spend=total_spend,
        conversions=total_conversions,
        conversion_value=total_conv_value,
    )

    return {
        "campaign_id": str(campaign_id),
        "campaign_name": campaign.name,
        "channel": channel_key,
        "status": _derive_status(total_spend),
        "totals": {
            "spend": float(total_spend),
            "impressions": float(total_impressions),
            "clicks": float(total_clicks),
            "conversions": float(total_conversions),
            "conversion_value": float(total_conv_value),
            "ctr": float(total_derived["ctr"]),
            "cpc": float(total_derived["cpc"]),
            "cpa": float(total_derived["cpa"]),
            "roas": float(total_derived["roas"]),
        },
        "timeseries": timeseries,
    }


# ── Campaign-grain data loading for recommendations ────────────────────────────


def _load_campaign_daily_points(
    db: Session,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> list[DailyPoint]:
    """Load per-day DailyPoint objects for a single campaign.

    Mirrors _load_daily_points from insights.py but groups by (date_key) for a
    single campaign instead of (date_key, channel_key) across all channels.
    The channel_key on each DailyPoint is set to the campaign's channel so the
    existing detector functions (which key by channel_key) work without changes.
    """
    rows = db.execute(
        select(
            FactDailyMetrics.date_key,
            DimChannel.key.label("channel_key"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.campaign_id == campaign_id,
            FactDailyMetrics.date_key >= period_start,
            FactDailyMetrics.date_key <= period_end,
        )
        .group_by(FactDailyMetrics.date_key, DimChannel.key)
        .order_by(FactDailyMetrics.date_key)
    ).mappings().all()

    points: list[DailyPoint] = []
    for row in rows:
        imp = _d(row["impressions"])
        clk = _d(row["clicks"])
        spd = _d(row["spend"])
        cvr = _d(row["conversions"])
        cvv = _d(row["conversion_value"])
        p = DailyPoint(
            date_key=row["date_key"],
            channel_key=str(row["channel_key"]),
            impressions=imp,
            clicks=clk,
            spend=spd,
            conversions=cvr,
            conversion_value=cvv,
        )
        p.ctr_val = float(_ctr(imp, clk))
        p.cpc_val = float(_cpc(spd, clk))
        p.roas_val = float(_roas(cvv, spd))
        points.append(p)

    return points


# ── Turkish recommendation narratives ─────────────────────────────────────────


_CATEGORY_ACTIONS: dict[str, str] = {
    "roas_drop": "Bütçeyi gözden geçir",
    "spend_spike": "Bütçeyi gözden geçir",
    "zero_conversions": "Dönüşüm izlemeyi kontrol et",
    "ctr_drop": "Kreatifi yenile",
    "cpc_rise": "Teklif stratejisini güncelle",
    "anomaly": "Detaylı incele",
}

_SEVERITY_ACTION_SUFFIX: dict[str, str] = {
    "critical": "Duraklatmayı değerlendir",
    "warning": "Bütçe artır",
    "info": "Detaylı incele",
}


def _build_turkish_message(result: DetectorResult, campaign_name: str) -> str:
    """Produce a Turkish recommendation body from a DetectorResult.

    M6 phase 2 note: this is READ-ONLY guidance.  No write/execution API exists.
    The suggested_action label is provided so the frontend can show affordances;
    actual budget changes or pausing will be wired in M6 phase 2.
    """
    category = result.category
    data = result.data

    if category == "roas_drop":
        pct = round(data.get("pct_drop", 0) * 100, 1)
        current = round(data.get("current_roas", 0), 2)
        return (
            f"'{campaign_name}' kampanyasında ROAS %{pct} düştü "
            f"(şu an {current}x). Bütçeyi gözden geçirin veya kampanyayı duraklatın."
        )
    if category == "spend_spike":
        pct = round(data.get("pct_rise", 0) * 100, 1)
        return (
            f"'{campaign_name}' kampanyasında harcama %{pct} arttı. "
            "Bütçe limitinizi ve teklif stratejinizi kontrol edin."
        )
    if category == "zero_conversions":
        spend = round(data.get("spend", 0), 2)
        return (
            f"'{campaign_name}' kampanyası {spend} harcama yaptı "
            "fakat hiç dönüşüm gerçekleşmedi. "
            "Piksel/dönüşüm izlemeyi ve açılış sayfasını kontrol edin."
        )
    if category == "ctr_drop":
        pct = round(data.get("pct_drop", 0) * 100, 1)
        return (
            f"'{campaign_name}' kampanyasında tıklama oranı (CTR) %{pct} düştü. "
            "Kreatifi ve hedeflemeyi yenileyin."
        )
    if category == "cpc_rise":
        pct = round(data.get("pct_rise", 0) * 100, 1)
        return (
            f"'{campaign_name}' kampanyasında tıklama başına maliyet (CPC) %{pct} yükseldi. "
            "Teklif stratejinizi ve rekabeti gözden geçirin."
        )
    if category == "anomaly":
        metric = result.metric
        direction = data.get("direction", "")
        direction_tr = "yüksek" if direction == "yuksek" else "düşük"
        return (
            f"'{campaign_name}' kampanyasında {metric} metriğinde "
            f"istatistiksel anomali tespit edildi ({direction_tr}). "
            "Kampanya performansını detaylı inceleyin."
        )
    # Fallback
    return (
        f"'{campaign_name}' kampanyasında {category} sinyali tespit edildi. "
        "Kampanyayı gözden geçirin."
    )


def _pick_suggested_action(result: DetectorResult) -> str:
    """Choose the best suggested action label (Turkish) for a DetectorResult.

    M6 phase 2 note: write/execute is NOT implemented.  This label is the
    affordance hint for the frontend UI.
    """
    category = result.category
    severity = result.severity

    if category == "roas_drop" and severity == "critical":
        return "Duraklatmayı değerlendir"
    if category == "roas_drop":
        return "Bütçeyi gözden geçir"
    if category == "zero_conversions":
        return "Dönüşüm izlemeyi kontrol et"
    if category == "ctr_drop":
        return "Kreatifi yenile"
    if category == "cpc_rise":
        return "Teklif stratejisini güncelle"
    if category == "spend_spike" and severity == "critical":
        return "Duraklatmayı değerlendir"
    if category == "spend_spike":
        return "Bütçe artır"
    return _SEVERITY_ACTION_SUFFIX.get(severity, "Detaylı incele")


# ── Public recommendations function ───────────────────────────────────────────


def campaign_recommendations(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    lookback_days: int = 30,
) -> list[dict]:
    """Run insights detectors at campaign granularity and return recommendations.

    This function is READ-ONLY.  It reuses the pure detector functions from
    ayaz.services.insights without writing anything to the insights table.
    Each detector receives a per-campaign slice of DailyPoint objects.

    IMPORTANT — M6 phase 2: write/execute paths (pause, budget change, creative
    refresh) are NOT implemented here.  The ``suggested_action`` field is a UI
    affordance label only.

    Parameters
    ----------
    db:
        SQLAlchemy Session.
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    date_from:
        Display date range start (used for filtering; lookback extends further).
    date_to:
        Display date range end / as_of_date for detectors.
    lookback_days:
        How many calendar days of history to load for the detectors (default 30).
        A longer window makes the anomaly detector more reliable.

    Returns
    -------
    list of dicts, sorted by score descending, each with keys:
        campaign_id, campaign_name, channel, category, severity, score,
        metric, message (Turkish), suggested_action (Turkish),
        period_start, period_end, data
    """
    from datetime import timedelta as _timedelta

    as_of_date = date_to
    lookback_start = as_of_date - _timedelta(days=lookback_days - 1)

    # Fetch all campaigns that have data in the requested range
    campaign_rows = db.execute(
        select(
            DimCampaign.id.label("campaign_id"),
            DimCampaign.name.label("campaign_name"),
            DimChannel.key.label("channel_key"),
        )
        .join(FactDailyMetrics, FactDailyMetrics.campaign_id == DimCampaign.id)
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            DimCampaign.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= lookback_start,
            FactDailyMetrics.date_key <= as_of_date,
        )
        .group_by(DimCampaign.id, DimCampaign.name, DimChannel.key)
    ).mappings().all()

    all_recommendations: list[dict] = []

    for camp_row in campaign_rows:
        campaign_id = camp_row["campaign_id"]
        campaign_name = camp_row["campaign_name"]
        channel_key = camp_row["channel_key"]

        # Load daily points for this campaign over the lookback window
        points = _load_campaign_daily_points(
            db, tenant_id, campaign_id, lookback_start, as_of_date
        )

        if not points:
            continue

        # The detectors expect a dict keyed by "channel" (or any grouping key).
        # We key by campaign_id string so each campaign is its own "bucket".
        by_campaign: dict[str, list[DailyPoint]] = {str(campaign_id): points}

        # Run all six detectors
        results: list[DetectorResult] = []
        results.extend(detect_anomaly(by_campaign, as_of_date))
        results.extend(detect_roas_drop(by_campaign, as_of_date))
        results.extend(detect_spend_spike(by_campaign, as_of_date))
        results.extend(detect_zero_conversions(by_campaign, as_of_date))
        results.extend(detect_ctr_drop(by_campaign, as_of_date))
        results.extend(detect_cpc_rise(by_campaign, as_of_date))

        for result in results:
            all_recommendations.append({
                "campaign_id": str(campaign_id),
                "campaign_name": campaign_name,
                "channel": channel_key,
                "category": result.category,
                "severity": result.severity,
                "score": result.score,
                "metric": result.metric,
                "message": _build_turkish_message(result, campaign_name),
                "suggested_action": _pick_suggested_action(result),
                "period_start": str(result.period_start),
                "period_end": str(result.period_end),
                "data": result.data,
            })

    # Sort by score descending so the most urgent recommendations come first
    all_recommendations.sort(key=lambda r: r["score"], reverse=True)
    return all_recommendations
