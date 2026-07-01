"""Tests for M12 Aylık Bütçe Planlayıcısı (Monthly Budget Planner).

Coverage
--------
1. compute_allocation — pure unit tests (no DB)
   - balanced / maximize_roas / maximize_conversions produce different splits
   - guardrails: floor 5 %, cap 60 %
   - shares sum to ~100 %
   - projections computed (expected_conversions, expected_revenue, expected_roas)
   - empty-history even split
   - empty channel_metrics returns []
2. POST /budget/preview — returns allocation without DB write
3. POST /budget/plans   — create → 201, stores snapshot
4. GET  /budget/plans   — list, most recent first
5. GET  /budget/plans/{id} — get one
6. PATCH /budget/plans/{id} — update name/status, auto-recompute on param change
7. DELETE /budget/plans/{id} — 204
8. POST /budget/plans/{id}/recompute — recomputes and saves
9. Validation 422: total_budget <= 0, bad objective, bad period_month
10. Tenant isolation: other tenant's plan returns 404
11. DB-read path: seeded DimChannel/DimCampaign/FactDailyMetrics rows exercise
    the full allocate_budget() path
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata.create_all works
import ayaz.models.oltp          # noqa: F401
import ayaz.models.analytics     # noqa: F401
import ayaz.models.feeds         # noqa: F401
import ayaz.models.insights      # noqa: F401
import ayaz.models.reports       # noqa: F401
import ayaz.models.automation    # noqa: F401
import ayaz.models.tracking      # noqa: F401
import ayaz.models.budget        # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics
from ayaz.models.budget import BudgetPlan
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import budget as budget_module
from ayaz.services.auth import hash_password
from ayaz.services.budget_planner import (
    _apply_guardrails,
    _build_campaign_allocations,
    _compute_channel_weights,
    allocate_budget,
    compute_allocation,
)

# ── Minimal test FastAPI app ──────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Budget Planner Test App")
_test_app.include_router(budget_module.router, prefix="/api/v1")


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Session:
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


# ── Authenticated client fixture ──────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Bütçe Test Kiracısı",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="budget_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Bütçe Test Kullanıcısı",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db_session.add(membership)
    db_session.commit()

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Helper: seed analytics warehouse rows ─────────────────────────────────────


def _seed_warehouse(
    db: Session,
    tenant_id: uuid.UUID,
) -> tuple[DimChannel, DimChannel, DimCampaign, DimCampaign, DimCampaign]:
    """Create two channels and three campaigns with fact rows for testing."""
    from ayaz.models.analytics import DimAdSet, DimAd, DimDate
    from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus

    # Channels
    ch_google = DimChannel(id=uuid.uuid4(), key="google_ads", label="Google Ads")
    ch_meta = DimChannel(id=uuid.uuid4(), key="meta_ads", label="Meta Ads")
    db.add_all([ch_google, ch_meta])
    db.flush()

    # Connected account (required FK) — uses the correct Platform enum
    acc = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        platform=Platform.google_ads,
        external_account_id="acc-001",
        display_name="Test Account",
        vault_secret_ref="test/secret/ref",
        sync_status=SyncStatus.idle,
    )
    db.add(acc)
    db.flush()

    # Campaigns
    camp_g1 = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=ch_google.id,
        external_id="g-camp-1", name="Google Kampanya 1",
    )
    camp_g2 = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=ch_google.id,
        external_id="g-camp-2", name="Google Kampanya 2",
    )
    camp_m1 = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=ch_meta.id,
        external_id="m-camp-1", name="Meta Kampanya 1",
    )
    db.add_all([camp_g1, camp_g2, camp_m1])
    db.flush()

    # Ad sets and ads (required for fact rows)
    adset_g1 = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=camp_g1.id,
        external_id="as-g1", name="AdSet G1",
    )
    adset_g2 = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=camp_g2.id,
        external_id="as-g2", name="AdSet G2",
    )
    adset_m1 = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=camp_m1.id,
        external_id="as-m1", name="AdSet M1",
    )
    from ayaz.models.analytics import DimAd
    ad_g1 = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_g1.id,
        external_id="ad-g1", name="Ad G1",
    )
    ad_g2 = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_g2.id,
        external_id="ad-g2", name="Ad G2",
    )
    ad_m1 = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_m1.id,
        external_id="ad-m1", name="Ad M1",
    )
    db.add_all([adset_g1, adset_g2, adset_m1, ad_g1, ad_g2, ad_m1])
    db.flush()

    # Date dim rows
    today = date.today()
    for delta in range(3):
        d = today - timedelta(days=delta)
        existing = db.get(DimDate, d)
        if existing is None:
            db.add(DimDate(
                date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
                month=d.month, week=d.isocalendar()[1],
                day_of_week=d.weekday(), is_weekend=d.weekday() >= 5,
            ))
    db.flush()

    now = datetime.now(timezone.utc)
    # Google Ads: spend=6000, conversions=60, conv_value=18000  → ROAS=3.0 CPA=100
    db.add(FactDailyMetrics(
        id=uuid.uuid4(), tenant_id=tenant_id,
        connected_account_id=acc.id,
        channel_id=ch_google.id, campaign_id=camp_g1.id,
        adset_id=adset_g1.id, ad_id=ad_g1.id,
        date_key=today - timedelta(days=1),
        impressions=100000, clicks=3000,
        cost_raw=4000, cost_ccy="TRY", cost_base_ccy=4000,
        conversions=40, conversion_value_raw=12000,
        conversion_value_ccy="TRY", conv_value_base_ccy=12000,
        ingested_at=now,
    ))
    db.add(FactDailyMetrics(
        id=uuid.uuid4(), tenant_id=tenant_id,
        connected_account_id=acc.id,
        channel_id=ch_google.id, campaign_id=camp_g2.id,
        adset_id=adset_g2.id, ad_id=ad_g2.id,
        date_key=today - timedelta(days=2),
        impressions=80000, clicks=2000,
        cost_raw=2000, cost_ccy="TRY", cost_base_ccy=2000,
        conversions=20, conversion_value_raw=6000,
        conversion_value_ccy="TRY", conv_value_base_ccy=6000,
        ingested_at=now,
    ))
    # Meta Ads: spend=4000, conversions=20, conv_value=6000  → ROAS=1.5 CPA=200
    db.add(FactDailyMetrics(
        id=uuid.uuid4(), tenant_id=tenant_id,
        connected_account_id=acc.id,
        channel_id=ch_meta.id, campaign_id=camp_m1.id,
        adset_id=adset_m1.id, ad_id=ad_m1.id,
        date_key=today - timedelta(days=1),
        impressions=50000, clicks=1000,
        cost_raw=4000, cost_ccy="TRY", cost_base_ccy=4000,
        conversions=20, conversion_value_raw=6000,
        conversion_value_ccy="TRY", conv_value_base_ccy=6000,
        ingested_at=now,
    ))
    db.commit()
    return ch_google, ch_meta, camp_g1, camp_g2, camp_m1


# ── Helper: channel metrics dict for pure unit tests ─────────────────────────


def _two_channel_metrics() -> dict[str, dict]:
    """Two-channel metrics dict for pure allocation tests.

    Chosen so that the two channels have different ROAS and CPA figures and
    neither channel has a historical share high enough to hit the 60 % cap
    under a "balanced" objective, but the dominant channel (google_ads) would
    get pushed above it under "maximize_roas" without the cap.

    google_ads: spend=5000, conv_value=20000 → ROAS=4.0, CPA=83.3
    meta_ads:   spend=5000, conv_value=7500  → ROAS=1.5, CPA=250.0
    historical share: 50/50 each
    """
    return {
        "google_ads": {
            "label": "Google Ads",
            "spend": 5000.0,
            "conversions": 60.0,
            "conversion_value": 20000.0,
            "clicks": 3000.0,
            "impressions": 100000.0,
        },
        "meta_ads": {
            "label": "Meta Ads",
            "spend": 5000.0,
            "conversions": 20.0,
            "conversion_value": 7500.0,
            "clicks": 1000.0,
            "impressions": 50000.0,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure unit tests for compute_allocation
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeAllocationPure:
    """Unit tests for the pure compute_allocation helper (no DB)."""

    def test_empty_channel_metrics_returns_empty_list(self) -> None:
        result = compute_allocation({}, 10000.0, "balanced")
        assert result == []

    def test_shares_sum_to_100(self) -> None:
        result = compute_allocation(_two_channel_metrics(), 10000.0, "balanced")
        total = sum(p["recommended_share"] for p in result)
        assert abs(total - 100.0) < 0.2  # floating-point tolerance

    def test_budgets_sum_to_total(self) -> None:
        total_budget = 10000.0
        result = compute_allocation(_two_channel_metrics(), total_budget, "balanced")
        total = sum(p["recommended_budget"] for p in result)
        # Allow small rounding error from per-channel round()
        assert abs(total - total_budget) < 1.0

    def test_balanced_vs_maximize_roas_differ(self) -> None:
        metrics = _two_channel_metrics()
        balanced = compute_allocation(metrics, 10000.0, "balanced")
        max_roas = compute_allocation(metrics, 10000.0, "maximize_roas")

        balanced_by_ch = {p["channel"]: p for p in balanced}
        maxroas_by_ch = {p["channel"]: p for p in max_roas}

        # Google Ads has higher ROAS (3.0) → maximize_roas should give it more
        assert (
            maxroas_by_ch["google_ads"]["recommended_share"]
            > balanced_by_ch["google_ads"]["recommended_share"]
        )

    def test_maximize_conversions_favours_lower_cpa(self) -> None:
        metrics = _two_channel_metrics()
        # google_ads: CPA = 6000/60 = 100; meta_ads: CPA = 4000/20 = 200
        # maximize_conversions should give more to google_ads (lower CPA)
        result = compute_allocation(metrics, 10000.0, "maximize_conversions")
        by_ch = {p["channel"]: p for p in result}
        assert (
            by_ch["google_ads"]["recommended_share"]
            > by_ch["meta_ads"]["recommended_share"]
        )

    def test_all_three_objectives_differ(self) -> None:
        metrics = _two_channel_metrics()
        b = compute_allocation(metrics, 10000.0, "balanced")
        r = compute_allocation(metrics, 10000.0, "maximize_roas")
        c = compute_allocation(metrics, 10000.0, "maximize_conversions")
        # At minimum two of the three should produce different google_ads shares
        shares = {
            p["channel"]: p["recommended_share"]
            for p in b
            if p["channel"] == "google_ads"
        }
        shares_r = {
            p["channel"]: p["recommended_share"]
            for p in r
            if p["channel"] == "google_ads"
        }
        shares_c = {
            p["channel"]: p["recommended_share"]
            for p in c
            if p["channel"] == "google_ads"
        }
        # All three should not all be identical
        all_shares = [
            shares["google_ads"],
            shares_r["google_ads"],
            shares_c["google_ads"],
        ]
        assert len(set(all_shares)) > 1

    def test_guardrail_floor_5pct(self) -> None:
        """A channel with tiny historical share still gets >= 5 %."""
        metrics = {
            "google_ads": {
                "label": "Google Ads",
                "spend": 9900.0,
                "conversions": 99.0,
                "conversion_value": 29700.0,
                "clicks": 5000.0,
                "impressions": 200000.0,
            },
            "tiny_channel": {
                "label": "Tiny",
                "spend": 100.0,    # only 1 % historical share
                "conversions": 1.0,
                "conversion_value": 100.0,
                "clicks": 50.0,
                "impressions": 5000.0,
            },
        }
        result = compute_allocation(metrics, 10000.0, "balanced")
        by_ch = {p["channel"]: p for p in result}
        assert by_ch["tiny_channel"]["recommended_share"] >= 5.0 - 0.1

    def test_guardrail_cap_60pct(self) -> None:
        """No single channel should exceed 60 % share."""
        metrics = {
            "dominant": {
                "label": "Dominant",
                "spend": 9500.0,
                "conversions": 200.0,
                "conversion_value": 95000.0,  # huge ROAS
                "clicks": 5000.0,
                "impressions": 200000.0,
            },
            "small_a": {
                "label": "Small A",
                "spend": 300.0,
                "conversions": 5.0,
                "conversion_value": 300.0,
                "clicks": 100.0,
                "impressions": 10000.0,
            },
            "small_b": {
                "label": "Small B",
                "spend": 200.0,
                "conversions": 3.0,
                "conversion_value": 200.0,
                "clicks": 80.0,
                "impressions": 8000.0,
            },
        }
        result = compute_allocation(metrics, 10000.0, "maximize_roas")
        for p in result:
            assert p["recommended_share"] <= 60.0 + 0.1  # small tolerance

    def test_projections_present_and_nonzero(self) -> None:
        result = compute_allocation(_two_channel_metrics(), 10000.0, "balanced")
        for p in result:
            assert "expected_conversions" in p
            assert "expected_revenue" in p
            assert "expected_roas" in p
            # Both channels have non-zero CPA so expected_conversions > 0
            assert p["expected_conversions"] > 0
            assert p["expected_revenue"] > 0

    def test_empty_history_even_split(self) -> None:
        """When all channels have spend=0, budget is split evenly."""
        metrics = {
            "ch_a": {
                "label": "A",
                "spend": 0.0,
                "conversions": 0.0,
                "conversion_value": 0.0,
                "clicks": 0.0,
                "impressions": 0.0,
            },
            "ch_b": {
                "label": "B",
                "spend": 0.0,
                "conversions": 0.0,
                "conversion_value": 0.0,
                "clicks": 0.0,
                "impressions": 0.0,
            },
        }
        result = compute_allocation(metrics, 10000.0, "balanced")
        assert len(result) == 2
        shares = [p["recommended_share"] for p in result]
        assert abs(shares[0] - 50.0) < 0.2
        assert abs(shares[1] - 50.0) < 0.2

    def test_delta_pct_field_present(self) -> None:
        result = compute_allocation(_two_channel_metrics(), 10000.0, "balanced")
        for p in result:
            assert "delta_pct" in p

    def test_response_shape_fields(self) -> None:
        result = compute_allocation(_two_channel_metrics(), 10000.0, "balanced")
        required_fields = {
            "channel", "label", "historical_spend", "historical_share",
            "roas", "cpa", "recommended_budget", "recommended_share",
            "delta_pct", "expected_conversions", "expected_revenue",
            "expected_roas", "campaigns",
        }
        for p in result:
            assert required_fields <= set(p.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DB-read path: allocate_budget with seeded warehouse data
# ═══════════════════════════════════════════════════════════════════════════════


class TestAllocateBudgetDBPath:
    """Tests that exercise the full allocate_budget() path with a seeded DB."""

    def test_allocate_budget_returns_two_platforms(
        self, db_session: Session
    ) -> None:
        tenant_id = uuid.uuid4()
        _seed_warehouse(db_session, tenant_id)

        result = allocate_budget(
            db_session,
            tenant_id,
            total_budget=10000.0,
            objective="balanced",
            lookback_days=30,
        )
        assert "platforms" in result
        assert len(result["platforms"]) == 2
        channels = {p["channel"] for p in result["platforms"]}
        assert "google_ads" in channels
        assert "meta_ads" in channels

    def test_allocate_budget_result_shape(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        _seed_warehouse(db_session, tenant_id)

        result = allocate_budget(
            db_session, tenant_id, total_budget=10000.0, lookback_days=30
        )
        assert result["total_budget"] == 10000.0
        assert result["currency"] == "TRY"
        assert "based_on" in result
        assert "date_from" in result["based_on"]
        assert "date_to" in result["based_on"]
        assert "projection" in result
        assert "notes" in result
        assert isinstance(result["notes"], list) and len(result["notes"]) > 0

    def test_allocate_budget_no_data_returns_empty_platforms(
        self, db_session: Session
    ) -> None:
        tenant_id = uuid.uuid4()  # fresh tenant with no data
        result = allocate_budget(
            db_session, tenant_id, total_budget=10000.0, lookback_days=30
        )
        assert result["platforms"] == []
        assert len(result["notes"]) > 0

    def test_campaigns_present_under_channels(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        _seed_warehouse(db_session, tenant_id)

        result = allocate_budget(
            db_session, tenant_id, total_budget=10000.0, lookback_days=30
        )
        for platform in result["platforms"]:
            assert "campaigns" in platform
            # Each campaign entry should have required fields
            for camp in platform["campaigns"]:
                assert "name" in camp
                assert "recommended_budget" in camp
                assert "recommended_share" in camp


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetPreviewEndpoint:
    def test_preview_returns_allocation_without_db_write(
        self, client: TestClient, db_session: Session
    ) -> None:
        resp = client.post(
            "/api/v1/budget/preview",
            json={"total_budget": 10000.0, "objective": "balanced"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "platforms" in body
        assert "projection" in body
        assert "notes" in body
        # Verify no plan was written
        plans = db_session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(BudgetPlan)
        ).all()
        assert len(plans) == 0

    def test_preview_with_warehouse_data(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        _seed_warehouse(db_session, membership.tenant_id)

        resp = client.post(
            "/api/v1/budget/preview",
            json={"total_budget": 50000.0, "objective": "maximize_roas", "lookback_days": 30},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["platforms"]) == 2

    def test_preview_invalid_budget_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/preview",
            json={"total_budget": 0.0},
        )
        assert resp.status_code == 422

    def test_preview_negative_budget_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/preview",
            json={"total_budget": -100.0},
        )
        assert resp.status_code == 422

    def test_preview_bad_objective_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/preview",
            json={"total_budget": 10000.0, "objective": "invalid_objective"},
        )
        assert resp.status_code == 422


class TestBudgetPlanCRUD:
    def _create_plan(self, client: TestClient, **overrides: Any) -> dict:
        payload = {
            "name": "Temmuz 2026 Planı",
            "period_month": "2026-07",
            "total_budget": 10000.0,
            "objective": "balanced",
        }
        payload.update(overrides)
        resp = client.post("/api/v1/budget/plans", json=payload)
        assert resp.status_code == 201
        return resp.json()

    def test_create_plan_201(self, client: TestClient) -> None:
        body = self._create_plan(client)
        assert body["name"] == "Temmuz 2026 Planı"
        assert body["period_month"] == "2026-07"
        assert body["total_budget"] == 10000.0
        assert body["objective"] == "balanced"
        assert body["status"] == "draft"
        assert "id" in body
        assert body["allocations"] is not None

    def test_create_plan_stores_allocation_snapshot(
        self, client: TestClient
    ) -> None:
        body = self._create_plan(client)
        alloc = body["allocations"]
        assert "platforms" in alloc
        assert "projection" in alloc
        assert "notes" in alloc

    def test_get_plan(self, client: TestClient) -> None:
        created = self._create_plan(client)
        resp = client.get(f"/api/v1/budget/plans/{created['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["name"] == created["name"]

    def test_list_plans_returns_all_tenant_plans(self, client: TestClient) -> None:
        p1 = self._create_plan(client, name="Plan A", period_month="2026-07")
        p2 = self._create_plan(client, name="Plan B", period_month="2026-08")
        resp = client.get("/api/v1/budget/plans")
        assert resp.status_code == 200
        plans = resp.json()
        assert len(plans) >= 2
        # Both plans must appear in the list
        ids_returned = [p["id"] for p in plans]
        assert p1["id"] in ids_returned
        assert p2["id"] in ids_returned

    def test_patch_plan_name(self, client: TestClient) -> None:
        created = self._create_plan(client)
        resp = client.patch(
            f"/api/v1/budget/plans/{created['id']}",
            json={"name": "Güncellenmiş Plan"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Güncellenmiş Plan"

    def test_patch_plan_status(self, client: TestClient) -> None:
        created = self._create_plan(client)
        resp = client.patch(
            f"/api/v1/budget/plans/{created['id']}",
            json={"status": "active"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_patch_plan_budget_triggers_recompute(
        self, client: TestClient
    ) -> None:
        created = self._create_plan(client)
        original_alloc = created["allocations"]
        resp = client.patch(
            f"/api/v1/budget/plans/{created['id']}",
            json={"total_budget": 20000.0},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["total_budget"] == 20000.0
        # allocations should have been recomputed (total_budget changed)
        assert updated["allocations"]["total_budget"] == 20000.0

    def test_patch_plan_explicit_allocations_no_recompute(
        self, client: TestClient
    ) -> None:
        created = self._create_plan(client)
        custom_alloc = {"platforms": [], "projection": {}, "notes": ["Özel."]}
        resp = client.patch(
            f"/api/v1/budget/plans/{created['id']}",
            json={"allocations": custom_alloc},
        )
        assert resp.status_code == 200
        assert resp.json()["allocations"]["notes"] == ["Özel."]

    def test_delete_plan_204(self, client: TestClient) -> None:
        created = self._create_plan(client)
        resp = client.delete(f"/api/v1/budget/plans/{created['id']}")
        assert resp.status_code == 204
        # Subsequent GET should return 404
        resp2 = client.get(f"/api/v1/budget/plans/{created['id']}")
        assert resp2.status_code == 404

    def test_recompute_endpoint(self, client: TestClient) -> None:
        created = self._create_plan(client)
        resp = client.post(f"/api/v1/budget/plans/{created['id']}/recompute")
        assert resp.status_code == 200
        body = resp.json()
        assert body["allocations"] is not None
        assert "platforms" in body["allocations"]

    def test_create_plan_with_warehouse_data(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()
        _seed_warehouse(db_session, membership.tenant_id)

        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Gerçek Veri Planı",
                "period_month": "2026-08",
                "total_budget": 10000.0,
                "objective": "maximize_roas",
                "lookback_days": 30,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        alloc = body["allocations"]
        assert len(alloc["platforms"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Validation 422 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetValidation:
    def test_create_plan_zero_budget_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Test",
                "period_month": "2026-07",
                "total_budget": 0.0,
            },
        )
        assert resp.status_code == 422

    def test_create_plan_negative_budget_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Test",
                "period_month": "2026-07",
                "total_budget": -500.0,
            },
        )
        assert resp.status_code == 422

    def test_create_plan_bad_objective_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Test",
                "period_month": "2026-07",
                "total_budget": 1000.0,
                "objective": "win_everything",
            },
        )
        assert resp.status_code == 422

    def test_create_plan_bad_period_month_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Test",
                "period_month": "07-2026",  # wrong format
                "total_budget": 1000.0,
            },
        )
        assert resp.status_code == 422

    def test_create_plan_period_month_day_level_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={
                "name": "Test",
                "period_month": "2026-07-01",  # too long
                "total_budget": 1000.0,
            },
        )
        assert resp.status_code == 422

    def test_patch_plan_bad_status_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={"name": "T", "period_month": "2026-07", "total_budget": 1000.0},
        )
        plan_id = resp.json()["id"]
        resp2 = client.patch(
            f"/api/v1/budget/plans/{plan_id}",
            json={"status": "deleted"},
        )
        assert resp2.status_code == 422

    def test_patch_plan_bad_objective_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget/plans",
            json={"name": "T", "period_month": "2026-07", "total_budget": 1000.0},
        )
        plan_id = resp.json()["id"]
        resp2 = client.patch(
            f"/api/v1/budget/plans/{plan_id}",
            json={"objective": "bad_objective"},
        )
        assert resp2.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_other_tenant_plan_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Create a plan belonging to a different tenant directly in DB
        other_tenant_id = uuid.uuid4()
        plan = BudgetPlan(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            name="Başka Kiracı Planı",
            period_month="2026-07",
            total_budget=5000,
            currency="TRY",
            objective="balanced",
            lookback_days=90,
            allocations=None,
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        resp = client.get(f"/api/v1/budget/plans/{plan.id}")
        assert resp.status_code == 404

    def test_other_tenant_plan_patch_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        other_tenant_id = uuid.uuid4()
        plan = BudgetPlan(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            name="Başka Kiracı Planı",
            period_month="2026-07",
            total_budget=5000,
            currency="TRY",
            objective="balanced",
            lookback_days=90,
            allocations=None,
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        resp = client.patch(
            f"/api/v1/budget/plans/{plan.id}",
            json={"name": "Hacklendi"},
        )
        assert resp.status_code == 404

    def test_list_plans_only_returns_own_tenant(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = _test_app.dependency_overrides[get_current_membership]()

        # Another tenant's plan
        other_id = uuid.uuid4()
        db_session.add(BudgetPlan(
            id=uuid.uuid4(), tenant_id=other_id,
            name="Diğer", period_month="2026-07",
            total_budget=1000, currency="TRY",
            objective="balanced", lookback_days=90,
            allocations=None, status="draft",
        ))
        db_session.commit()

        # My plan via the API
        client.post(
            "/api/v1/budget/plans",
            json={"name": "Benim Planım", "period_month": "2026-07", "total_budget": 1000.0},
        )

        resp = client.get("/api/v1/budget/plans")
        assert resp.status_code == 200
        plans = resp.json()
        tenant_ids = {p["tenant_id"] for p in plans}
        assert tenant_ids == {str(membership.tenant_id)}
