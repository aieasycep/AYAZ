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
from ayaz.services.metrics import compute_derived_metrics


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
        # Fetch the source to get last_synced_at and item_count
        source = db.get(FeedSource, ch.feed_source_id) if ch.feed_source_id else None
        channels.append({
            "id": str(ch.id),
            "name": ch.name,
            "channel_type": ch.channel_type,
            "output_format": ch.output_format,
            "last_synced_at": source.last_synced_at if source else None,
            "item_count": source.item_count if source else 0,
        })

    return {"count": len(channels), "channels": channels}


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


# ── Tool dispatch table ────────────────────────────────────────────────────────

_TOOLS: dict[str, Any] = {
    "get_performance_summary": _get_performance_summary,
    "get_timeseries": _get_timeseries,
    "list_campaigns": _list_campaigns,
    "get_recommendations": _get_recommendations,
    "get_insights": _get_insights,
    "get_feed_channels": _get_feed_channels,
    "draft_automation_rule": _draft_automation_rule,
    "get_subscription_status": _get_subscription_status,
}


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
        return {"error": str(exc)}


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
]
