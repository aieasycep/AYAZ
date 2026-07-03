"""Goal Tracking & Forecasting service.

Public API
----------
    create_goal(db, tenant_id, data)   -> Goal
    list_goals(db, tenant_id, ...)     -> list[Goal]
    get_goal(db, tenant_id, goal_id)   -> Goal | None
    update_goal(db, tenant_id, goal_id, data) -> Goal | None
    delete_goal(db, tenant_id, goal_id) -> bool
    compute_progress(db, goal, as_of_date) -> ProgressPayload

Forecast assumptions (documented per metric type)
--------------------------------------------------

Additive metrics (spend, conversions, conversion_value)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
These accumulate linearly over time.  The forecast projects the current
run-rate forward to the end of the period:

    daily_rate      = current_value / days_elapsed    (0 if days_elapsed == 0)
    forecast_value  = daily_rate * days_total

This is a straight-line run-rate projection.  It ignores weekday patterns and
campaign-pause windows, which is appropriate for a first-order estimate.
When days_elapsed == 0 (as_of_date == period_start) the forecast is 0.

Ratio metrics (roas)
~~~~~~~~~~~~~~~~~~~~
ROAS is conversion_value / spend.  A run-rate projection of ROAS itself is
misleading because the numerator and denominator both scale.  Instead we use
the period-to-date *average* ROAS as the forecast, assuming the current ratio
holds for the rest of the period:

    forecast_value  = current_value      (period-average ROAS to date)

When there is no spend yet in the period, current_value (ROAS) == 0 and the
forecast is also 0.

Status thresholds (applied against forecast_value vs target_value)
------------------------------------------------------------------
    on_track   forecast >= 95 % of target
    at_risk    80 % <= forecast < 95 % of target
    off_track  forecast < 80 % of target

When target_value == 0, status is "on_track" (trivially met).

Expected-pace value (linear target pace)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This answers: "where should we be by now if progress were perfectly linear?"

    expected_pace_value = target_value * (days_elapsed / days_total)

For ratio metrics this is the same formula because target_value is the desired
ROAS, not a total to accumulate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.goals import Goal
from ayaz.services.metrics import roas as _roas

# ── Status thresholds ─────────────────────────────────────────────────────────

ON_TRACK_THRESHOLD: float = 0.95
"""Forecast must reach >= 95 % of target to be on_track."""

AT_RISK_THRESHOLD: float = 0.80
"""Forecast between 80-95 % of target triggers at_risk."""

# Below AT_RISK_THRESHOLD -> off_track

# ── Valid metric names ────────────────────────────────────────────────────────

ADDITIVE_METRICS = frozenset({"spend", "conversions", "conversion_value"})
RATIO_METRICS = frozenset({"roas"})
ALL_METRICS = ADDITIVE_METRICS | RATIO_METRICS

VALID_PERIODS = frozenset({"month"})


# ── Data structure returned by compute_progress ───────────────────────────────


@dataclass
class ProgressPayload:
    """Pacing and forecast data for a single goal at a specific date.

    Fields
    ------
    goal_id:
        UUID of the goal.
    current_value:
        Aggregated metric value from period_start to as_of_date (inclusive),
        scoped to the goal's tenant and optional channel_filter.
    target_value:
        The numeric target set on the goal.
    pct_to_target:
        current_value / target_value as a fraction (0–1+).  Returns 0.0 when
        target_value is 0.
    days_elapsed:
        Number of days from period_start to as_of_date (inclusive).  Clamped
        to [0, days_total].
    days_total:
        Total calendar days in the period (period_start to period_end inclusive).
    expected_pace_value:
        The value the goal *should* be at if it were progressing linearly:
        ``target_value * (days_elapsed / days_total)``.
    forecast_value:
        Projected end-of-period value.  For additive metrics: run-rate
        (current / elapsed * total).  For ratio metrics: current period-average
        ROAS held constant.
    status:
        "on_track" | "at_risk" | "off_track".
    recommendation:
        Turkish-language guidance string.
    """

    goal_id: uuid.UUID
    current_value: float
    target_value: float
    pct_to_target: float
    days_elapsed: int
    days_total: int
    expected_pace_value: float
    forecast_value: float
    status: str
    recommendation: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB scalar (Decimal, int, float, None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def _fetch_metric_value(
    db: Session,
    tenant_id: uuid.UUID,
    metric: str,
    period_start: date,
    as_of_date: date,
    channel_filter: str | None,
) -> Decimal:
    """Query fact_daily_metrics to aggregate the metric value for the period.

    Parameters
    ----------
    db:
        Active SQLAlchemy Session.
    tenant_id:
        Always applied as a WHERE filter (tenant isolation).
    metric:
        One of: spend, roas, conversions, conversion_value.
    period_start:
        Start of the tracking period (inclusive).
    as_of_date:
        End of the aggregation window (inclusive).  Typically today or a date
        in the past.
    channel_filter:
        When not None, an additional WHERE clause ``dim_channel.key = channel_filter``
        is applied.  When None, all channels are summed.

    Returns
    -------
    Decimal
        The aggregated value.  For ROAS: conversion_value_total / spend_total
        (returns 0 if spend is 0).
    """
    # Build the base query columns we always need
    spend_expr = func.sum(
        func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
    )
    conv_value_expr = func.sum(FactDailyMetrics.conversion_value_raw)
    conversions_expr = func.sum(FactDailyMetrics.conversions)

    if channel_filter is not None:
        # Join DimChannel to filter by key
        stmt = (
            select(
                spend_expr.label("spend"),
                conv_value_expr.label("conversion_value"),
                conversions_expr.label("conversions"),
            )
            .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
            .where(
                FactDailyMetrics.tenant_id == tenant_id,
                FactDailyMetrics.date_key >= period_start,
                FactDailyMetrics.date_key <= as_of_date,
                DimChannel.key == channel_filter,
            )
        )
    else:
        stmt = (
            select(
                spend_expr.label("spend"),
                conv_value_expr.label("conversion_value"),
                conversions_expr.label("conversions"),
            )
            .where(
                FactDailyMetrics.tenant_id == tenant_id,
                FactDailyMetrics.date_key >= period_start,
                FactDailyMetrics.date_key <= as_of_date,
            )
        )

    row = db.execute(stmt).mappings().one()

    spend = _d(row["spend"])
    conv_value = _d(row["conversion_value"])
    conversions = _d(row["conversions"])

    if metric == "spend":
        return spend
    elif metric == "roas":
        return _roas(conv_value, spend)
    elif metric == "conversions":
        return conversions
    elif metric == "conversion_value":
        return conv_value
    else:
        return Decimal(0)


def _tr_num(value: float, decimals: int = 2) -> str:
    """Format a number with Turkish separators (1.234,56)."""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _tr_pct(value: float) -> str:
    """Format a 0-100 percent value with one decimal and Turkish comma."""
    return f"{value:.1f}".replace(".", ",")


def _build_recommendation(
    metric: str,
    status: str,
    pct_to_target: float,
    target_value: float,
    current_value: float,
    days_elapsed: int,
    days_total: int,
    days_remaining: int,
    forecast_value: float,
) -> str:
    """Generate a Turkish recommendation string.

    The recommendation is template-based (no network/LLM required).
    Tone: direct, data-driven, actionable — always in the formal "siz" form,
    with Turkish number formatting (comma decimals). Spend goals are budgets:
    overshooting is a problem, not a success.

    Parameters passed in are already computed floats to keep this function pure.
    """
    pct = pct_to_target * 100
    pct_gap_display = _tr_pct(max(0.0, 100.0 - pct))
    over_display = _tr_pct(max(0.0, pct - 100.0))

    # Spend goals are budget targets: exceeding the target is an overrun.
    # The strong warning uses the same tolerance band as _classify_status
    # (SPEND_AT_RISK_OVERRUN) so the badge and the message never contradict:
    # a ≤5 % realized overrun keeps the goal on_track, and alarming copy next
    # to a green "Yolunda" badge would read as a bug.
    if metric == "spend" and pct_to_target > SPEND_AT_RISK_OVERRUN:
        if days_remaining <= 0:
            return (
                f"Dönem sona erdi. Bütçe %{over_display} aşıldı "
                f"(hedef: {_tr_num(target_value, 0)}, gerçekleşen: {_tr_num(current_value, 0)})."
            )
        return (
            f"Bütçe hedefi aşılıyor: hedef {_tr_num(target_value, 0)} iken "
            f"{_tr_num(current_value, 0)} harcandı (%{over_display} üzerinde). "
            f"Günlük harcama hızını düşürün veya bütçe hedefini güncelleyin."
        )

    # Mid-period pacing overrun: the realized total is still under target but
    # the forecast says the budget will blow past it. Without this branch the
    # goal lands in the generic "you're behind, spend more" message below —
    # the exact opposite of the right advice for a budget at overrun risk.
    if (
        metric == "spend"
        and target_value > 0.0
        and forecast_value / target_value > SPEND_AT_RISK_OVERRUN
    ):
        forecast_over = _tr_pct(max(0.0, forecast_value / target_value * 100.0 - 100.0))
        return (
            f"Bu hızla dönem sonunda bütçe %{forecast_over} aşılacak "
            f"(tahmin: {_tr_num(forecast_value, 0)}, hedef: {_tr_num(target_value, 0)}). "
            f"Günlük harcama hızını düşürün veya bütçe hedefini güncelleyin."
        )

    if status == "on_track":
        if metric == "spend":
            return f"Bütçe hedefiyle uyumlu ilerliyor (kullanılan: %{_tr_pct(pct)})."
        if pct >= 100.0:
            return f"Hedef aşıldı! Tamamlanan: %{_tr_pct(pct)}."
        return f"Hedef yolunda gidiyor! Tamamlanan: %{_tr_pct(pct)}."

    if days_remaining <= 0:
        # Period already ended
        return (
            f"Dönem sona erdi. Hedefe ulaşılamadı — gerçekleşen, hedefin "
            f"%{pct_gap_display} altında kaldı."
        )

    if metric == "roas":
        return (
            f"ROAS hedefinin %{pct_gap_display} gerisindesiniz. "
            f"Kalan {days_remaining} günde hedefe ulaşmak için dönüşüm değerini "
            f"artırmanız veya harcamayı optimize etmeniz gerekiyor "
            f"(mevcut ROAS: {_tr_num(current_value)}, hedef: {_tr_num(target_value)})."
        )

    elif metric == "spend":
        daily_needed = (target_value - current_value) / days_remaining if days_remaining > 0 else 0
        return (
            f"Bütçe kullanım hedefinin %{pct_gap_display} gerisindesiniz. "
            f"Kalan {days_remaining} günde günlük ortalama "
            f"{_tr_num(daily_needed, 0)} birim harcama gerekiyor "
            f"(hedef: {_tr_num(target_value, 0)}, şu ana kadar: {_tr_num(current_value, 0)})."
        )

    elif metric == "conversions":
        daily_needed = (target_value - current_value) / days_remaining if days_remaining > 0 else 0
        return (
            f"Dönüşüm hedefinin %{pct_gap_display} gerisindesiniz. "
            f"Kalan {days_remaining} günde günlük ortalama "
            f"{_tr_num(daily_needed, 1)} dönüşüm daha gerekiyor "
            f"(hedef: {_tr_num(target_value, 0)}, şu ana kadar: {_tr_num(current_value, 0)})."
        )

    elif metric == "conversion_value":
        daily_needed = (target_value - current_value) / days_remaining if days_remaining > 0 else 0
        return (
            f"Dönüşüm değeri hedefinin %{pct_gap_display} gerisindesiniz. "
            f"Kalan {days_remaining} günde günlük ortalama "
            f"{_tr_num(daily_needed, 0)} birim değer daha gerekiyor "
            f"(hedef: {_tr_num(target_value, 0)}, şu ana kadar: {_tr_num(current_value, 0)})."
        )

    return (
        f"Hedefin %{pct_gap_display} gerisindesiniz; kalan {days_remaining} "
        f"günde ilerlemeyi hızlandırmanız gerekiyor."
    )


# Spend (budget) goals: forecast above these multiples of target = overrun.
SPEND_AT_RISK_OVERRUN = 1.05
SPEND_OFF_TRACK_OVERRUN = 1.20


def _classify_status(forecast_value: float, target_value: float, metric: str = "") -> str:
    """Classify goal status from forecast vs target.

    Thresholds (see module docstring):
        on_track   forecast >= 95 % of target
        at_risk    80 % <= forecast < 95 % of target
        off_track  forecast < 80 % of target

    Spend goals are budgets — a forecast far above target is an overrun, so the
    band is two-sided: >105 % of target → at_risk, >120 % → off_track.

    When target_value == 0, returns "on_track" (target trivially met).
    """
    if target_value == 0.0:
        return "on_track"

    ratio = forecast_value / target_value

    if metric == "spend":
        if ratio > SPEND_OFF_TRACK_OVERRUN:
            return "off_track"
        if ratio > SPEND_AT_RISK_OVERRUN:
            return "at_risk"

    if ratio >= ON_TRACK_THRESHOLD:
        return "on_track"
    elif ratio >= AT_RISK_THRESHOLD:
        return "at_risk"
    else:
        return "off_track"


# ── Public: compute_progress ─────────────────────────────────────────────────


def compute_progress(
    db: Session,
    goal: Goal,
    as_of_date: date,
) -> ProgressPayload:
    """Compute pacing, forecast, status, and Turkish recommendation for a goal.

    Parameters
    ----------
    db:
        Active SQLAlchemy Session.
    goal:
        The ``Goal`` ORM row to evaluate.
    as_of_date:
        The date to treat as "today" for the forecast.  May be any date
        within or after the goal period.

    Returns
    -------
    ProgressPayload
        All progress fields as a dataclass.  See class docstring for semantics.

    Notes
    -----
    * Tenant isolation: every DB query inside this function is filtered by
      ``goal.tenant_id``.  No data from other tenants is read.
    * ``as_of_date`` is clamped to ``[period_start, period_end]`` for the
      days_elapsed computation only.  The metric query always uses
      ``min(as_of_date, period_end)`` so data outside the period is excluded.
    """
    period_start = date.fromisoformat(goal.period_start)
    period_end = date.fromisoformat(goal.period_end)
    target_value = float(goal.target_value)

    # Days arithmetic
    days_total = (period_end - period_start).days + 1  # inclusive

    # Clamp query end to period_end (don't pull data beyond the period)
    query_end = min(as_of_date, period_end)

    if as_of_date < period_start:
        days_elapsed = 0
    elif as_of_date >= period_end:
        days_elapsed = days_total
    else:
        days_elapsed = (as_of_date - period_start).days + 1

    days_remaining = days_total - days_elapsed

    # Retrieve the metric value from the fact table
    current_dec = _fetch_metric_value(
        db=db,
        tenant_id=goal.tenant_id,
        metric=goal.metric,
        period_start=period_start,
        as_of_date=query_end,
        channel_filter=goal.channel_filter,
    )
    current_value = float(current_dec)

    # Expected pace (linear, same formula for additive and ratio metrics)
    if days_total > 0:
        expected_pace_value = target_value * (days_elapsed / days_total)
    else:
        expected_pace_value = 0.0

    # Forecast value
    if goal.metric in RATIO_METRICS:
        # ROAS: hold the current period-average ROAS constant
        forecast_value = current_value
    else:
        # Additive metrics: project daily run-rate to period end
        if days_elapsed > 0:
            daily_rate = current_value / days_elapsed
            forecast_value = daily_rate * days_total
        else:
            forecast_value = 0.0

    # Status (metric-aware: spend goals treat overrun as a problem)
    status = _classify_status(forecast_value, target_value, metric=goal.metric)

    # pct_to_target
    if target_value == 0.0:
        pct_to_target = 1.0
    else:
        pct_to_target = current_value / target_value

    # Turkish recommendation
    recommendation = _build_recommendation(
        metric=goal.metric,
        status=status,
        pct_to_target=pct_to_target,
        target_value=target_value,
        current_value=current_value,
        days_elapsed=days_elapsed,
        days_total=days_total,
        days_remaining=days_remaining,
        forecast_value=forecast_value,
    )

    return ProgressPayload(
        goal_id=goal.id,
        current_value=round(current_value, 6),
        target_value=target_value,
        pct_to_target=round(pct_to_target, 6),
        days_elapsed=days_elapsed,
        days_total=days_total,
        expected_pace_value=round(expected_pace_value, 6),
        forecast_value=round(forecast_value, 6),
        status=status,
        recommendation=recommendation,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_goal(
    db: Session,
    tenant_id: uuid.UUID,
    name: str,
    metric: str,
    target_value: float,
    period_start: str,
    period_end: str,
    period: str = "month",
    channel_filter: str | None = None,
    is_active: bool = True,
) -> Goal:
    """Persist a new Goal row for the tenant.

    Raises ``ValueError`` for invalid metric or period values.
    """
    if metric not in ALL_METRICS:
        raise ValueError(
            f"Invalid metric {metric!r}. Choose from: {sorted(ALL_METRICS)}"
        )
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period {period!r}. Choose from: {sorted(VALID_PERIODS)}"
        )
    # Validate date strings parse correctly
    date.fromisoformat(period_start)
    date.fromisoformat(period_end)

    goal = Goal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        metric=metric,
        target_value=target_value,
        period=period,
        period_start=period_start,
        period_end=period_end,
        channel_filter=channel_filter,
        is_active=is_active,
    )
    db.add(goal)
    db.flush()
    return goal


def list_goals(
    db: Session,
    tenant_id: uuid.UUID,
    active_only: bool = True,
) -> list[Goal]:
    """Return goals for the tenant, optionally filtering to active-only.

    Results are ordered by ``created_at`` descending (newest first).
    """
    stmt = select(Goal).where(Goal.tenant_id == tenant_id)
    if active_only:
        stmt = stmt.where(Goal.is_active.is_(True))
    stmt = stmt.order_by(Goal.created_at.desc())
    return list(db.scalars(stmt).all())


def get_goal(
    db: Session,
    tenant_id: uuid.UUID,
    goal_id: uuid.UUID,
) -> Goal | None:
    """Return a single Goal scoped to the tenant, or None if not found."""
    return db.scalar(
        select(Goal).where(
            Goal.id == goal_id,
            Goal.tenant_id == tenant_id,
        )
    )


def update_goal(
    db: Session,
    tenant_id: uuid.UUID,
    goal_id: uuid.UUID,
    **kwargs: Any,
) -> Goal | None:
    """Apply field updates to an existing goal.

    Only the keys present in ``kwargs`` are updated.  Unknown keys are silently
    ignored.  Raises ``ValueError`` if ``metric`` or ``period`` is changed to
    an invalid value.

    Returns the updated Goal, or None if not found.
    """
    goal = get_goal(db, tenant_id, goal_id)
    if goal is None:
        return None

    allowed_fields = {
        "name", "metric", "target_value", "period",
        "period_start", "period_end", "channel_filter", "is_active",
    }
    for field, value in kwargs.items():
        if field not in allowed_fields:
            continue
        if field == "metric" and value not in ALL_METRICS:
            raise ValueError(
                f"Invalid metric {value!r}. Choose from: {sorted(ALL_METRICS)}"
            )
        if field == "period" and value not in VALID_PERIODS:
            raise ValueError(
                f"Invalid period {value!r}. Choose from: {sorted(VALID_PERIODS)}"
            )
        if field in ("period_start", "period_end"):
            date.fromisoformat(value)  # validate format
        setattr(goal, field, value)

    db.flush()
    return goal


def delete_goal(
    db: Session,
    tenant_id: uuid.UUID,
    goal_id: uuid.UUID,
) -> bool:
    """Hard-delete a goal.

    Returns True if the goal existed and was deleted, False if not found.
    Tenant isolation is enforced by the WHERE clause.
    """
    goal = get_goal(db, tenant_id, goal_id)
    if goal is None:
        return False
    db.delete(goal)
    db.flush()
    return True
