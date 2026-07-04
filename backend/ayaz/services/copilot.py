"""AYAZ AI Copilot service — the backbone of the flagship feature.

Two operating modes
-------------------
Claude path (when settings.anthropic_api_key is set)
    Calls the Anthropic Messages API via httpx (same pattern as
    ClaudeNarrator — no SDK dependency, pure httpx).  Passes TOOL_SPECS so
    the model can call the tenant's real data.  The tool-use loop runs until
    the model returns a final ``text`` block or 5 iterations have elapsed.
    On any error the stub path is used as a fallback.

Stub path (no API key, or fallback)
    Deterministic Turkish intent router.  Keywords are matched against the
    user's text and the matching tool(s) are called.  A concise, data-grounded
    Turkish reply is templated from the tool results.  This path is
    genuinely useful and is the primary assertion target for tests.

Persistence
-----------
Every chat call persists:
1. The user Message row (role="user").
2. One or more tool Message rows (role="tool") for each tool called.
3. The final assistant Message row (role="assistant").

The Conversation.title is set from the first 120 characters of the first
user message if the conversation has no title yet.

Groundedness / no-hallucination
--------------------------------
The system prompt instructs the model to use only data returned by tools
and to present recommendations as proposals (not executed actions).
The stub path has no generative component at all — answers are built
exclusively from real aggregated numbers returned by the tool layer.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ayaz.models.copilot import Conversation, Message
from ayaz.services.copilot_tools import TOOL_SPECS, build_tenant_tool_specs, dispatch
from ayaz.services.channels import channel_label
from ayaz.services.trdate import TR_MONTHS_FULL
from ayaz.services.trformat import tr_int, tr_pct, tr_roas, tr_tl

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_TOOL_ITERATIONS = 5

_SYSTEM_PROMPT = (
    "Sen AYAZ'ın dijital pazarlama asistanısın. "
    "Görevin, kullanıcıya ait reklam ve pazarlama verilerini analiz etmek, "
    "içgörüler sunmak ve aksiyon önerileri yapmaktır. "
    "YALNIZCA araçların döndürdüğü gerçek verilere dayan — asla uydurma. "
    "Yanıtlarını kısa, net ve Türkçe yaz.\n\n"
    "## Eylem araçları hakkında önemli kurallar\n"
    "- create_automation_rule ve create_goal araçları gerçek veritabanı yazmaları yapar.\n"
    "- Bu araçları YALNIZCA kullanıcı açıkça 'kural oluştur', 'hedef koy', 'uyarı kur' "
    "gibi net bir eylem isteği yaptığında çağır.\n"
    "- Gerekli parametreler eksikse ÖNCE kullanıcıya sor; eksik parametrelerle araç çağırma.\n"
    "- Bir eylem aracı çağırdıktan sonra yanıtında ne oluşturulduğunu özetle: "
    "'Oluşturuldu: [kural/hedef adı] (ID: ...)'\n"
    "- Sadece okuma araçları (get_*, list_*, draft_*) için onay gerekmez.\n\n"
    "## Entegrasyon aksiyon araçları ([EYLEM] önekli)\n"
    "- [EYLEM] önekli araçlar Slack, Google Sheets, Gmail gibi harici servislere "
    "gerçek yazma işlemleri yapar.\n"
    "- Bu araçları YALNIZCA kullanıcı açıkça istediğinde çağır.\n"
    "- Çağırmadan önce ne yapacağını Türkçe olarak özetle ve kullanıcıdan onay iste: "
    "'[Bağlantı adı] üzerinde şunu yapacağım: [özet]. Onaylıyor musunuz?'\n"
    "- Araç 'requires_confirmation: true' döndürürse kullanıcıya özeti göster, "
    "onay aldıktan sonra tekrar çağır.\n"
    "- Kullanıcı onaylamadıysa aksiyonu gerçekleştirme."
)

# Default date range used by stub when user doesn't specify dates
def _default_date_range() -> tuple[str, str]:
    today = date.today()
    from datetime import timedelta
    date_to = today.isoformat()
    date_from = (today - timedelta(days=29)).isoformat()
    return date_from, date_to


# ── AssistantReply ────────────────────────────────────────────────────────────


@dataclass
class ToolUsed:
    """A record of one tool call made during a chat turn."""

    name: str
    summary: str  # Short human-readable summary of what the tool returned


@dataclass
class AssistantReply:
    """The final output of one chat() call."""

    text: str
    tools_used: list[ToolUsed] = field(default_factory=list)


# ── Persistence helpers ───────────────────────────────────────────────────────


def _persist_message(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_payload: dict | None = None,
) -> Message:
    """Create and flush a Message row."""
    msg = Message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_payload=tool_payload,
    )
    db.add(msg)
    db.flush()
    return msg


def _auto_title(conversation: Conversation, text: str, db: Session) -> None:
    """Set conversation.title from the first 120 characters of text if not set."""
    if conversation.title is None:
        conversation.title = text[:120]
        db.add(conversation)
        db.flush()


# ── Stub path: deterministic Turkish intent router ────────────────────────────


def _keyword_match(text: str, *keywords: str) -> bool:
    """Return True if any keyword appears in text (case-insensitive, Turkish-safe).

    Turkish has two types of I: dotted I (I/i) and dotless I (I/ı).
    Python's str.lower() maps 'İ' (U+0130, dotted capital I) to 'i̇'
    (i + combining dot above), not to plain 'i'.  This causes substring
    matching on Turkish text to fail.  We work around this by replacing 'İ'
    with 'i' before lowercasing, making the comparison ASCII-safe for the
    common case while preserving other Turkish characters correctly.
    """
    normalised = text.replace("İ", "i").replace("I", "i").lower()
    return any(kw in normalised for kw in keywords)


def _summarise_performance(result: dict) -> str:
    """Build a concise Turkish summary from get_performance_summary result."""
    totals = result.get("totals", {})
    by_channel = result.get("by_channel", [])
    spend = totals.get("spend", 0)
    roas = totals.get("roas", 0)
    conversions = totals.get("conversions", 0)
    clicks = totals.get("clicks", 0)
    ctr = totals.get("ctr", 0) * 100

    lines = [
        f"Seçilen dönemde toplam harcama: {tr_tl(spend, 2)}, "
        f"ROAS: {tr_roas(roas)}, "
        f"tıklama: {tr_int(clicks)}, "
        f"dönüşüm: {tr_int(conversions)}, "
        f"CTR: {tr_pct(ctr, 2)}."
    ]
    if by_channel:
        top = sorted(by_channel, key=lambda c: c.get("spend", 0), reverse=True)
        top_ch = top[0]
        lines.append(
            f"En yüksek harcama kanalı: {channel_label(top_ch['channel'])} "
            f"({tr_tl(top_ch['spend'], 2)} harcama, {tr_roas(top_ch['roas'])} ROAS)."
        )
    return " ".join(lines)


def _summarise_campaigns(result: dict) -> str:
    campaigns = result.get("campaigns", [])
    if not campaigns:
        return "Bu dönemde kampanya verisi bulunamadı."
    top = campaigns[0]
    return (
        f"Toplam {len(campaigns)} kampanya bulunuyor. "
        f"En yüksek harcamalı kampanya: '{top['campaign_name']}' "
        f"({channel_label(top['channel'])}, harcama: {tr_tl(top['spend'], 2)}, "
        f"ROAS: {tr_roas(top['roas'])}, dönüşüm: {tr_int(top['conversions'])})."
    )


def _summarise_recommendations(result: dict) -> str:
    recs = result.get("recommendations", [])
    if not recs:
        return "Bu dönem için öne çıkan bir kampanya önerisi bulunamadı."
    lines = [f"Tespit edilen {len(recs)} kampanya önerisi:"]
    for r in recs[:3]:
        lines.append(f"• [{r['severity'].upper()}] {r['message']}")
    return " ".join(lines)


def _summarise_insights(result: dict) -> str:
    insights = result.get("insights", [])
    if not insights:
        return "Şu an aktif içgörü bulunamadı."
    lines = [f"Son {len(insights)} içgörü:"]
    for ins in insights[:3]:
        lines.append(f"• [{ins['severity'].upper()}] {ins['title']} ({channel_label(ins['channel'])}).")
    return " ".join(lines)


def _summarise_feeds(result: dict) -> str:
    channels = result.get("channels", [])
    if not channels:
        return "Tanımlı feed kanalı bulunamadı."
    names = [f"{c['name']} ({c['channel_type']})" for c in channels[:5]]
    return f"Feed kanalları: {', '.join(names)}. Toplam {result.get('count', 0)} kanal."


def _summarise_content(result: dict) -> str:
    """Build a concise Turkish summary from get_content_status result."""
    total = result.get("total", 0)
    if total == 0:
        return "Henüz planlanmış içerik bulunmuyor."

    label = {
        "draft": "taslak",
        "pending_approval": "onay bekleyen",
        "approved": "onaylı",
        "scheduled": "zamanlanmış",
        "published": "yayınlanmış",
        "archived": "arşivlenmiş",
    }
    by_status = result.get("by_status", {})
    segs = [f"{cnt} {label.get(k, k)}" for k, cnt in by_status.items() if cnt]
    parts = [f"Toplam {total} içerik ({', '.join(segs)})."]

    upcoming = result.get("upcoming", [])
    if upcoming:
        nxt = upcoming[0]
        date = (nxt.get("scheduled_at") or "")[:10]
        parts.append(f"Sıradaki yayın: '{nxt['title']}'{f' ({date})' if date else ''}.")
    return " ".join(parts)


def _summarise_budget(result: dict) -> str:
    """Build a concise Turkish summary from get_budget_status result."""
    if not result.get("has_plan"):
        return "Henüz bir bütçe planı oluşturulmamış. 'Planlama' bölümünden oluşturabilirsiniz."
    obj_label = {
        "balanced": "dengeli",
        "maximize_roas": "ROAS odaklı",
        "maximize_conversions": "dönüşüm odaklı",
    }.get(result.get("objective", ""), result.get("objective", ""))
    parts = [
        f"En güncel plan: '{result.get('name')}' ({result.get('period_month')}), "
        f"toplam {tr_int(result.get('total_budget', 0))} {result.get('currency', 'TRY')}, "
        f"{obj_label} dağılım."
    ]
    top = result.get("top_platforms", [])
    if top:
        segs = [
            f"{p.get('label')} %{p.get('recommended_share')}"
            for p in top if p.get("label")
        ]
        if segs:
            parts.append("Önerilen dağılım: " + ", ".join(segs) + ".")
    proj = result.get("projection", {})
    if proj.get("expected_revenue"):
        parts.append(
            f"Beklenen gelir: {tr_int(proj['expected_revenue'])}, "
            f"ROAS: {tr_roas(float(proj.get('expected_roas', 0) or 0))}."
        )
    return " ".join(parts)


def _summarise_inbox(result: dict) -> str:
    """Build a concise Turkish summary from get_inbox_summary result."""
    total = result.get("total", 0)
    if total == 0:
        return "Sosyal gelen kutusunda mesaj bulunmuyor."
    sentiment = result.get("by_sentiment", {})
    parts = [
        f"Toplam {total} mesaj — {result.get('open', 0)} açık, "
        f"{result.get('pending', 0)} beklemede, {result.get('resolved', 0)} çözüldü."
    ]
    neg = sentiment.get("negative", 0)
    if neg:
        parts.append(f"{neg} olumsuz mesaj öncelik bekliyor.")
    return " ".join(parts)


def _summarise_executive(result: dict) -> str:
    """Build a concise Turkish summary from get_executive_summary result."""
    headline = result.get("headline")
    if headline:
        return headline
    kpis = result.get("kpis", {})
    if not kpis:
        return "Bu dönemde yeterli veri yok."
    return (
        f"Son 30 gün: harcama {tr_tl(kpis.get('spend', 0))}, "
        f"gelir {tr_tl(kpis.get('revenue', 0))}, ROAS {tr_roas(float(kpis.get('roas', 0) or 0))}."
    )


def _summarise_funnel(result: dict) -> str:
    """Build a concise Turkish summary from get_funnel_summary result."""
    entry_count = result.get("entry_count", 0)
    final_count = result.get("final_count", 0)
    overall_pct = result.get("overall_conversion_pct", 0.0)
    biggest_dropoff = result.get("biggest_dropoff")

    if entry_count == 0:
        return "Dönüşüm hunisi için henüz yeterli veri bulunamadı."

    parts = [
        f"Dönüşüm hunisi: {tr_int(entry_count)} giriş → {tr_int(final_count)} satın alma "
        f"({tr_pct(overall_pct)} genel dönüşüm)."
    ]
    if biggest_dropoff:
        from_label = biggest_dropoff.get("from_label", "?")
        to_label = biggest_dropoff.get("to_label", "?")
        dropoff_pct = biggest_dropoff.get("dropoff_pct", 0.0)
        parts.append(
            f"En büyük düşüş: {from_label} → {to_label} ({tr_pct(dropoff_pct)})."
        )
    return " ".join(parts)


def _summarise_consent(result: dict) -> str:
    """Build a concise Turkish summary from get_consent_summary result."""
    consent_rate = result.get("consent_rate_pct", 0.0)
    skipped = result.get("skipped_no_consent", 0)
    score = result.get("compliance_score", 0)
    grade = result.get("compliance_grade", "")

    grade_tr = {
        "uyumlu": "uyumlu",
        "kismi": "kısmi uyumlu",
        "eksik": "eksik",
    }.get(grade, grade)

    total_events = result.get("total_events", 0)
    if total_events == 0:
        return "KVKK rıza verileri için henüz kayıtlı olay bulunamadı."

    parts = [
        f"KVKK rıza oranı {tr_pct(consent_rate)}; "
        f"uyum skoru {score}/100 ({grade_tr})."
    ]
    if skipped:
        parts.append(f"{tr_int(skipped)} olay rıza olmadığı için iletilmedi.")
    return " ".join(parts)


def _summarise_benchmark(result: dict) -> str:
    """Build a concise Turkish summary from get_benchmark_summary result."""
    headline = result.get("headline", "")
    if not headline:
        return "Sektör kıyaslama verisi henüz yeterli değil."

    counts = result.get("summary_counts", {})
    metrics = result.get("metrics", [])

    parts = [f"Sektör kıyaslaması: {headline}"]

    # Add ROAS value as a concrete number anchor
    roas_metric = next((m for m in metrics if m.get("key") == "roas"), None)
    if roas_metric:
        val = roas_metric.get("your_value", 0.0)
        position_tr = {
            "strong": "güçlü",
            "average": "ortalama",
            "weak": "zayıf",
        }.get(roas_metric.get("position", ""), "")
        parts.append(f"ROAS {tr_roas(val)} ({position_tr}).")

    return " ".join(parts)


def _summarise_audit(result: dict) -> str:
    """Build a concise Turkish summary from get_audit_summary result."""
    score = result.get("score", 0)
    grade = result.get("grade", "")
    counts = result.get("counts", {})

    grade_tr = {
        "mukemmel": "mükemmel",
        "iyi": "iyi",
        "orta": "orta",
        "zayif": "zayıf",
    }.get(grade, grade)

    fail_count = counts.get("fail", 0)
    warn_count = counts.get("warn", 0)
    pass_count = counts.get("pass", 0)

    parts = [
        f"Hesap sağlık skoru {score}/100 ({grade_tr}): "
        f"{fail_count} sorun, {warn_count} uyarı, {pass_count} geçti."
    ]

    top_issues = result.get("top_issues", [])
    if top_issues:
        first = top_issues[0]
        parts.append(f"Öncelikli bulgu: {first.get('title', '')}.")

    return " ".join(parts)


def _summarise_subscription(result: dict) -> str:
    plan = result.get("plan_name", "?")
    status = result.get("status", "?")
    limits = result.get("limits", {})
    ds = limits.get("max_data_sources", "?")
    hist = limits.get("history_days", "?")
    return (
        f"Aktif plan: {plan} ({status}). "
        f"Veri kaynağı limiti: {ds}, "
        f"geçmiş verisi: {hist} gün."
    )


def _extract_rule_params(user_text: str) -> dict:
    """Try to extract automation rule parameters from free-form Turkish text.

    Returns a dict of the params found.  Missing params are absent from the dict.
    This is a best-effort heuristic; the stub asks for missing params rather than
    creating with guessed values.
    """
    params: dict = {}
    text_lower = user_text.replace("İ", "i").replace("I", "i").lower()

    # Metric detection
    metric_keywords = {
        "roas": "roas",
        "harcama": "spend",
        "spend": "spend",
        "tıklama oranı": "ctr",
        "ctr": "ctr",
        "tıklama başı": "cpc",
        "cpc": "cpc",
        "dönüşüm başı": "cpa",
        "cpa": "cpa",
        "dönüşüm": "conversions",
        "conversions": "conversions",
    }
    for kw, val in metric_keywords.items():
        if kw in text_lower:
            params["metric"] = val
            break

    # Comparator detection
    if any(kw in text_lower for kw in ["düştüğünde", "azaldığında", "pct_drop", "düşüş"]):
        params["comparator"] = "pct_drop"
    elif any(kw in text_lower for kw in ["arttığında", "yükseldiğinde", "artış", "pct_rise"]):
        params["comparator"] = "pct_rise"
    elif any(kw in text_lower for kw in ["altına", "below"]):
        params["comparator"] = "below"
    elif any(kw in text_lower for kw in ["üzerine", "above"]):
        params["comparator"] = "above"
    elif any(kw in text_lower for kw in ["anomali", "anormal", "anomaly"]):
        params["comparator"] = "anomaly"

    # Action detection (default to alert)
    if any(kw in text_lower for kw in ["bildir", "e-posta", "email", "notify_email"]):
        params["action"] = "notify_email"
    elif any(kw in text_lower for kw in ["slack"]):
        params["action"] = "notify_slack"
    else:
        params["action"] = "alert"

    # Threshold detection: look for numbers followed by % or bağımsız
    import re
    pct_match = re.search(r"(%\s*)?(\d+(?:[.,]\d+)?)\s*(%|yüzde|pct)?", user_text)
    if pct_match and params.get("comparator") in ("pct_drop", "pct_rise"):
        try:
            params["threshold"] = float(pct_match.group(2).replace(",", "."))
        except ValueError:
            pass
    elif pct_match and params.get("comparator") in ("below", "above"):
        try:
            params["threshold"] = float(pct_match.group(2).replace(",", "."))
        except ValueError:
            pass

    return params


def _handle_create_rule_intent(
    db: "Session",
    tenant_id: uuid.UUID,
    user_text: str,
    tools_used: "list[ToolUsed]",
) -> str:
    """Handle 'kural oluştur' intent: create if params present, else ask."""
    params = _extract_rule_params(user_text)

    missing = []
    if "metric" not in params:
        missing.append("hangi metrik (roas, spend, ctr, cpc, cpa, dönüşüm)")
    if "comparator" not in params:
        missing.append("hangi koşul (düşüş, artış, altına, üzerine, anomali)")
    if "threshold" not in params and params.get("comparator") not in ("anomaly", None):
        missing.append("eşik değeri (ör. %20)")

    if missing:
        return (
            "Otomasyon kuralı oluşturmak için şu bilgilere ihtiyacım var: "
            + "; ".join(missing) + ". "
            "Lütfen belirtin ve 'kural oluştur' diyerek tekrar deneyin."
        )

    # All required params present — create the rule
    name_base = params.get("metric", "Metrik").upper()
    comparator = params["comparator"]
    comp_tr = {
        "pct_drop": "Düşüş", "pct_rise": "Artış",
        "below": "Alt Limit", "above": "Üst Limit", "anomaly": "Anomali",
    }.get(comparator, comparator)
    rule_name = f"{name_base} {comp_tr} Uyarısı"

    dispatch_args: dict = {
        "name": rule_name,
        "metric": params["metric"],
        "comparator": comparator,
        "action": params.get("action", "alert"),
        "scope": "account",
        "window_days": 7,
    }
    if "threshold" in params:
        dispatch_args["threshold"] = params["threshold"]

    result = dispatch("create_automation_rule", db, tenant_id, dispatch_args)
    summary = _short_summary_action("create_automation_rule", result)
    tools_used.append(ToolUsed(name="create_automation_rule", summary=summary))

    if result.get("created"):
        return (
            f"Oluşturuldu: '{result['name']}' kuralı (ID: {result['rule_id']}). "
            f"Kural; {result['metric']} metriği için {result['comparator']} koşuluyla "
            f"{'eşik: ' + str(result['threshold']) if result.get('threshold') is not None else 'anomali tespiti'} "
            f"durumunda {result['action']} eylemi tetikleyecek."
        )
    else:
        return f"Kural oluşturulamadı: {result.get('errors', 'Bilinmeyen hata')}"


def _handle_create_goal_intent(
    db: "Session",
    tenant_id: uuid.UUID,
    user_text: str,
    tools_used: "list[ToolUsed]",
) -> str:
    """Handle 'hedef koy' intent: create if params present, else ask."""
    from datetime import date as _date
    import re

    text_lower = user_text.replace("İ", "i").replace("I", "i").lower()

    # Metric detection
    metric: str | None = None
    metric_keywords = {
        "roas": "roas",
        "harcama": "spend",
        "spend": "spend",
        "dönüşüm değeri": "conversion_value",
        "dönüşüm": "conversions",
        "conversions": "conversions",
    }
    for kw, val in metric_keywords.items():
        if kw in text_lower:
            metric = val
            break

    # Target value detection
    target_value: float | None = None
    num_match = re.search(r"(\d+(?:[.,]\d+)?)", user_text)
    if num_match:
        try:
            target_value = float(num_match.group(1).replace(",", "."))
        except ValueError:
            pass

    missing = []
    if metric is None:
        missing.append("hangi metrik (roas, spend, dönüşüm, dönüşüm değeri)")
    if target_value is None:
        missing.append("hedef değer (sayısal)")

    if missing:
        return (
            "Hedef oluşturmak için şu bilgilere ihtiyacım var: "
            + "; ".join(missing) + ". "
            "Ayrıca dönem başlangıç ve bitiş tarihlerini de belirtebilirsiniz "
            "(varsayılan: bu ayın başından sonuna). "
            "Lütfen belirtin ve 'hedef koy' diyerek tekrar deneyin."
        )

    # Default period: current month
    today = _date.today()
    period_start = today.replace(day=1).isoformat()
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day).isoformat()

    goal_name = f"{metric.upper()} Hedefi — {TR_MONTHS_FULL[today.month]} {today.year}"
    dispatch_args: dict = {
        "name": goal_name,
        "metric": metric,
        "target_value": target_value,
        "period_start": period_start,
        "period_end": period_end,
    }

    result = dispatch("create_goal", db, tenant_id, dispatch_args)
    summary = _short_summary_action("create_goal", result)
    tools_used.append(ToolUsed(name="create_goal", summary=summary))

    if result.get("created"):
        return (
            f"Oluşturuldu: '{result['name']}' hedefi (ID: {result['goal_id']}). "
            f"Hedef: {result['metric']} metriği için {result['target_value']} değeri, "
            f"dönem: {result['period_start']} → {result['period_end']}."
        )
    else:
        return f"Hedef oluşturulamadı: {result.get('errors', 'Bilinmeyen hata')}"


def _short_summary_action(tool_name: str, result: dict) -> str:
    """One-line Turkish summary for action tool results."""
    if tool_name == "create_automation_rule":
        if result.get("created"):
            return f"Kural oluşturuldu: {result.get('name', '?')} (ID: {result.get('rule_id', '?')})"
        return f"Kural oluşturulamadı: {result.get('errors', [])}"
    if tool_name == "create_goal":
        if result.get("created"):
            return f"Hedef oluşturuldu: {result.get('name', '?')} (ID: {result.get('goal_id', '?')})"
        return f"Hedef oluşturulamadı: {result.get('errors', [])}"
    return "Tamamlandı"


def _stub_chat(
    db: Session,
    tenant_id: uuid.UUID,
    user_text: str,
) -> AssistantReply:
    """Deterministic Turkish intent router."""
    date_from, date_to = _default_date_range()
    tools_used: list[ToolUsed] = []

    # Turkish-safe normalisation (see _keyword_match docstring)
    text_lower = user_text.replace("İ", "i").replace("I", "i").lower()

    # ── ACTION intents checked FIRST (most specific — user explicitly asks) ──

    # ── intent: create automation rule (ACTION) ────────────────────────────
    if _keyword_match(
        text_lower,
        "kural oluştur", "kural ekle", "uyarı kur", "alarm kur",
        "otomatik kural", "otomasyon kural", "create rule",
    ):
        reply_text = _handle_create_rule_intent(db, tenant_id, user_text, tools_used)

    # ── intent: create goal (ACTION) ──────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "hedef koy", "hedef oluştur", "hedef ekle", "kpi hedef",
        "create goal", "set goal",
    ):
        reply_text = _handle_create_goal_intent(db, tenant_id, user_text, tools_used)

    # ── intent: budget plan ────────────────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "bütçe", "budget", "alokasyon", "bütçe planı", "harcama planı",
    ):
        result = dispatch("get_budget_status", db, tenant_id, {})
        summary = _summarise_budget(result)
        tools_used.append(ToolUsed(name="get_budget_status", summary=summary))
        reply_text = f"Bütçe planı durumu: {summary}"

    # ── intent: social inbox ───────────────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "gelen kutusu", "inbox", "gelen mesaj", "müşteri mesaj",
        "müşteri hizmet", "açık mesaj", "kaç mesaj", "sosyal mesaj",
    ):
        result = dispatch("get_inbox_summary", db, tenant_id, {})
        summary = _summarise_inbox(result)
        tools_used.append(ToolUsed(name="get_inbox_summary", summary=summary))
        reply_text = f"Sosyal gelen kutusu: {summary}"

    # ── intent: executive overview ─────────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "yönetici", "cmo", "ceo", "üst düzey", "genel bakış",
        "executive", "pazarlama özet", "yönetici özet",
    ):
        result = dispatch("get_executive_summary", db, tenant_id, {})
        summary = _summarise_executive(result)
        tools_used.append(ToolUsed(name="get_executive_summary", summary=summary))
        reply_text = summary

    # ── intent: account audit / health check ──────────────────────────────
    # Must be BEFORE the greedy performance intent ("nasıl" would capture these).
    # "denetim", "sağlık taraması", "hesap denetimi", "audit", "sağlık skoru"
    # are all specific enough to be safe before performance.
    # "hesap sağlığı" — the phrase is unique (performance doesn't mention "sağlık").
    elif _keyword_match(
        text_lower,
        "denetim", "hesap sağlığı", "sağlık taraması", "hesap denetimi",
        "audit", "sağlık skoru",
    ):
        result = dispatch("get_audit_summary", db, tenant_id, {})
        summary = _summarise_audit(result)
        tools_used.append(ToolUsed(name="get_audit_summary", summary=summary))
        reply_text = summary

    # ── intent: KVKK / consent ─────────────────────────────────────────────
    # Must be BEFORE the greedy performance intent.
    # "kvkk", "rıza", "consent", "onay oranı", "rıza oranı" are all unique.
    # NOTE: "uyum" alone is deliberately excluded — it is too broad and could
    # match unrelated queries.  Only "kvkk" + "rıza" anchors are used.
    elif _keyword_match(
        text_lower,
        "kvkk", "rıza", "consent", "onay oranı", "rıza oranı",
    ):
        result = dispatch("get_consent_summary", db, tenant_id, {})
        summary = _summarise_consent(result)
        tools_used.append(ToolUsed(name="get_consent_summary", summary=summary))
        reply_text = summary

    # ── intent: sector benchmark / comparison ──────────────────────────────
    # Must be BEFORE performance ("sektör" is not captured by performance).
    # "kıyas", "benchmark", "sektör", "sektör ortalaması", "rakip ortalama"
    elif _keyword_match(
        text_lower,
        "kıyas", "benchmark", "sektör", "sektör ortalaması", "rakip ortalama",
    ):
        result = dispatch("get_benchmark_summary", db, tenant_id, {})
        summary = _summarise_benchmark(result)
        tools_used.append(ToolUsed(name="get_benchmark_summary", summary=summary))
        reply_text = summary

    # ── intent: funnel / conversion journey ───────────────────────────────
    # Must be BEFORE performance because "nasıl" in the performance branch would
    # steal "Dönüşüm hunisi nasıl görünüyor?".
    # "huni", "dönüşüm hunisi", "müşteri yolculuğu", "sepete ekleme",
    # "satın alma adımı", "funnel"
    # NOTE: "satın alma adımı" is a phrase (not bare "satın alma") so it does
    # not collide with the budget/performance "dönüşüm" keyword.
    elif _keyword_match(
        text_lower,
        "huni", "dönüşüm hunisi", "müşteri yolculuğu", "sepete ekleme",
        "satın alma adımı", "funnel",
    ):
        result = dispatch("get_funnel_summary", db, tenant_id, {})
        summary = _summarise_funnel(result)
        tools_used.append(ToolUsed(name="get_funnel_summary", summary=summary))
        reply_text = summary

    # ── intent: performance summary ────────────────────────────────────────
    # NOTE: "nasıl" is a very greedy keyword — it must come AFTER the four new
    # specific intents above (audit, consent, benchmark, funnel) to avoid
    # stealing queries like "Hesap sağlığı nasıl?".
    elif _keyword_match(
        text_lower,
        "özet", "performans", "nasıl gidiyor", "genel durum",
        "harcama", "toplam", "summary", "nasıl",
    ):
        result = dispatch(
            "get_performance_summary",
            db,
            tenant_id,
            {"date_from": date_from, "date_to": date_to},
        )
        summary = _summarise_performance(result)
        tools_used.append(ToolUsed(name="get_performance_summary", summary=summary))
        reply_text = (
            f"Son 30 günün performans özeti: {summary} "
            f"Daha fazla detay için kampanya veya kanal bazlı analiz yapabilirim."
        )

    # ── intent: campaign list ──────────────────────────────────────────────
    elif _keyword_match(text_lower, "kampanya", "campaign", "reklam listesi"):
        result = dispatch(
            "list_campaigns",
            db,
            tenant_id,
            {"date_from": date_from, "date_to": date_to},
        )
        summary = _summarise_campaigns(result)
        tools_used.append(ToolUsed(name="list_campaigns", summary=summary))
        reply_text = f"Kampanya durumu: {summary}"

    # ── intent: recommendations / optimization ─────────────────────────────
    elif _keyword_match(
        text_lower,
        "ne yapmalı", "öneri", "optimize", "tavsiye", "öneriyor",
        "iyileştir", "aksiyon",
        # root-cause / diagnosis phrasings ("ROAS neden düştü?", "sorun ne?")
        "neden", "düşt", "düşüyor", "sebep", "sorun", "kötü", "azal",
    ):
        rec_result = dispatch(
            "get_recommendations",
            db,
            tenant_id,
            {"date_from": date_from, "date_to": date_to},
        )
        ins_result = dispatch(
            "get_insights",
            db,
            tenant_id,
            {},
        )
        rec_summary = _summarise_recommendations(rec_result)
        ins_summary = _summarise_insights(ins_result)
        tools_used.append(ToolUsed(name="get_recommendations", summary=rec_summary))
        tools_used.append(ToolUsed(name="get_insights", summary=ins_summary))
        reply_text = f"{rec_summary} Ayrıca içgörüler: {ins_summary}"

    # ── intent: insights / anomaly ─────────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "içgörü", "anomali", "uyarı", "insight", "alert", "sorun", "kritik",
    ):
        result = dispatch("get_insights", db, tenant_id, {})
        summary = _summarise_insights(result)
        tools_used.append(ToolUsed(name="get_insights", summary=summary))
        reply_text = f"İçgörüler: {summary}"

    # ── intent: feed channels ──────────────────────────────────────────────
    elif _keyword_match(text_lower, "feed", "ürün kataloğu", "ürün listesi", "catalog"):
        result = dispatch("get_feed_channels", db, tenant_id, {})
        summary = _summarise_feeds(result)
        tools_used.append(ToolUsed(name="get_feed_channels", summary=summary))
        reply_text = f"Ürün feed'leri: {summary}"

    # ── intent: content planner ────────────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "içerik", "gönderi", "paylaşım", "sosyal medya", "içerik takvim",
        "onay bekleyen içerik", "zamanlanmış içerik", "content",
    ):
        result = dispatch("get_content_status", db, tenant_id, {})
        summary = _summarise_content(result)
        tools_used.append(ToolUsed(name="get_content_status", summary=summary))
        reply_text = f"İçerik planlayıcı durumu: {summary}"

    # ── intent: subscription / plan ───────────────────────────────────────
    elif _keyword_match(
        text_lower,
        "plan", "abonelik", "limit", "paket", "ücret", "subscription",
    ):
        result = dispatch("get_subscription_status", db, tenant_id, {})
        summary = _summarise_subscription(result)
        tools_used.append(ToolUsed(name="get_subscription_status", summary=summary))
        reply_text = f"Abonelik durumu: {summary}"

    # ── default: capability message ────────────────────────────────────────
    else:
        reply_text = (
            "Merhaba! AYAZ AI Kopilot olarak şunları yapabilirim: "
            "• Performans özeti (harcama, ROAS, CTR, dönüşüm) "
            "• Kampanya listesi ve detayları "
            "• Optimizasyon önerileri "
            "• İçgörü ve anomali analizi "
            "• Ürün feed durumu "
            "• İçerik planlayıcı durumu (taslak, onay bekleyen, zamanlanmış içerikler) "
            "• Aylık bütçe planı (dağılım ve beklenen sonuç) "
            "• Sosyal gelen kutusu özeti (açık/beklemede/çözüldü mesajlar) "
            "• Yönetici özeti (üst düzey KPI ve genel durum) "
            "• Dönüşüm hunisi analizi (müşteri yolculuğu, sepete ekleme, satın alma adımları) "
            "• KVKK rıza ve uyum durumu (rıza oranı, consent skoru) "
            "• Sektör kıyaslaması (benchmark, sektör ortalaması ile karşılaştırma) "
            "• Hesap sağlık taraması (denetim skoru, geçen/uyarı/sorun kontrolü) "
            "• Otomasyon kuralı oluşturma ('kural oluştur') "
            "• Hedef belirleme ('hedef koy') "
            "• Abonelik ve limit bilgisi "
            "Sorularınızı Türkçe veya İngilizce yazabilirsiniz."
        )

    return AssistantReply(text=reply_text, tools_used=tools_used)


# ── Claude path ────────────────────────────────────────────────────────────────


def _build_history_for_claude(
    conversation: Conversation,
    db: Session,
) -> list[dict]:
    """Rebuild the messages list for the Claude API from persisted Message rows.

    Claude expects alternating user/assistant messages.  Tool messages in our
    DB are internal records; we reconstruct the Claude format:
    - user turns: {role: user, content: str}
    - assistant turns with tool_use blocks followed by tool_result user turns.

    For simplicity we send a condensed history: the last 10 non-tool messages.
    """
    from sqlalchemy import select, asc
    from ayaz.models.copilot import Message as MsgModel

    msgs = db.scalars(
        select(MsgModel)
        .where(
            MsgModel.conversation_id == conversation.id,
            MsgModel.role.in_(["user", "assistant"]),
        )
        .order_by(asc(MsgModel.created_at))
        .limit(20)
    ).all()

    history = []
    for m in msgs:
        history.append({"role": m.role, "content": m.content})
    return history


def _call_claude(
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    http_client: Any,
    tools: list[dict] | None = None,
) -> dict:
    """POST to the Anthropic Messages API and return the parsed response body."""
    import httpx

    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": _SYSTEM_PROMPT,
        "tools": tools if tools is not None else TOOL_SPECS,
        "messages": messages,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "tools-2024-04-04",
        "content-type": "application/json",
    }

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
        raise RuntimeError(
            f"Anthropic API {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def _claude_chat(
    db: Session,
    tenant_id: uuid.UUID,
    conversation: Conversation,
    user_text: str,
    api_key: str,
    model: str,
    http_client: Any,
    user_id: uuid.UUID | None = None,
) -> AssistantReply:
    """Run the Claude tool-use loop.  Falls back to stub on any error.

    Builds a per-tenant dynamic tool pool (static tools + connected integration
    action tools) so Claude only sees tools for the tenant's actual connections.
    Integration write actions use the confirm-before-write flow (ADR-8).
    """
    tools_used: list[ToolUsed] = []

    # ── Per-tenant dynamic tool pool (design §6.1) ─────────────────────────
    try:
        tenant_tools = build_tenant_tool_specs(db, tenant_id)
    except Exception:
        tenant_tools = list(TOOL_SPECS)  # fall back to static tools on error

    # Build the messages list: existing history + new user message
    history = _build_history_for_claude(conversation, db)
    history.append({"role": "user", "content": user_text})

    messages = history  # mutable local reference

    try:
        for iteration in range(_MAX_TOOL_ITERATIONS):
            response = _call_claude(
                api_key=api_key,
                model=model,
                messages=messages,
                http_client=http_client,
                tools=tenant_tools,
            )

            stop_reason = response.get("stop_reason")
            content_blocks = response.get("content", [])

            # ── Collect any text blocks ────────────────────────────────────
            text_parts: list[str] = []
            tool_use_blocks: list[dict] = []

            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_use_blocks.append(block)

            # ── If model wants to call tools ───────────────────────────────
            if stop_reason == "tool_use" and tool_use_blocks:
                # Add assistant message (with tool_use content blocks)
                messages.append({"role": "assistant", "content": content_blocks})

                # Run each tool call and collect results
                tool_result_contents: list[dict] = []
                for tb in tool_use_blocks:
                    tool_id = tb.get("id", "")
                    tool_name = tb.get("name", "")
                    tool_input = tb.get("input", {})

                    # Dispatch — integration actions use extended dispatch with
                    # confirm-before-write (ADR-8); static tools dispatch directly.
                    result = dispatch(
                        tool_name,
                        db,
                        tenant_id,
                        tool_input,
                        user_id=user_id,
                        confirmed=False,  # Claude path always starts in preview phase
                    )
                    result_text = json.dumps(result, ensure_ascii=False, default=str)

                    # Build a summary for persistence and response
                    summary = _short_summary(tool_name, result)
                    tools_used.append(ToolUsed(name=tool_name, summary=summary))

                    tool_result_contents.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_text,
                    })

                # Append all tool results as one user message
                messages.append({"role": "user", "content": tool_result_contents})
                continue  # next iteration: model processes tool results

            # ── Final text reply ───────────────────────────────────────────
            final_text = " ".join(text_parts).strip()
            if not final_text:
                final_text = (
                    "Analiziniz tamamlandı. Başka bir sorunuz var mı?"
                )
            return AssistantReply(text=final_text, tools_used=tools_used)

        # Exceeded max iterations — return what we have
        return AssistantReply(
            text="Analiz sınırına ulaşıldı. Lütfen sorunuzu daha spesifik hale getirin.",
            tools_used=tools_used,
        )

    except Exception as exc:
        logger.warning(
            "[copilot] Claude path failed (%s) — falling back to stub", exc
        )
        return _stub_chat(db, tenant_id, user_text)


def _short_summary(tool_name: str, result: dict) -> str:
    """Produce a one-line Turkish summary of a tool result for the tools_used list."""
    if "error" in result:
        return f"Hata: {result['error']}"
    if tool_name == "get_performance_summary":
        spend = result.get("totals", {}).get("spend", 0)
        return f"Toplam harcama: {tr_tl(spend, 2)}"
    if tool_name == "get_timeseries":
        pts = result.get("points", [])
        return f"{result.get('metric', '?')} için {len(pts)} günlük veri"
    if tool_name == "list_campaigns":
        return f"{len(result.get('campaigns', []))} kampanya"
    if tool_name == "get_recommendations":
        return f"{len(result.get('recommendations', []))} öneri"
    if tool_name == "get_insights":
        return f"{result.get('count', 0)} içgörü"
    if tool_name == "get_feed_channels":
        return f"{result.get('count', 0)} feed kanalı"
    if tool_name == "draft_automation_rule":
        return "Taslak kural oluşturuldu" if result.get("draft") else "Hata"
    if tool_name == "get_subscription_status":
        return f"Plan: {result.get('plan_name', '?')}"
    if tool_name == "create_automation_rule":
        if result.get("created"):
            return f"Kural oluşturuldu: {result.get('name', '?')} (ID: {result.get('rule_id', '?')})"
        return f"Kural oluşturulamadı: {result.get('errors', [])}"
    if tool_name == "create_goal":
        if result.get("created"):
            return f"Hedef oluşturuldu: {result.get('name', '?')} (ID: {result.get('goal_id', '?')})"
        return f"Hedef oluşturulamadı: {result.get('errors', [])}"
    return "Tamamlandı"


# ── Public API ─────────────────────────────────────────────────────────────────


def chat(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation: Conversation,
    user_text: str,
    *,
    http_client: Any = None,  # injected in tests to avoid live network calls
) -> AssistantReply:
    """Run one chat turn: persist input, call the model (or stub), persist output.

    Parameters
    ----------
    db            : SQLAlchemy Session.
    tenant_id     : Tenant UUID — every tool call is scoped to this tenant.
    user_id       : User UUID (for audit / future personalisation).
    conversation  : The Conversation ORM object this message belongs to.
    user_text     : The raw text the user typed.
    http_client   : Optional httpx-compatible client for the Claude API call.
                    Inject a mock in tests; leave None for production.

    Returns
    -------
    AssistantReply with the final Turkish text and a list of tools used.
    """
    from ayaz.config import settings

    # ── Auto-title on first message ────────────────────────────────────────
    _auto_title(conversation, user_text, db)

    # ── Persist user message ───────────────────────────────────────────────
    _persist_message(
        db,
        conversation_id=conversation.id,
        tenant_id=tenant_id,
        role="user",
        content=user_text,
    )

    # ── Generate reply ─────────────────────────────────────────────────────
    api_key = settings.anthropic_api_key
    model = settings.claude_narrator_model

    if api_key:
        reply = _claude_chat(
            db=db,
            tenant_id=tenant_id,
            conversation=conversation,
            user_text=user_text,
            api_key=api_key,
            model=model,
            http_client=http_client,
            user_id=user_id,
        )
    else:
        reply = _stub_chat(db, tenant_id, user_text)

    # ── Persist tool messages ──────────────────────────────────────────────
    for tu in reply.tools_used:
        _persist_message(
            db,
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            role="tool",
            content=tu.summary,
            tool_name=tu.name,
            tool_payload=None,  # payload too large; summary stored in content
        )

    # ── Persist assistant reply ────────────────────────────────────────────
    _persist_message(
        db,
        conversation_id=conversation.id,
        tenant_id=tenant_id,
        role="assistant",
        content=reply.text,
    )

    db.commit()
    return reply
