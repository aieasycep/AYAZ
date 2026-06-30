"""seo_search_metrics table — SEO module Wave 1.

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-30

Creates one new table:

  seo_search_metrics  — stores per-query/page Search Console performance rows
                        (clicks, impressions, CTR, position) scoped to a tenant.

UUID columns use ``postgresql.UUID(as_uuid=True)`` for native Postgres UUID
type (the GUID TypeDecorator renders this on Postgres).  FKs to tenants.id
use the same type.

server_default values:
  - JSON columns: ``server_default="{}"``  (bare string, no inner quotes)
  - int columns:  ``server_default="0"``   (bare string, no inner quotes)
  - float columns: ``server_default="0"``  (bare string, no inner quotes)
  - created_at:   ``server_default=sa.func.now()``
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seo_search_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "query",
            sa.String(2048),
            nullable=False,
        ),
        sa.Column(
            "page",
            sa.String(2048),
            nullable=False,
        ),
        sa.Column(
            "clicks",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "impressions",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "ctr",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "position",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "device",
            sa.String(50),
            nullable=True,
        ),
        sa.Column(
            "country",
            sa.String(10),
            nullable=True,
        ),
        sa.Column(
            "extra",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "date", "query", "page", "device", "country",
            name="uq_seo_search_metrics",
        ),
    )
    op.create_index(
        "ix_seo_search_metrics_tenant_id",
        "seo_search_metrics",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_search_metrics_tenant_date",
        "seo_search_metrics",
        ["tenant_id", "date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_search_metrics_tenant_date", table_name="seo_search_metrics")
    op.drop_index("ix_seo_search_metrics_tenant_id", table_name="seo_search_metrics")
    op.drop_table("seo_search_metrics")
