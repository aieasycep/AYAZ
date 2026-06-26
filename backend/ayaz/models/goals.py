"""Goal Tracking ORM model.

Design notes
------------
* All enum-like columns use ``sa.String`` — no Postgres ENUM types, keeping
  SQLite compatibility for tests.
* ``tenant_id`` is on every row; every query MUST filter by it explicitly
  until Postgres RLS policies are active.
* ``channel_filter`` is nullable: NULL means "all channels"; a non-null value
  restricts progress queries to rows whose ``dim_channel.key`` matches.
* ``period`` is fixed to "month" for the initial implementation.  The column is
  retained as a String so future period types ("week", "quarter") can be added
  without a schema change.
* ``period_start`` / ``period_end`` are stored as ISO-8601 text (YYYY-MM-DD)
  for full SQLite compatibility; the service layer parses them to ``date``.

Metric values supported
-----------------------
    spend            — total effective spend over the period
    roas             — conversion_value / spend (ratio metric)
    conversions      — total conversions (additive)
    conversion_value — total conversion value (additive)
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import Base, TimestampMixin, uuid_pk


class Goal(Base, TimestampMixin):
    """A marketer-defined performance target for a specific metric and period.

    Attributes
    ----------
    id:
        UUID primary key.
    tenant_id:
        Tenant this goal belongs to (used for isolation on every query).
    name:
        Human-readable label, e.g. "March ROAS Target".
    metric:
        The KPI being targeted. One of: ``spend``, ``roas``, ``conversions``,
        ``conversion_value``.  Stored as a plain String (no PG ENUM).
    target_value:
        The numeric goal value for the period.
    period:
        Granularity string.  Currently only ``"month"`` is supported; stored
        as String so additional values can be added without migration.
    period_start:
        ISO-8601 date string (YYYY-MM-DD) for the first day of the tracking
        window (inclusive).
    period_end:
        ISO-8601 date string (YYYY-MM-DD) for the last day of the tracking
        window (inclusive).
    channel_filter:
        When set, restricts the metric query to rows whose ``dim_channel.key``
        equals this value.  NULL means all channels are aggregated.
    is_active:
        Soft-disable flag; inactive goals are excluded from list endpoints by
        default but can be retrieved explicitly.
    created_at / updated_at:
        Supplied by ``TimestampMixin``.
    """

    __tablename__ = "goals"
    __table_args__ = (
        Index("ix_goals_tenant_id", "tenant_id"),
        Index("ix_goals_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Tenant that owns this goal (RLS: filter on every query)",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable goal name",
    )

    metric: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="spend | roas | conversions | conversion_value",
    )

    target_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="The numeric target for this goal",
    )

    period: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="month",
        comment="Tracking period grain: month (only value for now)",
    )

    period_start: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Inclusive start date as ISO-8601 text (YYYY-MM-DD)",
    )

    period_end: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Inclusive end date as ISO-8601 text (YYYY-MM-DD)",
    )

    channel_filter: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment=(
            "dim_channel.key to restrict the metric query to. "
            "NULL = all channels aggregated."
        ),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Soft-disable flag; False = hidden from default list views",
    )

    def __repr__(self) -> str:
        return (
            f"<Goal id={self.id} name={self.name!r} metric={self.metric!r}"
            f" target={self.target_value} period={self.period_start}/{self.period_end}>"
        )
