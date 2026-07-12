"""Attribution / kaynak-mutabakatı servis katmanı.

Neden bu modül var
------------------
Google Ads / Meta Ads gibi reklam platformları KENDİ dönüşümlerini
(self-attributed — genelde son-tıklama ya da platforma özgü bir attribution
penceresi/modeliyle) raporlar. GA4 gibi analitik kaynaklar ise sitedeki/
uygulamadaki GERÇEK dönüşümü ölçer. Bu iki sayı FARKLI şeylerdir; ama aynı
``fact_daily_metrics`` tablosuna, aynı ``conversions`` /
``conversion_value_raw`` kolonlarına yazılırlar. Panelin kanal-üstü
``SUM()`` alan eski davranışı bunları kör toplardı — yani GA4'ün ölçtüğü
dönüşüm, reklam platformlarının ZATEN raporladığı dönüşümün ÜSTÜNE
ekleniyordu (manşet dönüşüm 2-3× şişik, blended ROAS yapısal olarak
abartılı).

Bu modül ikisini asla kör toplamaz; yan yana gösterir ve aradaki farkı
(``inflation_factor``) nicelleştirir. Dashboard/executive'teki "manşet"
alanlar geriye-uyumluluk için hâlâ TEK bir değere düşer (GA4 varsa GA4,
yoksa ad) — ama BU modül, o çözümlemenin altında yatan ham gerçeği açıkça
ortaya koyar.

Public API
----------
build_attribution_summary(db, tenant_id, date_from, date_to) -> dict
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from ayaz.services.channels import source_type
from ayaz.services.metrics import (
    _aggregate_by_channel_raw,
    blended_roas as _blended_roas,
    roas as _roas,
    split_channel_totals_by_source,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def build_attribution_summary(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict:
    """Verilen (tenant, date_from, date_to) için kaynak-mutabakatı özetini döndürür.

    Tenant izolasyonu: ``_aggregate_by_channel_raw`` üzerinden tüm sorgular
    ``tenant_id`` ile filtrelenir — cross-tenant veri sızıntısı mümkün
    değildir.

    Returns
    -------
    dict şu anahtarlarla:

    date_from, date_to : str (ISO)
    platform_claimed_conversions, platform_claimed_revenue : float
        Yalnız ``source_type == "ad"`` kanallarının (Google Ads, Meta Ads,
        ...) kendi raporladığı toplam dönüşüm / dönüşüm değeri.
    ga4_conversions, ga4_revenue : float
        Yalnız ``source_type == "analytics"`` kanallarının (GA4, Search
        Console) toplam dönüşüm / dönüşüm değeri. (Bugün pratikte yalnız
        GA4 dönüşüm raporlar; Search Console her zaman 0 conversions
        raporlar — bkz. ``ayaz/connectors/search_console.py`` docstring'i.)
    inflation_factor : float | None
        ``platform_claimed_conversions / ga4_conversions`` — yalnız
        ``ga4_conversions > 0`` ise hesaplanır; aksi halde ``None``
        (GA4 verisi yoksa karşılaştırma anlamsızdır, sıfıra bölme yapılmaz).
        1.0'dan büyük bir değer, reklam platformlarının GA4'e göre daha
        FAZLA dönüşüm iddia ettiğini gösterir (genelde beklenen durum —
        platformlar kendi attribution pencereleriyle sayar).
    ad_spend : float
        Yalnız ``ad`` tipi kanalların harcaması.
    blended_roas : float
        ``ga4_revenue / ad_spend`` (GA4 yoksa/sıfırsa 0 — fallback YOK;
        bu endpoint'in amacı "gerçek" resmi göstermektir, dashboard'daki
        geriye-uyumlu ad-only fallback burada UYGULANMAZ).
    channels : list[dict]
        Harcamaya göre azalan sırada, her kanal için: key, label,
        source_type, spend, conversions, conversion_value, roas (kanalın
        KENDİ rakamlarına göre — çapraz kanal karışımı yok, tek kanalın
        kendi verisi zaten çift-sayım riski taşımaz).
    """
    channel_data = _aggregate_by_channel_raw(db, tenant_id, date_from, date_to)
    split = split_channel_totals_by_source(channel_data)

    platform_claimed_conversions = split["ad_conversions"]
    platform_claimed_revenue = split["ad_conversion_value"]
    ga4_conversions = split["analytics_conversions"]
    ga4_revenue = split["analytics_conversion_value"]
    ad_spend = split["ad_spend"]

    inflation_factor: float | None = None
    if ga4_conversions != Decimal(0):
        inflation_factor = float(platform_claimed_conversions / ga4_conversions)

    blended = _blended_roas(
        ad_spend=ad_spend,
        analytics_conversion_value=ga4_revenue,
        # ad_conversion_value KASITLI OLARAK geçilmiyor (varsayılan 0) — bu
        # endpoint GA4 yoksa/sıfırsa dürüstçe 0 döner, dashboard'un ad-only
        # fallback'ine düşmez (bkz. blended_roas docstring).
    )

    channels: list[dict] = []
    for ch_key, row in sorted(
        channel_data.items(), key=lambda kv: kv[1]["spend"], reverse=True
    ):
        ch_spend = row["spend"]
        ch_conversion_value = row["conversion_value"]
        channels.append(
            {
                "key": ch_key,
                "label": str(row["label"]),
                "source_type": source_type(ch_key),
                "spend": float(ch_spend),
                "conversions": float(row["conversions"]),
                "conversion_value": float(ch_conversion_value),
                "roas": float(_roas(ch_conversion_value, ch_spend)),
            }
        )

    return {
        "date_from": str(date_from),
        "date_to": str(date_to),
        "platform_claimed_conversions": float(platform_claimed_conversions),
        "platform_claimed_revenue": float(platform_claimed_revenue),
        "ga4_conversions": float(ga4_conversions),
        "ga4_revenue": float(ga4_revenue),
        "inflation_factor": inflation_factor,
        "ad_spend": float(ad_spend),
        "blended_roas": float(blended),
        "channels": channels,
    }
