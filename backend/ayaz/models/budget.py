"""Aylık Bütçe Planlayıcı (Monthly Budget Planner) — M12 data model.

BudgetPlan
----------
A tenant-scoped record that captures the user's next-month total budget,
their optimisation objective, and the computed channel/campaign allocation
snapshot.  Plans start as "draft", can be promoted to "active", and
eventually "archived".

objective values
----------------
"balanced"              – balance historical spend share with ROAS performance
"maximize_roas"         – tilt allocation toward highest-ROAS channels
"maximize_conversions"  – favour channels with the lowest CPA

status values
-------------
"draft"     – just created; allocation may or may not have been run
"active"    – the plan currently being executed
"archived"  – superseded or historical plan; read-only by convention

allocations (JSON)
------------------
Snapshot of the ``allocate_budget`` return value at the time of creation or
last recompute.  Stored as-is so the frontend can render without re-running
the algorithm.  NULL until the allocation has been computed.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import GUID as UUID
from ayaz.models.base import Base, TimestampMixin, uuid_pk


# ── Value-set constants (enforced at the Pydantic/service layer) ──────────────

VALID_OBJECTIVES: frozenset[str] = frozenset(
    {"balanced", "maximize_roas", "maximize_conversions"}
)

VALID_STATUSES: frozenset[str] = frozenset({"draft", "active", "archived"})


# ── Model ─────────────────────────────────────────────────────────────────────


class BudgetPlan(Base, TimestampMixin):
    """Monthly budget plan with channel/campaign allocation snapshot.

    Columns
    -------
    id              – UUID primary key
    tenant_id       – RLS: filter by current_setting('app.tenant_id')
    name            – Human-readable label (e.g. "Temmuz 2026 Planı")
    period_month    – "YYYY-MM" string (e.g. "2026-07")
    total_budget    – Total TRY/USD/... budget to distribute
    currency        – ISO 4217 currency code (default TRY)
    objective       – Optimisation objective (balanced | maximize_roas | maximize_conversions)
    lookback_days   – Historical window for metric aggregation (default 90)
    allocations     – JSON snapshot of the last computed allocation result
    status          – Plan lifecycle state (draft | active | archived)
    created_at      – Auto-managed by TimestampMixin
    updated_at      – Auto-managed by TimestampMixin
    """

    __tablename__ = "budget_plans"
    __table_args__ = (
        Index("ix_budget_plans_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Human-readable plan label",
    )

    # "YYYY-MM" — e.g. "2026-07"; validated by the Pydantic layer
    period_month: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        comment="Target month in YYYY-MM format",
    )

    total_budget: Mapped[sa.Numeric] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=0,
        comment="Total budget to allocate across all channels",
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="TRY",
        server_default="'TRY'",
        comment="ISO 4217 currency code",
    )

    # "balanced" | "maximize_roas" | "maximize_conversions"
    objective: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="balanced",
        server_default="'balanced'",
        comment="balanced | maximize_roas | maximize_conversions",
    )

    lookback_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=90,
        server_default="90",
        comment="Days of historical data used for the allocation algorithm",
    )

    # JSON snapshot of the allocate_budget() return value; NULL until computed
    allocations: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Serialised allocation result snapshot (None until first compute)",
    )

    # "draft" | "active" | "archived"
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="'draft'",
        comment="draft | active | archived",
    )

    def __repr__(self) -> str:
        return (
            f"<BudgetPlan id={self.id} name={self.name!r}"
            f" period={self.period_month} tenant={self.tenant_id}>"
        )
