"""Tests for M10 Subscription & Billing module.

Coverage
--------
* PLANS catalog: structure, required keys, price values.
* Default free subscription: get_subscription returns synthetic free row.
* entitlements per plan: correct limits and features resolved.
* check_can_add_data_source: allow under limit, block at limit, unlimited for agency.
* checkout stub: returns a URL containing "checkout.test", writes a BillingEvent.
* start_subscription: trial set on first upgrade; status + trial_end correct.
* cancel_subscription: status transitions to "canceled".
* Webhook stub: updates subscription state, writes BillingEvent.
* Connectors create endpoint: blocked when over plan limit (returns 402).

Strategy
--------
* FastAPI TestClient with minimal test apps for billing and connectors routers.
* get_db overridden to an in-memory SQLite session.
* get_current_membership overridden to return a fixed Membership.
* All existing tests remain green (no global state is mutated).
"""

from __future__ import annotations

import uuid
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.billing import BillingEvent, Subscription
from ayaz.models.oltp import (
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
)
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import billing as billing_module
from ayaz.api.v1 import connectors as connectors_module
from ayaz.services.auth import hash_password
from ayaz.services.billing import (
    PLANS,
    cancel_subscription,
    check_can_add_data_source,
    entitlements,
    get_provider,
    get_subscription,
    start_subscription,
)


# ── Minimal test apps ─────────────────────────────────────────────────────────

_billing_app = FastAPI(title="AYAZ Billing Test App")
_billing_app.include_router(billing_module.router, prefix="/api/v1")

_connectors_app = FastAPI(title="AYAZ Connectors Test App")
_connectors_app.include_router(connectors_module.router, prefix="/api/v1")


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_tenant(db: Session) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Billing Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(tenant)
    db.flush()
    return tenant


def _make_user(db: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"billing-{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Billing Test User",
    )
    db.add(user)
    db.flush()
    return user


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _make_connected_account(
    db: Session, tenant: Tenant, platform: Platform = Platform.google_ads
) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=f"ACC-{uuid.uuid4().hex[:8]}",
        display_name="Test Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


# ── Client fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def billing_client(db_session: Session):
    """TestClient wired to the billing router with DB + membership overridden."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _billing_app.dependency_overrides[get_db] = override_get_db
    _billing_app.dependency_overrides[get_current_membership] = override_membership

    client = TestClient(_billing_app)
    yield client, tenant, membership

    _billing_app.dependency_overrides.clear()


@pytest.fixture()
def connectors_client(db_session: Session):
    """TestClient wired to the connectors router; membership is on a FREE plan."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _connectors_app.dependency_overrides[get_db] = override_get_db
    _connectors_app.dependency_overrides[get_current_membership] = override_membership

    client = TestClient(_connectors_app)
    yield client, tenant, membership

    _connectors_app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Plan catalog tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPlansCatalog:
    def test_plans_has_four_tiers(self) -> None:
        assert set(PLANS.keys()) == {"free", "starter", "growth", "agency"}

    def test_each_plan_has_required_keys(self) -> None:
        required = {"code", "name", "price_try", "price_usd", "limits", "features"}
        for code, plan in PLANS.items():
            missing = required - set(plan.keys())
            assert not missing, f"Plan {code!r} missing keys: {missing}"

    def test_free_plan_price_zero(self) -> None:
        assert PLANS["free"]["price_try"] == 0
        assert PLANS["free"]["price_usd"] == 0

    def test_starter_prices(self) -> None:
        assert PLANS["starter"]["price_try"] == 1490
        assert PLANS["starter"]["price_usd"] == 39

    def test_growth_prices(self) -> None:
        assert PLANS["growth"]["price_try"] == 4900
        assert PLANS["growth"]["price_usd"] == 129

    def test_agency_prices(self) -> None:
        assert PLANS["agency"]["price_try"] == 12900
        assert PLANS["agency"]["price_usd"] == 349

    def test_free_max_data_sources(self) -> None:
        assert PLANS["free"]["limits"]["max_data_sources"] == 1

    def test_starter_max_data_sources(self) -> None:
        assert PLANS["starter"]["limits"]["max_data_sources"] == 3

    def test_growth_max_data_sources(self) -> None:
        assert PLANS["growth"]["limits"]["max_data_sources"] == 8

    def test_agency_max_data_sources_unlimited(self) -> None:
        assert PLANS["agency"]["limits"]["max_data_sources"] == "unlimited"

    def test_free_insights_false(self) -> None:
        assert PLANS["free"]["limits"]["insights"] is False

    def test_starter_insights_basic(self) -> None:
        assert PLANS["starter"]["limits"]["insights"] == "basic"

    def test_growth_insights_full(self) -> None:
        assert PLANS["growth"]["limits"]["insights"] == "full"

    def test_agency_white_label(self) -> None:
        assert PLANS["agency"]["limits"].get("white_label") is True

    def test_agency_multi_account(self) -> None:
        assert PLANS["agency"]["limits"].get("multi_account") is True

    def test_free_ad_spend_cap_zero(self) -> None:
        assert PLANS["free"]["limits"]["ad_spend_cap"] == 0

    def test_starter_ad_spend_cap(self) -> None:
        assert PLANS["starter"]["limits"]["ad_spend_cap"] == 150000

    def test_growth_ad_spend_cap(self) -> None:
        assert PLANS["growth"]["limits"]["ad_spend_cap"] == 1000000

    def test_features_are_lists(self) -> None:
        for code, plan in PLANS.items():
            assert isinstance(plan["features"], list), (
                f"Plan {code!r} features should be a list"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Subscription service unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestGetSubscription:
    def test_returns_synthetic_free_when_no_row(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        sub = get_subscription(db_session, tenant.id)
        assert sub.plan_code == "free"
        assert sub.status == "active"
        assert sub.provider == "none"

    def test_returns_existing_row(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        row = Subscription(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            plan_code="growth",
            status="active",
            provider="stripe",
        )
        db_session.add(row)
        db_session.commit()

        sub = get_subscription(db_session, tenant.id)
        assert sub.plan_code == "growth"
        assert sub.provider == "stripe"


class TestEntitlements:
    def test_free_entitlements(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        assert ents["plan_code"] == "free"
        assert ents["limits"]["max_data_sources"] == 1
        assert ents["limits"]["insights"] is False

    def test_starter_entitlements(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="starter",
                status="active",
                provider="iyzico",
            )
        )
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        assert ents["plan_code"] == "starter"
        assert ents["limits"]["max_data_sources"] == 3
        assert ents["limits"]["insights"] == "basic"
        assert "insights_basic" in ents["features"]

    def test_growth_entitlements(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="growth",
                status="active",
                provider="stripe",
            )
        )
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        assert ents["plan_code"] == "growth"
        assert ents["limits"]["max_data_sources"] == 8
        assert ents["limits"]["insights"] == "full"
        assert "alerts_slack" in ents["features"]

    def test_agency_entitlements(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="agency",
                status="active",
                provider="stripe",
            )
        )
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        assert ents["plan_code"] == "agency"
        assert ents["limits"]["max_data_sources"] == "unlimited"
        assert "white_label" in ents["features"]
        assert "priority_support" in ents["features"]

    def test_canceled_past_period_downgrades_to_free(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        # canceled subscription with period_end in the past
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="growth",
                status="canceled",
                provider="stripe",
                current_period_end="2020-01-01T00:00:00+00:00",
            )
        )
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        # Should downgrade to free limits
        assert ents["limits"]["max_data_sources"] == 1

    def test_canceled_before_period_end_keeps_plan(self, db_session: Session) -> None:
        from datetime import timedelta
        from ayaz.services.billing import _utcnow

        tenant = _make_tenant(db_session)
        future = (_utcnow() + timedelta(days=30)).isoformat()
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="growth",
                status="canceled",
                provider="stripe",
                current_period_end=future,
            )
        )
        db_session.commit()

        ents = entitlements(db_session, tenant.id)
        # Period hasn't ended, so growth limits still apply
        assert ents["limits"]["max_data_sources"] == 8


# ══════════════════════════════════════════════════════════════════════════════
# Data-source gating tests
# ══════════════════════════════════════════════════════════════════════════════


class TestDataSourceGating:
    def test_allow_when_under_free_limit(self, db_session: Session) -> None:
        """Free plan allows 1 data source; 0 currently connected → should pass."""
        tenant = _make_tenant(db_session)
        db_session.commit()

        result = check_can_add_data_source(db_session, tenant.id)
        assert result is True

    def test_block_at_free_limit(self, db_session: Session) -> None:
        """Free plan allows 1 data source; 1 already connected → should raise 402."""
        from fastapi import HTTPException

        tenant = _make_tenant(db_session)
        _make_connected_account(db_session, tenant)
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            check_can_add_data_source(db_session, tenant.id)
        assert exc_info.value.status_code == 402
        assert "yükseltin" in exc_info.value.detail.lower()

    def test_allow_under_starter_limit(self, db_session: Session) -> None:
        """Starter allows 3; 2 connected → should pass."""
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="starter",
                status="active",
                provider="iyzico",
            )
        )
        _make_connected_account(db_session, tenant, Platform.google_ads)
        _make_connected_account(db_session, tenant, Platform.meta_ads)
        db_session.commit()

        result = check_can_add_data_source(db_session, tenant.id)
        assert result is True

    def test_block_at_starter_limit(self, db_session: Session) -> None:
        """Starter allows 3; 3 already connected → should raise 402."""
        from fastapi import HTTPException

        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="starter",
                status="active",
                provider="iyzico",
            )
        )
        for plat in (Platform.google_ads, Platform.meta_ads, Platform.ga4):
            _make_connected_account(db_session, tenant, plat)
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            check_can_add_data_source(db_session, tenant.id)
        assert exc_info.value.status_code == 402

    def test_unlimited_for_agency(self, db_session: Session) -> None:
        """Agency plan is unlimited; many accounts connected → should always pass."""
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="agency",
                status="active",
                provider="stripe",
            )
        )
        # Add more than the growth limit (8)
        for plat in [Platform.google_ads, Platform.meta_ads, Platform.ga4,
                     Platform.search_console, Platform.tiktok_ads,
                     Platform.linkedin_ads, Platform.microsoft_ads,
                     Platform.sample, Platform.google_ads]:
            _make_connected_account(db_session, tenant, plat)
        db_session.commit()

        result = check_can_add_data_source(db_session, tenant.id)
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# Subscription lifecycle mutation tests
# ══════════════════════════════════════════════════════════════════════════════


class TestStartSubscription:
    def test_first_upgrade_sets_trialing(self, db_session: Session) -> None:
        """First upgrade from free → paid plan should set status=trialing."""
        tenant = _make_tenant(db_session)
        db_session.commit()

        sub = start_subscription(db_session, tenant.id, "growth", "stripe")
        assert sub.status == "trialing"
        assert sub.trial_end is not None
        assert sub.plan_code == "growth"

    def test_trial_end_is_14_days_from_now(self, db_session: Session) -> None:
        from datetime import datetime, timedelta, timezone

        tenant = _make_tenant(db_session)
        db_session.commit()

        sub = start_subscription(db_session, tenant.id, "starter", "iyzico")
        trial_end = datetime.fromisoformat(sub.trial_end)
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) + timedelta(days=14)
        # Allow 60 seconds tolerance for test execution time
        diff = abs((trial_end - expected).total_seconds())
        assert diff < 60

    def test_subsequent_upgrade_sets_active(self, db_session: Session) -> None:
        """Upgrading from starter to growth (not from free) → active, no trial."""
        tenant = _make_tenant(db_session)
        # Pre-existing starter subscription (not free)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="starter",
                status="active",
                provider="iyzico",
            )
        )
        db_session.commit()

        sub = start_subscription(db_session, tenant.id, "growth", "stripe")
        assert sub.status == "active"
        assert sub.trial_end is None

    def test_writes_billing_event(self, db_session: Session) -> None:
        from sqlalchemy import select as sa_select

        tenant = _make_tenant(db_session)
        db_session.commit()

        start_subscription(db_session, tenant.id, "growth", "stripe")

        event = db_session.scalar(
            sa_select(BillingEvent).where(
                BillingEvent.tenant_id == tenant.id,
                BillingEvent.type == "subscription.upgraded",
            )
        )
        assert event is not None
        assert event.provider == "stripe"

    def test_unknown_plan_raises_400(self, db_session: Session) -> None:
        from fastapi import HTTPException

        tenant = _make_tenant(db_session)
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            start_subscription(db_session, tenant.id, "enterprise", "stripe")
        assert exc_info.value.status_code == 400


class TestCancelSubscription:
    def test_cancel_sets_status_canceled(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="growth",
                status="active",
                provider="stripe",
            )
        )
        db_session.commit()

        sub = cancel_subscription(db_session, tenant.id)
        assert sub.status == "canceled"

    def test_cancel_writes_billing_event(self, db_session: Session) -> None:
        from sqlalchemy import select as sa_select

        tenant = _make_tenant(db_session)
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="starter",
                status="active",
                provider="iyzico",
            )
        )
        db_session.commit()

        cancel_subscription(db_session, tenant.id)

        event = db_session.scalar(
            sa_select(BillingEvent).where(
                BillingEvent.tenant_id == tenant.id,
                BillingEvent.type == "subscription.canceled",
            )
        )
        assert event is not None

    def test_cancel_no_subscription_returns_free(self, db_session: Session) -> None:
        """Cancelling when there is no subscription row → synthetic free row, no error."""
        tenant = _make_tenant(db_session)
        db_session.commit()

        sub = cancel_subscription(db_session, tenant.id)
        assert sub.plan_code == "free"


# ══════════════════════════════════════════════════════════════════════════════
# Provider stub tests
# ══════════════════════════════════════════════════════════════════════════════


class TestProviderStubs:
    def test_none_provider_checkout_returns_url(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        provider = get_provider("none")
        result = provider.create_checkout(tenant.id, "growth", db_session)

        assert "checkout_url" in result
        assert "checkout.test" in result["checkout_url"]
        assert result["provider"] == "none"

    def test_iyzico_provider_checkout_returns_url(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        provider = get_provider("iyzico")
        result = provider.create_checkout(tenant.id, "starter", db_session)

        assert "checkout_url" in result
        assert "iyzico" in result["checkout_url"]
        assert result["provider"] == "iyzico"

    def test_stripe_provider_checkout_returns_url(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        provider = get_provider("stripe")
        result = provider.create_checkout(tenant.id, "agency", db_session)

        assert "checkout_url" in result
        assert "stripe" in result["checkout_url"]
        assert result["provider"] == "stripe"

    def test_checkout_writes_billing_event(self, db_session: Session) -> None:
        from sqlalchemy import select as sa_select

        tenant = _make_tenant(db_session)
        db_session.commit()

        provider = get_provider("stripe")
        provider.create_checkout(tenant.id, "growth", db_session)

        event = db_session.scalar(
            sa_select(BillingEvent).where(
                BillingEvent.tenant_id == tenant.id,
                BillingEvent.type == "checkout.created",
            )
        )
        assert event is not None
        assert event.payload["plan_code"] == "growth"

    def test_webhook_updates_subscription(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        payload = {
            "tenant_id": str(tenant.id),
            "type": "subscription.renewed",
            "plan_code": "growth",
            "status": "active",
        }
        provider = get_provider("stripe")
        event = provider.handle_webhook(payload, tenant.id, db_session)

        assert event is not None
        assert event.type == "subscription.renewed"

        # Subscription should now reflect the new plan
        from sqlalchemy import select as sa_select
        sub = db_session.scalar(
            sa_select(Subscription).where(Subscription.tenant_id == tenant.id)
        )
        assert sub is not None
        assert sub.plan_code == "growth"

    def test_iyzico_webhook_writes_event(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        db_session.commit()

        provider = get_provider("iyzico")
        payload = {
            "tenant_id": str(tenant.id),
            "type": "subscription.upgraded",
            "plan_code": "starter",
            "status": "trialing",
        }
        event = provider.handle_webhook(payload, tenant.id, db_session)
        assert event.provider == "iyzico"


# ══════════════════════════════════════════════════════════════════════════════
# Billing API endpoint tests
# ══════════════════════════════════════════════════════════════════════════════


class TestBillingAPI:
    def test_get_plans_200(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.get("/api/v1/billing/plans")
        assert resp.status_code == 200

    def test_get_plans_returns_four_tiers(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.get("/api/v1/billing/plans")
        plans = resp.json()
        codes = {p["code"] for p in plans}
        assert codes == {"free", "starter", "growth", "agency"}

    def test_get_plans_free_price_zero(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.get("/api/v1/billing/plans")
        free = next(p for p in resp.json() if p["code"] == "free")
        assert free["price_try"] == 0
        assert free["price_usd"] == 0

    def test_get_subscription_default_free(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.get("/api/v1/billing/subscription")
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan_code"] == "free"
        assert body["status"] == "active"
        assert "entitlements" in body
        assert "data_sources_used" in body

    def test_get_subscription_includes_usage(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.get("/api/v1/billing/subscription")
        body = resp.json()
        assert isinstance(body["data_sources_used"], int)

    def test_checkout_returns_url(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan_code": "growth", "provider": "stripe"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "checkout_url" in body
        assert "checkout.test" in body["checkout_url"]

    def test_checkout_invalid_plan_returns_400(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"plan_code": "enterprise", "provider": "stripe"},
        )
        assert resp.status_code == 400

    def test_cancel_subscription(self, billing_client, db_session: Session) -> None:
        client, tenant, _ = billing_client
        # Create an active subscription first
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="growth",
                status="active",
                provider="stripe",
            )
        )
        db_session.commit()

        resp = client.post("/api/v1/billing/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "canceled"

    def test_webhook_none_provider(self, billing_client, db_session: Session) -> None:
        client, tenant, _ = billing_client
        payload = {
            "tenant_id": str(tenant.id),
            "type": "subscription.renewed",
            "plan_code": "starter",
            "status": "active",
        }
        resp = client.post("/api/v1/billing/webhook/none", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["received"] is True
        assert "event_id" in body

    def test_webhook_iyzico(self, billing_client, db_session: Session) -> None:
        client, tenant, _ = billing_client
        payload = {
            "tenant_id": str(tenant.id),
            "type": "checkout.completed",
            "plan_code": "growth",
            "status": "trialing",
        }
        resp = client.post("/api/v1/billing/webhook/iyzico", json=payload)
        assert resp.status_code == 200

    def test_webhook_stripe(self, billing_client, db_session: Session) -> None:
        client, tenant, _ = billing_client
        payload = {
            "tenant_id": str(tenant.id),
            "type": "invoice.paid",
            "plan_code": "agency",
            "status": "active",
        }
        resp = client.post("/api/v1/billing/webhook/stripe", json=payload)
        assert resp.status_code == 200

    def test_webhook_unknown_provider_400(self, billing_client) -> None:
        client, tenant, _ = billing_client
        payload = {"tenant_id": str(tenant.id)}
        resp = client.post("/api/v1/billing/webhook/paypal", json=payload)
        assert resp.status_code == 400

    def test_webhook_missing_tenant_id_400(self, billing_client) -> None:
        client, _, _ = billing_client
        resp = client.post("/api/v1/billing/webhook/stripe", json={"type": "test"})
        assert resp.status_code == 400

    def test_upgrade_reflected_in_subscription_endpoint(
        self, billing_client, db_session: Session
    ) -> None:
        """After a webhook upgrades the plan, GET /subscription returns new plan."""
        client, tenant, _ = billing_client
        payload = {
            "tenant_id": str(tenant.id),
            "type": "subscription.upgraded",
            "plan_code": "growth",
            "status": "active",
        }
        client.post("/api/v1/billing/webhook/stripe", json=payload)

        resp = client.get("/api/v1/billing/subscription")
        body = resp.json()
        assert body["plan_code"] == "growth"


# ══════════════════════════════════════════════════════════════════════════════
# Connector plan-gating tests
# ══════════════════════════════════════════════════════════════════════════════


class TestConnectorPlanGating:
    def test_create_account_allowed_under_free_limit(
        self, connectors_client
    ) -> None:
        """Free plan allows 1 data source; no accounts yet → 201."""
        client, tenant, _ = connectors_client
        resp = client.post(
            "/api/v1/connectors/accounts",
            json={
                "platform": "sample",
                "external_account_id": "ACC-001",
                "display_name": "Test",
            },
        )
        assert resp.status_code == 201

    def test_create_account_blocked_at_free_limit(
        self, connectors_client, db_session: Session
    ) -> None:
        """Free plan allows 1 data source; 1 already linked → 402."""
        client, tenant, _ = connectors_client
        # Insert one account directly so we're at the limit
        _make_connected_account(db_session, tenant, Platform.sample)
        db_session.commit()

        resp = client.post(
            "/api/v1/connectors/accounts",
            json={
                "platform": "google_ads",
                "external_account_id": "ACC-002",
                "display_name": "Second",
            },
        )
        assert resp.status_code == 402
        assert "yükseltin" in resp.json()["detail"].lower() or "limit" in resp.json()["detail"].lower()

    def test_create_account_allowed_for_agency(
        self, connectors_client, db_session: Session
    ) -> None:
        """Agency plan is unlimited; many accounts → 201."""
        client, tenant, _ = connectors_client
        # Set agency subscription
        db_session.add(
            Subscription(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                plan_code="agency",
                status="active",
                provider="stripe",
            )
        )
        # Add many accounts
        for plat in [Platform.google_ads, Platform.meta_ads, Platform.ga4,
                     Platform.search_console, Platform.tiktok_ads,
                     Platform.linkedin_ads, Platform.microsoft_ads,
                     Platform.sample]:
            _make_connected_account(db_session, tenant, plat)
        db_session.commit()

        resp = client.post(
            "/api/v1/connectors/accounts",
            json={
                "platform": "google_ads",
                "external_account_id": "ACC-NEW",
                "display_name": "Agency Account",
            },
        )
        assert resp.status_code == 201
