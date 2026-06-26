"""Initial schema — all AYAZ tables.

Revision ID: 0001
Revises: (none)
Create Date: 2026-06-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────────────
    membership_role = postgresql.ENUM(
        "owner", "admin", "member", name="membership_role", create_type=False
    )
    platform = postgresql.ENUM(
        "google_ads",
        "meta_ads",
        "ga4",
        "search_console",
        "tiktok_ads",
        "linkedin_ads",
        "microsoft_ads",
        "sample",
        name="platform",
        create_type=False,
    )
    sync_status = postgresql.ENUM(
        "idle", "syncing", "success", "error", "paused",
        name="sync_status",
        create_type=False,
    )
    membership_role.create(op.get_bind(), checkfirst=True)
    platform.create(op.get_bind(), checkfirst=True)
    sync_status.create(op.get_bind(), checkfirst=True)

    # ── OLTP tables ───────────────────────────────────────────────────────

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "country", sa.String(2), nullable=False, server_default="TR",
            comment="ISO 3166-1 alpha-2",
        ),
        sa.Column(
            "base_currency", sa.String(3), nullable=False, server_default="TRY",
            comment="ISO 4217",
        ),
        sa.Column(
            "kvkk_region", sa.String(50), nullable=False, server_default="TR",
            comment="Data residency region for KVKK compliance",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text, nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "role", sa.Enum("owner", "admin", "member", name="membership_role"),
            nullable=False, server_default="member",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])

    op.create_table(
        "connected_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "platform",
            sa.Enum(
                "google_ads", "meta_ads", "ga4", "search_console",
                "tiktok_ads", "linkedin_ads", "microsoft_ads", "sample",
                name="platform",
            ),
            nullable=False,
        ),
        sa.Column("external_account_id", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "vault_secret_ref", sa.Text, nullable=False, server_default="",
            comment="Vault path to OAuth tokens — never store tokens in this column",
        ),
        sa.Column(
            "sync_status",
            sa.Enum("idle", "syncing", "success", "error", "paused", name="sync_status"),
            nullable=False, server_default="idle",
        ),
        sa.Column(
            "watermark", sa.Text, nullable=True,
            comment="ISO-8601 datetime of the last successful incremental sync",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_connected_accounts_tenant_id", "connected_accounts", ["tenant_id"]
    )

    # ── Analytics dim tables ──────────────────────────────────────────────

    op.create_table(
        "dim_channel",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(50), nullable=False, unique=True),
        sa.Column("label", sa.String(100), nullable=False),
    )

    op.create_table(
        "dim_date",
        sa.Column("date_key", sa.Date, primary_key=True, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("week", sa.Integer, nullable=False),
        sa.Column("day_of_week", sa.Integer, nullable=False,
                  comment="0=Mon…6=Sun"),
        sa.Column("is_weekend", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "dim_currency_rate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("date_key", sa.Date, nullable=False),
        sa.Column("from_ccy", sa.String(3), nullable=False),
        sa.Column("to_ccy", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "source", sa.String(50), nullable=False, server_default="tcmb",
            comment="Rate data source: tcmb | ecb | manual",
        ),
        sa.UniqueConstraint(
            "date_key", "from_ccy", "to_ccy", name="uq_rate_date_pair"
        ),
    )
    op.create_index("ix_dim_currency_rate_date_key", "dim_currency_rate", ["date_key"])

    op.create_table(
        "dim_campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "channel_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_channel.id"), nullable=False,
        ),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_dim_campaign_tenant", "dim_campaign", ["tenant_id"])

    op.create_table(
        "dim_adset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "campaign_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_campaign.id"), nullable=False,
        ),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_dim_adset_tenant", "dim_adset", ["tenant_id"])

    op.create_table(
        "dim_ad",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "ad_set_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_adset.id"), nullable=False,
        ),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_dim_ad_tenant", "dim_ad", ["tenant_id"])

    # ── Fact table ────────────────────────────────────────────────────────

    op.create_table(
        "fact_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "connected_account_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_channel.id"), nullable=False,
        ),
        sa.Column(
            "campaign_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_campaign.id"), nullable=False,
        ),
        sa.Column(
            "adset_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_adset.id"), nullable=False,
        ),
        sa.Column(
            "ad_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dim_ad.id"), nullable=False,
        ),
        sa.Column("date_key", sa.Date, sa.ForeignKey("dim_date.date_key"), nullable=False),
        sa.Column("impressions", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "cost_raw", sa.Numeric(20, 6), nullable=False, server_default="0",
            comment="Spend in source currency (cost_ccy)",
        ),
        sa.Column("cost_ccy", sa.String(3), nullable=False,
                  comment="ISO 4217 source currency"),
        sa.Column("conversions", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column(
            "conversion_value_raw", sa.Numeric(20, 6), nullable=False,
            server_default="0",
            comment="Conversion value in source currency",
        ),
        sa.Column(
            "conversion_value_ccy", sa.String(3), nullable=False,
            comment="ISO 4217 source currency for conv value",
        ),
        sa.Column(
            "cost_base_ccy", sa.Numeric(20, 6), nullable=False, server_default="0",
            comment="cost_raw converted to tenant base_currency",
        ),
        sa.Column(
            "conv_value_base_ccy", sa.Numeric(20, 6), nullable=False,
            server_default="0",
            comment="conversion_value_raw converted to tenant base_currency",
        ),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False,
            comment="Wall-clock UTC time this row was written by the ETL worker",
        ),
        sa.UniqueConstraint(
            "tenant_id", "connected_account_id", "channel_id",
            "campaign_id", "adset_id", "ad_id", "date_key",
            name="uq_fact_daily_grain",
        ),
    )
    op.create_index(
        "ix_fact_tenant_date", "fact_daily_metrics", ["tenant_id", "date_key"]
    )
    op.create_index(
        "ix_fact_tenant_channel_date",
        "fact_daily_metrics",
        ["tenant_id", "channel_id", "date_key"],
    )


def downgrade() -> None:
    op.drop_table("fact_daily_metrics")
    op.drop_table("dim_ad")
    op.drop_table("dim_adset")
    op.drop_table("dim_campaign")
    op.drop_table("dim_currency_rate")
    op.drop_table("dim_date")
    op.drop_table("dim_channel")
    op.drop_table("connected_accounts")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")

    op.execute("DROP TYPE IF EXISTS sync_status")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute("DROP TYPE IF EXISTS membership_role")
