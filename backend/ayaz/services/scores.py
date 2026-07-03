"""Performance scoring layer — transparent, self-relative marketing scores.

Design philosophy
-----------------
Scores are computed by comparing the SELECTED period to the immediately preceding
equal-length period (the "baseline").  This is entirely self-relative: there are
no external benchmarks, no industry averages, no hype.  A score of ~50 means
"same as your own recent history".

Scoring formula (ratio → score)
--------------------------------
For each component metric we compute:

    ratio = current_value / baseline_value

Then map ratio to a 0–100 score via a bounded sigmoid-like linear interpolation:

    score = 50 + 50 * clamp((ratio - 1) / SENSITIVITY, -1, 1)

where SENSITIVITY = 0.5 (i.e. a 50% improvement → score ≈ 100; a 50% regression
→ score ≈ 0; equal performance → exactly 50).

Breaking this down:
  - ratio == 1.0  (current == baseline)  → (1-1)/0.5 = 0  → 50 + 0   = 50
  - ratio == 1.5  (+50% vs baseline)     → (1.5-1)/0.5=1  → 50 + 50  = 100
  - ratio == 0.5  (-50% vs baseline)     → (0.5-1)/0.5=-1 → 50 - 50  = 0
  - ratio == 2.0  (+100%)                → clamped to 1    → score = 100
  - ratio == 0.0  (-100%, baseline > 0)  → clamped to -1   → score = 0

For metrics where LOWER is better (CPA), we invert before scoring:
    inverted_ratio = baseline_value / current_value
so that improving (lower CPA) still maps to ratio > 1.

Component scores and weights
----------------------------
Verimlilik (Efficiency) — 40% weight
    Driven by ROAS (primary) and CPA-inverse (secondary).
    Combined ratio = 0.6 * roas_ratio + 0.4 * cpa_inv_ratio
    When only one sub-metric has a valid baseline, uses that one only.
    When neither is available, returns neutral 50.

Etkileşim (Engagement) — 30% weight
    Driven by CTR (clicks / impressions).
    ratio = current_ctr / baseline_ctr

Dönüşüm (Conversion) — 30% weight
    Driven by conversion rate (conversions / clicks).
    ratio = current_conv_rate / baseline_conv_rate

Genel Etkinlik (Overall Effectiveness) — weighted average:
    overall = 0.40 * efficiency + 0.30 * engagement + 0.30 * conversion

Neutral score policy
--------------------
When a baseline is zero (no historical data) OR when the current period has
zero clicks (making CVR undefined), the component returns score=50 with a
``basis`` note "yeterli geçmiş veri yok" — never crashes and never divides
by zero.  Scores are always clamped to [0, 100].

Rating thresholds
-----------------
    >= 67  →  "iyi"
    34–66  →  "orta"
    <  34  →  "zayıf"

Pure-function guarantee
-----------------------
``compute_scores(current_totals, baseline_totals)`` takes plain dicts of
Decimal/float values and returns a plain dict.  No DB, no HTTP, no side-effects.
This makes it fully unit-testable in isolation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ayaz.services.trformat import tr_num, tr_pct, tr_roas

# ── Constants ──────────────────────────────────────────────────────────────────

# Sensitivity: how much relative change maps to full score swing.
# 0.5 = ±50% change vs baseline → full 0 or 100 score.
_SENSITIVITY: float = 0.5

# Component weights (must sum to 1.0).
_WEIGHT_EFFICIENCY: float = 0.40
_WEIGHT_ENGAGEMENT: float = 0.30
_WEIGHT_CONVERSION: float = 0.30

# Rating thresholds.
_THRESHOLD_IYTL: int = 67   # >= this → "iyi"
_THRESHOLD_ORTA: int = 34   # >= this → "orta", else "zayıf"

# Basis string when there is no historical baseline to compare against.
_NO_BASELINE_NOTE = "yeterli geçmiş veri yok"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_float(v: Any) -> float:
    """Coerce Decimal/int/float/None to float, treating None as 0.0."""
    if v is None:
        return 0.0
    return float(v)


def _ratio_to_score(ratio: float) -> int:
    """Map a performance ratio to a 0–100 score.

    Formula: score = 50 + 50 * clamp((ratio - 1) / SENSITIVITY, -1, 1)

    Examples:
      ratio=1.0  → score=50  (same as baseline)
      ratio=1.5  → score=100 (+50% improvement)
      ratio=0.5  → score=0   (-50% regression)
      ratio=2.0  → score=100 (clamped)
      ratio=0.0  → score=0   (clamped)

    Parameters
    ----------
    ratio:
        current / baseline (already inverted for lower-is-better metrics).

    Returns
    -------
    int in [0, 100].
    """
    normalised = (ratio - 1.0) / _SENSITIVITY
    clamped = max(-1.0, min(1.0, normalised))
    raw = 50.0 + 50.0 * clamped
    return int(round(max(0.0, min(100.0, raw))))


def _rating(score: int) -> str:
    """Return Turkish rating label from a 0–100 score.

    >= 67  → "iyi"
    34–66  → "orta"
    <  34  → "zayıf"
    """
    if score >= _THRESHOLD_IYTL:
        return "iyi"
    if score >= _THRESHOLD_ORTA:
        return "orta"
    return "zayıf"


def _fmt_pct(ratio: float) -> str:
    """Format a ratio change as a compact percentage string for basis notes.

    Examples: 0.14 → "+%14", -0.14 → "-%14", 0.0 → "%0"
    """
    pct = round((ratio - 1.0) * 100)
    if pct >= 0:
        return f"+%{pct}"
    return f"-%{abs(pct)}"


# ── Component scorers ──────────────────────────────────────────────────────────


def _score_efficiency(curr: dict[str, float], base: dict[str, float]) -> dict:
    """Score Verimlilik (Efficiency).

    Primary driver: ROAS (higher is better).
    Secondary driver: CPA inverse (lower CPA is better → inverted ratio).

    Combined ratio = 0.6 * roas_ratio + 0.4 * cpa_inv_ratio.
    Falls back to whichever sub-metric has a valid (non-zero) baseline.
    If neither has a baseline, returns neutral 50.

    The "value" field reports current ROAS as the headline metric for display.
    The "baseline" field reports baseline ROAS.
    """
    curr_roas = curr["roas"]
    base_roas = base["roas"]
    curr_cpa = curr["cpa"]
    base_cpa = base["cpa"]

    has_roas = base_roas > 0.0
    has_cpa = base_cpa > 0.0 and curr_cpa > 0.0  # need current too for inversion

    if not has_roas and not has_cpa:
        return {
            "key": "efficiency",
            "label": "Verimlilik",
            "score": 50,
            "value": curr_roas,
            "baseline": base_roas,
            "basis": _NO_BASELINE_NOTE,
        }

    roas_ratio: float = 0.0
    cpa_inv_ratio: float = 0.0

    if has_roas:
        roas_ratio = curr_roas / base_roas
    if has_cpa:
        # Lower CPA = better → invert: baseline / current > 1 when CPA improved.
        cpa_inv_ratio = base_cpa / curr_cpa

    if has_roas and has_cpa:
        combined_ratio = 0.6 * roas_ratio + 0.4 * cpa_inv_ratio
        roas_pct = _fmt_pct(roas_ratio)
        cpa_pct = _fmt_pct(cpa_inv_ratio)  # cpa_inv_ratio > 1 means CPA went DOWN
        basis = (
            f"ROAS {tr_roas(curr_roas)} · önceki dönem {tr_roas(base_roas)} ({roas_pct}) · "
            f"CPA {tr_num(curr_cpa)} · önceki {tr_num(base_cpa)} ({cpa_pct})"
        )
    elif has_roas:
        combined_ratio = roas_ratio
        basis = (
            f"ROAS {tr_roas(curr_roas)} · önceki dönem {tr_roas(base_roas)} ({_fmt_pct(roas_ratio)})"
        )
    else:
        combined_ratio = cpa_inv_ratio
        basis = (
            f"CPA {tr_num(curr_cpa)} · önceki dönem {tr_num(base_cpa)} ({_fmt_pct(cpa_inv_ratio)})"
        )

    score = _ratio_to_score(combined_ratio)
    return {
        "key": "efficiency",
        "label": "Verimlilik",
        "score": score,
        "value": curr_roas,
        "baseline": base_roas,
        "basis": basis,
    }


def _score_engagement(curr: dict[str, float], base: dict[str, float]) -> dict:
    """Score Etkileşim (Engagement).

    Driver: CTR = clicks / impressions (higher is better).
    Returns neutral 50 when baseline CTR is zero.
    """
    curr_ctr = curr["ctr"]
    base_ctr = base["ctr"]

    if base_ctr == 0.0:
        return {
            "key": "engagement",
            "label": "Etkileşim",
            "score": 50,
            "value": curr_ctr,
            "baseline": base_ctr,
            "basis": _NO_BASELINE_NOTE,
        }

    ratio = curr_ctr / base_ctr
    score = _ratio_to_score(ratio)
    basis = (
        f"CTR {tr_pct(curr_ctr * 100, 2)} · önceki dönem {tr_pct(base_ctr * 100, 2)} ({_fmt_pct(ratio)})"
    )
    return {
        "key": "engagement",
        "label": "Etkileşim",
        "score": score,
        "value": curr_ctr,
        "baseline": base_ctr,
        "basis": basis,
    }


def _conversion_rate(totals: dict[str, float]) -> float:
    """Compute conversion rate = conversions / clicks.  Returns 0.0 when clicks=0."""
    clicks = totals["clicks"]
    if clicks == 0.0:
        return 0.0
    return totals["conversions"] / clicks


def _score_conversion(curr: dict[str, float], base: dict[str, float]) -> dict:
    """Score Dönüşüm (Conversion).

    Driver: conversion rate = conversions / clicks (higher is better).
    Returns neutral 50 when:
    - baseline clicks are zero (no history), OR
    - current clicks are zero (cannot compute current CVR).
    """
    curr_cvr = _conversion_rate(curr)
    base_cvr = _conversion_rate(base)

    if base_cvr == 0.0 or curr["clicks"] == 0.0:
        return {
            "key": "conversion",
            "label": "Dönüşüm",
            "score": 50,
            "value": curr_cvr,
            "baseline": base_cvr,
            "basis": _NO_BASELINE_NOTE,
        }

    ratio = curr_cvr / base_cvr
    score = _ratio_to_score(ratio)
    basis = (
        f"Dönüşüm oranı {tr_pct(curr_cvr * 100, 2)} · "
        f"önceki dönem {tr_pct(base_cvr * 100, 2)} ({_fmt_pct(ratio)})"
    )
    return {
        "key": "conversion",
        "label": "Dönüşüm",
        "score": score,
        "value": curr_cvr,
        "baseline": base_cvr,
        "basis": basis,
    }


# ── Public API ────────────────────────────────────────────────────────────────


def compute_scores(
    current_totals: dict[str, Any],
    baseline_totals: dict[str, Any],
) -> dict:
    """Compute self-relative performance scores for the current vs baseline period.

    This is a PURE FUNCTION — no DB, no HTTP, no side-effects.  All inputs and
    outputs are plain Python dicts.  Suitable for unit testing in complete
    isolation.

    Parameters
    ----------
    current_totals:
        Dict with at least these keys (Decimal or float accepted):
        spend, impressions, clicks, conversions, conversion_value,
        ctr, cpc, cpa, roas.
        Typically the ``totals`` field from ``_aggregate_period``.

    baseline_totals:
        Same shape as ``current_totals`` for the preceding equal-length period.
        This is the self-relative baseline — NOT an external benchmark.

    Returns
    -------
    dict matching the scores endpoint response body:
    {
      "overall": {"score": int, "label": "Genel Etkinlik", "rating": str},
      "components": [
        {"key": str, "label": str, "score": int, "value": float,
         "baseline": float, "basis": str},
        ...
      ]
    }

    Scoring formula
    ---------------
    For each component:
        ratio  = current_metric / baseline_metric  (or inverted for lower-is-better)
        score  = 50 + 50 * clamp((ratio - 1) / 0.5, -1, 1)

    Overall:
        overall = 0.40 * efficiency + 0.30 * engagement + 0.30 * conversion

    Neutral score (50) is returned whenever a baseline value is zero or a
    required current-period denominator is zero.  Never crashes.
    Scores are always clamped to [0, 100].
    """
    # Normalise all values to plain floats so arithmetic is uniform.
    curr: dict[str, float] = {k: _to_float(v) for k, v in current_totals.items()}
    base: dict[str, float] = {k: _to_float(v) for k, v in baseline_totals.items()}

    efficiency = _score_efficiency(curr, base)
    engagement = _score_engagement(curr, base)
    conversion = _score_conversion(curr, base)

    components = [efficiency, engagement, conversion]

    overall_raw = (
        _WEIGHT_EFFICIENCY * efficiency["score"]
        + _WEIGHT_ENGAGEMENT * engagement["score"]
        + _WEIGHT_CONVERSION * conversion["score"]
    )
    overall_score = int(round(max(0.0, min(100.0, overall_raw))))

    return {
        "overall": {
            "score": overall_score,
            "label": "Genel Etkinlik",
            "rating": _rating(overall_score),
        },
        "components": components,
    }
