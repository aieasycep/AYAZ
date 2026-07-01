"""Automation & Rules engine schema — M9.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String to avoid the duplicate-type migration
  bug documented in 0001_initial_schema.py.  Allowed values are validated at
  the application/Pydantic layer.
* Every tenant-scoped table carries tenant_id for explicit filtering until
  Postgres RLS policies are deployed.
* action_config / detail are JSON columns (opaque to the schema layer).
* last_triggered_at is a nullable Text (ISO-8601 date) to avoid timezone
  complexity in SQLite; comparison is done in Python.
* automation_runs.rule_id references automation_rules.id with CASCADE DELETE so
  audit rows are removed when a rule is deleted.

Tables created
--------------
  automation_rules – user-defined metric conditions and their actions
  automation_runs  – append-only audit log of every evaluation
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── automation_rules ──────────────────────────────────────────────────────

    op.create_table(
        "automation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column("name", sa.String(200), nullable=False),
        # "account" | "channel" | "campaign"
        sa.Column(
            "scope", sa.String(20), nullable=False, server_default="account"
        ),
        # DimChannel.key or DimCampaign.id string; null = all
        sa.Column("scope_filter", sa.String(300), nullable=True),
        # "spend" | "roas" | "ctr" | "cpc" | "cpa" | "conversions"
        sa.Column("metric", sa.String(50), nullable=False),
        # "pct_drop" | "pct_rise" | "below" | "above" | "anomaly"
        sa.Column("comparator", sa.String(20), nullable=False),
        # Threshold value; null for "anomaly" comparator
        sa.Column("threshold", sa.Float, nullable=True),
        # Look-back window in days (default 7)
        sa.Column(
            "window_days", sa.Integer, nullable=False, server_default="7"
        ),
        # "alert" | "notify_email" | "notify_slack" | "pause_suggest"
        sa.Column(
            "action", sa.String(30), nullable=False, server_default="alert"
        ),
        # JSON delivery config: {recipients} | {webhook} | {}
        sa.Column(
            "action_config", sa.JSON, nullable=False, server_default="{}"
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
        # ISO-8601 date string of the last calendar day an action fired
        sa.Column("last_triggered_at", sa.Text, nullable=True),
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
        "ix_automation_rules_tenant_id", "automation_rules", ["tenant_id"]
    )
    op.create_index(
        "ix_automation_rules_tenant_active",
        "automation_rules",
        ["tenant_id", "is_active"],
    )

    # ── automation_runs ───────────────────────────────────────────────────────

    op.create_table(
        "automation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Denormalised from the rule for efficient per-tenant queries",
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("automation_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ISO-8601 UTC datetime of when this evaluation ran
        sa.Column("ran_at", sa.Text, nullable=False),
        # True when condition was met and an action was taken
        sa.Column(
            "triggered", sa.Boolean, nullable=False, server_default="false"
        ),
        # Machine-readable evaluation output: matched entities, values, action taken
        sa.Column(
            "detail", sa.JSON, nullable=False, server_default="{}"
        ),
    )
    op.create_index(
        "ix_automation_runs_tenant_id", "automation_runs", ["tenant_id"]
    )
    op.create_index(
        "ix_automation_runs_rule_id", "automation_runs", ["rule_id"]
    )
    op.create_index(
        "ix_automation_runs_tenant_ran_at",
        "automation_runs",
        ["tenant_id", "ran_at"],
    )


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automation_rules")
