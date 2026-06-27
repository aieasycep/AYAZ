"""Add credentials_changed_at column to users table.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-27

Notes
-----
* Adds a nullable ``credentials_changed_at`` DateTime(timezone=True) column to
  the ``users`` table.
* No backfill: existing rows get NULL, meaning pre-existing tokens are not
  invalidated by the migration itself — only after the user changes their
  password for the first time post-deployment.
* No Postgres ENUM types used.
* Plain ``sa.DateTime`` (with timezone=True) — compatible with SQLite in tests.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "credentials_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "UTC timestamp of the last password change; "
                "tokens issued before this are rejected."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "credentials_changed_at")
