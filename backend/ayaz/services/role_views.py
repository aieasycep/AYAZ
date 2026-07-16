"""Rol Görünümü (Role-based views) service — Dalga 75.

Her pazarlama ekibine kendi önceliklerine göre özelleştirilmiş bir kokpit
sunar.  Veriler tamamen mevcut servislerden okunur; yeni model veya migration
yoktur.

Public API
----------
    list_roles() -> list[dict]
        Tanımlı rollerin kısa listesini döndürür.
        [{key, label, description, icon_key}]

    get_role_view(db, tenant_id, role) -> dict
        Verilen rol için tam görünümü döndürür.
        Bilinmeyen rol → ValueError.

Kilitli dönüş şekli
--------------------
{
    "role": str,
    "label": str,
    "description": str,
    "icon_key": str,
    "generated_at": ISO str,
    "metrics": [{"label": str, "value": str, "hint": str}],   # 3-5 KPI
    "attention": [{"title": str, "detail": str,
                   "severity": "high"|"medium"|"low", "href": str}],  # ≤4
    "priority_screens": [{"href": str, "label": str, "why": str}],
    "quick_actions": [{"label": str, "href": str}],
}

Tenant izolasyonu
-----------------
Her DB çağrısı tenant_id ile filtrelenir; servis katmanı bu garantiyi uygular.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ayaz.services.trformat import tr_int, tr_pct, tr_roas, tr_tl

log = logging.getLogger(__name__)

# ── Rol tanımları ──────────────────────────────────────────────────────────────

ROLE_DEFINITIONS: list[dict] = [
    {
        "key": "performans",
        "label": "Performans Pazarlamacısı",
        "description": (
            "Reklam kampanyalarını, bütçe kullanımını ve kanal performansını "
            "günlük bazda takip eder; dönüşüm ve ROAS odaklı optimize eder."
        ),
        "icon_key": "trending",
        "priority_screens": [
            {
                "href": "/dashboard",
                "label": "Kontrol Paneli",
                "why": "Günlük harcama, ROAS ve dönüşüm özetine hızlıca ulaş.",
            },
            {
                "href": "/optimizer",
                "label": "Optimizasyon Merkezi",
                "why": "Düşük performanslı kampanyaları otomatik tespitle optimize et.",
            },
            {
                "href": "/ads",
                "label": "Reklam Kampanyaları",
                "why": "Kampanya bazlı metrikleri görüntüle ve karşılaştır.",
            },
            {
                "href": "/recommendations",
                "label": "Öneri Akışı",
                "why": "Aksiyon gerektiren yüksek etkili önerileri önceliklendir.",
            },
        ],
        "quick_actions": [
            {"label": "Kampanyaları Görüntüle", "href": "/ads"},
            {"label": "Optimizasyonu Başlat", "href": "/optimizer"},
            {"label": "Öneri Akışını Aç", "href": "/recommendations"},
        ],
        "rec_categories": ["performance", "budget", "audit"],
    },
    {
        "key": "marcom",
        "label": "Marka & İçerik (Marcom)",
        "description": (
            "Marka iletişimini, sosyal medya içerik takvimine ve reklam "
            "kreatiflerine odaklanarak yönetir."
        ),
        "icon_key": "palette",
        "priority_screens": [
            {
                "href": "/content",
                "label": "İçerik Planlayıcı",
                "why": "Sosyal medya içerik takvimine göz at ve yeni içerik ekle.",
            },
            {
                "href": "/creative-lens",
                "label": "Kreatif Lens",
                "why": "Marka görsel ve metin performansını analiz et.",
            },
            {
                "href": "/ad-studio",
                "label": "Reklam Stüdyosu",
                "why": "Reklam kopyaları oluştur ve düzenle.",
            },
            {
                "href": "/creatives",
                "label": "Kreatifler",
                "why": "Tüm reklam kreatifleri kütüphanesini yönet.",
            },
        ],
        "quick_actions": [
            {"label": "Yeni İçerik Oluştur", "href": "/content"},
            {"label": "Reklam Kopyası Yaz", "href": "/ad-studio"},
            {"label": "Kreatifleri Görüntüle", "href": "/creatives"},
        ],
        "rec_categories": ["content"],
    },
    {
        "key": "musteri_hizmetleri",
        "label": "Müşteri Hizmetleri",
        "description": (
            "Sosyal medya mesajlarını, müşteri yorumlarını ve gelen kutusunu "
            "takip ederek yanıt sürelerini ve memnuniyeti yönetir."
        ),
        "icon_key": "chat",
        "priority_screens": [
            {
                "href": "/inbox",
                "label": "Sosyal Gelen Kutusu",
                "why": "Tüm kanallardan gelen müşteri mesajlarını tek ekranda yönet.",
            },
        ],
        "quick_actions": [
            {"label": "Gelen Kutusunu Aç", "href": "/inbox"},
            {"label": "Bekleyen Mesajları Gör", "href": "/inbox?filter=pending"},
        ],
        "rec_categories": ["inbox"],
    },
    {
        "key": "planlama",
        "label": "Planlama & Bütçe",
        "description": (
            "Aylık bütçe planlarını, kanal dağılımlarını ve pazarlama "
            "hedeflerinin ilerleme durumunu yönetir."
        ),
        "icon_key": "calendar",
        "priority_screens": [
            {
                "href": "/planning",
                "label": "Bütçe Planlama",
                "why": "Aylık bütçe planını oluştur ve gerçekleşen harcamayla karşılaştır.",
            },
            {
                "href": "/optimizer?tab=senaryo",
                "label": "Bütçe Simülatörü",
                "why": "Farklı bütçe senaryolarının etkisini simüle et.",
            },
            {
                "href": "/goals",
                "label": "Hedefler",
                "why": "KPI hedeflerinin ilerleme durumunu takip et.",
            },
        ],
        "quick_actions": [
            {"label": "Bütçe Planını Aç", "href": "/planning"},
            {"label": "Hedefleri Görüntüle", "href": "/goals"},
            {"label": "Simülasyon Çalıştır", "href": "/optimizer?tab=senaryo"},
        ],
        "rec_categories": ["budget", "goal"],
    },
    {
        "key": "yonetim",
        "label": "Yönetim (CMO/CEO)",
        "description": (
            "Tüm pazarlama performansını üst düzey KPI'lar, sektör kıyaslaması "
            "ve stratejik önerilerle izler."
        ),
        "icon_key": "chart",
        "priority_screens": [
            {
                "href": "/executive",
                "label": "Yönetici Özeti",
                "why": "Son 30 günün harcama, ROAS ve dönüşüm özetine bak.",
            },
            {
                "href": "/command-center",
                "label": "Komuta Merkezi",
                "why": "Tüm kanalların anlık durumunu tek ekrandan izle.",
            },
            {
                "href": "/reports",
                "label": "Raporlar",
                "why": "Detaylı performans raporlarını görüntüle ve dışa aktar.",
            },
            {
                "href": "/benchmark",
                "label": "Sektör Kıyaslaması",
                "why": "Hesap metriklerini sektör ortalamasıyla karşılaştır.",
            },
            {
                "href": "/consent",
                "label": "Rıza Merkezi",
                "why": "Veri gizliliği ve KVKK uyum durumunu gözden geçir.",
            },
        ],
        "quick_actions": [
            {"label": "Yönetici Özetini Aç", "href": "/executive"},
            {"label": "Kıyaslama Raporunu Gör", "href": "/benchmark"},
            {"label": "Raporları Görüntüle", "href": "/reports"},
        ],
        "rec_categories": ["benchmark", "goal", "performance"],
    },
]

# Hızlı arama için anahtar → tanım dict'i
_ROLE_MAP: dict[str, dict] = {r["key"]: r for r in ROLE_DEFINITIONS}


# ── Yardımcı biçimleyiciler ────────────────────────────────────────────────────


# Rol panosu kartları kullanıcıya dönük; sayılar TR biçimden (binlik=nokta,
# ondalık=virgül, % önde) geçmeli — hepsi ortak trformat modülüne yönlendirildi.
def _fmt_tl(value: float) -> str:
    """₺ ile biçimlendirilmiş para birimi dizesi (₺125.000)."""
    return tr_tl(value)


def _fmt_roas(value: float) -> str:
    return tr_roas(value)


def _fmt_pct(value: float) -> str:
    return tr_pct(value)


def _fmt_int(value: float) -> str:
    return tr_int(value)


# ── Metrik toplayıcılar (rol bazlı) ───────────────────────────────────────────


def _metrics_performans(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Harcama, ROAS, dönüşüm, TO metriklerini döndürür."""
    from datetime import date, timedelta
    from ayaz.services.copilot_tools import _get_performance_summary

    today = date.today()
    date_from = (today - timedelta(days=29)).isoformat()
    date_to = today.isoformat()

    try:
        data = _get_performance_summary(db, tenant_id, date_from, date_to)
        totals = data.get("totals", {})
        return [
            {
                "label": "Toplam Harcama",
                "value": _fmt_tl(totals.get("spend", 0)),
                "hint": "Son 30 gün toplam reklam harcaması",
            },
            {
                "label": "ROAS",
                "value": _fmt_roas(totals.get("roas", 0)),
                "hint": "Harcama başına dönüşüm geliri",
            },
            {
                "label": "Dönüşüm",
                "value": _fmt_int(totals.get("conversions", 0)),
                "hint": "Son 30 günde toplam dönüşüm sayısı",
            },
            {
                "label": "TO (CTR)",
                "value": _fmt_pct(totals.get("ctr", 0) * 100),
                "hint": "Tıklama / gösterim oranı",
            },
        ]
    except Exception:
        log.warning("role_views: performans metrikleri alınamadı", exc_info=True)
        return []


def _metrics_marcom(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """İçerik durumu metriklerini döndürür."""
    from ayaz.services.copilot_tools import _get_content_status

    try:
        data = _get_content_status(db, tenant_id)
        return [
            {
                "label": "Planlanan İçerik",
                "value": _fmt_int(data.get("scheduled", 0)),
                "hint": "Zamanlanmış yayın sayısı",
            },
            {
                "label": "Taslak İçerik",
                "value": _fmt_int(data.get("draft", 0)),
                "hint": "Tamamlanmamış taslak sayısı",
            },
            {
                "label": "Yayınlanan İçerik",
                "value": _fmt_int(data.get("published", 0)),
                "hint": "Yayınlanmış içerik sayısı",
            },
        ]
    except Exception:
        log.warning("role_views: marcom metrikleri alınamadı", exc_info=True)
        return []


def _metrics_musteri_hizmetleri(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Gelen kutusu istatistiklerini döndürür."""
    from ayaz.services.copilot_tools import _get_inbox_summary

    try:
        data = _get_inbox_summary(db, tenant_id)
        # Ortalama yanıt süresini hesapla (mesaj sayısına dayalı basit tahmin)
        open_count = data.get("open", 0)
        pending_count = data.get("pending", 0)
        # avg_response_hours: alan yoksa basit bir gösterge kullan
        avg_hint = "Var olan mesaj sayısına göre"
        return [
            {
                "label": "Açık Mesaj",
                "value": _fmt_int(open_count),
                "hint": "Yanıt bekleyen açık mesaj sayısı",
            },
            {
                "label": "Bekleyen Mesaj",
                "value": _fmt_int(pending_count),
                "hint": "İşlemde olan mesaj sayısı",
            },
            {
                "label": "Toplam Mesaj",
                "value": _fmt_int(data.get("total", 0)),
                "hint": "Tüm kanallardaki toplam mesaj",
            },
        ]
    except Exception:
        log.warning("role_views: müşteri hizmetleri metrikleri alınamadı", exc_info=True)
        return []


def _metrics_planlama(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Bütçe ve hedef ilerleme metriklerini döndürür."""
    from ayaz.services.copilot_tools import _get_budget_status, _get_goal_progress

    metrics: list[dict] = []

    try:
        budget = _get_budget_status(db, tenant_id)
        if budget.get("has_plan"):
            total_budget = budget.get("total_budget", 0)
            projection = budget.get("projection", {})
            # Tempo: projection'dan ya da basit gösterge
            if isinstance(projection, dict) and "spend_pct" in projection:
                tempo_val = projection["spend_pct"]
                tempo_str = _fmt_pct(tempo_val)
            else:
                tempo_str = "—"
            metrics.append({
                "label": "Toplam Bütçe",
                "value": _fmt_tl(total_budget),
                "hint": f"Dönem: {budget.get('period_month', '—')}",
            })
            metrics.append({
                "label": "Bütçe Temposu",
                "value": tempo_str,
                "hint": "Harcama temposunun bütçe içindeki yüzdesi",
            })
        else:
            metrics.append({
                "label": "Bütçe Planı",
                "value": "Tanımlı Değil",
                "hint": "Bu ay için bütçe planı oluşturulmamış",
            })
    except Exception:
        log.warning("role_views: bütçe metrikleri alınamadı", exc_info=True)

    try:
        goal_data = _get_goal_progress(db, tenant_id)
        goals = goal_data.get("goals", [])
        if goals:
            on_track = sum(1 for g in goals if g.get("status") == "on_track")
            at_risk = sum(1 for g in goals if g.get("status") in ("at_risk", "off_track"))
            metrics.append({
                "label": "Hedef İlerleme",
                "value": f"{on_track}/{len(goals)}",
                "hint": f"{at_risk} hedef gecikmiş veya risk altında",
            })
    except Exception:
        log.warning("role_views: hedef metrikleri alınamadı", exc_info=True)

    return metrics


def _metrics_yonetim(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    """Yönetici KPI metriklerini döndürür."""
    from ayaz.services.copilot_tools import _get_executive_summary, _get_insights

    metrics: list[dict] = []

    try:
        data = _get_executive_summary(db, tenant_id)
        kpis = data.get("kpis", {})
        metrics.extend([
            {
                "label": "Toplam Harcama",
                "value": _fmt_tl(kpis.get("spend", 0)),
                "hint": "Son 30 gün toplam reklam harcaması",
            },
            {
                "label": "ROAS",
                "value": _fmt_roas(kpis.get("roas", 0)),
                "hint": "Harcama başına dönüşüm geliri",
            },
            {
                "label": "Dönüşüm Değeri",
                "value": _fmt_tl(kpis.get("revenue", 0)),
                "hint": "Reklamlardan elde edilen toplam dönüşüm geliri",
            },
        ])
    except Exception:
        log.warning("role_views: yönetim kpi metrikleri alınamadı", exc_info=True)

    try:
        insights_data = _get_insights(db, tenant_id, severity="critical")
        critical_count = insights_data.get("count", 0)
        metrics.append({
            "label": "Aktif Kritik Uyarı",
            "value": _fmt_int(critical_count),
            "hint": "Sistem tarafından tespit edilen kritik sorun sayısı",
        })
    except Exception:
        log.warning("role_views: uyarı metrikleri alınamadı", exc_info=True)

    return metrics


# ── Dikkat öğeleri (attention) ─────────────────────────────────────────────────

# Öneri impact → attention severity eşlemesi
_IMPACT_TO_SEVERITY: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}

# Öneri kategorileri — recommendation.category değerleri
# "performance" kategorisi audit + benchmark önerilerinin üst kümesi olarak
# yönetim ve performans rolleri için genişletilmiş kategori listesiyle eşleşir.
_PERF_CATEGORIES = frozenset({"audit", "benchmark"})


def _attention_for_role(
    db: Session,
    tenant_id: uuid.UUID,
    rec_categories: list[str],
) -> list[dict]:
    """Verilen kategorilere göre öneri akışından dikkat öğeleri oluşturur."""
    from ayaz.services.recommendations import build_recommendation_feed

    try:
        feed = build_recommendation_feed(db, tenant_id)
        recs = feed.get("recommendations", [])
    except Exception:
        log.warning("role_views: öneri akışı alınamadı", exc_info=True)
        return []

    # "performance" sanal kategorisi → audit + benchmark gerçek kategorileri
    expanded: set[str] = set()
    for cat in rec_categories:
        if cat == "performance":
            expanded.update(_PERF_CATEGORIES)
        else:
            expanded.add(cat)

    attention: list[dict] = []
    for rec in recs:
        if rec.get("status") in ("dismissed", "snoozed"):
            continue
        if rec.get("category") not in expanded:
            continue
        attention.append({
            "title": rec.get("title", ""),
            "detail": rec.get("rationale", ""),
            "severity": _IMPACT_TO_SEVERITY.get(rec.get("impact", "low"), "low"),
            "href": rec.get("action_href", "/recommendations"),
        })
        if len(attention) >= 4:
            break

    return attention


# ── Public API ─────────────────────────────────────────────────────────────────


def list_roles() -> list[dict]:
    """Tanımlı 5 rolün kısa listesini döndürür.

    Returns
    -------
    [{key, label, description, icon_key}]  — tanımlandıkları sırayla.
    """
    return [
        {
            "key": r["key"],
            "label": r["label"],
            "description": r["description"],
            "icon_key": r["icon_key"],
        }
        for r in ROLE_DEFINITIONS
    ]


_METRIC_BUILDERS = {
    "performans": _metrics_performans,
    "marcom": _metrics_marcom,
    "musteri_hizmetleri": _metrics_musteri_hizmetleri,
    "planlama": _metrics_planlama,
    "yonetim": _metrics_yonetim,
}


def get_role_view(
    db: Session,
    tenant_id: uuid.UUID,
    role: str,
) -> dict:
    """Verilen rol için tam görünümü döndürür.

    Parameters
    ----------
    db:
        SQLAlchemy Session — tüm okumalar bu oturumdan yapılır.
    tenant_id:
        Kiracı UUID'si — tüm sorgulara uygulanır.
    role:
        Rol anahtarı (ör. "performans", "yonetim").  Bilinmeyen rol → ValueError.

    Returns
    -------
    Kilitli şema: role, label, description, icon_key, generated_at,
    metrics, attention, priority_screens, quick_actions.

    Raises
    ------
    ValueError — bilinmeyen rol anahtarı.
    """
    role_def = _ROLE_MAP.get(role)
    if role_def is None:
        valid = ", ".join(r["key"] for r in ROLE_DEFINITIONS)
        raise ValueError(
            f"Bilinmeyen rol: {role!r}. Geçerli değerler: {valid}"
        )

    generated_at = datetime.now(timezone.utc).isoformat()

    # Metrikler
    metric_builder = _METRIC_BUILDERS.get(role)
    metrics: list[dict] = []
    if metric_builder is not None:
        try:
            metrics = metric_builder(db, tenant_id)
        except Exception:
            log.warning("role_views: %r için metrik oluşturulamadı", role, exc_info=True)

    # Dikkat öğeleri
    attention = _attention_for_role(db, tenant_id, role_def["rec_categories"])

    return {
        "role": role_def["key"],
        "label": role_def["label"],
        "description": role_def["description"],
        "icon_key": role_def["icon_key"],
        "generated_at": generated_at,
        "metrics": metrics,
        "attention": attention,
        "priority_screens": role_def["priority_screens"],
        "quick_actions": role_def["quick_actions"],
    }
