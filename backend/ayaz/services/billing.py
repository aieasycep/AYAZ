"""Billing service — M10 Subscription & Billing.

Responsibilities
----------------
* PLANS constant dict: the four pricing tiers from docs/03-strategy.md §5.
* ``get_subscription`` / ``entitlements`` — read billing state for a tenant.
* ``check_can_add_data_source`` / ``require_within_data_source_limit`` — plan gate.
* ``start_subscription`` / ``cancel_subscription`` — lifecycle mutations.
* ``BillingProvider`` interface + ``IyzicoProvider``, ``StripeProvider``,
  ``NoneProvider`` stubs — no live network; ready to flip live when keys arrive.
* ``get_provider`` factory — selects provider from settings.

Design rules
------------
* NO live network calls.  Provider stubs return fake checkout URLs.
* Settings keys default to ""; providers detect empty key and stay in stub mode.
* All DB mutations also write a BillingEvent for auditability.
* Tenant isolation: every query filters on tenant_id explicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.config import settings
from ayaz.database import get_db
from ayaz.models.billing import BillingEvent, Subscription
from ayaz.models.oltp import ConnectedAccount, Membership
from ayaz.api.deps import get_current_membership

# ── Plan catalog ──────────────────────────────────────────────────────────────
# Source of truth for plan definitions.  These are constants — not a DB table.
# Prices: price_try = monthly TRY, price_usd = monthly USD.
# Limits: max_data_sources = int or "unlimited"; max_dashboards = int or "unlimited".
# history_days = int; insights = False | "basic" | "full".
# ad_spend_cap = int (TRY monthly cap) or 0 (no ad spend feature).
# features = list of feature flag strings.

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "code": "free",
        "name": "Free",
        "price_try": 0,
        "price_usd": 0,
        "limits": {
            "max_data_sources": 1,
            "max_dashboards": 1,
            "history_days": 7,
            "insights": False,
            "ad_spend_cap": 0,
        },
        "features": [],
    },
    "starter": {
        "code": "starter",
        "name": "Starter",
        "price_try": 1490,
        "price_usd": 39,
        "limits": {
            "max_data_sources": 3,
            "max_dashboards": "unlimited",
            "history_days": 90,
            "insights": "basic",
            "ad_spend_cap": 150000,
            "alerts": "email",
        },
        "features": ["insights_basic", "alerts_email"],
    },
    "growth": {
        "code": "growth",
        "name": "Growth",
        "price_try": 4900,
        "price_usd": 129,
        "limits": {
            "max_data_sources": 8,
            "max_dashboards": "unlimited",
            "history_days": 365,
            "insights": "full",
            "ad_spend_cap": 1000000,
            "alerts": ["email", "slack"],
        },
        "features": [
            "insights_full",
            "alerts_email",
            "alerts_slack",
            "anomaly_detection",
        ],
    },
    "agency": {
        "code": "agency",
        "name": "Agency",
        "price_try": 12900,
        "price_usd": 349,
        "limits": {
            "max_data_sources": "unlimited",
            "max_dashboards": "unlimited",
            "history_days": 730,
            "insights": "full",
            "ad_spend_cap": "unlimited",
            "alerts": ["email", "slack"],
            "white_label": True,
            "multi_account": True,
            "priority_support": True,
        },
        "features": [
            "insights_full",
            "alerts_email",
            "alerts_slack",
            "anomaly_detection",
            "white_label",
            "multi_account",
            "priority_support",
        ],
    },
}

# Trial duration in days (applied on first paid plan upgrade)
_TRIAL_DAYS = 14


# ── Internal helpers ──────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _write_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    event_type: str,
    provider: str,
    payload: dict,
) -> BillingEvent:
    """Append a BillingEvent and flush (caller must commit)."""
    event = BillingEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        type=event_type,
        provider=provider,
        payload=payload,
        created_at=_utcnow_iso(),
    )
    db.add(event)
    db.flush()
    return event


# ── Core subscription queries ─────────────────────────────────────────────────


def get_subscription(db: Session, tenant_id: uuid.UUID) -> Subscription:
    """Return the tenant's Subscription row.

    If no row exists (tenant has never interacted with billing), return a
    synthetic in-memory FREE subscription — the caller must NOT commit this
    object back to the DB without first creating a real row via
    ``start_subscription`` or similar.
    """
    row = db.scalar(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    if row is not None:
        return row

    # Synthetic default — free plan, never persisted
    synthetic = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        plan_code="free",
        status="active",
        provider="none",
        provider_customer_id=None,
        provider_subscription_id=None,
        trial_end=None,
        current_period_end=None,
    )
    return synthetic


def entitlements(db: Session, tenant_id: uuid.UUID) -> dict:
    """Return the resolved entitlements (limits + features) for a tenant.

    Entitlements are derived from the tenant's current plan code.  If the
    subscription is in "canceled" or "past_due" status and the billing period
    has ended, we fall back to the "free" plan limits.
    """
    sub = get_subscription(db, tenant_id)
    plan_code = sub.plan_code

    # Downgrade to free if canceled/past_due and period has ended
    if sub.status in ("canceled", "past_due") and sub.current_period_end:
        try:
            period_end = datetime.fromisoformat(sub.current_period_end)
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=timezone.utc)
            if _utcnow() > period_end:
                plan_code = "free"
        except ValueError:
            pass  # malformed date — keep current plan_code

    plan = PLANS.get(plan_code, PLANS["free"])
    return {
        "plan_code": plan["code"],
        "plan_name": plan["name"],
        "limits": plan["limits"],
        "features": plan["features"],
        "status": sub.status,
    }


# ── Data-source gating ────────────────────────────────────────────────────────


def check_can_add_data_source(db: Session, tenant_id: uuid.UUID) -> bool:
    """Return True if the tenant may add another ConnectedAccount.

    Raises HTTPException 402 with a Turkish message when the limit is exceeded.

    Agency plan has "unlimited" data sources and always returns True.
    """
    ents = entitlements(db, tenant_id)
    max_ds = ents["limits"]["max_data_sources"]

    if max_ds == "unlimited":
        return True

    current_count = db.scalar(
        select(func.count()).where(ConnectedAccount.tenant_id == tenant_id)
    )
    if current_count is None:
        current_count = 0

    if current_count >= max_ds:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Plan limitiniz doldu — yükseltin. "
                f"({current_count}/{max_ds} veri kaynağı kullanıldı)"
            ),
        )
    return True


def require_within_data_source_limit(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """FastAPI dependency: raises 402 when the tenant's data-source limit is exceeded.

    Add to any endpoint that creates a ConnectedAccount::

        _: None = Depends(require_within_data_source_limit)

    This does NOT consume the return value; FastAPI runs it for its side-effects.
    """
    check_can_add_data_source(db, membership.tenant_id)


# ── Subscription lifecycle mutations ──────────────────────────────────────────


def start_subscription(
    db: Session,
    tenant_id: uuid.UUID,
    plan_code: str,
    provider: str = "none",
    *,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
) -> Subscription:
    """Upgrade (or initialise) the subscription to the given plan.

    Rules
    -----
    * If moving from "free" to any paid plan for the first time, set
      status="trialing" and trial_end = now + 14 days.
    * If the tenant already has a paid subscription, set status="active".
    * Writes a BillingEvent of type "subscription.upgraded".
    * Creates the Subscription row if it does not yet exist.
    """
    if plan_code not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bilinmeyen plan kodu: {plan_code!r}",
        )

    sub = db.scalar(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )

    is_new = sub is None
    was_free = is_new or (sub is not None and sub.plan_code == "free")

    now = _utcnow()
    # 14-day trial only on first upgrade from free
    if was_free and plan_code != "free":
        new_status = "trialing"
        trial_end = (now + timedelta(days=_TRIAL_DAYS)).isoformat()
        # Current period ends when trial ends
        period_end = trial_end
    else:
        new_status = "active"
        trial_end = None
        # Default period: 30 days from now
        period_end = (now + timedelta(days=30)).isoformat()

    if is_new:
        sub = Subscription(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            plan_code=plan_code,
            status=new_status,
            provider=provider,
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            trial_end=trial_end,
            current_period_end=period_end,
        )
        db.add(sub)
    else:
        sub.plan_code = plan_code  # type: ignore[union-attr]
        sub.status = new_status  # type: ignore[union-attr]
        sub.provider = provider  # type: ignore[union-attr]
        if provider_customer_id is not None:
            sub.provider_customer_id = provider_customer_id  # type: ignore[union-attr]
        if provider_subscription_id is not None:
            sub.provider_subscription_id = provider_subscription_id  # type: ignore[union-attr]
        sub.trial_end = trial_end  # type: ignore[union-attr]
        sub.current_period_end = period_end  # type: ignore[union-attr]

    _write_event(
        db,
        tenant_id=tenant_id,
        event_type="subscription.upgraded",
        provider=provider,
        payload={
            "plan_code": plan_code,
            "status": new_status,
            "trial_end": trial_end,
            "current_period_end": period_end,
        },
    )

    db.commit()
    db.refresh(sub)
    return sub


def cancel_subscription(db: Session, tenant_id: uuid.UUID) -> Subscription:
    """Cancel the active subscription at the end of the current period.

    Sets status="canceled" (access continues until current_period_end).
    Writes a BillingEvent of type "subscription.canceled".
    If no subscription exists, this is a no-op returning a synthetic free row.
    """
    sub = db.scalar(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    if sub is None:
        # Nothing to cancel — return synthetic free subscription
        return get_subscription(db, tenant_id)

    sub.status = "canceled"  # type: ignore[union-attr]

    _write_event(
        db,
        tenant_id=tenant_id,
        event_type="subscription.canceled",
        provider=sub.provider,
        payload={
            "plan_code": sub.plan_code,
            "current_period_end": sub.current_period_end,
        },
    )

    db.commit()
    db.refresh(sub)
    return sub


# ── Provider abstraction ──────────────────────────────────────────────────────


class BillingProvider:
    """Abstract billing provider interface.

    All methods are stubs unless overridden by a concrete provider.
    NO live network calls are made in this module.
    """

    provider_name: str = "none"

    def create_checkout(
        self,
        tenant_id: uuid.UUID,
        plan_code: str,
        db: Session,
    ) -> dict:
        """Return a dict with at least ``checkout_url`` and ``provider``.

        The caller should redirect the user's browser to ``checkout_url``.
        Writes a BillingEvent of type "checkout.created".
        """
        raise NotImplementedError

    def handle_webhook(
        self,
        payload: dict,
        tenant_id: uuid.UUID,
        db: Session,
    ) -> BillingEvent:
        """Parse a webhook payload, update subscription state, and return the event.

        The webhook endpoint calls this after verifying the signature.
        """
        raise NotImplementedError


class NoneProvider(BillingProvider):
    """Dummy provider for free plan and development/test use."""

    provider_name: str = "none"

    def create_checkout(
        self,
        tenant_id: uuid.UUID,
        plan_code: str,
        db: Session,
    ) -> dict:
        """No-op checkout — used for downgrading to free or testing."""
        checkout_url = f"https://checkout.test/none/{tenant_id}/{plan_code}"
        _write_event(
            db,
            tenant_id=tenant_id,
            event_type="checkout.created",
            provider=self.provider_name,
            payload={"plan_code": plan_code, "checkout_url": checkout_url},
        )
        db.commit()
        return {"checkout_url": checkout_url, "provider": self.provider_name}

    def handle_webhook(
        self,
        payload: dict,
        tenant_id: uuid.UUID,
        db: Session,
    ) -> BillingEvent:
        """Stub webhook handler — accept any payload, write an audit event."""
        event = _write_event(
            db,
            tenant_id=tenant_id,
            event_type=payload.get("type", "webhook.received"),
            provider=self.provider_name,
            payload=payload,
        )
        # If payload signals a plan change, apply it
        if "plan_code" in payload:
            _apply_webhook_plan_change(db, tenant_id, payload, self.provider_name)
        db.commit()
        db.refresh(event)
        return event


class IyzicoProvider(BillingProvider):
    """Iyzico payment provider stub (TR market).

    In TEST/STUB mode (iyzico_api_key == ""):
      - create_checkout returns a fake URL immediately.
      - handle_webhook accepts any payload structure.

    To go live: set IYZICO_API_KEY + IYZICO_SECRET_KEY in the environment.
    The stub checks for empty keys and stays in test mode.
    """

    provider_name: str = "iyzico"

    def _is_live(self) -> bool:
        return bool(settings.iyzico_api_key and settings.iyzico_secret_key)

    def create_checkout(
        self,
        tenant_id: uuid.UUID,
        plan_code: str,
        db: Session,
    ) -> dict:
        # STUB: return a fake iyzico checkout URL
        # TODO (Faz 1): call iyzico CheckoutFormInitialize API when live keys set
        checkout_url = f"https://checkout.test/iyzico/{tenant_id}/{plan_code}"
        if self._is_live():
            # Placeholder for live iyzico integration
            # checkout_url = iyzico_client.init_form(tenant_id, plan_code)
            pass  # pragma: no cover

        _write_event(
            db,
            tenant_id=tenant_id,
            event_type="checkout.created",
            provider=self.provider_name,
            payload={"plan_code": plan_code, "checkout_url": checkout_url},
        )
        db.commit()
        return {"checkout_url": checkout_url, "provider": self.provider_name}

    def handle_webhook(
        self,
        payload: dict,
        tenant_id: uuid.UUID,
        db: Session,
    ) -> BillingEvent:
        # STUB: accept any payload, write audit event
        # TODO (Faz 1): verify iyzico HMAC signature, parse real event types
        event = _write_event(
            db,
            tenant_id=tenant_id,
            event_type=payload.get("type", "webhook.received"),
            provider=self.provider_name,
            payload=payload,
        )
        if "plan_code" in payload:
            _apply_webhook_plan_change(db, tenant_id, payload, self.provider_name)
        db.commit()
        db.refresh(event)
        return event


class StripeProvider(BillingProvider):
    """Stripe payment provider stub (global market).

    In TEST/STUB mode (stripe_api_key == ""):
      - create_checkout returns a fake URL immediately.
      - handle_webhook accepts any payload structure.

    To go live: set STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET in the environment.
    """

    provider_name: str = "stripe"

    def _is_live(self) -> bool:
        return bool(settings.stripe_secret_key and settings.stripe_webhook_secret)

    def create_checkout(
        self,
        tenant_id: uuid.UUID,
        plan_code: str,
        db: Session,
    ) -> dict:
        # STUB: return a fake Stripe checkout URL
        # TODO (Faz 1): call stripe.checkout.Session.create when live keys set
        checkout_url = f"https://checkout.test/stripe/{tenant_id}/{plan_code}"
        if self._is_live():
            # Placeholder for live Stripe integration
            # session = stripe.checkout.Session.create(...)
            # checkout_url = session.url
            pass  # pragma: no cover

        _write_event(
            db,
            tenant_id=tenant_id,
            event_type="checkout.created",
            provider=self.provider_name,
            payload={"plan_code": plan_code, "checkout_url": checkout_url},
        )
        db.commit()
        return {"checkout_url": checkout_url, "provider": self.provider_name}

    def handle_webhook(
        self,
        payload: dict,
        tenant_id: uuid.UUID,
        db: Session,
    ) -> BillingEvent:
        # STUB: accept any payload, write audit event
        # TODO (Faz 1): verify Stripe-Signature header, parse real event types
        event = _write_event(
            db,
            tenant_id=tenant_id,
            event_type=payload.get("type", "webhook.received"),
            provider=self.provider_name,
            payload=payload,
        )
        if "plan_code" in payload:
            _apply_webhook_plan_change(db, tenant_id, payload, self.provider_name)
        db.commit()
        db.refresh(event)
        return event


def _apply_webhook_plan_change(
    db: Session,
    tenant_id: uuid.UUID,
    payload: dict,
    provider: str,
) -> None:
    """Apply a plan change signalled by a webhook payload (internal helper).

    Looks for ``plan_code`` and optionally ``status`` in the payload.
    This is called inside handle_webhook; the caller commits after this returns.
    """
    plan_code = payload.get("plan_code", "free")
    new_status = payload.get("status", "active")

    sub = db.scalar(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    if sub is None:
        sub = Subscription(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            plan_code=plan_code,
            status=new_status,
            provider=provider,
        )
        db.add(sub)
    else:
        sub.plan_code = plan_code  # type: ignore[union-attr]
        sub.status = new_status  # type: ignore[union-attr]
        sub.provider = provider  # type: ignore[union-attr]
        if new_status == "canceled":
            pass  # keep current_period_end as-is


def get_provider(provider_name: str | None = None) -> BillingProvider:
    """Return the appropriate BillingProvider instance.

    Selection order:
    1. Explicit ``provider_name`` argument (used in checkout requests).
    2. ``settings.billing_provider`` from environment.
    3. Default: NoneProvider.

    Provider instances are lightweight — create a new one per request.
    """
    name = provider_name or getattr(settings, "billing_provider", "none") or "none"
    if name == "iyzico":
        return IyzicoProvider()
    if name == "stripe":
        return StripeProvider()
    return NoneProvider()
