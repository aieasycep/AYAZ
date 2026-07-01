"""AI Reklam Metni Stüdyosu (Ad Copy Studio) service layer — M15 Dalga 73.

Public API
----------
    generate_ad_copy(brief, *, n_variants=3, http_client=None)
        -> {"platform": str, "platform_label": str, "source": str,
            "tone": str, "tone_label": str, "variants": [...]}

    save_draft(db, tenant_id, *, platform, title, brief, variants, source) -> dict
    list_drafts(db, tenant_id, *, status=None) -> list[dict]
    update_draft_status(db, tenant_id, draft_id, status) -> dict
    delete_draft(db, tenant_id, draft_id) -> None

Platform specs
--------------
PLATFORM_SPECS maps platform key → list of field defs with Turkish labels
and character limits (real Google / Meta / TikTok ad limits).

Generation
----------
Two paths — same pattern as content.py:

  _TemplateAdCopyGenerator (default, no network)
      Deterministic Turkish copy built from brief fields.  Always works.
      source="template", ai_assisted=False.

  _ClaudeAdCopyGenerator (opt-in)
      Calls the Claude API via raw httpx POST.  Requires
      settings.anthropic_api_key + settings.claude_narrator_model.
      Falls back to _TemplateAdCopyGenerator on ANY exception.
      source="ai" on success, "template" on fallback.

Tenant isolation
----------------
save/list/update/delete all filter by tenant_id.  generate_ad_copy is
a pure stateless helper — no DB access.
"""

from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Platform specs ─────────────────────────────────────────────────────────────

# Each field: key (str), label (Turkish str), max_len (int)
PLATFORM_SPECS: dict[str, list[dict[str, Any]]] = {
    "google_ads": [
        {"key": "headline_1",     "label": "Başlık 1",       "max_len": 30},
        {"key": "headline_2",     "label": "Başlık 2",       "max_len": 30},
        {"key": "headline_3",     "label": "Başlık 3",       "max_len": 30},
        {"key": "description_1",  "label": "Açıklama 1",     "max_len": 90},
        {"key": "description_2",  "label": "Açıklama 2",     "max_len": 90},
    ],
    "meta_ads": [
        {"key": "primary_text",      "label": "Ana Metin",        "max_len": 125},
        {"key": "headline",          "label": "Başlık",           "max_len": 40},
        {"key": "link_description",  "label": "Bağlantı Açıklaması", "max_len": 30},
    ],
    "tiktok_ads": [
        {"key": "caption",   "label": "Açıklama Metni", "max_len": 100},
        {"key": "hashtags",  "label": "Etiketler",      "max_len": 100},
    ],
}

_PLATFORM_LABELS: dict[str, str] = {
    "google_ads":  "Google Ads",
    "meta_ads":    "Meta (Facebook/Instagram)",
    "tiktok_ads":  "TikTok Ads",
}

_TONE_LABELS: dict[str, str] = {
    "profesyonel":    "Profesyonel",
    "samimi":         "Samimi",
    "heyecanli":      "Heyecanlı",
    "bilgilendirici": "Bilgilendirici",
}

# Tone-specific phrases used in template copy
_TONE_INTROS: dict[str, str] = {
    "profesyonel":    "Lider kalitesiyle",
    "samimi":         "Sizi düşünerek",
    "heyecanli":      "Hemen keşfedin —",
    "bilgilendirici": "Bilmeniz gerekenler:",
}

_TONE_CTAS: dict[str, str] = {
    "profesyonel":    "Hemen inceleyin.",
    "samimi":         "Şimdi deneyin.",
    "heyecanli":      "Kaçırmayın!",
    "bilgilendirici": "Detayları keşfedin.",
}

# Variant angle labels — one per index, cycling
_ANGLES: list[str] = [
    "fayda-odakli",
    "aciliyet-odakli",
    "sosyal-kanit-odakli",
    "soru-odakli",
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe_truncate(text: str, max_len: int) -> str:
    """Truncate *text* to at most *max_len* characters, appending '…' if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _field_entry(key: str, label: str, value: str, max_len: int) -> dict[str, Any]:
    """Build the uniform field dict that the frontend renders generically."""
    char_count = len(value)
    return {
        "key": key,
        "label": label,
        "value": value,
        "char_count": char_count,
        "max_len": max_len,
        "within_limit": char_count <= max_len,
    }


def _keywords_str(keywords: list[str], max_kw: int = 3) -> str:
    """Return a comma-joined string of the first *max_kw* keywords."""
    return ", ".join(keywords[:max_kw]) if keywords else ""


# ── Template generator ────────────────────────────────────────────────────────


class _TemplateAdCopyGenerator:
    """Deterministic Turkish ad copy — no network, always available."""

    def generate(
        self,
        brief: dict[str, Any],
        n_variants: int,
    ) -> dict[str, Any]:
        platform: str = brief["platform"]
        product: str = brief["product"]
        value_prop: str = brief.get("value_prop") or ""
        tone: str = brief.get("tone") or "profesyonel"
        keywords: list[str] = brief.get("keywords") or []
        audience: str = brief.get("audience") or ""

        tone_intro = _TONE_INTROS.get(tone, "")
        tone_cta = _TONE_CTAS.get(tone, "Hemen keşfedin.")
        kw_str = _keywords_str(keywords)
        specs = PLATFORM_SPECS[platform]

        variants: list[dict[str, Any]] = []
        for i in range(n_variants):
            angle = _ANGLES[i % len(_ANGLES)]
            fields = self._build_fields(
                specs, platform, product, value_prop, tone_intro,
                tone_cta, kw_str, audience, angle, i,
            )
            variants.append({"index": i, "fields": fields})

        return {
            "platform": platform,
            "platform_label": _PLATFORM_LABELS[platform],
            "source": "template",
            "tone": tone,
            "tone_label": _TONE_LABELS.get(tone, tone.capitalize()),
            "variants": variants,
        }

    # ── Per-platform copy builders ────────────────────────────────────────────

    def _build_fields(
        self,
        specs: list[dict[str, Any]],
        platform: str,
        product: str,
        value_prop: str,
        tone_intro: str,
        tone_cta: str,
        kw_str: str,
        audience: str,
        angle: str,
        idx: int,
    ) -> list[dict[str, Any]]:
        if platform == "google_ads":
            return self._google_fields(
                specs, product, value_prop, tone_intro, tone_cta, kw_str, angle, idx
            )
        if platform == "meta_ads":
            return self._meta_fields(
                specs, product, value_prop, tone_intro, tone_cta, kw_str, audience, angle, idx
            )
        # tiktok_ads
        return self._tiktok_fields(
            specs, product, value_prop, tone_intro, tone_cta, kw_str, angle, idx
        )

    def _google_fields(
        self,
        specs: list[dict[str, Any]],
        product: str,
        value_prop: str,
        tone_intro: str,
        tone_cta: str,
        kw_str: str,
        angle: str,
        idx: int,
    ) -> list[dict[str, Any]]:
        # Build raw values for the 5 fields
        vp_short = value_prop[:20] if value_prop else "Kalite Garantili"
        kw_hint = kw_str[:15] if kw_str else product[:15]

        raw: dict[str, str] = {}
        if angle == "fayda-odakli":
            raw["headline_1"] = f"{product[:25]}"
            raw["headline_2"] = f"{vp_short[:28]}"
            raw["headline_3"] = tone_cta[:28]
            raw["description_1"] = (
                f"{tone_intro} {product} ile tanışın. {value_prop or 'En iyi seçim.'}"[:88]
            )
            raw["description_2"] = (
                f"Hemen sipariş verin, {kw_hint} fırsatını kaçırmayın. {tone_cta}"[:88]
            )
        elif angle == "aciliyet-odakli":
            raw["headline_1"] = f"Fırsat: {product[:22]}"
            raw["headline_2"] = "Sınırlı Stok!"[:29]
            raw["headline_3"] = tone_cta[:28]
            raw["description_1"] = (
                f"Stoklar tükenmeden {product} siparişinizi verin. {value_prop or ''}"[:88]
            ).rstrip()
            raw["description_2"] = (
                f"Özel teklif — {kw_hint} ile avantajlı alışveriş. {tone_cta}"[:88]
            )
        elif angle == "sosyal-kanit-odakli":
            raw["headline_1"] = f"Müşteriler Sevdi: {product[:12]}"
            raw["headline_2"] = "Binlerce Memnun Kullanıcı"[:29]
            raw["headline_3"] = tone_cta[:28]
            raw["description_1"] = (
                f"Binlerce müşteri {product} tercih etti. {value_prop or 'Siz de katılın.'}"[:88]
            )
            raw["description_2"] = (
                f"Güvenilir kalite, {kw_hint} garantisi. {tone_cta}"[:88]
            )
        else:  # soru-odakli
            raw["headline_1"] = f"{product[:20]} Arayışında mısınız?"
            raw["headline_2"] = f"{vp_short[:28]}"
            raw["headline_3"] = tone_cta[:28]
            raw["description_1"] = (
                f"Doğru ürünü arıyorsanız {product} tam size göre. {value_prop or ''}"[:88]
            ).rstrip()
            raw["description_2"] = (
                f"Detayları inceleyin, {kw_hint} hakkında bilgi alın. {tone_cta}"[:88]
            )

        fields = []
        for spec in specs:
            k = spec["key"]
            raw_val = raw.get(k, f"{product} — {k}")
            truncated = _safe_truncate(raw_val, spec["max_len"])
            fields.append(_field_entry(k, spec["label"], truncated, spec["max_len"]))
        return fields

    def _meta_fields(
        self,
        specs: list[dict[str, Any]],
        product: str,
        value_prop: str,
        tone_intro: str,
        tone_cta: str,
        kw_str: str,
        audience: str,
        angle: str,
        idx: int,
    ) -> list[dict[str, Any]]:
        aud_phrase = f" {audience}" if audience else ""
        vp = value_prop or "Kalitesi ile öne çıkıyor"
        kw_hint = kw_str or product

        raw: dict[str, str] = {}
        if angle == "fayda-odakli":
            raw["primary_text"] = (
                f"{tone_intro} {product} — {vp}. {tone_cta}"
            )
            raw["headline"] = f"{product} — Şimdi Keşfet"
            raw["link_description"] = "Hemen inceleyin"
        elif angle == "aciliyet-odakli":
            raw["primary_text"] = (
                f"Fırsat kaçmadan {product} siparişinizi verin.{aud_phrase} {vp}. {tone_cta}"
            )
            raw["headline"] = f"Son Fırsat: {product[:28]}"
            raw["link_description"] = "Stok tükenmeden al"
        elif angle == "sosyal-kanit-odakli":
            raw["primary_text"] = (
                f"Binlerce kullanıcı {product} tercih etti. {vp}. Siz de deneyin! {tone_cta}"
            )
            raw["headline"] = f"{product} — Çok Satanlar"
            raw["link_description"] = "İncele ve sipariş ver"
        else:  # soru-odakli
            raw["primary_text"] = (
                f"{product} hakkında merak mı ediyorsunuz?{aud_phrase} {vp}. {tone_cta}"
            )
            raw["headline"] = f"Neden {product[:32]}?"
            raw["link_description"] = "Cevapları burada"

        fields = []
        for spec in specs:
            k = spec["key"]
            raw_val = raw.get(k, f"{product}")
            truncated = _safe_truncate(raw_val, spec["max_len"])
            fields.append(_field_entry(k, spec["label"], truncated, spec["max_len"]))
        return fields

    def _tiktok_fields(
        self,
        specs: list[dict[str, Any]],
        product: str,
        value_prop: str,
        tone_intro: str,
        tone_cta: str,
        kw_str: str,
        angle: str,
        idx: int,
    ) -> list[dict[str, Any]]:
        vp = value_prop or "harika özellikleriyle"
        kw_list = kw_str.replace(", ", " ").split()[:4] if kw_str else [product.split()[0].lower()]

        raw: dict[str, str] = {}
        if angle == "fayda-odakli":
            raw["caption"] = f"{product} {vp} 🔥 {tone_cta}"
            raw["hashtags"] = " ".join(f"#{w.lower()}" for w in ([product.replace(" ", "")] + kw_list))
        elif angle == "aciliyet-odakli":
            raw["caption"] = f"Bunu kaçırma! {product} — {vp} ⏰ {tone_cta}"
            raw["hashtags"] = " ".join(f"#{w.lower()}" for w in (["firsatlar", product.replace(" ", "")] + kw_list[:2]))
        elif angle == "sosyal-kanit-odakli":
            raw["caption"] = f"Herkes konuşuyor: {product} — {vp} 💬 {tone_cta}"
            raw["hashtags"] = " ".join(f"#{w.lower()}" for w in (["viral", product.replace(" ", "")] + kw_list[:2]))
        else:  # soru-odakli
            raw["caption"] = f"{product} doğru seçim mi? {vp} 🤔 {tone_cta}"
            raw["hashtags"] = " ".join(f"#{w.lower()}" for w in (["kesfet", product.replace(" ", "")] + kw_list[:2]))

        fields = []
        for spec in specs:
            k = spec["key"]
            raw_val = raw.get(k, product)
            truncated = _safe_truncate(raw_val, spec["max_len"])
            fields.append(_field_entry(k, spec["label"], truncated, spec["max_len"]))
        return fields


# ── Claude generator ──────────────────────────────────────────────────────────


class _ClaudeAdCopyGenerator:
    """Optional Claude-API ad copy generator.  Falls back to template on any error.

    The model ID is read from ``settings.claude_narrator_model`` at call time —
    never hardcoded.
    """

    def __init__(self, api_key: str, http_client: Any = None) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._fallback = _TemplateAdCopyGenerator()

    def generate(
        self,
        brief: dict[str, Any],
        n_variants: int,
    ) -> dict[str, Any]:
        try:
            return self._call_claude(brief, n_variants)
        except Exception as exc:
            logger.warning(
                "[ClaudeAdCopyGenerator] API call failed (%s) — using template", exc
            )
            return self._fallback.generate(brief, n_variants)

    def _call_claude(
        self,
        brief: dict[str, Any],
        n_variants: int,
    ) -> dict[str, Any]:
        import httpx

        from ayaz.config import settings

        model = settings.claude_narrator_model

        platform = brief["platform"]
        product = brief["product"]
        value_prop = brief.get("value_prop") or ""
        tone = brief.get("tone") or "profesyonel"
        keywords = brief.get("keywords") or []
        audience = brief.get("audience") or ""

        platform_label = _PLATFORM_LABELS[platform]
        specs = PLATFORM_SPECS[platform]
        fields_desc = "; ".join(
            f"{s['key']} (maks. {s['max_len']} karakter)" for s in specs
        )
        kw_str = ", ".join(keywords) if keywords else "(yok)"

        prompt = (
            f"Sen bir dijital reklam metin yazarısın. "
            f"Aşağıdaki bilgileri kullanarak {platform_label} için Türkçe reklam metni üret.\n\n"
            f"Platform: {platform_label}\n"
            f"Ürün/Hizmet: {product}\n"
            f"Değer Önerisi: {value_prop or '(belirtilmedi)'}\n"
            f"Ton: {tone}\n"
            f"Anahtar Kelimeler: {kw_str}\n"
            f"Hedef Kitle: {audience or '(belirtilmedi)'}\n\n"
            f"Her varyant için şu alanları doldur: {fields_desc}\n"
            f"Her alanın karakter sınırına kesinlikle uy.\n\n"
            f"Tam olarak {n_variants} farklı varyant üret (fayda-odaklı, aciliyet-odaklı, "
            f"sosyal-kanıt-odaklı, soru-odaklı açılarını kullan).\n\n"
            f"Yanıtını YALNIZCA aşağıdaki JSON formatında ver, başka hiçbir şey ekleme:\n"
            f'{{"variants": ['
            f'{{"index": 0, "fields": [{{"key": "...", "value": "..."}}]}}, ...'
            f']}}'
        )

        payload = {
            "model": model,
            "max_tokens": 1500,
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
                timeout=30.0,
            )
        else:
            with httpx.Client() as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:200]}"
            )

        raw_text = resp.json()["content"][0]["text"].strip()
        # Strip markdown code fences if present
        raw_text = re.sub(r"^```[a-z]*\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        parsed = json.loads(raw_text)
        raw_variants = parsed["variants"]
        if not isinstance(raw_variants, list) or len(raw_variants) == 0:
            raise ValueError("variants must be a non-empty list")

        # Rebuild with the uniform field shape (add char_count, max_len, within_limit)
        specs = PLATFORM_SPECS[platform]
        spec_map = {s["key"]: s for s in specs}
        variants = []
        for i, rv in enumerate(raw_variants[:n_variants]):
            fields_in = {f["key"]: f["value"] for f in rv.get("fields", [])}
            fields_out = []
            for spec in specs:
                k = spec["key"]
                val = str(fields_in.get(k, ""))
                truncated = _safe_truncate(val, spec["max_len"])
                fields_out.append(
                    _field_entry(k, spec["label"], truncated, spec["max_len"])
                )
            variants.append({"index": i, "fields": fields_out})

        tone = brief.get("tone") or "profesyonel"
        return {
            "platform": platform,
            "platform_label": _PLATFORM_LABELS[platform],
            "source": "ai",
            "tone": tone,
            "tone_label": _TONE_LABELS.get(tone, tone.capitalize()),
            "variants": variants,
        }


# ── Picker ────────────────────────────────────────────────────────────────────


def _pick_generator(
    http_client: Any = None,
) -> _TemplateAdCopyGenerator | _ClaudeAdCopyGenerator:
    """Return a Claude generator when an API key is configured, else template."""
    try:
        from ayaz.config import settings

        if settings.anthropic_api_key:
            return _ClaudeAdCopyGenerator(
                api_key=settings.anthropic_api_key,
                http_client=http_client,
            )
    except Exception:
        pass
    return _TemplateAdCopyGenerator()


# ── Public generation API ─────────────────────────────────────────────────────


def generate_ad_copy(
    brief: dict[str, Any],
    *,
    n_variants: int = 3,
    http_client: Any = None,
) -> dict[str, Any]:
    """Generate platform-specific Turkish ad copy from a brief.

    Parameters
    ----------
    brief:
        Dict with keys:
        - platform (required): "google_ads" | "meta_ads" | "tiktok_ads"
        - product (required): product/service name
        - value_prop: unique selling point
        - tone: "profesyonel" | "samimi" | "heyecanli" | "bilgilendirici"
        - keywords: list of keyword strings
        - audience: target audience description
    n_variants:
        Number of distinct variants to generate (default 3).
    http_client:
        Optional httpx-compatible client injected for testing.

    Returns
    -------
    Dict with keys: platform, platform_label, source, tone, tone_label, variants.
    Each variant: {"index": int, "fields": [{"key", "label", "value",
    "char_count", "max_len", "within_limit"}, ...]}.

    Raises
    ------
    ValueError
        When ``platform`` is missing/unknown or ``product`` is missing.
    """
    platform = (brief.get("platform") or "").strip()
    product = (brief.get("product") or "").strip()

    if not platform:
        raise ValueError("'platform' alanı zorunludur.")
    if platform not in PLATFORM_SPECS:
        raise ValueError(
            f"Bilinmeyen platform: {platform!r}. "
            f"Geçerli değerler: {sorted(PLATFORM_SPECS)}"
        )
    if not product:
        raise ValueError("'product' alanı zorunludur.")

    # Normalise brief for the generators
    normalised = dict(brief)
    normalised["platform"] = platform
    normalised["product"] = product

    generator = _pick_generator(http_client=http_client)
    try:
        return generator.generate(normalised, n_variants)
    except Exception as exc:
        logger.warning(
            "[generate_ad_copy] Generator raised unexpectedly (%s) — using template",
            exc,
        )
        return _TemplateAdCopyGenerator().generate(normalised, n_variants)


# ── Draft library CRUD ────────────────────────────────────────────────────────


def _serialize_draft(d: Any) -> dict[str, Any]:
    """Serialize an AdCopyDraft ORM row to a plain dict for API responses."""
    return {
        "id": str(d.id),
        "platform": d.platform,
        "platform_label": _PLATFORM_LABELS.get(d.platform, d.platform),
        "title": d.title,
        "brief": d.brief,
        "variants": d.variants,
        "source": d.source,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def save_draft(
    db: Session,
    tenant_id: _uuid.UUID,
    *,
    platform: str,
    title: str,
    brief: dict[str, Any],
    variants: list[dict[str, Any]],
    source: str = "template",
) -> dict[str, Any]:
    """Persist a new AdCopyDraft and return its serialized form.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    tenant_id:
        Tenant UUID — enforced on the row.
    platform, title, brief, variants, source:
        Draft fields.

    Returns
    -------
    Serialized draft dict (see _serialize_draft).
    """
    from ayaz.models.ad_studio import AdCopyDraft

    draft = AdCopyDraft(
        tenant_id=tenant_id,
        platform=platform,
        title=title,
        brief=brief,
        variants=variants,
        source=source,
        status="saved",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


def list_drafts(
    db: Session,
    tenant_id: _uuid.UUID,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return AdCopyDrafts for the tenant, newest first.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    tenant_id:
        Tenant UUID — row-level filter.
    status:
        Optional status filter ("saved" | "archived").  When None all statuses
        are returned.

    Returns
    -------
    List of serialized draft dicts ordered by created_at DESC.
    """
    from ayaz.models.ad_studio import AdCopyDraft

    q = select(AdCopyDraft).where(AdCopyDraft.tenant_id == tenant_id)
    if status is not None:
        q = q.where(AdCopyDraft.status == status)
    q = q.order_by(AdCopyDraft.created_at.desc())
    rows = db.scalars(q).all()
    return [_serialize_draft(r) for r in rows]


def update_draft_status(
    db: Session,
    tenant_id: _uuid.UUID,
    draft_id: str | _uuid.UUID,
    status: str,
) -> dict[str, Any]:
    """Update the status of an existing draft.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    tenant_id:
        Tenant UUID — enforces isolation.
    draft_id:
        UUID of the draft to update.
    status:
        New status value ("saved" | "archived").

    Returns
    -------
    Serialized updated draft dict.

    Raises
    ------
    ValueError
        When *status* is not one of the valid values.
    ValueError
        When the draft is not found or belongs to a different tenant (404-style).
    """
    from ayaz.models.ad_studio import AdCopyDraft, VALID_STATUSES

    if status not in VALID_STATUSES:
        raise ValueError(
            f"Geçersiz durum: {status!r}. "
            f"Geçerli değerler: {sorted(VALID_STATUSES)}"
        )

    try:
        draft_uuid = _uuid.UUID(str(draft_id))
    except (ValueError, AttributeError):
        raise ValueError(f"Geçersiz draft_id: {draft_id!r}")

    draft = db.scalar(
        select(AdCopyDraft).where(
            AdCopyDraft.id == draft_uuid,
            AdCopyDraft.tenant_id == tenant_id,
        )
    )
    if draft is None:
        raise LookupError(f"Taslak bulunamadı: {draft_id}")

    draft.status = status
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


def delete_draft(
    db: Session,
    tenant_id: _uuid.UUID,
    draft_id: str | _uuid.UUID,
) -> None:
    """Hard-delete a draft.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    tenant_id:
        Tenant UUID — enforces isolation.
    draft_id:
        UUID of the draft to delete.

    Raises
    ------
    LookupError
        When the draft is not found or belongs to a different tenant.
    """
    from ayaz.models.ad_studio import AdCopyDraft

    try:
        draft_uuid = _uuid.UUID(str(draft_id))
    except (ValueError, AttributeError):
        raise LookupError(f"Taslak bulunamadı: {draft_id}")

    draft = db.scalar(
        select(AdCopyDraft).where(
            AdCopyDraft.id == draft_uuid,
            AdCopyDraft.tenant_id == tenant_id,
        )
    )
    if draft is None:
        raise LookupError(f"Taslak bulunamadı: {draft_id}")

    db.delete(draft)
    db.commit()
