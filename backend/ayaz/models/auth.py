"""Auth models — JWT revocation table.

Design notes
------------
* ``revoked_tokens`` stores the ``jti`` (JWT ID) of every explicitly revoked
  access token.  Tokens are rejected at the dependency layer
  (``ayaz/api/deps.py``) if their ``jti`` appears in this table.
* ``tenant_id`` is nullable — a token carries a tenant context but is revoked
  globally (regardless of which tenant it was scoped to).
* No Postgres ENUM types — all categorical data stored as String.
* Cleanup of expired jtis is handled by ``ayaz.services.auth.cleanup_revoked_tokens``.
  Call this periodically (e.g. nightly cron or Celery beat).  Without cleanup the
  table grows by one row per logout, but each row is tiny (~100 bytes).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import Base, uuid_pk


class RevokedToken(Base):
    """One row per revoked JWT access token.

    Primary key is the token's ``jti`` (a UUID string) so lookups are O(1)
    index scans and duplicate-revoke is a no-op (upsert by PK).
    """

    __tablename__ = "revoked_tokens"

    # jti is used as the primary key — already unique by design (uuid4 per token)
    jti: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        nullable=False,
        comment="JWT ID claim (uuid4 string) — used to identify a specific token",
    )

    # tenant_id is nullable — revocation is global, not per-tenant
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Tenant the token was scoped to (nullable; revocation is global)",
    )

    # ISO-8601 UTC datetime when the token was revoked (as Text for SQLite compat)
    revoked_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="ISO-8601 UTC datetime when the token was added to the deny-list",
    )

    # Store the original expiry so the cleanup job can drop stale rows without
    # decoding the (already-invalid) token.
    expires_at: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="ISO-8601 UTC datetime when the token would have naturally expired",
    )

    def __repr__(self) -> str:
        return (
            f"<RevokedToken jti={self.jti!r} tenant={self.tenant_id}"
            f" revoked_at={self.revoked_at!r}>"
        )
