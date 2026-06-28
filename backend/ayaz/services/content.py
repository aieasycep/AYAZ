"""İçerik Planlayıcı (Content Planner) service layer.

Public API
----------
    generate_caption(brief, channel=None, tone="profesyonel", *, http_client=None)
        -> {"caption": str, "hashtags": list[str], "ai_assisted": bool}

    is_valid_channel(channel: str) -> bool
    is_valid_status(status: str) -> bool

Caption generation
------------------
Two paths, mirroring the narrator pattern in briefing.py:

  _ClaudeCaptionGenerator (opt-in)
      Calls the Claude API via raw httpx POST to
      https://api.anthropic.com/v1/messages.
      Requires ``settings.anthropic_api_key``.
      Falls back to ``_TemplateCaptionGenerator`` on ANY exception (missing key,
      network timeout, non-200, JSON parse failure, malformed response, etc.).
      Model ID is read from ``settings.claude_narrator_model`` — never hardcoded.

  _TemplateCaptionGenerator (default, no network)
      Deterministic Turkish caption built from the brief, optional channel, and
      tone.  Hashtags are derived from the brief's significant words (lowercase,
      punctuation stripped, stop-words and short words dropped).
      Always works with no network.  ai_assisted=False.

Tenant isolation
----------------
This module contains only pure, stateless helpers — no DB queries.  Tenant
isolation is enforced in the API layer (``ayaz/api/v1/content.py``).
"""

from __future__ import annotations

import json
import logging
import re
import string
from typing import Any

logger = logging.getLogger(__name__)

# ── Turkish stop-words (common, non-informative) ──────────────────────────────

_TR_STOPWORDS: frozenset[str] = frozenset(
    {
        "ve", "bir", "bu", "ile", "için", "da", "de", "ki", "mi", "mu",
        "mı", "mü", "gibi", "ama", "ya", "en", "çok", "çok", "daha",
        "olarak", "olan", "olan", "her", "ne", "var", "yok", "ben", "sen",
        "o", "biz", "siz", "onlar", "hem", "veya", "fakat", "lakin",
        "ancak", "sadece", "bile", "kadar", "göre", "sonra", "önce",
        "üzere", "ise", "olan", "oldu", "olup", "the", "a", "an", "and",
        "or", "but", "in", "on", "at", "to", "for", "of", "is", "are",
        "was", "were",
    }
)

# Channel-specific call-to-action suffixes (Turkish)
_CHANNEL_CTA: dict[str, str] = {
    "instagram": "Keşfetmek için bağlantıya tıklayın! 📲",
    "facebook": "Paylaşın ve arkadaşlarınızı etiketleyin! 👍",
    "x": "Retweet yapın ve düşüncelerinizi paylaşın!",
    "linkedin": "Profesyonel ağınızla paylaşın. 💼",
    "tiktok": "Takip edin, kaçırmayın! 🎵",
    "youtube": "Abone olmayı unutmayın! 🔔",
}

# Tone modifier map (Turkish phrases)
_TONE_MODIFIERS: dict[str, str] = {
    "profesyonel": "Profesyonel bir bakış açısıyla",
    "samimi": "Samimi bir dille",
    "eğlenceli": "Eğlenceli ve enerjik bir tonda",
    "ilham verici": "İlham verici bir şekilde",
    "bilgilendirici": "Bilgilendirici bir yaklaşımla",
    "resmi": "Resmi bir üslupla",
}


def is_valid_channel(channel: str) -> bool:
    """Return True when *channel* is a recognised social channel key."""
    from ayaz.models.content import VALID_CHANNELS

    return channel in VALID_CHANNELS


def is_valid_status(status: str) -> bool:
    """Return True when *status* is a recognised ContentPost status value."""
    from ayaz.models.content import VALID_STATUSES

    return status in VALID_STATUSES


# ── Creative → organic content bridge ─────────────────────────────────────────
#
# Map an ad platform / channel label (M6 DimAd.channel) to the organic social
# channels where that creative's theme naturally belongs.  Best-effort; unknown
# values fall back to the broad Instagram + Facebook default.
_AD_CHANNEL_TO_SOCIAL: dict[str, list[str]] = {
    "meta": ["instagram", "facebook"],
    "meta_ads": ["instagram", "facebook"],
    "facebook": ["instagram", "facebook"],
    "facebook_ads": ["instagram", "facebook"],
    "instagram": ["instagram", "facebook"],
    "google": ["youtube"],
    "google_ads": ["youtube"],
    "youtube": ["youtube"],
    "tiktok": ["tiktok"],
    "tiktok_ads": ["tiktok"],
    "linkedin": ["linkedin"],
    "linkedin_ads": ["linkedin"],
    "x": ["x"],
    "twitter": ["x"],
}

# Ad-naming jargon stripped when turning an ad name into an organic post title.
_AD_NAME_JARGON: frozenset[str] = frozenset(
    {
        "karusel", "carousel", "video", "tek", "single", "image", "görsel",
        "kopya", "copy", "reklam", "ad", "ads", "set", "v1", "v2", "v3",
        "test", "a", "b", "abtest", "story", "stories", "reels", "reel",
    }
)


def map_ad_channel_to_social(channel: str | None) -> list[str]:
    """Map an ad platform label to organic social channel keys.

    Unknown / empty values fall back to ``["instagram", "facebook"]``.
    """
    if not channel:
        return ["instagram", "facebook"]
    return _AD_CHANNEL_TO_SOCIAL.get(channel.strip().lower(), ["instagram", "facebook"])


def clean_ad_name(ad_name: str) -> str:
    """Turn a raw ad name into a clean content theme for caption generation.

    Strips separators and common ad-naming jargon (karusel, video, kopya, v1…)
    while preserving the meaningful campaign words.  Falls back to the original
    name when stripping would leave nothing.
    """
    # Normalise separators to spaces
    text = re.sub(r"[|/_\-–—]+", " ", ad_name)
    text = re.sub(r"\s+", " ", text).strip()
    kept = [
        w for w in text.split()
        if w.lower() not in _AD_NAME_JARGON and not w.isdigit()
    ]
    cleaned = " ".join(kept).strip()
    return cleaned or ad_name.strip()


def build_creative_brief(
    ad_name: str,
    campaign_name: str | None = None,
    channel: str | None = None,
) -> str:
    """Build the caption brief (content theme) from a top ad creative.

    The brief is the marketing THEME, not the performance metadata — ROAS and
    spend are used by the caller to choose the creative, never written into the
    public caption.
    """
    theme = clean_ad_name(ad_name)
    if campaign_name:
        camp = clean_ad_name(campaign_name)
        # Only add the campaign theme when it adds new words
        if camp and camp.lower() not in theme.lower():
            theme = f"{theme} — {camp}"
    return theme


# ── Hashtag derivation helper ─────────────────────────────────────────────────


def _derive_hashtags(brief: str, max_tags: int = 5) -> list[str]:
    """Derive 3-5 lowercase hashtags from significant words in *brief*.

    Algorithm
    ---------
    1. Strip punctuation and lower-case the text.
    2. Split into words.
    3. Drop words that are in the Turkish/English stop-word list or have fewer
       than 4 characters.
    4. Deduplicate while preserving order.
    5. Return 3–max_tags entries, prefixed with ``#``.
    """
    text = brief.translate(str.maketrans("", "", string.punctuation))
    words = text.lower().split()
    seen: dict[str, None] = {}
    tags: list[str] = []
    for word in words:
        word = word.strip()
        if len(word) < 4:
            continue
        if word in _TR_STOPWORDS:
            continue
        if word not in seen:
            seen[word] = None
            tags.append(f"#{word}")
        if len(tags) >= max_tags:
            break

    # Ensure at least 3 tags by falling back to generic ones
    fallbacks = ["#içerik", "#sosyalmedya", "#dijitalmartketing", "#ayaz", "#iletişim"]
    i = 0
    while len(tags) < 3 and i < len(fallbacks):
        if fallbacks[i] not in tags:
            tags.append(fallbacks[i])
        i += 1

    return tags[:max_tags]


# ── Template caption generator ────────────────────────────────────────────────


class _TemplateCaptionGenerator:
    """Deterministic Turkish caption — no network, always available."""

    def generate(
        self, brief: str, channel: str | None, tone: str
    ) -> dict[str, Any]:
        tone_phrase = _TONE_MODIFIERS.get(tone, f"{tone} bir tonda")
        channel_cta = _CHANNEL_CTA.get(channel or "", "") if channel else ""

        brief_clean = brief.strip()
        # Build the caption
        parts = [f"{tone_phrase}: {brief_clean}"]
        if channel_cta:
            parts.append(channel_cta)

        caption = " ".join(parts)
        hashtags = _derive_hashtags(brief)

        return {
            "caption": caption,
            "hashtags": hashtags,
            "ai_assisted": False,
        }


# ── Claude caption generator ──────────────────────────────────────────────────


class _ClaudeCaptionGenerator:
    """Optional Claude-API caption generator.  Falls back to template on any error.

    The model ID is read from ``settings.claude_narrator_model`` at call time —
    never hardcoded — so changing the model in config is all that is required.
    """

    def __init__(self, api_key: str, http_client: Any = None) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._fallback = _TemplateCaptionGenerator()

    def generate(
        self, brief: str, channel: str | None, tone: str
    ) -> dict[str, Any]:
        try:
            return self._call_claude(brief, channel, tone)
        except Exception as exc:
            logger.warning(
                "[ClaudeCaptionGenerator] API call failed (%s) — using template", exc
            )
            return self._fallback.generate(brief, channel, tone)

    def _call_claude(
        self, brief: str, channel: str | None, tone: str
    ) -> dict[str, Any]:
        import httpx

        from ayaz.config import settings

        model = settings.claude_narrator_model

        channel_info = f" ({channel} platformu için)" if channel else ""
        prompt = (
            f"Sen bir sosyal medya içerik uzmanısın. "
            f"Aşağıdaki kısa açıklamayı kullanarak {tone} bir tonda"
            f"{channel_info} Türkçe bir sosyal medya gönderisi yaz.\n\n"
            f"Kısa açıklama: {brief}\n\n"
            f"Yanıtını şu JSON formatında ver (başka hiçbir şey ekleme):\n"
            f'{{"caption": "<gönderi metni>", "hashtags": ["#etiket1", "#etiket2", "#etiket3"]}}'
        )

        payload = {
            "model": model,
            "max_tokens": 300,
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
                timeout=20.0,
            )
        else:
            with httpx.Client() as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=20.0,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:200]}"
            )

        raw_text = resp.json()["content"][0]["text"].strip()

        # Parse the JSON response; raise on any failure so the caller falls back
        # to the template generator.
        parsed = json.loads(raw_text)
        caption = str(parsed["caption"])
        hashtags_raw = parsed.get("hashtags", [])
        if not isinstance(hashtags_raw, list):
            raise ValueError("hashtags must be a list")
        hashtags = [str(h) for h in hashtags_raw]
        if not hashtags:
            hashtags = _derive_hashtags(brief)

        return {
            "caption": caption,
            "hashtags": hashtags,
            "ai_assisted": True,
        }


# ── Picker ────────────────────────────────────────────────────────────────────


def _pick_generator(
    http_client: Any = None,
) -> _TemplateCaptionGenerator | _ClaudeCaptionGenerator:
    """Return a Claude generator when an API key is configured, else template."""
    try:
        from ayaz.config import settings

        if settings.anthropic_api_key:
            return _ClaudeCaptionGenerator(
                api_key=settings.anthropic_api_key,
                http_client=http_client,
            )
    except Exception:
        pass
    return _TemplateCaptionGenerator()


# ── Public API ────────────────────────────────────────────────────────────────


def generate_caption(
    brief: str,
    channel: str | None = None,
    tone: str = "profesyonel",
    *,
    http_client: Any = None,
) -> dict[str, Any]:
    """Generate a Turkish social-media caption for the given brief.

    Parameters
    ----------
    brief:
        A short description of the content to post (required).
    channel:
        Optional target channel key (e.g. "instagram").  When provided, the
        caption is tailored with a channel-appropriate call-to-action.
    tone:
        Desired tone of the caption.  Defaults to "profesyonel".  Common values:
        "profesyonel", "samimi", "eğlenceli", "ilham verici", "bilgilendirici".
    http_client:
        Optional httpx-compatible client injected for testing.  When None, a
        real httpx.Client is used for the Claude path.

    Returns
    -------
    dict with keys:
        caption    (str)       — the generated post text
        hashtags   (list[str]) — 3-5 lowercase hashtag strings (e.g. "#içerik")
        ai_assisted (bool)     — True when the Claude path was used successfully

    Notes
    -----
    This function NEVER raises.  The Claude path gracefully falls back to the
    template generator on any exception (network error, invalid API key,
    malformed JSON response, etc.).  The template path is fully deterministic
    and works with no network and no API key configured.
    """
    generator = _pick_generator(http_client=http_client)
    try:
        return generator.generate(brief, channel, tone)
    except Exception as exc:
        logger.warning(
            "[generate_caption] Generator raised unexpectedly (%s) — using template",
            exc,
        )
        return _TemplateCaptionGenerator().generate(brief, channel, tone)
