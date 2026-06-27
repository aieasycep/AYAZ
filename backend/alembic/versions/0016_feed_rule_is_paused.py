"""Add is_paused column to feed_rules table.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-27

Notes
-----
* Adds a non-nullable ``is_paused`` Boolean column to ``feed_rules`` with a
  server-default of ``false`` so that existing rows are automatically set to
  not-paused without a backfill step.
* No Postgres ENUM types used — Boolean + server_default ("false").
* Plain ``sa.Boolean`` — compatible with SQLite used in the test-suite.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feed_rules",
        sa.Column(
            "is_paused",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="When True this rule is skipped during feed generation",
        ),
    )


def downgrade() -> None:
    op.drop_column("feed_rules", "is_paused")
