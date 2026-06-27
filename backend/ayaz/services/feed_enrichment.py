"""AI product enrichment service — Dalga 49 (Channable Optimize-style).

Two operating modes (same Claude-with-stub-fallback pattern as feed_rule_nlp.py):

Claude path (when settings.anthropic_api_key is set)
    Calls the Anthropic Messages API via httpx.  Falls back to the heuristic stub
    on any error, so the endpoint never 500s on LLM failures.

Stub / heuristic path (default — no API key required)
    Deterministic keyword-based heuristics that cover the five enrichable fields.
    This is the path exercised by the test suite.

Public API
----------
    suggest_enrichment(products, fields) -> dict
        Pure function — no DB access, no side effects.
        Returns:
            {
                "suggestions": [
                    {
                        "product_id": str,
                        "field": str,
                        "current": str,
                        "suggested": str,
                        "confidence": "high" | "low",
                        "source": "ai" | "heuristic",
                    },
                    ...
                ]
            }
        Only generates a suggestion for a product/field combination when the
        current value is empty or missing.

Enrichable fields
-----------------
color    (renk)     — Turkish + English color words from title/description
brand    (marka)    — leading capitalized word when brand is empty
category            — keyword → category mapping
material (materyal) — material keywords from title/description
title               — collapse double spaces, trim, suggest if differs
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── ENRICHABLE_FIELDS ─────────────────────────────────────────────────────────

ENRICHABLE_FIELDS = {"color", "brand", "category", "material", "title"}

# ── Color heuristics ──────────────────────────────────────────────────────────

# Maps each color keyword (Turkish + English, lowercased) to its canonical value.
_COLOR_MAP: dict[str, str] = {
    # Turkish
    "siyah": "Siyah",
    "beyaz": "Beyaz",
    "kırmızı": "Kırmızı",
    "mavi": "Mavi",
    "yeşil": "Yeşil",
    "sarı": "Sarı",
    "pembe": "Pembe",
    "mor": "Mor",
    "gri": "Gri",
    "lacivert": "Lacivert",
    "turuncu": "Turuncu",
    "kahverengi": "Kahverengi",
    "bej": "Bej",
    "krem": "Krem",
    "altın": "Altın",
    "gümüş": "Gümüş",
    "bronz": "Bronz",
    "şampanya": "Şampanya",
    "pudra": "Pudra",
    "ekru": "Ekru",
    "haki": "Haki",
    "bordo": "Bordo",
    "fuşya": "Fuşya",
    "lila": "Lila",
    "indigo": "İndigo",
    # English
    "black": "Siyah",
    "white": "Beyaz",
    "red": "Kırmızı",
    "blue": "Mavi",
    "green": "Yeşil",
    "yellow": "Sarı",
    "pink": "Pembe",
    "purple": "Mor",
    "grey": "Gri",
    "gray": "Gri",
    "navy": "Lacivert",
    "orange": "Turuncu",
    "brown": "Kahverengi",
    "beige": "Bej",
    "cream": "Krem",
    "gold": "Altın",
    "silver": "Gümüş",
    "bronze": "Bronz",
    "khaki": "Haki",
    "maroon": "Bordo",
    "fuchsia": "Fuşya",
    "lilac": "Lila",
    "indigo": "İndigo",
    "turquoise": "Turkuaz",
    "turkuaz": "Turkuaz",
    "mint": "Mint",
    "coral": "Mercan",
    "mercan": "Mercan",
    "rose": "Gül Kurusu",
}

# Pre-sorted by length descending so multi-word / longer keywords match first
# (e.g. "lacivert" before "mavi")
_COLOR_KEYWORDS_SORTED: list[str] = sorted(_COLOR_MAP.keys(), key=len, reverse=True)


def _extract_color(text: str) -> str | None:
    """Return the first color keyword found in text, or None."""
    lower = text.lower()
    for keyword in _COLOR_KEYWORDS_SORTED:
        # Word-boundary match so "krem" doesn't match inside "kremsi"
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower):
            return _COLOR_MAP[keyword]
    return None


# ── Material heuristics ───────────────────────────────────────────────────────

_MATERIAL_MAP: dict[str, str] = {
    # Turkish
    "pamuk": "Pamuk",
    "deri": "Deri",
    "plastik": "Plastik",
    "metal": "Metal",
    "ahşap": "Ahşap",
    "cam": "Cam",
    "kumaş": "Kumaş",
    "keten": "Keten",
    "ipek": "İpek",
    "yün": "Yün",
    "naylon": "Naylon",
    "polyester": "Polyester",
    "akrilik": "Akrilik",
    "vizon": "Vizon",
    "kadife": "Kadife",
    "denim": "Denim",
    "kot": "Denim",
    "süet": "Süet",
    "kanvas": "Kanvas",
    "kauçuk": "Kauçuk",
    "silikon": "Silikon",
    "seramik": "Seramik",
    "porselen": "Porselen",
    "alüminyum": "Alüminyum",
    "çelik": "Çelik",
    "paslanmaz": "Paslanmaz Çelik",
    "karbon": "Karbon Fiber",
    "mermer": "Mermer",
    "granit": "Granit",
    # English
    "cotton": "Pamuk",
    "leather": "Deri",
    "plastic": "Plastik",
    "wood": "Ahşap",
    "glass": "Cam",
    "fabric": "Kumaş",
    "linen": "Keten",
    "silk": "İpek",
    "wool": "Yün",
    "nylon": "Naylon",
    "acrylic": "Akrilik",
    "velvet": "Kadife",
    "canvas": "Kanvas",
    "rubber": "Kauçuk",
    "silicone": "Silikon",
    "ceramic": "Seramik",
    "porcelain": "Porselen",
    "aluminum": "Alüminyum",
    "aluminium": "Alüminyum",
    "steel": "Çelik",
    "stainless": "Paslanmaz Çelik",
    "carbon": "Karbon Fiber",
    "marble": "Mermer",
    "granite": "Granit",
}

_MATERIAL_KEYWORDS_SORTED: list[str] = sorted(_MATERIAL_MAP.keys(), key=len, reverse=True)


def _extract_material(text: str) -> str | None:
    """Return the first material keyword found in text, or None."""
    lower = text.lower()
    for keyword in _MATERIAL_KEYWORDS_SORTED:
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower):
            return _MATERIAL_MAP[keyword]
    return None


# ── Category heuristics ───────────────────────────────────────────────────────

# keyword (lower) → canonical category string
# Longer/more-specific keywords are listed first in the list; the first match wins.
_CATEGORY_RULES: list[tuple[str, str]] = [
    # Electronics — specific first
    ("telefon kılıf", "Elektronik > Telefon Aksesuarları"),
    ("kılıf", "Elektronik > Telefon Aksesuarları"),
    ("iphone", "Elektronik > Akıllı Telefonlar"),
    ("samsung", "Elektronik > Akıllı Telefonlar"),
    ("telefon", "Elektronik > Akıllı Telefonlar"),
    ("laptop", "Elektronik > Bilgisayarlar"),
    ("bilgisayar", "Elektronik > Bilgisayarlar"),
    ("tablet", "Elektronik > Tabletler"),
    ("kulaklık", "Elektronik > Ses Sistemleri"),
    ("hoparlör", "Elektronik > Ses Sistemleri"),
    ("klavye", "Elektronik > Bilgisayar Aksesuarları"),
    ("mouse", "Elektronik > Bilgisayar Aksesuarları"),
    ("televizyon", "Elektronik > Televizyonlar"),
    ("tv", "Elektronik > Televizyonlar"),
    ("kamera", "Elektronik > Kameralar"),
    ("fotoğraf makinesi", "Elektronik > Kameralar"),
    ("şarj", "Elektronik > Şarj Cihazları"),
    ("elektronik", "Elektronik"),
    # Shoes — before generic Giyim
    ("ayakkabı", "Giyim > Ayakkabı"),
    ("sneaker", "Giyim > Ayakkabı"),
    ("bot", "Giyim > Ayakkabı"),
    ("sandal", "Giyim > Ayakkabı"),
    ("terlik", "Giyim > Ayakkabı"),
    ("spor ayakkabı", "Giyim > Spor Ayakkabı"),
    # Clothing
    ("tişört", "Giyim > Tişört"),
    ("t-shirt", "Giyim > Tişört"),
    ("gömlek", "Giyim > Gömlek"),
    ("pantolon", "Giyim > Pantolon"),
    ("etek", "Giyim > Etek"),
    ("elbise", "Giyim > Elbise"),
    ("ceket", "Giyim > Ceket"),
    ("mont", "Giyim > Mont"),
    ("kazak", "Giyim > Kazak"),
    ("sweatshirt", "Giyim > Sweatshirt"),
    ("hoodie", "Giyim > Sweatshirt"),
    ("şort", "Giyim > Şort"),
    ("eşofman", "Giyim > Eşofman"),
    ("iç çamaşır", "Giyim > İç Giyim"),
    ("çorap", "Giyim > Çorap"),
    ("kıyafet", "Giyim"),
    ("giyim", "Giyim"),
    # Bags / Accessories
    ("çanta", "Aksesuar > Çanta"),
    ("sırt çantası", "Aksesuar > Sırt Çantası"),
    ("kemer", "Aksesuar > Kemer"),
    ("şapka", "Aksesuar > Şapka"),
    ("gözlük", "Aksesuar > Gözlük"),
    ("saat", "Aksesuar > Saat"),
    ("takı", "Aksesuar > Takı"),
    ("kolye", "Aksesuar > Takı"),
    ("bileklik", "Aksesuar > Takı"),
    ("yüzük", "Aksesuar > Takı"),
    ("küpe", "Aksesuar > Takı"),
    # Home / Kitchen
    ("mobilya", "Ev & Yaşam > Mobilya"),
    ("sandalye", "Ev & Yaşam > Mobilya"),
    ("masa", "Ev & Yaşam > Mobilya"),
    ("koltuk", "Ev & Yaşam > Mobilya"),
    ("yatak", "Ev & Yaşam > Yatak & Yorgan"),
    ("yorgan", "Ev & Yaşam > Yatak & Yorgan"),
    ("yastık", "Ev & Yaşam > Yatak & Yorgan"),
    ("tencere", "Ev & Yaşam > Mutfak"),
    ("tava", "Ev & Yaşam > Mutfak"),
    ("mutfak", "Ev & Yaşam > Mutfak"),
    ("beyaz eşya", "Ev & Yaşam > Beyaz Eşya"),
    ("buzdolabı", "Ev & Yaşam > Beyaz Eşya"),
    ("çamaşır makinesi", "Ev & Yaşam > Beyaz Eşya"),
    # Beauty / Personal care
    ("parfüm", "Güzellik & Kişisel Bakım > Parfüm"),
    ("krem", "Güzellik & Kişisel Bakım > Cilt Bakımı"),
    ("şampuan", "Güzellik & Kişisel Bakım > Saç Bakımı"),
    ("makyaj", "Güzellik & Kişisel Bakım > Makyaj"),
    ("ruj", "Güzellik & Kişisel Bakım > Makyaj"),
    ("fondöten", "Güzellik & Kişisel Bakım > Makyaj"),
    # Sports
    ("spor", "Spor > Spor Ekipmanları"),
    ("fitness", "Spor > Fitness"),
    ("bisiklet", "Spor > Bisiklet"),
    # Books / Stationery
    ("kitap", "Kitap & Kırtasiye > Kitap"),
    ("defter", "Kitap & Kırtasiye > Kırtasiye"),
    ("kalem", "Kitap & Kırtasiye > Kırtasiye"),
    # Toys
    ("oyuncak", "Oyuncak & Hobi"),
    ("puzzle", "Oyuncak & Hobi"),
    ("lego", "Oyuncak & Hobi"),
    # Food
    ("gıda", "Gıda & İçecek"),
    ("yiyecek", "Gıda & İçecek"),
    ("içecek", "Gıda & İçecek"),
]


def _extract_category(text: str) -> str | None:
    """Return category string from keyword lookup, or None."""
    lower = text.lower()
    for keyword, category in _CATEGORY_RULES:
        if keyword in lower:
            return category
    return None


# ── Brand heuristics ──────────────────────────────────────────────────────────


def _extract_brand(text: str) -> str | None:
    """Heuristic: first word of title if it is a TitleCase or ALL-CAPS token.

    Returns (suggested_brand, confidence="low") or None.
    Turkish common words that look like brands are excluded.
    """
    _COMMON_WORDS = {
        "the", "bir", "bu", "şu", "o", "ve", "ile", "için", "de", "da",
        "den", "dan", "te", "ta", "a", "an", "in", "on", "at", "to",
        "new", "yeni", "eski", "büyük", "küçük", "mini", "max", "pro",
        "super", "ultra", "plus", "lite", "premium", "deluxe",
    }
    if not text:
        return None
    # Take the first whitespace-separated token
    first = text.split()[0] if text.split() else ""
    if not first:
        return None
    # Skip if it's a number, URL, or known common word
    if first.lower() in _COMMON_WORDS:
        return None
    if re.fullmatch(r"[\d\W]+", first):
        return None
    # Accept if Title-Cased (first char upper, rest lower) or ALL-CAPS (>=2 chars)
    if (first[0].isupper() and (len(first) == 1 or first[1:].islower())):
        return first
    if first.isupper() and len(first) >= 2:
        return first
    return None


# ── Title cleanup heuristics ──────────────────────────────────────────────────


def _clean_title(title: str) -> str | None:
    """Return a cleaned title if it differs from the original, else None.

    Cleaning steps:
    1. Strip leading/trailing whitespace.
    2. Collapse interior double (or more) spaces to a single space.
    3. Title-case if the ENTIRE title is uppercase (>=3 chars).
    """
    if not title:
        return None
    cleaned = title.strip()
    # Collapse multiple consecutive spaces
    cleaned = re.sub(r"  +", " ", cleaned)
    # Title-case all-uppercase titles (>=3 chars, ignoring punctuation)
    alpha_chars = re.sub(r"[^a-zA-ZÇĞİÖŞÜçğışöüıI]", "", cleaned)
    if len(alpha_chars) >= 3 and cleaned.upper() == cleaned:
        # Title-case using simple split — preserves separators
        cleaned = cleaned.title()
    if cleaned != title:
        return cleaned
    return None


# ── Heuristic suggest engine (stub path) ─────────────────────────────────────


def _get_field_value(product: dict, field: str) -> str:
    """Return the current value for a field from a product dict, normalised."""
    # Also check common alias keys so we pick up populated fields correctly
    _ALIASES: dict[str, list[str]] = {
        "color": ["color", "renk", "colour"],
        "brand": ["brand", "marka"],
        "category": ["category", "kategori", "google_product_category", "product_type"],
        "material": ["material", "materyal", "malzeme"],
        "title": ["title", "baslik", "başlık", "isim"],
    }
    candidates = _ALIASES.get(field, [field])
    for key in candidates:
        val = product.get(key, "")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _get_searchable_text(product: dict) -> str:
    """Concatenate title + description for keyword scanning."""
    title = str(product.get("title", "")).strip()
    desc = str(product.get("description", "")).strip()
    return f"{title} {desc}".strip()


def _stub_suggest(product: dict, product_id: str, fields: list[str]) -> list[dict]:
    """Return heuristic suggestions for one product."""
    suggestions: list[dict] = []
    text = _get_searchable_text(product)

    for field in fields:
        current = _get_field_value(product, field)

        # Title is special: we suggest a cleaned version even when a title exists.
        # All other fields: skip if the field already has a value.
        if field != "title" and current:
            continue

        suggested: str | None = None
        confidence: str = "high"

        if field == "color":
            suggested = _extract_color(text)

        elif field == "brand":
            title_val = str(product.get("title", "")).strip()
            suggested = _extract_brand(title_val)
            confidence = "low"  # brand guessing is inherently uncertain

        elif field == "category":
            suggested = _extract_category(text)

        elif field == "material":
            suggested = _extract_material(text)

        elif field == "title":
            raw_title = str(product.get("title", "")).strip()
            cleaned = _clean_title(raw_title)
            if cleaned:
                suggested = cleaned
                # Use the raw (uncleaned) title as the "current" value for UI diff
                current = raw_title

        if suggested:
            suggestions.append(
                {
                    "product_id": product_id,
                    "field": field,
                    "current": current,
                    "suggested": suggested,
                    "confidence": confidence,
                    "source": "heuristic",
                }
            )

    return suggestions


# ── Claude enrichment path ────────────────────────────────────────────────────

_ENRICHMENT_SYSTEM_PROMPT = (
    "Sen bir ürün feed zenginleştirme asistanısın. "
    "Ürün verilerindeki boş alanlar için öneriler üret. "
    "Yalnızca geçerli JSON döndür, başka hiçbir şey ekleme."
)

_ENRICHMENT_USER_TEMPLATE = """Aşağıdaki ürünler için boş olan alanları doldur.
Her öneri için: product_id, field (aşağıdaki alanlardan biri), current (mevcut değer, boşsa ""), suggested (önerilen değer), confidence ("high" veya "low"), source ("ai") belirt.

Zenginleştirilecek alanlar: {fields}

Ürünler (JSON):
{products_json}

Yalnızca boş/eksik alanlar için öneri üret. Cevabı JSON formatında döndür:
{{"suggestions": [
  {{"product_id": "...", "field": "...", "current": "", "suggested": "...", "confidence": "high", "source": "ai"}}
]}}
"""

_ENRICHMENT_SAMPLE_SIZE = 20  # Max products sent to LLM per call


def _claude_suggest(
    products: list[dict],
    product_ids: list[str],
    fields: list[str],
    *,
    api_key: str,
    model: str,
    http_client: Any,
) -> list[dict]:
    """Call Claude to suggest enrichment values. Falls back to stub on any error."""
    import httpx

    # Only send products with at least one empty field to reduce token usage
    eligible: list[tuple[str, dict]] = []
    for pid, prod in zip(product_ids, products):
        needs = [f for f in fields if not _get_field_value(prod, f)]
        if needs:
            eligible.append((pid, prod))

    if not eligible:
        return []

    # Cap to sample size
    sample = eligible[:_ENRICHMENT_SAMPLE_SIZE]

    products_json = json.dumps(
        [{"product_id": pid, **prod} for pid, prod in sample],
        ensure_ascii=False,
        indent=2,
    )
    user_msg = _ENRICHMENT_USER_TEMPLATE.format(
        fields=", ".join(fields),
        products_json=products_json,
    )

    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": _ENRICHMENT_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        if http_client is not None:
            resp = http_client.post(
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
            raise RuntimeError(f"Anthropic API {resp.status_code}: {resp.text[:200]}")

        raw_text = resp.json()["content"][0]["text"].strip()
        parsed = json.loads(raw_text)
        suggestions = parsed.get("suggestions", [])

        # Validate and sanitise each suggestion
        valid: list[dict] = []
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            field = str(s.get("field", ""))
            if field not in ENRICHABLE_FIELDS:
                continue
            pid = str(s.get("product_id", ""))
            suggested = str(s.get("suggested", "")).strip()
            if not pid or not suggested:
                continue
            confidence_raw = str(s.get("confidence", "low"))
            valid.append(
                {
                    "product_id": pid,
                    "field": field,
                    "current": str(s.get("current", "")),
                    "suggested": suggested,
                    "confidence": "high" if confidence_raw == "high" else "low",
                    "source": "ai",
                }
            )

        return valid

    except Exception as exc:
        logger.warning(
            "[feed_enrichment] Claude suggest failed (%s) — falling back to heuristics", exc
        )
        # Fallback: run heuristics on the full eligible set
        result: list[dict] = []
        for pid, prod in zip(product_ids, products):
            result.extend(_stub_suggest(prod, pid, fields))
        return result


# ── Public pure function ──────────────────────────────────────────────────────

# Sample cap: consistent with _IMPACT_SAMPLE_LIMIT in feeds.py
_ENRICH_SAMPLE_LIMIT = 200


def suggest_enrichment(
    products: list[dict],
    fields: list[str],
    *,
    product_ids: list[str] | None = None,
    http_client: Any = None,
) -> dict:
    """Return AI/heuristic enrichment suggestions for a list of product dicts.

    This is a PURE function — no DB access, no side effects.

    Parameters
    ----------
    products:
        List of product attribute dicts (from FeedProduct.data).
    fields:
        Which fields to suggest.  Must be a subset of ENRICHABLE_FIELDS.
        Unknown fields are silently ignored.
    product_ids:
        Optional list of product IDs (str) aligned with ``products``.  When
        omitted, positional indices are used as IDs.
    http_client:
        Optional httpx-compatible client.  Injected by tests; None → real.

    Returns
    -------
    {
        "suggestions": [
            {
                "product_id": str,
                "field": str,
                "current": str,       # "" when field was absent/empty
                "suggested": str,
                "confidence": "high" | "low",
                "source": "ai" | "heuristic",
            },
            ...
        ]
    }
    Only one suggestion per (product_id, field) combination.
    Only for products where the field is currently empty/missing.
    """
    valid_fields = [f for f in fields if f in ENRICHABLE_FIELDS]
    if not valid_fields or not products:
        return {"suggestions": []}

    if product_ids is None:
        product_ids = [str(i) for i in range(len(products))]

    from ayaz.config import settings

    api_key = settings.anthropic_api_key
    if api_key:
        suggestions = _claude_suggest(
            products,
            product_ids,
            valid_fields,
            api_key=api_key,
            model=settings.claude_narrator_model,
            http_client=http_client,
        )
    else:
        suggestions = []
        for pid, prod in zip(product_ids, products):
            suggestions.extend(_stub_suggest(prod, pid, valid_fields))

    # Deduplicate: keep first suggestion per (product_id, field)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for s in suggestions:
        key = (s["product_id"], s["field"])
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return {"suggestions": deduped}
