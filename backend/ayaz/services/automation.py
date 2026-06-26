"""Automation & Rules engine service — M9.

Public API
----------
    evaluate_rule(db, rule, as_of_date) -> RuleEvaluation
    run_rule(db, rule, as_of_date)
    run_all_active_rules(db, tenant_id=None, as_of_date=None)

Design principles
-----------------
* **evaluate_rule** is pure-ish: it reads DB data but writes nothing.  It
  aggregates the relevant metric over ``window_days`` vs the prior window of
  equal length, applies the comparator/threshold, and returns a ``RuleEvaluation``
  dataclass that describes what was found.  For the "anomaly" comparator it
  delegates to the existing ``detect_anomaly`` detector from
  ``ayaz.services.insights``.

* **run_rule** calls evaluate_rule, then (if triggered) performs the configured
  action:
    - "alert"          → creates an Insight row with Turkish text.
    - "notify_email"   → logs via EmailNotifier stub (no real SMTP).
    - "notify_slack"   → logs via SlackNotifier stub (no real webhook).
    - "pause_suggest"  → creates an actionable Insight recommending pause;
                         NO real execution — M6 phase 2 owns actual pause.
  It always writes an AutomationRun audit row.  Idempotency is enforced: if
  ``rule.last_triggered_at`` already equals ``str(as_of_date)``, no duplicate
  action is taken.

* **run_all_active_rules** iterates all active rules (optionally scoped to a
  single tenant) and calls run_rule for each.

Metric aggregation strategy
---------------------------
The service reuses the shared metric layer (``ayaz.services.metrics``) and
the existing fact-loading helpers from ``ayaz.services.insights``.

For "pct_drop" / "pct_rise" comparators:
  current_window  = [as_of_date - window_days + 1 … as_of_date]
  previous_window = [as_of_date - 2*window_days + 1 … as_of_date - window_days]
  pct_change = (current - prior) / prior   (signed)

For "below" / "above" comparators:
  Only the current_window is needed; the aggregated metric is compared against
  ``rule.threshold`` directly.

For "anomaly":
  Loads a 5×window_days lookback window and feeds it into detect_anomaly().

All ``threshold`` values for pct_* comparators are stored as percentages
(0–100) in the rule, matching the UI convention, and divided by 100 before
comparison with the fractional change.

Tenant isolation
----------------
Every query explicitly filters by ``tenant_id``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics
from ayaz.models.automation import AutomationRule, AutomationRun
from ayaz.models.insights import Insight
from ayaz.services.insights import (
    DailyPoint,
    _group_by_channel,
    _sum_period,
    detect_anomaly,
)
from ayaz.services.metrics import (
    ctr as _ctr,
    cpc as _cpc,
    roas as _roas,
    cpa as _cpa,
)

logger = logging.getLogger(__name__)

# ── Allowed values (validated at API boundary, documented here for reference) ──

VALID_SCOPES = frozenset({"account", "channel", "campaign"})
VALID_METRICS = frozenset({"spend", "roas", "ctr", "cpc", "cpa", "conversions"})
VALID_COMPARATORS = frozenset({"pct_drop", "pct_rise", "below", "above", "anomaly"})
VALID_ACTIONS = frozenset({"alert", "notify_email", "notify_slack", "pause_suggest"})


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class MatchedEntity:
    """A single channel or campaign that satisfied the rule condition."""

    entity_type: str           # "channel" | "campaign"
    entity_key: str            # channel key or campaign UUID string
    entity_name: str | None    # human-readable name (nullable for anonymised runs)
    current_value: float
    prior_value: float | None  # None for "below"/"above" comparators
    pct_change: float | None   # None for "below"/"above" comparators


@dataclass
class RuleEvaluation:
    """Result of evaluating one AutomationRule.

    ``triggered`` is True when at least one entity satisfied the condition.
    ``matched_entities`` lists the entities that fired.
    ``detail`` is a machine-readable summary (stored in AutomationRun.detail).
    """

    rule_id: uuid.UUID
    as_of_date: date
    triggered: bool
    matched_entities: list[MatchedEntity] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


# ── Internal data-loading helpers ─────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB value (Decimal/int/float/None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def _load_points_for_scope(
    db: Session,
    tenant_id: uuid.UUID,
    scope: str,
    scope_filter: str | None,
    period_start: date,
    period_end: date,
) -> list[DailyPoint]:
    """Load FactDailyMetrics as DailyPoint objects for the given scope.

    Groups by (date_key, channel_key) for "account"/"channel" scope.
    For "campaign" scope groups by (date_key) with channel_key set to the
    campaign id string (mirrors ads.py pattern).
    """
    if scope == "campaign" and scope_filter:
        try:
            campaign_uuid = uuid.UUID(scope_filter)
        except ValueError:
            logger.warning(
                "[automation] Invalid campaign UUID scope_filter=%r", scope_filter
            )
            return []

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
                FactDailyMetrics.campaign_id == campaign_uuid,
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
                # Use scope_filter (campaign id) as channel_key so detector buckets work
                date_key=row["date_key"],
                channel_key=scope_filter,
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

    # "account" or "channel" scope — group by (date_key, channel_key)
    stmt = (
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
    )
    if scope == "channel" and scope_filter:
        stmt = stmt.where(DimChannel.key == scope_filter)

    stmt = stmt.group_by(
        FactDailyMetrics.date_key, DimChannel.key
    ).order_by(DimChannel.key, FactDailyMetrics.date_key)

    rows = db.execute(stmt).mappings().all()

    points = []
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


def _extract_metric_value(
    points: list[DailyPoint],
    metric: str,
) -> float:
    """Aggregate ``points`` into a single metric scalar.

    For "spend" / "conversions": simple sum.
    For "roas" / "ctr" / "cpc" / "cpa": computed from the period totals.
    """
    if not points:
        return 0.0

    imp, clk, spd, cvr, cvv = _sum_period(points)

    if metric == "spend":
        return float(spd)
    if metric == "conversions":
        return float(cvr)
    if metric == "roas":
        return float(_roas(cvv, spd))
    if metric == "ctr":
        return float(_ctr(imp, clk))
    if metric == "cpc":
        return float(_cpc(spd, clk))
    if metric == "cpa":
        return float(_cpa(spd, cvr))
    return 0.0


# ── evaluate_rule ─────────────────────────────────────────────────────────────


def evaluate_rule(
    db: Session,
    rule: AutomationRule,
    as_of_date: date,
) -> RuleEvaluation:
    """Evaluate a single AutomationRule and return a RuleEvaluation.

    This function is read-only: it queries fact data and computes the
    condition, but does NOT write anything to the database.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries).
    rule:
        The AutomationRule to evaluate.
    as_of_date:
        The reference date.  The "current" window ends here.

    Returns
    -------
    RuleEvaluation describing whether the condition fired and for which
    channels/campaigns.
    """
    window_days = max(rule.window_days, 1)
    comparator = rule.comparator
    metric = rule.metric

    # Current window
    current_end = as_of_date
    current_start = current_end - timedelta(days=window_days - 1)

    # Prior window (same length, directly preceding the current window)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days - 1)

    # For anomaly detection we load a longer lookback (5x window or min 14 days)
    if comparator == "anomaly":
        anomaly_lookback = max(window_days * 5, 14)
        anomaly_start = current_end - timedelta(days=anomaly_lookback - 1)
        all_points = _load_points_for_scope(
            db, rule.tenant_id, rule.scope, rule.scope_filter,
            anomaly_start, current_end,
        )
        by_channel = _group_by_channel(all_points)
        anomaly_results = detect_anomaly(
            by_channel,
            as_of_date,
        )
        # Filter by the rule's metric (detect_anomaly checks all metrics)
        matching = [r for r in anomaly_results if r.metric == metric]

        triggered = len(matching) > 0
        matched_entities = [
            MatchedEntity(
                entity_type="channel",
                entity_key=r.channel or "unknown",
                entity_name=r.channel,
                current_value=r.data.get("candidate_value", 0.0),
                prior_value=r.data.get("history_mean"),
                pct_change=None,
            )
            for r in matching
        ]
        detail: dict[str, Any] = {
            "comparator": "anomaly",
            "metric": metric,
            "as_of_date": str(as_of_date),
            "window_days": window_days,
            "anomaly_results": [
                {
                    "channel": r.channel,
                    "z_score": r.data.get("z_score"),
                    "candidate_value": r.data.get("candidate_value"),
                    "history_mean": r.data.get("history_mean"),
                    "severity": r.severity,
                }
                for r in matching
            ],
        }
        return RuleEvaluation(
            rule_id=rule.id,
            as_of_date=as_of_date,
            triggered=triggered,
            matched_entities=matched_entities,
            detail=detail,
        )

    # Non-anomaly comparators: load current and (for pct_* ) prior windows
    current_points = _load_points_for_scope(
        db, rule.tenant_id, rule.scope, rule.scope_filter,
        current_start, current_end,
    )

    # Group by channel/campaign key
    by_channel_current = _group_by_channel(current_points)

    matched_entities = []

    # For pct_* comparators we need the prior window per channel
    if comparator in ("pct_drop", "pct_rise"):
        prior_points = _load_points_for_scope(
            db, rule.tenant_id, rule.scope, rule.scope_filter,
            prior_start, prior_end,
        )
        by_channel_prior = _group_by_channel(prior_points)

        # Evaluate each channel that has current data
        for ch_key, cur_pts in by_channel_current.items():
            prior_pts = by_channel_prior.get(ch_key, [])
            current_val = _extract_metric_value(cur_pts, metric)
            prior_val = _extract_metric_value(prior_pts, metric)

            if prior_val == 0.0:
                # Cannot compute percentage change with zero prior value
                continue

            pct_change = (current_val - prior_val) / prior_val  # signed

            # Threshold stored as percentage (e.g. 20 means 20%)
            threshold_frac = (rule.threshold or 0.0) / 100.0

            fires = False
            if comparator == "pct_drop":
                # condition: metric fell by >= threshold %
                fires = pct_change <= -threshold_frac
            elif comparator == "pct_rise":
                # condition: metric rose by >= threshold %
                fires = pct_change >= threshold_frac

            if fires:
                matched_entities.append(
                    MatchedEntity(
                        entity_type="channel" if rule.scope in ("account", "channel") else "campaign",
                        entity_key=ch_key,
                        entity_name=ch_key,
                        current_value=current_val,
                        prior_value=prior_val,
                        pct_change=pct_change,
                    )
                )

    else:
        # "below" / "above" comparators — use current window only
        threshold_val = rule.threshold or 0.0

        for ch_key, cur_pts in by_channel_current.items():
            current_val = _extract_metric_value(cur_pts, metric)

            fires = False
            if comparator == "below":
                fires = current_val < threshold_val
            elif comparator == "above":
                fires = current_val > threshold_val

            if fires:
                matched_entities.append(
                    MatchedEntity(
                        entity_type="channel" if rule.scope in ("account", "channel") else "campaign",
                        entity_key=ch_key,
                        entity_name=ch_key,
                        current_value=current_val,
                        prior_value=None,
                        pct_change=None,
                    )
                )

    triggered = len(matched_entities) > 0

    detail = {
        "comparator": comparator,
        "metric": metric,
        "threshold": rule.threshold,
        "window_days": window_days,
        "as_of_date": str(as_of_date),
        "current_window": {"start": str(current_start), "end": str(current_end)},
        "matched_entities": [
            {
                "entity_type": e.entity_type,
                "entity_key": e.entity_key,
                "current_value": e.current_value,
                "prior_value": e.prior_value,
                "pct_change": e.pct_change,
            }
            for e in matched_entities
        ],
    }
    if comparator in ("pct_drop", "pct_rise"):
        detail["prior_window"] = {"start": str(prior_start), "end": str(prior_end)}

    return RuleEvaluation(
        rule_id=rule.id,
        as_of_date=as_of_date,
        triggered=triggered,
        matched_entities=matched_entities,
        detail=detail,
    )


# ── Action helpers ────────────────────────────────────────────────────────────


def _metric_label_tr(metric: str) -> str:
    """Return a Turkish display label for a metric name."""
    return {
        "spend": "harcama",
        "roas": "ROAS",
        "ctr": "CTR",
        "cpc": "TBM (CPC)",
        "cpa": "TBE (CPA)",
        "conversions": "dönüşüm",
    }.get(metric, metric)


def _comparator_desc_tr(comparator: str, threshold: float | None) -> str:
    """Return a Turkish description of the comparator."""
    t = f"%{threshold:.0f}" if threshold is not None else ""
    return {
        "pct_drop": f"{t} oranında düşüş",
        "pct_rise": f"{t} oranında artış",
        "below": f"{threshold} altına düşme",
        "above": f"{threshold} üzerine çıkma",
        "anomaly": "istatistiksel anomali",
    }.get(comparator, comparator)


def _build_insight_for_rule(
    rule: AutomationRule,
    evaluation: RuleEvaluation,
    is_pause_suggest: bool = False,
) -> Insight:
    """Build an Insight ORM object for an automation rule action.

    The Insight is NOT added to the session here — the caller does that.

    For "pause_suggest" actions the category becomes "automation_pause_suggest"
    and the body explicitly states it is a recommendation only (NO execution).
    """
    entity = evaluation.matched_entities[0] if evaluation.matched_entities else None
    metric_tr = _metric_label_tr(rule.metric)
    comp_desc = _comparator_desc_tr(rule.comparator, rule.threshold)

    if is_pause_suggest:
        category = "automation_pause_suggest"
        title = f"Otomatik Kural: {rule.name} — Duraklatma Önerisi"
        body = (
            f"'{rule.name}' kuralı tetiklendi: {metric_tr} metriğinde {comp_desc} "
            f"tespit edildi. "
            f"Etkilenen kampanyayı duraklatmanız önerilir. "
            f"(Bu yalnızca bir öneridir — otomatik duraklatma etkin değil; "
            f"gerçek durdurma işlemi M6 Faz 2'de eklenecektir.)"
        )
    else:
        category = "automation_alert"
        title = f"Otomatik Kural Uyarısı: {rule.name}"
        body = (
            f"'{rule.name}' kuralı tetiklendi: {metric_tr} metriğinde {comp_desc} "
            f"tespit edildi."
        )
        if entity:
            body += f" Etkilenen: {entity.entity_key}."
            if entity.current_value is not None:
                body += f" Güncel değer: {entity.current_value:.4g}."
            if entity.prior_value is not None:
                body += f" Önceki değer: {entity.prior_value:.4g}."
            if entity.pct_change is not None:
                body += f" Değişim: %{entity.pct_change * 100:.1f}."

    window_days = rule.window_days
    as_of = evaluation.as_of_date
    period_end = as_of
    period_start = as_of - timedelta(days=window_days - 1)

    channel_val: str | None = None
    entity_type_val: str | None = None
    entity_id_val: str | None = None
    entity_name_val: str | None = None
    if entity:
        if rule.scope in ("account", "channel"):
            channel_val = entity.entity_key
        entity_type_val = entity.entity_type
        entity_id_val = entity.entity_key
        entity_name_val = entity.entity_name

    return Insight(
        tenant_id=rule.tenant_id,
        category=category,
        severity="warning",
        title=title,
        body=body,
        metric=rule.metric,
        channel=channel_val,
        entity_type=entity_type_val,
        entity_id=entity_id_val,
        entity_name=entity_name_val,
        period_start=period_start,
        period_end=period_end,
        status="new",
        score=75.0,
        data=evaluation.detail,
    )


def _perform_action(
    db: Session,
    rule: AutomationRule,
    evaluation: RuleEvaluation,
) -> str:
    """Execute the rule's action and return a short description of what was done.

    Actions
    -------
    alert          → Create an Insight row with Turkish text.
    notify_email   → Log via EmailNotifier stub (no real SMTP); also create Insight.
    notify_slack   → Log via SlackNotifier stub (no real webhook); also create Insight.
    pause_suggest  → Create an Insight recommending pause; NO real execution.

    Returns
    -------
    A short action description string logged in AutomationRun.detail.
    """
    action = rule.action

    if action == "alert":
        insight = _build_insight_for_rule(rule, evaluation, is_pause_suggest=False)
        db.add(insight)
        return "alert: Insight oluşturuldu"

    if action == "notify_email":
        # Import stub notifiers lazily to mirror notifications.py pattern
        from ayaz.services.notifications import EmailNotifier

        notifier = EmailNotifier()
        cfg = rule.action_config or {}
        recipients: list[str] = cfg.get("recipients", [])
        if not recipients:
            logger.warning(
                "[automation] notify_email action_config has no recipients for rule=%s",
                rule.id,
            )
        # Build a stub insight to pass to the notifier (mirrors notifications.py)
        insight = _build_insight_for_rule(rule, evaluation, is_pause_suggest=False)
        db.add(insight)
        for recipient in recipients:
            # Use a minimal AlertRule-compatible object — the stub only needs name/id
            class _StubAlertRule:
                id = rule.id
                name = rule.name
            try:
                notifier.deliver(recipient, insight, _StubAlertRule())  # type: ignore[arg-type]
            except Exception:
                logger.warning(
                    "[automation] EmailNotifier.deliver raised for rule=%s recipient=%s",
                    rule.id, recipient, exc_info=True,
                )
        return f"notify_email: {len(recipients)} alıcıya gönderim denendi"

    if action == "notify_slack":
        from ayaz.services.notifications import SlackNotifier

        notifier = SlackNotifier()
        cfg = rule.action_config or {}
        webhook: str = cfg.get("webhook", "")
        insight = _build_insight_for_rule(rule, evaluation, is_pause_suggest=False)
        db.add(insight)
        if webhook:
            class _StubAlertRule:
                id = rule.id
                name = rule.name
            try:
                notifier.deliver(webhook, insight, _StubAlertRule())  # type: ignore[arg-type]
            except Exception:
                logger.warning(
                    "[automation] SlackNotifier.deliver raised for rule=%s",
                    rule.id, exc_info=True,
                )
            return "notify_slack: Slack webhook'una gönderim denendi"
        else:
            logger.warning(
                "[automation] notify_slack action_config has no webhook for rule=%s",
                rule.id,
            )
            return "notify_slack: webhook yapılandırılmamış"

    if action == "pause_suggest":
        # Create an Insight that RECOMMENDS pause — no real execution.
        # Actual pause capability is M6 phase 2.
        insight = _build_insight_for_rule(rule, evaluation, is_pause_suggest=True)
        db.add(insight)
        return (
            "pause_suggest: Duraklatma önerisi Insight olarak oluşturuldu "
            "(gerçek duraklatma M6 Faz 2'de eklenecek)"
        )

    logger.warning("[automation] Unknown action=%r for rule=%s", action, rule.id)
    return f"bilinmeyen eylem: {action}"


# ── run_rule ──────────────────────────────────────────────────────────────────


def run_rule(
    db: Session,
    rule: AutomationRule,
    as_of_date: date,
) -> RuleEvaluation:
    """Evaluate and (if triggered) act on a single AutomationRule.

    Workflow
    --------
    1. Call evaluate_rule (read-only).
    2. If triggered AND not already fired today → perform the action.
    3. Update rule.last_triggered_at when action is taken.
    4. Write an AutomationRun audit row regardless of whether triggered.
    5. Flush (caller is responsible for commit).

    Idempotency
    -----------
    If ``rule.last_triggered_at == str(as_of_date)`` the rule has already been
    acted on for this calendar day and the action step is skipped, but an
    AutomationRun row is still written with ``triggered=False`` to preserve the
    audit trail.

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    rule:
        The AutomationRule to run.  Must be bound to ``db``.
    as_of_date:
        The evaluation reference date.

    Returns
    -------
    The RuleEvaluation produced during evaluation.
    """
    logger.info(
        "[automation] run_rule: rule=%s name=%r as_of=%s",
        rule.id, rule.name, as_of_date,
    )

    evaluation = evaluate_rule(db, rule, as_of_date)

    already_fired_today = rule.last_triggered_at == str(as_of_date)
    action_taken: str = "not_triggered"

    if evaluation.triggered and not already_fired_today:
        action_taken = _perform_action(db, rule, evaluation)
        rule.last_triggered_at = str(as_of_date)
        logger.info(
            "[automation] Rule %s triggered → %s", rule.id, action_taken
        )
    elif evaluation.triggered and already_fired_today:
        action_taken = "already_fired_today (idempotent skip)"
        logger.info(
            "[automation] Rule %s already fired today — skipping", rule.id
        )

    # Write audit row
    ran_at = datetime.now(timezone.utc).isoformat()
    run = AutomationRun(
        tenant_id=rule.tenant_id,
        rule_id=rule.id,
        ran_at=ran_at,
        triggered=evaluation.triggered and not already_fired_today,
        detail={**evaluation.detail, "action_taken": action_taken},
    )
    db.add(run)
    db.flush()

    return evaluation


# ── run_all_active_rules ──────────────────────────────────────────────────────


def run_all_active_rules(
    db: Session,
    tenant_id: uuid.UUID | None = None,
    as_of_date: date | None = None,
) -> dict[str, int]:
    """Run all active AutomationRules for the given tenant (or all tenants).

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    tenant_id:
        When supplied, only rules for this tenant are evaluated.
        When None, rules for ALL tenants are evaluated (used by the Celery beat).
    as_of_date:
        Reference date.  Defaults to today (UTC) when None.

    Returns
    -------
    dict with keys: ``evaluated``, ``triggered``, ``errors``.
    """
    if as_of_date is None:
        as_of_date = date.today()

    stmt = select(AutomationRule).where(AutomationRule.is_active.is_(True))
    if tenant_id is not None:
        stmt = stmt.where(AutomationRule.tenant_id == tenant_id)
    stmt = stmt.order_by(AutomationRule.tenant_id, AutomationRule.created_at)

    rules = db.scalars(stmt).all()
    logger.info(
        "[automation] run_all_active_rules: %d rules to evaluate (tenant=%s as_of=%s)",
        len(rules), tenant_id, as_of_date,
    )

    counts = {"evaluated": 0, "triggered": 0, "errors": 0}

    for rule in rules:
        try:
            result = run_rule(db, rule, as_of_date)
            counts["evaluated"] += 1
            if result.triggered:
                counts["triggered"] += 1
        except Exception:
            counts["errors"] += 1
            logger.exception(
                "[automation] run_rule failed for rule=%s", rule.id
            )

    try:
        db.commit()
    except Exception:
        logger.exception("[automation] commit failed after run_all_active_rules")
        db.rollback()
        raise

    logger.info("[automation] Done: %s", counts)
    return counts
