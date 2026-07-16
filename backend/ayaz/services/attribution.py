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

GA4 TOPLAMI vs GA4 ÜCRETLİ — ikinci bir elma-armut tuzağı
----------------------------------------------------------
GA4'ün kendi ``conversions``/``totalRevenue`` toplamı bile TEK BAŞINA reklam
platformlarıyla karşılaştırılamaz: bu toplam organik arama, direkt trafik,
e-posta, referans gibi TÜM kanalları kapsar. Reklam platformunun iddiasıyla
gerçekten elma-elma karşılaştırılabilir olan, YALNIZ GA4'ün ücretli kanal
gruplarına (``PAID_CHANNEL_GROUPS``) düşen dilimidir. Bu modül bu ayrımı da
yapar: ``ga4_conversions``/``ga4_revenue`` (TOPLAM) ile ``ga4_paid_conversions``/
``ga4_paid_revenue`` (yalnız ücretli) ayrı alanlar olarak sunulur;
``inflation_factor`` ve ``blended_roas`` ücretli dilime göre hesaplanır, ayrı
bir ``mer`` (Media Efficiency Ratio) alanı ise toplam GA4 gelirini kullanır.

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
    _d,
    blended_roas as _blended_roas,
    roas as _roas,
    split_channel_totals_by_source,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Ücretli kanal-grubu sabiti (apples-to-apples GA4 mutabakatı) ──────────────
#
# GA4'ün ``sessionDefaultChannelGroup`` boyutu (GA4 connector'da hem
# ``campaign_id`` hem ``campaign_name`` olarak saklanır — bkz.
# ``ayaz/connectors/ga4.py`` normalize()) bir kampanya DEĞİL, bir kanal
# sınıflandırmasıdır ("Paid Search", "Organic Search", "Direct", "Referral",
# "Email", ...). Reklam platformlarının (Google Ads, Meta Ads, ...) kendi
# iddia ettiği dönüşümle GA4'ü ELMA-ELMA karşılaştırmak için yalnız BU
# kanal gruplarındaki GA4 satırları kullanılmalı — aksi halde organik/direkt/
# e-posta trafiği paydaya karışır ve karşılaştırma anlamsızlaşır.
#
# Kaynak: GA4 Data API "Default channel group" referans değerleri.
PAID_CHANNEL_GROUPS: frozenset[str] = frozenset(
    {
        "Paid Search",
        "Paid Social",
        "Paid Shopping",
        "Paid Video",
        "Display",
        "Cross-network",
    }
)


def _aggregate_ga4_paid_totals(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, Decimal | int]:
    """GA4 dönüşüm/gelirini YALNIZ ücretli kanal-gruplarına (``PAID_CHANNEL_GROUPS``)
    kırarak toplar.

    GA4 connector, ``sessionDefaultChannelGroup``'u hem ``dim_campaign.name``
    hem ``external_id`` olarak saklar (kampanya seviyesinde grain yok — bkz.
    GA4 connector docstring'i). Bu fonksiyon ``dim_channel.key == "ga4"`` VE
    ``dim_campaign.name IN PAID_CHANNEL_GROUPS`` olan ``fact_daily_metrics``
    satırlarını (tenant + tarih aralığı filtreli) toplar.

    Parameters
    ----------
    db, tenant_id, date_from, date_to:
        ``_aggregate_by_channel_raw`` ile aynı — tenant izolasyonu SQL
        WHERE'de uygulanır, cross-tenant sızıntı mümkün değildir.

    Returns
    -------
    dict[str, Decimal | int] anahtarları:
        ``conversions``, ``conversion_value`` : Decimal
            Ücretli-kanal-grubu GA4 satırlarının toplamı. GA4 bağlı değilse
            veya ücretli grup satırı yoksa ``Decimal(0)`` (None DEĞİL —
            çağıran sıfıra bölme guard'ını kendi uygular).
        ``row_count`` : int
            Eşleşen ham satır sayısı. ``conversions == 0`` VE ``row_count
            == 0`` ayrımı önemlidir: ilki "ücretli trafik var ama dönüşüm
            sıfır", ikincisi "ücretli kanal grubu hiç izlenmiyor" anlamına
            gelir — ``data_quality.ga4_paid_tracked`` bunu ayırt etmek için
            ``row_count`` kullanır.
    """
    from sqlalchemy import func, select
    from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics

    row = db.execute(
        select(
            func.count().label("row_count"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label(
                "conversion_value"
            ),
        )
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
            DimChannel.key == "ga4",
            DimCampaign.name.in_(PAID_CHANNEL_GROUPS),
        )
    ).mappings().first()

    return {
        "conversions": _d(row["conversions"]) if row else Decimal(0),
        "conversion_value": _d(row["conversion_value"]) if row else Decimal(0),
        "row_count": int(row["row_count"] or 0) if row else 0,
    }


def build_attribution_summary(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict:
    """Verilen (tenant, date_from, date_to) için kaynak-mutabakatı özetini döndürür.

    Tenant izolasyonu: ``_aggregate_by_channel_raw`` / ``_aggregate_ga4_paid_totals``
    üzerinden tüm sorgular ``tenant_id`` ile filtrelenir — cross-tenant veri
    sızıntısı mümkün değildir.

    Returns
    -------
    dict şu anahtarlarla:

    date_from, date_to : str (ISO)
    platform_claimed_conversions, platform_claimed_revenue : float
        Yalnız ``source_type == "ad"`` kanallarının (Google Ads, Meta Ads,
        ...) kendi raporladığı toplam dönüşüm / dönüşüm değeri.
    ga4_conversions, ga4_revenue : float
        GA4 (analytics) TOPLAMI — TÜM kanal grupları (Paid Search + Organic
        Search + Direct + ... hepsi). Bu, sitedeki/uygulamadaki toplam
        aktiviteyi ölçer; reklam platformlarıyla doğrudan karşılaştırılamaz
        (elmayla armut) çünkü organik/direkt trafiği de içerir.
    ga4_paid_conversions, ga4_paid_revenue : float
        GA4 satırlarının YALNIZ ücretli kanal-grubuna (``PAID_CHANNEL_GROUPS``
        — "Paid Search", "Paid Social", "Paid Shopping", "Paid Video",
        "Display", "Cross-network") ait toplamı. Reklam platformlarının kendi
        iddiasıyla ELMA-ELMA karşılaştırılabilir olan budur (bkz.
        ``_aggregate_ga4_paid_totals``).
    inflation_factor : float | None
        ``platform_claimed_conversions / ga4_paid_conversions`` — yalnız
        ``ga4_paid_conversions > 0`` ise hesaplanır; aksi halde ``None``
        (ücretli-kanal GA4 verisi yoksa karşılaştırma anlamsızdır, sıfıra
        bölme yapılmaz). ARTIK toplam GA4'e değil ÜCRETLİ GA4'e göre
        hesaplanır — eski sürüm toplam GA4'e bölüyordu ki bu organik trafiği
        paydaya katıp şişme faktörünü yapay olarak küçültüyordu (hatta ters
        yönde "GA4 ile uyumlu" gibi yanlış bir izlenim veriyordu). 1.0'dan
        büyük bir değer, reklam platformlarının ücretli-GA4'e göre daha FAZLA
        dönüşüm iddia ettiğini gösterir (genelde beklenen durum — platformlar
        kendi attribution pencereleriyle sayar).
    ad_spend : float
        Yalnız ``ad`` tipi kanalların harcaması.
    blended_roas : float
        "Gerçek/Ücretli ROAS" = ``ga4_paid_revenue / ad_spend`` (GA4 ücretli
        verisi yoksa/sıfırsa 0 — fallback YOK; bu endpoint'in amacı "gerçek"
        resmi göstermektir, dashboard'daki geriye-uyumlu ad-only fallback
        burada UYGULANMAZ). ARTIK toplam GA4 gelirine değil ücretli-GA4
        gelirine göre hesaplanır (bkz. ``inflation_factor`` notu — aynı
        elma-armut düzeltmesi).
    mer : float
        Media Efficiency Ratio (Medya Verimlilik Oranı) = ``ga4_revenue
        (TOPLAM) / ad_spend`` (ad_spend sıfırsa 0). Tüm-işletme geliri ÷
        reklam harcaması — ``blended_roas`` (yalnız ücretli-atfedilen) ile
        KARIŞTIRILMAMASI için ayrı bir alan olarak sunulur; organik/direkt
        trafiğin de dahil olduğu daha geniş bir verimlilik sinyalidir.
    data_quality : dict
        ``ga4_connected`` (bool): tenant'ta herhangi bir ``analytics``
        kaynak tipi (bugün pratikte yalnız GA4) satırı var mı.
        ``ga4_paid_tracked`` (bool): ücretli kanal-grubu GA4 satırı
        (``PAID_CHANNEL_GROUPS`` içinde en az bir ham satır) var mı —
        ``ga4_paid_conversions == 0`` olması bunu YANLIŞ yapmaz (ücretli
        trafik izlenip dönüşüm sıfır da olabilir); ayrım
        ``_aggregate_ga4_paid_totals``'ın ``row_count``'una dayanır.
        ``note`` (str | None): GA4 bağlıyken ücretli kanal grubu satırı
        bulunamazsa TR açıklama metni; aksi halde ``None``.
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

    paid_totals = _aggregate_ga4_paid_totals(db, tenant_id, date_from, date_to)
    ga4_paid_conversions: Decimal = paid_totals["conversions"]  # type: ignore[assignment]
    ga4_paid_revenue: Decimal = paid_totals["conversion_value"]  # type: ignore[assignment]
    ga4_paid_row_count: int = paid_totals["row_count"]  # type: ignore[assignment]

    inflation_factor: float | None = None
    if ga4_paid_conversions != Decimal(0):
        inflation_factor = float(platform_claimed_conversions / ga4_paid_conversions)

    blended = _blended_roas(
        ad_spend=ad_spend,
        analytics_conversion_value=ga4_paid_revenue,
        # ad_conversion_value KASITLI OLARAK geçilmiyor (varsayılan 0) — bu
        # endpoint GA4 yoksa/sıfırsa dürüstçe 0 döner, dashboard'un ad-only
        # fallback'ine düşmez (bkz. blended_roas docstring).
    )

    mer = _roas(ga4_revenue, ad_spend)

    ga4_connected = any(
        source_type(ch_key) == "analytics" for ch_key in channel_data
    )
    ga4_paid_tracked = ga4_paid_row_count > 0

    #
    # İKİ FARKLI "not" durumu ayırt edilir — biri gerçek bağlantı sorunu, diğeri
    # (e-ticaret olmayan property için) tamamen normal bir durum. Bunları
    # karıştırmak, doğru bağlanmış bir lead-gen müşterisine "entegrasyonun
    # bozuk" izlenimi verir (bkz. adversarial inceleme bulgusu #1).
    note: str | None = None
    if ga4_connected and not ga4_paid_tracked:
        # Ücretli kanal-grubu satırı HİÇ yok → auto-tagging/bağlantı eksik olabilir.
        note = (
            "GA4'te ücretli kanal (Paid Search/Paid Social) trafiği "
            "bulunamadı; şişme faktörü hesaplanamıyor. Google Ads ↔ GA4 "
            "bağlantısını ve otomatik etiketlemeyi (auto-tagging) kontrol edin."
        )
    elif ga4_connected and ga4_paid_tracked and ga4_paid_conversions == Decimal(0):
        # Ücretli trafik izleniyor AMA satın-alma sıfır → property büyük olasılıkla
        # e-ticaret değil; bu "bozuk" değil, beklenen bir durum.
        note = (
            "GA4 ücretli kanallarında satın-alma (ecommerce) dönüşümü "
            "görülmedi. Property e-ticaret değilse bu beklenendir; lead/form "
            "gibi dönüşümler için GA4'te ecommerce ölçümü ayrıca yapılandırılmalı."
        )

    data_quality = {
        "ga4_connected": ga4_connected,
        "ga4_paid_tracked": ga4_paid_tracked,
        "note": note,
    }

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
        "ga4_paid_conversions": float(ga4_paid_conversions),
        "ga4_paid_revenue": float(ga4_paid_revenue),
        "inflation_factor": inflation_factor,
        "ad_spend": float(ad_spend),
        "blended_roas": float(blended),
        "mer": float(mer),
        "data_quality": data_quality,
        "channels": channels,
    }
