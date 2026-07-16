"""Sektör Kıyaslama (Benchmark) service — TR E-ticaret referans aralıkları.

Compares the tenant's ad metrics for a given period against reference ranges
for the Turkish e-commerce vertical and classifies each metric as
"strong" (better than typical), "average" (within range), or "weak"
(below typical performance).

Public API
----------
build_benchmark(db, tenant_id, date_from, date_to) -> dict
    Returns the full benchmark result dict.

Notes
-----
The reference ranges in ``_REFERENCE_RANGES`` are indicative benchmarks for
the Turkish e-commerce sector based on publicly available research.  They are
NOT performance guarantees.  Actual results will vary by category, seasonality,
budget, and audience.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Reference ranges (TR e-ticaret; indicative — not guarantees) ──────────────
#
# Each entry: low, mid, high thresholds + higher_is_better flag.
#
# For higher_is_better=True  (ctr, roas, conversion_rate):
#   weak   = value < low
#   average = low <= value <= high
#   strong = value > high
#
# For higher_is_better=False (cpc, cpm — lower cost is better):
#   strong  = value < low    (cheaper than the "good" threshold → best)
#   average = low <= value <= high
#   weak    = value > high   (more expensive than the "bad" threshold → worst)

_REFERENCE_RANGES: dict[str, dict] = {
    "ctr": {
        "label": "Tıklama Oranı (TO)",
        "unit": "%",
        "low": 0.8,
        "mid": 1.5,
        "high": 2.5,
        "higher_is_better": True,
    },
    "cpc": {
        "label": "Tıklama Başı Maliyet (TBM)",
        "unit": "₺",
        "low": 2.0,
        "mid": 4.0,
        "high": 8.0,
        "higher_is_better": False,
    },
    "roas": {
        "label": "Reklam Harcama Getirisi (ROAS)",
        "unit": "x",
        "low": 2.0,
        "mid": 3.5,
        "high": 5.0,
        "higher_is_better": True,
    },
    "conversion_rate": {
        "label": "Dönüşüm Oranı",
        "unit": "%",
        "low": 1.0,
        "mid": 2.5,
        "high": 4.0,
        "higher_is_better": True,
    },
    "cpm": {
        "label": "Bin Gösterim Başı Maliyet (BGBM)",
        "unit": "₺",
        "low": 30.0,
        "mid": 60.0,
        "high": 90.0,
        "higher_is_better": False,
    },
}

# Canonical metric order for the response.
_METRIC_ORDER = ["ctr", "cpc", "roas", "conversion_rate", "cpm"]


# ── Position helpers ──────────────────────────────────────────────────────────


def _classify_position(
    value: float,
    low: float,
    high: float,
    higher_is_better: bool,
) -> str:
    """Map a metric value to "strong" | "average" | "weak".

    For higher_is_better metrics (ctr, roas, conversion_rate):
        strong  = value > high
        average = low <= value <= high
        weak    = value < low

    For lower_is_better metrics (cpc, cpm):
        strong  = value < low   (below the "good" threshold)
        average = low <= value <= high
        weak    = value > high  (above the "poor" threshold)
    """
    if higher_is_better:
        if value > high:
            return "strong"
        if value >= low:
            return "average"
        return "weak"
    else:
        # lower is better → invert the direction
        if value < low:
            return "strong"
        if value <= high:
            return "average"
        return "weak"


def _build_verdict(
    key: str,
    position: str,
    higher_is_better: bool,
) -> str:
    """Return a Turkish one-liner verdict for a metric position."""
    _verdicts: dict[str, dict[str, str]] = {
        "ctr": {
            "strong": "TO'nuz sektör referansının üzerinde — güçlü.",
            "average": "TO'nuz sektör referans aralığında — ortalama.",
            "weak": "TO'nuz sektör referansının altında — iyileştirme fırsatı var.",
        },
        "cpc": {
            "strong": "TBM'niz sektör referansının altında — verimli harcama.",
            "average": "TBM'niz sektör referans aralığında — ortalama.",
            "weak": "TBM'niz sektör referansının üzerinde — maliyetleri düşürmeyi değerlendirin.",
        },
        "roas": {
            "strong": "ROAS'ınız sektör referansının üzerinde — güçlü getiri.",
            "average": "ROAS'ınız sektör referans aralığında — ortalama.",
            "weak": "ROAS'ınız sektör referansının altında — optimizasyon önerilir.",
        },
        "conversion_rate": {
            "strong": "Dönüşüm oranınız sektör referansının üzerinde — güçlü.",
            "average": "Dönüşüm oranınız sektör referans aralığında — ortalama.",
            "weak": "Dönüşüm oranınız sektör referansının altında — açılış sayfasını gözden geçirin.",
        },
        "cpm": {
            "strong": "BGBM'niz sektör referansının altında — görünürlük maliyeti verimli.",
            "average": "BGBM'niz sektör referans aralığında — ortalama.",
            "weak": "BGBM'niz sektör referansının üzerinde — hedefleme optimizasyonu önerilir.",
        },
    }
    return _verdicts.get(key, {}).get(position, "")


# ── Metric computation from summed totals ──────────────────────────────────────


def _compute_account_metrics(
    impressions: Decimal,
    clicks: Decimal,
    spend: Decimal,
    conversions: Decimal,
    conversion_value: Decimal,
) -> dict[str, float]:
    """Compute account-level derived metrics with div-by-zero guard (returns 0)."""

    def _safe_div(numerator: Decimal, denominator: Decimal) -> float:
        if denominator == Decimal(0):
            return 0.0
        return float(numerator / denominator)

    return {
        "ctr": _safe_div(clicks, impressions) * 100,
        "cpc": _safe_div(spend, clicks),
        "roas": _safe_div(conversion_value, spend),
        "conversion_rate": _safe_div(conversions, clicks) * 100,
        "cpm": _safe_div(spend, impressions) * 1000,
    }


# ── Channel-level ROAS / CTR position ─────────────────────────────────────────


def _channel_positions(channel_data: dict) -> tuple[str, str]:
    """Return (roas_position, ctr_position) for a single channel data dict."""
    impressions = channel_data["impressions"]
    clicks = channel_data["clicks"]
    spend = channel_data["spend"]
    conversion_value = channel_data["conversion_value"]

    ch_metrics = _compute_account_metrics(
        impressions, clicks, spend, Decimal(0), conversion_value
    )

    roas_ref = _REFERENCE_RANGES["roas"]
    ctr_ref = _REFERENCE_RANGES["ctr"]

    roas_pos = _classify_position(
        ch_metrics["roas"],
        roas_ref["low"],
        roas_ref["high"],
        roas_ref["higher_is_better"],
    )
    ctr_pos = _classify_position(
        ch_metrics["ctr"],
        ctr_ref["low"],
        ctr_ref["high"],
        ctr_ref["higher_is_better"],
    )
    return roas_pos, ctr_pos


# ── Headline builder ───────────────────────────────────────────────────────────


def _build_headline(counts: dict[str, int]) -> str:
    """Build a Turkish summary headline from position counts."""
    strong = counts["strong"]
    weak = counts["weak"]
    avg = counts["average"]
    total = strong + weak + avg

    if total == 0:
        return "Henüz yeterli reklam verisi yok."

    parts = []
    if strong > 0:
        parts.append(f"{strong} metrik güçlü")
    if avg > 0:
        parts.append(f"{avg} metrik ortalama")
    if weak > 0:
        parts.append(f"{weak} metrik zayıf")

    return ", ".join(parts) + " sektör kıyaslamasında."


# ── Insight generation (deterministic, cross-metric) ──────────────────────────
#
# The per-metric verdicts already say "güçlü / ortalama / zayıf".  These insights
# go one level up: they quantify the single biggest opportunity, diagnose a
# traffic-vs-conversion mismatch, and surface channel reallocation — the reasoning
# a data analyst would add on top of the raw position labels.  Fully rule-based;
# no model calls, no randomness.

_OPPORTUNITY_HINTS: dict[str, str] = {
    "ctr": "Kreatif başlık/görselleri ve hedef kitleyi güçlendirin; en düşük performanslı reklamları durdurun.",
    "cpc": "Teklif stratejisini ve anahtar kelime/hedefleme kalitesini gözden geçirin; kalite puanını yükseltin.",
    "roas": "Bütçeyi en yüksek getirili kampanyalara kaydırın, düşük getirili reklam setlerini kısın.",
    "conversion_rate": "Açılış sayfası deneyimini, teklif netliğini ve ödeme akışını iyileştirin.",
    "cpm": "Hedefleme genişliğini ve yayın yerlerini gözden geçirin; aşırı dar kitlelerden kaçının.",
}


def _fmt_metric(value: float, unit: str) -> str:
    """Format a metric value with the Turkish decimal comma, matching the UI."""
    decimals = 2 if unit == "₺" else 1
    s = f"{value:.{decimals}f}".replace(".", ",")
    if unit == "₺":
        return "₺" + s
    if unit == "x":
        return s + "x"
    return s + "%"


def _build_insights(
    values: dict[str, float],
    positions: dict[str, str],
    channel_rows: list[dict],
) -> list[dict]:
    """Derive up to three prioritized, cross-metric insights (deterministic).

    Parameters
    ----------
    values:
        Account-level metric values keyed by metric key (ctr, cpc, ...).
    positions:
        Per-metric position ("strong" | "average" | "weak").
    channel_rows:
        Per-channel rows (each with ``label`` and ``roas``), already sorted.

    Returns
    -------
    list of ``{severity, title, detail}`` dicts (max 3).  ``severity`` is one of
    ``"opportunity"`` (biggest lever), ``"diagnostic"`` (cross-metric mismatch),
    ``"strength"`` (reallocate to what works).
    """
    insights: list[dict] = []

    # 1) Biggest opportunity — weakest metric by relative gap to its threshold.
    worst_key: str | None = None
    worst_gap = 0.0
    for key in _METRIC_ORDER:
        if positions.get(key) != "weak":
            continue
        ref = _REFERENCE_RANGES[key]
        val = values[key]
        if ref["higher_is_better"]:
            gap = (ref["low"] - val) / ref["low"] if ref["low"] else 0.0
        else:
            gap = (val - ref["high"]) / ref["high"] if ref["high"] else 0.0
        if gap > worst_gap:
            worst_gap = gap
            worst_key = key

    if worst_key is not None and worst_gap > 0:
        ref = _REFERENCE_RANGES[worst_key]
        val = values[worst_key]
        pct = round(worst_gap * 100)
        threshold = ref["low"] if ref["higher_is_better"] else ref["high"]
        direction = "altında" if ref["higher_is_better"] else "üzerinde"
        hint = _OPPORTUNITY_HINTS.get(worst_key, "")
        insights.append(
            {
                "severity": "opportunity",
                "title": f"En büyük fırsat: {ref['label']}",
                "detail": (
                    f"Değeriniz {_fmt_metric(val, ref['unit'])}, sektör referans eşiği "
                    f"{_fmt_metric(threshold, ref['unit'])} — yaklaşık %{pct} {direction}. {hint}"
                ),
            }
        )

    # 2) Traffic-vs-conversion diagnostic (cross-metric reasoning).
    ctr_pos = positions.get("ctr")
    conv_pos = positions.get("conversion_rate")
    ok = {"strong", "average"}
    if ctr_pos in ok and conv_pos == "weak":
        insights.append(
            {
                "severity": "diagnostic",
                "title": "Trafik geliyor ama dönüşmüyor",
                "detail": (
                    "Tıklama oranınız iyi ama tıklayanlar yeterince dönüşmüyor. Sorun büyük "
                    "olasılıkla açılış sayfası, fiyat/teklif ya da ödeme akışında — kreatiflerde "
                    "değil. Açılış sayfası hızını, teklif netliğini ve ödeme adımlarını gözden geçirin."
                ),
            }
        )
    elif ctr_pos == "weak" and conv_pos in ok:
        insights.append(
            {
                "severity": "diagnostic",
                "title": "Dönüşüm iyi ama trafik az",
                "detail": (
                    "Tıklayanlar iyi dönüşüyor ama yeterli tıklama alamıyorsunuz. Kreatif ve hedef "
                    "kitleyi güçlendirip gösterimi artırırsanız aynı dönüşüm oranıyla daha çok satış "
                    "elde edersiniz."
                ),
            }
        )

    # 3) Channel reallocation — best vs worst ROAS channel (needs ≥2 channels).
    if len(channel_rows) >= 2:
        best = max(channel_rows, key=lambda r: r["roas"])
        worst = min(channel_rows, key=lambda r: r["roas"])
        if (
            best is not worst
            and best["roas"] > 0
            and worst["roas"] > 0
            and best["roas"] >= worst["roas"] * 1.5
        ):
            insights.append(
                {
                    "severity": "strength",
                    "title": "Bütçeyi en verimli kanala kaydırın",
                    "detail": (
                        f"{best['label']} ROAS'ı {_fmt_metric(best['roas'], 'x')} ile en yüksek; "
                        f"{worst['label']} ise {_fmt_metric(worst['roas'], 'x')}. Bütçenin bir kısmını "
                        f"{worst['label']} kanalından {best['label']} kanalına kaydırmak toplam "
                        f"getiriyi artırabilir."
                    ),
                }
            )

    return insights[:3]


# ── Public API ────────────────────────────────────────────────────────────────


def build_benchmark(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict:
    """Build the sector benchmark report for the tenant.

    Aggregates raw metrics across all channels for [date_from, date_to],
    computes account-level derived KPIs, and compares them against the
    TR e-commerce reference ranges defined in ``_REFERENCE_RANGES``.

    Parameters
    ----------
    db:
        SQLAlchemy session scoped to the current request.
    tenant_id:
        Tenant UUID.  All queries are filtered to this tenant — no
        cross-tenant leakage is possible.
    date_from, date_to:
        Inclusive date range for the comparison period.

    Returns
    -------
    dict matching the benchmark response schema (see module docstring).

    Tenant isolation
    ----------------
    All SQL passes ``tenant_id`` as a WHERE predicate via the shared
    ``_aggregate_by_channel_raw`` helper.  No cross-tenant data is accessible.

    Kaynak-tipi ayrımı (ad vs analytics)
    -------------------------------------
    Ad platforms (google_ads, meta_ads, ...) and analytics sources (ga4,
    search_console) write to the same fact-table columns.  This function's
    account-level metrics are all **ad-only**:

    - CTR/CPC/CPM use ad-only impressions/clicks/spend — Search Console's
      organic clicks/impressions would otherwise dilute a comparison meant
      for PAID media (the TR e-commerce reference ranges are paid-ads
      benchmarks).
    - Dönüşüm Oranı (conversion_rate) numerator is the source-of-truth
      conversions (GA4 wins when present and non-zero, else ad — see
      ``resolve_headline_metric``); the denominator stays ad-only clicks
      (mirrors CPA's existing "spend / headline-conversions" convention).
    - ROAS is the blended formula (source-of-truth revenue ÷ ad-only spend —
      see ``blended_roas``).

    Per-channel ``channels`` rows only include ``source_type == "ad"``
    channels: GA4/Search Console have structurally zero spend, so they would
    otherwise appear as a misleading "weak" 0-ROAS/0-CTR row and could
    corrupt the "reallocate budget to the best channel" insight (#3 below),
    which assumes every row is a real ad-spend channel.
    """
    from ayaz.services.channels import source_type
    from ayaz.services.metrics import (
        _aggregate_by_channel_raw,
        blended_roas as _blended_roas,
        resolve_headline_metric,
        split_channel_totals_by_source,
    )

    channel_data = _aggregate_by_channel_raw(db, tenant_id, date_from, date_to)

    # ── Kaynak-tipi ayrımı (ad vs analytics) — çift-sayımı önler ───────────
    split = split_channel_totals_by_source(channel_data)

    ad_impressions = split["ad_impressions"]
    ad_clicks = split["ad_clicks"]
    ad_spend = split["ad_spend"]
    ad_conversions = split["ad_conversions"]
    ad_conversion_value = split["ad_conversion_value"]
    analytics_conversions = split["analytics_conversions"]
    analytics_conversion_value = split["analytics_conversion_value"]

    headline_conversions = resolve_headline_metric(analytics_conversions, ad_conversions)
    headline_conversion_value = resolve_headline_metric(
        analytics_conversion_value, ad_conversion_value
    )

    has_data = ad_spend > Decimal(0) or ad_impressions > Decimal(0)

    # ── Compute account-level metrics (ad-only impressions/clicks/spend) ───
    metrics_values = _compute_account_metrics(
        ad_impressions,
        ad_clicks,
        ad_spend,
        headline_conversions,
        headline_conversion_value,
    )
    # ROAS explicitly via the shared blended-ROAS helper (source-of-truth
    # revenue ÷ ad-only spend) rather than relying on the coincidence that
    # ad_spend currently equals total spend.
    metrics_values["roas"] = float(
        _blended_roas(
            ad_spend=ad_spend,
            analytics_conversion_value=analytics_conversion_value,
            ad_conversion_value=ad_conversion_value,
        )
    )

    # ── Build metrics list in canonical order ──────────────────────────────
    metrics_list = []
    summary_counts: dict[str, int] = {"strong": 0, "average": 0, "weak": 0}
    positions: dict[str, str] = {}

    for key in _METRIC_ORDER:
        ref = _REFERENCE_RANGES[key]
        value = metrics_values[key]

        if has_data:
            position = _classify_position(
                value, ref["low"], ref["high"], ref["higher_is_better"]
            )
        else:
            position = "weak"

        positions[key] = position
        verdict = _build_verdict(key, position, ref["higher_is_better"])
        summary_counts[position] += 1

        metrics_list.append(
            {
                "key": key,
                "label": ref["label"],
                "unit": ref["unit"],
                "your_value": round(value, 4),
                "ref_low": ref["low"],
                "ref_mid": ref["mid"],
                "ref_high": ref["high"],
                "higher_is_better": ref["higher_is_better"],
                "position": position,
                "verdict": verdict,
            }
        )

    # ── Build per-channel rows sorted by spend desc ────────────────────────
    roas_ref = _REFERENCE_RANGES["roas"]
    ctr_ref = _REFERENCE_RANGES["ctr"]

    channel_rows = []
    for ch_key, row in channel_data.items():
        # Only paid-media channels are comparable to an ad sector benchmark
        # and reallocatable via the "shift budget" insight (#3 below).
        if source_type(ch_key) != "ad":
            continue
        ch_spend = row["spend"]
        ch_impressions = row["impressions"]
        ch_clicks = row["clicks"]
        ch_conversion_value = row["conversion_value"]

        def _safe_div_ch(num: Decimal, den: Decimal) -> float:
            return float(num / den) if den != Decimal(0) else 0.0

        ch_roas = _safe_div_ch(ch_conversion_value, ch_spend)
        ch_ctr = _safe_div_ch(ch_clicks, ch_impressions) * 100

        roas_pos = _classify_position(
            ch_roas, roas_ref["low"], roas_ref["high"], roas_ref["higher_is_better"]
        )
        ctr_pos = _classify_position(
            ch_ctr, ctr_ref["low"], ctr_ref["high"], ctr_ref["higher_is_better"]
        )

        channel_rows.append(
            {
                "channel": ch_key,
                "label": row["label"],
                "roas": round(ch_roas, 4),
                "ctr": round(ch_ctr, 4),
                "roas_position": roas_pos,
                "ctr_position": ctr_pos,
                "_spend": float(ch_spend),  # used for sort; removed below
            }
        )

    channel_rows.sort(key=lambda r: r["_spend"], reverse=True)
    for r in channel_rows:
        r.pop("_spend")

    # ── Headline ───────────────────────────────────────────────────────────
    headline = _build_headline(summary_counts) if has_data else "Henüz yeterli reklam verisi yok."

    # ── Prioritized cross-metric insights (empty when there is no data) ─────
    insights = (
        _build_insights(metrics_values, positions, channel_rows) if has_data else []
    )

    return {
        "period": {
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
        "vertical": "E-ticaret",
        "metrics": metrics_list,
        "channels": channel_rows,
        "headline": headline,
        "summary_counts": summary_counts,
        "insights": insights,
    }
