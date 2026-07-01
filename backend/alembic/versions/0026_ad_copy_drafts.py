"""AI Reklam Metni Stüdyosu — ad_copy_drafts table (M15 Dalga 73).

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-28

Creates the ``ad_copy_drafts`` table used by the AI Reklam Metni Stüdyosu
(Ad Copy Studio, M15).  The migration is fully additive: no existing tables
are modified.

No ENUM types are used — all status and source values are String columns
validated at the application layer.

The table stores generated ad copy drafts per tenant, with JSON columns for
the input brief and the generated variants list.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ad_copy_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "platform",
            sa.String(50),
            nullable=False,
            comment="google_ads | meta_ads | tiktok_ads",
        ),
        sa.Column(
            "title",
            sa.String(200),
            nullable=False,
            comment="Short user-supplied label, e.g. product name",
        ),
        sa.Column(
            "brief",
            sa.JSON(),
            nullable=False,
            comment="Input brief dict (platform, product, value_prop, tone, keywords, audience)",
        ),
        sa.Column(
            "variants",
            sa.JSON(),
            nullable=False,
            comment="Generated variants list — same shape as generate_ad_copy response",
        ),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="template",
            comment="template | ai",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="saved",
            comment="saved | archived",
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
        "ix_ad_copy_drafts_tenant_id",
        "ad_copy_drafts",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ad_copy_drafts_tenant_id",
        table_name="ad_copy_drafts",
    )
    op.drop_table("ad_copy_drafts")
