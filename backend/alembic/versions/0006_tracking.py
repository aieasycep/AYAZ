"""Server-side Tracking / Conversions API schema — M7.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-26

Notes
-----
* All type/status columns use sa.String to avoid the duplicate-type migration
  bug documented in 0001_initial_schema.py.  Allowed values are validated at
  the application/Pydantic layer.
* Every tenant-scoped table carries tenant_id for explicit filtering until
  Postgres RLS policies are deployed.
* user_data / custom_data / config / action_config are JSON columns (opaque to
  the schema layer).
* created_at on conversion_events is Text (ISO-8601) for SQLite compat, matching
  the pattern used in automation_runs.ran_at.
* No Postgres ENUM types are used.

Tables created
--------------
  tracking_sources    – named first-party data sources (public_token write key)
  event_destinations  – per-platform forwarding targets (config + vault ref)
  conversion_events   – immutable inbound event records with status tracking
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tracking_sources ──────────────────────────────────────────────────────

    op.create_table(
        "tracking_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "domain",
            sa.String(253),
            nullable=True,
            comment="Site domain (optional; informational)",
        ),
        # URL-safe random write key — the sole secret protecting the collect URL.
        sa.Column(
            "public_token",
            sa.String(64),
            nullable=False,
            unique=True,
            comment="Write key in the collect URL; rotate to revoke access",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
            comment="Inactive sources reject inbound events with 404",
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
        "ix_tracking_sources_tenant_id", "tracking_sources", ["tenant_id"]
    )
    op.create_unique_constraint(
        "uq_tracking_sources_public_token", "tracking_sources", ["public_token"]
    )

    # ── event_destinations ────────────────────────────────────────────────────

    op.create_table(
        "event_destinations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "tracking_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracking_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "meta_capi" | "tiktok_events" | "ga4_mp"
        sa.Column(
            "platform",
            sa.String(30),
            nullable=False,
            comment="meta_capi | tiktok_events | ga4_mp",
        ),
        # Non-secret platform config (pixel_id / measurement_id / etc.)
        sa.Column(
            "config",
            sa.JSON,
            nullable=False,
            server_default="{}",
            comment="Non-secret platform config; access token lives in Vault",
        ),
        # Vault reference for the access token / API secret
        sa.Column(
            "vault_secret_ref",
            sa.Text,
            nullable=False,
            server_default="",
            comment="Vault path — actual token never stored in this column",
        ),
        sa.Column(
            "consent_required",
            sa.Boolean,
            nullable=False,
            server_default="true",
            comment="Skip forwarding events without consent when True",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
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
        "ix_event_destinations_tenant_id", "event_destinations", ["tenant_id"]
    )
    op.create_index(
        "ix_event_destinations_tracking_source_id",
        "event_destinations",
        ["tracking_source_id"],
    )

    # ── conversion_events ─────────────────────────────────────────────────────

    op.create_table(
        "conversion_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "tracking_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracking_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_name",
            sa.String(200),
            nullable=False,
            comment="Platform-agnostic event name (e.g. Purchase, AddToCart)",
        ),
        # ISO-8601 UTC datetime as supplied by the client (Text for SQLite compat)
        sa.Column(
            "event_time",
            sa.Text,
            nullable=False,
            comment="ISO-8601 UTC event time as supplied by the client",
        ),
        sa.Column(
            "event_id",
            sa.String(200),
            nullable=False,
            comment="Caller-supplied dedup key; unique per tracking_source",
        ),
        # Pre-hashed user identifiers — raw PII MUST NOT be written here
        sa.Column(
            "user_data",
            sa.JSON,
            nullable=False,
            server_default="{}",
            comment="SHA-256 hashed user identifiers only — no raw PII",
        ),
        # Non-PII event payload (value, currency, product data, etc.)
        sa.Column(
            "custom_data",
            sa.JSON,
            nullable=False,
            server_default="{}",
            comment="Non-PII event payload (value, currency, product data, etc.)",
        ),
        sa.Column(
            "consent",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="True when the end-user has given explicit consent",
        ),
        # "received" | "forwarded" | "failed" | "skipped_no_consent" | "duplicate"
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="received",
            comment="received | forwarded | failed | skipped_no_consent | duplicate",
        ),
        sa.Column(
            "forwarded_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "error",
            sa.Text,
            nullable=True,
            comment="Error detail from a failed platform forward attempt",
        ),
        # ISO-8601 UTC datetime of ingest (Text for SQLite compat)
        sa.Column(
            "created_at",
            sa.Text,
            nullable=False,
            comment="ISO-8601 UTC datetime of ingest",
        ),
    )
    op.create_index(
        "ix_conversion_events_tenant_id", "conversion_events", ["tenant_id"]
    )
    op.create_index(
        "ix_conversion_events_tracking_source_id",
        "conversion_events",
        ["tracking_source_id"],
    )
    op.create_index(
        "ix_conversion_events_source_event_id",
        "conversion_events",
        ["tracking_source_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_table("conversion_events")
    op.drop_table("event_destinations")
    op.drop_table("tracking_sources")
