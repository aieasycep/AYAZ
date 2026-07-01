"""Insights & Alerts schema — M4.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String instead of Postgres ENUM types to
  avoid the duplicate-type migration bug present in the 0001 baseline.
  Allowed values are validated at the application/Pydantic layer.
* Every tenant-scoped table carries tenant_id for explicit filtering until
  Postgres RLS policies are deployed (see oltp.py for the same pattern).
* insights.data is a JSON column storing the detector's raw signal payload.
* alert_rules.threshold is nullable — "anomaly" comparator has no threshold.
* Indexes on (tenant_id, status) and (tenant_id, severity) support the
  common dashboard query patterns.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── insights ──────────────────────────────────────────────────────────────

    op.create_table(
        "insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        # Classification
        # "roas_drop" | "spend_spike" | "zero_conversions" | "ctr_drop"
        # | "budget_pacing" | "anomaly" | "cpc_rise"
        sa.Column("category", sa.String(50), nullable=False),
        # "info" | "warning" | "critical"
        sa.Column(
            "severity", sa.String(20), nullable=False, server_default="info"
        ),
        # Turkish narrative
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        # Metric and channel context
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(50), nullable=True),
        # Entity scope (e.g. specific campaign)
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.String(200), nullable=True),
        sa.Column("entity_name", sa.String(300), nullable=True),
        # Analysed time window
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        # Lifecycle: "new" | "seen" | "dismissed"
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="new"
        ),
        # Ranking (higher = more important)
        sa.Column(
            "score", sa.Float, nullable=False, server_default="0.0"
        ),
        # Machine-readable detector payload
        sa.Column("data", sa.JSON, nullable=False, server_default="{}"),
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
    op.create_index("ix_insights_tenant_id", "insights", ["tenant_id"])
    op.create_index(
        "ix_insights_tenant_status", "insights", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_insights_tenant_severity", "insights", ["tenant_id", "severity"]
    )

    # ── alert_rules ───────────────────────────────────────────────────────────

    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column("name", sa.String(200), nullable=False),
        # Watched metric (e.g. "roas", "spend", "ctr", "cpc")
        sa.Column("metric", sa.String(50), nullable=False),
        # "pct_drop" | "pct_rise" | "below" | "above" | "anomaly"
        sa.Column("comparator", sa.String(20), nullable=False),
        # Null for "anomaly" comparator
        sa.Column("threshold", sa.Float, nullable=True),
        # Optional channel scope (matches DimChannel.key)
        sa.Column("channel_filter", sa.String(50), nullable=True),
        # "email" | "slack" | "none"
        sa.Column(
            "delivery", sa.String(20), nullable=False, server_default="none"
        ),
        # Email address or Slack webhook URL
        sa.Column("destination", sa.Text, nullable=True),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
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
    op.create_index("ix_alert_rules_tenant_id", "alert_rules", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("alert_rules")
    op.drop_table("insights")
