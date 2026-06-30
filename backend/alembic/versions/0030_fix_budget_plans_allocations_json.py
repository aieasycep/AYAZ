"""Fix budget_plans.allocations column type: Text -> JSON.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-30

Bug
---
``0023_budget_plans.py`` mistakenly declared ``allocations`` as ``sa.Text()``
while every other JSON-shaped column in this codebase (and the
``BudgetPlan.allocations`` ORM mapping itself) uses ``sa.JSON``. Every other
table with a JSON-shaped column in this codebase follows the ``sa.JSON``
pattern (see ``insights.data``, ``automation_rules.action_config``,
``briefings.body``, etc.) — ``budget_plans`` is the only outlier.

Symptom
-------
SQLAlchemy's ``JSON`` Python type round-trips on top of a Postgres ``text``
column by always serialising on write but Postgres returns the raw text
string, not a parsed object, on plain text columns. The API's strict
Pydantic ``BudgetPlanResponse`` (``allocations: dict[str, Any] | None``)
then fails validation with a 500 the moment any plan is read back —
breaking ``GET /budget/plans``, ``GET /budget/plans/{id}``, and any mutation
endpoint that returns the updated row. Service-layer callers that defensively
check ``isinstance(plan.allocations, dict)`` (``copilot_tools._get_budget_status``,
``budget_planner.plan_actuals``) degraded silently instead of crashing, which
is how this slipped past those code paths.

Fix
---
Alter the column to a real ``json`` type in Postgres, converting existing
double-encoded text rows via ``USING allocations::json``. NULL values pass
through unchanged. SQLite has no distinct JSON column type (TEXT affinity is
used either way and SQLAlchemy's JSON type handles the serialisation in
Python), so the ``alter_column`` is skipped there — this mirrors how SQLite
test fixtures already build the correct schema directly from
``Base.metadata.create_all`` and never hit this bug.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "budget_plans",
            "allocations",
            type_=sa.JSON(),
            existing_type=sa.Text(),
            postgresql_using="allocations::json",
            existing_nullable=True,
        )
    # SQLite: TEXT affinity already backs sa.JSON; no-op (and ALTER COLUMN TYPE
    # is not supported without a full table rebuild, which is unnecessary here).


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "budget_plans",
            "allocations",
            type_=sa.Text(),
            existing_type=sa.JSON(),
            postgresql_using="allocations::text",
            existing_nullable=True,
        )
