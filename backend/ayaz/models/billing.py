"""Billing data models — M10 Subscription & Billing.

Tables
------
  subscriptions   — one row per tenant; uniquely links a tenant to its current plan.
  billing_events  — immutable audit log of every billing lifecycle event (webhook,
                    checkout, upgrade, cancel, etc.).

Design notes
------------
* Status and provider columns use String (not Postgres ENUM) for SQLite compatibility
  and to avoid the duplicate-type migration bug documented in 0001_initial_schema.py.
* Allowed values are validated at the application / Pydantic layer, NOT as DB constraints.
* tenant_id carries an explicit index for isolation queries.  The uniqueness constraint on
  Subscription.tenant_id ensures exactly one subscription row per tenant.
* BillingEvent.payload is a JSON column that stores the raw provider webhook body or a
  synthetic dict describing an internal lifecycle change.
* No Postgres ENUM types are used; no live network calls in this module.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import JSON

from ayaz.models.base import Base, TimestampMixin, uuid_pk
from ayaz.models.oltp import Tenant  # noqa: F401 — imported for relationship type hint


class Subscription(Base, TimestampMixin):
    """One subscription row per tenant — the source of truth for billing state.

    Status values
    -------------
    "trialing"  — within the 14-day free Growth trial on first upgrade.
    "active"    — paid / in-period subscription.
    "past_due"  — payment failed; access may be restricted after a grace period.
    "canceled"  — subscription cancelled at period end; still active until current_period_end.

    Provider values
    ---------------
    "none"    — free plan or manually set; no payment provider involved.
    "iyzico"  — Turkish market payments (iyzico.com).
    "stripe"  — global payments (stripe.com).
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    # Tenant FK — one subscription per tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    # Plan code from the PLANS constant dict (free | starter | growth | agency)
    plan_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="free",
        comment="free | starter | growth | agency",
    )

    # Lifecycle status — String to avoid Postgres ENUM issues
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="trialing | active | past_due | canceled",
    )

    # Payment provider — String to avoid Postgres ENUM issues
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="none",
        comment="none | iyzico | stripe",
    )

    # Provider-specific identifiers (nullable for free / none-provider)
    provider_customer_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Provider customer ID (e.g. cus_xxx for Stripe)",
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Provider subscription ID (e.g. sub_xxx for Stripe)",
    )

    # Trial end — ISO-8601 text for SQLite compat
    trial_end: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC datetime when the trial ends (null if not trialing)",
    )

    # Current billing period end — ISO-8601 text for SQLite compat
    current_period_end: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC datetime of the current billing period end",
    )

    # Relationship
    tenant: Mapped["Tenant"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<Subscription tenant={self.tenant_id} plan={self.plan_code}"
            f" status={self.status}>"
        )


class BillingEvent(Base):
    """Immutable audit log for every billing lifecycle event.

    Events are NEVER updated or deleted — they are append-only.

    Type values (illustrative, not exhaustive)
    -------------------------------------------
    "checkout.created"   — a checkout session was started.
    "subscription.upgraded" — plan changed (including trial start).
    "subscription.canceled" — cancellation requested.
    "webhook.received"   — a raw webhook was received from a provider.
    "subscription.past_due" — payment failed.
    "subscription.renewed"  — period renewed (webhook from provider).
    """

    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    # Event type string (free-form; use the values documented above)
    type: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        comment="checkout.created | subscription.upgraded | subscription.canceled | webhook.received | …",
    )

    # Provider that originated this event
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="none",
        comment="none | iyzico | stripe",
    )

    # Raw or synthetic payload; stored as JSON
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Raw webhook body or synthetic event payload dict",
    )

    # created_at only — events are immutable; no updated_at
    created_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ISO-8601 UTC datetime of event ingestion",
    )

    def __repr__(self) -> str:
        return (
            f"<BillingEvent type={self.type!r} provider={self.provider}"
            f" tenant={self.tenant_id}>"
        )
