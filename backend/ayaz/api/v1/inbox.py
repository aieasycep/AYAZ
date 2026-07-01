"""Sosyal Gelen Kutusu (Social Inbox) API — M13.

All endpoints are tenant-scoped via the ``get_current_membership`` dependency.
Tenant isolation is enforced on every query via ``membership.tenant_id``.

Endpoints
---------
    GET    /inbox/messages                       — list messages (filterable)
    POST   /inbox/messages                       — create / seed a message
    GET    /inbox/messages/{id}                  — get message WITH reply thread
    DELETE /inbox/messages/{id}                  — delete message (cascade replies)
    POST   /inbox/messages/{id}/replies          — add a reply (delivered=False)
    POST   /inbox/messages/{id}/assign           — set/clear assignee
    POST   /inbox/messages/{id}/status           — change status
    POST   /inbox/messages/{id}/tags             — replace tags
    POST   /inbox/suggest-reply                  — AI/template reply suggestion (no DB write)
    GET    /inbox/stats                          — aggregate stats

Live-delivery credential gate
------------------------------
``POST /inbox/messages/{id}/replies`` stores the reply in AYAZ with
``delivered=False``.  Live delivery to the social platform requires per-channel
OAuth tokens managed by the Integrations connector layer.  These credentials are
NOT available in this release.  The reply is persisted for audit purposes and
will never be silently discarded — it can be delivered later once the connector
layer is configured.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.models.social_inbox import (
    VALID_CHANNELS,
    VALID_KINDS,
    VALID_SENTIMENTS,
    VALID_STATUSES,
    SocialMessage,
    SocialReply,
)
from ayaz.services.social_inbox import (
    classify_sentiment,
    compute_inbox_stats,
    suggest_reply,
)

router = APIRouter(prefix="/inbox", tags=["inbox"])


# ── Utility ───────────────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Ownership helper ──────────────────────────────────────────────────────────


def _require_message(
    message_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> SocialMessage:
    """Return the message or raise 404 if not found / belongs to another tenant."""
    msg = db.scalar(
        select(SocialMessage).where(
            SocialMessage.id == message_id,
            SocialMessage.tenant_id == tenant_id,
        )
    )
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sosyal mesaj bulunamadı.",
        )
    return msg


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class SocialReplyOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    message_id: uuid.UUID
    body: str
    author: str | None
    delivered: bool
    ai_assisted: bool
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: SocialReply) -> "SocialReplyOut":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            message_id=obj.message_id,
            body=obj.body,
            author=obj.author,
            delivered=obj.delivered,
            ai_assisted=obj.ai_assisted,
            created_at=obj.created_at,
        )


class SocialMessageOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    channel: str
    kind: str
    external_id: str | None
    author_handle: str
    author_name: str | None
    text: str
    permalink: str | None
    sentiment: str
    status: str
    assignee: str | None
    tags: list[str]
    received_at: str
    created_at: str
    updated_at: str
    replies: list[SocialReplyOut] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(
        cls, obj: SocialMessage, include_replies: bool = False
    ) -> "SocialMessageOut":
        replies: list[SocialReplyOut] = []
        if include_replies:
            # Replies are already ordered by created_at via relationship config
            replies = [SocialReplyOut.from_orm_obj(r) for r in (obj.replies or [])]
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            channel=obj.channel,
            kind=obj.kind,
            external_id=obj.external_id,
            author_handle=obj.author_handle,
            author_name=obj.author_name,
            text=obj.text,
            permalink=obj.permalink,
            sentiment=obj.sentiment,
            status=obj.status,
            assignee=obj.assignee,
            tags=obj.tags if isinstance(obj.tags, list) else [],
            received_at=obj.received_at,
            created_at=obj.created_at.isoformat()
            if hasattr(obj.created_at, "isoformat")
            else str(obj.created_at),
            updated_at=obj.updated_at.isoformat()
            if hasattr(obj.updated_at, "isoformat")
            else str(obj.updated_at),
            replies=replies,
        )


class MessageCreateBody(BaseModel):
    channel: str
    kind: str
    author_handle: str
    text: str
    author_name: str | None = None
    permalink: str | None = None
    external_id: str | None = None
    received_at: str | None = None
    sentiment: str | None = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in VALID_CHANNELS:
            raise ValueError(
                f"Geçersiz kanal: {v!r}. "
                f"Geçerli kanallar: {sorted(VALID_CHANNELS)}."
            )
        return v

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in VALID_KINDS:
            raise ValueError(
                f"Geçersiz mesaj türü: {v!r}. "
                f"Geçerli türler: {sorted(VALID_KINDS)}."
            )
        return v

    @field_validator("sentiment")
    @classmethod
    def validate_sentiment(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in VALID_SENTIMENTS:
            raise ValueError(
                f"Geçersiz duygu: {v!r}. "
                f"Geçerli değerler: {sorted(VALID_SENTIMENTS)}."
            )
        return v


class ReplyCreateBody(BaseModel):
    body: str
    author: str | None = None


class AssignBody(BaseModel):
    assignee: str | None = None


class StatusBody(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(
                f"Geçersiz durum: {v!r}. "
                f"Geçerli durumlar: {sorted(VALID_STATUSES)}."
            )
        return v


class TagsBody(BaseModel):
    tags: list[str]


class SuggestReplyRequest(BaseModel):
    text: str
    channel: str | None = None
    tone: str = "samimi"


class SuggestReplyResponse(BaseModel):
    reply: str
    ai_assisted: bool


# ── List messages ─────────────────────────────────────────────────────────────


@router.get(
    "/messages",
    response_model=list[SocialMessageOut],
    summary="Gelen kutusundaki mesajları listele (filtrelenebilir)",
)
def list_messages(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    channel: str | None = Query(
        default=None,
        description="Kanala göre filtrele (ör: instagram, x)",
    ),
    kind: str | None = Query(
        default=None,
        description="Mesaj türüne göre filtrele (dm | comment | mention)",
    ),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Duruma göre filtrele (open | pending | resolved | snoozed)",
    ),
    sentiment: str | None = Query(
        default=None,
        description="Duyguya göre filtrele (positive | neutral | negative)",
    ),
    assignee: str | None = Query(
        default=None,
        description="Atanan temsilciye göre filtrele",
    ),
) -> list[SocialMessageOut]:
    q = (
        select(SocialMessage)
        .where(SocialMessage.tenant_id == membership.tenant_id)
        .order_by(SocialMessage.received_at.desc())
    )
    rows = list(db.scalars(q))

    # Python-side filtering for portability (same pattern as content.py)
    if channel is not None:
        rows = [r for r in rows if r.channel == channel]
    if kind is not None:
        rows = [r for r in rows if r.kind == kind]
    if status_filter is not None:
        rows = [r for r in rows if r.status == status_filter]
    if sentiment is not None:
        rows = [r for r in rows if r.sentiment == sentiment]
    if assignee is not None:
        rows = [r for r in rows if r.assignee == assignee]

    return [SocialMessageOut.from_orm_obj(r, include_replies=False) for r in rows]


# ── Create message ────────────────────────────────────────────────────────────


@router.post(
    "/messages",
    response_model=SocialMessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni bir sosyal mesaj oluştur (tohumlama/test/manuel ekleme için)",
)
def create_message(
    body: MessageCreateBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialMessageOut:
    """Create a social inbox message.

    Normally messages are populated by the platform sync job (connector layer).
    This endpoint is exposed for seed data, manual testing, and demo flows.

    Sentiment is auto-classified from the message text when not provided.
    received_at defaults to the current UTC time when not provided.
    """
    sentiment = body.sentiment
    if sentiment is None:
        sentiment = classify_sentiment(body.text)

    received_at = body.received_at or _utcnow_iso()

    msg = SocialMessage(
        tenant_id=membership.tenant_id,
        channel=body.channel,
        kind=body.kind,
        external_id=body.external_id,
        author_handle=body.author_handle,
        author_name=body.author_name,
        text=body.text,
        permalink=body.permalink,
        sentiment=sentiment,
        status="open",
        assignee=None,
        tags=[],
        received_at=received_at,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return SocialMessageOut.from_orm_obj(msg, include_replies=False)


# ── Get single message WITH thread ────────────────────────────────────────────


@router.get(
    "/messages/{message_id}",
    response_model=SocialMessageOut,
    summary="Bir mesajı yanıt dizisiyle birlikte getir",
)
def get_message(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialMessageOut:
    """Return the message and its full reply thread (replies sorted oldest-first)."""
    msg = _require_message(message_id, membership.tenant_id, db)
    return SocialMessageOut.from_orm_obj(msg, include_replies=True)


# ── Delete message ────────────────────────────────────────────────────────────


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sosyal mesajı sil (yanıtlar da silinir)",
)
def delete_message(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    msg = _require_message(message_id, membership.tenant_id, db)
    db.delete(msg)
    db.commit()


# ── Add reply ─────────────────────────────────────────────────────────────────


@router.post(
    "/messages/{message_id}/replies",
    response_model=SocialReplyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Mesaja yanıt ekle (canlı teslimat için kimlik bilgisi gerekli)",
)
def add_reply(
    message_id: uuid.UUID,
    body: ReplyCreateBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialReplyOut:
    """Add a reply to the message.

    The reply is stored in AYAZ with ``delivered=False``.

    Live delivery to the social platform (i.e. actually posting the reply on
    Instagram / X / etc.) requires per-channel OAuth tokens managed by the
    Integrations connector layer.  These credentials are NOT available in this
    release.  The reply is persisted for audit and will never be silently lost —
    it can be delivered later once the connector layer is configured.

    The message status is NOT changed automatically; use the /status endpoint
    to transition the message to "pending" or "resolved" as needed.
    """
    msg = _require_message(message_id, membership.tenant_id, db)

    reply = SocialReply(
        tenant_id=membership.tenant_id,
        message_id=msg.id,
        body=body.body,
        author=body.author,
        delivered=False,
        ai_assisted=False,
        created_at=_utcnow_iso(),
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)
    return SocialReplyOut.from_orm_obj(reply)


# ── Assign ────────────────────────────────────────────────────────────────────


@router.post(
    "/messages/{message_id}/assign",
    response_model=SocialMessageOut,
    summary="Mesajı bir temsilciye ata (veya atamayı kaldır)",
)
def assign_message(
    message_id: uuid.UUID,
    body: AssignBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialMessageOut:
    """Assign (or unassign) the message to a team agent.

    Pass ``assignee: null`` to clear the current assignment.
    """
    msg = _require_message(message_id, membership.tenant_id, db)
    msg.assignee = body.assignee
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return SocialMessageOut.from_orm_obj(msg, include_replies=False)


# ── Status transition ─────────────────────────────────────────────────────────


@router.post(
    "/messages/{message_id}/status",
    response_model=SocialMessageOut,
    summary="Mesajın durumunu değiştir (open | pending | resolved | snoozed)",
)
def set_message_status(
    message_id: uuid.UUID,
    body: StatusBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialMessageOut:
    msg = _require_message(message_id, membership.tenant_id, db)
    msg.status = body.status
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return SocialMessageOut.from_orm_obj(msg, include_replies=False)


# ── Tags ──────────────────────────────────────────────────────────────────────


@router.post(
    "/messages/{message_id}/tags",
    response_model=SocialMessageOut,
    summary="Mesajın etiketlerini güncelle (mevcut etiketlerin üzerine yazar)",
)
def set_message_tags(
    message_id: uuid.UUID,
    body: TagsBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SocialMessageOut:
    """Replace the message's tag list wholesale.

    Pass an empty list to clear all tags.
    """
    msg = _require_message(message_id, membership.tenant_id, db)
    msg.tags = body.tags
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return SocialMessageOut.from_orm_obj(msg, include_replies=False)


# ── AI reply suggestion ───────────────────────────────────────────────────────


@router.post(
    "/suggest-reply",
    response_model=SuggestReplyResponse,
    summary="Yapay zeka destekli yanıt önerisi üret (DB yazımı yok)",
)
def suggest_reply_endpoint(
    body: SuggestReplyRequest,
    membership: Membership = Depends(get_current_membership),  # noqa: ARG001 — auth gate
) -> SuggestReplyResponse:
    """Generate a Turkish customer-care reply suggestion for the given message text.

    No database write is performed.  The suggestion can be used as the body
    when calling POST /inbox/messages/{id}/replies.

    Uses the Claude API when ``settings.anthropic_api_key`` is configured;
    falls back to a deterministic template generator otherwise.  Never raises.

    ai_assisted will be False when the template path is used (no API key
    configured in this environment).
    """
    result = suggest_reply(
        message_text=body.text,
        channel=body.channel,
        tone=body.tone,
    )
    return SuggestReplyResponse(**result)


# ── Stats ─────────────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    summary="Gelen kutusu istatistiklerini hesapla",
)
def inbox_stats(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Return aggregate stats for the current tenant's social inbox.

    Counts are broken down by status, channel, sentiment, and kind.
    """
    messages = list(
        db.scalars(
            select(SocialMessage).where(
                SocialMessage.tenant_id == membership.tenant_id
            )
        )
    )
    return compute_inbox_stats(messages)
