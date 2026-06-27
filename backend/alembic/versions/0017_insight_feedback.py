"""Add applied_at and reaction feedback columns to insights.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-27

Notes
-----
* Adds two nullable columns to ``insights``:
  - ``applied_at`` (DateTime with timezone) — set when the user marks a
    recommendation as applied; null means not yet applied.
  - ``reaction`` (String(8)) — thumbs feedback: 'up' | 'down' | null.
* No Postgres ENUM types used — plain DateTime + String, nullable.
* Additive only — all existing rows keep NULL for both columns, which is
  the correct default (nothing applied, no reaction yet).
* Compatible with SQLite used in the test suite (DateTime(timezone=True)
  stores as TEXT on SQLite, which is fine for testing).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the user marked this recommendation as applied; null = not applied",
        ),
    )
    op.add_column(
        "insights",
        sa.Column(
            "reaction",
            sa.String(8),
            nullable=True,
            comment="User reaction: 'up' | 'down' | null",
        ),
    )


def downgrade() -> None:
    op.drop_column("insights", "reaction")
    op.drop_column("insights", "applied_at")
