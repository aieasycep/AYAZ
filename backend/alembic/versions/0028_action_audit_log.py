"""action_audit_log table — Wave 3 ADR-8 audit trail.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-30

Creates one new table:

  action_audit_log  — immutable write-action audit trail.  Every integration
                      action (ok / error / denied) is logged here.  The table
                      is append-only; rows are never updated (no updated_at).

UUID columns use ``postgresql.UUID(as_uuid=True)`` for native Postgres UUID
type (the GUID TypeDecorator renders this on Postgres).  FKs to tenants.id and
users.id use the same type.

server_default values:
  - JSON columns: ``server_default="{}"``     (bare string, no inner quotes)
  - bool columns: ``server_default="false"``  (bare string, no inner quotes)
  - created_at:   ``server_default=sa.func.now()``
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_audit_log",
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
            comment="Integration key, e.g. slack | google_sheets | gmail",
        ),
        sa.Column(
            "action_name",
            sa.String(200),
            nullable=False,
            comment="Tool name, e.g. slack_send_message",
        ),
        sa.Column(
            "params_summary",
            sa.JSON(),
            nullable=False,
            server_default="{}",
            comment="Action arguments with PII/secrets redacted",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            comment="ok | error | denied",
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
            comment="Error message when status=error; NULL for ok/denied",
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User who triggered the action; NULL for automation-triggered",
        ),
        sa.Column(
            "was_auto",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True when triggered by automation rule, False for direct user action",
        ),
        sa.Column(
            "created_at",
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
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_audit_log_tenant_id",
        "action_audit_log",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_action_audit_log_created_at",
        "action_audit_log",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_action_audit_log_created_at", table_name="action_audit_log")
    op.drop_index("ix_action_audit_log_tenant_id", table_name="action_audit_log")
    op.drop_table("action_audit_log")
