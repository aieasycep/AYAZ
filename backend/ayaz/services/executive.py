"""Executive Overview service — Yönetici (CMO) Görünümü.

Assembles a single high-level marketing summary for a CEO/CMO from the
existing warehouse.  Pure aggregation — no new models, no migrations.

Public API
----------
build_overview(db, tenant_id, date_from, date_to) -> dict
    Returns the full executive overview dict.

_compute_totals(channel_data) -> dict
    Pure helper: sums raw channel data to totals dict.  Unit-testable.

_compute_delta(current, previous) -> float | None
    Pure helper: percentage change current vs previous.  Unit-testable.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Pure helpers (unit-testable without DB) ────────────────────────────────────


def _compute_totals(channel_data: dict[str, dict]) -> dict:
    """Sum raw channel aggregation data into cross-channel totals.

    Parameters
    ----------
    channel_data:
        Output of ``_aggregate_by_channel_raw`` — mapping of channel key to
        dict with keys: impressions, clicks, spend, conversions,
        conversion_value (all Decimal).

    Returns
    -------
    dict with keys: spend, revenue, conversions, clicks, impressions, roas,
    plus the kaynak-tipi (ad vs analytics) breakdown: ad_conversions,
    ad_conversion_value, analytics_conversions, analytics_conversion_value.
    All values are float.

    ``revenue``/``conversions`` are resolved via the source-of-truth rule
    (``resolve_headline_metric``): analytics (GA4) data wins when present
    and non-zero, otherwise falls back to the ad-channel total — this is
    NOT a blind SUM across ad + analytics channels anymore (that double-
    counted GA4's conversions on top of what the ad platforms already
    report). ``roas`` = ``blended_roas`` (source-of-truth revenue ÷ ad-only
    spend). When no analytics channel is present, all of the above reduce
    exactly to the pre-fix (ad-only) numbers — no behaviour change for
    tenants without GA4/Search Console connected.
    """
    from ayaz.services.metrics import (
        blended_roas as _blended_roas,
        resolve_headline_metric,
        split_channel_totals_by_source,
    )

    split = split_channel_totals_by_source(channel_data)

    total_spend = split["total_spend"]
    total_clicks = split["total_clicks"]
    total_impressions = split["total_impressions"]

    ad_conversions = split["ad_conversions"]
    ad_conversion_value = split["ad_conversion_value"]
    analytics_conversions = split["analytics_conversions"]
    analytics_conversion_value = split["analytics_conversion_value"]

    headline_conversions = resolve_headline_metric(analytics_conversions, ad_conversions)
    headline_revenue = resolve_headline_metric(
        analytics_conversion_value, ad_conversion_value
    )

    roas = float(
        _blended_roas(
            ad_spend=split["ad_spend"],
            analytics_conversion_value=analytics_conversion_value,
            ad_conversion_value=ad_conversion_value,
        )
    )

    return {
        "spend": float(total_spend),
        "revenue": float(headline_revenue),
        "conversions": float(headline_conversions),
        "clicks": float(total_clicks),
        "impressions": float(total_impressions),
        "roas": roas,
        "ad_conversions": float(ad_conversions),
        "ad_conversion_value": float(ad_conversion_value),
        "analytics_conversions": float(analytics_conversions),
        "analytics_conversion_value": float(analytics_conversion_value),
    }


def _compute_delta(current: float, previous: float) -> float | None:
    """Percentage change from previous to current, rounded to 1 decimal.

    Returns None when previous is 0 (avoid division by zero).
    Returns a positive value for increases, negative for decreases.
    """
    if previous == 0.0:
        return None
    return round((current - previous) / previous * 100, 1)


# ── Severity ordering for insights ────────────────────────────────────────────

_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}


def _severity_key(insight: dict) -> int:
    return _SEVERITY_ORDER.get(insight.get("severity", "info"), 99)


# ── Main assembler ─────────────────────────────────────────────────────────────


def build_overview(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict:
    """Assemble the executive marketing overview for the given period.

    Steps
    -----
    1. Aggregate current-period metrics per channel via
       ``_aggregate_by_channel_raw``.
    2. Aggregate previous equal-length period (immediately before date_from)
       for MoM-style delta computation.
    3. Build channel list sorted by spend descending with share_pct.
    4. Fetch goal progress via ``_get_goal_progress``.
    5. Fetch insights via ``_get_insights``, sort by severity, top 5.
    6. Build deterministic Turkish headline.

    Parameters
    ----------
    db:
        SQLAlchemy session (tenant-scoped queries only).
    tenant_id:
        Tenant UUID — all sub-queries filter on this value.
    date_from, date_to:
        Inclusive date range for the current period.

    Returns
    -------
    dict matching the ExecutiveOverviewResponse schema.
    """
    from ayaz.services.metrics import _aggregate_by_channel_raw
    from ayaz.services.copilot_tools import _get_goal_progress, _get_insights

    # ── Period dates ──────────────────────────────────────────────────────────
    period_len = (date_to - date_from).days  # e.g. 29 for 30-day window
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_len)

    # ── Aggregate current and previous periods ────────────────────────────────
    curr_data = _aggregate_by_channel_raw(db, tenant_id, date_from, date_to)
    prev_data = _aggregate_by_channel_raw(db, tenant_id, prev_from, prev_to)

    curr_totals = _compute_totals(curr_data)
    prev_totals = _compute_totals(prev_data)

    # ── Deltas (MoM-style) ────────────────────────────────────────────────────
    deltas = {
        "spend_pct": _compute_delta(curr_totals["spend"], prev_totals["spend"]),
        "revenue_pct": _compute_delta(curr_totals["revenue"], prev_totals["revenue"]),
        "conversions_pct": _compute_delta(
            curr_totals["conversions"], prev_totals["conversions"]
        ),
        "roas_pct": _compute_delta(curr_totals["roas"], prev_totals["roas"]),
    }

    # ── Channel list sorted by spend desc ─────────────────────────────────────
    total_spend = curr_totals["spend"]
    channels: list[dict] = []
    for ch_key, row in curr_data.items():
        spend = float(row["spend"])
        revenue = float(row["conversion_value"])
        ch_roas = (
            round(revenue / spend, 2) if spend > 0.0 else 0.0
        )
        share_pct = (
            round(spend / total_spend * 100, 1) if total_spend > 0.0 else 0.0
        )
        channels.append({
            "channel": ch_key,
            "label": str(row["label"]),
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "roas": ch_roas,
            "share_pct": share_pct,
        })

    channels.sort(key=lambda c: c["spend"], reverse=True)

    # ── Goals: top 5 active ───────────────────────────────────────────────────
    goal_result = _get_goal_progress(db, tenant_id)
    raw_goals = goal_result.get("goals", [])
    goals: list[dict] = [
        {
            "name": g["name"],
            "metric": g["metric"],
            "current_value": g["current_value"],
            "target_value": g["target_value"],
            # Goal service returns a 0..1+ ratio; the executive payload exposes
            # a 0-100+ percent so the UI can render bars/labels directly.
            "pct_to_target": round((g["pct_to_target"] or 0) * 100, 1),
            "status": g["status"],
        }
        for g in raw_goals[:5]
    ]

    # ── Insights: top 5 sorted by severity ───────────────────────────────────
    insight_result = _get_insights(db, tenant_id)
    raw_insights = insight_result.get("insights", [])
    raw_insights_sorted = sorted(raw_insights, key=_severity_key)
    insights: list[dict] = [
        {
            "severity": i["severity"],
            "title": i["title"],
            "channel": i.get("channel"),
        }
        for i in raw_insights_sorted[:5]
    ]

    # ── Headline: deterministic Turkish summary ───────────────────────────────
    headline = _build_headline(
        date_from=date_from,
        date_to=date_to,
        curr=curr_totals,
        deltas=deltas,
        channels=channels,
    )

    return {
        "period": {
            "date_from": str(date_from),
            "date_to": str(date_to),
            "prev_date_from": str(prev_from),
            "prev_date_to": str(prev_to),
        },
        "kpis": {
            "spend": round(curr_totals["spend"], 2),
            "revenue": round(curr_totals["revenue"], 2),
            "conversions": round(curr_totals["conversions"], 2),
            "clicks": round(curr_totals["clicks"], 2),
            "roas": round(curr_totals["roas"], 2),
            "deltas": deltas,
        },
        "channels": channels,
        "goals": goals,
        "insights": insights,
        "headline": headline,
    }


def _strongest_channel_label(channels: list[dict]) -> str:
    """Return the label of the best-performing channel by ROAS.

    "En güçlü kanal" (strongest channel) is a performance claim, so it must
    be ranked by ROAS — not by spend.  ``channels`` is sorted by spend
    descending for the table view; that ordering is independent of which
    channel is actually the most efficient one, so we re-rank here rather
    than reusing ``channels[0]``.

    Only channels with spend > 0 are eligible (a zero-spend channel has a
    ROAS of 0 by definition in this codebase and would otherwise never win
    ties against a real spender, but is excluded explicitly for clarity).
    Ties on ROAS are broken by spend descending for determinism.
    """
    eligible = [c for c in channels if c.get("spend", 0.0) > 0.0]
    if not eligible:
        return channels[0]["label"] if channels else "—"
    best = max(eligible, key=lambda c: (c.get("roas", 0.0), c.get("spend", 0.0)))
    return str(best["label"])


from ayaz.services.trformat import tr_pct, tr_roas, tr_tl


def _build_headline(
    *,
    date_from: date,
    date_to: date,
    curr: dict,
    deltas: dict,
    channels: list[dict],
) -> str:
    """Build a deterministic single-sentence Turkish headline.

    Uses real numbers from the current period.  When no data is available
    returns a fallback Turkish sentence.
    """
    if curr["spend"] == 0.0 and curr["revenue"] == 0.0:
        return "Bu dönemde yeterli veri yok."

    num_days = (date_to - date_from).days + 1

    spend_str = tr_tl(curr["spend"])
    revenue_str = tr_tl(curr["revenue"])
    roas_str = tr_roas(curr["roas"])

    # "En güçlü kanal" is a performance claim -> rank by ROAS, not spend, so
    # it never contradicts a ROAS-sorted ROI table elsewhere in the UI.
    top_label = _strongest_channel_label(channels)

    # MoM direction for ROAS
    roas_pct = deltas.get("roas_pct")
    if roas_pct is not None:
        direction = "arttı" if roas_pct >= 0 else "azaldı"
        abs_pct = abs(roas_pct)
        mom_clause = (
            f" ROAS geçen döneme göre {tr_pct(abs_pct)} {direction}."
        )
    else:
        mom_clause = ""

    return (
        f"Son {num_days} günde toplam {spend_str} harcama, {revenue_str} gelir "
        f"ve {roas_str} ROAS; en güçlü kanal: {top_label}.{mom_clause}"
    )
