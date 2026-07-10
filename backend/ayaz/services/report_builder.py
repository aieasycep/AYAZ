"""Natural-Language Report Builder — parse Turkish prompts into structured specs
and execute them against the unified data layer.

Two operating modes
-------------------
Claude path (when settings.anthropic_api_key is set)
    Calls the Anthropic Messages API via httpx (same pattern as ClaudeNarrator).
    Asks the model to return a JSON spec; falls back to the stub on any error.

Stub path (default, no API key required)
    Deterministic Turkish keyword extraction.  Handles channels, metrics, date
    ranges, comparison intent, and visualisation type.  Safe for tests and
    offline environments.

Reuse
-----
``build_report`` delegates entirely to
``ayaz.services.copilot_tools._get_performance_summary`` and
``ayaz.services.copilot_tools._get_timeseries`` — the same aggregation
functions the dashboard and AI copilot use.  No SQL is duplicated here.

Metric definitions
------------------
All metric names in ``ReportSpec.metrics`` match the canonical keys used
throughout the platform:
    spend, impressions, clicks, conversions, conversion_value,
    ctr, cpc, cpa, roas

Decimal-to-float boundary
--------------------------
The dashboard aggregation functions already return floats (they convert at
their own serialisation boundary).  This module never touches Decimal.
"""

from __future__ import annotations

import json
import logging
import re

from ayaz.services.channels import channel_label
from ayaz.services.trdate import tr_date
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── ReportSpec dataclass ───────────────────────────────────────────────────────

_DEFAULT_METRICS = ["spend", "roas", "conversions"]

# Canonical channel keys recognised by the platform
_CHANNEL_KEYWORDS: dict[str, str] = {
    "google": "google_ads",
    "google ads": "google_ads",
    "meta": "meta_ads",
    "facebook": "meta_ads",
    "instagram": "meta_ads",  # shares the meta_ads connector
    "tiktok": "tiktok_ads",
    "linkedin": "linkedin_ads",
    "microsoft": "microsoft_ads",
    "bing": "microsoft_ads",
    "criteo": "criteo",
    "pinterest": "pinterest_ads",
}

# Turkish/English metric keyword → canonical metric key
_METRIC_KEYWORDS: dict[str, str] = {
    "harcama": "spend",
    "spend": "spend",
    "roas": "roas",
    "tıklama": "clicks",
    "clicks": "clicks",
    "gösterim": "impressions",
    "impressions": "impressions",
    "dönüşüm": "conversions",
    "conversions": "conversions",
    "ctr": "ctr",
    "tıklama oranı": "ctr",
    "cpc": "cpc",
    "tıklama başı": "cpc",
    "cpa": "cpa",
    "dönüşüm başı": "cpa",
}

# viz keywords
_VIZ_TIMESERIES = ["trend", "zaman", "günlük", "daily", "timeseries"]
_VIZ_TABLE = ["tablo", "table", "liste", "list"]

# comparison keywords
_COMPARISON_KEYWORDS = ["vs", "karşılaştır", "kıyas", "compare", "versus"]

# date-range patterns  (tuple: from_offset_days, to_offset_days relative to today)
# Positive = subtract from today; negative = add to today (i.e. for month-end).
_DATE_RANGE_PATTERNS: list[tuple[re.Pattern, int, int | None]] = []


def _normalise(text: str) -> str:
    """Turkish-safe lowercase.  Replaces İ→i and I→i before lowercasing."""
    return text.replace("İ", "i").replace("I", "i").lower()


def _keyword_match(text: str, *keywords: str) -> bool:
    norm = _normalise(text)
    return any(kw in norm for kw in keywords)


def _extract_channels(text: str) -> list[str]:
    """Return a deduplicated list of channel keys mentioned in the text."""
    norm = _normalise(text)
    found: list[str] = []
    seen: set[str] = set()
    # Match longest keyword first to avoid 'google' matching inside 'google ads'
    for kw in sorted(_CHANNEL_KEYWORDS, key=len, reverse=True):
        if kw in norm:
            key = _CHANNEL_KEYWORDS[kw]
            if key not in seen:
                found.append(key)
                seen.add(key)
    return found


def _extract_metrics(text: str) -> list[str]:
    """Return deduplicated metric keys mentioned.  Defaults to spend+roas+conversions."""
    norm = _normalise(text)
    found: list[str] = []
    seen: set[str] = set()
    for kw in sorted(_METRIC_KEYWORDS, key=len, reverse=True):
        if kw in norm:
            key = _METRIC_KEYWORDS[kw]
            if key not in seen:
                found.append(key)
                seen.add(key)
    return found if found else list(_DEFAULT_METRICS)


def _extract_date_range(
    text: str,
    default_from: date,
    default_to: date,
) -> tuple[date, date]:
    """Extract a concrete date range from Turkish natural-language text.

    Recognised patterns (case-insensitive):
        son N gün   — last N days (inclusive of today)
        bu ay       — current calendar month
        geçen ay    — previous calendar month
        son 90 gün  — handled by the generic "son N gün" rule

    Fallback: default_from / default_to unchanged.
    """
    norm = _normalise(text)
    # UTC to stay consistent with the reports endpoint and the UTC-keyed warehouse
    # (fact_daily_metrics dates come from the ad platforms in UTC). Using local
    # date.today() here caused an off-by-one vs the endpoint during 00:00–03:00 TRT.
    today = datetime.now(timezone.utc).date()

    # "son N gün" — last N calendar days
    m = re.search(r"son\s+(\d+)\s+g[üu]n", norm)
    if m:
        n = int(m.group(1))
        return today - timedelta(days=n - 1), today

    # "bu ay" — current month start → today
    if "bu ay" in norm:
        return today.replace(day=1), today

    # "geçen ay" / "gecen ay"
    if "ge" in norm and "en ay" in norm:  # covers geçen / gecen
        first_this_month = today.replace(day=1)
        last_prev = first_this_month - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev

    return default_from, default_to


def _extract_comparison(text: str) -> bool:
    return _keyword_match(text, *_COMPARISON_KEYWORDS)


def _extract_viz(text: str) -> str:
    """Return 'timeseries', 'table', or 'mixed'."""
    norm = _normalise(text)
    if any(kw in norm for kw in _VIZ_TIMESERIES):
        return "timeseries"
    if any(kw in norm for kw in _VIZ_TABLE):
        return "table"
    return "mixed"


def _build_title(
    channels: list[str],
    metrics: list[str],
    date_from: date,
    date_to: date,
    comparison: bool,
) -> str:
    """Generate a concise Turkish report title from the parsed intent."""
    ch_part = (
        " vs ".join(channel_label(c) for c in channels)
        if channels
        else "Tüm Kanallar"
    )
    days = (date_to - date_from).days + 1
    if days <= 1:
        period_part = f"{tr_date(date_from)} Günü"
    elif days == 30:
        period_part = "Son 30 Gün"
    elif days == 7:
        period_part = "Son 7 Gün"
    elif days == 90:
        period_part = "Son 90 Gün"
    else:
        period_part = f"{tr_date(date_from)} – {tr_date(date_to)}"
    suffix = " Karşılaştırması" if comparison else " Raporu"
    return f"{ch_part} {period_part}{suffix}"


@dataclass
class ReportSpec:
    """Structured report specification parsed from a natural-language prompt.

    Attributes
    ----------
    title:
        Turkish-language auto-generated title describing the report intent.
    metrics:
        Canonical metric keys to include (e.g. ["spend", "roas", "conversions"]).
    channels:
        Platform channel keys to filter to (empty = all channels).
    comparison:
        True when the user wants a side-by-side channel comparison.
    viz:
        Preferred visualisation type: "timeseries" | "table" | "mixed".
    date_from:
        Inclusive start date for the report.
    date_to:
        Inclusive end date for the report.
    """

    title: str
    metrics: list[str]
    channels: list[str]
    comparison: bool
    viz: str
    date_from: date
    date_to: date


# ── Stub parser ────────────────────────────────────────────────────────────────


def _stub_parse(
    prompt: str,
    *,
    default_from: date,
    default_to: date,
) -> ReportSpec:
    """Deterministic Turkish keyword-based spec extractor (no network)."""
    channels = _extract_channels(prompt)
    metrics = _extract_metrics(prompt)
    date_from, date_to = _extract_date_range(prompt, default_from, default_to)
    comparison = _extract_comparison(prompt)
    viz = _extract_viz(prompt)
    title = _build_title(channels, metrics, date_from, date_to, comparison)
    return ReportSpec(
        title=title,
        metrics=metrics,
        channels=channels,
        comparison=comparison,
        viz=viz,
        date_from=date_from,
        date_to=date_to,
    )


# ── Claude parser ──────────────────────────────────────────────────────────────


def _claude_parse(
    prompt: str,
    *,
    default_from: date,
    default_to: date,
    api_key: str,
    model: str,
    http_client: Any,
) -> ReportSpec:
    """Call Claude to extract a structured JSON spec.  Falls back to stub on error."""
    import httpx

    today = datetime.now(timezone.utc).date()
    system = (
        "Sen bir dijital pazarlama raporlama asistanısın. "
        "Kullanıcının Türkçe doğal dil sorgusunu yapılandırılmış JSON spesifikasyonuna "
        "dönüştür. Yalnızca geçerli JSON döndür, başka hiçbir şey ekleme."
    )
    user_msg = (
        f"Bugün: {today.isoformat()}\n"
        f"Varsayılan başlangıç: {default_from.isoformat()}\n"
        f"Varsayılan bitiş: {default_to.isoformat()}\n\n"
        f"Kullanıcı sorgusu: {prompt}\n\n"
        "Şu JSON formatında yanıt ver:\n"
        "{\n"
        '  "channels": ["google_ads","meta_ads"],\n'
        '  "metrics": ["spend","roas","conversions"],\n'
        '  "date_from": "YYYY-MM-DD",\n'
        '  "date_to": "YYYY-MM-DD",\n'
        '  "comparison": true,\n'
        '  "viz": "mixed"\n'
        "}\n\n"
        "channels: Desteklenen değerler: google_ads, meta_ads, tiktok_ads, "
        "linkedin_ads, microsoft_ads, criteo, pinterest_ads. Boş liste = tüm kanallar.\n"
        "metrics: Desteklenen değerler: spend, impressions, clicks, conversions, "
        "conversion_value, ctr, cpc, cpa, roas.\n"
        "viz: timeseries | table | mixed\n"
        "comparison: true ise kanal karşılaştırması isteniyor."
    )

    payload = {
        "model": model,
        "max_tokens": 512,
        "system": system,
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
            raise RuntimeError(
                f"Anthropic API {resp.status_code}: {resp.text[:200]}"
            )

        text = resp.json()["content"][0]["text"].strip()
        parsed = json.loads(text)

        channels = [str(c) for c in parsed.get("channels", [])]
        raw_metrics = [str(m) for m in parsed.get("metrics", [])]
        metrics = raw_metrics if raw_metrics else list(_DEFAULT_METRICS)

        date_from = date.fromisoformat(parsed["date_from"])
        date_to = date.fromisoformat(parsed["date_to"])
        comparison = bool(parsed.get("comparison", False))
        viz = str(parsed.get("viz", "mixed"))
        if viz not in ("timeseries", "table", "mixed"):
            viz = "mixed"

        title = _build_title(channels, metrics, date_from, date_to, comparison)
        return ReportSpec(
            title=title,
            metrics=metrics,
            channels=channels,
            comparison=comparison,
            viz=viz,
            date_from=date_from,
            date_to=date_to,
        )

    except Exception as exc:
        logger.warning(
            "[report_builder] Claude parse failed (%s) — falling back to stub", exc
        )
        return _stub_parse(prompt, default_from=default_from, default_to=default_to)


# ── Public API ─────────────────────────────────────────────────────────────────


def parse_request(
    prompt: str,
    *,
    default_from: date,
    default_to: date,
    http_client: Any = None,
) -> ReportSpec:
    """Parse a natural-language report request into a structured ReportSpec.

    Parameters
    ----------
    prompt:
        Free-form user text (Turkish or English).
    default_from:
        Fallback start date when no date expression is detected.
    default_to:
        Fallback end date when no date expression is detected.
    http_client:
        Optional httpx-compatible client for the Claude API.  Inject a mock
        in tests to avoid live network calls.  None → create on demand.

    Returns
    -------
    ReportSpec
        Fully populated specification.  Never raises; falls back to stub on
        Claude path errors.
    """
    from ayaz.config import settings

    api_key = settings.anthropic_api_key
    if api_key:
        return _claude_parse(
            prompt,
            default_from=default_from,
            default_to=default_to,
            api_key=api_key,
            model=settings.claude_narrator_model,
            http_client=http_client,
        )

    return _stub_parse(prompt, default_from=default_from, default_to=default_to)


def build_report(
    db: Any,
    tenant_id: Any,
    spec: ReportSpec,
) -> dict:
    """Execute a ReportSpec against the unified data layer and return aggregated data.

    Reuses ``_get_performance_summary`` and ``_get_timeseries`` from
    ``ayaz.services.copilot_tools`` — the exact same aggregation functions
    used by the dashboard API and AI copilot.  No SQL is duplicated.

    Parameters
    ----------
    db:
        SQLAlchemy Session (tenant-isolated by every query inside the tools).
    tenant_id:
        UUID of the requesting tenant.  Passed through to every SQL query.
    spec:
        Parsed report specification.

    Returns
    -------
    dict with keys:
        totals      — cross-channel metric totals (floats)
        by_channel  — list of per-channel dicts, filtered to spec.channels if any
        timeseries  — list of daily points for the primary metric (spend by default)
    """
    from ayaz.services.copilot_tools import _get_performance_summary, _get_timeseries

    date_from_str = spec.date_from.isoformat()
    date_to_str = spec.date_to.isoformat()

    # ── Aggregated summary ─────────────────────────────────────────────────
    summary = _get_performance_summary(db, tenant_id, date_from_str, date_to_str)
    totals = summary["totals"]
    by_channel = summary["by_channel"]

    # Filter by_channel to spec.channels when channels are specified
    if spec.channels:
        by_channel = [
            ch for ch in by_channel if ch["channel"] in spec.channels
        ]

    # ── Timeseries for primary metric ──────────────────────────────────────
    # Use the first metric in the spec that is supported by the timeseries tool.
    _TS_SUPPORTED = {"spend", "impressions", "clicks", "conversions", "conversion_value", "roas"}
    primary_metric = next(
        (m for m in spec.metrics if m in _TS_SUPPORTED),
        "spend",
    )
    ts_result = _get_timeseries(db, tenant_id, date_from_str, date_to_str, primary_metric)
    timeseries = ts_result.get("points", [])

    # ── Filter totals to requested metrics only ────────────────────────────
    # Always return all fields; consumer can pick what to display.
    # (Filtering here would make the API less useful for mixed visualisations.)

    return {
        "totals": totals,
        "by_channel": by_channel,
        "timeseries": timeseries,
    }
