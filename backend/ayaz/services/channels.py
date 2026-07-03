"""Kanal anahtarı → kullanıcıya dönük etiket (backend tek kaynak).

Ham anahtarlar ("google_ads") AI özetlerine, içgörülere, raporlara
SIZMAMALI. Bu modül frontend'deki ``src/lib/channels.ts`` haritasının
backend karşılığıdır; ikisi birlikte güncellenmeli.
"""

from __future__ import annotations

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
