"""Billing API — M10 Subscription & Billing.

Endpoints
---------
GET  /billing/plans            — public plan catalog (no auth required)
GET  /billing/subscription     — current subscription + entitlements + usage
POST /billing/checkout         — initiate a checkout session (stub)
POST /billing/cancel           — cancel the current subscription at period end
POST /billing/webhook/{provider} — receive provider webhooks (no auth)

Auth
----
All endpoints except ``GET /billing/plans`` and ``POST /billing/webhook/{provider}``
require a valid JWT with a ``tid`` claim (resolved via ``get_current_membership``).

Tenant isolation
----------------
Every service call passes ``membership.tenant_id`` — never trusts a tenant_id
from the request body.

Provider stubs
--------------
No live network calls are made.  All checkout URLs are synthetic test URLs.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.billing import BillingEvent
from ayaz.models.oltp import ConnectedAccount, Membership
from ayaz.services.billing import (
    PLANS,
    cancel_subscription,
    entitlements,
    get_provider,
    get_subscription,
    start_subscription,
)

router = APIRouter(prefix="/billing", tags=["billing"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PlanResponse(BaseModel):
    """Public representation of a single pricing plan."""

    code: str
    name: str
    price_try: int
    price_usd: int
    limits: dict[str, Any]
    features: list[str]


class SubscriptionResponse(BaseModel):
    """Subscription state + resolved entitlements + current usage."""

    # Subscription fields
    id: uuid.UUID
    tenant_id: uuid.UUID
    plan_code: str
    status: str
    provider: str
    provider_customer_id: str | None
    provider_subscription_id: str | None
    trial_end: str | None
    current_period_end: str | None

    # Resolved entitlements
    entitlements: dict[str, Any]

    # Current usage
    data_sources_used: int


class CheckoutRequest(BaseModel):
    """Request body for initiating a checkout session."""

    plan_code: str
    provider: str | None = None  # "iyzico" | "stripe" | None → use settings default


class CheckoutResponse(BaseModel):
    """Checkout initiation response."""

    checkout_url: str
    provider: str


class CancelResponse(BaseModel):
    """Response after cancellation request."""

    status: str
    plan_code: str
    current_period_end: str | None
    message: str


class WebhookResponse(BaseModel):
    """Webhook processing acknowledgement."""

    received: bool
    event_id: uuid.UUID


# ── Helper ────────────────────────────────────────────────────────────────────


def _count_data_sources(db: Session, tenant_id: uuid.UUID) -> int:
    """Return the count of ConnectedAccount rows for the tenant."""
    count = db.scalar(
        select(func.count()).where(ConnectedAccount.tenant_id == tenant_id)
    )
    return count or 0


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/plans",
    response_model=list[PlanResponse],
    summary="List all available subscription plans",
)
def list_plans() -> list[PlanResponse]:
    """Return the full plan catalog.

    This endpoint requires NO authentication — it is publicly accessible so
    marketing pages and unauthenticated users can see pricing.
    """
    return [
        PlanResponse(
            code=p["code"],
            name=p["name"],
            price_try=p["price_try"],
            price_usd=p["price_usd"],
            limits=p["limits"],
            features=p["features"],
        )
        for p in PLANS.values()
    ]


@router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    summary="Get the current tenant subscription, entitlements, and usage",
)
def get_current_subscription(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SubscriptionResponse:
    """Return the tenant's current subscription state.

    Includes resolved entitlements (limits + features for the current plan) and
    live usage figures (e.g. number of connected data sources).
    """
    tenant_id = membership.tenant_id
    sub = get_subscription(db, tenant_id)
    ents = entitlements(db, tenant_id)
    ds_count = _count_data_sources(db, tenant_id)

    return SubscriptionResponse(
        id=sub.id,
        tenant_id=sub.tenant_id,
        plan_code=sub.plan_code,
        status=sub.status,
        provider=sub.provider,
        provider_customer_id=sub.provider_customer_id,
        provider_subscription_id=sub.provider_subscription_id,
        trial_end=sub.trial_end,
        current_period_end=sub.current_period_end,
        entitlements=ents,
        data_sources_used=ds_count,
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate a checkout session for a plan upgrade",
)
def create_checkout(
    body: CheckoutRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> CheckoutResponse:
    """Start a checkout session for the requested plan.

    Returns a ``checkout_url`` that the frontend should redirect the user to.
    In TEST/STUB mode this URL is a synthetic https://checkout.test/... URL.
    When live credentials are configured the URL comes from iyzico or Stripe.

    Writes a BillingEvent of type "checkout.created".
    """
    if body.plan_code not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bilinmeyen plan kodu: {body.plan_code!r}",
        )

    provider = get_provider(body.provider)
    result = provider.create_checkout(membership.tenant_id, body.plan_code, db)
    return CheckoutResponse(
        checkout_url=result["checkout_url"],
        provider=result["provider"],
    )


@router.post(
    "/cancel",
    response_model=CancelResponse,
    summary="Cancel the current subscription at the end of the billing period",
)
def cancel_current_subscription(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> CancelResponse:
    """Mark the subscription for cancellation.

    The subscription transitions to status="canceled" but access continues
    until ``current_period_end``.  After that date ``entitlements`` will
    downgrade to the free plan limits.

    Writes a BillingEvent of type "subscription.canceled".
    """
    sub = cancel_subscription(db, membership.tenant_id)
    return CancelResponse(
        status=sub.status,
        plan_code=sub.plan_code,
        current_period_end=sub.current_period_end,
        message=(
            "Aboneliğiniz dönem sonunda iptal edilecek. "
            "Erişiminiz geçerli dönem bitimine kadar devam eder."
        ),
    )


@router.post(
    "/webhook/{provider}",
    response_model=WebhookResponse,
    summary="Receive a billing webhook from a payment provider",
    # No auth — webhook is authenticated via provider signature (stub: accepts all)
    include_in_schema=True,
)
def receive_webhook(
    provider: str,
    payload: dict,
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """Process an incoming webhook from iyzico or Stripe.

    This endpoint has NO JWT authentication — it is secured (in production) via
    the provider's request signature (iyzico HMAC / Stripe-Signature header).

    In STUB mode every payload is accepted.  The endpoint expects a JSON body
    with at minimum::

        {
          "tenant_id": "<uuid>",           // required to scope the event
          "type": "subscription.renewed",  // optional; defaults to "webhook.received"
          "plan_code": "growth",           // optional; triggers a plan update
          "status": "active"               // optional; subscription status override
        }

    TODO (Faz 1): verify HMAC/signature before processing; reject unsigned payloads.
    """
    if provider not in ("iyzico", "stripe", "none"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bilinmeyen sağlayıcı: {provider!r}",
        )

    # Extract tenant_id from payload — required for scoping
    tenant_id_raw = payload.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload'ında tenant_id eksik.",
        )
    try:
        tenant_id = uuid.UUID(str(tenant_id_raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geçersiz tenant_id formatı.",
        )

    billing_provider = get_provider(provider)
    event = billing_provider.handle_webhook(payload, tenant_id, db)

    return WebhookResponse(received=True, event_id=event.id)
