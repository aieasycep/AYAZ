"""Create notifications table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-27

Notes
-----
* Creates the ``notifications`` table used by the Bildirim Merkezi (Dalga 26).
* No Postgres ENUM types — all values stored as String (SQLite compatible).
* ``tenant_id`` references ``tenants.id`` with CASCADE delete.
* ``source_ref`` is indexed for fast deduplication lookups.
* ``read_at`` is a nullable timezone-aware DateTime; NULL means unread.
* TimestampMixin columns (``created_at``, ``updated_at``) have server defaults.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.CHAR(32), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "type",
            sa.String(32),
            nullable=False,
            comment="'insight' | 'automation' | 'system'",
        ),
        sa.Column(
            "severity",
            sa.String(16),
            nullable=False,
            server_default="info",
            comment="'info' | 'warning' | 'critical'",
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("link", sa.String(255), nullable=True),
        sa.Column(
            "source_ref",
            sa.String(128),
            nullable=True,
            comment="Dedup key — aynı kaynak için tekrar bildirim üretilmez",
        ),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Okunma zamanı; NULL ise okunmamış",
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
    )
    op.create_index(
        "ix_notifications_tenant_id", "notifications", ["tenant_id"]
    )
    op.create_index(
        "ix_notifications_source_ref", "notifications", ["source_ref"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_source_ref", table_name="notifications")
    op.drop_index("ix_notifications_tenant_id", table_name="notifications")
    op.drop_table("notifications")
