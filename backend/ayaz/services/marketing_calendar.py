"""Pazarlama Fırsat Takvimi (Marketing Opportunity Calendar) servisi — Dalga 80.

Türkiye'nin önemli ticari/sezonsal/resmi/dini tarihlerini derleyen ve her fırsat
için hazırlık durumunu (içerik planlandı mı? o ayın bütçesi var mı?) hesaplayan
saf okuma/sentez servisidir.

Yeni model veya migrasyon gerektirmez — mevcut ContentPost ve BudgetPlan
tablolarından veri okur.

Genel Kullanım
--------------
    from ayaz.services.marketing_calendar import build_opportunity_calendar

    result = build_opportunity_calendar(db, tenant_id, as_of=date(2026, 6, 29))
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Türkiye Önemli Pazarlama Tarihleri ────────────────────────────────────────
#
# Her giriş bir dict:
#   key              – benzersiz tanımlayıcı (slug)
#   name             – Türkçe isim
#   category         – "ticari" | "resmi" | "sezonsal" | "dini"
#   recurrence       – "fixed" | "variable"
#   month            – (fixed için) ay numarası (1-12)
#   day              – (fixed için) gün numarası (1-31)
#   dates_by_year    – (variable için) {yil: date} sözlüğü
#   is_approximate   – variable dini günler için True (yaklaşık tarih)
#   lead_time_days   – hazırlığa ne kadar önce başlanmalı (gün)
#   marketing_tip    – Türkçe bir cümlelik pazarlama ipucu
#   commerce_weight  – "yuksek" | "orta" | "dusuk"

TR_KEY_DATES: list[dict] = [
    {
        "key": "yilbasi",
        "name": "Yılbaşı",
        "category": "sezonsal",
        "recurrence": "fixed",
        "month": 1,
        "day": 1,
        "is_approximate": False,
        "lead_time_days": 30,
        "marketing_tip": (
            "Yılbaşı döneminde hediye kampanyaları ve yıl sonu özel tekliflerle "
            "satışları artırın; aralık ayının ilk haftasında içerik planlamasını tamamlayın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "sevgililer_gunu",
        "name": "Sevgililer Günü",
        "category": "ticari",
        "recurrence": "fixed",
        "month": 2,
        "day": 14,
        "is_approximate": False,
        "lead_time_days": 21,
        "marketing_tip": (
            "Sevgililer Günü için kişiselleştirilmiş hediye paketleri ve çift "
            "kampanyaları hazırlayın; 14 Şubat'tan en az 3 hafta önce iletişimi başlatın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "dunya_kadinlar_gunu",
        "name": "Dünya Kadınlar Günü",
        "category": "ticari",
        "recurrence": "fixed",
        "month": 3,
        "day": 8,
        "is_approximate": False,
        "lead_time_days": 14,
        "marketing_tip": (
            "8 Mart'ta markanızın değerlerini ve kadın dayanışmasını öne çıkaran "
            "özgün bir kampanya oluşturun; indirim yerine anlam odaklı mesajlar tercih edin."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "ramazan_baslangici",
        "name": "Ramazan Başlangıcı",
        "category": "dini",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 2, 18),
            2027: date(2027, 2, 8),
        },
        "is_approximate": True,
        "lead_time_days": 21,
        "marketing_tip": (
            "Ramazan öncesinde iftar sofrası, aile ve bereket temalı içeriklerle "
            "marka bilinirliğini güçlendirin; sahur ve iftar saatlerinde reklam bütçenizi yoğunlaştırın."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "ramazan_bayrami",
        "name": "Ramazan Bayramı",
        "category": "dini",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 3, 20),
            2027: date(2027, 3, 10),
        },
        "is_approximate": True,
        "lead_time_days": 30,
        "marketing_tip": (
            "Ramazan Bayramı'nda bayramlık, çikolata ve hediye kategorileri zirveye çıkar; "
            "bayramdan 30 gün önce stok ve lojistik planlamasını tamamlayın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "23_nisan",
        "name": "23 Nisan Ulusal Egemenlik ve Çocuk Bayramı",
        "category": "resmi",
        "recurrence": "fixed",
        "month": 4,
        "day": 23,
        "is_approximate": False,
        "lead_time_days": 14,
        "marketing_tip": (
            "23 Nisan'da çocuklara özel ürün ve içeriklerle duygusal bağ kuran "
            "kampanyalar hazırlayın; sosyal sorumluluk mesajları marka itibarını artırır."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "1_mayis",
        "name": "1 Mayıs İşçi Bayramı",
        "category": "resmi",
        "recurrence": "fixed",
        "month": 5,
        "day": 1,
        "is_approximate": False,
        "lead_time_days": 7,
        "marketing_tip": (
            "1 Mayıs'ta emekçi dayanışmasını destekleyen mesajlarla marka değerlerinizi "
            "gösterin; agresif satış yerine değer odaklı içerikler tercih edin."
        ),
        "commerce_weight": "dusuk",
    },
    {
        "key": "anneler_gunu",
        "name": "Anneler Günü",
        "category": "ticari",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 5, 10),
            2027: date(2027, 5, 9),
        },
        "is_approximate": False,
        "lead_time_days": 21,
        "marketing_tip": (
            "Anneler Günü Türkiye'nin en yüksek hediye harcaması yapılan günlerinden biridir; "
            "kişiselleştirilmiş hediye fikirleri ve duygusal içeriklerle 3 hafta önceden iletişime başlayın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "19_mayis",
        "name": "19 Mayıs Atatürk'ü Anma, Gençlik ve Spor Bayramı",
        "category": "resmi",
        "recurrence": "fixed",
        "month": 5,
        "day": 19,
        "is_approximate": False,
        "lead_time_days": 7,
        "marketing_tip": (
            "19 Mayıs'ta gençlik ve spor temalı içeriklerle aktif bir marka imajı oluşturun; "
            "spor ve sağlık kategorileri bu dönemde daha iyi performans gösterir."
        ),
        "commerce_weight": "dusuk",
    },
    {
        "key": "kurban_bayrami",
        "name": "Kurban Bayramı",
        "category": "dini",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 5, 27),
            2027: date(2027, 5, 17),
        },
        "is_approximate": True,
        "lead_time_days": 30,
        "marketing_tip": (
            "Kurban Bayramı döneminde et, gıda ve bayramlık kategorileri öne çıkar; "
            "uzun tatil nedeniyle teslimat sürelerini ve stok planlamasını önceden düzenleyin."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "babalar_gunu",
        "name": "Babalar Günü",
        "category": "ticari",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 6, 21),
            2027: date(2027, 6, 20),
        },
        "is_approximate": False,
        "lead_time_days": 14,
        "marketing_tip": (
            "Babalar Günü'nde teknoloji, spor ve hobi kategorileri öne çıkar; "
            "babaya özel koleksiyon ve hediye seti kampanyalarıyla ortalama sepet tutarını artırın."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "30_agustos",
        "name": "30 Ağustos Zafer Bayramı",
        "category": "resmi",
        "recurrence": "fixed",
        "month": 8,
        "day": 30,
        "is_approximate": False,
        "lead_time_days": 7,
        "marketing_tip": (
            "30 Ağustos'ta milli gurur temalı içeriklerle marka bağlılığını güçlendirin; "
            "Türk yapımı ürünler bu dönemde daha fazla ilgi görür."
        ),
        "commerce_weight": "dusuk",
    },
    {
        "key": "okula_donus",
        "name": "Okula Dönüş Sezonu",
        "category": "sezonsal",
        "recurrence": "fixed",
        "month": 9,
        "day": 1,
        "is_approximate": False,
        "lead_time_days": 30,
        "marketing_tip": (
            "Okula dönüş sezonu; kırtasiye, giyim, teknoloji ve çanta kategorilerinde "
            "büyük fırsatlar sunar — ağustos ortasında kampanyanızı başlatın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "cumhuriyet_bayrami",
        "name": "29 Ekim Cumhuriyet Bayramı",
        "category": "resmi",
        "recurrence": "fixed",
        "month": 10,
        "day": 29,
        "is_approximate": False,
        "lead_time_days": 14,
        "marketing_tip": (
            "Cumhuriyet Bayramı'nda vatan ve bayrak temalı kampanyalar güçlü duygusal "
            "bağ kurar; yerel üretim ve Türk markaları öne çıkarılabilir."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "singles_day",
        "name": "11.11 Bekarlar Günü / Singles Day",
        "category": "ticari",
        "recurrence": "fixed",
        "month": 11,
        "day": 11,
        "is_approximate": False,
        "lead_time_days": 21,
        "marketing_tip": (
            "11.11, küresel olarak en büyük online alışveriş günüdür; "
            "sınırlı süreli flash indirimler ve geri sayım sayaçlarıyla aciliyet hissi yaratın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "efsane_cuma",
        "name": "Efsane Cuma / Black Friday",
        "category": "ticari",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 11, 27),
            2027: date(2027, 11, 26),
        },
        "is_approximate": False,
        "lead_time_days": 30,
        "marketing_tip": (
            "Efsane Cuma yılın en yüksek ciro günüdür; teaser kampanyalarıyla "
            "beklenti yaratın, stok ve altyapı planlamasını kasımın başında tamamlayın."
        ),
        "commerce_weight": "yuksek",
    },
    {
        "key": "cyber_monday",
        "name": "Cyber Monday",
        "category": "ticari",
        "recurrence": "variable",
        "dates_by_year": {
            2026: date(2026, 11, 30),
            2027: date(2027, 11, 29),
        },
        "is_approximate": False,
        "lead_time_days": 30,
        "marketing_tip": (
            "Cyber Monday'de dijital ürünler ve teknoloji kategorileri öne çıkar; "
            "Black Friday kampanyanızı pazartesi gününe kadar uzatarak momentum koruyun."
        ),
        "commerce_weight": "orta",
    },
    {
        "key": "yilbasi_alisverisi",
        "name": "Yılbaşı Alışverişi Sezonu",
        "category": "sezonsal",
        "recurrence": "fixed",
        "month": 12,
        "day": 15,
        "is_approximate": False,
        "lead_time_days": 30,
        "marketing_tip": (
            "Aralık ayı yılın en uzun alışveriş sezonu başlangıcıdır; hediye, dekorasyon "
            "ve yılbaşı kategorilerinde içerik takviminizi kasımdan itibaren oluşturun."
        ),
        "commerce_weight": "yuksek",
    },
]


# ── Tarih çözümleme yardımcıları ─────────────────────────────────────────────


def _resolve_date_for_year(entry: dict, year: int) -> date | None:
    """Bir giriş için belirli bir yıldaki tarihi döndür.

    Fixed girişler için ay ve gün kullanılır.
    Variable girişler için dates_by_year sözlüğüne bakılır;
    bulunamazsa None döner.
    """
    if entry["recurrence"] == "fixed":
        try:
            return date(year, entry["month"], entry["day"])
        except ValueError:
            return None
    else:
        return entry.get("dates_by_year", {}).get(year)


def _find_next_occurrence(entry: dict, as_of: date, horizon_end: date) -> date | None:
    """as_of ile horizon_end arasındaki en yakın tarihi bul.

    as_of dahil, horizon_end dahil olan aralıkta arama yapar.
    Bulunamazsa None döner.
    """
    for year in (as_of.year, as_of.year + 1, as_of.year + 2):
        candidate = _resolve_date_for_year(entry, year)
        if candidate is None:
            continue
        if as_of <= candidate <= horizon_end:
            return candidate
    return None


# ── Önerilen eylemler ─────────────────────────────────────────────────────────


def _build_suggested_actions(
    entry: dict,
    readiness: dict,
) -> list[dict]:
    """Fırsata göre önerilen eylemlerin listesini oluştur."""
    actions = []

    # İçerik planlanmamışsa içerik öner
    if readiness["content_scheduled"] == 0:
        actions.append({"label": "İçerik planla", "href": "/content"})

    # Her zaman reklam metni öner (ticari ve sezonsal günler için daha kritik)
    if entry["category"] in ("ticari", "sezonsal"):
        actions.append({"label": "Reklam metni üret", "href": "/ad-studio"})

    # Bütçe planlanmamışsa bütçe öner
    if not readiness["budget_planned"]:
        actions.append({"label": "Bütçe planla", "href": "/planning"})

    # Varsayılan olarak en az bir eylem olsun
    if not actions:
        actions.append({"label": "İçerik planla", "href": "/content"})

    return actions


# ── Ana servis fonksiyonu ─────────────────────────────────────────────────────


def build_opportunity_calendar(
    db: "Session",
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
    horizon_months: int = 6,
) -> dict[str, Any]:
    """Pazarlama Fırsat Takvimi'ni oluştur ve döndür.

    Parametreler
    ------------
    db              : SQLAlchemy oturumu
    tenant_id       : Kiracı UUID'si (tüm sorgular bununla filtrelenir)
    as_of           : Referans tarihi; belirtilmezse bugün (UTC)
    horizon_months  : Kaç aylık ufuk (1-12; dışarıdan clamp edilmeli)

    Dönüş
    ------
    {
        "as_of": "YYYY-MM-DD",
        "horizon_months": int,
        "summary": {"total", "urgent", "this_month", "high_weight"},
        "opportunities": [ {fırsat dict'leri, tarihe göre artan sıralı} ]
    }
    """
    from ayaz.models.content import ContentPost
    from ayaz.models.budget import BudgetPlan

    if as_of is None:
        from datetime import datetime, timezone
        as_of = datetime.now(timezone.utc).date()

    # Ufuk bitiş tarihi (ayın son günü değil, sadece as_of + horizon_months gün)
    # Aylık hesaplama: horizon_months ay sonrasının aynı günü
    horizon_year = as_of.year + (as_of.month + horizon_months - 1) // 12
    horizon_month = (as_of.month + horizon_months - 1) % 12 + 1
    # Ayın sonunu aşmamak için max gün kontrolü
    import calendar
    last_day = calendar.monthrange(horizon_year, horizon_month)[1]
    horizon_day = min(as_of.day, last_day)
    horizon_end = date(horizon_year, horizon_month, horizon_day)

    # Ufuk içindeki tüm bütçe planı ay etiketlerini önceden yükle (n+1 sorgusu önleme)
    try:
        from sqlalchemy import select
        budget_months_result = db.execute(
            select(BudgetPlan.period_month).where(
                BudgetPlan.tenant_id == tenant_id
            )
        ).scalars().all()
        budgeted_months: set[str] = set(budget_months_result)
    except Exception:
        budgeted_months = set()

    opportunities: list[dict] = []

    for entry in TR_KEY_DATES:
        candidate = _find_next_occurrence(entry, as_of, horizon_end)
        if candidate is None:
            continue

        days_until = (candidate - as_of).days
        lead_time = entry["lead_time_days"]
        status_val = "urgent" if days_until <= lead_time else "upcoming"

        # period_month etiketi: "YYYY-MM"
        period_month_label = f"{candidate.year}-{candidate.month:02d}"

        # İçerik zamanlaması: tarihe ±7 gün içinde scheduled_at olan yazılar
        content_count = 0
        try:
            window_start = candidate - timedelta(days=7)
            window_end = candidate + timedelta(days=7)

            # scheduled_at metin olarak saklandığı için LIKE ile yıl-ay-gün ön ekini karşılaştırıyoruz
            # ISO-8601: "YYYY-MM-DDT..." formatında; basit string karşılaştırması güvenli
            from sqlalchemy import and_, or_

            posts = db.execute(
                select(ContentPost.id).where(
                    and_(
                        ContentPost.tenant_id == tenant_id,
                        ContentPost.scheduled_at.isnot(None),
                        ContentPost.scheduled_at >= window_start.isoformat(),
                        ContentPost.scheduled_at <= (window_end.isoformat() + "Z"),  # Z ile sona erenler dahil
                    )
                )
            ).scalars().all()
            content_count = len(posts)
        except Exception:
            content_count = 0

        readiness = {
            "content_scheduled": content_count,
            "budget_planned": period_month_label in budgeted_months,
        }

        suggested_actions = _build_suggested_actions(entry, readiness)

        opportunities.append({
            "key": entry["key"],
            "date": candidate.isoformat(),
            "name": entry["name"],
            "category": entry["category"],
            "commerce_weight": entry["commerce_weight"],
            "is_approximate": entry.get("is_approximate", False),
            "days_until": days_until,
            "lead_time_days": lead_time,
            "status": status_val,
            "marketing_tip": entry["marketing_tip"],
            "readiness": readiness,
            "suggested_actions": suggested_actions,
        })

    # Tarihe göre artan sırala
    opportunities.sort(key=lambda o: o["date"])

    # Özet istatistikler
    total = len(opportunities)
    urgent = sum(1 for o in opportunities if o["status"] == "urgent")
    this_month = sum(
        1 for o in opportunities
        if o["date"].startswith(f"{as_of.year}-{as_of.month:02d}")
    )
    high_weight = sum(1 for o in opportunities if o["commerce_weight"] == "yuksek")

    return {
        "as_of": as_of.isoformat(),
        "horizon_months": horizon_months,
        "summary": {
            "total": total,
            "urgent": urgent,
            "this_month": this_month,
            "high_weight": high_weight,
        },
        "opportunities": opportunities,
    }
