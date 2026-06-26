"""Add user preferences columns: locale, timezone, email_alerts, email_briefing.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-26

Notes
-----
* Adds four preference columns to the ``users`` table.
* All columns are NOT NULL with server defaults so existing rows are
  back-filled immediately on upgrade without a two-phase migration.
* No Postgres ENUM types — all values stored as String/Boolean (SQLite
  compatible).
* ``locale`` is constrained to short locale codes (max 8 chars).
* ``timezone`` holds IANA timezone identifiers (max 64 chars).
* ``email_alerts`` and ``email_briefing`` are booleans with TRUE defaults.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "locale",
            sa.String(8),
            nullable=False,
            server_default="tr",
            comment="UI locale: 'tr' or 'en'",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default="Europe/Istanbul",
            comment="IANA timezone identifier, e.g. 'Europe/Istanbul'",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_alerts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether to send email alert notifications",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_briefing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether to send the daily email briefing",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "email_briefing")
    op.drop_column("users", "email_alerts")
    op.drop_column("users", "timezone")
    op.drop_column("users", "locale")
