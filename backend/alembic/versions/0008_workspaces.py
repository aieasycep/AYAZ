"""Agency / Multi-Workspace + White-label schema — M8.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-26

Notes
-----
* All status/role columns use sa.String to avoid the duplicate-type migration bug
  documented in 0001_initial_schema.py.  Allowed values are validated at the
  application/Pydantic layer.
* ``workspace_invitations.token`` has a UNIQUE constraint (used as the accept-link
  payload).
* ``invited_by`` is nullable (SET NULL on user deletion) so the audit trail is
  preserved even when the inviter account is removed.
* ``accepted_at`` is Text/ISO-8601 for SQLite compatibility, matching the pattern
  used in billing_events.created_at.
* No Postgres ENUM types are used.

Tables / columns changed
------------------------
  tenants                  — adds brand_name, logo_url, primary_color (nullable)
  workspace_invitations    — new table for M8 invite flow
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tenants: white-label branding columns ──────────────────────────────────

    op.add_column(
        "tenants",
        sa.Column(
            "brand_name",
            sa.String(200),
            nullable=True,
            comment="White-label display name override (M8)",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "logo_url",
            sa.Text,
            nullable=True,
            comment="URL of the workspace logo for white-labelling (M8)",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "primary_color",
            sa.String(20),
            nullable=True,
            comment="CSS hex color for white-label branding, e.g. #3A7BFF (M8)",
        ),
    )

    # ── workspace_invitations ──────────────────────────────────────────────────

    op.create_table(
        "workspace_invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="RLS: filter by current_setting('app.tenant_id')",
        ),
        sa.Column(
            "email",
            sa.String(254),
            nullable=False,
            comment="Email address of the invitee",
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="member",
            comment="admin | member — role to assign on acceptance",
        ),
        sa.Column(
            "token",
            sa.String(128),
            nullable=False,
            comment="URL-safe random token for the accept link",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending | accepted | revoked",
        ),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="User who sent the invitation",
        ),
        sa.Column(
            "accepted_at",
            sa.Text,
            nullable=True,
            comment="ISO-8601 UTC datetime when the invitation was accepted",
        ),
        # Timestamps (TimestampMixin equivalent)
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
        "ix_workspace_invitations_tenant_id",
        "workspace_invitations",
        ["tenant_id"],
    )
    op.create_unique_constraint(
        "uq_workspace_invitations_token",
        "workspace_invitations",
        ["token"],
    )
    op.create_index(
        "ix_workspace_invitations_token",
        "workspace_invitations",
        ["token"],
    )


def downgrade() -> None:
    op.drop_table("workspace_invitations")
    op.drop_column("tenants", "primary_color")
    op.drop_column("tenants", "logo_url")
    op.drop_column("tenants", "brand_name")
