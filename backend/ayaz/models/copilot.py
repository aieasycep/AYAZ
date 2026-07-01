"""ORM models for AYAZ AI Copilot — M11.

Tables
------
conversations
    One conversation thread per (tenant, user).  Title auto-set from the first
    user message.

messages
    Individual messages within a conversation.  Roles: user | assistant | tool.
    tool messages carry tool_name and tool_payload (JSON).

Design notes
------------
* All String columns — no Postgres ENUM to stay SQLite-compatible in tests.
* tenant_id on every row — explicit filter on every query (no RLS yet).
* conversation_id FK has CASCADE DELETE so removing a conversation also removes
  its messages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String, Text
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base


class Conversation(Base):
    """A copilot conversation thread belonging to one tenant/user pair."""

    __tablename__ = "copilot_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant that owns this conversation",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who started the conversation",
    )
    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Auto-derived from the first user message (truncated to 500 chars)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """A single message in a copilot conversation.

    Roles
    -----
    user      — sent by the human user.
    assistant — the final text reply from the copilot.
    tool      — internal tool-call record (tool_name + tool_payload).
    """

    __tablename__ = "copilot_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Denormalised for fast tenant-scoped queries without joining conversations",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="user | assistant | tool",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message body.  For tool role: human-readable summary of tool result.",
    )
    tool_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Tool function name for role=tool rows",
    )
    tool_payload: Mapped[dict | None] = mapped_column(
        sa.JSON,
        nullable=True,
        comment="Full tool result dict for role=tool rows",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )
