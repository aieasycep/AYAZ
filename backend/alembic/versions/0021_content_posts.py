"""İçerik Planlayıcı — create content_posts table (M8).

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-28

What this migration adds
------------------------
New table ``content_posts`` for the Content Planner module.

Schema notes
------------
- All type / status values are ``sa.String`` — no Postgres ENUM — to avoid the
  duplicate-type migration bug documented in 0001_initial_schema.py.
- ``channels`` uses ``sa.JSON`` with ``server_default="'[]'"`` (SQLite-safe).
- ``status`` uses ``server_default="'draft'"`` so existing rows created before
  the application layer runs always have a valid status.
- ``ai_assisted`` uses ``server_default="'0'"`` (SQLite-safe boolean false).
- The table is tenant-scoped via ``tenant_id`` with an explicit index.

Live-publish gate
-----------------
The ``published`` status value is reserved for a future release when per-channel
OAuth credentials are available via the Integrations connector layer.  The HTTP
``publish`` action returns 501 in this version.  This is intentional — the status
column stores the value but the API prevents reaching it without valid credentials.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_posts",
        sa.Column(
            "id",
            sa.CHAR(32),
            primary_key=True,
            nullable=False,
            comment="UUID primary key (stored as 32-char hex on non-Postgres backends)",
        ),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "title",
            sa.String(200),
            nullable=False,
            comment="Short label for the post",
        ),
        sa.Column(
            "body",
            sa.Text,
            nullable=False,
            server_default="''",
            comment="Caption / post body text",
        ),
        sa.Column(
            "channels",
            sa.JSON,
            nullable=False,
            server_default="'[]'",
            comment="JSON array of target channel keys",
        ),
        sa.Column(
            "scheduled_at",
            sa.Text,
            nullable=True,
            comment="ISO-8601 datetime string for the scheduled publish time",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="'draft'",
            comment=(
                "draft | pending_approval | approved | scheduled | published | archived"
            ),
        ),
        sa.Column(
            "approval_note",
            sa.Text,
            nullable=True,
            comment="Reviewer note populated on reject",
        ),
        sa.Column(
            "media_url",
            sa.Text,
            nullable=True,
            comment="URL of an attached image or video asset",
        ),
        sa.Column(
            "ai_assisted",
            sa.Boolean,
            nullable=False,
            server_default="'0'",
            comment="True when the caption was generated via the Claude AI path",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_content_posts_tenant_id",
        "content_posts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_posts_tenant_id", table_name="content_posts")
    op.drop_table("content_posts")
