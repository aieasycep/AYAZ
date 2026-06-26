"""Feed Management schema — M5 (Channable-style).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String instead of Postgres ENUM types to
  avoid the duplicate-type migration bug present in the 0001 baseline.
  Allowed values are validated at the application/Pydantic layer.
* Every tenant-scoped table carries tenant_id for explicit filtering until
  Postgres RLS policies are deployed (see oltp.py for the same pattern).
* FeedProduct has a unique constraint on (feed_source_id, external_id) to
  make upserts idempotent across re-ingestions.
* FeedChannel.public_token is globally unique — it is used as the sole
  credential for the unauthenticated public feed URL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── feed_sources ─────────────────────────────────────────────────────────

    op.create_table(
        "feed_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column("name", sa.String(200), nullable=False),
        # "url_xml" | "url_csv" | "upload" | "google_sheet"
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        # "pending" | "syncing" | "ok" | "error"
        sa.Column(
            "status", sa.String(50), nullable=False, server_default="pending"
        ),
        sa.Column(
            "item_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "last_synced_at",
            sa.Text,
            nullable=True,
            comment="ISO-8601 UTC timestamp of the last successful sync",
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
    op.create_index("ix_feed_sources_tenant_id", "feed_sources", ["tenant_id"])

    # ── feed_products ─────────────────────────────────────────────────────────

    op.create_table(
        "feed_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "feed_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feed_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SKU / product ID from the source feed
        sa.Column("external_id", sa.String(500), nullable=False),
        # Full attribute dict from the parsed feed row (JSON)
        sa.Column("data", sa.JSON, nullable=False, server_default="{}"),
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
        sa.UniqueConstraint(
            "feed_source_id",
            "external_id",
            name="uq_feed_product_source_extid",
        ),
    )
    op.create_index("ix_feed_products_tenant_id", "feed_products", ["tenant_id"])
    op.create_index(
        "ix_feed_products_feed_source_id", "feed_products", ["feed_source_id"]
    )

    # ── feed_channels ─────────────────────────────────────────────────────────

    op.create_table(
        "feed_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "feed_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feed_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        # "google_shopping" | "meta_catalog" | "tiktok_catalog" | "custom"
        sa.Column("channel_type", sa.String(50), nullable=False),
        # "xml" | "csv"
        sa.Column(
            "output_format", sa.String(10), nullable=False, server_default="xml"
        ),
        # Unguessable random URL token — public feed URL credential
        sa.Column("public_token", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
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
    op.create_index("ix_feed_channels_tenant_id", "feed_channels", ["tenant_id"])
    op.create_index(
        "ix_feed_channels_feed_source_id", "feed_channels", ["feed_source_id"]
    )

    # ── feed_rules ────────────────────────────────────────────────────────────

    op.create_table(
        "feed_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "feed_channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feed_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Ascending application order within the channel",
        ),
        # "set_value" | "rename_field" | "find_replace"
        # | "filter_include" | "filter_exclude" | "calculated"
        sa.Column("rule_type", sa.String(50), nullable=False),
        # Rule-specific config dict — schema depends on rule_type
        sa.Column("config", sa.JSON, nullable=False, server_default="{}"),
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
    op.create_index("ix_feed_rules_tenant_id", "feed_rules", ["tenant_id"])
    op.create_index(
        "ix_feed_rules_feed_channel_id", "feed_rules", ["feed_channel_id"]
    )


def downgrade() -> None:
    op.drop_table("feed_rules")
    op.drop_table("feed_channels")
    op.drop_table("feed_products")
    op.drop_table("feed_sources")
