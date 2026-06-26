"""Automation & Rules engine data model — M9.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as other model modules).

Type/status columns
-------------------
All type columns use ``sa.String`` to avoid the duplicate-type migration bug.
Allowed values are enforced at the Pydantic/service layer.

AutomationRule
--------------
A tenant-defined rule that watches a metric and fires an action when the
condition is satisfied.  The evaluation is performed by the automation service
on a schedule (Celery beat) or on-demand via the API.

AutomationRun
-------------
Audit log row produced every time a rule is evaluated (whether triggered or not).
Keeps the full evaluation history for debugging and reporting.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import Base, TimestampMixin, uuid_pk


# ── AutomationRule ─────────────────────────────────────────────────────────────


class AutomationRule(Base, TimestampMixin):
    """A tenant-defined rule that evaluates a metric condition and fires an action.

    scope values
    ------------
    "account"   – evaluate across all channels / campaigns
    "channel"   – restrict to one channel (scope_filter = channel key, e.g. "google_ads")
    "campaign"  – restrict to one campaign (scope_filter = campaign UUID string)

    metric values
    -------------
    "spend" | "roas" | "ctr" | "cpc" | "cpa" | "conversions"

    comparator values
    -----------------
    "pct_drop"  – metric fell by >= threshold % vs the prior window
    "pct_rise"  – metric rose by >= threshold % vs the prior window
    "below"     – metric absolute value is below threshold
    "above"     – metric absolute value exceeds threshold
    "anomaly"   – statistical anomaly detected (z-score based, reuses insights detector)

    action values
    -------------
    "alert"          – create an Insight row with Turkish text
    "notify_email"   – route to EmailNotifier stub (no real sending yet)
    "notify_slack"   – route to SlackNotifier stub (no real sending yet)
    "pause_suggest"  – create an actionable Insight recommending campaign pause;
                       NO real execution — M6 phase 2 owns actual pause capability

    action_config
    -------------
    JSON blob whose schema depends on ``action``:
      alert:          {}  (no extra config needed)
      notify_email:   {"recipients": ["email@example.com"]}
      notify_slack:   {"webhook": "https://hooks.slack.com/services/..."}
      pause_suggest:  {}  (creates insight only; no execution)

    Idempotency
    -----------
    ``last_triggered_at`` stores the ISO-8601 UTC date string of the last
    calendar day on which the rule was triggered.  ``run_rule`` skips writing
    a second action if it has already fired for the same date.
    """

    __tablename__ = "automation_rules"
    __table_args__ = (
        Index("ix_automation_rules_tenant_id", "tenant_id"),
        Index("ix_automation_rules_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # "account" | "channel" | "campaign"
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="account"
    )

    # Channel key or campaign UUID string; None = all
    scope_filter: Mapped[str | None] = mapped_column(
        String(300), nullable=True,
        comment="DimChannel.key or DimCampaign.id string; null = all",
    )

    # "spend" | "roas" | "ctr" | "cpc" | "cpa" | "conversions"
    metric: Mapped[str] = mapped_column(String(50), nullable=False)

    # "pct_drop" | "pct_rise" | "below" | "above" | "anomaly"
    comparator: Mapped[str] = mapped_column(String(20), nullable=False)

    # Percentage (0–100 for pct_* comparators) or absolute value; null for "anomaly"
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    # How many days to look back for metric aggregation (default 7)
    window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7
    )

    # "alert" | "notify_email" | "notify_slack" | "pause_suggest"
    action: Mapped[str] = mapped_column(String(30), nullable=False, default="alert")

    # Channel-specific action configuration (recipients, webhook, etc.)
    action_config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Delivery config: {recipients} | {webhook} | {}",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ISO-8601 UTC date string of the last day the rule fired an action.
    # Used for same-day idempotency.  Null until the rule has ever triggered.
    last_triggered_at: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="ISO-8601 date of last action fire; null = never triggered",
    )

    def __repr__(self) -> str:
        return (
            f"<AutomationRule id={self.id} name={self.name!r}"
            f" metric={self.metric!r} action={self.action!r} tenant={self.tenant_id}>"
        )


# ── AutomationRun ──────────────────────────────────────────────────────────────


class AutomationRun(Base):
    """Audit log of every rule evaluation.

    One row is written per (rule, evaluation) call — whether the rule triggered
    or not.  The ``detail`` JSON captures what the evaluator found:
    matched entities, metric values, threshold comparison results, etc.

    This table is append-only (never updated after insert).
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        Index("ix_automation_runs_tenant_id", "tenant_id"),
        Index("ix_automation_runs_rule_id", "rule_id"),
        Index("ix_automation_runs_tenant_ran_at", "tenant_id", "ran_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Denormalised from the rule for efficient per-tenant queries",
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automation_rules.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ISO-8601 UTC datetime of when the evaluation ran
    ran_at: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="ISO-8601 UTC datetime of the evaluation",
    )

    # True if the condition evaluated to met AND an action was taken
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Machine-readable evaluation details
    detail: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Matched entities, metric values, comparator result, action taken",
    )

    def __repr__(self) -> str:
        return (
            f"<AutomationRun id={self.id} rule={self.rule_id}"
            f" triggered={self.triggered} ran_at={self.ran_at!r}>"
        )
