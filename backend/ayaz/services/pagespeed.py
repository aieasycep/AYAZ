"""Google PageSpeed Insights service — site audit via Core Web Vitals + Lighthouse.

API: https://www.googleapis.com/pagespeedonline/v5/runPagespeed
Free to use without a key (low rate limits); optional PAGESPEED_API_KEY / GOOGLE_API_KEY.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

_STRATEGY = "mobile"  # "mobile" or "desktop"


def run_audit(url: str, *, api_key: str = "", strategy: str = "mobile") -> dict[str, Any]:
    """Run a PageSpeed Insights audit for the given URL.

    Returns a structured result dict. Never raises — on error returns a degraded
    result with "status": "error" and "message" explaining the issue in Turkish.

    Parameters
    ----------
    url: The URL to audit.
    api_key: Optional PSI API key (from settings.google_api_key or settings.pagespeed_api_key).
    strategy: "mobile" or "desktop". Default "mobile".

    Returns
    -------
    dict with keys:
        status: "ok" | "error" | "kimlik_bekliyor"
        url: str
        strategy: str
        scores: {"performance": float|None, "seo": float|None, "accessibility": float|None, "best_practices": float|None}
        core_web_vitals: {"lcp": ..., "fid": ..., "cls": ..., "fcp": ..., "ttfb": ...}  — each is {"value": float|None, "display": str, "score": str}  (score: "good"|"needs-improvement"|"poor"|"unknown")
        issues: [{"id": str, "title": str, "score": float, "description": str}]  — top failing audits
        raw: dict  — full API response (for debugging; omitted on error)
    """
    params: dict[str, str] = {"url": url, "strategy": strategy}
    if api_key:
        params["key"] = api_key

    try:
        resp = httpx.get(_PSI_URL, params=params, timeout=30)
    except httpx.TimeoutException:
        return _degraded(url, strategy, "PageSpeed API isteği zaman aşımına uğradı. Daha sonra tekrar deneyin.")
    except httpx.ConnectError:
        return _degraded(url, strategy, "PageSpeed API'ye bağlanılamadı. İnternet bağlantısını kontrol edin.")
    except httpx.HTTPError as exc:
        return _degraded(url, strategy, f"PageSpeed API hatası: {exc}")

    if resp.status_code == 400:
        return _degraded(url, strategy, "Geçersiz URL veya API isteği. URL'yi kontrol edin.")
    if resp.status_code == 403:
        return {
            "status": "kimlik_bekliyor",
            "url": url,
            "strategy": strategy,
            "message": "PageSpeed API anahtarı gerekli veya kota aşıldı. GOOGLE_API_KEY ortam değişkenini ayarlayın.",
            "scores": {"performance": None, "seo": None, "accessibility": None, "best_practices": None},
            "core_web_vitals": _empty_cwv(),
            "issues": [],
        }
    if resp.status_code == 429:
        return _degraded(url, strategy, "PageSpeed API oran limiti aşıldı. Birkaç dakika sonra tekrar deneyin.")
    if not resp.is_success:
        return _degraded(url, strategy, f"PageSpeed API {resp.status_code} hatası döndürdü.")

    try:
        data = resp.json()
    except Exception:
        return _degraded(url, strategy, "PageSpeed API yanıtı ayrıştırılamadı.")

    return _parse_response(url, strategy, data)


def _parse_response(url: str, strategy: str, data: dict) -> dict:
    """Parse a successful PSI API response."""
    cats = (data.get("lighthouseResult") or {}).get("categories") or {}
    audits = (data.get("lighthouseResult") or {}).get("audits") or {}

    def _score(key: str) -> float | None:
        cat = cats.get(key)
        if cat is None:
            return None
        s = cat.get("score")
        return round(float(s) * 100, 1) if s is not None else None

    scores = {
        "performance": _score("performance"),
        "seo": _score("seo"),
        "accessibility": _score("accessibility"),
        "best_practices": _score("best-practices"),
    }

    # Core Web Vitals — extract from audits
    def _cwv_metric(audit_id: str) -> dict:
        a = audits.get(audit_id) or {}
        num_val = (a.get("numericValue") or None)
        disp = a.get("displayValue") or "N/A"
        score_val = a.get("score")
        if score_val is None:
            score_label = "unknown"
        elif score_val >= 0.9:
            score_label = "good"
        elif score_val >= 0.5:
            score_label = "needs-improvement"
        else:
            score_label = "poor"
        return {
            "value": round(float(num_val), 2) if num_val is not None else None,
            "display": disp,
            "score": score_label,
        }

    cwv = {
        "lcp": _cwv_metric("largest-contentful-paint"),
        "fid": _cwv_metric("max-potential-fid"),
        "cls": _cwv_metric("cumulative-layout-shift"),
        "fcp": _cwv_metric("first-contentful-paint"),
        "ttfb": _cwv_metric("server-response-time"),
    }

    # Top failing audits (score < 0.9, has description, is not informative)
    issues = []
    for audit_id, audit in audits.items():
        score = audit.get("score")
        if score is None or score >= 0.9:
            continue
        if audit.get("scoreDisplayMode") in ("informative", "notApplicable", "manual"):
            continue
        title = audit.get("title") or audit_id
        desc = (audit.get("description") or "")[:200]
        issues.append({"id": audit_id, "title": title, "score": score, "description": desc})

    issues.sort(key=lambda x: x["score"])
    issues = issues[:10]  # top 10 worst

    return {
        "status": "ok",
        "url": url,
        "strategy": strategy,
        "scores": scores,
        "core_web_vitals": cwv,
        "issues": issues,
        "raw": data,
    }


def _degraded(url: str, strategy: str, message: str) -> dict:
    return {
        "status": "error",
        "url": url,
        "strategy": strategy,
        "message": message,
        "scores": {"performance": None, "seo": None, "accessibility": None, "best_practices": None},
        "core_web_vitals": _empty_cwv(),
        "issues": [],
    }


def _empty_cwv() -> dict:
    empty = {"value": None, "display": "N/A", "score": "unknown"}
    return {"lcp": dict(empty), "fid": dict(empty), "cls": dict(empty), "fcp": dict(empty), "ttfb": dict(empty)}
