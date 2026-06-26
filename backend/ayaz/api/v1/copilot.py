"""AI Copilot API — conversational marketing assistant endpoints.

All endpoints are tenant-scoped via ``get_current_membership``.  Every query
explicitly filters by ``membership.tenant_id``.

Routes
------
POST   /assistant/conversations                 — create a new conversation
GET    /assistant/conversations                 — list conversations for tenant
GET    /assistant/conversations/{id}/messages   — list messages in a conversation
POST   /assistant/conversations/{id}/messages   — send a message, get reply
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.copilot import Conversation, Message
from ayaz.models.oltp import Membership

router = APIRouter(prefix="/assistant", tags=["copilot"])


# ── Request / Response schemas ────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    """Optional first message to start the conversation with."""

    first_message: str | None = None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_name: str | None
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str


class ToolUsedOut(BaseModel):
    name: str
    summary: str


class SendMessageResponse(BaseModel):
    assistant_message: MessageOut
    tools_used: list[ToolUsedOut]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_conversation_or_404(
    db: Session,
    conversation_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Conversation:
    """Return the conversation or raise 404.  Enforces tenant isolation."""
    conv = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Konuşma bulunamadı.",
        )
    return conv


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new copilot conversation",
)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ConversationSummary:
    """Create a new conversation (optionally with a first message).

    If ``first_message`` is provided the copilot runs immediately and the
    conversation title is derived from the first message.
    """
    conv = Conversation(
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
    )
    db.add(conv)
    db.flush()

    if body.first_message:
        from ayaz.services.copilot import chat

        chat(
            db=db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            conversation=conv,
            user_text=body.first_message,
        )
        db.refresh(conv)

    db.commit()
    db.refresh(conv)
    return ConversationSummary(
        id=conv.id,
        title=conv.title,
        updated_at=conv.updated_at,
    )


@router.get(
    "/conversations",
    response_model=list[ConversationSummary],
    summary="List conversations for the current tenant",
)
def list_conversations(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[ConversationSummary]:
    """Return the 50 most recent conversations for the tenant.

    Ordered by updated_at descending so the most active conversations appear
    first.
    """
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == membership.tenant_id)
        .order_by(desc(Conversation.updated_at))
        .limit(50)
    ).all()

    return [
        ConversationSummary(id=c.id, title=c.title, updated_at=c.updated_at)
        for c in convs
    ]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
    summary="List messages in a conversation",
)
def list_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[MessageOut]:
    """Return all messages in the conversation, ordered chronologically.

    Returns 404 if the conversation does not exist or belongs to a different
    tenant (tenant isolation enforced).
    """
    conv = _get_conversation_or_404(db, conversation_id, membership.tenant_id)

    msgs = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    ).all()

    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_name=m.tool_name,
            created_at=m.created_at,
        )
        for m in msgs
    ]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
    summary="Send a user message and receive the assistant reply",
)
def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SendMessageResponse:
    """Run one chat turn.

    Validates the conversation belongs to the tenant, persists the user
    message, calls the copilot service (Claude path or stub), and persists
    the assistant reply + tool records.

    Returns the assistant Message row and a list of tools used.
    """
    if not body.content.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mesaj boş olamaz.",
        )

    conv = _get_conversation_or_404(db, conversation_id, membership.tenant_id)

    from ayaz.services.copilot import chat

    reply = chat(
        db=db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        conversation=conv,
        user_text=body.content,
    )

    # Retrieve the assistant message that was just persisted
    assistant_msg = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.role == "assistant",
        )
        .order_by(desc(Message.created_at))
    )
    if assistant_msg is None:
        # Should never happen — chat() always persists the assistant message
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Asistan yanıtı kaydedilemedi.",
        )

    return SendMessageResponse(
        assistant_message=MessageOut(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            tool_name=assistant_msg.tool_name,
            created_at=assistant_msg.created_at,
        ),
        tools_used=[
            ToolUsedOut(name=tu.name, summary=tu.summary) for tu in reply.tools_used
        ],
    )
