"""Sosyal Gelen Kutusu (Social Inbox) service layer — M13.

Public API
----------
    classify_sentiment(text: str) -> str
        Pure keyword classifier.  Returns one of "positive", "neutral", "negative".
        No network calls; always works offline.

    suggest_reply(message_text, channel=None, tone="samimi", *, http_client=None)
        -> {"reply": str, "ai_assisted": bool}
        Template fallback builds a polite Turkish customer-care reply.
        Optional Claude path when ``settings.anthropic_api_key`` is configured.
        Model ID is read from ``settings.claude_narrator_model`` — never hardcoded.
        Falls back to template on ANY exception.  Never raises.

    compute_inbox_stats(messages: list) -> dict
        Aggregates a list of SocialMessage ORM objects (or stubs with the same
        attributes) into a stats dict.  Uses ``getattr`` defensively.

Tenant isolation
----------------
This module is pure / stateless — no DB queries.  Tenant isolation is enforced
in the API layer (``ayaz/api/v1/inbox.py``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Sentiment keyword lists ───────────────────────────────────────────────────

# Turkish + English positive signals
_POSITIVE_HINTS: frozenset[str] = frozenset(
    {
        "teşekkür", "tesekkur", "harika", "mükemmel", "mukemmel",
        "bayıldım", "bayildim", "süper", "super", "çok iyi",
        "memnun", "love", "great", "thanks", "thank", "awesome",
        "perfect", "excellent", "wonderful", "fantastic", "amazing",
    }
)

# Turkish + English negative signals
_NEGATIVE_HINTS: frozenset[str] = frozenset(
    {
        "berbat", "kötü", "kotu", "rezalet", "iğrenç", "igrenç",
        "kırgın", "kirgın", "şikayet", "sikayet", "iade",
        "çalışmıyor", "calismıyor", "geç", "gec", "kayıp", "kayip",
        "hata", "terrible", "bad", "worst", "broken", "refund",
        "angry", "disappointed", "horrible", "awful", "disgusting",
        "unacceptable", "useless", "pathetic",
    }
)


def classify_sentiment(text: str) -> str:
    """Classify the sentiment of *text* using a keyword heuristic.

    Algorithm
    ---------
    1. Lower-case the text.
    2. Count how many positive and negative hint strings appear in it.
    3. If *any* negative hint matches → "negative" (negative wins ties).
    4. Else if *any* positive hint matches → "positive".
    5. Otherwise → "neutral".

    The function is intentionally simple and offline — it never makes network
    calls and never raises.

    Parameters
    ----------
    text:
        The raw message text to classify.

    Returns
    -------
    One of "positive", "neutral", or "negative".
    """
    lowered = text.lower()

    neg_count = sum(1 for hint in _NEGATIVE_HINTS if hint in lowered)
    pos_count = sum(1 for hint in _POSITIVE_HINTS if hint in lowered)

    if neg_count > 0:
        return "negative"
    if pos_count > 0:
        return "positive"
    return "neutral"


# ── Channel-specific reply openers ────────────────────────────────────────────

_CHANNEL_OPENER: dict[str, str] = {
    "instagram": "Merhaba! Instagram mesajınız için teşekkür ederiz.",
    "facebook": "Merhaba! Facebook mesajınız için teşekkür ederiz.",
    "x": "Merhaba! Bizi etiketlediğiniz için teşekkür ederiz.",
    "linkedin": "Merhaba! LinkedIn mesajınız için teşekkür ederiz.",
    "tiktok": "Merhaba! TikTok yorumunuz için teşekkür ederiz.",
    "youtube": "Merhaba! YouTube yorumunuz için teşekkür ederiz.",
}

# Tone-to-closing map
_TONE_CLOSING: dict[str, str] = {
    "samimi": "Size yardımcı olmaktan mutluluk duyarız. İyi günler! 😊",
    "profesyonel": "Konuya ilişkin her türlü sorunuzda bizimle iletişime geçebilirsiniz. Saygılarımızla.",
    "resmi": "Talebiniz incelenecek ve en kısa sürede geri dönüş sağlanacaktır. Saygılarımızla.",
    "eğlenceli": "Haberdar olmak için bizi takip etmeyi unutmayın! 🎉",
}


# ── Template reply generator ──────────────────────────────────────────────────


class _TemplateReplyGenerator:
    """Deterministic Turkish customer-care reply — no network, always available."""

    def generate(
        self,
        message_text: str,
        channel: str | None,
        tone: str,
    ) -> dict[str, Any]:
        opener = _CHANNEL_OPENER.get(
            channel or "",
            "Merhaba! Mesajınız için teşekkür ederiz.",
        )
        closing = _TONE_CLOSING.get(
            tone,
            "Size yardımcı olmaktan mutluluk duyarız. İyi günler!",
        )

        # Trim the original message to a brief acknowledgement quote
        trimmed = message_text.strip()
        if len(trimmed) > 80:
            trimmed = trimmed[:77] + "..."

        body = (
            f"{opener} "
            f'"{trimmed}" konusunu inceledik. '
            f"Ekibimiz en kısa sürede sizinle iletişime geçecektir. "
            f"{closing}"
        )
        return {"reply": body, "ai_assisted": False}


# ── Claude reply generator ────────────────────────────────────────────────────


class _ClaudeReplyGenerator:
    """Optional Claude-API reply generator.  Falls back to template on any error.

    The model ID is read from ``settings.claude_narrator_model`` at call time —
    never hardcoded — so changing the model in config requires only a config
    change.
    """

    def __init__(self, api_key: str, http_client: Any = None) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._fallback = _TemplateReplyGenerator()

    def generate(
        self,
        message_text: str,
        channel: str | None,
        tone: str,
    ) -> dict[str, Any]:
        try:
            return self._call_claude(message_text, channel, tone)
        except Exception as exc:
            logger.warning(
                "[ClaudeReplyGenerator] API call failed (%s) — using template", exc
            )
            return self._fallback.generate(message_text, channel, tone)

    def _call_claude(
        self,
        message_text: str,
        channel: str | None,
        tone: str,
    ) -> dict[str, Any]:
        import httpx

        from ayaz.config import settings

        model = settings.claude_narrator_model

        channel_info = f" ({channel} platformu için)" if channel else ""
        prompt = (
            f"Sen bir müşteri hizmetleri uzmanısın. "
            f"Aşağıdaki sosyal medya mesajına{channel_info} {tone} bir tonda "
            f"Türkçe, kısa ve kibar bir yanıt yaz.\n\n"
            f"Müşteri mesajı: {message_text}\n\n"
            f"Yanıtını şu JSON formatında ver (başka hiçbir şey ekleme):\n"
            f'{{"reply": "<yanıt metni>"}}'
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
        parsed = json.loads(raw_text)
        reply = str(parsed["reply"])
        if not reply:
            raise ValueError("Empty reply from Claude")

        return {"reply": reply, "ai_assisted": True}


# ── Picker ────────────────────────────────────────────────────────────────────


def _pick_reply_generator(
    http_client: Any = None,
) -> _TemplateReplyGenerator | _ClaudeReplyGenerator:
    """Return a Claude generator when an API key is configured, else template."""
    try:
        from ayaz.config import settings

        if settings.anthropic_api_key:
            return _ClaudeReplyGenerator(
                api_key=settings.anthropic_api_key,
                http_client=http_client,
            )
    except Exception:
        pass
    return _TemplateReplyGenerator()


# ── Public API ────────────────────────────────────────────────────────────────


def suggest_reply(
    message_text: str,
    channel: str | None = None,
    tone: str = "samimi",
    *,
    http_client: Any = None,
) -> dict[str, Any]:
    """Generate a Turkish customer-care reply for the given social message.

    Parameters
    ----------
    message_text:
        The full text of the inbound customer message (required).
    channel:
        Optional source channel key (e.g. "instagram").  When provided, the
        reply opener is tailored to the channel.
    tone:
        Desired reply tone.  Defaults to "samimi".  Common values:
        "samimi", "profesyonel", "resmi", "eğlenceli".
    http_client:
        Optional httpx-compatible client injected for testing.  When None, a
        real httpx.Client is used for the Claude path.

    Returns
    -------
    dict with keys:
        reply       (str)  — the suggested reply text
        ai_assisted (bool) — True when the Claude path was used successfully

    Notes
    -----
    This function NEVER raises.  The Claude path gracefully falls back to the
    template generator on any exception.  The template path works with no
    network and no API key configured.
    """
    generator = _pick_reply_generator(http_client=http_client)
    try:
        return generator.generate(message_text, channel, tone)
    except Exception as exc:
        logger.warning(
            "[suggest_reply] Generator raised unexpectedly (%s) — using template", exc
        )
        return _TemplateReplyGenerator().generate(message_text, channel, tone)


def compute_inbox_stats(messages: list) -> dict[str, Any]:
    """Aggregate a list of SocialMessage objects into an inbox stats dict.

    Uses ``getattr`` defensively so plain stubs without all fields don't crash.
    Works with any object that has the expected attributes — no ORM import
    required.

    Parameters
    ----------
    messages:
        List of SocialMessage ORM objects (or attribute-compatible stubs).

    Returns
    -------
    dict with keys:
        total        (int)  — total message count
        open         (int)  — messages with status "open"
        pending      (int)  — messages with status "pending"
        resolved     (int)  — messages with status "resolved"
        by_status    (dict) — {status: count}
        by_channel   (dict) — {channel: count}
        by_sentiment (dict) — {sentiment: count}
        by_kind      (dict) — {kind: count}
    """
    by_status: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    by_sentiment: dict[str, int] = {}
    by_kind: dict[str, int] = {}

    for msg in messages:
        status = getattr(msg, "status", "open") or "open"
        channel = getattr(msg, "channel", "unknown") or "unknown"
        sentiment = getattr(msg, "sentiment", "neutral") or "neutral"
        kind = getattr(msg, "kind", "unknown") or "unknown"

        by_status[status] = by_status.get(status, 0) + 1
        by_channel[channel] = by_channel.get(channel, 0) + 1
        by_sentiment[sentiment] = by_sentiment.get(sentiment, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1

    return {
        "total": len(messages),
        "by_status": by_status,
        "by_channel": by_channel,
        "by_sentiment": by_sentiment,
        "by_kind": by_kind,
        "open": by_status.get("open", 0),
        "pending": by_status.get("pending", 0),
        "resolved": by_status.get("resolved", 0),
    }
