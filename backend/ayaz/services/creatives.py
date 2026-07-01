"""Creative / Ad-level Performance Analysis service.

Public API
----------
    ad_performance(db, tenant_id, date_from, date_to, *, sort="spend") -> dict

Design notes
------------
* Aggregates FactDailyMetrics grouped at the ad grain (dim_ad), excluding
  the sentinel "(not set)" ad rows that represent campaign-level data.
* Derived metrics (CTR, CPC, CPA, ROAS) are computed exclusively via the
  shared metrics layer (ayaz.services.metrics) — no formula duplication.
* top / bottom lists are derived from the aggregated per-ad data using ROAS:
    top   — 3 best ROAS (any spend, including zero-spend ads if they somehow
             have conversion value, but in practice only spenders).
    bottom — 3 worst ROAS among ads that have spend > 0 (ignores non-spenders
             because ROAS=0 for no-spend ads is trivially bad and unhelpful).
* commentary — deterministic Turkish text grounded in the real aggregated
  numbers.  Named templates are filled from actual aggregates; no fabrication.
* Decimal -> float conversion happens only at the final JSON-edge dict, never
  inside intermediate calculations.
* Tenant isolation: every query carries an explicit tenant_id filter.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimAd, DimAdSet, DimCampaign, DimChannel, FactDailyMetrics
from ayaz.services.metrics import compute_derived_metrics

# Sentinel value used for campaign-level / unattributed rows; excluded from
# ad-level analysis because they are not real creatives.
_NOT_SET = "(not set)"

# Valid sort keys for the ads list (parallel to ads.py _SORT_COLUMNS).
_AD_SORT_COLUMNS: frozenset[str] = frozenset(
    {"spend", "impressions", "clicks", "conversions", "conversion_value",
     "ctr", "cpc", "cpa", "roas", "ad_name", "campaign_name", "channel"}
)


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, or None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


# ── Aggregation query ─────────────────────────────────────────────────────────


def _query_ad_aggregates(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> list[Any]:
    """Return one aggregated row per ad (excluding sentinel "(not set)" ads).

    Each row exposes:
        ad_id, ad_name, campaign_id, campaign_name, channel_key,
        impressions, clicks, spend, conversions, conversion_value
    """
    rows = db.execute(
        select(
            DimAd.id.label("ad_id"),
            DimAd.name.label("ad_name"),
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
        .join(DimAd, FactDailyMetrics.ad_id == DimAd.id)
        .join(DimAdSet, FactDailyMetrics.adset_id == DimAdSet.id)
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            DimCampaign.tenant_id == tenant_id,
            DimAd.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
            # Exclude the sentinel "(not set)" ad — these are campaign-level rows
            DimAd.name != _NOT_SET,
        )
        .group_by(
            DimAd.id, DimAd.name,
            DimCampaign.id, DimCampaign.name,
            DimChannel.key,
        )
        .order_by(DimAd.name)
    ).mappings().all()
    return rows


def _row_to_ad_dict(row: Any) -> dict:
    """Convert one aggregation row into the standard ad performance dict."""
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
        "ad_id": str(row["ad_id"]),
        "ad_name": row["ad_name"],
        "campaign_id": str(row["campaign_id"]),
        "campaign_name": row["campaign_name"],
        "channel": row["channel_key"],
        "spend": float(spend),
        "impressions": float(impressions),
        "clicks": float(clicks),
        "conversions": float(conversions),
        "conversion_value": float(conv_value),
        "roas": float(derived["roas"]),
        "ctr": float(derived["ctr"]),
        "cpc": float(derived["cpc"]),
        "cpa": float(derived["cpa"]),
    }


# ── Commentary builder ────────────────────────────────────────────────────────


def _build_commentary(ads: list[dict], top: list[dict], bottom: list[dict]) -> str:
    """Build deterministic Turkish commentary grounded in the real aggregates.

    Rules:
    - If no ads: generic "no data" message.
    - Names the best creative by ad_name and its ROAS (2 dp).
    - Names the worst spending creative by ad_name, its spend (2 dp), and
      whether it has zero conversions (dönüşüm yok) or just low ROAS.
    - No fabrication — every number comes from the aggregated dicts passed in.
    """
    if not ads:
        return "Seçilen tarih aralığında reklam düzeyinde veri bulunamadı."

    parts: list[str] = []

    if top:
        best = top[0]
        parts.append(
            f"'{best['ad_name']}' reklamı {best['roas']:.2f}x ROAS ile en verimli kreatif."
        )

    if bottom:
        worst = bottom[0]
        spend_val = worst["spend"]
        if worst["conversions"] == 0.0:
            parts.append(
                f"'{worst['ad_name']}' reklamı ₺{spend_val:.2f} harcadı, "
                f"dönüşüm yok — durdurmayı değerlendirin."
            )
        else:
            roas_val = worst["roas"]
            parts.append(
                f"'{worst['ad_name']}' reklamı ₺{spend_val:.2f} harcadı, "
                f"ROAS yalnızca {roas_val:.2f}x — bütçeyi gözden geçirin."
            )

    if len(ads) > 1:
        total_spend = sum(a["spend"] for a in ads)
        parts.append(
            f"Toplam {len(ads)} reklam analiz edildi, toplam harcama ₺{total_spend:.2f}."
        )

    return " ".join(parts)


# ── Public service function ───────────────────────────────────────────────────


def ad_performance(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    sort: str = "spend",
) -> dict:
    """Aggregate FactDailyMetrics at ad grain and return creative performance.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries issued).
    tenant_id:
        Tenant UUID — all queries are explicitly scoped to this tenant.
    date_from:
        Inclusive start of the date range.
    date_to:
        Inclusive end of the date range.
    sort:
        Column to sort the ``ads`` list by (descending).  Must be one of the
        keys in _AD_SORT_COLUMNS.  Defaults to "spend".

    Returns
    -------
    dict with keys:
        ads: list of ad dicts sorted by ``sort`` descending, each with:
            ad_id, ad_name, campaign_id, campaign_name, channel,
            spend, impressions, clicks, conversions, conversion_value,
            roas, ctr, cpc, cpa
        top: list of up to 3 best-ROAS ad dicts
        bottom: list of up to 3 worst-ROAS ad dicts among spenders (spend > 0)
        commentary: deterministic Turkish narrative string
    """
    rows = _query_ad_aggregates(db, tenant_id, date_from, date_to)
    ads = [_row_to_ad_dict(r) for r in rows]

    # ── Sort the main ads list ────────────────────────────────────────────
    effective_sort = sort if (sort and sort in _AD_SORT_COLUMNS) else "spend"
    ads.sort(key=lambda a: a.get(effective_sort, 0) or 0, reverse=True)

    # ── Top 3 by ROAS (best performers) ──────────────────────────────────
    # Among all ads with any spend; ROAS=0 when no conversion value.
    ads_with_spend = [a for a in ads if a["spend"] > 0]
    top = sorted(ads_with_spend, key=lambda a: a["roas"], reverse=True)[:3]

    # ── Bottom 3 by ROAS (worst spenders) ────────────────────────────────
    # Only include ads that actually spent money; excludes zero-spend ads
    # because their ROAS=0 is trivially uninformative.
    bottom = sorted(ads_with_spend, key=lambda a: a["roas"])[:3]

    commentary = _build_commentary(ads, top, bottom)

    return {
        "ads": ads,
        "top": top,
        "bottom": bottom,
        "commentary": commentary,
    }
