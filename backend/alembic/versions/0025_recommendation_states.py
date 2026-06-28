"""Öneri Durumu (Recommendation State) — recommendation_states table (M14).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-28

Creates the ``recommendation_states`` table used by the Proaktif Öneri Merkezi
(Proactive Recommendation Center, M14).  The migration is fully additive: no
existing tables are modified.

No ENUM types are used — all status values are String columns validated at the
application layer.

The unique constraint on (tenant_id, recommendation_key) ensures one state row
per recommendation per tenant.  The accept/snooze/dismiss/reopen workflow is
enforced at the service layer.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_states",
        sa.Column("id", sa.CHAR(32), nullable=False),
        sa.Column(
            "tenant_id",
            sa.CHAR(32),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "recommendation_key",
            sa.String(200),
            nullable=False,
            comment="Stable deterministic key: <category>:<subtype>[:<channel>]",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'open'",
            comment="open | accepted | snoozed | dismissed",
        ),
        sa.Column(
            "snoozed_until",
            sa.Text(),
            nullable=True,
            comment="ISO-8601 UTC datetime when the snooze expires; null unless snoozed",
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
            comment="Optional user-supplied note attached to the action",
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
        sa.UniqueConstraint(
            "tenant_id",
            "recommendation_key",
            name="uq_recommendation_states_tenant_key",
        ),
    )
    op.create_index(
        "ix_recommendation_states_tenant_id",
        "recommendation_states",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_states_tenant_id",
        table_name="recommendation_states",
    )
    op.drop_table("recommendation_states")
