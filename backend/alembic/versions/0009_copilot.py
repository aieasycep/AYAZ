"""AI Copilot conversations & messages tables — M11.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-26

Notes
-----
* Uses sa.String for all status/role columns — no Postgres ENUM (SQLite compat).
* tenant_id is denormalised onto copilot_messages for query performance; the
  application layer always writes both the conversation FK and the tenant_id.
* CASCADE DELETE on conversation_id ensures messages are cleaned up when the
  parent conversation is deleted.
* No JSONB — sa.JSON used for SQLite compatibility (Postgres accepts it too).

Tables
------
copilot_conversations  — one thread per (tenant, user).
copilot_messages       — individual messages within a thread.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── copilot_conversations ──────────────────────────────────────────────────
    op.create_table(
        "copilot_conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="Tenant that owns this conversation",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="User who started the conversation",
        ),
        sa.Column(
            "title",
            sa.String(500),
            nullable=True,
            comment="Auto-derived from the first user message (truncated to 500 chars)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_copilot_conversations_tenant_id",
        "copilot_conversations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_copilot_conversations_user_id",
        "copilot_conversations",
        ["user_id"],
    )

    # ── copilot_messages ───────────────────────────────────────────────────────
    op.create_table(
        "copilot_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Denormalised for fast tenant-scoped queries",
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="user | assistant | tool",
        ),
        sa.Column(
            "content",
            sa.Text,
            nullable=False,
            comment="Message body or tool result summary",
        ),
        sa.Column(
            "tool_name",
            sa.String(100),
            nullable=True,
            comment="Tool function name for role=tool rows",
        ),
        sa.Column(
            "tool_payload",
            sa.JSON,
            nullable=True,
            comment="Full tool result dict for role=tool rows",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_copilot_messages_conversation_id",
        "copilot_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_copilot_messages_tenant_id",
        "copilot_messages",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("copilot_messages")
    op.drop_table("copilot_conversations")
