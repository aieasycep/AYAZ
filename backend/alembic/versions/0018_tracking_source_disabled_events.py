"""Add disabled_events JSON column to tracking_sources.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-28

Notes
-----
* Adds ``disabled_events`` (JSON, nullable=False, server_default='[]') to
  ``tracking_sources``.
* No Postgres ENUM types are used — plain JSON column only.
* Additive only: all existing rows get an empty list, preserving existing
  behaviour (all events remain enabled by default).
* The column stores a JSON array of event_name strings whose forwarding is
  suppressed.  Events with a name in this list are recorded (status="disabled")
  but NOT forwarded to any destination.

Decision: ingest order is dedup → disabled → consent check → forward.
Rationale: disabled is a source-level configuration gate; checking it early
avoids loading destinations unnecessarily for known-disabled event names.
Dedup is always first so that re-submitted duplicate events are always
detected and returned consistently regardless of disabled state.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tracking_sources",
        sa.Column(
            "disabled_events",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment=(
                "JSON array of event_name strings whose forwarding is suppressed. "
                "Events in this list are recorded (status='disabled') but not forwarded."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("tracking_sources", "disabled_events")
