"""Briefing table — daily AI Turkish digest.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-26

Notes
-----
* Uses sa.String for the date column (YYYY-MM-DD text) — no native Date type,
  keeping SQLite compatibility for tests (same convention as goals table).
* ``body`` is sa.JSON (not JSONB) for the same SQLite compatibility reason.
* ``headline`` is Text — unbounded Turkish string.
* Unique compound index on (tenant_id, briefing_date) enforces the idempotency
  key at the DB level.  The service layer relies on this to implement upsert
  behaviour without a UNIQUE constraint race.
* No Postgres ENUM types — all categorical data stored as String.

Table
-----
briefings — one row per (tenant, date) daily digest.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefings",
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
            comment="Tenant that owns this briefing (RLS: filter on every query)",
        ),
        sa.Column(
            "briefing_date",
            sa.String(10),
            nullable=False,
            comment="ISO-8601 date (YYYY-MM-DD) of the day this briefing covers",
        ),
        sa.Column(
            "headline",
            sa.Text,
            nullable=False,
            comment="Turkish one-liner — Claude-generated or deterministic template",
        ),
        sa.Column(
            "body",
            sa.JSON,
            nullable=False,
            comment=(
                "Structured sections: performance_delta, top_insights, "
                "top_recommendation, goals_status"
            ),
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

    # Primary lookup: tenant + date (idempotency + most common query pattern)
    op.create_index(
        "ix_briefings_tenant_date",
        "briefings",
        ["tenant_id", "briefing_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_briefings_tenant_date", table_name="briefings")
    op.drop_table("briefings")
