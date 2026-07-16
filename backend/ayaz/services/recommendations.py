"""Proaktif Öneri Merkezi + AI Haftalık Strateji servisi — M14.

Public API
----------
    build_recommendation_feed(db, tenant_id, *, as_of=None) -> dict
        Synthesise a prioritised recommendation feed from all AYAZ signals.

    apply_recommendation_action(db, tenant_id, recommendation_key, action, *,
                                note=None, snooze_days=7) -> dict
        Persist an accept / snooze / dismiss / reopen action.

    generate_weekly_strategy(db, tenant_id, *, as_of=None) -> dict
        Return a Turkish weekly strategy narrative (template or AI).

Recommendation keys (stable, deterministic)
--------------------------------------------
    "audit:fail:<check_id>"         — a fail-severity audit check
    "audit:warn:<check_id>"         — a warn-severity audit check (selected ones)
    "budget:overspend"              — budget pace > time pace + 10 pp
    "budget:underspend"             — budget pace < time pace - 10 pp
    "budget:no_plan"                — no budget plan exists
    "benchmark:weak_roas"           — account-level ROAS below sector low
    "benchmark:weak_roas:<ch>"      — per-channel ROAS weak
    "benchmark:weak_ctr"            — account-level CTR weak
    "goal:behind_pace"              — at least one goal off-track / at-risk
    "inbox:backlog"                 — open + pending messages > threshold
    "content:no_scheduled"          — no scheduled content

Impact mapping
--------------
    audit fail     → high
    goal behind    → high
    budget overspend → high
    audit warn     → medium
    budget underspend → medium
    benchmark weak → medium
    inbox backlog  → medium
    content gap    → low

Tenant isolation
----------------
All DB queries carry explicit tenant_id filters; this service never reads
data belonging to another tenant.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ayaz.services.trformat import tr_int, tr_pct, tr_roas, tr_tl

log = logging.getLogger(__name__)

# ── Turkish month name map ─────────────────────────────────────────────────────

_TR_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
_STATUS_ORDER = {"open": 0, "accepted": 1, "snoozed": 2, "dismissed": 3}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _today(as_of: date | None = None) -> date:
    return as_of or datetime.now(timezone.utc).date()


def _now_iso(as_of: date | None = None) -> str:
    if as_of is not None:
        return datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _load_states(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Return {recommendation_key: RecommendationState} for the tenant."""
    from sqlalchemy import select
    from ayaz.models.recommendations import RecommendationState

    rows = db.scalars(
        select(RecommendationState).where(
            RecommendationState.tenant_id == tenant_id
        )
    ).all()
    return {r.recommendation_key: r for r in rows}


def _rec(
    key: str,
    category: str,
    category_label: str,
    title: str,
    rationale: str,
    impact: str,
    effort: str,
    metric: dict | None,
    action_label: str,
    action_href: str,
    state: Any | None,
) -> dict:
    """Build a single recommendation dict."""
    _impact_labels = {"high": "Yüksek", "medium": "Orta", "low": "Düşük"}
    _effort_labels = {"low": "Düşük", "medium": "Orta", "high": "Yüksek"}

    status = "open"
    snoozed_until = None
    if state is not None:
        status = state.status or "open"
        snoozed_until = state.snoozed_until

    return {
        "key": key,
        "category": category,
        "category_label": category_label,
        "title": title,
        "rationale": rationale,
        "impact": impact,
        "impact_label": _impact_labels.get(impact, impact),
        "effort": effort,
        "effort_label": _effort_labels.get(effort, effort),
        "metric": metric,
        "action_label": action_label,
        "action_href": action_href,
        "status": status,
        "snoozed_until": snoozed_until,
    }


# ── Recommendation builders ────────────────────────────────────────────────────


def _from_audit(db: Session, tenant_id: uuid.UUID, states: dict) -> list[dict]:
    """Build recommendations from the account health audit."""
    from ayaz.services.audit import run_account_audit

    recs: list[dict] = []
    try:
        audit = run_account_audit(db, tenant_id)
    except Exception:
        log.warning("recommendations: audit call failed", exc_info=True)
        return recs

    # Selected check IDs that map to actionable recommendations (avoid duplicating
    # every single check — pick the most actionable fail/warn items).
    _SKIP_IDS = frozenset({
        "ads_healthy", "tracking_healthy", "budget_plan_exists",
        "content_healthy", "goals_on_track", "goals_none_defined",
        "insights_none", "insights_info_only", "ads_no_data",
        "ads_error", "tracking_error", "budget_error", "content_error",
        "goals_error", "insights_error",
    })

    # Map audit check IDs to (effort, action_label, action_href)
    _CHECK_META: dict[str, tuple[str, str, str]] = {
        "ads_roas_below_1":          ("medium", "Reklamları incele", "/ads"),
        "ads_budget_concentration":  ("low",    "Bütçeyi çeşitlendir", "/ads"),
        "ads_low_ctr":               ("medium", "Kreatif yenile", "/ads"),
        "tracking_no_source":        ("high",   "İzleme kur", "/tracking"),
        "tracking_no_destination":   ("medium", "Hedef ekle", "/tracking"),
        "tracking_failed_events":    ("low",    "Olayları yeniden gönder", "/tracking"),
        "tracking_low_match_quality":("medium", "Kimlik sinyali ekle", "/tracking"),
        "tracking_consent_drop":     ("medium", "Rıza akışını gözden geçir", "/tracking"),
        "budget_no_plan":            ("low",    "Bütçe planı oluştur", "/planning"),
        "content_pending_approval":  ("low",    "İçerikleri onayla", "/content"),
        "content_no_scheduled":      ("low",    "İçerik zamanla", "/content"),
        "goals_at_risk":             ("medium", "Hedef stratejisini güncelle", "/goals"),
        "insights_critical":         ("medium", "İçgörüleri incele", "/insights"),
        "insights_warnings":         ("low",    "İçgörüleri incele", "/insights"),
    }

    score = audit.get("score", 100)

    for cat in audit.get("categories", []):
        for check in cat.get("checks", []):
            cid = check.get("id", "")
            severity = check.get("severity", "pass")
            if severity == "pass" or cid in _SKIP_IDS:
                continue

            key = f"audit:{'fail' if severity == 'fail' else 'warn'}:{cid}"
            impact = "high" if severity == "fail" else "medium"
            meta = _CHECK_META.get(cid, ("medium", "Detayları gör", "/audit"))
            effort, action_label, action_href = meta

            recs.append(_rec(
                key=key,
                category="audit",
                category_label="Hesap Sağlık Taraması",
                title=check.get("title", "Sorun tespit edildi"),
                rationale=(
                    check.get("finding", "") + " — " + check.get("recommendation", "")
                ).strip(" —").strip(),
                impact=impact,
                effort=effort,
                metric={"label": "Sağlık Puanı", "value": f"{score}/100"},
                action_label=action_label,
                action_href=action_href,
                state=states.get(key),
            ))

    return recs


def _from_budget(db: Session, tenant_id: uuid.UUID, states: dict, as_of: date | None) -> list[dict]:
    """Build recommendations from budget plan vs actuals."""
    from sqlalchemy import select
    from ayaz.models.budget import BudgetPlan
    from ayaz.services.budget_planner import plan_actuals, _month_bounds

    recs: list[dict] = []
    try:
        today = _today(as_of)
        current_month = f"{today.year}-{today.month:02d}"
        plan = db.scalar(
            select(BudgetPlan).where(
                BudgetPlan.tenant_id == tenant_id,
                BudgetPlan.period_month == current_month,
            ).order_by(BudgetPlan.created_at.desc())
        )
        if plan is None:
            # No plan for this month — low-priority recommendation
            key = "budget:no_plan"
            recs.append(_rec(
                key=key,
                category="budget",
                category_label="Bütçe & Planlama",
                title="Bu ay için bütçe planı yok",
                rationale=(
                    f"{_TR_MONTHS.get(today.month, str(today.month))} {today.year} için "
                    "tanımlı bir bütçe planı bulunamadı; harcamalar plansız ilerliyor."
                ),
                impact="medium",
                effort="low",
                metric=None,
                action_label="Bütçe planı oluştur",
                action_href="/planning",
                state=states.get(key),
            ))
            return recs

        actuals = plan_actuals(db, tenant_id, plan, as_of=today)
        totals = actuals.get("totals", {})
        overall_pace = totals.get("pace_pct", 0.0)
        time_pace = totals.get("time_pace_pct", 0.0)
        actual_spend = totals.get("actual_spend", 0.0)
        planned_total = totals.get("planned_budget", 0.0)

        if overall_pace > time_pace + 10:
            key = "budget:overspend"
            recs.append(_rec(
                key=key,
                category="budget",
                category_label="Bütçe & Planlama",
                title="Bütçe temposu zamanın önünde",
                rationale=(
                    f"Bütçenin %{overall_pace:.0f}'i harcandı ancak ayın yalnızca "
                    f"%{time_pace:.0f}'i geçti. Gerçekleşen harcama "
                    f"{tr_tl(actual_spend)} / Planlanan {tr_tl(planned_total)}. "
                    "Bütçe erken tükenebilir."
                ),
                impact="high",
                effort="medium",
                metric={"label": "Harcama Temposu", "value": f"%{overall_pace:.0f}"},
                action_label="Bütçe planını aç",
                action_href="/planning",
                state=states.get(key),
            ))
        elif overall_pace < time_pace - 10:
            key = "budget:underspend"
            recs.append(_rec(
                key=key,
                category="budget",
                category_label="Bütçe & Planlama",
                title="Bütçe temposu zamanın gerisinde",
                rationale=(
                    f"Ayın %{time_pace:.0f}'i geçmesine rağmen bütçenin yalnızca "
                    f"%{overall_pace:.0f}'i kullanıldı. Gerçekleşen harcama "
                    f"{tr_tl(actual_spend)} / Planlanan {tr_tl(planned_total)}. "
                    "Bütçe tam kullanılmayabilir."
                ),
                impact="medium",
                effort="low",
                metric={"label": "Harcama Temposu", "value": f"%{overall_pace:.0f}"},
                action_label="Bütçe planını aç",
                action_href="/planning",
                state=states.get(key),
            ))
    except Exception:
        log.warning("recommendations: budget call failed", exc_info=True)

    return recs


def _from_benchmark(db: Session, tenant_id: uuid.UUID, states: dict, as_of: date | None) -> list[dict]:
    """Build recommendations from the sector benchmark."""
    from ayaz.services.benchmark import build_benchmark

    recs: list[dict] = []
    try:
        today = _today(as_of)
        date_from = today - timedelta(days=29)
        result = build_benchmark(db, tenant_id, date_from, today)

        # Account-level ROAS
        for m in result.get("metrics", []):
            if m["key"] == "roas" and m["position"] == "weak":
                key = "benchmark:weak_roas"
                roas_val = m["your_value"]
                ref_low = m["ref_low"]
                recs.append(_rec(
                    key=key,
                    category="benchmark",
                    category_label="Sektör Kıyaslaması",
                    title="ROAS sektör ortalamasının altında",
                    rationale=(
                        f"Hesap genelinde ROAS {tr_roas(roas_val)} — sektör referansının "
                        f"alt sınırı {tr_roas(ref_low)}. Reklam optimizasyonu önerilir."
                    ),
                    impact="medium",
                    effort="medium",
                    metric={"label": "ROAS", "value": tr_roas(roas_val)},
                    action_label="Kıyaslama raporunu aç",
                    action_href="/benchmark",
                    state=states.get(key),
                ))
            elif m["key"] == "ctr" and m["position"] == "weak":
                key = "benchmark:weak_ctr"
                ctr_val = m["your_value"]
                ref_low = m["ref_low"]
                recs.append(_rec(
                    key=key,
                    category="benchmark",
                    category_label="Sektör Kıyaslaması",
                    title="Tıklama oranı (TO) sektör ortalamasının altında",
                    rationale=(
                        f"Hesap genelinde CTR {tr_pct(ctr_val, 2)} — sektör referansının "
                        f"alt sınırı {tr_pct(ref_low, 1)}. Kreatif yenilenmesi önerilir."
                    ),
                    impact="medium",
                    effort="medium",
                    metric={"label": "CTR", "value": f"%{ctr_val:.2f}"},
                    action_label="Kıyaslama raporunu aç",
                    action_href="/benchmark",
                    state=states.get(key),
                ))

        # Per-channel ROAS
        for ch in result.get("channels", []):
            if ch.get("roas_position") == "weak":
                ch_key = ch.get("channel", "")
                key = f"benchmark:weak_roas:{ch_key}"
                ch_roas = ch.get("roas", 0.0)
                ch_label = ch.get("label", ch_key)
                recs.append(_rec(
                    key=key,
                    category="benchmark",
                    category_label="Sektör Kıyaslaması",
                    title=f"{ch_label} ROAS'ı sektör ortalamasının altında",
                    rationale=(
                        f"{ch_label} kanalının ROAS'ı {tr_roas(ch_roas)} — sektör "
                        "referans alt sınırının (2.0x) altında. Kanal optimizasyonu önerilir."
                    ),
                    impact="medium",
                    effort="medium",
                    metric={"label": f"{ch_label} ROAS", "value": tr_roas(ch_roas)},
                    action_label="Kıyaslama raporunu aç",
                    action_href="/benchmark",
                    state=states.get(key),
                ))
    except Exception:
        log.warning("recommendations: benchmark call failed", exc_info=True)

    return recs


def _from_goals(db: Session, tenant_id: uuid.UUID, states: dict) -> list[dict]:
    """Build recommendations from goal progress."""
    from ayaz.services.copilot_tools import _get_goal_progress

    recs: list[dict] = []
    try:
        result = _get_goal_progress(db, tenant_id)
        goals = result.get("goals", [])

        # pct_to_target is a 0..1+ ratio from the goal service. Spend goals
        # flagged for OVERRUN pacing must not land in the "behind" card —
        # "hedefin gerisinde / hızlan" would be the opposite of the right
        # advice. They get their own budget-overrun recommendation below.
        def _spend_overrun(g: dict) -> bool:
            if g.get("metric") != "spend":
                return False
            target = g.get("target_value") or 0
            forecast = g.get("forecast_value") or 0
            return bool(target) and (forecast / target) > 1.05

        flagged = [
            g for g in goals if g.get("status") in ("at_risk", "off_track")
        ]
        overrun = [g for g in flagged if _spend_overrun(g)]
        at_risk = [
            g for g in flagged
            if not _spend_overrun(g) and (g.get("pct_to_target") or 0) < 1.0
        ]

        if overrun:
            key = "goal:budget_overrun"
            names = ", ".join(f"'{g['name']}'" for g in overrun[:3])
            if len(overrun) > 3:
                names += f" ve {len(overrun) - 3} diğeri"
            worst = overrun[0]
            w_target = worst.get("target_value", 0) or 0
            w_forecast = worst.get("forecast_value", 0) or 0
            over_pct = (w_forecast / w_target * 100 - 100) if w_target else 0
            recs.append(_rec(
                key=key,
                category="goal",
                category_label="Hedefler",
                title="Bütçe hedefi aşım riskinde",
                rationale=(
                    f"{len(overrun)} bütçe hedefi aşım temposunda: {names}. "
                    f"'{worst['name']}': bu hızla dönem sonunda hedef "
                    f"%{over_pct:.0f} aşılacak (tahmin {tr_tl(w_forecast)} / "
                    f"hedef {tr_tl(w_target)}). Harcama hızını düşürün."
                ),
                impact="high",
                effort="medium",
                metric={"label": "Tahmini Aşım", "value": f"%{over_pct:.0f}"},
                action_label="Hedefleri incele",
                action_href="/goals",
                state=states.get(key),
            ))

        if at_risk:
            key = "goal:behind_pace"
            names = ", ".join(f"'{g['name']}'" for g in at_risk[:3])
            if len(at_risk) > 3:
                names += f" ve {len(at_risk) - 3} diğeri"
            best = at_risk[0]
            pct = ((best.get("pct_to_target", 0) or 0)) * 100
            target = best.get("target_value", 0) or 0
            current = best.get("current_value", 0) or 0
            # Turkish thousands separator (dot) for the inline numbers.
            cur_txt = f"{current:,.0f}".replace(",", ".")
            tgt_txt = f"{target:,.0f}".replace(",", ".")
            recs.append(_rec(
                key=key,
                category="goal",
                category_label="Hedefler",
                title="Hedef geride kalıyor",
                rationale=(
                    f"{len(at_risk)} hedef hedefin gerisinde: {names}. "
                    f"'{best['name']}': %{pct:.0f} tamamlandı "
                    f"(mevcut {cur_txt} / hedef {tgt_txt})."
                ),
                impact="high",
                effort="medium",
                metric={"label": "Hedefe Yüzde", "value": f"%{pct:.0f}"},
                action_label="Hedefleri incele",
                action_href="/goals",
                state=states.get(key),
            ))
    except Exception:
        log.warning("recommendations: goals call failed", exc_info=True)

    return recs


def _from_inbox(db: Session, tenant_id: uuid.UUID, states: dict) -> list[dict]:
    """Build recommendations from social inbox backlog."""
    from ayaz.services.copilot_tools import _get_inbox_summary

    recs: list[dict] = []
    try:
        summary = _get_inbox_summary(db, tenant_id)
        open_count = summary.get("open", 0)
        pending_count = summary.get("pending", 0)
        backlog = open_count + pending_count
        if backlog >= 3:
            key = "inbox:backlog"
            recs.append(_rec(
                key=key,
                category="inbox",
                category_label="Sosyal Gelen Kutusu",
                title="Yanıt bekleyen mesaj birikimi var",
                rationale=(
                    f"Gelen kutusunda {open_count} açık ve {pending_count} beklemede olan "
                    f"mesaj bulunuyor (toplam {backlog}). Müşteri memnuniyeti için "
                    "yanıt süresinin kısaltılması önerilir."
                ),
                impact="medium",
                effort="low",
                metric={"label": "Bekleyen Mesaj", "value": str(backlog)},
                action_label="Gelen kutusuna git",
                action_href="/inbox",
                state=states.get(key),
            ))
    except Exception:
        log.warning("recommendations: inbox call failed", exc_info=True)

    return recs


def _from_content(db: Session, tenant_id: uuid.UUID, states: dict) -> list[dict]:
    """Build recommendations from content planner status."""
    from ayaz.services.copilot_tools import _get_content_status

    recs: list[dict] = []
    try:
        status = _get_content_status(db, tenant_id)
        scheduled = status.get("scheduled", 0)
        draft = status.get("draft", 0)
        if scheduled == 0:
            key = "content:no_scheduled"
            detail = (
                f"{draft} taslak var ancak planlanmış yayın yok."
                if draft > 0
                else "Henüz planlanmış içerik bulunmuyor."
            )
            recs.append(_rec(
                key=key,
                category="content",
                category_label="İçerik Planlayıcı",
                title="Planlanmış içerik yok",
                rationale=(
                    f"{detail} İçerik takvimini doldurmak sosyal medya varlığını "
                    "güçlendirir."
                ),
                impact="low",
                effort="low",
                metric={"label": "Zamanlanmış İçerik", "value": "0"},
                action_label="İçerik planlayıcıyı aç",
                action_href="/content",
                state=states.get(key),
            ))
    except Exception:
        log.warning("recommendations: content call failed", exc_info=True)

    return recs


# ── Public API ─────────────────────────────────────────────────────────────────


def build_recommendation_feed(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> dict:
    """Synthesise a prioritised recommendation feed for the tenant.

    Pulls from audit, budget, benchmark, goals, inbox, and content signals.
    Merges persisted RecommendationState by key.
    Sorts: open first (high→medium→low impact), then accepted/snoozed/dismissed.

    Returns
    -------
    {
        "generated_at": ISO str,
        "summary": {
            "open": int, "accepted": int, "snoozed": int,
            "dismissed": int, "total": int, "high_impact_open": int
        },
        "recommendations": [...]
    }
    """
    states = _load_states(db, tenant_id)

    all_recs: list[dict] = []
    all_recs.extend(_from_audit(db, tenant_id, states))
    all_recs.extend(_from_budget(db, tenant_id, states, as_of))
    all_recs.extend(_from_benchmark(db, tenant_id, states, as_of))
    all_recs.extend(_from_goals(db, tenant_id, states))
    all_recs.extend(_from_inbox(db, tenant_id, states))
    all_recs.extend(_from_content(db, tenant_id, states))

    # Deduplicate by key — first occurrence wins (audit runs first)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in all_recs:
        if r["key"] not in seen:
            seen.add(r["key"])
            deduped.append(r)

    # Sort: open first sorted by impact asc(high=0, medium=1, low=2);
    # then accepted/snoozed/dismissed by their own order.
    def _sort_key(r: dict) -> tuple[int, int]:
        status_ord = _STATUS_ORDER.get(r["status"], 4)
        impact_ord = _IMPACT_ORDER.get(r["impact"], 3)
        return (status_ord, impact_ord)

    deduped.sort(key=_sort_key)

    # Summary counts
    summary: dict[str, int] = {
        "open": 0, "accepted": 0, "snoozed": 0, "dismissed": 0,
        "total": 0, "high_impact_open": 0,
    }
    for r in deduped:
        st = r["status"]
        summary[st] = summary.get(st, 0) + 1
        summary["total"] += 1
        if st == "open" and r["impact"] == "high":
            summary["high_impact_open"] += 1

    return {
        "generated_at": _now_iso(as_of),
        "summary": summary,
        "recommendations": deduped,
    }


def apply_recommendation_action(
    db: Session,
    tenant_id: uuid.UUID,
    recommendation_key: str,
    action: str,
    *,
    note: str | None = None,
    snooze_days: int = 7,
) -> dict:
    """Persist an accept / snooze / dismiss / reopen action for a recommendation.

    Parameters
    ----------
    action:
        One of "accept", "snooze", "dismiss", "reopen".
    snooze_days:
        Number of days from now to snooze (only used when action == "snooze").

    Returns
    -------
    {"key", "status", "snoozed_until", "note"}

    Raises
    ------
    ValueError for an unknown action.
    """
    from sqlalchemy import select
    from ayaz.models.recommendations import RecommendationState, VALID_ACTIONS

    if action not in VALID_ACTIONS:
        raise ValueError(
            f"Geçersiz eylem: {action!r}. Geçerli değerler: {sorted(VALID_ACTIONS)}"
        )

    now = datetime.now(timezone.utc)

    state = db.scalar(
        select(RecommendationState).where(
            RecommendationState.tenant_id == tenant_id,
            RecommendationState.recommendation_key == recommendation_key,
        )
    )

    if state is None:
        import uuid as _uuid
        state = RecommendationState(
            id=_uuid.uuid4(),
            tenant_id=tenant_id,
            recommendation_key=recommendation_key,
            status="open",
        )
        db.add(state)
        db.flush()

    if action == "accept":
        state.status = "accepted"
        state.snoozed_until = None
    elif action == "snooze":
        state.status = "snoozed"
        snooze_until_dt = now + timedelta(days=max(1, snooze_days))
        state.snoozed_until = snooze_until_dt.isoformat()
    elif action == "dismiss":
        state.status = "dismissed"
        state.snoozed_until = None
    elif action == "reopen":
        state.status = "open"
        state.snoozed_until = None

    if note is not None:
        state.note = note

    db.flush()
    db.commit()

    return {
        "key": state.recommendation_key,
        "status": state.status,
        "snoozed_until": state.snoozed_until,
        "note": state.note,
    }


# ── Weekly Strategy ────────────────────────────────────────────────────────────


def _week_label(ref: date) -> str:
    """Return Turkish week label like '22–28 Haziran 2026'."""
    # Week starts Monday
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    month_name = _TR_MONTHS.get(monday.month, "")
    if monday.month == sunday.month:
        return f"{monday.day}–{sunday.day} {month_name} {monday.year}"
    end_month = _TR_MONTHS.get(sunday.month, "")
    return f"{monday.day} {month_name} – {sunday.day} {end_month} {monday.year}"


def _template_strategy(
    feed: dict,
    exec_summary: dict | None,
    ref: date,
) -> dict:
    """Build a fully deterministic Turkish weekly strategy — no network."""
    recs = feed.get("recommendations", [])
    summary = feed.get("summary", {})
    total_open = summary.get("open", 0)
    high_impact = summary.get("high_impact_open", 0)

    # Top-3 open recommendations by impact
    open_recs = [r for r in recs if r["status"] == "open"][:3]

    # Headline
    if high_impact > 0:
        headline = (
            f"Bu hafta {high_impact} yüksek etkili aksiyona odaklanarak "
            "performans açığını kapatın."
        )
    elif total_open > 0:
        headline = (
            f"Bu hafta {total_open} bekleyen öneriyi ele alarak "
            "pazarlama verimliliğinizi artırın."
        )
    else:
        headline = "Bu hafta tüm öneriler güncel — optimizasyona devam edin."

    # Narrative
    kpis = exec_summary.get("kpis", {}) if exec_summary else {}
    spend = kpis.get("spend", 0) or 0
    roas = kpis.get("roas", 0) or 0
    conversions = kpis.get("conversions", 0) or 0

    if spend > 0:
        narrative = (
            f"Son 30 günde toplam {tr_tl(spend)} harcama ile {tr_int(conversions)} dönüşüm "
            f"sağlandı; ortalama ROAS {tr_roas(roas)} olarak gerçekleşti. "
        )
    else:
        narrative = "Reklam performans verisi henüz oluşmamış. "

    if high_impact > 0:
        narrative += (
            f"Bu hafta {high_impact} yüksek etkili öneri acil dikkat gerektiriyor. "
        )
    if total_open > 0:
        narrative += (
            f"Toplam {total_open} açık önerinin tamamlanması hedeflenmeli."
        )

    # Focus areas (derived from top open recommendations)
    focus_areas: list[dict] = []
    seen_categories: set[str] = set()

    for r in open_recs:
        cat = r.get("category", "")
        if cat in seen_categories:
            continue
        seen_categories.add(cat)
        focus_areas.append({
            "title": r["category_label"],
            "detail": r["title"] + " — " + r["rationale"][:100] + ("..." if len(r["rationale"]) > 100 else ""),
        })

    # Ensure at least 3 focus areas with fallbacks
    _fallback_areas = [
        {"title": "Reklam Optimizasyonu", "detail": "Düşük performanslı reklamları gözden geçirin ve bütçeyi güçlü kanallara kaydırın."},
        {"title": "İçerik Planlaması", "detail": "Tutarlı sosyal medya içeriği marka bilinirliğini artırır; haftalık paylaşım takvimi oluşturun."},
        {"title": "Dönüşüm İyileştirmesi", "detail": "Açılış sayfası deneyimini ve ödeme akışını optimize ederek dönüşüm oranını yükseltin."},
        {"title": "Veri & Ölçümleme", "detail": "İzleme kaynaklarınızın sağlıklı çalıştığını doğrulayın; doğru veri doğru karar almanızı sağlar."},
    ]
    for fb in _fallback_areas:
        if len(focus_areas) >= 4:
            break
        if fb["title"] not in {fa["title"] for fa in focus_areas}:
            focus_areas.append(fb)

    return {
        "week_label": _week_label(ref),
        "headline": headline,
        "narrative": narrative.strip(),
        "focus_areas": focus_areas[:4],
        "top_recommendations": open_recs,
        "source": "template",
    }


class _ClaudeStrategyGenerator:
    """Optional Claude-powered weekly strategy narrative.

    Falls back to template on any error — never raises.
    Model ID from settings.claude_narrator_model.
    """

    def __init__(self, api_key: str, http_client: Any = None) -> None:
        self._api_key = api_key
        self._http_client = http_client

    def generate(
        self,
        feed: dict,
        exec_summary: dict | None,
        ref: date,
    ) -> dict:
        try:
            return self._call_claude(feed, exec_summary, ref)
        except Exception as exc:
            log.warning(
                "[ClaudeStrategyGenerator] API call failed (%s) — using template", exc
            )
            return _template_strategy(feed, exec_summary, ref)

    def _call_claude(
        self,
        feed: dict,
        exec_summary: dict | None,
        ref: date,
    ) -> dict:
        import httpx
        from ayaz.config import settings

        model = settings.claude_narrator_model

        summary = feed.get("summary", {})
        recs = feed.get("recommendations", [])
        open_recs = [r for r in recs if r["status"] == "open"][:5]
        kpis = (exec_summary or {}).get("kpis", {})

        prompt = (
            f"Bir dijital pazarlama platformunun haftalık Türkçe strateji özetini yaz. "
            f"Referans haftası: {_week_label(ref)}. "
            f"Son 30 gün KPI'ları: harcama={tr_tl(kpis.get('spend', 0))}, "
            f"ROAS={tr_roas(float(kpis.get('roas', 0) or 0))}, dönüşüm={tr_int(kpis.get('conversions', 0))}. "
            f"Açık öneri sayısı: {summary.get('open', 0)} (yüksek etkili: {summary.get('high_impact_open', 0)}). "
            f"En kritik öneriler: {json.dumps([{'title': r['title'], 'category': r['category_label'], 'impact': r['impact']} for r in open_recs[:3]], ensure_ascii=False)}. "
            "Şu alanları Türkçe ve doğal bir dille doldurarak JSON formatında yanıtla: "
            "headline (1 cümle), narrative (2-3 cümle), focus_areas (3-4 odak alanı, her biri title ve detail). "
            "Sadece JSON döndür, başka metin ekleme."
        )

        payload = {
            "model": model,
            "max_tokens": 800,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        if self._http_client is not None:
            resp = self._http_client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=30.0,
            )
        else:
            import httpx as _httpx
            with _httpx.Client() as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:200]}"
            )

        raw_text = resp.json()["content"][0]["text"].strip()
        parsed = json.loads(raw_text)

        open_recs_top = [r for r in recs if r["status"] == "open"][:3]

        return {
            "week_label": _week_label(ref),
            "headline": str(parsed.get("headline", "")),
            "narrative": str(parsed.get("narrative", "")),
            "focus_areas": list(parsed.get("focus_areas", []))[:4],
            "top_recommendations": open_recs_top,
            "source": "ai",
        }


def generate_weekly_strategy(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> dict:
    """Return a Turkish weekly strategy for the tenant.

    Always returns a valid dict (template fallback works without an API key).

    Returns
    -------
    {
        "week_label": str (e.g. "22–28 Haziran 2026"),
        "headline": str,
        "narrative": str,
        "focus_areas": [{"title": str, "detail": str}, ...],
        "top_recommendations": [...],
        "source": "template" | "ai",
    }
    """
    ref = _today(as_of)
    feed = build_recommendation_feed(db, tenant_id, as_of=as_of)

    # Executive summary for KPI context
    exec_summary: dict | None = None
    try:
        from ayaz.services.copilot_tools import _get_executive_summary
        exec_summary = _get_executive_summary(db, tenant_id)
    except Exception:
        log.warning("recommendations: exec summary failed", exc_info=True)

    # Pick generator
    try:
        from ayaz.config import settings
        api_key = getattr(settings, "anthropic_api_key", None)
        if api_key:
            generator: Any = _ClaudeStrategyGenerator(api_key)
            return generator.generate(feed, exec_summary, ref)
    except Exception:
        log.warning("recommendations: claude strategy init failed", exc_info=True)

    return _template_strategy(feed, exec_summary, ref)
