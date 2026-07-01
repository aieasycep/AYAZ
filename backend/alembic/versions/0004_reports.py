"""Advanced Reporting schema — M3+.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String instead of Postgres ENUM types to
  avoid the duplicate-type migration bug present in the 0001 baseline.
  Allowed values are validated at the application/Pydantic layer.
* Every tenant-scoped table carries tenant_id for explicit filtering until
  Postgres RLS policies are deployed (see oltp.py for the same pattern).
* config / recipients are JSON columns.
* shared_reports.public_token has a UNIQUE constraint — the token is the secret.
* shared_reports.expires_at is a nullable Text (ISO-8601) so we avoid
  timezone complexity in SQLite; comparison is done in Python.
* PDF export is intentionally deferred; the HTML rendered by the service is
  designed to be rendered by headless Chrome in a later phase.

Tables created
--------------
  report_definitions — saved report templates
  report_schedules   — recurring delivery schedules for report_definitions
  shared_reports     — shareable public links for report_definitions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── report_definitions ────────────────────────────────────────────────────

    op.create_table(
        "report_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column("name", sa.String(300), nullable=False),
        # Full report specification (metrics, channels, branding, sections)
        sa.Column("config", sa.JSON, nullable=False, server_default="{}"),
        # UUID of the user who created this definition (informational, nullable)
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        # Timestamps
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
        "ix_report_definitions_tenant_id", "report_definitions", ["tenant_id"]
    )

    # ── report_schedules ──────────────────────────────────────────────────────

    op.create_table(
        "report_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "report_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "daily" | "weekly" | "monthly"
        sa.Column("cadence", sa.String(20), nullable=False),
        # 0=Mon … 6=Sun — null for daily/monthly cadences
        sa.Column("weekday", sa.Integer, nullable=True),
        # Hour of day in UTC (0-23)
        sa.Column("hour", sa.Integer, nullable=False, server_default="8"),
        # "email"
        sa.Column(
            "delivery", sa.String(20), nullable=False, server_default="email"
        ),
        # JSON list of recipient email addresses
        sa.Column("recipients", sa.JSON, nullable=False, server_default="[]"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
        # ISO-8601 UTC timestamp of last successful delivery (null until first send)
        sa.Column("last_sent_at", sa.Text, nullable=True),
        # Timestamps
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
        "ix_report_schedules_tenant_id", "report_schedules", ["tenant_id"]
    )
    op.create_index(
        "ix_report_schedules_definition_id",
        "report_schedules",
        ["report_definition_id"],
    )

    # ── shared_reports ────────────────────────────────────────────────────────

    op.create_table(
        "shared_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "report_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Unguessable 32-byte urlsafe token — the sole secret for public access
        sa.Column("public_token", sa.String(100), nullable=False, unique=True),
        # ISO-8601 UTC datetime after which the link expires (null = permanent)
        sa.Column("expires_at", sa.Text, nullable=True),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
        # Hit counter for simple engagement tracking
        sa.Column("view_count", sa.Integer, nullable=False, server_default="0"),
        # Timestamps
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
        "ix_shared_reports_tenant_id", "shared_reports", ["tenant_id"]
    )
    op.create_index(
        "ix_shared_reports_definition_id",
        "shared_reports",
        ["report_definition_id"],
    )


def downgrade() -> None:
    op.drop_table("shared_reports")
    op.drop_table("report_schedules")
    op.drop_table("report_definitions")
