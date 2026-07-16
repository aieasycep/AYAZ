"""Hesap Sağlık Taraması (Account Health Audit) service.

Public API
----------
    run_account_audit(db, tenant_id) -> dict

Returns a structured audit report with a 0-100 health score, a letter-grade,
a Turkish summary, and a categorised checklist of findings with fix
recommendations.

Score formula
-------------
Start at 100.  Each ``fail`` deducts 12 points; each ``warn`` deducts 4.
Score is floored at 0 (never negative).

Grade bands
-----------
score >= 85  →  "mukemmel"
score >= 65  →  "iyi"
score >= 40  →  "orta"
else         →  "zayif"

Categories
----------
1. ads       – Ad performance (ROAS, CTR, budget concentration).
2. tracking  – Tracking sources, destinations, event errors, match quality.
3. budget    – Budget plan existence.
4. content   – Content planner workflow status.
5. goals     – Goal progress (at-risk detection).
6. insights  – Persisted insight severity.

Tenant isolation
----------------
Every query carries an explicit tenant_id filter.  This service is read-only;
it never writes to the database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score / grade helpers
# ---------------------------------------------------------------------------

_FAIL_PENALTY = 12
_WARN_PENALTY = 4


def _compute_score(checks: list[dict]) -> int:
    """Compute the aggregate health score from a flat list of check dicts."""
    score = 100
    for c in checks:
        if c["severity"] == "fail":
            score -= _FAIL_PENALTY
        elif c["severity"] == "warn":
            score -= _WARN_PENALTY
    return max(0, score)


def _tr_num(value: float, decimals: int = 1) -> str:
    """Format a number with the Turkish decimal comma (e.g. 0.4 → '0,4')."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _grade(score: int) -> str:
    if score >= 85:
        return "mukemmel"
    if score >= 65:
        return "iyi"
    if score >= 40:
        return "orta"
    return "zayif"


def _counts(checks: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
    for c in checks:
        sev = c["severity"]
        result[sev] = result.get(sev, 0) + 1
    return result


# ---------------------------------------------------------------------------
# Category builders
# ---------------------------------------------------------------------------


def _check_ads(db: Session, tenant_id: uuid.UUID, date_from: Any, date_to: Any) -> dict:
    """Reklam Performansı — analyse ad-level ROAS, CTR, and budget concentration."""
    from ayaz.services.creatives import ad_performance

    checks: list[dict] = []

    try:
        result = ad_performance(db, tenant_id, date_from, date_to, sort="spend")
        ads = result.get("ads", [])

        if not ads:
            checks.append({
                "id": "ads_no_data",
                "severity": "pass",
                "title": "Reklam verisi yok",
                "finding": "Son 30 günde reklam düzeyinde harcama verisi bulunmuyor.",
                "recommendation": "Reklam bağlantılarınızın doğru yapılandırıldığını kontrol edin.",
            })
            return {"key": "ads", "label": "Reklam Performansı", "checks": checks}

        spenders = [a for a in ads if a.get("spend", 0) > 0]

        # --- Fail: any ad with spend>0 and roas < 1.0 ---
        loss_ads = [a for a in spenders if a.get("roas", 0) < 1.0]
        if loss_ads:
            worst = sorted(loss_ads, key=lambda a: a.get("roas", 0))[:3]
            named = ", ".join(
                f"'{a.get('ad_name', '(isimsiz)')}' (ROAS {_tr_num(a.get('roas', 0))}x)"
                for a in worst
            )
            more = (
                f" ve {len(loss_ads) - len(worst)} reklam daha"
                if len(loss_ads) > len(worst)
                else ""
            )
            checks.append({
                "id": "ads_roas_below_1",
                "severity": "fail",
                "title": "Zarar eden reklam(lar)",
                "finding": (
                    f"{len(loss_ads)} reklam zarar ediyor (ROAS<1,0 — harcama "
                    f"dönüşüm değerinin üstünde): {named}{more}."
                ),
                "recommendation": "En düşük getirili reklamları durdurun veya optimize edin.",
            })

        # --- Warn: any single creative > 50% of total spend ---
        total_spend = sum(a.get("spend", 0) for a in spenders)
        if total_spend > 0:
            for a in spenders:
                if a.get("spend", 0) / total_spend > 0.50:
                    checks.append({
                        "id": "ads_budget_concentration",
                        "severity": "warn",
                        "title": "Bütçe yoğunlaşması",
                        "finding": (
                            f"'{a['ad_name']}' reklamı toplam harcamanın "
                            f"%{a['spend'] / total_spend * 100:.0f}'ini alıyor."
                        ),
                        "recommendation": "Bütçeyi çeşitlendirin.",
                    })
                    break  # only one check needed; first offender is sufficient

        # --- Warn: any ad with spend>0 and ctr < 0.5% ---
        low_ctr_ads = [a for a in spenders if a.get("ctr", 1) < 0.005]
        if low_ctr_ads:
            worst_ctr = sorted(low_ctr_ads, key=lambda a: a.get("ctr", 0))[:3]
            named = ", ".join(
                f"'{a.get('ad_name', '(isimsiz)')}' (%{_tr_num(a.get('ctr', 0) * 100)})"
                for a in worst_ctr
            )
            more = (
                f" ve {len(low_ctr_ads) - len(worst_ctr)} reklam daha"
                if len(low_ctr_ads) > len(worst_ctr)
                else ""
            )
            checks.append({
                "id": "ads_low_ctr",
                "severity": "warn",
                "title": "Düşük CTR kreatif(ler)",
                "finding": (
                    f"{len(low_ctr_ads)} reklamın CTR'si %0,5'in altında: {named}{more}."
                ),
                "recommendation": "En düşük CTR'li kreatifleri yenileyin.",
            })

        # --- Pass: no issues found ---
        if not checks:
            checks.append({
                "id": "ads_healthy",
                "severity": "pass",
                "title": "Reklam performansı sağlıklı",
                "finding": "Son 30 günde reklam düzeyinde kritik sorun tespit edilmedi.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: ads category failed", exc_info=True)
        checks.append({
            "id": "ads_error",
            "severity": "warn",
            "title": "Reklam verisi alınamadı",
            "finding": "Reklam performans verileri şu an erişilemez durumda.",
            "recommendation": "Bağlantılarınızı kontrol edin ve taramayı tekrarlayın.",
        })

    return {"key": "ads", "label": "Reklam Performansı", "checks": checks}


def _check_tracking(db: Session, tenant_id: uuid.UUID, date_from: Any, date_to: Any) -> dict:
    """Ölçümleme & CAPI — tracking sources, destinations, error rates, match quality."""
    from sqlalchemy import select
    from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
    from ayaz.api.v1.tracking import compute_tracking_stats

    checks: list[dict] = []

    try:
        sources = list(
            db.scalars(
                select(TrackingSource).where(TrackingSource.tenant_id == tenant_id)
            )
        )

        # --- Fail: no tracking source at all ---
        if not sources:
            checks.append({
                "id": "tracking_no_source",
                "severity": "fail",
                "title": "Ölçümleme kurulu değil",
                "finding": "Kiracıya ait hiç izleme kaynağı bulunamadı.",
                "recommendation": "Bir izleme kaynağı oluşturun.",
            })
            return {"key": "tracking", "label": "Ölçümleme & CAPI", "checks": checks}

        # --- Fail: a source has no active EventDestination ---
        orphan_sources: list[str] = []
        for src in sources:
            destinations = list(
                db.scalars(
                    select(EventDestination).where(
                        EventDestination.tracking_source_id == src.id,
                        EventDestination.tenant_id == tenant_id,
                        EventDestination.is_active.is_(True),
                    )
                )
            )
            if not destinations:
                orphan_sources.append(src.name)

        if orphan_sources:
            checks.append({
                "id": "tracking_no_destination",
                "severity": "fail",
                "title": "Hedefsiz izleme kaynağı",
                "finding": (
                    f"{len(orphan_sources)} izleme kaynağının aktif hedefi yok: "
                    + ", ".join(f"'{n}'" for n in orphan_sources[:3])
                    + ("..." if len(orphan_sources) > 3 else "")
                ),
                "recommendation": "Her izleme kaynağına en az bir aktif hedef ekleyin.",
            })

        # --- Aggregate events for all sources across the date window ---
        date_from_str = date_from.isoformat()
        date_to_str = date_to.isoformat() + "T23:59:59"

        all_events: list[ConversionEvent] = []
        for src in sources:
            src_events = list(
                db.scalars(
                    select(ConversionEvent).where(
                        ConversionEvent.tracking_source_id == src.id,
                        ConversionEvent.tenant_id == tenant_id,
                        ConversionEvent.created_at >= date_from_str,
                        ConversionEvent.created_at <= date_to_str,
                    )
                )
            )
            all_events.extend(src_events)

        if all_events:
            # Aggregate stats across all sources (disabled_events ignored here
            # as we're assessing the overall health picture)
            stats = compute_tracking_stats(all_events, date_from, date_to, disabled_events=[])

            totals = stats.get("totals", {})
            total_events = totals.get("total_events", 0)
            total_errors = totals.get("total_errors", 0)
            consent_blocked = totals.get("consent_blocked", 0)

            # --- Warn: failed events exist ---
            if total_errors > 0:
                checks.append({
                    "id": "tracking_failed_events",
                    "severity": "warn",
                    "title": "Başarısız iletimler",
                    "finding": (
                        f"Son 30 günde {total_errors} başarısız iletim tespit edildi "
                        f"(toplam {total_events} olaydan)."
                    ),
                    "recommendation": "Yeniden gönderin / kimlik doğrulayın.",
                })

            # --- Warn: match quality avg < 50 ---
            mq = stats.get("match_quality")
            if mq is not None and mq.get("avg_score", 100) < 50:
                checks.append({
                    "id": "tracking_low_match_quality",
                    "severity": "warn",
                    "title": "Düşük eşleşme kalitesi",
                    "finding": (
                        f"Ortalama eşleşme puanı {mq['avg_score']}/100 "
                        f"({mq.get('scored_events', 0)} değerlendirilen olay)."
                    ),
                    "recommendation": "Daha fazla kimlik sinyali gönderin.",
                })

            # --- Warn: skipped_no_consent share > 20% ---
            if total_events > 0 and consent_blocked / total_events > 0.20:
                pct = consent_blocked / total_events * 100
                checks.append({
                    "id": "tracking_consent_drop",
                    "severity": "warn",
                    "title": "Rıza ile düşen olaylar yüksek",
                    "finding": (
                        f"Olayların %{pct:.0f}'i rıza yokluğu nedeniyle iletilmedi "
                        f"({consent_blocked}/{total_events})."
                    ),
                    "recommendation": "Kullanıcı rızası alım sürecinizi gözden geçirin.",
                })

        # --- Pass: no issues ---
        if not checks:
            checks.append({
                "id": "tracking_healthy",
                "severity": "pass",
                "title": "Ölçümleme sağlıklı",
                "finding": "İzleme kaynakları ve iletimler sorunsuz görünüyor.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: tracking category failed", exc_info=True)
        checks.append({
            "id": "tracking_error",
            "severity": "warn",
            "title": "Ölçümleme verisi alınamadı",
            "finding": "İzleme verileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "tracking", "label": "Ölçümleme & CAPI", "checks": checks}


def _check_budget(db: Session, tenant_id: uuid.UUID) -> dict:
    """Bütçe & Planlama — check if a budget plan exists."""
    from ayaz.services.copilot_tools import _get_budget_status

    checks: list[dict] = []

    try:
        status = _get_budget_status(db, tenant_id)

        if not status.get("has_plan"):
            checks.append({
                "id": "budget_no_plan",
                "severity": "warn",
                "title": "Bütçe planı yok",
                "finding": "Bu ay için tanımlanmış bir bütçe planı bulunamadı.",
                "recommendation": "Aylık plan oluşturun.",
            })
        else:
            plan_name = status.get("name", "")
            period = status.get("period_month", "")
            checks.append({
                "id": "budget_plan_exists",
                "severity": "pass",
                "title": "Bütçe planı mevcut",
                "finding": f"'{plan_name}' planı ({period}) aktif durumda.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: budget category failed", exc_info=True)
        checks.append({
            "id": "budget_error",
            "severity": "warn",
            "title": "Bütçe verisi alınamadı",
            "finding": "Bütçe bilgileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "budget", "label": "Bütçe & Planlama", "checks": checks}


def _check_content(db: Session, tenant_id: uuid.UUID) -> dict:
    """İçerik — check pending approvals and scheduled posts."""
    from ayaz.services.copilot_tools import _get_content_status

    checks: list[dict] = []

    try:
        status = _get_content_status(db, tenant_id)

        pending_approval = status.get("pending_approval", 0)
        scheduled = status.get("scheduled", 0)
        draft = status.get("draft", 0)

        if pending_approval > 0:
            checks.append({
                "id": "content_pending_approval",
                "severity": "warn",
                "title": "Onay bekleyen içerik",
                "finding": f"{pending_approval} içerik yayına alınmayı bekliyor.",
                "recommendation": "İçerikleri inceleyin ve onaylayın.",
            })

        if scheduled == 0 and draft > 0:
            checks.append({
                "id": "content_no_scheduled",
                "severity": "warn",
                "title": "Planlanmış içerik yok",
                "finding": f"{draft} taslak var ancak planlanmış yayın bulunmuyor.",
                "recommendation": "Taslakları zamanlayarak içerik takvimini doldurun.",
            })

        if not checks:
            checks.append({
                "id": "content_healthy",
                "severity": "pass",
                "title": "İçerik planlama sağlıklı",
                "finding": "Bekleyen onay yok ve içerikler planlanmış durumda.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: content category failed", exc_info=True)
        checks.append({
            "id": "content_error",
            "severity": "warn",
            "title": "İçerik verisi alınamadı",
            "finding": "İçerik planlama verileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "content", "label": "İçerik", "checks": checks}


def _check_goals(db: Session, tenant_id: uuid.UUID) -> dict:
    """Hedefler — check for at-risk goals."""
    from ayaz.services.copilot_tools import _get_goal_progress

    checks: list[dict] = []

    try:
        result = _get_goal_progress(db, tenant_id)
        goals = result.get("goals", [])

        if not goals:
            checks.append({
                "id": "goals_none_defined",
                "severity": "pass",
                "title": "Hedef tanımlı değil",
                "finding": "Bu kiracı için henüz aktif hedef tanımlanmamış.",
                "recommendation": "Hedefler ekleyerek performansı takip edin.",
            })
            return {"key": "goals", "label": "Hedefler", "checks": checks}

        # at-risk: status not on-track. pct_to_target is a 0..1+ RATIO.
        # Spend (budget) goals can be flagged for overrun — for them a
        # realized ratio >= 1.0 IS the problem, so only non-spend goals that
        # already achieved their target are excluded.
        at_risk = [
            g for g in goals
            if g.get("status") != "on_track"
            and (
                g.get("metric") == "spend"
                or (g.get("pct_to_target") or 0) < 1.0
            )
        ]

        if at_risk:
            names = ", ".join(f"'{g['name']}'" for g in at_risk[:3])
            if len(at_risk) > 3:
                names += "..."
            checks.append({
                "id": "goals_at_risk",
                "severity": "warn",
                "title": "Risk altındaki hedef(ler)",
                # Direction-neutral wording: the list may mix behind-pace
                # growth goals and overrun-pacing budget goals.
                "finding": (
                    f"{len(at_risk)} hedef plandan sapmış durumda: {names}."
                ),
                "recommendation": "Hedef stratejinizi ve bütçe tahsisinizi gözden geçirin.",
            })

        if not checks:
            checks.append({
                "id": "goals_on_track",
                "severity": "pass",
                "title": "Tüm hedefler yolunda",
                "finding": f"{len(goals)} aktif hedefin tamamı hedefte veya üstünde.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: goals category failed", exc_info=True)
        checks.append({
            "id": "goals_error",
            "severity": "warn",
            "title": "Hedef verisi alınamadı",
            "finding": "Hedef verileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "goals", "label": "Hedefler", "checks": checks}


def _check_data_quality(db: Session, tenant_id: uuid.UUID) -> dict:
    """Veri Kalitesi — check for duplicate ConnectedAccounts and KPI inconsistencies."""
    from ayaz.services.data_quality import detect_duplicate_accounts, detect_kpi_inconsistencies

    checks: list[dict] = []

    try:
        date_to = datetime.now(timezone.utc).date()
        date_from = date_to - timedelta(days=29)

        dupes = detect_duplicate_accounts(db, tenant_id)
        if dupes:
            dupe_summary = "; ".join(
                f"{d['platform']}/{d['external_account_id']} ({d['count']}x)"
                for d in dupes[:3]
            )
            if len(dupes) > 3:
                dupe_summary += "..."
            checks.append({
                "id": "data_quality_duplicate_accounts",
                "severity": "fail",
                "title": f"{len(dupes)} yinelenen hesap bağlantısı",
                "finding": (
                    f"Aynı harici hesap birden fazla kez bağlanmış: {dupe_summary}. "
                    f"Bu durum tüm metrik toplamlarında çift sayıma yol açmaktadır."
                ),
                "recommendation": "Yinelenen hesap bağlantılarını kaldırın.",
            })

        inconsistencies = detect_kpi_inconsistencies(db, tenant_id, date_from, date_to)
        if inconsistencies:
            rules = sorted({i["rule"] for i in inconsistencies})
            checks.append({
                "id": "data_quality_kpi_inconsistency",
                "severity": "warn",
                "title": "KPI tutarsızlıkları tespit edildi",
                "finding": (
                    f"{len(inconsistencies)} satırda veri tutarsızlığı bulundu "
                    f"(kurallar: {', '.join(rules)})."
                ),
                "recommendation": (
                    "Bağlı hesap veri akışını ve izleme yapılandırmasını kontrol edin."
                ),
            })

        if not checks:
            checks.append({
                "id": "data_quality_healthy",
                "severity": "pass",
                "title": "Veri kalitesi sağlıklı",
                "finding": "Yinelenen hesap veya KPI tutarsızlığı tespit edilmedi.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: data_quality category failed", exc_info=True)
        checks.append({
            "id": "data_quality_error",
            "severity": "warn",
            "title": "Veri kalitesi kontrolü yapılamadı",
            "finding": "Veri kalitesi kontrol verileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "data_quality", "label": "Veri Kalitesi", "checks": checks}


def _check_insights(db: Session, tenant_id: uuid.UUID) -> dict:
    """İçgörüler — check for critical and warning-level insights."""
    from ayaz.services.copilot_tools import _get_insights

    checks: list[dict] = []

    try:
        # Fetch all insights (no severity filter → get everything)
        result = _get_insights(db, tenant_id)
        insights = result.get("insights", [])

        if not insights:
            checks.append({
                "id": "insights_none",
                "severity": "pass",
                "title": "Aktif içgörü yok",
                "finding": "Sistemde tespit edilmiş kritik ya da uyarı düzeyinde içgörü bulunmuyor.",
                "recommendation": "",
            })
            return {"key": "insights", "label": "İçgörüler", "checks": checks}

        critical_items = [i for i in insights if i.get("severity") == "critical"]
        warning_items = [i for i in insights if i.get("severity") == "warning"]

        if critical_items:
            checks.append({
                "id": "insights_critical",
                "severity": "fail",
                "title": "Kritik içgörüler mevcut",
                "finding": f"{len(critical_items)} kritik içgörü acil dikkat gerektiriyor.",
                "recommendation": "İçgörüler panelini açarak kritik bulguları inceleyin ve aksiyona geçin.",
            })

        if warning_items:
            checks.append({
                "id": "insights_warnings",
                "severity": "warn",
                "title": "Uyarı içgörüleri mevcut",
                "finding": f"{len(warning_items)} uyarı içgörüsü dikkat gerektiriyor.",
                "recommendation": "İçgörüler panelini inceleyerek uyarıları değerlendirin.",
            })

        if not checks:
            checks.append({
                "id": "insights_info_only",
                "severity": "pass",
                "title": "Yalnızca bilgi düzeyinde içgörüler",
                "finding": "Kritik ya da uyarı içgörüsü yok; yalnızca bilgi niteliğinde bulgular mevcut.",
                "recommendation": "",
            })

    except Exception:
        log.warning("audit: insights category failed", exc_info=True)
        checks.append({
            "id": "insights_error",
            "severity": "warn",
            "title": "İçgörü verisi alınamadı",
            "finding": "İçgörü verileri şu an erişilemez durumda.",
            "recommendation": "Taramayı daha sonra tekrarlayın.",
        })

    return {"key": "insights", "label": "İçgörüler", "checks": checks}


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _build_summary(score: int, grade: str, categories: list[dict]) -> str:
    """Build a Turkish natural-language one/two-liner summary."""
    # Find the category with the most failures or warnings (biggest issue area)
    worst_category: str | None = None
    worst_fail_count = 0
    worst_warn_count = 0

    for cat in categories:
        fails = sum(1 for c in cat["checks"] if c["severity"] == "fail")
        warns = sum(1 for c in cat["checks"] if c["severity"] == "warn")
        if fails > worst_fail_count or (fails == worst_fail_count and warns > worst_warn_count):
            worst_fail_count = fails
            worst_warn_count = warns
            worst_category = cat["label"]

    grade_tr = {
        "mukemmel": "Mükemmel",
        "iyi": "İyi",
        "orta": "Orta",
        "zayif": "Zayıf",
    }.get(grade, grade.capitalize())

    base = f"Hesap sağlık puanınız {score}/100 ({grade_tr})."

    if worst_category and (worst_fail_count > 0 or worst_warn_count > 0):
        if worst_fail_count > 0:
            detail = f" En fazla sorun '{worst_category}' kategorisinde tespit edildi — hemen incelemeniz önerilir."
        else:
            detail = f" '{worst_category}' kategorisinde dikkat edilmesi gereken uyarılar var."
        return base + detail

    return base + " Hesabınız genel olarak sağlıklı görünüyor."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_account_audit(db: Session, tenant_id: uuid.UUID) -> dict:
    """Run the full account health audit for the given tenant.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries issued).
    tenant_id:
        Tenant UUID — all queries are explicitly scoped to this tenant.

    Returns
    -------
    dict with keys:
        score       int 0-100
        grade       "mukemmel" | "iyi" | "orta" | "zayif"
        summary     Turkish one/two-liner
        counts      {"pass": int, "warn": int, "fail": int}
        categories  list of category dicts, each with:
                        key, label, checks (list of check dicts)
    """
    date_to = datetime.now(timezone.utc).date()
    date_from = date_to - timedelta(days=29)

    categories = [
        _check_ads(db, tenant_id, date_from, date_to),
        _check_tracking(db, tenant_id, date_from, date_to),
        _check_budget(db, tenant_id),
        _check_content(db, tenant_id),
        _check_goals(db, tenant_id),
        _check_insights(db, tenant_id),
        _check_data_quality(db, tenant_id),
    ]

    all_checks = [c for cat in categories for c in cat["checks"]]

    score = _compute_score(all_checks)
    grade = _grade(score)
    counts = _counts(all_checks)
    summary = _build_summary(score, grade, categories)

    return {
        "score": score,
        "grade": grade,
        "summary": summary,
        "counts": counts,
        "categories": categories,
    }
