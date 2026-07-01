"""Proactive AI Daily Briefing service.

Public API
----------
    generate_briefing(db, tenant_id, as_of_date, *, http_client=None) -> Briefing
    deliver_briefing(db, briefing) -> None

Design
------
``generate_briefing`` is the core entry point.  It assembles data from four
existing services (metrics/copilot_tools aggregation, insights, ads recommendations,
goals) into a single structured ``body`` JSON, then writes a ``Briefing`` row that
is idempotent per (tenant, date): calling it twice for the same date updates the
existing row rather than creating a duplicate.

Headline generation
-------------------
Two paths, mirroring the narrator pattern in narrator.py:

  ClaudeBriefingNarrator (opt-in)
      Calls the Claude API via raw httpx.  Requires ``settings.anthropic_api_key``.
      Falls back to ``TemplateBriefingNarrator`` on any error (missing key,
      network timeout, non-200, JSON parse failure).

  TemplateBriefingNarrator (default, no network)
      Deterministic Turkish headline grounded in the computed numbers and the top
      insight/recommendation so it is always factually anchored.

``deliver_briefing`` routes the headline + one-paragraph summary through the
existing EmailNotifier and SlackNotifier stubs.  No live network calls are made
(the stubs only log).  The delivery is best-effort: failure is logged but does not
raise.

Metric delta computation
------------------------
Reuses the ``_get_performance_summary`` aggregation from copilot_tools, applied to:
  - yesterday   (as_of_date - 1 day)
  - prior day   (as_of_date - 2 days)

Delta percentage = (yesterday - prior) / prior  (0 when prior == 0).
All Decimal arithmetic is done internally; floats appear only at the JSON edge.

Idempotency
-----------
Before writing, the service queries for an existing Briefing on (tenant_id,
briefing_date).  If found, all fields are updated in place and the existing row
is returned.  This makes the task safely re-runnable.

Tenant isolation
----------------
Every DB query is scoped to tenant_id.  No cross-tenant data is accessible.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.briefing import Briefing

logger = logging.getLogger(__name__)


# ── Internal decimal helper ───────────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


# ── Performance delta helper ──────────────────────────────────────────────────


def _aggregate_one_day(
    db: Session,
    tenant_id: uuid.UUID,
    day: date,
) -> dict[str, Decimal]:
    """Return {spend, conversions, conversion_value} totals for a single day.

    Reuses the same SQL pattern as copilot_tools._get_performance_summary but
    scoped to a single calendar date so we avoid re-importing that function and
    preserving the Decimal boundary.
    """
    from ayaz.models.analytics import FactDailyMetrics
    from ayaz.services.metrics import roas as _roas

    row = db.execute(
        select(
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        ).where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key == day,
        )
    ).mappings().one()

    spend = _d(row["spend"])
    conversions = _d(row["conversions"])
    conv_value = _d(row["conversion_value"])
    roas_val = _roas(conv_value, spend)

    return {
        "spend": spend,
        "conversions": conversions,
        "conversion_value": conv_value,
        "roas": roas_val,
    }


def _pct_delta(current: Decimal, prior: Decimal) -> float:
    """Percentage change from prior to current; 0.0 when prior is zero."""
    if prior == Decimal(0):
        return 0.0
    return float((current - prior) / prior)


def _compute_performance_delta(
    db: Session,
    tenant_id: uuid.UUID,
    yesterday: date,
    prior_day: date,
) -> dict:
    """Return the performance_delta section of the briefing body."""
    yest = _aggregate_one_day(db, tenant_id, yesterday)
    prior = _aggregate_one_day(db, tenant_id, prior_day)

    return {
        "yesterday": {
            "spend": float(yest["spend"]),
            "conversions": float(yest["conversions"]),
            "roas": float(yest["roas"]),
        },
        "prior_day": {
            "spend": float(prior["spend"]),
            "conversions": float(prior["conversions"]),
            "roas": float(prior["roas"]),
        },
        "delta": {
            "spend_pct": _pct_delta(yest["spend"], prior["spend"]),
            "conversions_pct": _pct_delta(yest["conversions"], prior["conversions"]),
            "roas_pct": _pct_delta(yest["roas"], prior["roas"]),
        },
    }


# ── Insight section helper ────────────────────────────────────────────────────


def _top_insights(db: Session, tenant_id: uuid.UUID, limit: int = 3) -> list[dict]:
    """Return up to ``limit`` highest-score new/seen Insight rows for the tenant."""
    from sqlalchemy import desc

    from ayaz.models.insights import Insight

    rows = db.scalars(
        select(Insight)
        .where(
            Insight.tenant_id == tenant_id,
            Insight.status.in_(["new", "seen"]),
        )
        .order_by(desc(Insight.score))
        .limit(limit)
    ).all()

    return [
        {
            "id": str(r.id),
            "category": r.category,
            "severity": r.severity,
            "title": r.title,
            "metric": r.metric,
            "channel": r.channel,
            "score": r.score,
            "period_start": str(r.period_start),
            "period_end": str(r.period_end),
        }
        for r in rows
    ]


# ── Recommendation section helper ─────────────────────────────────────────────


def _top_recommendation(
    db: Session,
    tenant_id: uuid.UUID,
    as_of_date: date,
) -> dict | None:
    """Return the highest-score campaign recommendation or None."""
    from datetime import timedelta

    from ayaz.services.ads import campaign_recommendations

    date_from = as_of_date - timedelta(days=29)
    recs = campaign_recommendations(db, tenant_id, date_from, as_of_date)
    if not recs:
        return None
    top = recs[0]
    return {
        "campaign_id": top["campaign_id"],
        "campaign_name": top["campaign_name"],
        "channel": top["channel"],
        "category": top["category"],
        "severity": top["severity"],
        "score": top["score"],
        "message": top["message"],
        "suggested_action": top["suggested_action"],
    }


# ── Goals status section helper ───────────────────────────────────────────────


def _goals_status(
    db: Session,
    tenant_id: uuid.UUID,
    as_of_date: date,
) -> list[dict]:
    """Return pacing status for all active goals of the tenant."""
    from ayaz.services.goals import compute_progress, list_goals

    goals = list_goals(db, tenant_id, active_only=True)
    result = []
    for goal in goals:
        try:
            progress = compute_progress(db, goal, as_of_date)
            result.append({
                "goal_id": str(goal.id),
                "name": goal.name,
                "metric": goal.metric,
                "target_value": float(goal.target_value),
                "current_value": progress.current_value,
                "pct_to_target": progress.pct_to_target,
                "forecast_value": progress.forecast_value,
                "status": progress.status,
                "recommendation": progress.recommendation,
            })
        except Exception as exc:
            logger.warning(
                "[briefing] compute_progress failed for goal=%s: %s",
                goal.id,
                exc,
            )
    return result


# ── Headline narrators ────────────────────────────────────────────────────────


def _build_deterministic_headline(
    performance_delta: dict,
    top_insights: list[dict],
    top_recommendation: dict | None,
    goals_status: list[dict],
) -> str:
    """Return a Turkish headline grounded in the actual computed numbers.

    The headline picks the most salient signal in priority order:
      1. If ROAS dropped by >= 10%: mention it with the % and top recommendation.
      2. Else if spend spiked >= 20%: mention it.
      3. Else if a critical insight exists: reference its title.
      4. Else if an off_track goal exists: mention it.
      5. Fallback: overall performance summary.
    """
    delta = performance_delta.get("delta", {})
    roas_pct = delta.get("roas_pct", 0.0)
    spend_pct = delta.get("spend_pct", 0.0)
    yest = performance_delta.get("yesterday", {})
    yest_roas = yest.get("roas", 0.0)
    yest_spend = yest.get("spend", 0.0)

    # 1. ROAS drop
    if roas_pct <= -0.10:
        drop_display = abs(round(roas_pct * 100, 1))
        rec_part = ""
        if top_recommendation:
            action = top_recommendation.get("suggested_action", "")
            campaign = top_recommendation.get("campaign_name", "")
            rec_part = f" En kritik kampanya: '{campaign}'. Öneri: {action}."
        return (
            f"Dun ROAS %{drop_display} dustu (simdiki: {round(yest_roas, 2)}x)."
            f"{rec_part}"
        )

    # 2. Spend spike
    if spend_pct >= 0.20:
        spike_display = round(spend_pct * 100, 1)
        return (
            f"Dun harcama %{spike_display} artti "
            f"(toplam: {round(yest_spend, 2)}). Butce sinirlari kontrol edilmeli."
        )

    # 3. Critical insight
    critical = next(
        (i for i in top_insights if i.get("severity") == "critical"), None
    )
    if critical:
        return critical["title"]

    # 4. Off-track goal
    off_track = next(
        (g for g in goals_status if g.get("status") == "off_track"), None
    )
    if off_track:
        name = off_track.get("name", "hedef")
        pct = round(off_track.get("pct_to_target", 0) * 100, 1)
        return (
            f"'{name}' hedefinin %{pct}'ine ulasildi — hedefe yetismek icin"
            f" hizlanmak gerekiyor."
        )

    # 5. Fallback: generic positive/neutral summary
    if roas_pct >= 0:
        roas_display = round(abs(roas_pct * 100), 1)
        if roas_pct > 0:
            return (
                f"Dun performans istikrardi: ROAS %{roas_display} yukseldi"
                f" ({round(yest_roas, 2)}x). Devam edin!"
            )
        return (
            f"Dun performans: ROAS {round(yest_roas, 2)}x, "
            f"harcama {round(yest_spend, 2)}. Dikkat gerektiren sinyal yok."
        )

    drop_display = abs(round(roas_pct * 100, 1))
    return (
        f"Dun ROAS %{drop_display} geriledi ({round(yest_roas, 2)}x); "
        f"kampanya ayarlarinizi gozden gecirin."
    )


class _TemplateBriefingNarrator:
    """Deterministic Turkish headline — no network, always available."""

    def generate(self, body: dict) -> str:
        return _build_deterministic_headline(
            performance_delta=body.get("performance_delta", {}),
            top_insights=body.get("top_insights", []),
            top_recommendation=body.get("top_recommendation"),
            goals_status=body.get("goals_status", []),
        )


class _ClaudeBriefingNarrator:
    """Optional Claude-API narrator.  Falls back to template on any error."""

    DEFAULT_MODEL = "claude-opus-4-8"

    def __init__(self, api_key: str, http_client: Any = None) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._fallback = _TemplateBriefingNarrator()

    def generate(self, body: dict) -> str:
        try:
            return self._call_claude(body)
        except Exception as exc:
            logger.warning(
                "[ClaudeBriefingNarrator] API call failed (%s) — using template", exc
            )
            return self._fallback.generate(body)

    def _call_claude(self, body: dict) -> str:
        import httpx

        delta = body.get("performance_delta", {}).get("delta", {})
        top_rec = body.get("top_recommendation") or {}
        top_insights = body.get("top_insights", [])
        goals = body.get("goals_status", [])

        data_summary = json.dumps(
            {
                "delta": delta,
                "top_insights": top_insights[:2],
                "top_recommendation": top_rec,
                "goals": goals[:3],
            },
            ensure_ascii=False,
            default=str,
        )

        prompt = (
            "Sen bir dijital pazarlama analisti asistanisın. "
            "Asagidaki gunluk performans verilerini kullanarak "
            "tek bir Turkce cumle yaz — maksimum 200 karakter. "
            "Cumle somut sayilar icermeli ve en onemli sinyali vurgulamali.\n\n"
            f"Veriler: {data_summary}\n\n"
            "Yanit yalnizca o tek Turkce cumlesi olsun, baska hicbir sey ekleme."
        )

        payload = {
            "model": self.DEFAULT_MODEL,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        client = self._http_client
        if client is not None:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=20.0,
            )
        else:
            with httpx.Client() as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=20.0,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:200]}"
            )

        return resp.json()["content"][0]["text"].strip()


def _pick_narrator(http_client: Any = None) -> _TemplateBriefingNarrator | _ClaudeBriefingNarrator:
    """Return a Claude narrator when an API key is configured, else template."""
    try:
        from ayaz.config import settings

        if settings.anthropic_api_key:
            return _ClaudeBriefingNarrator(
                api_key=settings.anthropic_api_key,
                http_client=http_client,
            )
    except Exception:
        pass
    return _TemplateBriefingNarrator()


# ── Delivery ──────────────────────────────────────────────────────────────────


def deliver_briefing(db: Session, briefing: Briefing) -> None:
    """Route the briefing headline + summary to Email and Slack notifier stubs.

    Uses the same notifier stubs as notifications.py.  Both notifiers only log
    (no live network).  Failures are caught and logged — delivery is best-effort.

    The function fabricates a minimal sentinel ``AlertRule``-like object accepted
    by the existing stub ``deliver()`` signatures (which expect ``rule.name`` and
    ``rule.id``).  A dataclass is used to avoid importing or depending on the
    AlertRule ORM for a stub call.
    """
    from dataclasses import dataclass

    from ayaz.services.notifications import EmailNotifier, SlackNotifier

    @dataclass
    class _StubRule:
        name: str
        id: str
        delivery: str = "email"
        destination: str = ""
        is_active: bool = True
        metric: str = "spend"
        channel_filter: str | None = None

    @dataclass
    class _BriefingAsInsight:
        """Minimal duck-typed object that satisfies Notifier.deliver() signature."""

        id: str
        title: str
        body: str
        severity: str = "info"
        category: str = "briefing"
        metric: str = "roas"
        channel: str | None = None
        period_start: str = ""
        period_end: str = ""

    body_text = briefing.headline
    stub_insight = _BriefingAsInsight(
        id=str(briefing.id),
        title=f"[Gunluk Brifing] {briefing.briefing_date}",
        body=body_text,
        period_start=briefing.briefing_date,
        period_end=briefing.briefing_date,
    )
    stub_rule = _StubRule(
        name="daily_briefing",
        id="briefing-stub",
    )

    for Notifier in (EmailNotifier, SlackNotifier):
        try:
            Notifier().deliver("briefing-stub-destination", stub_insight, stub_rule)
        except Exception as exc:
            logger.warning("[briefing] deliver_briefing notifier error: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────


def generate_briefing(
    db: Session,
    tenant_id: uuid.UUID,
    as_of_date: date,
    *,
    http_client: Any = None,
) -> Briefing:
    """Generate (or update) the daily Turkish briefing for the tenant.

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    as_of_date:
        The date being reported on.  ``yesterday`` for the briefing is
        ``as_of_date - 1 day``; ``prior_day`` is ``as_of_date - 2 days``.
        Typically callers pass ``date.today()`` so the briefing covers yesterday
        vs the day before.
    http_client:
        Optional httpx-compatible client for the Claude API call (used in tests
        to avoid live network).  When None, a real httpx.Client is used.

    Returns
    -------
    Briefing
        The newly created or updated Briefing ORM row (flushed, not committed).
        The caller (task or API endpoint) is responsible for the commit.

    Idempotency
    -----------
    If a Briefing for (tenant_id, as_of_date) already exists, all its mutable
    fields are updated in place and the existing row is returned.  No duplicate
    rows are created.
    """
    briefing_date_str = as_of_date.isoformat()
    yesterday = as_of_date - timedelta(days=1)
    prior_day = as_of_date - timedelta(days=2)

    logger.info(
        "[briefing] Generating for tenant=%s as_of=%s",
        tenant_id,
        as_of_date,
    )

    # ── Assemble body sections ─────────────────────────────────────────────
    try:
        performance_delta = _compute_performance_delta(
            db, tenant_id, yesterday, prior_day
        )
    except Exception as exc:
        logger.warning("[briefing] performance_delta failed: %s", exc)
        performance_delta = {
            "yesterday": {"spend": 0.0, "conversions": 0.0, "roas": 0.0},
            "prior_day": {"spend": 0.0, "conversions": 0.0, "roas": 0.0},
            "delta": {"spend_pct": 0.0, "conversions_pct": 0.0, "roas_pct": 0.0},
        }

    try:
        insights = _top_insights(db, tenant_id, limit=3)
    except Exception as exc:
        logger.warning("[briefing] top_insights failed: %s", exc)
        insights = []

    try:
        top_rec = _top_recommendation(db, tenant_id, as_of_date)
    except Exception as exc:
        logger.warning("[briefing] top_recommendation failed: %s", exc)
        top_rec = None

    try:
        goals = _goals_status(db, tenant_id, yesterday)
    except Exception as exc:
        logger.warning("[briefing] goals_status failed: %s", exc)
        goals = []

    body = {
        "performance_delta": performance_delta,
        "top_insights": insights,
        "top_recommendation": top_rec,
        "goals_status": goals,
    }

    # ── Generate headline ──────────────────────────────────────────────────
    narrator = _pick_narrator(http_client=http_client)
    try:
        headline = narrator.generate(body)
    except Exception as exc:
        logger.warning("[briefing] narrator failed: %s — using template", exc)
        headline = _TemplateBriefingNarrator().generate(body)

    # ── Upsert ────────────────────────────────────────────────────────────
    existing = db.scalar(
        select(Briefing).where(
            Briefing.tenant_id == tenant_id,
            Briefing.briefing_date == briefing_date_str,
        )
    )

    if existing is not None:
        existing.headline = headline
        existing.body = body
        db.flush()
        logger.info("[briefing] Updated existing briefing id=%s", existing.id)
        return existing

    briefing = Briefing(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        briefing_date=briefing_date_str,
        headline=headline,
        body=body,
    )
    db.add(briefing)
    db.flush()
    logger.info("[briefing] Created new briefing id=%s", briefing.id)
    return briefing
