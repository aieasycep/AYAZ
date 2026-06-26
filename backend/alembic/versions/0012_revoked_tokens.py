"""Revoked JWT tokens deny-list (JWT revocation / logout support).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-26

Notes
-----
* ``revoked_tokens`` stores the ``jti`` (JWT ID claim) of every revoked access
  token.  Tokens whose ``jti`` appears here are rejected by the auth dependency
  with HTTP 401 even if they have not yet expired.
* ``jti`` is the primary key — a String(64) holding a UUID4 hex string.  This
  makes duplicate-revoke a no-op (PK uniqueness) and lookups O(1).
* ``tenant_id`` is nullable and carries a FK to tenants(id) with CASCADE DELETE.
  Revocation is global (not per-tenant), but storing the tenant enables targeted
  cleanup when a tenant is deleted.
* No Postgres ENUM types — all values stored as String (SQLite compatible).
* ``expires_at`` allows the periodic cleanup job to delete rows for tokens that
  have already naturally expired, keeping the table small.

Table
-----
revoked_tokens — one row per revoked JWT (jti → deny-list entry).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column(
            "jti",
            sa.String(64),
            primary_key=True,
            nullable=False,
            comment="JWT ID claim (uuid4 string) — deny-list primary key",
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
            comment="Tenant the token was scoped to (nullable; revocation is global)",
        ),
        sa.Column(
            "revoked_at",
            sa.String(40),
            nullable=False,
            comment="ISO-8601 UTC datetime of revocation",
        ),
        sa.Column(
            "expires_at",
            sa.String(40),
            nullable=True,
            comment="ISO-8601 UTC datetime when the token would have naturally expired",
        ),
    )

    # Index for cleanup queries: find all rows whose token has already expired
    op.create_index(
        "ix_revoked_tokens_expires_at",
        "revoked_tokens",
        ["expires_at"],
    )

    # Index for tenant-scoped cleanup (e.g. on tenant deletion before CASCADE fires)
    op.create_index(
        "ix_revoked_tokens_tenant_id",
        "revoked_tokens",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_tenant_id", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
