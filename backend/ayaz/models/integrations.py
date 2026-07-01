"""ORM models for the Integration layer.

Tables (Alembic 0027):
- ``provider_grants``        — one OAuth grant = one Vault entry; shared by
                               multiple IntegrationConnection rows (bundle model)
- ``integration_connections`` — per-tenant integration instance; tracks
                                lifecycle, scopes, sync watermark
- ``integration_requests``   — "Yakında" demand signal from catalog cards

Table (Alembic 0028):
- ``action_audit_log``       — every WRITE action recorded (ADR-8)

These tables are intentionally separate from ``connected_accounts`` (which
powers the ad/analytics sync engine via ``Platform`` enum and ``SyncStatus``).
Do NOT remove or modify ``connected_accounts``; it stays in ``oltp.py``.

Multi-tenancy
-------------
Every table carries ``tenant_id FK→tenants.id`` (RLS-ready pattern matching
all other tenant-scoped models in oltp.py).  Every query filtering on
tenant_id is the caller's responsibility until Postgres RLS policies are
activated (see oltp.py module docstring for the convention).

Status vocabulary
-----------------
``IntegrationConnection.status`` uses ``IntegrationStatus`` string enum from
``ayaz.integrations.base`` — the canonical vocabulary replacing the
``idle/success`` → ``connected/pending`` mask in ``connectors-api.ts``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base, GUID as UUID_TYPE, TimestampMixin, uuid_pk


class ProviderGrant(Base, TimestampMixin):
    """One OAuth grant record = one Vault entry.

    A single OAuth consent flow may produce a grant that is shared across
    multiple ``IntegrationConnection`` rows (e.g. a Google Workspace consent
    grants access to Google Ads + GA4 + Search Console — all three point at
    the same ``ProviderGrant``).

    Security notes
    --------------
    - ``vault_secret_ref`` stores the Fernet-encrypted token blob *reference*
      — the format is ``enc:<ciphertext>`` matching ``EncryptedColumnVault``.
      Raw tokens are NEVER stored in this column.
    - ``provider_user_email`` is the account email from the OAuth ``id_token``
      or ``userinfo`` endpoint — stored for transparency/audit, not auth.
    """

    __tablename__ = "provider_grants"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="OAuth provider key, e.g. google_workspace | meta | slack | tiktok",
    )
    vault_secret_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="Fernet-encrypted token blob (enc:…) — never store raw tokens here",
    )
    provider_user_email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
        comment="Provider account email from OAuth id_token / userinfo (transparency)",
    )
    scopes: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment="List of OAuth scopes granted by the user",
    )
    access_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC expiry of the access token; NULL for non-expiring tokens",
    )
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who performed the OAuth flow",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        server_default="active",
        comment="active | reauth_required | revoked",
    )

    # Relationships
    connections: Mapped[list["IntegrationConnection"]] = relationship(
        back_populates="provider_grant",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderGrant id={self.id} provider={self.provider!r}"
            f" tenant={self.tenant_id} status={self.status!r}>"
        )


class IntegrationConnection(Base, TimestampMixin):
    """A tenant's connected integration instance.

    One row per (tenant, integration_key, external_entity_id) — the unique
    constraint enforces this.  A single ``ProviderGrant`` may be referenced
    by multiple connections (bundle model: Google Workspace → Ads + GA4 + SC).

    Status field
    ------------
    ``status`` uses the canonical ``IntegrationStatus`` vocabulary from
    ``ayaz.integrations.base``.  Valid values:

        connected        — active, healthy
        connecting       — OAuth flow in progress
        syncing          — sync job running
        needs_reconnect  — token expired/revoked, user action required
        error            — non-auth failure
        disconnected     — manually removed or never connected

    This replaces the ``idle/success`` → ``pending/connected`` transformation
    previously masked by ``connectors-api.ts`` frontend code.

    Scopes field
    ------------
    ``scopes`` stores the subset of the grant's scopes that apply to THIS
    specific integration (a bundle grant may have 6 scopes; a GA4 connection
    only uses the analytics.readonly subset).
    """

    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "integration_key",
            "external_entity_id",
            name="uq_integration_connections_tenant_key_entity",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    integration_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Integration key matching IntegrationMetadata.key, e.g. google_ads | slack",
    )
    provider_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("provider_grants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to ProviderGrant; NULL for api_key integrations before credential validation",
    )
    external_entity_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        server_default="",
        comment="Platform-specific account/channel/property ID selected during discover()",
    )
    display_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        server_default="",
        comment="Human-readable label for this connection, e.g. account/channel name",
    )
    capabilities: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment='Capabilities active for this connection: ["read"] | ["action"] | ["read","action"]',
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="disconnected",
        server_default="disconnected",
        comment=(
            "IntegrationStatus: connected | connecting | syncing | "
            "needs_reconnect | error | disconnected"
        ),
    )
    scopes: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment="OAuth scopes active for this connection (subset of the grant's scopes)",
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp of the last successful data sync",
    )
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp of the last health-check probe",
    )
    watermark: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Incremental sync cursor — ISO-8601 datetime or platform-specific string. "
            "Compatible with ConnectedAccount.watermark for read integrations."
        ),
    )
    extra_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Adapter-specific metadata (e.g. selected account_id, channel_id)",
    )

    # Relationships
    provider_grant: Mapped["ProviderGrant | None"] = relationship(
        back_populates="connections",
    )

    def __repr__(self) -> str:
        return (
            f"<IntegrationConnection id={self.id}"
            f" key={self.integration_key!r}"
            f" tenant={self.tenant_id}"
            f" status={self.status!r}>"
        )


class IntegrationRequest(Base, TimestampMixin):
    """Demand signal from a "Yakında" (Coming Soon) integration card.

    When a user clicks "Haber ver" on a coming-soon integration, a row is
    created here.  The product team queries this table to prioritize which
    integrations to implement next (design §3.2, catalog demand signal).
    """

    __tablename__ = "integration_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    integration_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="The coming-soon integration key the user requested",
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who clicked 'Haber ver'",
    )

    def __repr__(self) -> str:
        return (
            f"<IntegrationRequest id={self.id}"
            f" key={self.integration_key!r}"
            f" tenant={self.tenant_id}>"
        )


class ActionAuditLog(Base):
    """Immutable audit log for every WRITE action executed through the Integration layer.

    ADR-8: Every write action is recorded here regardless of outcome (ok/error/denied).
    This table is append-only — no ``updated_at`` column; rows are never mutated.

    Columns
    -------
    id               : UUID primary key.
    tenant_id        : Tenant that owns the action (RLS).
    integration_key  : Integration key (e.g. "slack", "google_sheets").
    action_name      : Tool name (e.g. "slack_send_message").
    params_summary   : JSON dict of action arguments with PII/secrets redacted.
    status           : "ok" | "error" | "denied".
    error            : Error message when status="error"; NULL otherwise.
    actor_user_id    : User who triggered the action (NULL for automation).
    was_auto         : True when triggered by an automation rule (not direct user).
    created_at       : Immutable insertion timestamp (server-side).
    """

    __tablename__ = "action_audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    integration_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Integration key, e.g. slack | google_sheets | gmail",
    )
    action_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Tool name, e.g. slack_send_message",
    )
    params_summary: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Action arguments with PII/secrets redacted — never store raw tokens",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="ok | error | denied",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message when status=error; NULL for ok/denied",
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who triggered the action; NULL for automation-triggered actions",
    )
    was_auto: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when triggered by an automation rule, False for direct user action",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
        index=True,
        comment="Immutable insertion timestamp — never updated",
    )

    def __repr__(self) -> str:
        return (
            f"<ActionAuditLog id={self.id}"
            f" action={self.action_name!r}"
            f" status={self.status!r}"
            f" tenant={self.tenant_id}>"
        )
