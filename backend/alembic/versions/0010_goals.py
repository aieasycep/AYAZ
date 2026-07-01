"""Goal Tracking table — M12.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-26

Notes
-----
* Uses sa.String for all enum-like columns (metric, period) — no Postgres ENUM,
  keeps SQLite compatibility for tests.
* period_start / period_end stored as String(10) ISO-8601 text (YYYY-MM-DD)
  for full SQLite compatibility; the service layer parses them to Python date.
* tenant_id carries tenant isolation; two partial indexes are created for the
  most common query patterns.
* No JSONB — not needed for this table.

Table
-----
goals — one row per marketer-defined performance target.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goals",
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
            comment="Tenant that owns this goal (RLS: filter on every query)",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="Human-readable goal name",
        ),
        sa.Column(
            "metric",
            sa.String(50),
            nullable=False,
            comment="spend | roas | conversions | conversion_value",
        ),
        sa.Column(
            "target_value",
            sa.Float,
            nullable=False,
            comment="The numeric target for the period",
        ),
        sa.Column(
            "period",
            sa.String(20),
            nullable=False,
            server_default="month",
            comment="Tracking period grain: month (only value currently)",
        ),
        sa.Column(
            "period_start",
            sa.String(10),
            nullable=False,
            comment="Inclusive start date as ISO-8601 text (YYYY-MM-DD)",
        ),
        sa.Column(
            "period_end",
            sa.String(10),
            nullable=False,
            comment="Inclusive end date as ISO-8601 text (YYYY-MM-DD)",
        ),
        sa.Column(
            "channel_filter",
            sa.String(100),
            nullable=True,
            comment="dim_channel.key to restrict metric to; NULL = all channels",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
            comment="Soft-disable flag",
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
        "ix_goals_tenant_id",
        "goals",
        ["tenant_id"],
    )
    op.create_index(
        "ix_goals_tenant_active",
        "goals",
        ["tenant_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_goals_tenant_active", table_name="goals")
    op.drop_index("ix_goals_tenant_id", table_name="goals")
    op.drop_table("goals")
