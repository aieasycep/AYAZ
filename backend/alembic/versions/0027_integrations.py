"""Entegrasyon & Aksiyon Merkezi — Wave 1 foundation tables.

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-30

Creates three new tables for the unified integration layer (design §7.1):

  provider_grants         — one OAuth grant = one Vault record; shared by
                            multiple IntegrationConnection rows (bundle model)
  integration_connections — per-tenant integration instance; status uses the
                            canonical IntegrationStatus vocabulary
  integration_requests    — "Yakında" demand signal from catalog cards

The existing ``connected_accounts`` table (ad/analytics sync engine) is NOT
modified.

UUID columns use ``postgresql.UUID(as_uuid=True)`` as required for native
Postgres UUID type (the GUID TypeDecorator renders this type on Postgres).
FKs to ``tenants.id`` and ``users.id`` use the same type.

server_default values for JSON columns use bare string literals (no inner
quotes): ``server_default="[]"`` and ``server_default="{}"`` — NOT the
``sa.text("'[]'")`` form which inserts SQL-string literal with single quotes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── provider_grants ───────────────────────────────────────────────────
    op.create_table(
        "provider_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "provider",
            sa.String(100),
            nullable=False,
            comment="OAuth provider key, e.g. google_workspace | meta | slack | tiktok",
        ),
        sa.Column(
            "vault_secret_ref",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="Fernet-encrypted token blob (enc:…) — never store raw tokens here",
        ),
        sa.Column(
            "provider_user_email",
            sa.String(254),
            nullable=True,
            comment="Provider account email from OAuth id_token / userinfo (transparency)",
        ),
        sa.Column(
            "scopes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment="List of OAuth scopes granted by the user",
        ),
        sa.Column(
            "access_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC expiry of the access token; NULL for non-expiring tokens",
        ),
        sa.Column(
            "connected_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User who performed the OAuth flow",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="active",
            comment="active | reauth_required | revoked",
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_grants_tenant_id",
        "provider_grants",
        ["tenant_id"],
        unique=False,
    )

    # ── integration_connections ───────────────────────────────────────────
    op.create_table(
        "integration_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "integration_key",
            sa.String(100),
            nullable=False,
            comment="Integration key matching IntegrationMetadata.key, e.g. google_ads | slack",
        ),
        sa.Column(
            "provider_grant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                "FK to ProviderGrant; NULL for api_key integrations before "
                "credential validation"
            ),
        ),
        sa.Column(
            "external_entity_id",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="Platform-specific account/channel/property ID selected during discover()",
        ),
        sa.Column(
            "display_name",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="Human-readable label for this connection, e.g. account/channel name",
        ),
        sa.Column(
            "capabilities",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment='Capabilities active for this connection: ["read"] | ["action"] | ["read","action"]',
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="disconnected",
            comment=(
                "IntegrationStatus: connected | connecting | syncing | "
                "needs_reconnect | error | disconnected"
            ),
        ),
        sa.Column(
            "scopes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment="OAuth scopes active for this connection (subset of the grant's scopes)",
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp of the last successful data sync",
        ),
        sa.Column(
            "last_health_check",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp of the last health-check probe",
        ),
        sa.Column(
            "watermark",
            sa.Text(),
            nullable=True,
            comment=(
                "Incremental sync cursor — ISO-8601 datetime or platform-specific string. "
                "Compatible with ConnectedAccount.watermark for read integrations."
            ),
        ),
        sa.Column(
            "extra_metadata",
            sa.JSON(),
            nullable=False,
            server_default="{}",
            comment="Adapter-specific metadata (e.g. selected account_id, channel_id)",
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_grant_id"],
            ["provider_grants.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "integration_key",
            "external_entity_id",
            name="uq_integration_connections_tenant_key_entity",
        ),
    )
    op.create_index(
        "ix_integration_connections_tenant_id",
        "integration_connections",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_connections_provider_grant_id",
        "integration_connections",
        ["provider_grant_id"],
        unique=False,
    )

    # ── integration_requests ──────────────────────────────────────────────
    op.create_table(
        "integration_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "integration_key",
            sa.String(100),
            nullable=False,
            comment="The coming-soon integration key the user requested",
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User who clicked 'Haber ver'",
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_requests_tenant_id",
        "integration_requests",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop in reverse creation order (foreign-key dependency)
    op.drop_index(
        "ix_integration_requests_tenant_id",
        table_name="integration_requests",
    )
    op.drop_table("integration_requests")

    op.drop_index(
        "ix_integration_connections_provider_grant_id",
        table_name="integration_connections",
    )
    op.drop_index(
        "ix_integration_connections_tenant_id",
        table_name="integration_connections",
    )
    op.drop_table("integration_connections")

    op.drop_index(
        "ix_provider_grants_tenant_id",
        table_name="provider_grants",
    )
    op.drop_table("provider_grants")
