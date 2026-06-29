"""Pazarlama Sağlık Endeksi (Marketing Health Index) servisi.

CMO / Yönetim personası için tek bir stratejik 0-100 skoru üretir;
mevcut modüllerdeki 6 boyutu sentezler.

Genel API
---------
    build_health_index(db, tenant_id, *, as_of=None) -> dict

Boyutlar ve kaynak eşlemeleri
------------------------------
    hesap_sagligi   — audit.run_account_audit     → audit.score (0-100)
    sektor_konumu   — benchmark.build_benchmark   → summary_counts ağırlıklı
    kvkk_uyum       — consent_center.build_consent_center → compliance.score
    donusum         — funnel.build_funnel         → overall_conversion_pct
    hedef_ilerleme  — copilot_tools._get_goal_progress → on_track oranı
    butce_disiplini — budget_planner.plan_actuals → pace_pct ile time_pace_pct farkı

Puan hesaplama
--------------
overall_score = round(None-olmayan boyutların ortalaması)

Derece bantları (audit.py ile aynı)
------------------------------------
score >= 85 → "mukemmel"
score >= 65 → "iyi"
score >= 40 → "orta"
else        → "zayif"

Dönüşüm skalası (heuristic)
----------------------------
overall_conversion_pct 10% veya üzeri → 100 puan.
Formula: min(100, round(overall_conversion_pct / 10.0 * 100))
Örnek: %5 → 50, %10 → 100, %15 → 100.

Sektör konumu skalası
----------------------
score = round((strong*100 + average*60 + weak*20) / total)
total = strong + average + weak  (None ise total==0)

Bütçe disiplini skalası
-----------------------
score = clamp(0, 100, round(100 - abs(pace_pct - time_pace_pct)))
Yani: tempo farkı sıfır → 100, fark 100 → 0.

Kiracı yalıtımı
---------------
Tüm sorgular tenant_id filtresiyle kısıtlanır; kaynak servislerin kendi
izolasyon güvenceleri bu servis için de geçerlidir.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ── Derece bantları ────────────────────────────────────────────────────────────


def _grade(score: int | None) -> str | None:
    """0-100 skoru için Türkçe derece döner. None girişi → None."""
    if score is None:
        return None
    if score >= 85:
        return "mukemmel"
    if score >= 65:
        return "iyi"
    if score >= 40:
        return "orta"
    return "zayif"


def _clamp(lo: int, hi: int, value: int) -> int:
    return max(lo, min(hi, value))


# ── Boyut hesaplayıcılar ──────────────────────────────────────────────────────


def _dim_hesap_sagligi(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Hesap Sağlığı — run_account_audit.score → puan."""
    try:
        from ayaz.services.audit import run_account_audit

        result = run_account_audit(db, tenant_id)
        score = int(result["score"])
        return {
            "score": score,
            "status": "ok",
            "detail": f"Hesap sağlık taraması: {score}/100",
        }
    except Exception:
        log.warning("health_index: hesap_sagligi failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "Hesap sağlık verisi alınamadı"}


def _dim_sektor_konumu(db: Session, tenant_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    """Sektör Konumu — benchmark.summary_counts ağırlıklı skor.

    Ağırlıklar: strong=100, average=60, weak=20
    score = round((strong*100 + average*60 + weak*20) / total)
    total=0 → None
    """
    try:
        from ayaz.services.benchmark import build_benchmark

        date_to = as_of
        date_from = as_of - timedelta(days=29)
        result = build_benchmark(db, tenant_id, date_from, date_to)
        counts = result["summary_counts"]
        strong = counts.get("strong", 0)
        average = counts.get("average", 0)
        weak = counts.get("weak", 0)
        total = strong + average + weak

        if total == 0:
            return {
                "score": None,
                "status": "veri_yok",
                "detail": "Sektör kıyaslama verisi yok",
            }

        score = round((strong * 100 + average * 60 + weak * 20) / total)
        return {
            "score": score,
            "status": "ok",
            "detail": f"Sektör kıyaslaması: {strong} güçlü, {average} ortalama, {weak} zayıf",
        }
    except Exception:
        log.warning("health_index: sektor_konumu failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "Sektör kıyaslama verisi alınamadı"}


def _dim_kvkk_uyum(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """KVKK Uyumu — consent_center.compliance.score → puan."""
    try:
        from ayaz.services.consent_center import build_consent_center

        result = build_consent_center(db, tenant_id)
        compliance = result.get("compliance", {})
        score = int(compliance.get("score", 0))
        grade_label = compliance.get("grade", "")
        return {
            "score": score,
            "status": "ok",
            "detail": f"KVKK uyum skoru: {score}/100 ({grade_label})",
        }
    except Exception:
        log.warning("health_index: kvkk_uyum failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "KVKK uyum verisi alınamadı"}


def _dim_donusum(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Dönüşüm — funnel.overall_conversion_pct → 0-100 skalası.

    Skalama: min(100, round(overall_conversion_pct / 10.0 * 100))
    Yorum: %10 ve üzeri dönüşüm oranı → 100 puan (heuristic eşik).
    entry_count == 0 → None (huni verisi yok).
    """
    try:
        from ayaz.services.funnel import build_funnel

        today = date.today()
        date_to = today.isoformat()
        date_from = (today - timedelta(days=29)).isoformat()
        result = build_funnel(db, tenant_id, date_from=date_from, date_to=date_to)

        if result.get("entry_count", 0) == 0:
            return {
                "score": None,
                "status": "veri_yok",
                "detail": "Dönüşüm hunisi verisi yok (giriş olayı yok)",
            }

        pct = result.get("overall_conversion_pct", 0.0) or 0.0
        score = min(100, round(pct / 10.0 * 100))
        return {
            "score": score,
            "status": "ok",
            "detail": f"Genel dönüşüm oranı: %{pct:.2f} → {score}/100",
        }
    except Exception:
        log.warning("health_index: donusum failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "Dönüşüm hunisi verisi alınamadı"}


def _dim_hedef_ilerleme(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Hedef İlerleme — aktif hedeflerin on_track/achieved oranı.

    Hedef statüsü "on_track" olan (ya da pct_to_target >= 1.0 olanlar)
    hedefe ulaşmış/yolunda sayılır.
    score = round(yolunda_olan / toplam * 100)
    Hedef yok → None.
    """
    try:
        from ayaz.services.copilot_tools import _get_goal_progress

        result = _get_goal_progress(db, tenant_id)
        goals = result.get("goals", [])

        if not goals:
            return {
                "score": None,
                "status": "veri_yok",
                "detail": "Aktif hedef tanımlanmamış",
            }

        total = len(goals)
        # "on_track" statüsündekiler veya hedefe ulaşmışlar (pct_to_target >= 1.0)
        on_track = sum(
            1 for g in goals
            if g.get("status") == "on_track" or (g.get("pct_to_target") or 0) >= 1.0
        )
        score = round(on_track / total * 100)
        return {
            "score": score,
            "status": "ok",
            "detail": f"{on_track}/{total} hedef yolunda veya tamamlandı",
        }
    except Exception:
        log.warning("health_index: hedef_ilerleme failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "Hedef ilerleme verisi alınamadı"}


def _dim_butce_disiplini(db: Session, tenant_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    """Bütçe Disiplini — pace_pct ile time_pace_pct arasındaki farktan skor.

    Aktif (veya en güncel) plan bulunur; plan_actuals üzerinden:
        score = clamp(0, 100, round(100 - abs(pace_pct - time_pace_pct)))
    Yani: fark ne kadar küçükse skor o kadar yüksek.
    Plan yoksa ya da veri alınamazsa → None.
    """
    try:
        from ayaz.models.budget import BudgetPlan
        from ayaz.services.budget_planner import plan_actuals
        from sqlalchemy import select

        # İçinde bulunulan ayın planını tercih et (gerçek tempo orada hesaplanır);
        # yoksa en güncel plana düş. Bu, Komuta Merkezi ile tutarlıdır.
        current_month = as_of.strftime("%Y-%m")
        plan = db.scalar(
            select(BudgetPlan)
            .where(
                BudgetPlan.tenant_id == tenant_id,
                BudgetPlan.period_month == current_month,
            )
            .order_by(BudgetPlan.created_at.desc())
        )
        if plan is None:
            plan = db.scalar(
                select(BudgetPlan)
                .where(BudgetPlan.tenant_id == tenant_id)
                .order_by(
                    BudgetPlan.status.asc(),
                    BudgetPlan.created_at.desc(),
                )
            )

        if plan is None:
            return {
                "score": None,
                "status": "veri_yok",
                "detail": "Bütçe planı bulunamadı",
            }

        actuals = plan_actuals(db, tenant_id, plan, as_of=as_of)
        totals = actuals.get("totals", {})
        pace_pct = totals.get("pace_pct")
        time_pace_pct = totals.get("time_pace_pct")

        if pace_pct is None or time_pace_pct is None:
            return {
                "score": None,
                "status": "veri_yok",
                "detail": "Bütçe tempo verisi hesaplanamadı",
            }

        diff = abs(float(pace_pct) - float(time_pace_pct))
        score = _clamp(0, 100, round(100 - diff))
        return {
            "score": score,
            "status": "ok",
            "detail": (
                f"Harcama temposu %{pace_pct:.1f}, zaman temposu %{time_pace_pct:.1f} "
                f"(fark {diff:.1f} puan)"
            ),
        }
    except Exception:
        log.warning("health_index: butce_disiplini failed", exc_info=True)
        return {"score": None, "status": "veri_yok", "detail": "Bütçe disiplin verisi alınamadı"}


# ── Genel API ─────────────────────────────────────────────────────────────────


def build_health_index(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> dict:
    """Pazarlama Sağlık Endeksi'ni hesaplar.

    Parameters
    ----------
    db:
        SQLAlchemy Session (yalnızca okuma sorguları gönderir).
    tenant_id:
        Kiracı UUID — tüm alt sorgular bu kiracıyla sınırlıdır.
    as_of:
        Hesaplama tarihi; None ise bugün UTC kullanılır.

    Returns
    -------
    Sabit şemalı dict:

        {
            "generated_at": ISO str,
            "overall_score": int,
            "overall_grade": str,
            "dimensions": [
                {
                    "key": str, "label": str,
                    "score": int | None, "grade": str | None,
                    "status": "ok" | "veri_yok",
                    "detail": str, "href": str, "weight": 1,
                }
            ],
            "summary": {
                "strong_count": int,    # score >= 85 olan boyutlar
                "weak_count": int,      # score < 40 olan boyutlar (None hariç)
                "scored_count": int,    # None olmayan boyut sayısı
            },
        }
    """
    _as_of: date = as_of or datetime.now(timezone.utc).date()
    generated_at = datetime.now(timezone.utc).isoformat()

    # ── 6 boyutu hesapla ──────────────────────────────────────────────────────
    # Her boyut kendi içinde de try/except ile korunur (bkz. _dim_* fonksiyonları).
    # Ek olarak, build_health_index seviyesinde de her çağrıyı sarıyoruz;
    # böylece patch/mock senaryolarında dış hata boyutu "veri_yok" olarak düşürür.
    _FALLBACK = {"score": None, "status": "veri_yok", "detail": "Veri alınamadı"}

    def _safe(fn, *args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.warning("health_index: dimension call failed", exc_info=True)
            return _FALLBACK.copy()

    raw: list[tuple[str, str, str, dict]] = [
        # (key, label_tr, href, result_dict)
        ("hesap_sagligi", "Hesap Sağlığı", "/audit",
         _safe(_dim_hesap_sagligi, db, tenant_id)),
        ("sektor_konumu", "Sektör Konumu", "/benchmark",
         _safe(_dim_sektor_konumu, db, tenant_id, _as_of)),
        ("kvkk_uyum", "KVKK Uyumu", "/consent",
         _safe(_dim_kvkk_uyum, db, tenant_id)),
        ("donusum", "Dönüşüm", "/funnel",
         _safe(_dim_donusum, db, tenant_id)),
        ("hedef_ilerleme", "Hedef İlerleme", "/goals",
         _safe(_dim_hedef_ilerleme, db, tenant_id)),
        ("butce_disiplini", "Bütçe Disiplini", "/planning",
         _safe(_dim_butce_disiplini, db, tenant_id, _as_of)),
    ]

    # ── Boyut listesi oluştur ─────────────────────────────────────────────────
    dimensions: list[dict] = []
    for key, label, href, res in raw:
        score = res["score"]
        status = res["status"]
        detail = res.get("detail", "")
        grade = _grade(score)
        dimensions.append({
            "key": key,
            "label": label,
            "score": score,
            "grade": grade,
            "status": status,
            "detail": detail,
            "href": href,
            "weight": 1,
        })

    # ── Genel skor ────────────────────────────────────────────────────────────
    scored = [d for d in dimensions if d["score"] is not None]
    scored_count = len(scored)

    if scored:
        overall_score: int = round(sum(d["score"] for d in scored) / scored_count)
    else:
        overall_score = 0

    overall_grade: str = _grade(overall_score) or "zayif"

    # ── Özet sayıları ─────────────────────────────────────────────────────────
    strong_count = sum(1 for d in scored if d["score"] >= 85)
    weak_count = sum(1 for d in scored if d["score"] < 40)

    return {
        "generated_at": generated_at,
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "dimensions": dimensions,
        "summary": {
            "strong_count": strong_count,
            "weak_count": weak_count,
            "scored_count": scored_count,
        },
    }
