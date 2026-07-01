"""Subscription & Billing schema — M10.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String to avoid the duplicate-type migration
  bug documented in 0001_initial_schema.py.  Allowed values are validated at
  the application/Pydantic layer.
* ``subscriptions`` carries a UNIQUE constraint on ``tenant_id`` — exactly one
  subscription row per tenant at all times.
* ``billing_events`` is append-only (no updated_at) — the audit log must never
  be modified.  ``created_at`` is Text (ISO-8601) for SQLite compatibility,
  matching the pattern used in automation_runs.ran_at and conversion_events.created_at.
* ``trial_end`` and ``current_period_end`` on subscriptions are also Text/ISO-8601
  for SQLite compatibility.
* payload on billing_events is a JSON column (opaque to the schema layer).
* No Postgres ENUM types are used.

Tables created
--------------
  subscriptions   — one row per tenant; current billing state
  billing_events  — immutable audit log of all billing lifecycle events
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── subscriptions ──────────────────────────────────────────────────────────

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        # Plan code: free | starter | growth | agency
        sa.Column(
            "plan_code",
            sa.String(30),
            nullable=False,
            server_default="free",
            comment="free | starter | growth | agency",
        ),
        # Subscription lifecycle status
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
            comment="trialing | active | past_due | canceled",
        ),
        # Payment provider identifier
        sa.Column(
            "provider",
            sa.String(20),
            nullable=False,
            server_default="none",
            comment="none | iyzico | stripe",
        ),
        # Provider-side customer + subscription identifiers (nullable)
        sa.Column(
            "provider_customer_id",
            sa.String(200),
            nullable=True,
            comment="Provider customer ID (e.g. cus_xxx for Stripe)",
        ),
        sa.Column(
            "provider_subscription_id",
            sa.String(200),
            nullable=True,
            comment="Provider subscription ID (e.g. sub_xxx for Stripe)",
        ),
        # ISO-8601 datetime of trial end (Text for SQLite compat)
        sa.Column(
            "trial_end",
            sa.Text,
            nullable=True,
            comment="ISO-8601 UTC datetime when the trial ends",
        ),
        # ISO-8601 datetime of current billing period end (Text for SQLite compat)
        sa.Column(
            "current_period_end",
            sa.Text,
            nullable=True,
            comment="ISO-8601 UTC datetime of the current billing period end",
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
    op.create_index(
        "ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"]
    )
    op.create_unique_constraint(
        "uq_subscriptions_tenant_id", "subscriptions", ["tenant_id"]
    )

    # ── billing_events ─────────────────────────────────────────────────────────

    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        # Free-form event type string
        sa.Column(
            "type",
            sa.String(60),
            nullable=False,
            comment="checkout.created | subscription.upgraded | subscription.canceled | webhook.received | …",
        ),
        # Provider that originated the event
        sa.Column(
            "provider",
            sa.String(20),
            nullable=False,
            server_default="none",
            comment="none | iyzico | stripe",
        ),
        # Raw or synthetic event payload
        sa.Column(
            "payload",
            sa.JSON,
            nullable=False,
            server_default="{}",
            comment="Raw webhook body or synthetic event payload dict",
        ),
        # Immutable ingest timestamp (Text for SQLite compat)
        sa.Column(
            "created_at",
            sa.Text,
            nullable=False,
            comment="ISO-8601 UTC datetime of event ingestion",
        ),
    )
    op.create_index(
        "ix_billing_events_tenant_id", "billing_events", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_table("subscriptions")
