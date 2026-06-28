"""Sosyal Gelen Kutusu (Social Inbox) — social_messages + social_replies tables (M13).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-28

Creates the ``social_messages`` and ``social_replies`` tables used by the
Social Inbox (M13).  The migration is fully additive: no existing tables are
modified.

No ENUM types are used — all channel/kind/status/sentiment values are String
columns validated at the application layer.

Live platform sync and reply delivery are intentionally credential-gated: a
reply row is written with ``delivered=False`` until the connector layer has
valid OAuth tokens.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── social_messages ───────────────────────────────────────────────────────
    op.create_table(
        "social_messages",
        sa.Column("id", sa.CHAR(32), nullable=False),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            comment="instagram | facebook | x | linkedin | tiktok | youtube",
        ),
        sa.Column(
            "kind",
            sa.String(20),
            nullable=False,
            comment="dm | comment | mention",
        ),
        sa.Column(
            "external_id",
            sa.String(200),
            nullable=True,
            comment="Platform-native message/comment identifier; used for dedup on live sync",
        ),
        sa.Column(
            "author_handle",
            sa.String(120),
            nullable=False,
            comment="Platform @handle of the message author",
        ),
        sa.Column(
            "author_name",
            sa.String(200),
            nullable=True,
            comment="Display name of the message author (optional)",
        ),
        sa.Column(
            "text",
            sa.Text(),
            nullable=False,
            comment="Full text of the inbound message",
        ),
        sa.Column(
            "permalink",
            sa.Text(),
            nullable=True,
            comment="URL of the original post/comment/thread on the platform",
        ),
        sa.Column(
            "sentiment",
            sa.String(20),
            nullable=False,
            server_default="'neutral'",
            comment="positive | neutral | negative",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'open'",
            comment="open | pending | resolved | snoozed",
        ),
        sa.Column(
            "assignee",
            sa.String(200),
            nullable=True,
            comment="Display name/email of the agent assigned to this message",
        ),
        sa.Column(
            "tags",
            sa.Text(),
            nullable=False,
            server_default="'[]'",
            comment="Agent-applied label list (JSON string array)",
        ),
        sa.Column(
            "received_at",
            sa.Text(),
            nullable=False,
            comment="ISO-8601 UTC datetime when the message was received on the platform",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_social_messages_tenant_id",
        "social_messages",
        ["tenant_id"],
        unique=False,
    )

    # ── social_replies ────────────────────────────────────────────────────────
    op.create_table(
        "social_replies",
        sa.Column("id", sa.CHAR(32), nullable=False),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "message_id",
            sa.CHAR(32),
            sa.ForeignKey("social_messages.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent SocialMessage that this reply addresses",
        ),
        sa.Column(
            "body",
            sa.Text(),
            nullable=False,
            comment="Text body of the outbound reply",
        ),
        sa.Column(
            "author",
            sa.String(200),
            nullable=True,
            comment="Display name/email of the agent who wrote the reply",
        ),
        sa.Column(
            "delivered",
            sa.Boolean(),
            nullable=False,
            server_default="'0'",
            comment=(
                "False until live delivery via the connector layer. "
                "Live delivery requires per-channel OAuth tokens."
            ),
        ),
        sa.Column(
            "ai_assisted",
            sa.Boolean(),
            nullable=False,
            server_default="'0'",
            comment="True when the reply body came from the AI suggest-reply path",
        ),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            comment="ISO-8601 UTC datetime when the reply was recorded in AYAZ",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_social_replies_tenant_id",
        "social_replies",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_social_replies_message_id",
        "social_replies",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_social_replies_message_id", table_name="social_replies")
    op.drop_index("ix_social_replies_tenant_id", table_name="social_replies")
    op.drop_table("social_replies")
    op.drop_index("ix_social_messages_tenant_id", table_name="social_messages")
    op.drop_table("social_messages")
