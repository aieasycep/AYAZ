"""Root-cause analysis and one-click fix suggestions for Insights — M11 v2.

Public API
----------
    suggested_fixes_for_insight(db, tenant_id, insight) -> FixSuggestion
    apply_fix(db, tenant_id, insight, action_type, payload) -> ApplyResult

Design
------
For each insight category (roas_drop, zero_conversions, spend_spike, ctr_drop,
cpc_rise, anomaly) this module produces:

1. root_cause — a Turkish-language explanation grounded in the insight.data
   field (actual measured values, not fabricated text).

2. fixes — a list of one-click fix actions, each with:
   {label, action_type, payload}
   where action_type is one of:
     "create_automation_rule" — calls automation.create_rule_from_copilot
     "create_goal"            — calls goals.create_goal
     "view_campaign"          — navigational hint (no server action)
     "dismiss_insight"        — marks the insight dismissed

apply_fix() executes a safe action (create rule, create goal, dismiss).  It
never touches live ad-platform APIs.

Tenant isolation
----------------
Every operation filters by tenant_id.  Entity IDs in payloads are validated
against the tenant before being used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ayaz.models.insights import Insight
from ayaz.services.trformat import tr_num, tr_pct


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class FixAction:
    """A single one-click fix action."""

    label: str
    """Human-readable Turkish button label, e.g. 'Kural Oluştur'."""

    action_type: str
    """One of: create_automation_rule | create_goal | view_campaign | dismiss_insight"""

    payload: dict[str, Any]
    """Ready-to-apply parameters for the action."""


@dataclass
class FixSuggestion:
    """Root-cause explanation + list of one-click fix actions for one Insight."""

    insight_id: uuid.UUID
    root_cause: str
    """Turkish-language explanation grounded in the insight's measured data."""

    fixes: list[FixAction] = field(default_factory=list)


@dataclass
class ApplyResult:
    """Result returned after executing a fix action."""

    action_type: str
    success: bool
    message: str
    """Turkish confirmation or error message."""

    entity_id: str | None = None
    """UUID of the created entity (rule or goal), if any."""

    entity_type: str | None = None
    """'automation_rule' | 'goal' | None"""


# ── Root-cause templates (Turkish, data-grounded) ─────────────────────────────


def _channel_display(channel: str | None) -> str:
    """Slug → human-readable label for user-facing text (meta_ads → Meta Ads)."""
    if not channel:
        return "belirtilmemiş kanal"
    return channel.replace("_", " ").title()


def _num(value: object, decimals: int = 2) -> str:
    """TR-format a possibly-missing numeric value; '?' when not a number."""
    if isinstance(value, (int, float)):
        return tr_num(float(value), decimals)
    return "?"


def _root_cause_roas_drop(insight: Insight) -> str:
    data = insight.data or {}
    current = data.get("current_roas")
    prior = data.get("prior_roas")
    pct = data.get("pct_drop", 0)
    channel = _channel_display(insight.channel)
    spend = data.get("current_spend")
    cv = data.get("current_conversion_value")

    try:
        pct_display = tr_pct(pct * 100)
    except (TypeError, ValueError):
        pct_display = "?"

    return (
        f"{channel} kanalında ROAS {pct_display} oranında düştü "
        f"(önceki dönem: {_num(prior)}x → güncel: {_num(current)}x). "
        f"Bu dönemde {_num(spend)} birim harcamayla yalnızca {_num(cv)} birim dönüşüm değeri elde edildi. "
        "Olası nedenler: reklam yorgunluğu (aynı hedef kitleye çok uzun süre gösterim), "
        "açılış sayfası dönüşüm sorunları, yanlış hedefleme veya artan rekabet maliyetleri. "
        "Dönüşüm izleme pikseli çalışıyor mu kontrol edin."
    )


def _root_cause_zero_conversions(insight: Insight) -> str:
    data = insight.data or {}
    spend = data.get("spend", 0)
    channel = _channel_display(insight.channel)
    period_days = (
        (insight.period_end - insight.period_start).days + 1
        if insight.period_end and insight.period_start
        else "?"
    )
    return (
        f"{channel} kanalı son {period_days} günde {_num(spend)} birim harcama yaptı "
        "ancak hiç dönüşüm kaydedilmedi. "
        "En sık karşılaşılan nedenler: dönüşüm takip pikselinin çalışmaması, "
        "açılış sayfasında teknik hata, reklam onay sorunu veya "
        "hedefleme kitlesi ile teklif stratejisinin uyumsuzluğu. "
        "Öncelikle piksel ve açılış sayfasını kontrol edin."
    )


def _root_cause_spend_spike(insight: Insight) -> str:
    data = insight.data or {}
    current = data.get("current_spend")
    prior = data.get("prior_spend")
    pct = data.get("pct_rise", 0)
    channel = _channel_display(insight.channel)
    try:
        pct_display = tr_pct(pct * 100)
    except (TypeError, ValueError):
        pct_display = "?"
    return (
        f"{channel} kanalında harcama {pct_display} oranında ani artış gösterdi "
        f"(önceki dönem: {_num(prior)} → güncel: {_num(current)}). "
        "Olası nedenler: bütçe güncellemesi, teklif artışı, yeni reklam seti aktivasyonu "
        "veya rakipler çekildiğinde artan açık artırma verimliliği. "
        "Harcama artışının ROAS'a yansıyıp yansımadığını kontrol edin."
    )


def _root_cause_ctr_drop(insight: Insight) -> str:
    data = insight.data or {}
    current = data.get("current_ctr", "?")
    prior = data.get("prior_ctr", "?")
    pct = data.get("pct_drop", 0)
    channel = _channel_display(insight.channel)
    impressions = data.get("current_impressions")
    try:
        pct_display = tr_pct(pct * 100)
        c_display = tr_pct(current * 100, 2) if isinstance(current, float) else current
        p_display = tr_pct(prior * 100, 2) if isinstance(prior, float) else prior
    except (TypeError, ValueError):
        pct_display = c_display = p_display = "?"
    imp_display = (
        tr_num(float(impressions), 0) if isinstance(impressions, (int, float)) else "?"
    )
    return (
        f"{channel} kanalında tıklama oranı (CTR) {pct_display} düştü "
        f"(önceki: {p_display} → güncel: {c_display}). "
        f"Bu dönemde {imp_display} gösterimde bu oran yakalandı. "
        "Olası nedenler: reklam yorgunluğu (kreatif yenilenmesi gerekiyor), "
        "hedef kitlede reklam doygunluğu veya reklam alaka düzeyinin düşmesi. "
        "Reklam metni ve görsellerin güncellenmesini değerlendirin."
    )


def _root_cause_cpc_rise(insight: Insight) -> str:
    data = insight.data or {}
    current = data.get("current_cpc")
    prior = data.get("prior_cpc")
    pct = data.get("pct_rise", 0)
    channel = _channel_display(insight.channel)
    try:
        pct_display = tr_pct(pct * 100)
    except (TypeError, ValueError):
        pct_display = "?"
    return (
        f"{channel} kanalında tıklama başı maliyet (CPC) {pct_display} arttı "
        f"(önceki: {_num(prior)} → güncel: {_num(current)}). "
        "Olası nedenler: artan rekabet, sezonsal açık artırma baskısı, "
        "kalite puanı düşüşü veya teklif stratejisindeki değişiklik. "
        "Anahtar kelime kalite puanlarını ve açık artırma rekabetini inceleyin."
    )


def _root_cause_anomaly(insight: Insight) -> str:
    data = insight.data or {}
    metric = insight.metric or "?"
    channel = _channel_display(insight.channel)
    z = data.get("z_score", "?")
    direction = data.get("direction", "")
    candidate = data.get("candidate_value", "?")
    mean = data.get("history_mean", "?")
    dir_tr = "yüksek" if direction == "yuksek" else "düşük"
    try:
        z_display = tr_num(abs(float(z)), 1)
        z_str = f"istatistiksel sapma: {z_display}σ"
    except (TypeError, ValueError):
        z_str = "istatistiksel anomali"
    try:
        candidate_str = tr_num(float(candidate))
        mean_str = tr_num(float(mean))
    except (TypeError, ValueError):
        candidate_str = str(candidate)
        mean_str = str(mean)
    return (
        f"{channel} kanalının '{metric}' metriğinde beklenmedik bir {dir_tr} değer tespit edildi "
        f"({z_str}; güncel değer: {candidate_str}, geçmiş ortalama: {mean_str}). "
        "Bu tür ani sapmalar genellikle veri toplama sorununu, kampanya yapılandırma "
        "değişikliğini veya gerçek pazar anomalisini işaret eder. "
        "Güncel kampanya ayarlarını ve veri bütünlüğünü kontrol edin."
    )


def _root_cause_generic(insight: Insight) -> str:
    return (
        f"'{insight.category}' kategorisinde '{insight.metric}' metriği için anormallik tespit edildi. "
        "Detaylı analiz için ilgili kampanya ve kanal verilerini inceleyin."
    )


# ── Fix builders ───────────────────────────────────────────────────────────────


def _fixes_for_roas_drop(insight: Insight) -> list[FixAction]:
    data = insight.data or {}
    pct_drop = data.get("pct_drop", 0)
    # Threshold: at least the observed drop, rounded up to nearest 5%
    threshold = max(round(float(pct_drop) * 100 / 5) * 5, 15)
    channel = insight.channel
    period_end = insight.period_end
    period_start = insight.period_start

    fixes = [
        FixAction(
            label="ROAS Düşüş Uyarısı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"ROAS Düşüş Alarmı — {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": "roas",
                "comparator": "pct_drop",
                "threshold": float(threshold),
                "action": "alert",
                "window_days": 7,
            },
        ),
        FixAction(
            label="ROAS Hedefi Oluştur",
            action_type="create_goal",
            payload={
                "name": f"ROAS Toparlanma Hedefi — {channel or 'Tüm Kanallar'}",
                "metric": "roas",
                "target_value": round(float(data.get("prior_roas", 2.0)), 2),
                "period_start": str(period_start) if period_start else str(date.today()),
                "period_end": str(period_end) if period_end else str(date.today() + timedelta(days=29)),
                "channel_filter": channel,
            },
        ),
        FixAction(
            label="Kampanyaları İncele",
            action_type="view_campaign",
            payload={"channel": channel, "metric": "roas"},
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


def _fixes_for_zero_conversions(insight: Insight) -> list[FixAction]:
    channel = insight.channel
    data = insight.data or {}
    spend = data.get("spend", 0)
    period_end = insight.period_end
    period_start = insight.period_start

    fixes = [
        FixAction(
            label="Sıfır Dönüşüm Uyarısı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"Sıfır Dönüşüm Alarmı — {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": "conversions",
                "comparator": "below",
                "threshold": 1.0,
                "action": "alert",
                "window_days": 7,
            },
        ),
        FixAction(
            label="Dönüşüm Hedefi Koy",
            action_type="create_goal",
            payload={
                "name": f"Dönüşüm Kurtarma Hedefi — {channel or 'Tüm Kanallar'}",
                "metric": "conversions",
                "target_value": max(round(float(spend) / 50, 0), 10),
                "period_start": str(period_start) if period_start else str(date.today()),
                "period_end": str(period_end) if period_end else str(date.today() + timedelta(days=29)),
                "channel_filter": channel,
            },
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


def _fixes_for_spend_spike(insight: Insight) -> list[FixAction]:
    channel = insight.channel
    data = insight.data or {}
    pct_rise = data.get("pct_rise", 0)
    threshold = max(round(float(pct_rise) * 100 / 5) * 5, 20)

    fixes = [
        FixAction(
            label="Harcama Artışı Uyarısı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"Harcama Artış Alarmı — {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": "spend",
                "comparator": "pct_rise",
                "threshold": float(threshold),
                "action": "alert",
                "window_days": 7,
            },
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


def _fixes_for_ctr_drop(insight: Insight) -> list[FixAction]:
    channel = insight.channel
    data = insight.data or {}
    pct_drop = data.get("pct_drop", 0)
    threshold = max(round(float(pct_drop) * 100 / 5) * 5, 20)

    fixes = [
        FixAction(
            label="CTR Düşüş Uyarısı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"CTR Düşüş Alarmı — {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": "ctr",
                "comparator": "pct_drop",
                "threshold": float(threshold),
                "action": "alert",
                "window_days": 7,
            },
        ),
        FixAction(
            label="Kampanyaları İncele",
            action_type="view_campaign",
            payload={"channel": channel, "metric": "ctr"},
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


def _fixes_for_cpc_rise(insight: Insight) -> list[FixAction]:
    channel = insight.channel
    data = insight.data or {}
    pct_rise = data.get("pct_rise", 0)
    threshold = max(round(float(pct_rise) * 100 / 5) * 5, 20)

    fixes = [
        FixAction(
            label="CPC Artış Uyarısı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"CPC Artış Alarmı — {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": "cpc",
                "comparator": "pct_rise",
                "threshold": float(threshold),
                "action": "alert",
                "window_days": 7,
            },
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


def _fixes_for_anomaly(insight: Insight) -> list[FixAction]:
    channel = insight.channel
    metric = insight.metric or "spend"

    fixes = [
        FixAction(
            label="Anomali İzleme Kuralı Kur",
            action_type="create_automation_rule",
            payload={
                "name": f"Anomali Alarmı — {metric} / {channel or 'Tüm Kanallar'}",
                "scope": "channel" if channel else "account",
                "scope_filter": channel,
                "metric": metric if metric in ("spend", "roas", "ctr", "cpc", "cpa", "conversions") else "spend",
                "comparator": "anomaly",
                "threshold": None,
                "action": "alert",
                "window_days": 14,
            },
        ),
        FixAction(
            label="Bu İçgörüyü Kapat",
            action_type="dismiss_insight",
            payload={"insight_id": str(insight.id)},
        ),
    ]
    return fixes


# ── Category dispatch ──────────────────────────────────────────────────────────

_ROOT_CAUSE_BUILDERS = {
    "roas_drop": _root_cause_roas_drop,
    "zero_conversions": _root_cause_zero_conversions,
    "spend_spike": _root_cause_spend_spike,
    "ctr_drop": _root_cause_ctr_drop,
    "cpc_rise": _root_cause_cpc_rise,
    "anomaly": _root_cause_anomaly,
}

_FIX_BUILDERS = {
    "roas_drop": _fixes_for_roas_drop,
    "zero_conversions": _fixes_for_zero_conversions,
    "spend_spike": _fixes_for_spend_spike,
    "ctr_drop": _fixes_for_ctr_drop,
    "cpc_rise": _fixes_for_cpc_rise,
    "anomaly": _fixes_for_anomaly,
}


# ── Public API ─────────────────────────────────────────────────────────────────


def suggested_fixes_for_insight(
    db: Session,
    tenant_id: uuid.UUID,
    insight: Insight,
) -> FixSuggestion:
    """Return root-cause explanation + one-click fix list for one Insight.

    Parameters
    ----------
    db:
        SQLAlchemy Session.  Not currently used for data access but kept for
        future lookups (e.g. checking existing rules for deduplication).
    tenant_id:
        Caller's tenant UUID.  The insight must belong to this tenant (enforced
        by the API layer before calling this function).
    insight:
        The Insight ORM row to analyse.

    Returns
    -------
    FixSuggestion with a Turkish root_cause string and a list of FixActions.
    """
    category = insight.category or ""

    # Root cause
    root_cause_fn = _ROOT_CAUSE_BUILDERS.get(category, _root_cause_generic)
    try:
        root_cause = root_cause_fn(insight)
    except Exception:
        root_cause = _root_cause_generic(insight)

    # Fix actions
    fix_fn = _FIX_BUILDERS.get(category)
    if fix_fn is not None:
        try:
            fixes = fix_fn(insight)
        except Exception:
            fixes = [
                FixAction(
                    label="Bu İçgörüyü Kapat",
                    action_type="dismiss_insight",
                    payload={"insight_id": str(insight.id)},
                )
            ]
    else:
        fixes = [
            FixAction(
                label="Bu İçgörüyü Kapat",
                action_type="dismiss_insight",
                payload={"insight_id": str(insight.id)},
            )
        ]

    return FixSuggestion(
        insight_id=insight.id,
        root_cause=root_cause,
        fixes=fixes,
    )


def apply_fix(
    db: Session,
    tenant_id: uuid.UUID,
    insight: Insight,
    action_type: str,
    payload: dict[str, Any],
) -> ApplyResult:
    """Execute a one-click fix action.

    Only safe internal actions are permitted:
    - create_automation_rule — persists an AutomationRule via automation service
    - create_goal            — persists a Goal via goals service
    - dismiss_insight        — sets insight.status = 'dismissed'
    - view_campaign          — no-op (navigational, returns success immediately)

    No live ad-platform writes are ever performed.

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access).
    tenant_id:
        Caller's tenant UUID.  All entity creations are scoped to this tenant.
    insight:
        The Insight this fix was generated for (already validated by the API
        layer to belong to tenant_id).
    action_type:
        One of the allowed action type strings.
    payload:
        Ready-to-apply parameters from the FixAction.

    Returns
    -------
    ApplyResult describing what was done.
    """
    if action_type == "dismiss_insight":
        insight.status = "dismissed"
        db.flush()
        return ApplyResult(
            action_type=action_type,
            success=True,
            message="İçgörü kapatıldı.",
            entity_id=str(insight.id),
            entity_type="insight",
        )

    if action_type == "view_campaign":
        # Navigational — no server action
        return ApplyResult(
            action_type=action_type,
            success=True,
            message="Kampanya görünümüne yönlendir.",
            entity_id=None,
            entity_type=None,
        )

    if action_type == "create_automation_rule":
        from ayaz.models.automation import AutomationRule
        from ayaz.services.automation import VALID_METRICS, VALID_COMPARATORS, VALID_ACTIONS, VALID_SCOPES

        name = payload.get("name", "Otomatik Kural")
        scope = payload.get("scope", "account")
        scope_filter = payload.get("scope_filter")
        metric = payload.get("metric", "spend")
        comparator = payload.get("comparator", "pct_drop")
        threshold = payload.get("threshold")
        action = payload.get("action", "alert")
        window_days = int(payload.get("window_days", 7))

        # Validate
        errors = []
        if scope not in VALID_SCOPES:
            scope = "account"
        if metric not in VALID_METRICS:
            errors.append(f"Geçersiz metrik: {metric!r}")
        if comparator not in VALID_COMPARATORS:
            errors.append(f"Geçersiz karşılaştırıcı: {comparator!r}")
        if action not in VALID_ACTIONS:
            errors.append(f"Geçersiz eylem: {action!r}")

        if errors:
            return ApplyResult(
                action_type=action_type,
                success=False,
                message="Parametre hatası: " + "; ".join(errors),
            )

        rule = AutomationRule(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            scope_filter=scope_filter if scope != "account" else None,
            metric=metric,
            comparator=comparator,
            threshold=float(threshold) if threshold is not None else None,
            window_days=window_days,
            action=action,
            action_config={},
            is_active=True,
        )
        db.add(rule)
        db.flush()

        return ApplyResult(
            action_type=action_type,
            success=True,
            message=f"Otomasyon kuralı oluşturuldu: '{name}' (ID: {rule.id})",
            entity_id=str(rule.id),
            entity_type="automation_rule",
        )

    if action_type == "create_goal":
        from ayaz.services.goals import create_goal, ALL_METRICS

        name = payload.get("name", "Yeni Hedef")
        metric = payload.get("metric", "roas")
        target_value = float(payload.get("target_value", 1.0))
        period_start = payload.get("period_start", str(date.today()))
        period_end = payload.get("period_end", str(date.today() + timedelta(days=29)))
        channel_filter = payload.get("channel_filter")

        if metric not in ALL_METRICS:
            return ApplyResult(
                action_type=action_type,
                success=False,
                message=f"Geçersiz metrik: {metric!r}. Geçerli değerler: {sorted(ALL_METRICS)}",
            )

        try:
            goal = create_goal(
                db=db,
                tenant_id=tenant_id,
                name=name,
                metric=metric,
                target_value=target_value,
                period_start=period_start,
                period_end=period_end,
                channel_filter=channel_filter,
            )
        except ValueError as exc:
            return ApplyResult(
                action_type=action_type,
                success=False,
                message=f"Hedef oluşturulamadı: {exc}",
            )

        return ApplyResult(
            action_type=action_type,
            success=True,
            message=f"Hedef oluşturuldu: '{name}' (ID: {goal.id})",
            entity_id=str(goal.id),
            entity_type="goal",
        )

    return ApplyResult(
        action_type=action_type,
        success=False,
        message=f"Bilinmeyen eylem türü: {action_type!r}",
    )
