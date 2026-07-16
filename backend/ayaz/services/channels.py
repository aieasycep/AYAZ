"""Kanal anahtarı → kullanıcıya dönük etiket / kaynak-tipi (backend tek kaynak).

Ham anahtarlar ("google_ads") AI özetlerine, içgörülere, raporlara
SIZMAMALI. Bu modül frontend'deki ``src/lib/channels.ts`` haritasının
backend karşılığıdır; ikisi birlikte güncellenmeli.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CHANNEL_LABELS: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "tiktok_ads": "TikTok Ads",
    "linkedin_ads": "LinkedIn Ads",
    "microsoft_ads": "Microsoft Ads",
    "criteo": "Criteo",
    "pinterest_ads": "Pinterest Ads",
    "ga4": "Google Analytics 4",
    "search_console": "Search Console",
    "sample": "Örnek Kaynak",
}


def channel_label(slug: str | None) -> str:
    """'google_ads' → 'Google Ads'. Bilinmeyen anahtarı olduğu gibi döndürür
    (ham anahtar en azından bozulmadan geçer); None/boş → 'genel'."""
    if not slug:
        return "genel"
    return _CHANNEL_LABELS.get(slug.lower(), slug)


# ── Kaynak tipi (source type) ──────────────────────────────────────────────────
#
# "ad"        — harcaması olan reklam platformları (Google Ads, Meta Ads, ...).
#               Bu platformlar KENDİ dönüşümlerini raporlar (self-attributed,
#               genelde platforma özgü attribution penceresi/modeli ile).
# "analytics" — harcaması OLMAYAN ölçüm/analitik kaynakları (GA4, Search
#               Console). Bunlar sitedeki/uygulamadaki GERÇEK aktiviteyi ölçer.
#
# Neden önemli: Her ikisi de aynı ``fact_daily_metrics`` tablosuna, aynı
# ``conversions``/``conversion_value_raw`` kolonlarına yazar. Kanal-üstü
# SUM() alırken bu ikisini ayırmazsak, GA4'ün ölçtüğü dönüşümler reklam
# platformlarının ZATEN raporladığı dönüşümlerin ÜSTÜNE eklenir (çift sayım).
# Bkz. ``ayaz/services/metrics.py`` — ``split_channel_totals_by_source``,
# ``resolve_headline_metric``, ``blended_roas``.
_AD_CHANNELS: frozenset[str] = frozenset(
    {
        "google_ads",
        "meta_ads",
        "tiktok_ads",
        "linkedin_ads",
        "microsoft_ads",
        "criteo",
        "pinterest_ads",
        # "sample" gerçek bir reklam platformu değil (demo/test konektörü) ama
        # harcama + dönüşüm üreten bir ad-benzeri veri şekli kullanır (bkz.
        # ayaz/connectors/sample.py, scripts/seed_demo.py) — "ad" kanalı gibi
        # ele alınır ki demo/seed verisi mevcut davranışıyla tutarlı kalsın.
        "sample",
    }
)

_ANALYTICS_CHANNELS: frozenset[str] = frozenset({"ga4", "search_console"})


def source_type(channel_key: str | None) -> str:
    """Kanal anahtarını kaynak tipine sınıflandırır: ``"ad"`` | ``"analytics"``.

    'google_ads' → 'ad'; 'ga4' → 'analytics'.

    Bilinmeyen (veya None/boş) anahtar → ``"ad"`` varsayılanı döner (mevcut
    "kanal-üstü kör toplama" davranışını bozmamak için — yeni bir konektör
    burada sınıflandırılmadan eklenirse en azından harcama/dönüşümü var
    sayılan tarafta kalır) ve bir uyarı loglanır, böylece sınıflandırmanın
    unutulduğu sessizce geçmez.
    """
    if not channel_key:
        return "ad"
    key = channel_key.lower()
    if key in _ANALYTICS_CHANNELS:
        return "analytics"
    if key in _AD_CHANNELS:
        return "ad"
    logger.warning(
        "channels.source_type: bilinmeyen kanal anahtarı %r — varsayılan "
        "'ad' kullanılıyor. _AD_CHANNELS/_ANALYTICS_CHANNELS setlerine "
        "eklemeyi unutmayın (ayaz/services/channels.py).",
        channel_key,
    )
    return "ad"
