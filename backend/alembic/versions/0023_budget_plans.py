"""Aylık Bütçe Planlayıcı — budget_plans table (M12).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-28

Creates the ``budget_plans`` table used by the Monthly Budget Planner (M12).
The table is fully additive: no existing tables are modified.

No ENUM types are used — all status/objective values are String columns
validated at the application layer.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_plans",
        sa.Column("id", sa.CHAR(32), nullable=False),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "name",
            sa.String(200),
            nullable=False,
            comment="Human-readable plan label",
        ),
        sa.Column(
            "period_month",
            sa.String(7),
            nullable=False,
            comment="Target month in YYYY-MM format",
        ),
        sa.Column(
            "total_budget",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
            comment="Total budget to allocate across all channels",
        ),
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default="'TRY'",
            comment="ISO 4217 currency code",
        ),
        sa.Column(
            "objective",
            sa.String(30),
            nullable=False,
            server_default="'balanced'",
            comment="balanced | maximize_roas | maximize_conversions",
        ),
        sa.Column(
            "lookback_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
            comment="Days of historical data used for the allocation algorithm",
        ),
        sa.Column(
            "allocations",
            sa.Text(),
            nullable=True,
            comment="Serialised allocation result snapshot (NULL until first compute)",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'draft'",
            comment="draft | active | archived",
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
        "ix_budget_plans_tenant_id",
        "budget_plans",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_budget_plans_tenant_id", table_name="budget_plans")
    op.drop_table("budget_plans")
