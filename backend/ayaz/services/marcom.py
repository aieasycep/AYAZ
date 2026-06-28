"""Marcom Kreatif Lensi (Marketing Creative Lens) — service layer.

Public API
----------
    creative_insights(db, tenant_id, date_from, date_to, limit=8) -> dict

Design notes
------------
* Read-only over existing ad data — no new models or migrations.
* Delegates all DB access to ``ayaz.services.creatives.ad_performance``.
* All user-facing strings are in Turkish with correct diacritics.
* CTR is expressed as a PERCENT (0-100, rounded to 2 decimal places).
  Example: 0.031 raw → 3.10 percent.  Documented here and mirrored in the API
  response schema docstring.
* ``traffic_share_pct``: ad clicks / total clicks * 100, rounded to 1 dp.
* Tiering thresholds (for insight generation):
    high   — ad ctr >= 1.2 * avg_ctr
    low    — ad ctr <  0.8 * avg_ctr
    medium — otherwise
* The ``_engagement_insight`` helper is pure (no DB) so it can be unit-tested
  independently.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ayaz.services.creatives import ad_performance

# ── Tier thresholds ───────────────────────────────────────────────────────────

_HIGH_FACTOR = 1.2   # ad ctr >= avg_ctr * 1.2  → yüksek ilgi
_LOW_FACTOR  = 0.8   # ad ctr <  avg_ctr * 0.8  → düşük ilgi


# ── Pure insight helper ───────────────────────────────────────────────────────


def _engagement_insight(
    ad: dict[str, Any],
    avg_ctr_ratio: float,
    total_clicks: float,
) -> str:
    """Return a plain Turkish marketing sentence for one creative.

    Parameters
    ----------
    ad:
        Ad dict from ``ad_performance`` (keys: ad_name, clicks, ctr, …).
        ``ctr`` is the raw ratio as returned by the metrics layer (0–1).
    avg_ctr_ratio:
        Average CTR across all creatives in the period (raw ratio, 0–1).
        Pass 0.0 when there are no impressions overall.
    total_clicks:
        Total clicks across all creatives (used for traffic-share sentence).

    Returns
    -------
    str
        A single Turkish sentence.  Example:
        "12.400 tıklama ve %3,10 TO ile en çok ilgi gören kreatiflerden;
         toplam trafiğin %18,0'ini getirdi."
    """
    clicks      = int(ad.get("clicks", 0) or 0)
    ad_ctr_raw  = float(ad.get("ctr", 0.0) or 0.0)   # ratio 0-1
    ad_ctr_pct  = round(ad_ctr_raw * 100, 2)

    # Traffic share
    if total_clicks and total_clicks > 0:
        share = round(clicks / total_clicks * 100, 1)
    else:
        share = 0.0

    # Tier based on ctr vs average
    if avg_ctr_ratio and avg_ctr_ratio > 0:
        if ad_ctr_raw >= avg_ctr_ratio * _HIGH_FACTOR:
            tier = "yüksek ilgi"
        elif ad_ctr_raw < avg_ctr_ratio * _LOW_FACTOR:
            tier = "düşük ilgi"
        else:
            tier = "orta ilgi"
    else:
        # No avg available (zero impressions edge case)
        tier = "orta ilgi"

    # Format clicks with Turkish thousand separator (.)
    clicks_fmt = f"{clicks:,}".replace(",", ".")
    # Format CTR with Turkish decimal separator (,)
    ctr_str = f"{ad_ctr_pct:.2f}".replace(".", ",")
    share_str = f"{share:.1f}".replace(".", ",")

    return (
        f"{clicks_fmt} tıklama ve %{ctr_str} TO ile {tier} gösteren kreatif; "
        f"toplam trafiğin %{share_str}'ini getirdi."
    )


# ── Totals helper ─────────────────────────────────────────────────────────────


def _compute_totals(ads: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate totals across all ads."""
    total_impressions = sum(int(a.get("impressions", 0) or 0) for a in ads)
    total_clicks      = sum(int(a.get("clicks", 0) or 0) for a in ads)
    total_conversions = sum(float(a.get("conversions", 0.0) or 0.0) for a in ads)

    if total_impressions > 0:
        avg_ctr_pct = round(total_clicks / total_impressions * 100, 2)
    else:
        avg_ctr_pct = 0.0

    return {
        "impressions":     total_impressions,
        "clicks":          total_clicks,
        "conversions":     round(total_conversions, 4),
        "ctr":             avg_ctr_pct,          # percent, 2 dp
        "creatives_count": len(ads),
    }


# ── Headline builder ──────────────────────────────────────────────────────────


def _build_headline(ads: list[dict[str, Any]], totals: dict[str, Any]) -> str:
    """Return a single Turkish summary sentence.

    Empty-data fallback: "Bu dönemde kreatif verisi bulunamadı."
    """
    if not ads:
        return "Bu dönemde kreatif verisi bulunamadı."

    n            = totals["creatives_count"]
    impressions  = f"{totals['impressions']:,}".replace(",", ".")
    clicks       = f"{totals['clicks']:,}".replace(",", ".")
    top_name     = ads[0]["ad_name"]   # already sorted by clicks desc

    return (
        f"Son dönemde {n} kreatif toplam {impressions} gösterim ve "
        f"{clicks} tıklama getirdi; en çok ilgi gören: '{top_name}'."
    )


# ── Public service function ───────────────────────────────────────────────────


def creative_insights(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    limit: int = 8,
) -> dict[str, Any]:
    """Assemble marketing-language creative insights for the requested period.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries issued via ad_performance).
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    date_from:
        Inclusive start of the date range.
    date_to:
        Inclusive end of the date range.
    limit:
        Maximum number of top creatives to return (default 8).

    Returns
    -------
    dict with keys:
        totals: {impressions:int, clicks:int, ctr:float(percent), conversions:float,
                 creatives_count:int}
        headline: str (Turkish)
        top_creatives: list of up to ``limit`` creative dicts, sorted by clicks desc,
            each with: {ad_id, ad_name, campaign_name, channel, impressions(int),
                        clicks(int), ctr(float, PERCENT 0-100 rounded 2dp),
                        conversions(float), traffic_share_pct(float, rounded 1dp),
                        insight(str, Turkish)}

    CTR convention
    --------------
    All CTR values in this module are expressed as **percent** (0-100), rounded
    to 2 decimal places.  Example: raw ratio 0.031 → 3.10.
    """
    # 1. Fetch raw ad performance, sorted by clicks descending.
    result = ad_performance(db, tenant_id, date_from, date_to, sort="clicks")
    ads: list[dict[str, Any]] = result["ads"]

    # Defensive re-sort: guarantee clicks-desc even if ad_performance changes.
    ads = sorted(ads, key=lambda a: float(a.get("clicks", 0) or 0), reverse=True)

    # 2. Compute cross-creative totals.
    totals = _compute_totals(ads)
    total_clicks      = totals["clicks"]
    total_impressions = totals["impressions"]

    # Average CTR as raw ratio for tier calculation.
    avg_ctr_ratio = (total_clicks / total_impressions) if total_impressions > 0 else 0.0

    # 3. Build top_creatives list (up to limit entries).
    top_creatives: list[dict[str, Any]] = []
    for ad in ads[:limit]:
        ad_ctr_raw  = float(ad.get("ctr", 0.0) or 0.0)
        ad_ctr_pct  = round(ad_ctr_raw * 100, 2)

        ad_clicks_raw = float(ad.get("clicks", 0) or 0)
        share = round(ad_clicks_raw / total_clicks * 100, 1) if total_clicks > 0 else 0.0

        insight = _engagement_insight(ad, avg_ctr_ratio, float(total_clicks))

        top_creatives.append({
            "ad_id":             ad["ad_id"],
            "ad_name":           ad["ad_name"],
            "campaign_name":     ad["campaign_name"],
            "channel":           ad["channel"],
            "impressions":       int(ad.get("impressions", 0) or 0),
            "clicks":            int(ad.get("clicks", 0) or 0),
            "ctr":               ad_ctr_pct,           # PERCENT, 2 dp
            "conversions":       float(ad.get("conversions", 0.0) or 0.0),
            "traffic_share_pct": share,
            "insight":           insight,
        })

    # 4. Build headline.
    headline = _build_headline(ads, totals)

    return {
        "totals":        totals,
        "headline":      headline,
        "top_creatives": top_creatives,
    }
