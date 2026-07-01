"""product segment depth — dim_product + fact_product_daily (Dalga 3).

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-01

Creates two new tables for SKU / category segment analytics:

  dim_product         — product / SKU dimension (sku, name, category, price)
  fact_product_daily  — per (tenant, product, channel, date) sales fact with
                        actual revenue, returns and attributed ad spend, so
                        gross vs return-adjusted (net) ROAS can be computed by
                        SKU and category.

UUID columns use ``postgresql.UUID(as_uuid=True)`` (the GUID TypeDecorator
renders native uuid on Postgres, CHAR(32) on SQLite).

server_default values:
  - int columns:     ``server_default="0"``  (bare string)
  - numeric columns: ``server_default="0"``  (bare string)
  - price_ccy / ccy: ``server_default="TRY"``
  - created_at:      ``server_default=sa.func.now()``
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dim_product",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("sku", sa.String(120), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(120), nullable=False, server_default=""),
        sa.Column("price_raw", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("price_ccy", sa.String(3), nullable=False, server_default="TRY"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_dim_product_tenant_sku"),
    )
    op.create_index("ix_dim_product_tenant", "dim_product", ["tenant_id"], unique=False)

    op.create_table(
        "fact_product_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date_key", sa.Date(), nullable=False),
        sa.Column("units_sold", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("gross_revenue", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("returned_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("returned_revenue", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("ad_spend", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("ccy", sa.String(3), nullable=False, server_default="TRY"),
        sa.ForeignKeyConstraint(["product_id"], ["dim_product.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["dim_channel.id"]),
        sa.ForeignKeyConstraint(["date_key"], ["dim_date.date_key"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "channel_id", "date_key",
            name="uq_fact_product_grain",
        ),
    )
    op.create_index(
        "ix_fact_product_tenant_date",
        "fact_product_daily",
        ["tenant_id", "date_key"],
        unique=False,
    )
    op.create_index(
        "ix_fact_product_tenant_product",
        "fact_product_daily",
        ["tenant_id", "product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fact_product_tenant_product", table_name="fact_product_daily")
    op.drop_index("ix_fact_product_tenant_date", table_name="fact_product_daily")
    op.drop_table("fact_product_daily")
    op.drop_index("ix_dim_product_tenant", table_name="dim_product")
    op.drop_table("dim_product")
