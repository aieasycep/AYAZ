"""Insights & Alerts data model — M4.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as oltp.py).

Type/status columns
-------------------
All type and status fields use ``sa.String`` (via Mapped[str]) to avoid the
duplicate-type migration bug documented in 0001_initial_schema.py.
Allowed values are enforced at the Pydantic/service layer.

Insight
-------
A single actionable finding produced by the detection engine for one tenant.
Severity and category are plain strings so new values can be added without
a schema migration.

AlertRule
---------
A tenant-configured rule that triggers delivery (email/Slack) when the
detection engine produces a matching critical insight.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import Base, TimestampMixin, uuid_pk


# ── Insight ───────────────────────────────────────────────────────────────────


class Insight(Base, TimestampMixin):
    """One actionable finding produced by the AI / rule-based detection engine.

    category values (not exhaustive — new categories can be added freely)
    -----------------------------------------------------------------------
    "roas_drop"         – ROAS fell significantly vs prior period
    "spend_spike"       – Spend jumped beyond threshold
    "zero_conversions"  – Spend > 0 but conversions == 0
    "ctr_drop"          – CTR fell significantly vs prior period
    "budget_pacing"     – Spend pace implies over/under-delivery
    "anomaly"           – Statistical anomaly (z-score / moving-average)
    "cpc_rise"          – CPC rose significantly vs prior period

    severity values
    ---------------
    "info"     – notable but not urgent
    "warning"  – warrants attention today
    "critical" – immediate action required

    status values
    -------------
    "new"       – just generated, not yet seen by the user
    "seen"      – user opened / acknowledged
    "dismissed" – user chose to ignore

    entity_type values (nullable)
    -----------------------------
    "campaign" | "adset" | "ad" | "channel" | None
    """

    __tablename__ = "insights"
    __table_args__ = (
        Index("ix_insights_tenant_id", "tenant_id"),
        Index("ix_insights_tenant_status", "tenant_id", "status"),
        Index("ix_insights_tenant_severity", "tenant_id", "severity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    # ── Classification ────────────────────────────────────────────────────
    # "roas_drop" | "spend_spike" | "zero_conversions" | "ctr_drop"
    # | "budget_pacing" | "anomaly" | "cpc_rise"
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # "info" | "warning" | "critical"
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="info"
    )

    # ── Narrative (Turkish) ───────────────────────────────────────────────
    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        comment="Short Turkish headline — 'ne oldu'",
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Turkish narrative with recommendation — 'neden / ne yapmalı'",
    )

    # ── Context ───────────────────────────────────────────────────────────
    # Which metric triggered this insight
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    # Which channel (nullable — may be cross-channel)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Entity that owns this insight (e.g. a specific campaign)
    entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="'campaign' | 'adset' | 'ad' | 'channel'"
    )
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # ── Time window that was analysed ─────────────────────────────────────
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    # "new" | "seen" | "dismissed"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new"
    )

    # ── Ranking ───────────────────────────────────────────────────────────
    score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Higher score = higher dashboard priority"
    )


    # ── User feedback (closed feedback loop) ───────────────────────────────
    # Set when the marketer clicks "Mark as Applied" on the recommendation card.
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="UTC timestamp when the user marked this recommendation as applied; null = not applied",
    )
    # Thumbs feedback: 'up' | 'down' | null
    reaction: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        default=None,
        comment="User reaction: 'up' | 'down' | null",
    )
    # ── Machine-readable details ──────────────────────────────────────────
    # Stores raw values, deltas, thresholds used by the detector.
    # Schema varies by category; consumers should treat it as opaque.
    data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Detector output: values, deltas, z-scores, etc.",
    )

    def __repr__(self) -> str:
        return (
            f"<Insight id={self.id} category={self.category!r}"
            f" severity={self.severity!r} tenant={self.tenant_id}>"
        )


# ── AlertRule ─────────────────────────────────────────────────────────────────


class AlertRule(Base, TimestampMixin):
    """A tenant-configured rule that triggers a delivery when matched.

    comparator values
    -----------------
    "pct_drop"  – metric fell by >= threshold % vs prior period
    "pct_rise"  – metric rose by >= threshold % vs prior period
    "below"     – metric absolute value falls below threshold
    "above"     – metric absolute value exceeds threshold
    "anomaly"   – any statistical anomaly detected for the metric

    delivery values
    ---------------
    "email"  – send an email to ``destination``
    "slack"  – POST to the Slack webhook URL in ``destination``
    "none"   – record only; no external delivery

    channel_filter
    --------------
    Optional string matching ``DimChannel.key`` (e.g. "google_ads").
    When set, the rule only fires for insights on that channel.
    When None, the rule fires for any channel.
    """

    __tablename__ = "alert_rules"
    __table_args__ = (
        Index("ix_alert_rules_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Which metric this rule watches (e.g. "roas", "spend", "ctr", "cpc")
    metric: Mapped[str] = mapped_column(String(50), nullable=False)

    # "pct_drop" | "pct_rise" | "below" | "above" | "anomaly"
    comparator: Mapped[str] = mapped_column(String(20), nullable=False)

    # For "pct_drop"/"pct_rise"/"below"/"above" — null for "anomaly"
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional channel scope (matches DimChannel.key)
    channel_filter: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    # "email" | "slack" | "none"
    delivery: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none"
    )

    # Email address or Slack webhook URL; null when delivery == "none"
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return (
            f"<AlertRule id={self.id} name={self.name!r}"
            f" metric={self.metric!r} tenant={self.tenant_id}>"
        )
