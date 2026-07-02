"""Komuta Merkezi (Command Center) service — tenant-scoped aggregation.

build_command_center(db, tenant_id) -> dict
-------------------------------------------
Assembles a single-screen "what needs attention now" snapshot for the
current tenant by reusing existing copilot_tools functions.  Read-only;
no data is written.

Return shape
------------
{
  "headline": str,
  "kpis": {
    "spend": float, "revenue": float, "roas": float, "conversions": float,
    "deltas": {
      "spend_pct": float|None, "revenue_pct": float|None,
      "roas_pct": float|None, "conversions_pct": float|None
    }
  },
  "attention": [
    { "severity": "critical"|"warning"|"info",
      "title": str, "detail": str, "module": str, "link": str }
  ],
  "modules": {
    "budget":   {"has_plan": bool, "period_month": str|None,
                 "pace_pct": float|None, "pace_status": str|None},
    "inbox":    {"total": int, "open": int, "pending": int, "negative": int},
    "content":  {"draft": int, "pending_approval": int, "scheduled": int},
    "goals":    {"total": int, "at_risk": int},
    "insights": {"critical": int, "warning": int},
    "recommendations": {"open": int, "high_impact_open": int, "total": int},
    "consent":  {"score": int|None, "grade": str|None,
                 "consent_rate_pct": float|None},
    "funnel":   {"overall_conversion_pct": float|None,
                 "biggest_dropoff_label": str|None}
  }
}
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Attention item severity ordering ──────────────────────────────────────────
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_ATTENTION_CAP = 8


# ── At-risk goal detection ─────────────────────────────────────────────────────

_ON_TRACK_STATUSES: frozenset[str] = frozenset(
    {"on_track", "ahead", "yolunda", "completed", "tamamlandi", "tamamlandı"}
)


def _is_at_risk(goal: dict) -> bool:
    """Return True when a goal should be counted as at-risk.

    A goal is at-risk when:
    - pct_to_target < 100 (not yet achieved), AND
    - status is not a known "good" status.

    This is intentionally defensive: unexpected/unknown status values are
    treated as at-risk so we never under-report risk.
    """
    status = (goal.get("status") or "").lower().strip()
    pct = goal.get("pct_to_target")
    try:
        pct_float = float(pct) if pct is not None else 0.0
    except (TypeError, ValueError):
        pct_float = 0.0
    if pct_float >= 100:
        return False
    return status not in _ON_TRACK_STATUSES


def _goal_with_pct(goal: dict) -> dict:
    """Normalize a goal-service dict (0..1+ ratio) to the percent scale
    ``_is_at_risk`` expects."""
    try:
        ratio = float(goal.get("pct_to_target") or 0)
    except (TypeError, ValueError):
        ratio = 0.0
    return {**goal, "pct_to_target": ratio * 100}


# ── Budget pacing helper ───────────────────────────────────────────────────────


def _get_current_month_plan(
    db: Session,
    tenant_id: uuid.UUID,
    current_month: str,
) -> Any | None:
    """Return the BudgetPlan for the current UTC month, or None."""
    from sqlalchemy import select

    from ayaz.models.budget import BudgetPlan

    return db.scalar(
        select(BudgetPlan)
        .where(
            BudgetPlan.tenant_id == tenant_id,
            BudgetPlan.period_month == current_month,
        )
        .order_by(BudgetPlan.created_at.desc())
    )


# ── Attention synthesis ────────────────────────────────────────────────────────


def _build_attention(
    insights_data: dict,
    inbox_data: dict,
    content_data: dict,
    goals_data: dict,
    budget_actuals: dict | None,
) -> list[dict]:
    """Synthesize the attention list from module data.

    Priority rules (applied in declaration order; sorted critical→warning→info
    at the end before the cap):

    1. CRITICAL insights  → severity "critical", module "insights"   (top 3)
    2. Negative inbox     → severity "warning",  module "inbox"
    3. Open inbox (no neg)→ severity "info",     module "inbox"
    4. pending_approval   → severity "info",     module "content"
    5. At-risk goals      → severity "warning",  module "goals"
    6. Budget pacing gap  → severity "warning",  module "budget"
    7. WARNING insights   → severity "info",     module "insights"   (top 2)
    """
    items: list[dict] = []

    # ── 1. Critical insights → attention "critical" (top 3) ──────────────────
    critical_insights = [
        i for i in (insights_data.get("insights") or [])
        if (i.get("severity") or "").lower() == "critical"
    ]
    for ins in critical_insights[:3]:
        items.append({
            "severity": "critical",
            "title": ins.get("title") or "Kritik uyarı",
            "detail": ins.get("body") or ins.get("title") or "",
            "module": "insights",
            "link": "/insights",
        })

    # ── 2 & 3. Inbox negative / open ─────────────────────────────────────────
    by_sentiment = inbox_data.get("by_sentiment") or {}
    negative_count = int(by_sentiment.get("negative") or 0)
    open_count = int(inbox_data.get("open") or 0)

    if negative_count > 0:
        items.append({
            "severity": "warning",
            "title": f"{negative_count} olumsuz mesaj yanıt bekliyor",
            "detail": (
                f"Gelen kutusunda {negative_count} olumsuz duygu algılanan mesaj "
                "henüz yanıtlanmadı."
            ),
            "module": "inbox",
            "link": "/inbox",
        })
    elif open_count > 0:
        items.append({
            "severity": "info",
            "title": f"{open_count} açık müşteri mesajı",
            "detail": f"Gelen kutusunda {open_count} yanıt bekleyen açık mesaj var.",
            "module": "inbox",
            "link": "/inbox",
        })

    # ── 4. Content pending approval ───────────────────────────────────────────
    pending_approval = int(content_data.get("pending_approval") or 0)
    if pending_approval > 0:
        items.append({
            "severity": "info",
            "title": f"{pending_approval} içerik onay bekliyor",
            "detail": (
                f"{pending_approval} içerik, yayınlanmadan önce onay sürecini bekliyor."
            ),
            "module": "content",
            "link": "/content",
        })

    # ── 5. At-risk goals ──────────────────────────────────────────────────────
    goals_list = goals_data.get("goals") or []
    at_risk_count = sum(1 for g in goals_list if _is_at_risk(_goal_with_pct(g)))
    if at_risk_count > 0:
        items.append({
            "severity": "warning",
            "title": f"{at_risk_count} hedef risk altında",
            "detail": (
                f"{at_risk_count} hedef hedefe ulaşmakta geride veya risk altında."
            ),
            "module": "goals",
            "link": "/goals",
        })

    # ── 6. Budget pacing ──────────────────────────────────────────────────────
    if budget_actuals is not None:
        totals = budget_actuals.get("totals") or {}
        pace_pct = totals.get("pace_pct")
        time_pace_pct = totals.get("time_pace_pct")
        if pace_pct is not None and time_pace_pct is not None:
            try:
                diff = abs(float(pace_pct) - float(time_pace_pct))
            except (TypeError, ValueError):
                diff = 0.0
            if diff > 15:
                notes = budget_actuals.get("notes") or []
                note_text = notes[0] if notes else (
                    f"Bütçe temposu (%{pace_pct}) ile zaman temposu (%{time_pace_pct}) "
                    "arasında önemli fark var."
                )
                items.append({
                    "severity": "warning",
                    "title": "Bütçe pacing uyarısı",
                    "detail": note_text,
                    "module": "budget",
                    "link": "/planning",
                })

    # ── 7. Warning insights → attention "info" (top 2) ───────────────────────
    warning_insights = [
        i for i in (insights_data.get("insights") or [])
        if (i.get("severity") or "").lower() == "warning"
    ]
    for ins in warning_insights[:2]:
        items.append({
            "severity": "info",
            "title": ins.get("title") or "Uyarı",
            "detail": ins.get("body") or ins.get("title") or "",
            "module": "insights",
            "link": "/insights",
        })

    # ── Sort: critical → warning → info; then cap ────────────────────────────
    items.sort(key=lambda x: _SEVERITY_ORDER.get(x.get("severity", "info"), 2))
    return items[:_ATTENTION_CAP]


# ── Modules block builder ─────────────────────────────────────────────────────


def _build_modules(
    budget_data: dict,
    budget_actuals: dict | None,
    inbox_data: dict,
    content_data: dict,
    goals_data: dict,
    insights_data: dict,
) -> dict:
    """Assemble the per-module status summary block."""
    # Budget
    has_plan = bool(budget_data.get("has_plan"))
    period_month = budget_data.get("period_month") if has_plan else None
    pace_pct: float | None = None
    pace_status: str | None = None

    if budget_actuals is not None:
        # Prefer the current-month plan's period for the card (pace is for it).
        period_month = budget_actuals.get("period_month") or period_month
        has_plan = True
        totals = budget_actuals.get("totals") or {}
        raw_pace = totals.get("pace_pct")
        raw_time = totals.get("time_pace_pct")
        if raw_pace is not None:
            try:
                pace_pct = float(raw_pace)
            except (TypeError, ValueError):
                pace_pct = None
        if pace_pct is not None and raw_time is not None:
            try:
                time_p = float(raw_time)
            except (TypeError, ValueError):
                time_p = None
            if time_p is not None:
                diff = pace_pct - time_p
                if diff > 5:
                    pace_status = "ahead"
                elif diff < -5:
                    pace_status = "behind"
                else:
                    pace_status = "on_track"

    # Inbox
    by_sentiment = inbox_data.get("by_sentiment") or {}
    inbox_block = {
        "total": int(inbox_data.get("total") or 0),
        "open": int(inbox_data.get("open") or 0),
        "pending": int(inbox_data.get("pending") or 0),
        "negative": int(by_sentiment.get("negative") or 0),
    }

    # Content
    content_block = {
        "draft": int(content_data.get("draft") or 0),
        "pending_approval": int(content_data.get("pending_approval") or 0),
        "scheduled": int(content_data.get("scheduled") or 0),
    }

    # Goals
    goals_list = goals_data.get("goals") or []
    at_risk_count = sum(1 for g in goals_list if _is_at_risk(_goal_with_pct(g)))
    goals_block = {
        "total": len(goals_list),
        "at_risk": at_risk_count,
    }

    # Insights counts by severity
    all_insights = insights_data.get("insights") or []
    crit_count = sum(
        1 for i in all_insights if (i.get("severity") or "").lower() == "critical"
    )
    warn_count = sum(
        1 for i in all_insights if (i.get("severity") or "").lower() == "warning"
    )

    return {
        "budget": {
            "has_plan": has_plan,
            "period_month": period_month,
            "pace_pct": pace_pct,
            "pace_status": pace_status,
        },
        "inbox": inbox_block,
        "content": content_block,
        "goals": goals_block,
        "insights": {
            "critical": crit_count,
            "warning": warn_count,
        },
    }


# ── KPI extractor ─────────────────────────────────────────────────────────────


def _extract_kpis(exec_summary: dict) -> dict:
    """Extract the KPI block from the executive summary."""
    raw = exec_summary.get("kpis") or {}
    raw_deltas = raw.get("deltas") or {}
    return {
        "spend": float(raw.get("spend") or 0),
        "revenue": float(raw.get("revenue") or 0),
        "roas": float(raw.get("roas") or 0),
        "conversions": float(raw.get("conversions") or 0),
        "deltas": {
            "spend_pct": _to_float_or_none(raw_deltas.get("spend_pct")),
            "revenue_pct": _to_float_or_none(raw_deltas.get("revenue_pct")),
            "roas_pct": _to_float_or_none(raw_deltas.get("roas_pct")),
            "conversions_pct": _to_float_or_none(raw_deltas.get("conversions_pct")),
        },
    }


def _to_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Public entry point ────────────────────────────────────────────────────────


def build_command_center(db: Session, tenant_id: uuid.UUID) -> dict:
    """Build the Command Center snapshot for the given tenant.

    Calls existing copilot_tools functions (all read-only) and synthesises
    their outputs into a single prioritised, role-aware summary dict.

    Tenant isolation: every underlying function receives tenant_id and
    filters strictly by it — no cross-tenant data can leak.
    """
    from ayaz.services.copilot_tools import (
        _get_budget_status,
        _get_content_status,
        _get_executive_summary,
        _get_inbox_summary,
        _get_insights,
        _get_goal_progress,
    )
    from ayaz.services.budget_planner import plan_actuals

    # ── 1. Gather data from reused functions ──────────────────────────────────
    try:
        exec_summary = _get_executive_summary(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_executive_summary failed", exc_info=True)
        exec_summary = {}

    try:
        budget_data = _get_budget_status(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_budget_status failed", exc_info=True)
        budget_data = {"has_plan": False}

    try:
        inbox_data = _get_inbox_summary(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_inbox_summary failed", exc_info=True)
        inbox_data = {
            "total": 0, "open": 0, "pending": 0, "resolved": 0,
            "by_sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "by_channel": {}, "by_kind": {},
        }

    try:
        content_data = _get_content_status(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_content_status failed", exc_info=True)
        content_data = {
            "total": 0, "by_status": {}, "draft": 0, "pending_approval": 0,
            "approved": 0, "scheduled": 0, "published": 0, "upcoming": [],
        }

    try:
        goals_data = _get_goal_progress(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_goal_progress failed", exc_info=True)
        goals_data = {"goals": []}

    try:
        insights_data = _get_insights(db, tenant_id)
    except Exception:
        logger.warning("build_command_center: _get_insights failed", exc_info=True)
        insights_data = {"count": 0, "insights": []}

    # ── 2. Budget pacing for current month ────────────────────────────────────
    budget_actuals: dict | None = None
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    # Look up the CURRENT-month plan directly (it may differ from the latest
    # plan returned by _get_budget_status, e.g. a next-month plan exists too).
    try:
        plan = _get_current_month_plan(db, tenant_id, current_month)
        if plan is not None:
            budget_actuals = plan_actuals(db, tenant_id, plan)
    except Exception:
        logger.warning(
            "build_command_center: plan_actuals failed", exc_info=True
        )

    # ── 3. Build KPIs block ───────────────────────────────────────────────────
    kpis = _extract_kpis(exec_summary)

    # ── 4. Build attention list ───────────────────────────────────────────────
    attention = _build_attention(
        insights_data=insights_data,
        inbox_data=inbox_data,
        content_data=content_data,
        goals_data=goals_data,
        budget_actuals=budget_actuals,
    )

    # ── 5. Build modules block ────────────────────────────────────────────────
    modules = _build_modules(
        budget_data=budget_data,
        budget_actuals=budget_actuals,
        inbox_data=inbox_data,
        content_data=content_data,
        goals_data=goals_data,
        insights_data=insights_data,
    )

    # ── 5b. Öneriler (Recommendations) module block ───────────────────────────
    try:
        from ayaz.services.recommendations import build_recommendation_feed
        rec_feed = build_recommendation_feed(db, tenant_id)
        rec_summary = rec_feed.get("summary") or {}
        modules["recommendations"] = {
            "open": int(rec_summary.get("open") or 0),
            "high_impact_open": int(rec_summary.get("high_impact_open") or 0),
            "total": int(rec_summary.get("total") or 0),
        }
    except Exception:
        logger.warning(
            "build_command_center: build_recommendation_feed failed", exc_info=True
        )
        modules["recommendations"] = {
            "open": 0,
            "high_impact_open": 0,
            "total": 0,
        }

    # ── 5c. KVKK Uyum (Consent) module block ─────────────────────────────────
    try:
        from ayaz.services.consent_center import build_consent_center
        consent_data = build_consent_center(db, tenant_id)
        consent_summary = consent_data.get("summary") or {}
        consent_compliance = consent_data.get("compliance") or {}
        modules["consent"] = {
            "score": consent_compliance.get("score"),
            "grade": consent_compliance.get("grade"),
            "consent_rate_pct": consent_summary.get("consent_rate_pct"),
        }
    except Exception:
        logger.warning(
            "build_command_center: build_consent_center failed", exc_info=True
        )
        modules["consent"] = {
            "score": None,
            "grade": None,
            "consent_rate_pct": None,
        }

    # ── 5d. Dönüşüm Hunisi (Funnel) module block ──────────────────────────────
    try:
        from ayaz.services.funnel import build_funnel
        funnel_data = build_funnel(db, tenant_id)
        biggest_dropoff = funnel_data.get("biggest_dropoff")
        if biggest_dropoff is not None:
            from_label = biggest_dropoff.get("from_label") or ""
            to_label = biggest_dropoff.get("to_label") or ""
            biggest_dropoff_label: str | None = f"{from_label} → {to_label}"
        else:
            biggest_dropoff_label = None
        modules["funnel"] = {
            "overall_conversion_pct": funnel_data.get("overall_conversion_pct"),
            "biggest_dropoff_label": biggest_dropoff_label,
        }
    except Exception:
        logger.warning(
            "build_command_center: build_funnel failed", exc_info=True
        )
        modules["funnel"] = {
            "overall_conversion_pct": None,
            "biggest_dropoff_label": None,
        }

    # ── 6. Headline (fall back to Turkish if executive summary is empty) ──────
    headline: str = exec_summary.get("headline") or ""
    if not headline:
        headline = "Veriler yükleniyor — yeterli veri mevcut değil."

    return {
        "headline": headline,
        "kpis": kpis,
        "attention": attention,
        "modules": modules,
    }
