"""Copilot tool registry — the functions the AI assistant can call.

Each tool is a pure Python callable that wraps existing service functions.
No business logic is duplicated here; the tools are thin adapters that
translate from the copilot's parameter space (dates as strings, optional
filters as strings) into the typed signatures the services expect.

Public exports
--------------
TOOL_SPECS   — list of Claude-compatible tool schema dicts (name, description,
               input_schema).
dispatch     — call a tool by name and return its dict result.

Tool catalogue
--------------
get_performance_summary(date_from, date_to)
    Cross-channel totals + per-channel breakdown for the date range.
    Delegates to the dashboard query logic (replicated here for service-layer
    access; the dashboard API does the same aggregation).

get_timeseries(date_from, date_to, metric)
    Daily values of one metric across all channels.

list_campaigns(date_from, date_to, channel?, sort?)
    Per-campaign metrics table.  Delegates to ads.list_campaigns.

get_recommendations(date_from, date_to)
    Campaign-grain recommendations from the insights detectors.
    Delegates to ads.campaign_recommendations.

get_insights(severity?)
    Persisted Insight rows for the tenant, optionally filtered by severity.
    Returns the most recent 20.

get_feed_channels()
    FeedChannel rows for the tenant (name, channel_type, last sync).

draft_automation_rule(name, metric, comparator, threshold, action)
    Returns a DRAFT dict describing the rule the user described.
    DOES NOT persist — the user confirms in the Automation UI.

get_subscription_status()
    Current plan + entitlements from billing.entitlements().

Tenant isolation
----------------
Every tool receives tenant_id and passes it through to the underlying service.
No cross-tenant data is ever accessible via these tools.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.services.metrics import compute_derived_metrics, compute_top_movers


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> date:
    """Parse an ISO-8601 date string, defaulting to today on error."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return date.today()


def _d(v: object) -> Decimal:
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


# ── Tool implementations ───────────────────────────────────────────────────────


def _get_performance_summary(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: str,
    date_to: str,
) -> dict:
    """Aggregate totals and per-channel breakdown for the date range."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    channel_rows = db.execute(
        select(
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
            FactDailyMetrics.date_key >= df,
            FactDailyMetrics.date_key <= dt,
        )
        .group_by(DimChannel.key)
        .order_by(DimChannel.key)
    ).mappings().all()

    by_channel = []
    total_imp = Decimal(0)
    total_clk = Decimal(0)
    total_spd = Decimal(0)
    total_cvr = Decimal(0)
    total_cvv = Decimal(0)

    for row in channel_rows:
        imp = _d(row["impressions"])
        clk = _d(row["clicks"])
        spd = _d(row["spend"])
        cvr = _d(row["conversions"])
        cvv = _d(row["conversion_value"])
        derived = compute_derived_metrics(
            impressions=imp,
            clicks=clk,
            spend=spd,
            conversions=cvr,
            conversion_value=cvv,
        )
        by_channel.append({
            "channel": str(row["channel_key"]),
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
        total_imp += imp
        total_clk += clk
        total_spd += spd
        total_cvr += cvr
        total_cvv += cvv

    total_derived = compute_derived_metrics(
        impressions=total_imp,
        clicks=total_clk,
        spend=total_spd,
        conversions=total_cvr,
        conversion_value=total_cvv,
    )

    return {
        "date_from": str(df),
        "date_to": str(dt),
        "totals": {
            "spend": float(total_spd),
            "impressions": float(total_imp),
            "clicks": float(total_clk),
            "conversions": float(total_cvr),
            "conversion_value": float(total_cvv),
            "ctr": float(total_derived["ctr"]),
            "cpc": float(total_derived["cpc"]),
            "cpa": float(total_derived["cpa"]),
            "roas": float(total_derived["roas"]),
        },
        "by_channel": by_channel,
    }


def _get_timeseries(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: str,
    date_to: str,
    metric: str,
) -> dict:
    """Daily values of one metric across all channels."""
    from ayaz.services.metrics import ctr as _ctr, cpc as _cpc, roas as _roas, cpa as _cpa

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    _SUPPORTED = {"spend", "impressions", "clicks", "conversions", "conversion_value", "roas"}
    if metric not in _SUPPORTED:
        metric = "spend"

    rows = db.execute(
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
            FactDailyMetrics.date_key >= df,
            FactDailyMetrics.date_key <= dt,
        )
        .group_by(FactDailyMetrics.date_key)
        .order_by(FactDailyMetrics.date_key)
    ).mappings().all()

    points = []
    for row in rows:
        imp = _d(row["impressions"])
        clk = _d(row["clicks"])
        spd = _d(row["spend"])
        cvr = _d(row["conversions"])
        cvv = _d(row["conversion_value"])

        if metric == "spend":
            val = float(spd)
        elif metric == "impressions":
            val = float(imp)
        elif metric == "clicks":
            val = float(clk)
        elif metric == "conversions":
            val = float(cvr)
        elif metric == "conversion_value":
            val = float(cvv)
        elif metric == "roas":
            val = float(_roas(cvv, spd))
        else:
            val = float(spd)

        points.append({"date": str(row["date_key"]), "value": val})

    return {"metric": metric, "date_from": str(df), "date_to": str(dt), "points": points}


def _list_campaigns(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: str,
    date_to: str,
    channel: str | None = None,
    sort: str | None = None,
) -> dict:
    """Per-campaign metrics, delegating to ads.list_campaigns."""
    from ayaz.services.ads import list_campaigns

    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    campaigns = list_campaigns(
        db,
        tenant_id,
        df,
        dt,
        channel=channel or None,
        sort=sort or "spend",
        sort_desc=True,
    )
    return {"date_from": str(df), "date_to": str(dt), "campaigns": campaigns[:20]}


def _get_recommendations(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: str,
    date_to: str,
) -> dict:
    """Campaign-grain recommendations from the insights detectors."""
    from ayaz.services.ads import campaign_recommendations

    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    recs = campaign_recommendations(db, tenant_id, df, dt)
    return {
        "date_from": str(df),
        "date_to": str(dt),
        "recommendations": recs[:10],
    }


def _get_insights(
    db: Session,
    tenant_id: uuid.UUID,
    severity: str | None = None,
) -> dict:
    """Persisted Insight rows, optionally filtered by severity."""
    from ayaz.models.insights import Insight
    from sqlalchemy import select, desc

    stmt = (
        select(Insight)
        .where(Insight.tenant_id == tenant_id)
        .order_by(desc(Insight.created_at))
        .limit(20)
    )
    if severity and severity in ("info", "warning", "critical"):
        stmt = stmt.where(Insight.severity == severity)

    insights = db.scalars(stmt).all()
    return {
        "count": len(insights),
        "insights": [
            {
                "id": str(i.id),
                "category": i.category,
                "severity": i.severity,
                "title": i.title,
                "metric": i.metric,
                "channel": i.channel,
                "score": i.score,
                "period_start": str(i.period_start),
                "period_end": str(i.period_end),
            }
            for i in insights
        ],
    }


def _get_feed_channels(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """FeedChannel rows for the tenant."""
    from ayaz.models.feeds import FeedChannel, FeedSource
    from sqlalchemy import select

    rows = db.scalars(
        select(FeedChannel).where(FeedChannel.tenant_id == tenant_id).limit(20)
    ).all()

    channels = []
    for ch in rows:
        # Fetch the source to get last_synced_at and item_count.
        # Tenant-isolation guard: ignore a source that does not belong to this
        # tenant (defence-in-depth against a stale/cross-tenant FK).
        source = db.get(FeedSource, ch.feed_source_id) if ch.feed_source_id else None
        if source is not None and source.tenant_id != tenant_id:
            source = None
        channels.append({
            "id": str(ch.id),
            "name": ch.name,
            "channel_type": ch.channel_type,
            "output_format": ch.output_format,
            "last_synced_at": source.last_synced_at if source else None,
            "item_count": source.item_count if source else 0,
        })

    return {"count": len(channels), "channels": channels}


def _get_content_status(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """Content planner status: counts by workflow status + upcoming scheduled posts."""
    from ayaz.models.content import ContentPost
    from sqlalchemy import select

    rows = db.scalars(
        select(ContentPost).where(ContentPost.tenant_id == tenant_id)
    ).all()

    by_status: dict[str, int] = {}
    for p in rows:
        by_status[p.status] = by_status.get(p.status, 0) + 1

    # Upcoming scheduled posts, soonest first (top 5).
    scheduled = sorted(
        [p for p in rows if p.status == "scheduled" and p.scheduled_at],
        key=lambda p: p.scheduled_at or "",
    )
    upcoming = [
        {
            "title": p.title,
            "scheduled_at": p.scheduled_at,
            "channels": p.channels if isinstance(p.channels, list) else [],
        }
        for p in scheduled[:5]
    ]

    return {
        "total": len(rows),
        "by_status": by_status,
        "draft": by_status.get("draft", 0),
        "pending_approval": by_status.get("pending_approval", 0),
        "approved": by_status.get("approved", 0),
        "scheduled": by_status.get("scheduled", 0),
        "published": by_status.get("published", 0),
        "upcoming": upcoming,
    }


def _get_budget_status(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """Latest budget plan summary: total, objective, period, top channel allocation."""
    from ayaz.models.budget import BudgetPlan
    from sqlalchemy import select

    plan = db.scalar(
        select(BudgetPlan)
        .where(BudgetPlan.tenant_id == tenant_id)
        .order_by(BudgetPlan.created_at.desc())
    )
    if plan is None:
        return {"has_plan": False}

    alloc = plan.allocations if isinstance(plan.allocations, dict) else {}
    platforms = alloc.get("platforms", []) if isinstance(alloc, dict) else []
    top = [
        {
            "label": p.get("label"),
            "recommended_budget": p.get("recommended_budget"),
            "recommended_share": p.get("recommended_share"),
        }
        for p in platforms[:3]
    ]
    projection = alloc.get("projection", {}) if isinstance(alloc, dict) else {}
    return {
        "has_plan": True,
        "name": plan.name,
        "period_month": plan.period_month,
        "total_budget": float(plan.total_budget or 0),
        "currency": plan.currency,
        "objective": plan.objective,
        "status": plan.status,
        "top_platforms": top,
        "projection": projection,
    }


def _get_inbox_summary(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """Social inbox summary: open/pending/resolved counts + sentiment + channel mix."""
    from ayaz.models.social_inbox import SocialMessage
    from ayaz.services.social_inbox import compute_inbox_stats
    from sqlalchemy import select

    rows = db.scalars(
        select(SocialMessage).where(SocialMessage.tenant_id == tenant_id)
    ).all()
    return compute_inbox_stats(rows)


def _get_executive_summary(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """High-level executive overview for the last 30 days (KPIs + headline)."""
    from datetime import datetime, timedelta, timezone
    from ayaz.services.executive import build_overview

    today = datetime.now(timezone.utc).date()
    overview = build_overview(db, tenant_id, today - timedelta(days=29), today)
    # Return a compact subset for the assistant
    return {
        "kpis": overview.get("kpis", {}),
        "channels": overview.get("channels", [])[:3],
        "headline": overview.get("headline", ""),
    }


def _draft_automation_rule(
    db: Session,
    tenant_id: uuid.UUID,
    name: str,
    metric: str,
    comparator: str,
    threshold: float,
    action: str,
) -> dict:
    """Return a DRAFT automation rule dict.  Does NOT persist anything."""
    from ayaz.services.automation import (
        VALID_METRICS,
        VALID_COMPARATORS,
        VALID_ACTIONS,
    )

    issues = []
    if metric not in VALID_METRICS:
        issues.append(f"Geçersiz metrik: {metric!r}. Geçerli değerler: {sorted(VALID_METRICS)}")
    if comparator not in VALID_COMPARATORS:
        issues.append(f"Geçersiz karşılaştırıcı: {comparator!r}. Geçerli değerler: {sorted(VALID_COMPARATORS)}")
    if action not in VALID_ACTIONS:
        issues.append(f"Geçersiz eylem: {action!r}. Geçerli değerler: {sorted(VALID_ACTIONS)}")

    if issues:
        return {
            "draft": False,
            "errors": issues,
            "note": "Lütfen parametreleri düzeltin ve tekrar onaylayın.",
        }

    return {
        "draft": True,
        "note": (
            "Bu bir TASLAK'tır — henüz kaydedilmedi. "
            "Oluşturmak için Otomasyon UI'da onaylayın."
        ),
        "rule": {
            "name": name,
            "metric": metric,
            "comparator": comparator,
            "threshold": threshold,
            "action": action,
            "scope": "account",
            "window_days": 7,
            "is_active": True,
        },
    }


# ── ACTION tools (v2) — real writes, tenant-scoped ────────────────────────────


def _create_automation_rule(
    db: Session,
    tenant_id: uuid.UUID,
    name: str,
    metric: str,
    comparator: str,
    action: str,
    scope: str = "account",
    scope_filter: str | None = None,
    threshold: float | None = None,
    window_days: int = 7,
) -> dict:
    """Persist a new AutomationRule for the tenant.

    This is an ACTION tool — it writes to the DB.  The stub path only calls
    this when the user clearly requests rule creation with enough parameters.
    """
    from ayaz.models.automation import AutomationRule
    from ayaz.services.automation import VALID_METRICS, VALID_COMPARATORS, VALID_ACTIONS, VALID_SCOPES

    errors = []
    if scope not in VALID_SCOPES:
        scope = "account"
    if metric not in VALID_METRICS:
        errors.append(f"Geçersiz metrik: {metric!r}. Geçerli değerler: {sorted(VALID_METRICS)}")
    if comparator not in VALID_COMPARATORS:
        errors.append(f"Geçersiz karşılaştırıcı: {comparator!r}. Geçerli değerler: {sorted(VALID_COMPARATORS)}")
    if action not in VALID_ACTIONS:
        errors.append(f"Geçersiz eylem: {action!r}. Geçerli değerler: {sorted(VALID_ACTIONS)}")

    if errors:
        return {"created": False, "errors": errors}

    rule = AutomationRule(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        scope=scope,
        scope_filter=scope_filter if scope != "account" else None,
        metric=metric,
        comparator=comparator,
        threshold=float(threshold) if threshold is not None else None,
        window_days=max(int(window_days), 1),
        action=action,
        action_config={},
        is_active=True,
    )
    db.add(rule)
    db.flush()

    return {
        "created": True,
        "rule_id": str(rule.id),
        "name": rule.name,
        "metric": rule.metric,
        "comparator": rule.comparator,
        "threshold": rule.threshold,
        "action": rule.action,
        "scope": rule.scope,
        "window_days": rule.window_days,
        "is_active": rule.is_active,
        "message": f"Otomasyon kuralı oluşturuldu: '{rule.name}'",
    }


def _create_goal(
    db: Session,
    tenant_id: uuid.UUID,
    name: str,
    metric: str,
    target_value: float,
    period_start: str,
    period_end: str,
    channel_filter: str | None = None,
) -> dict:
    """Persist a new Goal for the tenant.

    This is an ACTION tool — it writes to the DB.  The stub path only calls
    this when the user clearly requests goal creation with enough parameters.
    """
    from ayaz.services.goals import create_goal, ALL_METRICS

    if metric not in ALL_METRICS:
        return {
            "created": False,
            "errors": [f"Geçersiz metrik: {metric!r}. Geçerli değerler: {sorted(ALL_METRICS)}"],
        }

    try:
        goal = create_goal(
            db=db,
            tenant_id=tenant_id,
            name=name,
            metric=metric,
            target_value=float(target_value),
            period_start=period_start,
            period_end=period_end,
            channel_filter=channel_filter,
        )
    except ValueError as exc:
        return {"created": False, "errors": [str(exc)]}

    return {
        "created": True,
        "goal_id": str(goal.id),
        "name": goal.name,
        "metric": goal.metric,
        "target_value": goal.target_value,
        "period_start": goal.period_start,
        "period_end": goal.period_end,
        "channel_filter": goal.channel_filter,
        "message": f"Hedef oluşturuldu: '{goal.name}'",
    }


def _get_top_movers(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: str | None = None,
    date_to: str | None = None,
    dimension: str = "channel",
    metric: str = "spend",
    limit: int = 5,
) -> dict:
    """Return the top movers ranked by absolute delta vs the prior period.

    Defaults to the last 30 days when dates are omitted (same convention as
    _get_performance_summary).  Delegates entirely to compute_top_movers which
    is the single source of truth for this calculation.
    """
    from datetime import timedelta

    today = date.today()
    if date_to is None or date_to == "":
        dt = today
    else:
        dt = _parse_date(date_to)

    if date_from is None or date_from == "":
        df = today - timedelta(days=29)
    else:
        df = _parse_date(date_from)

    # Symmetry guard: if date_from is after date_to, swap them so the
    # underlying service always receives a valid (non-negative) date range.
    if df > dt:
        df, dt = dt, df

    # Clamp limit to sensible bounds.
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5

    result = compute_top_movers(
        db=db,
        tenant_id=tenant_id,
        date_from=df,
        date_to=dt,
        dimension=dimension,
        metric=metric,
        limit=limit,
    )

    return {
        "dimension": result["dimension"],
        "metric": result["metric"],
        "period": f"{result['date_from']} / {result['date_to']}",
        "previous_period": f"{result['previous_from']} / {result['previous_to']}",
        "movers": [
            {
                "label": m["label"],
                "current": m["current"],
                "previous": m["previous"],
                "delta": m["delta"],
                "delta_pct": m["delta_pct"],
                "direction": m["direction"],
            }
            for m in result["movers"]
        ],
    }


def _get_funnel_summary(
    db: Session,
    tenant_id: uuid.UUID,
    params: dict | None = None,
) -> dict:
    """Dönüşüm hunisi özeti — build_funnel'i çağırır ve kilit sayıları döner."""
    from datetime import timedelta
    from ayaz.services.funnel import build_funnel

    today = date.today()
    date_to = today.isoformat()
    date_from = (today - timedelta(days=29)).isoformat()

    result = build_funnel(db, tenant_id, date_from=date_from, date_to=date_to)
    # Return full result; it is already compact enough for the copilot layer.
    return result


def _get_consent_summary(
    db: Session,
    tenant_id: uuid.UUID,
    params: dict | None = None,
) -> dict:
    """KVKK rıza merkezi özeti — build_consent_center'ı çağırır ve kilit alanları döner."""
    from ayaz.services.consent_center import build_consent_center

    full = build_consent_center(db, tenant_id)

    summary = full.get("summary", {})
    compliance = full.get("compliance", {})

    return {
        "consent_rate_pct": summary.get("consent_rate_pct", 0.0),
        "total_events": summary.get("total_events", 0),
        "consented_events": summary.get("consented_events", 0),
        "skipped_no_consent": summary.get("skipped_no_consent", 0),
        "compliance_score": compliance.get("score", 0),
        "compliance_grade": compliance.get("grade", ""),
        "compliance_counts": compliance.get("counts", {}),
        "period": full.get("period", {}),
    }


def _get_benchmark_summary(
    db: Session,
    tenant_id: uuid.UUID,
    params: dict | None = None,
) -> dict:
    """Sektör kıyaslama özeti — build_benchmark'ı son 30 gün için çağırır."""
    from datetime import timedelta
    from ayaz.services.benchmark import build_benchmark

    today = date.today()
    date_to = today
    date_from = today - timedelta(days=29)

    result = build_benchmark(db, tenant_id, date_from, date_to)

    # Extract key fields: headline, summary_counts, and per-metric positions
    metrics_summary = [
        {
            "key": m["key"],
            "label": m["label"],
            "your_value": m["your_value"],
            "unit": m["unit"],
            "position": m["position"],
            "verdict": m["verdict"],
        }
        for m in result.get("metrics", [])
    ]

    return {
        "period": result.get("period", {}),
        "vertical": result.get("vertical", "E-ticaret"),
        "headline": result.get("headline", ""),
        "summary_counts": result.get("summary_counts", {}),
        "metrics": metrics_summary,
    }


def _get_audit_summary(
    db: Session,
    tenant_id: uuid.UUID,
    params: dict | None = None,
) -> dict:
    """Hesap sağlık taraması özeti — run_account_audit'i çağırır."""
    from ayaz.services.audit import run_account_audit

    result = run_account_audit(db, tenant_id)

    # Include top failing/warning checks for actionable copilot context
    all_checks = [
        c
        for cat in result.get("categories", [])
        for c in cat.get("checks", [])
    ]
    top_issues = [c for c in all_checks if c.get("severity") in ("fail", "warn")][:5]

    return {
        "score": result.get("score", 0),
        "grade": result.get("grade", ""),
        "summary": result.get("summary", ""),
        "counts": result.get("counts", {}),
        "top_issues": [
            {
                "severity": c.get("severity"),
                "title": c.get("title"),
                "finding": c.get("finding"),
            }
            for c in top_issues
        ],
    }


def _get_subscription_status(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict:
    """Current plan and entitlements from billing."""
    from ayaz.services.billing import entitlements, get_subscription

    sub = get_subscription(db, tenant_id)
    ents = entitlements(db, tenant_id)
    return {
        "plan_code": ents["plan_code"],
        "plan_name": ents["plan_name"],
        "status": ents["status"],
        "limits": ents["limits"],
        "features": ents["features"],
        "trial_end": sub.trial_end,
        "current_period_end": sub.current_period_end,
    }


def _get_notifications(
    db: Session,
    tenant_id: uuid.UUID,
    unread_only: bool = False,
    limit: int = 10,
) -> dict:
    """Return recent notifications for the tenant.

    Calls sync_from_insights first (lazy generation) to ensure notifications
    reflect the current state of insights before listing.  Tenant-scoped.
    """
    from ayaz.services.notifications_center import (
        list_notifications,
        sync_from_insights,
        unread_count,
    )

    # Lazy sync: generate any new notifications from unseen insights
    sync_from_insights(db, tenant_id)

    # Clamp limit to sensible bounds
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10

    notifications = list_notifications(
        db, tenant_id, unread_only=unread_only, limit=limit
    )
    count_unread = unread_count(db, tenant_id)

    return {
        "unread_count": count_unread,
        "notifications": [
            {
                "id": str(n.id),
                "title": n.title,
                "severity": n.severity,
                "type": n.type,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "read": n.read_at is not None,
            }
            for n in notifications
        ],
    }


def _get_goal_progress(
    db: Session,
    tenant_id: uuid.UUID,
    goal_id: str | None = None,
) -> dict:
    """Return progress for all of the tenant's goals (or one specific goal).

    For each goal returns name, metric, target_value, current_value,
    pct_to_target, forecast_value, status, and a Turkish recommendation.
    Delegates entirely to goals.list_goals + goals.compute_progress.
    Tenant-scoped.
    """
    from datetime import date as _date

    from ayaz.services.goals import compute_progress, get_goal, list_goals

    as_of = _date.today()

    if goal_id is not None:
        # Focus on a single goal
        try:
            gid = uuid.UUID(str(goal_id))
        except ValueError:
            return {"error": f"Geçersiz goal_id formatı: {goal_id!r}"}

        goal = get_goal(db, tenant_id, gid)
        if goal is None:
            return {"error": f"Hedef bulunamadı: {goal_id!r}"}
        goals = [goal]
    else:
        goals = list_goals(db, tenant_id, active_only=True)

    if not goals:
        return {
            "goals": [],
            "note": "Bu kiracı için henüz aktif hedef tanımlanmamış.",
        }

    result = []
    for g in goals:
        progress = compute_progress(db=db, goal=g, as_of_date=as_of)
        result.append({
            "goal_id": str(g.id),
            "name": g.name,
            "metric": g.metric,
            "target_value": progress.target_value,
            "current_value": progress.current_value,
            "pct_to_target": progress.pct_to_target,
            "forecast_value": progress.forecast_value,
            "status": progress.status,
            "recommendation": progress.recommendation,
        })

    return {"goals": result}


# ── Tool dispatch table ────────────────────────────────────────────────────────

# Tools marked is_action=True perform real DB writes.  The stub path should
# only call them when the user's intent is unambiguous and all required
# parameters are present.  The Claude path relies on the model's judgment,
# guided by the updated system prompt.

_TOOLS: dict[str, Any] = {
    # ── Read tools ──────────────────────────────────────────────────────────
    "get_performance_summary": _get_performance_summary,
    "get_timeseries": _get_timeseries,
    "list_campaigns": _list_campaigns,
    "get_recommendations": _get_recommendations,
    "get_insights": _get_insights,
    "get_feed_channels": _get_feed_channels,
    "get_content_status": _get_content_status,
    "get_budget_status": _get_budget_status,
    "get_inbox_summary": _get_inbox_summary,
    "get_executive_summary": _get_executive_summary,
    "draft_automation_rule": _draft_automation_rule,
    "get_top_movers": _get_top_movers,
    "get_subscription_status": _get_subscription_status,
    "get_notifications": _get_notifications,
    "get_goal_progress": _get_goal_progress,
    # ── Dalga 77: new module tools ───────────────────────────────────────────
    "get_funnel_summary": _get_funnel_summary,
    "get_consent_summary": _get_consent_summary,
    "get_benchmark_summary": _get_benchmark_summary,
    "get_audit_summary": _get_audit_summary,
    # ── Action tools (v2) — real writes ─────────────────────────────────────
    "create_automation_rule": _create_automation_rule,
    "create_goal": _create_goal,
}

# Which tools perform writes (used for audit / confirmation logic)
ACTION_TOOLS: frozenset[str] = frozenset({"create_automation_rule", "create_goal"})


def dispatch(
    name: str,
    db: Session,
    tenant_id: uuid.UUID,
    args: dict,
) -> dict:
    """Call the named tool and return its result dict.

    Parameters
    ----------
    name       : tool function name.
    db         : SQLAlchemy Session (read-only for most tools; draft_automation_rule
                 doesn't write either, so effectively all tools are read-only).
    tenant_id  : always forwarded; tools must not use any other tenant's data.
    args       : keyword arguments from the model's tool_use block (already parsed).

    Returns
    -------
    dict  — always a dict (never raises; wraps errors in {"error": ...}).
    """
    fn = _TOOLS.get(name)
    if fn is None:
        return {"error": f"Bilinmeyen araç: {name!r}"}
    try:
        return fn(db=db, tenant_id=tenant_id, **args)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "[copilot_tools] dispatch(%r) raised: %s", name, exc, exc_info=True
        )
        # Return a generic Turkish message — never expose internal exception
        # details (e.g. Python TypeError/signature strings) to the caller.
        return {"error": "Araç çalıştırılamadı."}


# ── Claude tool schemas (TOOL_SPECS) ───────────────────────────────────────────

TOOL_SPECS: list[dict] = [
    {
        "name": "get_performance_summary",
        "description": (
            "Belirtilen tarih aralığında kiracının tüm kanallar genelindeki "
            "reklam performansı özetini döndürür. "
            "Toplam harcama, gösterim, tıklama, dönüşüm, ROAS, CTR, CPC, CPA "
            "ile kanal bazlı dağılımı içerir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Başlangıç tarihi (YYYY-MM-DD). Dahil.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Bitiş tarihi (YYYY-MM-DD). Dahil.",
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "get_timeseries",
        "description": (
            "Belirtilen metriğin günlük zaman serisini döndürür. "
            "Tüm kanalların toplamıdır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Başlangıç tarihi (YYYY-MM-DD)."},
                "date_to": {"type": "string", "description": "Bitiş tarihi (YYYY-MM-DD)."},
                "metric": {
                    "type": "string",
                    "description": (
                        "Metrik adı: spend | impressions | clicks | "
                        "conversions | conversion_value | roas"
                    ),
                    "enum": [
                        "spend", "impressions", "clicks",
                        "conversions", "conversion_value", "roas",
                    ],
                },
            },
            "required": ["date_from", "date_to", "metric"],
        },
    },
    {
        "name": "list_campaigns",
        "description": (
            "Kampanya bazlı metrikleri listeler: harcama, gösterim, tıklama, "
            "dönüşüm, ROAS, CTR, CPC, CPA. "
            "İsteğe bağlı olarak kanal ve sıralama filtresi uygulanabilir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Başlangıç tarihi."},
                "date_to": {"type": "string", "description": "Bitiş tarihi."},
                "channel": {
                    "type": "string",
                    "description": "Kanal anahtarı ile filtrele (ör. google_ads). İsteğe bağlı.",
                },
                "sort": {
                    "type": "string",
                    "description": "Sıralama metriği (spend, roas, ctr, cpc, cpa, clicks, conversions). Varsayılan: spend.",
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "get_recommendations",
        "description": (
            "Kampanya bazlı otomatik öneriler üretir. "
            "ROAS düşüşü, harcama artışı, sıfır dönüşüm, CTR düşüşü, CPC artışı "
            "gibi sorunları tespit eder ve Türkçe aksiyon önerisi sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Başlangıç tarihi."},
                "date_to": {"type": "string", "description": "Bitiş tarihi."},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "get_insights",
        "description": (
            "Sistemin daha önce tespit ettiği içgörüleri (anomali, ROAS düşüşü, vb.) "
            "listeler. İsteğe bağlı olarak önem seviyesine göre filtreleyin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "description": "Filtre: info | warning | critical. Boş bırakılırsa hepsi.",
                    "enum": ["info", "warning", "critical"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_feed_channels",
        "description": (
            "Ürün feed kanallarını listeler (Google Shopping, Meta Catalog, vb.) "
            "ve son senkronizasyon bilgilerini gösterir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_content_status",
        "description": (
            "İçerik Planlayıcı durumunu döndürür: iş akışı durumuna göre içerik "
            "sayıları (taslak, onay bekleyen, onaylı, zamanlanmış, yayınlanmış) ve "
            "yaklaşan zamanlanmış gönderiler. Sosyal medya içerik takvimi soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_budget_status",
        "description": (
            "En güncel aylık bütçe planını döndürür: dönem, toplam bütçe, hedef, "
            "platform bazlı önerilen dağılım ve beklenen sonuç projeksiyonu. "
            "Bütçe planı / harcama planı soruları için kullan."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_inbox_summary",
        "description": (
            "Sosyal gelen kutusu özetini döndürür: açık/beklemede/çözüldü mesaj "
            "sayıları, kanal ve duygu dağılımı. Müşteri hizmetleri / sosyal mesaj "
            "soruları için kullan."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_executive_summary",
        "description": (
            "Son 30 günün üst düzey yönetici özetini döndürür: toplam harcama, "
            "gelir, ROAS, dönüşüm KPI'ları + doğal dil manşet. CEO/CMO tipi "
            "'pazarlamada genel durum ne' soruları için kullan."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "draft_automation_rule",
        "description": (
            "Kullanıcının tarif ettiği otomasyon kuralı için TASLAK oluşturur. "
            "Veritabanına KAYDETMEZ — kullanıcı Otomasyon UI'dan onaylamalıdır. "
            "Geçerli metrикler: spend, roas, ctr, cpc, cpa, conversions. "
            "Geçerli karşılaştırıcılar: pct_drop, pct_rise, below, above, anomaly. "
            "Geçerli eylemler: alert, notify_email, notify_slack, pause_suggest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Kural adı."},
                "metric": {
                    "type": "string",
                    "description": "İzlenecek metrik: spend | roas | ctr | cpc | cpa | conversions",
                },
                "comparator": {
                    "type": "string",
                    "description": "Koşul: pct_drop | pct_rise | below | above | anomaly",
                },
                "threshold": {
                    "type": "number",
                    "description": "Eşik değeri. pct_* için yüzde (ör. 20 = %20).",
                },
                "action": {
                    "type": "string",
                    "description": "Tetiklenecek eylem: alert | notify_email | notify_slack | pause_suggest",
                },
            },
            "required": ["name", "metric", "comparator", "threshold", "action"],
        },
    },
    {
        "name": "get_subscription_status",
        "description": (
            "Kiracının mevcut abonelik planını ve limitlerini döndürür "
            "(plan adı, durum, veri kaynağı limiti, özellikler)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_top_movers",
        "description": (
            "Seçilen dönemde önceki döneme göre en çok değişen kanalları veya "
            "kampanyaları döndürür (mutlak delta büyüklüğüne göre sıralı). "
            "Hem kazananlar (direction='up') hem kaybedenler (direction='down') dahildir. "
            "Karşılaştırma dönemi, seçilen dönemle aynı uzunluktadır ve hemen öncesindedir. "
            "Tarihler belirtilmezse son 30 gün kullanılır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Dönem başlangıç tarihi (YYYY-MM-DD). Belirtilmezse 30 gün öncesi.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Dönem bitiş tarihi (YYYY-MM-DD). Belirtilmezse bugün.",
                },
                "dimension": {
                    "type": "string",
                    "description": "Gruplama boyutu: 'channel' (varsayılan) veya 'campaign'.",
                    "enum": ["channel", "campaign"],
                },
                "metric": {
                    "type": "string",
                    "description": (
                        "Karşılaştırılacak metrik. "
                        "spend | impressions | clicks | conversions | conversion_value | roas. "
                        "Varsayılan: spend."
                    ),
                    "enum": [
                        "spend", "impressions", "clicks",
                        "conversions", "conversion_value", "roas",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "description": "Döndürülecek maksimum kayıt sayısı (1-20). Varsayılan: 5.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_notifications",
        "description": (
            "Kullanıcının okunmamış/son bildirimlerini döndürür. "
            "İstek öncesinde mevcut içgörülerden yeni bildirimler otomatik olarak üretilir "
            "(gecikmeli üretim). unread_only=true ile yalnızca okunmamışlar listelenir; "
            "limit parametresiyle döndürülecek maksimum bildirim sayısı belirlenir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "unread_only": {
                    "type": "boolean",
                    "description": (
                        "True ise yalnızca okunmamış bildirimler döner. "
                        "Varsayılan: false (tüm son bildirimler)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Döndürülecek maksimum bildirim sayısı (1-50). Varsayılan: 10.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_goal_progress",
        "description": (
            "Hedeflerin ilerleme durumunu (hedefe %, tahmin, durum) döndürür. "
            "Varsayılan olarak kiracının tüm aktif hedeflerini döndürür. "
            "goal_id belirtilirse yalnızca o hedefe odaklanır. "
            "Her hedef için mevcut değer, hedef değer, hedefe yüzde, tahmin, "
            "durum (on_track/at_risk/off_track) ve Türkçe öneri içerir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {
                    "type": "string",
                    "description": (
                        "İlerleme bilgisi istenilen hedefin UUID'si. "
                        "Boş bırakılırsa tüm aktif hedefler döner."
                    ),
                },
            },
            "required": [],
        },
    },
    # ── ACTION tools (v2) ────────────────────────────────────────────────────
    # is_action=True: these tools write to the DB.  Only call them when the
    # user EXPLICITLY asks to create/set something ("kural oluştur", "hedef koy").
    # Always summarise what was created in the assistant reply.
    {
        "name": "create_automation_rule",
        "description": (
            "[EYLEM — DB YAZMA] Kullanıcı açıkça 'kural oluştur', 'uyarı kur' veya "
            "'otomatik kural ekle' gibi bir şey istediğinde bu aracı çağır. "
            "Veritabanına GERÇEK bir otomasyon kuralı yazar. "
            "Gerekli bilgiler eksikse ÖNCE sor; tahmin etme. "
            "Geçerli metrikler: spend, roas, ctr, cpc, cpa, conversions. "
            "Geçerli karşılaştırıcılar: pct_drop, pct_rise, below, above, anomaly. "
            "Geçerli eylemler: alert, notify_email, notify_slack, pause_suggest. "
            "Geçerli kapsam: account, channel, campaign."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Kural adı (kullanıcının belirlediği)."},
                "metric": {
                    "type": "string",
                    "description": "İzlenecek metrik: spend | roas | ctr | cpc | cpa | conversions",
                },
                "comparator": {
                    "type": "string",
                    "description": "Koşul: pct_drop | pct_rise | below | above | anomaly",
                },
                "action": {
                    "type": "string",
                    "description": "Tetiklenecek eylem: alert | notify_email | notify_slack | pause_suggest",
                },
                "scope": {
                    "type": "string",
                    "description": "Kapsam: account | channel | campaign. Varsayılan: account.",
                },
                "scope_filter": {
                    "type": "string",
                    "description": "Kanal anahtarı veya kampanya UUID'si (scope=channel/campaign ise). İsteğe bağlı.",
                },
                "threshold": {
                    "type": "number",
                    "description": "Eşik değeri. pct_* için yüzde (ör. 20 = %20). anomaly için boş bırak.",
                },
                "window_days": {
                    "type": "integer",
                    "description": "Değerlendirme penceresi (gün). Varsayılan: 7.",
                },
            },
            "required": ["name", "metric", "comparator", "action"],
        },
        "is_action": True,
    },
    {
        "name": "create_goal",
        "description": (
            "[EYLEM — DB YAZMA] Kullanıcı açıkça 'hedef koy', 'hedef oluştur' veya "
            "'KPI hedefi ekle' gibi bir şey istediğinde bu aracı çağır. "
            "Veritabanına GERÇEK bir hedef yazar. "
            "Gerekli bilgiler (metric, target_value, period_start, period_end) eksikse ÖNCE sor. "
            "Geçerli metrikler: spend, roas, conversions, conversion_value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Hedef adı."},
                "metric": {
                    "type": "string",
                    "description": "Hedeflenen metrik: spend | roas | conversions | conversion_value",
                },
                "target_value": {
                    "type": "number",
                    "description": "Hedef değeri (sayısal).",
                },
                "period_start": {
                    "type": "string",
                    "description": "Başlangıç tarihi (YYYY-MM-DD).",
                },
                "period_end": {
                    "type": "string",
                    "description": "Bitiş tarihi (YYYY-MM-DD).",
                },
                "channel_filter": {
                    "type": "string",
                    "description": "Kanal anahtarı (ör. google_ads). İsteğe bağlı; boş = tüm kanallar.",
                },
            },
            "required": ["name", "metric", "target_value", "period_start", "period_end"],
        },
        "is_action": True,
    },
    # ── Dalga 77: new module tool specs ─────────────────────────────────────
    {
        "name": "get_funnel_summary",
        "description": (
            "Dönüşüm hunisini (Müşteri Yolculuğu) özetler: her aşamadaki kullanıcı sayısı "
            "(Sayfa Görüntüleme → Ürün Görüntüleme → Sepete Ekleme → Ödeme Başlatma → Satın Alma), "
            "genel dönüşüm oranı ve en büyük düşüş noktasını döndürür. "
            "Son 30 günlük pencere kullanılır. "
            "Huni, müşteri yolculuğu, dönüşüm adımı soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_consent_summary",
        "description": (
            "KVKK Rıza Yönetim Merkezi özetini döndürür: genel rıza oranı, rıza olmadan "
            "atlanan olay sayısı, uyum skoru ve uyum derecesi. "
            "KVKK, rıza, consent, onay oranı soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_benchmark_summary",
        "description": (
            "Kiracının metriklerini Türk e-ticaret sektörü referans aralıklarıyla karşılaştırır. "
            "Her metrik için 'strong' / 'average' / 'weak' konumu ve Türkçe yorum döndürür. "
            "Son 30 günlük pencere kullanılır. "
            "Sektör kıyaslaması, benchmark, rakip ortalama soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_audit_summary",
        "description": (
            "Hesap sağlık taramasını çalıştırır ve 0-100 sağlık skoru, derece "
            "(mukemmel/iyi/orta/zayif), geçen/uyarı/başarısız kontrol sayıları ve "
            "üst sorunları döndürür. "
            "Hesap denetimi, sağlık taraması, hesap sağlığı soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
