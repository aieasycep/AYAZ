"""Insights detection engine — M4.

Public API
----------
    generate_insights(db, tenant_id, as_of_date, lookback_days=30)

This function analyses ``fact_daily_metrics`` for the given tenant and
produces :class:`~ayaz.models.insights.Insight` rows in the database.

Design principles
-----------------
* **Pure detectors**: every detector function takes a list of daily data
  points (plain dicts) and returns a list of :class:`DetectorResult` objects.
  No DB access inside the detector functions — makes unit testing trivial.
* **Idempotent**: before writing, we check whether an identical open insight
  already exists for the same (tenant, category, metric, channel, period_start,
  period_end, entity_id).  If found, the new signal is skipped.
* **Deduplication**: the same data structure enforces one open insight per
  "slot" — running ``generate_insights`` twice for the same ``as_of_date``
  is safe.
* **Severity and score**: each detector assigns a severity string and a
  numeric score so the dashboard can rank insights by importance.

Detectors implemented
---------------------
1. ``detect_anomaly``
   Z-score based anomaly detection per (metric, channel) over the lookback
   window.  Flags the most recent data point when |z| > ANOMALY_Z_THRESHOLD
   (default 2.5).  Covers: spend, roas, ctr, cpc, conversions.

2. ``detect_roas_drop``
   Compares ROAS in the last RECENT_DAYS days vs the prior RECENT_DAYS period.
   Fires when the percentage drop exceeds ROAS_DROP_THRESHOLD (default 20 %).
   Severity: warning at ≥20 %, critical at ≥40 %.

3. ``detect_spend_spike``
   Compares spend in the last RECENT_DAYS days vs prior period.
   Fires when the percentage rise exceeds SPEND_SPIKE_THRESHOLD (default 30 %).
   Severity: warning at ≥30 %, critical at ≥80 %.

4. ``detect_zero_conversions``
   Fires for any channel that had spend > 0 but conversions == 0 over the
   last RECENT_DAYS days.
   Severity: warning when spend is moderate, critical when spend is high
   (above ZERO_CONV_CRITICAL_SPEND).

5. ``detect_ctr_drop``
   Compares CTR in the last RECENT_DAYS days vs prior period.
   Fires when the percentage drop exceeds CTR_DROP_THRESHOLD (default 25 %).
   Severity: warning at ≥25 %, critical at ≥50 %.

6. ``detect_cpc_rise``
   Compares CPC in the last RECENT_DAYS days vs prior period.
   Fires when the percentage rise exceeds CPC_RISE_THRESHOLD (default 25 %).
   Severity: warning at ≥25 %, critical at ≥60 %.

7. ``detect_conversion_rate_drop``
   Compares CVR (conversions / clicks) in the last RECENT_DAYS days vs the prior
   RECENT_DAYS period.  Fires when the percentage drop exceeds CVR_DROP_THRESHOLD
   (default 25 %).  Severity: warning at ≥25 %, critical at ≥50 %.
   Divide-by-zero guarded: channels with zero clicks in either window are skipped.

8. ``detect_positive_movement``
   Fires an "info" severity positive insight when ROAS or conversions improve by at
   least POSITIVE_MOVEMENT_THRESHOLD (default 30 %) vs the prior period.  Noise
   floors prevent tiny absolute numbers from triggering: minimum spend
   POSITIVE_MOVEMENT_MIN_SPEND (default 50) for ROAS wins, minimum conversions
   POSITIVE_MOVEMENT_MIN_CONVERSIONS (default 5) for conversion wins.
   Severity: info.  Category: positive_movement.
"""

from __future__ import annotations

import logging
import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.insights import Insight
from ayaz.services.metrics import (
    compute_derived_metrics,
    ctr as _ctr,
    cpc as _cpc,
    roas as _roas,
    effective_spend,
)

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

ANOMALY_Z_THRESHOLD: float = 2.5
"""Standard-deviation multiplier beyond which a data point is flagged."""

RECENT_DAYS: int = 7
"""Number of tail days used as the 'current period' for rule comparisons."""

ROAS_DROP_THRESHOLD: float = 0.20
"""Fractional ROAS decline that triggers a warning (0.20 = 20 %)."""

ROAS_DROP_CRITICAL: float = 0.40
"""Fractional ROAS decline that escalates to critical."""

SPEND_SPIKE_THRESHOLD: float = 0.30
"""Fractional spend increase that triggers a warning."""

SPEND_SPIKE_CRITICAL: float = 0.80
"""Fractional spend increase that escalates to critical."""

ZERO_CONV_CRITICAL_SPEND: Decimal = Decimal("500")
"""Spend threshold (base currency) above which zero-conversions is critical."""

CTR_DROP_THRESHOLD: float = 0.25
"""Fractional CTR decline that triggers a warning."""

CTR_DROP_CRITICAL: float = 0.50
"""Fractional CTR decline that escalates to critical."""

CPC_RISE_THRESHOLD: float = 0.25
"""Fractional CPC rise that triggers a warning."""

CPC_RISE_CRITICAL: float = 0.60
"""Fractional CPC rise that escalates to critical."""

CVR_DROP_THRESHOLD: float = 0.25
"""Fractional CVR (conversion rate) decline that triggers a warning."""

CVR_DROP_CRITICAL: float = 0.50
"""Fractional CVR decline that escalates to critical."""

POSITIVE_MOVEMENT_THRESHOLD: float = 0.30
"""Fractional improvement (ROAS or conversions) that triggers a positive insight."""

POSITIVE_MOVEMENT_MIN_SPEND: Decimal = Decimal("50")
"""Minimum recent-period spend required before a positive ROAS signal is raised."""

POSITIVE_MOVEMENT_MIN_CONVERSIONS: Decimal = Decimal("5")
"""Minimum recent-period conversions required before a positive conversions signal fires."""

# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class DailyPoint:
    """Aggregated metric values for one (date, channel) pair.

    All Decimal fields use ``Decimal`` to preserve precision from the DB.
    Derived metrics (ctr_val, cpc_val, roas_val) are pre-computed floats for
    convenience inside the detector functions.
    """

    date_key: date
    channel_key: str
    impressions: Decimal
    clicks: Decimal
    spend: Decimal
    conversions: Decimal
    conversion_value: Decimal

    # Derived (computed after construction)
    ctr_val: float = 0.0
    cpc_val: float = 0.0
    roas_val: float = 0.0


@dataclass
class DetectorResult:
    """A single signal produced by a detector function.

    This is a pure-Python object — no ORM dependency.
    ``generate_insights`` maps these to Insight rows.
    """

    category: str
    severity: str          # "info" | "warning" | "critical"
    metric: str
    channel: str | None
    period_start: date
    period_end: date
    score: float
    data: dict[str, Any] = field(default_factory=dict)
    entity_type: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None


# ── Data loading helpers ──────────────────────────────────────────────────────


def _load_daily_points(
    db: Session,
    tenant_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> list[DailyPoint]:
    """Query fact_daily_metrics aggregated by (date_key, channel_key).

    Returns a list of :class:`DailyPoint` objects sorted by (channel_key,
    date_key) ascending.  Derived metrics are computed in Python from the
    aggregated sums using the shared metric-layer functions.
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
            FactDailyMetrics.date_key >= period_start,
            FactDailyMetrics.date_key <= period_end,
        )
        .group_by(FactDailyMetrics.date_key, DimChannel.key)
        .order_by(DimChannel.key, FactDailyMetrics.date_key)
    ).mappings().all()

    def _d(v: object) -> Decimal:
        return Decimal(str(v)) if v is not None else Decimal(0)

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


def _group_by_channel(
    points: list[DailyPoint],
) -> dict[str, list[DailyPoint]]:
    """Partition a flat list of DailyPoints into per-channel sub-lists."""
    result: dict[str, list[DailyPoint]] = {}
    for p in points:
        result.setdefault(p.channel_key, []).append(p)
    return result


def _sum_period(points: list[DailyPoint]) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return (impressions, clicks, spend, conversions, conversion_value) sums."""
    impressions = sum((p.impressions for p in points), Decimal(0))
    clicks = sum((p.clicks for p in points), Decimal(0))
    spend = sum((p.spend for p in points), Decimal(0))
    conversions = sum((p.conversions for p in points), Decimal(0))
    conversion_value = sum((p.conversion_value for p in points), Decimal(0))
    return impressions, clicks, spend, conversions, conversion_value


# ── Detector: anomaly (z-score / moving average) ─────────────────────────────


def detect_anomaly(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    z_threshold: float = ANOMALY_Z_THRESHOLD,
) -> list[DetectorResult]:
    """Detect statistical outliers in the most-recent data point per channel.

    Algorithm
    ---------
    For each (channel, metric) combination:
      1. Extract the time series of metric values across the lookback window.
      2. Compute the mean and standard deviation of all points *except* the
         most recent one (the candidate point).
      3. Compute z = (candidate - mean) / stdev.
      4. Flag when |z| > z_threshold.

    Requires at least 3 historical points (excluding the candidate) to have a
    meaningful standard deviation.  Otherwise the channel/metric is skipped.

    Metrics examined: spend, roas_val, ctr_val, cpc_val, conversions.
    """
    results: list[DetectorResult] = []

    metric_extractors: dict[str, Any] = {
        "spend": lambda p: float(p.spend),
        "roas": lambda p: p.roas_val,
        "ctr": lambda p: p.ctr_val,
        "cpc": lambda p: p.cpc_val,
        "conversions": lambda p: float(p.conversions),
    }

    for channel_key, channel_pts in by_channel.items():
        # Sort chronologically
        sorted_pts = sorted(channel_pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 4:
            # Need at least 3 baseline + 1 candidate
            continue

        candidate = sorted_pts[-1]
        history = sorted_pts[:-1]

        for metric_name, extractor in metric_extractors.items():
            hist_vals = [extractor(p) for p in history]
            candidate_val = extractor(candidate)

            # Skip if all values are zero (no activity)
            if all(v == 0.0 for v in hist_vals) and candidate_val == 0.0:
                continue

            if len(hist_vals) < 3:
                continue

            try:
                mean = statistics.mean(hist_vals)
                stdev = statistics.stdev(hist_vals)
            except statistics.StatisticsError:
                continue

            if stdev == 0.0:
                # No variance in history — cannot compute z-score
                continue

            z = (candidate_val - mean) / stdev
            if abs(z) <= z_threshold:
                continue

            # Determine severity and direction
            direction = "yuksek" if z > 0 else "dusuk"
            severity = "critical" if abs(z) > z_threshold * 1.4 else "warning"

            score = min(abs(z) * 10.0, 100.0)

            results.append(
                DetectorResult(
                    category="anomaly",
                    severity=severity,
                    metric=metric_name,
                    channel=channel_key,
                    period_start=history[0].date_key,
                    period_end=candidate.date_key,
                    score=score,
                    data={
                        "candidate_value": candidate_val,
                        "history_mean": mean,
                        "history_stdev": stdev,
                        "z_score": z,
                        "direction": direction,
                        "candidate_date": str(candidate.date_key),
                    },
                )
            )

    return results


# ── Detector: ROAS drop ───────────────────────────────────────────────────────


def detect_roas_drop(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = ROAS_DROP_THRESHOLD,
    critical_threshold: float = ROAS_DROP_CRITICAL,
) -> list[DetectorResult]:
    """Compare ROAS in the most recent N days vs the prior N days.

    Fires when (prior_roas - current_roas) / prior_roas >= threshold.
    Prior period must have positive ROAS to avoid spurious signals on zero spend.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        _, _, r_spend, r_conv, r_cv = _sum_period(recent)
        _, _, p_spend, _, p_cv = _sum_period(prior)

        current_roas = float(_roas(r_cv, r_spend))
        prior_roas = float(_roas(p_cv, p_spend))

        if prior_roas == 0.0:
            continue

        pct_drop = (prior_roas - current_roas) / prior_roas
        if pct_drop < threshold:
            continue

        severity = "critical" if pct_drop >= critical_threshold else "warning"
        score = min(pct_drop * 200.0, 100.0)

        results.append(
            DetectorResult(
                category="roas_drop",
                severity=severity,
                metric="roas",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "current_roas": current_roas,
                    "prior_roas": prior_roas,
                    "pct_drop": pct_drop,
                    "current_spend": float(r_spend),
                    "current_conversion_value": float(r_cv),
                },
            )
        )

    return results


# ── Detector: spend spike ─────────────────────────────────────────────────────


def detect_spend_spike(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = SPEND_SPIKE_THRESHOLD,
    critical_threshold: float = SPEND_SPIKE_CRITICAL,
) -> list[DetectorResult]:
    """Compare spend in the most recent N days vs the prior N days.

    Fires when (current_spend - prior_spend) / prior_spend >= threshold.
    Prior spend must be > 0 to avoid division by zero.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        _, _, r_spend, _, _ = _sum_period(recent)
        _, _, p_spend, _, _ = _sum_period(prior)

        if p_spend == Decimal(0):
            continue

        pct_rise = float((r_spend - p_spend) / p_spend)
        if pct_rise < threshold:
            continue

        severity = "critical" if pct_rise >= critical_threshold else "warning"
        score = min(pct_rise * 100.0, 100.0)

        results.append(
            DetectorResult(
                category="spend_spike",
                severity=severity,
                metric="spend",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "current_spend": float(r_spend),
                    "prior_spend": float(p_spend),
                    "pct_rise": pct_rise,
                },
            )
        )

    return results


# ── Detector: zero conversions while spending ─────────────────────────────────


def detect_zero_conversions(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    critical_spend: Decimal = ZERO_CONV_CRITICAL_SPEND,
) -> list[DetectorResult]:
    """Flag channels with positive spend but zero conversions in the recent period.

    This catches misfiring campaigns (wrong conversion tracking, paused pixels,
    landing-page issues) that would otherwise go unnoticed.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        recent = sorted_pts[-recent_days:]

        _, _, spend, conversions, _ = _sum_period(recent)

        if spend == Decimal(0) or conversions > Decimal(0):
            continue

        severity = "critical" if spend >= critical_spend else "warning"
        score = min(float(spend) / 10.0, 100.0)

        results.append(
            DetectorResult(
                category="zero_conversions",
                severity=severity,
                metric="conversions",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "spend": float(spend),
                    "conversions": float(conversions),
                },
            )
        )

    return results


# ── Detector: CTR drop ────────────────────────────────────────────────────────


def detect_ctr_drop(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = CTR_DROP_THRESHOLD,
    critical_threshold: float = CTR_DROP_CRITICAL,
) -> list[DetectorResult]:
    """Compare CTR in the most recent N days vs the prior N days.

    Fires when (prior_ctr - current_ctr) / prior_ctr >= threshold.
    CTR = total clicks / total impressions for the aggregated period.
    Prior period must have positive impressions.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        r_imp, r_clk, _, _, _ = _sum_period(recent)
        p_imp, p_clk, _, _, _ = _sum_period(prior)

        current_ctr = float(_ctr(r_imp, r_clk))
        prior_ctr = float(_ctr(p_imp, p_clk))

        if prior_ctr == 0.0 or r_imp == Decimal(0):
            continue

        pct_drop = (prior_ctr - current_ctr) / prior_ctr
        if pct_drop < threshold:
            continue

        severity = "critical" if pct_drop >= critical_threshold else "warning"
        score = min(pct_drop * 150.0, 100.0)

        results.append(
            DetectorResult(
                category="ctr_drop",
                severity=severity,
                metric="ctr",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "current_ctr": current_ctr,
                    "prior_ctr": prior_ctr,
                    "pct_drop": pct_drop,
                    "current_impressions": float(r_imp),
                    "current_clicks": float(r_clk),
                },
            )
        )

    return results


# ── Detector: CPC rise ────────────────────────────────────────────────────────


def detect_cpc_rise(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = CPC_RISE_THRESHOLD,
    critical_threshold: float = CPC_RISE_CRITICAL,
) -> list[DetectorResult]:
    """Compare CPC in the most recent N days vs the prior N days.

    Fires when (current_cpc - prior_cpc) / prior_cpc >= threshold.
    Prior period must have positive clicks.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        _, r_clk, r_spend, _, _ = _sum_period(recent)
        _, p_clk, p_spend, _, _ = _sum_period(prior)

        current_cpc = float(_cpc(r_spend, r_clk))
        prior_cpc = float(_cpc(p_spend, p_clk))

        if prior_cpc == 0.0 or r_clk == Decimal(0):
            continue

        pct_rise = (current_cpc - prior_cpc) / prior_cpc
        if pct_rise < threshold:
            continue

        severity = "critical" if pct_rise >= critical_threshold else "warning"
        score = min(pct_rise * 120.0, 100.0)

        results.append(
            DetectorResult(
                category="cpc_rise",
                severity=severity,
                metric="cpc",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "current_cpc": current_cpc,
                    "prior_cpc": prior_cpc,
                    "pct_rise": pct_rise,
                    "current_spend": float(r_spend),
                    "current_clicks": float(r_clk),
                },
            )
        )

    return results


# ── Detector: conversion rate drop ───────────────────────────────────────────


def detect_conversion_rate_drop(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = CVR_DROP_THRESHOLD,
    critical_threshold: float = CVR_DROP_CRITICAL,
) -> list[DetectorResult]:
    """Compare conversion rate (CVR) in the most recent N days vs the prior N days.

    CVR = total conversions / total clicks for the aggregated period.
    Fires when (prior_cvr - current_cvr) / prior_cvr >= threshold.

    Guards:
    - Prior period must have positive clicks (else CVR is undefined).
    - Recent period must have positive clicks (skip channels with no traffic).
    - Divide-by-zero on clicks == 0 is always guarded before division.

    Severity: warning at >= threshold, critical at >= critical_threshold.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        _, r_clk, _, r_conv, _ = _sum_period(recent)
        _, p_clk, _, p_conv, _ = _sum_period(prior)

        # Guard divide-by-zero: skip if either period has zero clicks
        if p_clk == Decimal(0) or r_clk == Decimal(0):
            continue

        current_cvr = float(r_conv / r_clk)
        prior_cvr = float(p_conv / p_clk)

        if prior_cvr == 0.0:
            continue

        pct_drop = (prior_cvr - current_cvr) / prior_cvr
        if pct_drop < threshold:
            continue

        severity = "critical" if pct_drop >= critical_threshold else "warning"
        score = min(pct_drop * 150.0, 100.0)

        results.append(
            DetectorResult(
                category="cvr_drop",
                severity=severity,
                metric="conversion_rate",
                channel=channel_key,
                period_start=recent[0].date_key,
                period_end=recent[-1].date_key,
                score=score,
                data={
                    "current_cvr": current_cvr,
                    "prior_cvr": prior_cvr,
                    "pct_drop": pct_drop,
                    "current_clicks": float(r_clk),
                    "current_conversions": float(r_conv),
                },
            )
        )

    return results


# ── Detector: positive movement ───────────────────────────────────────────────


def detect_positive_movement(
    by_channel: dict[str, list[DailyPoint]],
    as_of_date: date,
    recent_days: int = RECENT_DAYS,
    threshold: float = POSITIVE_MOVEMENT_THRESHOLD,
    min_spend: Decimal = POSITIVE_MOVEMENT_MIN_SPEND,
    min_conversions: Decimal = POSITIVE_MOVEMENT_MIN_CONVERSIONS,
) -> list[DetectorResult]:
    """Detect significant positive improvements in ROAS or conversions.

    Fires an "info" severity insight when:
    - ROAS improved by >= threshold vs prior period AND recent spend >= min_spend, OR
    - Conversions improved by >= threshold vs prior period AND recent conversions >=
      min_conversions.

    Noise floors
    ------------
    - ``min_spend``: minimum spend in the recent period before a ROAS win is raised.
      Prevents tiny absolute numbers (e.g. 1 click, 2 conversions) from producing
      celebratory insights.
    - ``min_conversions``: minimum conversions in the recent period before a
      conversions win is raised.

    Only one signal per channel is raised (ROAS takes precedence over conversions
    if both conditions are met, to avoid two "positive" insights for the same channel
    in the same window).

    Severity is always "info" — positive wins are informational, not actionable alerts.
    """
    results: list[DetectorResult] = []

    for channel_key, pts in by_channel.items():
        sorted_pts = sorted(pts, key=lambda p: p.date_key)
        if len(sorted_pts) < 2:
            continue

        recent = sorted_pts[-recent_days:]
        prior = sorted_pts[-2 * recent_days:-recent_days]

        if not prior:
            continue

        _, _, r_spend, r_conv, r_cv = _sum_period(recent)
        _, _, p_spend, p_conv, p_cv = _sum_period(prior)

        fired = False

        # --- Check ROAS improvement ---
        if r_spend >= min_spend and p_spend > Decimal(0):
            current_roas = float(_roas(r_cv, r_spend))
            prior_roas = float(_roas(p_cv, p_spend))

            if prior_roas > 0.0:
                pct_gain = (current_roas - prior_roas) / prior_roas
                if pct_gain >= threshold:
                    score = min(pct_gain * 100.0, 100.0)
                    results.append(
                        DetectorResult(
                            category="positive_movement",
                            severity="info",
                            metric="roas",
                            channel=channel_key,
                            period_start=recent[0].date_key,
                            period_end=recent[-1].date_key,
                            score=score,
                            data={
                                "current_roas": current_roas,
                                "prior_roas": prior_roas,
                                "pct_gain": pct_gain,
                                "current_spend": float(r_spend),
                                "trigger": "roas",
                            },
                        )
                    )
                    fired = True

        # --- Check conversions improvement (only if ROAS did not already fire) ---
        if not fired and r_conv >= min_conversions and p_conv > Decimal(0):
            pct_gain = float((r_conv - p_conv) / p_conv)
            if pct_gain >= threshold:
                score = min(pct_gain * 100.0, 100.0)
                results.append(
                    DetectorResult(
                        category="positive_movement",
                        severity="info",
                        metric="conversions",
                        channel=channel_key,
                        period_start=recent[0].date_key,
                        period_end=recent[-1].date_key,
                        score=score,
                        data={
                            "current_conversions": float(r_conv),
                            "prior_conversions": float(p_conv),
                            "pct_gain": pct_gain,
                            "trigger": "conversions",
                        },
                    )
                )

    return results


# ── Deduplication ─────────────────────────────────────────────────────────────


def _insight_exists(
    db: Session,
    tenant_id: uuid.UUID,
    category: str,
    metric: str,
    channel: str | None,
    period_start: date,
    period_end: date,
    entity_id: str | None,
) -> bool:
    """Return True if an open (new/seen) identical insight already exists.

    Identical means same (tenant, category, metric, channel, period_start,
    period_end, entity_id).  Dismissed insights do not count — if the user
    dismissed it, a re-occurrence creates a fresh insight.
    """
    stmt = select(Insight.id).where(
        Insight.tenant_id == tenant_id,
        Insight.category == category,
        Insight.metric == metric,
        Insight.period_start == period_start,
        Insight.period_end == period_end,
        Insight.status.in_(["new", "seen"]),
    )
    if channel is not None:
        stmt = stmt.where(Insight.channel == channel)
    else:
        stmt = stmt.where(Insight.channel.is_(None))
    if entity_id is not None:
        stmt = stmt.where(Insight.entity_id == entity_id)
    else:
        stmt = stmt.where(Insight.entity_id.is_(None))

    return db.scalar(stmt) is not None


# ── Narrator integration ──────────────────────────────────────────────────────


def _narrate(result: DetectorResult) -> tuple[str, str]:
    """Produce a (title, body) Turkish narrative for a DetectorResult.

    Imports narrator lazily to avoid circular dependencies.
    Uses TemplateNarrator (no network) — ClaudeNarrator is an opt-in upgrade
    that callers can wire in via the narrator parameter of generate_insights.
    """
    from ayaz.services.narrator import TemplateNarrator  # lazy import

    narrator = TemplateNarrator()
    return narrator.narrate(result)


# ── Public API ────────────────────────────────────────────────────────────────


def generate_insights(
    db: Session,
    tenant_id: uuid.UUID,
    as_of_date: date,
    lookback_days: int = 30,
    narrator=None,
) -> dict[str, int]:
    """Run all detectors and persist new Insight rows for the tenant.

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    tenant_id:
        Tenant UUID — every query and every inserted row is scoped to this.
    as_of_date:
        The latest date to analyse.  Usually today or the latest date that has
        synced data.  The lookback window ends here.
    lookback_days:
        How many calendar days to load from fact_daily_metrics, counting back
        from ``as_of_date`` (inclusive).
    narrator:
        Optional narrator instance.  Must implement ``narrate(result) -> (title, body)``.
        When None, :class:`~ayaz.services.narrator.TemplateNarrator` is used.

    Returns
    -------
    dict with counts: ``new_info``, ``new_warning``, ``new_critical``, ``skipped``.

    Notes
    -----
    The function loads data once and fans it out to all detectors.  Each
    detector is independent and produces its own list of DetectorResult objects.
    All results are then deduplicated against existing DB rows and narrated
    before being written in a single flush.
    """
    from datetime import timedelta

    period_start = date.fromordinal(as_of_date.toordinal() - lookback_days + 1)

    logger.info(
        "[insights] Generating for tenant=%s as_of=%s lookback=%d days",
        tenant_id,
        as_of_date,
        lookback_days,
    )

    # Load all data once
    all_points = _load_daily_points(db, tenant_id, period_start, as_of_date)

    if not all_points:
        logger.info("[insights] No data in window — skipping.")
        return {"new_info": 0, "new_warning": 0, "new_critical": 0, "skipped": 0}

    by_channel = _group_by_channel(all_points)

    # Resolve narrator
    if narrator is None:
        from ayaz.services.narrator import TemplateNarrator
        narrator = TemplateNarrator()

    # Run all detectors
    all_results: list[DetectorResult] = []
    all_results.extend(detect_anomaly(by_channel, as_of_date))
    all_results.extend(detect_roas_drop(by_channel, as_of_date))
    all_results.extend(detect_spend_spike(by_channel, as_of_date))
    all_results.extend(detect_zero_conversions(by_channel, as_of_date))
    all_results.extend(detect_ctr_drop(by_channel, as_of_date))
    all_results.extend(detect_cpc_rise(by_channel, as_of_date))
    all_results.extend(detect_conversion_rate_drop(by_channel, as_of_date))
    all_results.extend(detect_positive_movement(by_channel, as_of_date))

    # Data-quality detectors (category: data_quality)
    # Lazy import avoids circular: data_quality imports DetectorResult from this module.
    try:
        from ayaz.services.data_quality import run_data_quality_detectors
        all_results.extend(run_data_quality_detectors(db, tenant_id, as_of_date))
    except Exception:
        logger.warning("[insights] data_quality detectors failed", exc_info=True)

    counts = {"new_info": 0, "new_warning": 0, "new_critical": 0, "skipped": 0}

    for result in all_results:
        # Deduplication check
        if _insight_exists(
            db,
            tenant_id,
            category=result.category,
            metric=result.metric,
            channel=result.channel,
            period_start=result.period_start,
            period_end=result.period_end,
            entity_id=result.entity_id,
        ):
            counts["skipped"] += 1
            continue

        # Narrate in Turkish
        try:
            title, body = narrator.narrate(result)
        except Exception:
            logger.warning(
                "[insights] Narrator failed for %s — using fallback",
                result.category,
                exc_info=True,
            )
            from ayaz.services.narrator import TemplateNarrator
            title, body = TemplateNarrator().narrate(result)

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
    logger.info("[insights] Done: %s", counts)
    return counts
