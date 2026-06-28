"""Retry count on conversion events (Dalga 60 — M7 resilience).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-28

Adds ``conversion_events.retry_count`` (Integer, NOT NULL, server_default 0):
the number of retry attempts made after an initial forward failure.  The retry
endpoint increments it each time a failed event is re-forwarded.

Additive and non-breaking: existing rows default to 0.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversion_events",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Retry attempts made after an initial forward failure",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversion_events", "retry_count")
