"""OLTP models: tenancy, users, RBAC, and connected accounts.

Multi-tenancy strategy
----------------------
* Every tenant-scoped table carries a ``tenant_id`` foreign-key column.
* Postgres Row-Level Security (RLS) is the *intended* isolation mechanism.
  RLS policies are NOT written here (Faz 1 infrastructure task) but the schema
  is structured so they can be added with ``ALTER TABLE … ENABLE ROW LEVEL
  SECURITY`` + a policy matching ``current_setting('app.tenant_id')``.
* Until RLS policies are active every query MUST explicitly filter on
  ``tenant_id`` — enforced by the ``TenantContext`` FastAPI dependency.
  See ``ayaz/api/deps.py`` for the TODO comment.
"""

import enum
import uuid

from sqlalchemy import (
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base, TimestampMixin, uuid_pk


class MembershipRole(str, enum.Enum):
    """RBAC roles within a tenant organisation."""

    owner = "owner"
    admin = "admin"
    member = "member"


class Platform(str, enum.Enum):
    """Supported ad / analytics platforms (grow this list in Faz 1+)."""

    google_ads = "google_ads"
    meta_ads = "meta_ads"
    ga4 = "ga4"
    search_console = "search_console"
    tiktok_ads = "tiktok_ads"
    linkedin_ads = "linkedin_ads"
    microsoft_ads = "microsoft_ads"
    # TODO (Faz 3): Criteo, Pinterest, …
    sample = "sample"  # used by the SampleConnector in tests


class SyncStatus(str, enum.Enum):
    """Lifecycle of a connected-account sync job."""

    idle = "idle"
    syncing = "syncing"
    success = "success"
    error = "error"
    paused = "paused"


class Tenant(Base, TimestampMixin):
    """Organisation / workspace — the root multi-tenant boundary.

    Isolation note: all child rows reference this via ``tenant_id``.
    Postgres RLS policies will match ``current_setting('app.tenant_id')``
    against this primary key. (TODO: Faz 1 infra — write the RLS policies.)
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="TR", comment="ISO 3166-1 alpha-2"
    )
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="TRY", comment="ISO 4217"
    )
    kvkk_region: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="TR",
        comment="Data residency region for KVKK compliance",
    )

    # Relationships
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    connected_accounts: Mapped[list["ConnectedAccount"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} name={self.name!r}>"


class User(Base, TimestampMixin):
    """Platform user account (cross-tenant — one user may belong to many orgs).

    Passwords are stored as bcrypt hashes via passlib.
    Plain-text passwords are NEVER stored or logged.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(
        String(254), nullable=False, unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Relationships
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class Membership(Base, TimestampMixin):
    """Join table: User ↔ Tenant with an RBAC role.

    A user with the ``owner`` role has full control over the tenant.
    ``admin`` can manage connected accounts and members.
    ``member`` has read-only access (exact permission matrix: TODO Faz 1).
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role"),
        nullable=False,
        default=MembershipRole.member,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="memberships")
    tenant: Mapped["Tenant"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"<Membership user={self.user_id} tenant={self.tenant_id}"
            f" role={self.role}>"
        )


class ConnectedAccount(Base, TimestampMixin):
    """An external ad/analytics account linked to a tenant.

    Security note
    -------------
    ``vault_secret_ref`` is a *path* inside HashiCorp Vault (e.g.
    ``secret/data/tenants/<tenant_id>/google_ads/<account_id>``).
    The actual OAuth tokens / API keys are NEVER stored in this table —
    they live in Vault with envelope encryption and audit logging.
    (TODO Faz 1: implement VaultClient.read/write in ayaz/services/vault.py)
    """

    __tablename__ = "connected_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform"),
        nullable=False,
    )
    external_account_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Platform-specific account identifier (e.g. Google customer ID)",
    )
    display_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    vault_secret_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Vault path to OAuth tokens — never store tokens in this column",
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"),
        nullable=False,
        default=SyncStatus.idle,
    )
    watermark: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 datetime of the last successful incremental sync",
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="connected_accounts")

    def __repr__(self) -> str:
        return (
            f"<ConnectedAccount id={self.id} platform={self.platform}"
            f" tenant={self.tenant_id}>"
        )
