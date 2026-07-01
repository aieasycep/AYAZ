"""Natural-language → FeedRule generator — Dalga 45.

Two operating modes (same Claude-with-mock-fallback pattern as report_builder.py):

Claude path (when settings.anthropic_api_key is set)
    Calls the Anthropic Messages API via httpx.  Falls back to the stub on any
    error, so the endpoint never 500s on LLM failures.

Stub path (default — no API key required)
    Deterministic Turkish keyword extractor.  Covers the common rule patterns
    used in digital-marketing feed management.  This is the path exercised by
    the test suite.

Public API
----------
    parse_rule_from_text(text, http_client=None) -> ParsedRule
        Always returns a ParsedRule (never raises); confidence is "low" when
        no pattern matched.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Valid types (replicated to avoid circular import with the router) ──────────

VALID_RULE_TYPES = {
    "set_value",
    "rename_field",
    "find_replace",
    "filter_include",
    "filter_exclude",
    "calculated",
}

# ── Turkish field synonym map → canonical feed field name ──────────────────────

_FIELD_SYNONYMS: dict[str, str] = {
    # price
    "fiyat": "price",
    "fiyatı": "price",
    "fiyatla": "price",
    "ücret": "price",
    # title
    "başlık": "title",
    "başlığa": "title",
    "başlığı": "title",
    "başlıkta": "title",
    "başlık sonuna": "title",
    "isim": "title",
    # brand
    "marka": "brand",
    "markayı": "brand",
    "markası": "brand",
    # availability / stock
    "stok": "availability",
    "stokta": "availability",
    "stok durumu": "availability",
    "stok_durumu": "availability",
    "müsaitlik": "availability",
    "uygunluk": "availability",
    # category
    "kategori": "google_product_category",
    "kategorisi": "google_product_category",
    # description
    "açıklama": "description",
    "açıklaması": "description",
    # link
    "link": "link",
    "url": "link",
    "bağlantı": "link",
    # condition
    "durum": "condition",
    "koşul": "condition",
    # image
    "resim": "image_link",
    "görsel": "image_link",
    "fotoğraf": "image_link",
    # gtin
    "gtin": "gtin",
    "barkod": "gtin",
    # mpn
    "mpn": "mpn",
    # id
    "kimlik": "id",
    "ürün kodu": "id",
}


def _normalise(text: str) -> str:
    """Turkish-safe lowercase — replaces İ→i and I→i before lowercasing."""
    return text.replace("İ", "i").replace("I", "i").lower().strip()


def _resolve_field(token: str) -> str | None:
    """Return canonical field name for a Turkish field synonym, or None."""
    norm = _normalise(token)
    # Direct lookup first
    if norm in _FIELD_SYNONYMS:
        return _FIELD_SYNONYMS[norm]
    # Partial match — find the longest synonym contained in norm
    best: str | None = None
    best_len = 0
    for synonym, canonical in _FIELD_SYNONYMS.items():
        if synonym in norm and len(synonym) > best_len:
            best = canonical
            best_len = len(synonym)
    return best


def _extract_number(text: str) -> str | None:
    """Extract the first number (int or decimal) from text."""
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if m:
        return m.group(0).replace(",", ".")
    return None


def _extract_quoted_strings(text: str) -> list[str]:
    """Return all quoted substrings (single or double quotes)."""
    return re.findall(r"""['"]([^'"]+)['"]""", text)


# ── ParsedRule dataclass ───────────────────────────────────────────────────────


@dataclass
class ParsedRule:
    """Result of parsing a Turkish natural-language rule description.

    Attributes
    ----------
    rule_type:
        One of VALID_RULE_TYPES.
    config:
        Rule-specific config dict matching the FeedRule schema.
    explanation:
        Short Turkish sentence describing what the rule does.
    confidence:
        "high" when the parser matched a concrete pattern; "low" when the best
        guess is uncertain.
    """

    rule_type: str
    config: dict
    explanation: str
    confidence: str  # "high" | "low"


# ── Deterministic stub parser ─────────────────────────────────────────────────

# Stock-out keywords — trigger filter_exclude on availability
_STOCK_OUT_KEYWORDS = [
    "stokta olmayan",
    "stokta yok",
    "tükenmiş",
    "tükenen",
    "stoğu olmayan",
    "stoğu biten",
    "stok dışı",
    "stokta bulunmayan",
    "temin edilemeyen",
]

# In-stock include keywords — trigger filter_include on availability
_IN_STOCK_KEYWORDS = [
    "sadece stokta olan",
    "stokta olan",
    "stokta olanları",
    "stokta mevcut",
    "mevcut olan",
    "stokta bulunan",
    "stoğu olan",
]

# Exclude verbs (filter_exclude trigger words)
_EXCLUDE_VERBS = [
    "çıkar",
    "hariç tut",
    "çıkart",
    "dışla",
    "filtrele",
    "kaldır",
    "sil",
    "çıkarsın",
    "dışında bırak",
    "gösterme",
]

# Include verbs (filter_include trigger words)
_INCLUDE_VERBS = [
    "dahil et",
    "göster",
    "içer",
    "ekle",
    "listele",
    "tut",
    "sadece göster",
    "yalnızca göster",
]

# Price-below keywords → lt
_PRICE_BELOW_KEYWORDS = [
    "altındaki",
    "altında olan",
    "altında",
    "aşağısındaki",
    "azındaki",
    "küçük",
    "düşük",
    "aşağısında",
]

# Price-above keywords → gt
_PRICE_ABOVE_KEYWORDS = [
    "üstündeki",
    "üzerindeki",
    "üstünde",
    "üzerinde",
    "yukarısındaki",
    "fazlasındaki",
    "büyük",
    "yüksek",
    "yukarısında",
]

# Add-to-title keywords
_TITLE_APPEND_KEYWORDS = [
    "başlığa",
    "başlık sonuna",
    "başlığın sonuna",
    "başlığa ekle",
    "başlık ekle",
]

# Rename / copy field keywords
_RENAME_KEYWORDS = [
    "olarak yeniden adlandır",
    "olarak adlandır",
    "olarak kopyala",
    "alanını kopyala",
    "alanını taşı",
    "yeniden adlandır",
    "adlandır",
    "kopyala",
    "taşı",
]

# Set-value keywords
_SET_VALUE_KEYWORDS = [
    "yap",
    "ayarla",
    "olarak ayarla",
    "olarak yap",
    "değerini yap",
    "değişkeni yap",
    "olarak belirle",
    "belirle",
]

# Find-replace keywords
_FIND_REPLACE_KEYWORDS = [
    "yerine",
    "yaz",
    "değiştir",
    "içindeki",
    "replace",
]


def _try_parse_stock_exclude(norm: str) -> ParsedRule | None:
    """stokta olmayan ürünleri çıkar → filter_exclude on availability."""
    has_stock_out = any(kw in norm for kw in _STOCK_OUT_KEYWORDS)
    if not has_stock_out:
        return None
    # Check that there is an exclude intent (or the text just says "çıkar" / similar)
    has_exclude = any(kw in norm for kw in _EXCLUDE_VERBS) or True  # default exclude
    if has_exclude:
        return ParsedRule(
            rule_type="filter_exclude",
            config={
                "condition_field": "availability",
                "condition_op": "eq",
                "condition_value": "out of stock",
            },
            explanation="Stokta olmayan (availability = 'out of stock') ürünler feedden çıkarılır.",
            confidence="high",
        )
    return None


def _try_parse_stock_include(norm: str) -> ParsedRule | None:
    """sadece stokta olanları göster → filter_include on availability."""
    has_in_stock = any(kw in norm for kw in _IN_STOCK_KEYWORDS)
    if not has_in_stock:
        return None
    has_include = any(kw in norm for kw in _INCLUDE_VERBS) or True
    if has_include:
        return ParsedRule(
            rule_type="filter_include",
            config={
                "condition_field": "availability",
                "condition_op": "eq",
                "condition_value": "in stock",
            },
            explanation="Yalnızca stokta olan (availability = 'in stock') ürünler gösterilir.",
            confidence="high",
        )
    return None


def _try_parse_price_filter(norm: str, original: str) -> ParsedRule | None:
    """fiyatı N TL altındaki/üstündeki ürünleri çıkar/dahil et."""
    # Need a number in the text
    number = _extract_number(norm)
    if number is None:
        return None

    # Check for price-related context
    has_price_context = _resolve_field(norm) == "price" or any(
        kw in norm for kw in ["fiyat", "tl", "lira", "para", "ücret"]
    )
    if not has_price_context:
        # No price context — not a price filter
        return None

    # Determine comparison direction
    is_below = any(kw in norm for kw in _PRICE_BELOW_KEYWORDS)
    is_above = any(kw in norm for kw in _PRICE_ABOVE_KEYWORDS)
    if not is_below and not is_above:
        return None

    op = "lt" if is_below else "gt"
    direction_tr = "altındaki" if is_below else "üstündeki"

    # Determine include or exclude
    has_exclude = any(kw in norm for kw in _EXCLUDE_VERBS)
    has_include = any(kw in norm for kw in _INCLUDE_VERBS)

    if has_include and not has_exclude:
        rule_type = "filter_include"
        explanation = (
            f"Fiyatı {number} {direction_tr} ürünler dahil edilir "
            f"(price {op} {number})."
        )
    else:
        # Default to exclude when verb is ambiguous
        rule_type = "filter_exclude"
        explanation = (
            f"Fiyatı {number} {direction_tr} ürünler feedden çıkarılır "
            f"(price {op} {number})."
        )

    return ParsedRule(
        rule_type=rule_type,
        config={
            "condition_field": "price",
            "condition_op": op,
            "condition_value": number,
        },
        explanation=explanation,
        confidence="high",
    )


def _try_parse_title_append(norm: str, original: str) -> ParsedRule | None:
    """başlığa '{X}' ekle / başlığa marka ekle → calculated field."""
    is_title_append = any(kw in norm for kw in _TITLE_APPEND_KEYWORDS)
    # Also match "başlık" + "ekle"
    if not is_title_append and not ("başlık" in norm and "ekle" in norm):
        return None

    quoted = _extract_quoted_strings(original)
    if quoted:
        # Literal append: başlığa ' | Outlet' ekle
        literal = quoted[0]
        expression = f"{{title}} {literal}"
        explanation = f"Başlığa '{literal}' eklenir (calculated: {{title}} {literal})."
    else:
        # Try to find a field synonym to append
        # Common: "başlığa marka ekle", "başlığa kategori ekle"
        appended_field: str | None = None
        for synonym, canonical in _FIELD_SYNONYMS.items():
            if synonym in norm and canonical not in ("title",):
                appended_field = canonical
                break
        if appended_field:
            expression = f"{{title}} | {{{appended_field}}}"
            explanation = (
                f"Başlığa '{appended_field}' alanı eklenir "
                f"(calculated: {{title}} | {{{appended_field}}})."
            )
        else:
            # Can't determine what to append — low confidence
            expression = "{title}"
            return ParsedRule(
                rule_type="calculated",
                config={"field": "title", "expression": expression},
                explanation="Başlık alanı üzerinde hesaplamalı kural oluşturuldu (ne ekleneceği belirtilmedi).",
                confidence="low",
            )

    return ParsedRule(
        rule_type="calculated",
        config={"field": "title", "expression": expression},
        explanation=explanation,
        confidence="high",
    )


def _try_parse_set_value(norm: str, original: str) -> ParsedRule | None:
    """{alan} alanını '{X}' yap/ayarla → set_value."""
    has_set_verb = any(kw in norm for kw in _SET_VALUE_KEYWORDS)
    if not has_set_verb:
        return None

    quoted = _extract_quoted_strings(original)
    if not quoted:
        return None

    value = quoted[-1]  # last quoted string is typically the value

    # Try to find the target field
    target_field: str | None = None
    # Remove the value string from norm before searching for field
    norm_without_value = norm
    for q in quoted:
        norm_without_value = norm_without_value.replace(q.lower(), "")

    target_field = _resolve_field(norm_without_value)
    if target_field is None:
        # Try searching the whole text
        target_field = _resolve_field(norm)

    if target_field is None:
        return None

    return ParsedRule(
        rule_type="set_value",
        config={"field": target_field, "value": value},
        explanation=f"'{target_field}' alanı '{value}' olarak sabitlenir.",
        confidence="high",
    )


def _try_parse_find_replace(norm: str, original: str) -> ParsedRule | None:
    """{alan} içindeki '{a}' yerine '{b}' yaz → find_replace."""
    # Require "yerine" + "yaz"/"değiştir" OR "içindeki" + "yerine"
    has_find_replace = ("yerine" in norm and ("yaz" in norm or "değiştir" in norm)) or (
        "içindeki" in norm and "yerine" in norm
    )
    if not has_find_replace:
        return None

    quoted = _extract_quoted_strings(original)
    if len(quoted) < 2:
        return None

    # First quoted string is the pattern, last is the replacement
    pattern = quoted[0]
    replacement = quoted[-1]

    # Find field
    norm_without_quoted = norm
    for q in quoted:
        norm_without_quoted = norm_without_quoted.replace(q.lower(), "")

    target_field = _resolve_field(norm_without_quoted)
    if target_field is None:
        target_field = _resolve_field(norm)
    if target_field is None:
        return None

    return ParsedRule(
        rule_type="find_replace",
        config={
            "field": target_field,
            "pattern": pattern,
            "replacement": replacement,
            "use_regex": False,
        },
        explanation=(
            f"'{target_field}' alanındaki '{pattern}' ifadesi '{replacement}' ile değiştirilir."
        ),
        confidence="high",
    )


def _try_parse_rename_field(norm: str, original: str) -> ParsedRule | None:
    """{A} alanını {B} olarak yeniden adlandır/kopyala → rename_field."""
    has_rename = any(kw in norm for kw in _RENAME_KEYWORDS)
    if not has_rename:
        return None

    # Try to extract two field names from quoted strings or synonyms
    quoted = _extract_quoted_strings(original)

    # "product_type alanını google_product_category olarak kopyala"
    # Pattern: {from} alanını {to} olarak ...
    m = re.search(
        r"([a-z_À-ɏ]+)\s+alan[ıi]n[ıi]\s+([a-z_À-ɏ]+)\s+olarak",
        norm,
    )

    from_field: str | None = None
    to_field: str | None = None

    if m:
        from_raw, to_raw = m.group(1), m.group(2)
        from_field = _resolve_field(from_raw) or from_raw
        to_field = _resolve_field(to_raw) or to_raw
    elif len(quoted) >= 2:
        from_field = _resolve_field(quoted[0]) or quoted[0]
        to_field = _resolve_field(quoted[1]) or quoted[1]
    else:
        # Can't identify two fields — low confidence
        return None

    drop_original = "taşı" in norm or "kaldır" in norm or "sil" in norm

    return ParsedRule(
        rule_type="rename_field",
        config={
            "from_field": from_field,
            "to_field": to_field,
            "drop_original": drop_original,
        },
        explanation=(
            f"'{from_field}' alanı '{to_field}' olarak {'taşınır' if drop_original else 'kopyalanır'}."
        ),
        confidence="high",
    )


def _try_parse_calculated_expression(norm: str, original: str) -> ParsedRule | None:
    """Generic calculated field: {field} = {expression}."""
    # Look for "hesapla", "ifade", "formül", "expression"
    has_calc = any(kw in norm for kw in ["hesapla", "ifade", "formül", "expression", "hesap"])
    if not has_calc:
        return None

    quoted = _extract_quoted_strings(original)
    if not quoted:
        return None

    target_field = _resolve_field(norm)
    if target_field is None:
        return None

    expression = quoted[0]
    return ParsedRule(
        rule_type="calculated",
        config={"field": target_field, "expression": expression},
        explanation=f"'{target_field}' alanı '{expression}' ifadesiyle hesaplanır.",
        confidence="high",
    )


def _fallback_rule() -> ParsedRule:
    """Return a low-confidence best-guess when nothing else matched."""
    return ParsedRule(
        rule_type="filter_exclude",
        config={
            "condition_field": "availability",
            "condition_op": "eq",
            "condition_value": "out of stock",
        },
        explanation=(
            "Kural metni anlaşılamadı. En yakın tahmin: stokta olmayan ürünleri çıkar. "
            "Lütfen metni daha açık yazın."
        ),
        confidence="low",
    )


def _stub_parse(text: str) -> ParsedRule:
    """Deterministic Turkish parser — no network, no API key.

    Tries each pattern in priority order; returns the first match.
    If nothing matches, returns a low-confidence fallback.
    """
    norm = _normalise(text)

    # 1. Stock-out exclude (highest specificity)
    result = _try_parse_stock_exclude(norm)
    if result is not None:
        return result

    # 2. In-stock include
    result = _try_parse_stock_include(norm)
    if result is not None:
        return result

    # 3. Price filter (needs a number)
    result = _try_parse_price_filter(norm, text)
    if result is not None:
        return result

    # 4. Find & replace (check before set_value — more specific)
    result = _try_parse_find_replace(norm, text)
    if result is not None:
        return result

    # 5. Rename / rename_field
    result = _try_parse_rename_field(norm, text)
    if result is not None:
        return result

    # 6. Title append (calculated)
    result = _try_parse_title_append(norm, text)
    if result is not None:
        return result

    # 7. Set value
    result = _try_parse_set_value(norm, text)
    if result is not None:
        return result

    # 8. Generic calculated expression
    result = _try_parse_calculated_expression(norm, text)
    if result is not None:
        return result

    return _fallback_rule()


# ── Claude parser ─────────────────────────────────────────────────────────────

_CLAUDE_SYSTEM_PROMPT = (
    "Sen bir ürün feed yönetim asistanısın. "
    "Kullanıcının Türkçe doğal dil metnini bir FeedRule JSON nesnesine dönüştür. "
    "Yalnızca geçerli JSON döndür, başka hiçbir şey ekleme."
)

_CLAUDE_USER_TEMPLATE = """Kullanıcı metni: {text}

Aşağıdaki JSON formatında bir FeedRule taslağı döndür:
{{
  "rule_type": "filter_exclude",
  "config": {{}},
  "explanation": "Kısa Türkçe açıklama.",
  "confidence": "high"
}}

Geçerli rule_type değerleri: set_value, rename_field, find_replace, filter_include, filter_exclude, calculated.

Config şemaları:
- set_value: {{"field": "...", "value": "..."}}
- rename_field: {{"from_field": "...", "to_field": "...", "drop_original": false}}
- find_replace: {{"field": "...", "pattern": "...", "replacement": "...", "use_regex": false}}
- filter_include / filter_exclude: {{"condition_field": "...", "condition_op": "eq|neq|contains|not_contains|gt|lt", "condition_value": "..."}}
- calculated: {{"field": "...", "expression": "{{field_name}} template or arithmetic"}}

Türkçe alan adı eşleştirmeleri: fiyat→price, başlık→title, marka→brand, stok/stok durumu→availability, kategori→google_product_category, açıklama→description.

confidence: "high" eğer net bir kural çıkarılabiliyorsa, "low" eğer metin belirsizse.
"""


def _claude_parse(text: str, *, api_key: str, model: str, http_client: Any) -> ParsedRule:
    """Call Claude to parse the rule text. Falls back to stub on any error."""
    import httpx

    user_msg = _CLAUDE_USER_TEMPLATE.format(text=text)
    payload = {
        "model": model,
        "max_tokens": 512,
        "system": _CLAUDE_SYSTEM_PROMPT,
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
            raise RuntimeError(f"Anthropic API {resp.status_code}: {resp.text[:200]}")

        raw_text = resp.json()["content"][0]["text"].strip()
        parsed = json.loads(raw_text)

        rule_type = str(parsed.get("rule_type", ""))
        if rule_type not in VALID_RULE_TYPES:
            raise ValueError(f"Invalid rule_type from Claude: {rule_type!r}")

        config = parsed.get("config", {})
        if not isinstance(config, dict):
            config = {}

        confidence_raw = str(parsed.get("confidence", "high"))
        confidence = "high" if confidence_raw == "high" else "low"

        return ParsedRule(
            rule_type=rule_type,
            config=config,
            explanation=str(parsed.get("explanation", "")),
            confidence=confidence,
        )

    except Exception as exc:
        logger.warning(
            "[feed_rule_nlp] Claude parse failed (%s) — falling back to stub", exc
        )
        return _stub_parse(text)


# ── Public API ────────────────────────────────────────────────────────────────


def parse_rule_from_text(
    text: str,
    *,
    http_client: Any = None,
) -> ParsedRule:
    """Parse a natural-language Turkish rule description into a ParsedRule.

    Parameters
    ----------
    text:
        Free-form Turkish (or English) description of the desired rule.
    http_client:
        Optional httpx-compatible client for the Claude API.  Inject a mock
        in tests to avoid live network calls.  None → create on demand.

    Returns
    -------
    ParsedRule — never raises.  confidence="low" when parsing is uncertain.
    """
    from ayaz.config import settings

    api_key = settings.anthropic_api_key
    if api_key:
        return _claude_parse(
            text,
            api_key=api_key,
            model=settings.claude_narrator_model,
            http_client=http_client,
        )

    return _stub_parse(text)
