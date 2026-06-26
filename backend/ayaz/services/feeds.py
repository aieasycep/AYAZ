"""Feed Management service — M5 (Channable-style).

This module owns three public entry-points:

    ingest_feed_source(db, feed_source, *, raw_bytes=None)
        Parse an XML or CSV product feed and upsert FeedProduct rows.

    apply_rules(products, rules) -> list[dict]
        PURE function: apply a list of FeedRule objects to a list of product
        dicts in position order.  No DB access.

    generate_channel_feed(db, feed_channel) -> (content: str, content_type: str)
        Load products, apply channel rules, render to the channel's format.

Rule types
----------
set_value       — overwrite field with a constant string
rename_field    — copy src field value to dst field, optionally drop src
find_replace    — regex or substring replace within a field value
filter_include  — keep products that match a condition
filter_exclude  — drop products that match a condition
calculated      — evaluate a {template} or arithmetic expression to set a field

Channel output formats
----------------------
google_shopping — RSS 2.0 XML with g: namespace (Merchant Center spec)
meta_catalog    — CSV with Meta-required columns
tiktok_catalog  — CSV with TikTok catalog columns
custom          — generic XML or CSV depending on FeedChannel.output_format
"""

from __future__ import annotations

import csv
import io
import operator
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.feeds import FeedChannel, FeedProduct, FeedRule, FeedSource

if TYPE_CHECKING:
    pass

# ── Allowed values (validated here; no DB enum) ───────────────────────────────

VALID_SOURCE_TYPES = {"url_xml", "url_csv", "upload", "google_sheet"}
VALID_CHANNEL_TYPES = {
    "google_shopping", "meta_catalog", "tiktok_catalog", "custom"
}
VALID_OUTPUT_FORMATS = {"xml", "csv"}
VALID_RULE_TYPES = {
    "set_value",
    "rename_field",
    "find_replace",
    "filter_include",
    "filter_exclude",
    "calculated",
}
VALID_CONDITION_OPS = {"eq", "neq", "contains", "not_contains", "gt", "lt"}

# ── Feed ingestion ────────────────────────────────────────────────────────────


def _parse_xml_feed(raw_bytes: bytes) -> list[dict]:
    """Parse a generic product-feed XML into a list of attribute dicts.

    Supports two layouts:
    1. <items><item><field>value</field>…</item>…</items>  — any root/item tag
    2. RSS <channel><item>…</item>…</channel>

    The heuristic: find all direct children of the root (or first <channel>)
    that contain child elements (i.e. leaf text nodes are the attributes).
    """
    root = ET.fromstring(raw_bytes.decode("utf-8", errors="replace"))

    # For RSS feeds the data lives inside <channel>
    channel_el = root.find("channel")
    container = channel_el if channel_el is not None else root

    products: list[dict] = []
    for child in container:
        # Skip elements that have no sub-elements (they're scalars like <title>)
        sub_els = list(child)
        if not sub_els:
            continue
        product: dict = {}
        for field_el in sub_els:
            # Strip namespace prefix for storage: {ns}tag → tag
            tag = re.sub(r"\{[^}]*\}", "", field_el.tag)
            product[tag] = (field_el.text or "").strip()
        if product:
            products.append(product)

    return products


def _parse_csv_feed(raw_bytes: bytes) -> list[dict]:
    """Parse a CSV product feed (header row) into a list of attribute dicts."""
    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _detect_format(feed_source: FeedSource, raw_bytes: bytes) -> str:
    """Infer format from source_type or raw content sniff."""
    if feed_source.source_type in ("url_csv", "google_sheet"):
        return "csv"
    if feed_source.source_type == "url_xml":
        return "xml"
    # upload / unknown: sniff first non-whitespace byte
    stripped = raw_bytes.lstrip()
    return "xml" if stripped.startswith(b"<") else "csv"


def ingest_feed_source(
    db: Session,
    feed_source: FeedSource,
    *,
    raw_bytes: bytes | None = None,
) -> int:
    """Parse a product feed and upsert FeedProduct rows.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    feed_source:
        The FeedSource ORM object to ingest.  Must already be persisted.
    raw_bytes:
        Raw feed content.  When None the function fetches ``feed_source.source_url``
        via httpx (requires network).  Pass bytes in tests to stay hermetic.

    Returns
    -------
    Number of products upserted.
    """
    if raw_bytes is None:
        # Live network fetch — not exercised in unit tests
        try:
            import httpx  # type: ignore[import]

            resp = httpx.get(str(feed_source.source_url), follow_redirects=True, timeout=30)
            resp.raise_for_status()
            raw_bytes = resp.content
        except Exception as exc:
            feed_source.status = "error"
            db.add(feed_source)
            db.commit()
            raise RuntimeError(f"Feed fetch failed: {exc}") from exc

    fmt = _detect_format(feed_source, raw_bytes)
    if fmt == "xml":
        products = _parse_xml_feed(raw_bytes)
    else:
        products = _parse_csv_feed(raw_bytes)

    # Determine the external_id field — common candidates in priority order
    _ID_CANDIDATES = ("id", "g:id", "sku", "product_id", "item_id", "ID", "SKU")

    def _get_external_id(product: dict) -> str:
        for key in _ID_CANDIDATES:
            if key in product and product[key]:
                return str(product[key])
        # Fall back to a deterministic hash of the dict keys' sorted values
        return "-".join(str(v) for v in list(product.values())[:3])

    upserted = 0
    for prod_dict in products:
        ext_id = _get_external_id(prod_dict)
        existing = db.scalar(
            select(FeedProduct).where(
                FeedProduct.feed_source_id == feed_source.id,
                FeedProduct.external_id == ext_id,
                FeedProduct.tenant_id == feed_source.tenant_id,
            )
        )
        if existing is None:
            fp = FeedProduct(
                tenant_id=feed_source.tenant_id,
                feed_source_id=feed_source.id,
                external_id=ext_id,
                data=prod_dict,
            )
            db.add(fp)
        else:
            existing.data = prod_dict
        upserted += 1

    feed_source.item_count = upserted
    feed_source.last_synced_at = datetime.now(timezone.utc).isoformat()
    feed_source.status = "ok"
    db.add(feed_source)
    db.commit()

    return upserted


# ── Rule engine ───────────────────────────────────────────────────────────────


def _condition_matches(product: dict, config: dict) -> bool:
    """Evaluate a filter condition against one product dict.

    config keys: condition_field, condition_op, condition_value
    """
    field = config.get("condition_field", "")
    op_key = config.get("condition_op", "eq")
    target = str(config.get("condition_value", ""))
    actual = str(product.get(field, ""))

    _ops = {
        "eq": lambda a, b: a == b,
        "neq": lambda a, b: a != b,
        "contains": lambda a, b: b in a,
        "not_contains": lambda a, b: b not in a,
        "gt": lambda a, b: _safe_numeric_cmp(a, b, operator.gt),
        "lt": lambda a, b: _safe_numeric_cmp(a, b, operator.lt),
    }
    fn = _ops.get(op_key, _ops["eq"])
    return fn(actual, target)


def _safe_numeric_cmp(a: str, b: str, fn) -> bool:
    try:
        return fn(float(a), float(b))
    except (ValueError, TypeError):
        return False


def _apply_calculated(product: dict, config: dict) -> dict:
    """Evaluate a template or arithmetic expression and write to target field.

    If the expression contains arithmetic operators (+, -, *, /) and every
    referenced {field} resolves to a number, evaluate arithmetically.
    Otherwise treat as a Python str.format_map() template.
    """
    field = config.get("field", "")
    expression = str(config.get("expression", ""))

    # Build a dict of substitutions; missing fields become empty string / 0
    refs = re.findall(r"\{(\w+)\}", expression)
    substitutions: dict[str, str] = {r: str(product.get(r, "")) for r in refs}

    # Check arithmetic mode: expression has operators and all refs are numeric
    has_arith = bool(re.search(r"[+\-*/]", re.sub(r"\{[^}]*\}", "", expression)))
    all_numeric = has_arith and all(
        re.fullmatch(r"-?\d+(\.\d+)?", v) for v in substitutions.values() if v
    )

    if all_numeric:
        # Replace {field} with numeric value and evaluate safely
        numeric_subs: dict[str, float] = {k: float(v) for k, v in substitutions.items() if v}
        try:
            safe_expr = expression
            for k, v in numeric_subs.items():
                safe_expr = safe_expr.replace(f"{{{k}}}", str(v))
            # Only allow digits, operators, parens, spaces, and dots
            if re.fullmatch(r"[\d\s\+\-\*/\.\(\)]+", safe_expr):
                result = str(eval(safe_expr))  # noqa: S307 — safe after validation
            else:
                result = expression.format_map({k: str(v) for k, v in numeric_subs.items()})
        except Exception:
            result = expression.format_map(substitutions)
    else:
        try:
            result = expression.format_map(substitutions)
        except (KeyError, ValueError):
            result = expression

    product = dict(product)
    product[field] = result
    return product


def apply_rules(products: list[dict], rules: list[FeedRule]) -> list[dict]:
    """Apply a list of FeedRule objects to a list of product dicts.

    This is a PURE function — no DB access, no side effects.

    Rules are applied in the order they appear in ``rules`` (caller is
    responsible for sorting by ``position`` beforehand, which the ORM
    relationship already does via ``order_by="FeedRule.position"``).

    Rule types
    ----------
    set_value
        Force every product's ``config["field"]`` to ``config["value"]``.

    rename_field
        Copy ``from_field`` value to ``to_field``.  If ``drop_original`` is
        true (default false), remove ``from_field`` after copying.

    find_replace
        In ``config["field"]`` replace ``config["pattern"]`` with
        ``config["replacement"]``.  If ``config["use_regex"]`` is true, treat
        pattern as a Python regex; otherwise plain substring replace.

    filter_include
        Drop products that do NOT match the condition.
        condition keys: condition_field, condition_op, condition_value.
        condition_op: "eq" | "neq" | "contains" | "not_contains" | "gt" | "lt"

    filter_exclude
        Drop products that DO match the condition (inverse of filter_include).

    calculated
        Evaluate ``config["expression"]`` — a {field_name} template string or
        arithmetic expression — and store the result in ``config["field"]``.
    """
    result = list(products)

    for rule in rules:
        cfg = rule.config or {}
        rtype = rule.rule_type

        if rtype == "set_value":
            field = cfg.get("field", "")
            value = str(cfg.get("value", ""))
            result = [{**p, field: value} for p in result]

        elif rtype == "rename_field":
            src = cfg.get("from_field", "")
            dst = cfg.get("to_field", "")
            drop = cfg.get("drop_original", False)
            new_result = []
            for p in result:
                p2 = dict(p)
                p2[dst] = p2.get(src, "")
                if drop:
                    p2.pop(src, None)
                new_result.append(p2)
            result = new_result

        elif rtype == "find_replace":
            field = cfg.get("field", "")
            pattern = str(cfg.get("pattern", ""))
            replacement = str(cfg.get("replacement", ""))
            use_regex = cfg.get("use_regex", False)
            new_result = []
            for p in result:
                p2 = dict(p)
                val = str(p2.get(field, ""))
                if use_regex:
                    try:
                        val = re.sub(pattern, replacement, val)
                    except re.error:
                        pass  # invalid regex — leave value unchanged
                else:
                    val = val.replace(pattern, replacement)
                p2[field] = val
                new_result.append(p2)
            result = new_result

        elif rtype == "filter_include":
            result = [p for p in result if _condition_matches(p, cfg)]

        elif rtype == "filter_exclude":
            result = [p for p in result if not _condition_matches(p, cfg)]

        elif rtype == "calculated":
            result = [_apply_calculated(p, cfg) for p in result]

        # Unknown rule types are silently skipped (forward-compat)

    return result


# ── Feed rendering ────────────────────────────────────────────────────────────

# Normalised field names that the ingestion layer tries to standardise to,
# and the channel-required names for each output format.

# Common source field → normalised key mapping (best-effort)
_FIELD_ALIASES: dict[str, str] = {
    "g:id": "id",
    "g:title": "title",
    "g:description": "description",
    "g:link": "link",
    "g:image_link": "image_link",
    "g:price": "price",
    "g:availability": "availability",
    "g:brand": "brand",
    "g:condition": "condition",
    "g:gtin": "gtin",
    "g:mpn": "mpn",
    "g:google_product_category": "google_product_category",
    "g:product_type": "product_type",
    "product_id": "id",
    "sku": "id",
    "item_id": "id",
    "image": "image_link",
    "url": "link",
    "product_url": "link",
}


def _normalise(product: dict) -> dict:
    """Return a copy of product with aliased keys resolved to canonical names."""
    out: dict = {}
    for k, v in product.items():
        canonical = _FIELD_ALIASES.get(k, k)
        out[canonical] = v
    return out


def _safe(value: object) -> str:
    return str(value) if value is not None else ""


# ── Google Shopping (RSS 2.0 + g: namespace) ──────────────────────────────────

_GOOGLE_NS = "http://base.google.com/ns/1.0"


def _render_google_shopping_xml(products: list[dict]) -> str:
    """Render products as Google Merchant Center RSS 2.0 XML (g: namespace).

    Required g: fields: id, title, description, link, image_link, price,
    availability, brand.  Missing fields are included as empty strings so the
    feed is valid XML even if incomplete (Merchant Center flags them separately).
    """
    ET.register_namespace("g", _GOOGLE_NS)

    # Do NOT manually add xmlns:g — ET injects it automatically when it
    # encounters the first {_GOOGLE_NS}tag element.  Adding it manually causes
    # a "duplicate attribute" parse error.
    rss = ET.Element("rss", {"version": "2.0"})
    channel_el = ET.SubElement(rss, "channel")
    ET.SubElement(channel_el, "title").text = "AYAZ Product Feed"
    ET.SubElement(channel_el, "link").text = ""
    ET.SubElement(channel_el, "description").text = "Generated by AYAZ Feed Management"

    for prod in products:
        p = _normalise(prod)
        item = ET.SubElement(channel_el, "item")

        def _g(tag: str, field: str, fallback: str = "") -> None:
            el = ET.SubElement(item, f"{{{_GOOGLE_NS}}}{tag}")
            el.text = _safe(p.get(field, fallback))

        ET.SubElement(item, "title").text = _safe(p.get("title", ""))
        ET.SubElement(item, "link").text = _safe(p.get("link", ""))
        ET.SubElement(item, "description").text = _safe(p.get("description", ""))
        _g("id", "id")
        _g("title", "title")
        _g("description", "description")
        _g("link", "link")
        _g("image_link", "image_link")
        _g("price", "price")
        _g("availability", "availability", "in stock")
        _g("brand", "brand")
        _g("condition", "condition", "new")
        if p.get("gtin"):
            _g("gtin", "gtin")
        if p.get("mpn"):
            _g("mpn", "mpn")
        if p.get("google_product_category"):
            _g("google_product_category", "google_product_category")

    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


# ── Meta Catalog CSV ──────────────────────────────────────────────────────────

_META_FIELDS = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "brand",
]


def _render_meta_catalog_csv(products: list[dict]) -> str:
    """Render products as Meta Product Catalog CSV.

    Required columns: id, title, description, availability, condition,
    price, link, image_link, brand.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=_META_FIELDS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for prod in products:
        p = _normalise(prod)
        writer.writerow({f: _safe(p.get(f, "")) for f in _META_FIELDS})
    return buf.getvalue()


# ── TikTok Catalog CSV ────────────────────────────────────────────────────────

_TIKTOK_FIELDS = [
    "sku_id", "title", "description", "price", "availability",
    "image_link", "link", "brand", "condition",
]


def _render_tiktok_catalog_csv(products: list[dict]) -> str:
    """Render products as TikTok Shop catalog CSV.

    TikTok uses ``sku_id`` instead of ``id`` as the primary key column.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=_TIKTOK_FIELDS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for prod in products:
        p = _normalise(prod)
        row = {f: _safe(p.get(f, "")) for f in _TIKTOK_FIELDS}
        row["sku_id"] = _safe(p.get("id", ""))  # map id → sku_id
        writer.writerow(row)
    return buf.getvalue()


# ── Custom format ─────────────────────────────────────────────────────────────


def _render_custom_xml(products: list[dict]) -> str:
    """Generic XML: <feed><product><field>value</field>…</product>…</feed>."""
    root = ET.Element("feed")
    for prod in products:
        p_el = ET.SubElement(root, "product")
        for key, val in prod.items():
            # XML tag must be valid; strip invalid characters
            safe_tag = re.sub(r"[^a-zA-Z0-9_\-.]", "_", str(key)) or "field"
            if safe_tag[0].isdigit():
                safe_tag = f"f_{safe_tag}"
            ET.SubElement(p_el, safe_tag).text = _safe(val)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _render_custom_csv(products: list[dict]) -> str:
    """Generic CSV: dynamic header derived from all product keys."""
    if not products:
        return ""
    all_keys: list[str] = []
    seen: set[str] = set()
    for prod in products:
        for k in prod:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=all_keys,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for prod in products:
        writer.writerow({k: _safe(prod.get(k, "")) for k in all_keys})
    return buf.getvalue()


# ── Public entry-point ────────────────────────────────────────────────────────


def generate_channel_feed(
    db: Session,
    feed_channel: FeedChannel,
) -> tuple[str, str]:
    """Load products, apply rules, and render to the channel's output format.

    Returns
    -------
    (content, content_type)
        content      — rendered string (XML or CSV text)
        content_type — MIME type ("application/xml" or "text/csv; charset=utf-8")
    """
    # Load all products for this source, scoped to the same tenant
    product_rows = list(
        db.scalars(
            select(FeedProduct).where(
                FeedProduct.feed_source_id == feed_channel.feed_source_id,
                FeedProduct.tenant_id == feed_channel.tenant_id,
            )
        )
    )
    products: list[dict] = [row.data for row in product_rows]

    # Load rules ordered by position (ORM relationship already orders them)
    rules = list(
        db.scalars(
            select(FeedRule)
            .where(FeedRule.feed_channel_id == feed_channel.id)
            .order_by(FeedRule.position)
        )
    )

    transformed = apply_rules(products, rules)

    ctype = feed_channel.channel_type
    fmt = feed_channel.output_format or "xml"

    if ctype == "google_shopping":
        content = _render_google_shopping_xml(transformed)
        content_type = "application/xml"
    elif ctype == "meta_catalog":
        content = _render_meta_catalog_csv(transformed)
        content_type = "text/csv; charset=utf-8"
    elif ctype == "tiktok_catalog":
        content = _render_tiktok_catalog_csv(transformed)
        content_type = "text/csv; charset=utf-8"
    else:
        # custom
        if fmt == "csv":
            content = _render_custom_csv(transformed)
            content_type = "text/csv; charset=utf-8"
        else:
            content = _render_custom_xml(transformed)
            content_type = "application/xml"

    return content, content_type
