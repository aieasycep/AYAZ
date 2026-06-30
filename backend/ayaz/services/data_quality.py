"""DATA-TRUST layer — data quality detection and metric drill-down.

Public API
----------
    detect_duplicate_accounts(db, tenant_id) -> list[dict]
        Find ConnectedAccounts that share (tenant, platform, external_account_id).

    detect_double_count_risk(db, tenant_id, period_start, period_end) -> list[dict]
        Find duplicate account groups whose metrics rows overlap in fact_daily_metrics.

    detect_kpi_inconsistencies(db, tenant_id, period_start, period_end) -> list[dict]
        Find rows in fact_daily_metrics that violate basic sanity rules.

    run_data_quality_detectors(db, tenant_id, as_of_date) -> list[DetectorResult]
        Entry point called from generate_insights() — same shape as other detectors.

    get_metric_breakdown(db, tenant_id, metric, date_from, date_to) -> dict
        "Bu sayı neden böyle?" drill-down: which connected accounts drive a total.

    check_duplicate_before_link(db, tenant_id, platform, external_account_id) -> dict
        Pre-flight check called by connectors.create_account before persisting.

Design
------
* Zero schema changes — all detection is query-based.
* Tenant isolation: every query filters explicitly on tenant_id.
* No writes inside this module; callers persist Insight rows.
* Circular-import safe: DetectorResult is imported lazily inside
  run_data_quality_detectors to avoid the insights ↔ data_quality cycle.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.oltp import ConnectedAccount, Platform

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

_DEFAULT_LOOKBACK_DAYS = 30
"""Window used for KPI sanity and double-count checks when period is not supplied."""


# ── 1. Duplicate account detection ───────────────────────────────────────────


def detect_duplicate_accounts(
    db: Session,
    tenant_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return groups of ConnectedAccounts that share (platform, external_account_id).

    Each returned dict:
        platform             str   — platform enum value
        external_account_id  str
        count                int   — number of linked accounts (always >= 2)
        account_ids          list[str]
        display_names        list[str]

    Tenant isolation: WHERE tenant_id = :tenant_id on every query.
    """
    # Step 1: find (platform, external_account_id) combos with count > 1
    dup_stmt = (
        select(
            ConnectedAccount.platform,
            ConnectedAccount.external_account_id,
            func.count(ConnectedAccount.id).label("cnt"),
        )
        .where(ConnectedAccount.tenant_id == tenant_id)
        .group_by(ConnectedAccount.platform, ConnectedAccount.external_account_id)
        .having(func.count(ConnectedAccount.id) > 1)
    )
    dup_rows = db.execute(dup_stmt).mappings().all()

    if not dup_rows:
        return []

    results: list[dict[str, Any]] = []
    for row in dup_rows:
        platform_val = str(row["platform"].value) if hasattr(row["platform"], "value") else str(row["platform"])
        ext_id = str(row["external_account_id"])

        # Fetch the actual account rows for this group
        accts = list(
            db.scalars(
                select(ConnectedAccount).where(
                    ConnectedAccount.tenant_id == tenant_id,
                    ConnectedAccount.platform == row["platform"],
                    ConnectedAccount.external_account_id == ext_id,
                )
            )
        )
        results.append(
            {
                "platform": platform_val,
                "external_account_id": ext_id,
                "count": int(row["cnt"]),
                "account_ids": [str(a.id) for a in accts],
                "display_names": [a.display_name for a in accts],
            }
        )

    return results


# ── 2. Double-count risk detection ────────────────────────────────────────────


def detect_double_count_risk(
    db: Session,
    tenant_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    """Find duplicate account groups that have fact_daily_metrics rows in [period].

    A double-count risk is confirmed when:
    - Two or more ConnectedAccounts share the same (platform, external_account_id)
    - AND at least two of those accounts have rows in fact_daily_metrics within the period.

    Each returned dict:
        platform                 str
        external_account_id      str
        duplicate_account_ids    list[str]
        affected_dates           list[str]  — ISO date strings
        overlapping_rows         int
    """
    dupes = detect_duplicate_accounts(db, tenant_id)
    if not dupes:
        return []

    results: list[dict[str, Any]] = []

    for dupe in dupes:
        account_ids_as_uuid = [uuid.UUID(aid) for aid in dupe["account_ids"]]

        # Find rows in fact_daily_metrics for ANY of the duplicate accounts
        rows = db.execute(
            select(
                FactDailyMetrics.connected_account_id,
                FactDailyMetrics.date_key,
                func.count(FactDailyMetrics.id).label("row_count"),
            )
            .where(
                FactDailyMetrics.tenant_id == tenant_id,
                FactDailyMetrics.connected_account_id.in_(account_ids_as_uuid),
                FactDailyMetrics.date_key >= period_start,
                FactDailyMetrics.date_key <= period_end,
            )
            .group_by(
                FactDailyMetrics.connected_account_id,
                FactDailyMetrics.date_key,
            )
        ).mappings().all()

        if not rows:
            continue

        # Check how many DISTINCT account_ids have rows — double-count requires >= 2
        active_account_ids = {str(r["connected_account_id"]) for r in rows}
        if len(active_account_ids) < 2:
            continue

        affected_dates = sorted(
            {str(r["date_key"]) for r in rows}
        )
        overlapping_rows = sum(int(r["row_count"]) for r in rows)

        results.append(
            {
                "platform": dupe["platform"],
                "external_account_id": dupe["external_account_id"],
                "duplicate_account_ids": list(active_account_ids),
                "affected_dates": affected_dates,
                "overlapping_rows": overlapping_rows,
            }
        )

    return results


# ── 3. KPI inconsistency detection ───────────────────────────────────────────


def detect_kpi_inconsistencies(
    db: Session,
    tenant_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    """Detect rows in fact_daily_metrics that violate sanity rules.

    Rules checked:
    1. clicks_exceed_impressions  — clicks > impressions (physically impossible)
    2. conversions_exceed_clicks  — conversions > clicks AND both > 0
    3. spend_without_impressions  — cost_base_ccy > 0 AND impressions == 0

    Each returned dict:
        rule                  str   — rule key from above
        date_key              str
        connected_account_id  str
        channel_id            str
        details               dict  — raw values for that row

    Tenant isolation: WHERE tenant_id = :tenant_id.
    """
    results: list[dict[str, Any]] = []

    base_where = [
        FactDailyMetrics.tenant_id == tenant_id,
        FactDailyMetrics.date_key >= period_start,
        FactDailyMetrics.date_key <= period_end,
    ]

    # Rule 1: clicks > impressions
    rows1 = db.execute(
        select(
            FactDailyMetrics.date_key,
            FactDailyMetrics.connected_account_id,
            FactDailyMetrics.channel_id,
            FactDailyMetrics.impressions,
            FactDailyMetrics.clicks,
        ).where(
            *base_where,
            FactDailyMetrics.clicks > FactDailyMetrics.impressions,
            FactDailyMetrics.impressions >= 0,
        )
    ).mappings().all()

    for row in rows1:
        results.append(
            {
                "rule": "clicks_exceed_impressions",
                "date_key": str(row["date_key"]),
                "connected_account_id": str(row["connected_account_id"]),
                "channel_id": str(row["channel_id"]),
                "details": {
                    "impressions": int(row["impressions"]),
                    "clicks": int(row["clicks"]),
                },
            }
        )

    # Rule 2: conversions > clicks (both > 0)
    rows2 = db.execute(
        select(
            FactDailyMetrics.date_key,
            FactDailyMetrics.connected_account_id,
            FactDailyMetrics.channel_id,
            FactDailyMetrics.clicks,
            FactDailyMetrics.conversions,
        ).where(
            *base_where,
            FactDailyMetrics.clicks > 0,
            FactDailyMetrics.conversions > FactDailyMetrics.clicks,
        )
    ).mappings().all()

    for row in rows2:
        results.append(
            {
                "rule": "conversions_exceed_clicks",
                "date_key": str(row["date_key"]),
                "connected_account_id": str(row["connected_account_id"]),
                "channel_id": str(row["channel_id"]),
                "details": {
                    "clicks": int(row["clicks"]),
                    "conversions": float(row["conversions"]),
                },
            }
        )

    # Rule 3: spend > 0 but impressions == 0
    rows3 = db.execute(
        select(
            FactDailyMetrics.date_key,
            FactDailyMetrics.connected_account_id,
            FactDailyMetrics.channel_id,
            FactDailyMetrics.cost_base_ccy,
            FactDailyMetrics.impressions,
        ).where(
            *base_where,
            FactDailyMetrics.impressions == 0,
            FactDailyMetrics.cost_base_ccy > 0,
        )
    ).mappings().all()

    for row in rows3:
        results.append(
            {
                "rule": "spend_without_impressions",
                "date_key": str(row["date_key"]),
                "connected_account_id": str(row["connected_account_id"]),
                "channel_id": str(row["channel_id"]),
                "details": {
                    "cost_base_ccy": float(row["cost_base_ccy"]),
                    "impressions": int(row["impressions"]),
                },
            }
        )

    return results


# ── 4. Detector entry point (DetectorResult shape) ────────────────────────────


def run_data_quality_detectors(
    db: Session,
    tenant_id: uuid.UUID,
    as_of_date: date,
) -> list[Any]:  # returns list[DetectorResult] — lazy import avoids cycle
    """Run all data-quality checks and return DetectorResult objects.

    Called from generate_insights() alongside the other detectors.
    Import of DetectorResult is lazy to avoid a circular import cycle:
    insights.py imports this module inside generate_insights() body;
    this module must not import insights at module level.

    Period: (as_of_date - 29) to as_of_date, matching the standard 30-day window.
    """
    from ayaz.services.insights import DetectorResult  # lazy — safe from cycle

    period_start = as_of_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS - 1)
    period_end = as_of_date

    detector_results: list[DetectorResult] = []

    # --- Duplicate accounts ---
    try:
        dupes = detect_duplicate_accounts(db, tenant_id)
        for dupe in dupes:
            count = dupe["count"]
            severity = "critical" if count >= 3 else "warning"
            score = min(count * 20.0, 100.0)
            entity_id = f"{dupe['platform']}_{dupe['external_account_id']}"
            detector_results.append(
                DetectorResult(
                    category="data_quality",
                    severity=severity,
                    metric="connected_accounts",
                    channel=None,
                    period_start=period_start,
                    period_end=period_end,
                    score=score,
                    entity_type="account",
                    entity_id=entity_id,
                    entity_name=f"{dupe['platform']} / {dupe['external_account_id']}",
                    data={
                        "rule": "duplicate_accounts",
                        "platform": dupe["platform"],
                        "external_account_id": dupe["external_account_id"],
                        "count": count,
                        "account_ids": dupe["account_ids"],
                        "display_names": dupe["display_names"],
                    },
                )
            )
    except Exception:
        log.warning("[data_quality] duplicate_accounts detector failed", exc_info=True)

    # --- Double-count risk ---
    try:
        risks = detect_double_count_risk(db, tenant_id, period_start, period_end)
        for risk in risks:
            entity_id = f"{risk['platform']}_{risk['external_account_id']}"
            detector_results.append(
                DetectorResult(
                    category="data_quality",
                    severity="critical",
                    metric="spend",
                    channel=None,
                    period_start=period_start,
                    period_end=period_end,
                    score=80.0,
                    entity_type="account",
                    entity_id=entity_id,
                    entity_name=f"{risk['platform']} / {risk['external_account_id']}",
                    data={
                        "rule": "double_count_risk",
                        "platform": risk["platform"],
                        "external_account_id": risk["external_account_id"],
                        "duplicate_account_ids": risk["duplicate_account_ids"],
                        "affected_dates": risk["affected_dates"],
                        "overlapping_rows": risk["overlapping_rows"],
                    },
                )
            )
    except Exception:
        log.warning("[data_quality] double_count_risk detector failed", exc_info=True)

    # --- KPI inconsistencies ---
    _rule_severity: dict[str, tuple[str, float]] = {
        "clicks_exceed_impressions": ("critical", 70.0),
        "conversions_exceed_clicks": ("warning", 50.0),
        "spend_without_impressions": ("warning", 40.0),
    }

    try:
        inconsistencies = detect_kpi_inconsistencies(
            db, tenant_id, period_start, period_end
        )
        # Deduplicate by rule — one DetectorResult per rule type
        rules_seen: set[str] = set()
        for item in inconsistencies:
            rule = item["rule"]
            if rule in rules_seen:
                continue
            rules_seen.add(rule)
            sev, score = _rule_severity.get(rule, ("warning", 40.0))
            # Count how many rows had this issue
            rule_count = sum(1 for i in inconsistencies if i["rule"] == rule)
            detector_results.append(
                DetectorResult(
                    category="data_quality",
                    severity=sev,
                    metric=rule,
                    channel=None,
                    period_start=period_start,
                    period_end=period_end,
                    score=score,
                    entity_type=None,
                    entity_id=None,
                    entity_name=None,
                    data={
                        "rule": rule,
                        "affected_rows": rule_count,
                        "sample": item,
                    },
                )
            )
    except Exception:
        log.warning("[data_quality] kpi_inconsistencies detector failed", exc_info=True)

    return detector_results


# ── 5. Metric drill-down ("Bu sayı neden böyle?") ─────────────────────────────


_DERIVED_METRICS = frozenset({"roas", "ctr", "cpc"})
_RAW_METRICS = frozenset({"impressions", "clicks", "spend", "conversions"})
_ALL_METRICS = _RAW_METRICS | _DERIVED_METRICS


def get_metric_breakdown(
    db: Session,
    tenant_id: uuid.UUID,
    metric: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Return per-account breakdown of a metric total for the given period.

    Parameters
    ----------
    db:           SQLAlchemy Session.
    tenant_id:    Caller's tenant — all queries are explicitly scoped.
    metric:       One of: impressions, clicks, spend, conversions, roas, ctr, cpc.
    date_from:    Inclusive start date.
    date_to:      Inclusive end date.

    Returns
    -------
    dict with:
        metric          str
        date_from       str
        date_to         str
        total           float
        breakdown       list[dict] — one entry per (account × channel)
        duplicate_warning   bool
        duplicate_groups    list[dict]
    """
    if metric not in _ALL_METRICS:
        raise ValueError(
            f"Unknown metric {metric!r}. Allowed: {sorted(_ALL_METRICS)}"
        )

    # Aggregate raw metrics by (connected_account, channel)
    rows = db.execute(
        select(
            FactDailyMetrics.connected_account_id,
            ConnectedAccount.platform,
            ConnectedAccount.external_account_id,
            ConnectedAccount.display_name,
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
        .join(
            ConnectedAccount,
            FactDailyMetrics.connected_account_id == ConnectedAccount.id,
        )
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(
            FactDailyMetrics.connected_account_id,
            ConnectedAccount.platform,
            ConnectedAccount.external_account_id,
            ConnectedAccount.display_name,
            DimChannel.key,
        )
        .order_by(func.sum(FactDailyMetrics.cost_base_ccy).desc())
    ).mappings().all()

    def _d(v: object) -> Decimal:
        return Decimal(str(v)) if v is not None else Decimal(0)

    def _metric_value(row: Any) -> float:
        imp = _d(row["impressions"])
        clk = _d(row["clicks"])
        spd = _d(row["spend"])
        cvv = _d(row["conversion_value"])
        cvn = _d(row["conversions"])

        if metric == "impressions":
            return float(imp)
        if metric == "clicks":
            return float(clk)
        if metric == "spend":
            return float(spd)
        if metric == "conversions":
            return float(cvn)
        if metric == "roas":
            return float(cvv / spd) if spd > 0 else 0.0
        if metric == "ctr":
            return float(clk / imp) if imp > 0 else 0.0
        if metric == "cpc":
            return float(spd / clk) if clk > 0 else 0.0
        return 0.0

    breakdown: list[dict[str, Any]] = []
    for row in rows:
        platform_val = (
            str(row["platform"].value)
            if hasattr(row["platform"], "value")
            else str(row["platform"])
        )
        breakdown.append(
            {
                "connected_account_id": str(row["connected_account_id"]),
                "platform": platform_val,
                "external_account_id": str(row["external_account_id"]),
                "display_name": str(row["display_name"]),
                "channel": str(row["channel_key"]),
                "value": _metric_value(row),
                "pct_of_total": 0.0,  # filled in below
                "impressions": int(_d(row["impressions"])),
                "clicks": int(_d(row["clicks"])),
                "spend": float(_d(row["spend"])),
                "conversions": float(_d(row["conversions"])),
            }
        )

    # Compute total and percentages
    if metric in _DERIVED_METRICS:
        # For derived metrics total is the weighted average, not a simple sum
        # We compute from the aggregated totals across all accounts
        total_imp = sum(r["impressions"] for r in breakdown)
        total_clk = sum(r["clicks"] for r in breakdown)
        total_spd = sum(r["spend"] for r in breakdown)
        total_cvn = sum(r["conversions"] for r in breakdown)

        # Recompute conversion_value_total from a separate query
        conv_val_row = db.scalar(
            select(func.sum(FactDailyMetrics.conversion_value_raw)).where(
                FactDailyMetrics.tenant_id == tenant_id,
                FactDailyMetrics.date_key >= date_from,
                FactDailyMetrics.date_key <= date_to,
            )
        )
        total_cvv = float(_d(conv_val_row))

        if metric == "roas":
            total = total_cvv / total_spd if total_spd > 0 else 0.0
        elif metric == "ctr":
            total = total_clk / total_imp if total_imp > 0 else 0.0
        elif metric == "cpc":
            total = total_spd / total_clk if total_clk > 0 else 0.0
        else:
            total = 0.0

        # pct for derived: show each account's contribution to total spend
        denom = total_spd if total_spd > 0 else 1.0
        for entry in breakdown:
            entry["pct_of_total"] = round(entry["spend"] / denom * 100, 2)
    else:
        total_val = sum(r["value"] for r in breakdown)
        total = total_val
        denom = total_val if total_val > 0 else 1.0
        for entry in breakdown:
            entry["pct_of_total"] = round(entry["value"] / denom * 100, 2)

    # Duplicate warning
    dupes = detect_duplicate_accounts(db, tenant_id)
    involved_account_ids = {r["connected_account_id"] for r in breakdown}
    duplicate_warning = any(
        aid in involved_account_ids
        for dupe in dupes
        for aid in dupe["account_ids"]
    )

    return {
        "metric": metric,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "total": round(total, 6),
        "breakdown": breakdown,
        "duplicate_warning": duplicate_warning,
        "duplicate_groups": dupes if duplicate_warning else [],
    }


# ── 6. Duplicate-link pre-flight check ───────────────────────────────────────


def check_duplicate_before_link(
    db: Session,
    tenant_id: uuid.UUID,
    platform: Platform,
    external_account_id: str,
) -> dict[str, Any]:
    """Check whether a ConnectedAccount with this (platform, external_id) exists.

    Returns
    -------
    dict with:
        is_duplicate       bool
        existing_accounts  list[dict]  — [] when no duplicate
        warning            str | None  — Turkish message when is_duplicate is True
    """
    existing = list(
        db.scalars(
            select(ConnectedAccount).where(
                ConnectedAccount.tenant_id == tenant_id,
                ConnectedAccount.platform == platform,
                ConnectedAccount.external_account_id == external_account_id,
            )
        )
    )

    if not existing:
        return {"is_duplicate": False, "existing_accounts": [], "warning": None}

    platform_str = platform.value if hasattr(platform, "value") else str(platform)
    existing_list = [
        {
            "id": str(a.id),
            "display_name": a.display_name,
            "sync_status": str(a.sync_status.value) if hasattr(a.sync_status, "value") else str(a.sync_status),
            "created_at": str(a.created_at) if hasattr(a, "created_at") else None,
        }
        for a in existing
    ]

    warning = (
        f"Bu harici hesap ({platform_str} / {external_account_id}) zaten "
        f"{len(existing)} kez bağlanmış. Yeniden bağlamak tüm metrik "
        f"toplamlarında çift sayıma yol açacaktır. Devam etmek için "
        f"allow_duplicate=true parametresini ekleyin."
    )

    return {
        "is_duplicate": True,
        "existing_accounts": existing_list,
        "warning": warning,
    }
