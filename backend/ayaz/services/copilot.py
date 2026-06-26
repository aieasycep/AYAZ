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
from ayaz.services.copilot_tools import TOOL_SPECS, dispatch

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_TOOL_ITERATIONS = 5

_SYSTEM_PROMPT = (
    "Sen AYAZ'ın dijital pazarlama asistanısın. "
    "Görevin, kullanıcıya ait reklam ve pazarlama verilerini analiz etmek, "
    "içgörüler sunmak ve aksiyon önerileri yapmaktır. "
    "YALNIZCA araçların döndürdüğü gerçek verilere dayan — asla uydurma. "
    "Aksiyonları öneri olarak sun; hiçbir şeyi otomatik olarak çalıştırma. "
    "Yanıtlarını kısa, net ve Türkçe yaz."
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
        f"Seçilen dönemde toplam harcama: {spend:,.2f}, "
        f"ROAS: {roas:.2f}x, "
        f"tıklama: {clicks:,.0f}, "
        f"dönüşüm: {conversions:,.0f}, "
        f"CTR: %{ctr:.2f}."
    ]
    if by_channel:
        top = sorted(by_channel, key=lambda c: c.get("spend", 0), reverse=True)
        top_ch = top[0]
        lines.append(
            f"En yüksek harcama kanalı: {top_ch['channel']} "
            f"({top_ch['spend']:,.2f} harcama, {top_ch['roas']:.2f}x ROAS)."
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
        f"({top['channel']}, harcama: {top['spend']:,.2f}, "
        f"ROAS: {top['roas']:.2f}x, dönüşüm: {top['conversions']:,.0f})."
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
        lines.append(f"• [{ins['severity'].upper()}] {ins['title']} ({ins['channel'] or 'genel'}).")
    return " ".join(lines)


def _summarise_feeds(result: dict) -> str:
    channels = result.get("channels", [])
    if not channels:
        return "Tanımlı feed kanalı bulunamadı."
    names = [f"{c['name']} ({c['channel_type']})" for c in channels[:5]]
    return f"Feed kanalları: {', '.join(names)}. Toplam {result.get('count', 0)} kanal."


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

    # ── intent: performance summary ────────────────────────────────────────
    if _keyword_match(
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
            "• Otomasyon kuralı taslağı "
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
) -> dict:
    """POST to the Anthropic Messages API and return the parsed response body."""
    import httpx

    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": _SYSTEM_PROMPT,
        "tools": TOOL_SPECS,
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
) -> AssistantReply:
    """Run the Claude tool-use loop.  Falls back to stub on any error."""
    tools_used: list[ToolUsed] = []

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

                    result = dispatch(tool_name, db, tenant_id, tool_input)
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
        return f"Toplam harcama: {spend:,.2f}"
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
