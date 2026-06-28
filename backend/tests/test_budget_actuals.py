"""Tests for Budget Plan vs Actual (Dalga 66)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.budget  # noqa: F401

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import budget as budget_module
from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.base import Base
from ayaz.models.budget import BudgetPlan
from ayaz.models.oltp import Membership, MembershipRole
from ayaz.services.budget_planner import _month_bounds, plan_actuals


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield s
    finally:
        s.close()


def _seed_facts(db: Session, tenant_id: uuid.UUID, month: str) -> None:
    """Seed one channel with spend in the given YYYY-MM month."""
    ch = DimChannel(id=uuid.uuid4(), key="meta_ads", label="Meta Ads")
    db.add(ch)
    db.flush()
    y, m = int(month[:4]), int(month[5:7])
    for day in (5, 10, 15):
        db.add(FactDailyMetrics(
            tenant_id=tenant_id,
            connected_account_id=uuid.uuid4(),
            channel_id=ch.id,
            campaign_id=uuid.uuid4(),
            adset_id=uuid.uuid4(),
            ad_id=uuid.uuid4(),
            date_key=date(y, m, day),
            impressions=1000, clicks=100,
            cost_raw=Decimal("1000"), cost_ccy="TRY",
            cost_base_ccy=Decimal("1000"),
            conversions=Decimal("10"),
            conversion_value_raw=Decimal("4000"), conversion_value_ccy="TRY",
            conv_value_base_ccy=Decimal("4000"),
            ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
    db.commit()


def _make_plan(db: Session, tenant_id: uuid.UUID, month: str) -> BudgetPlan:
    plan = BudgetPlan(
        tenant_id=tenant_id, name=f"{month} Planı", period_month=month,
        total_budget=Decimal("10000"), currency="TRY", objective="balanced",
        lookback_days=90,
        allocations={
            "platforms": [
                {"channel": "meta_ads", "label": "Meta Ads",
                 "recommended_budget": 10000.0, "recommended_share": 100.0,
                 "expected_revenue": 30000.0, "expected_conversions": 100.0},
            ],
            "projection": {"expected_revenue": 30000.0, "expected_roas": 3.0},
        },
        status="active",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


class TestMonthBounds:
    def test_past_month_full(self) -> None:
        # as_of well after the month → full month elapsed
        ms, end, dim, elapsed = _month_bounds("2026-01", as_of=date(2026, 6, 1))
        assert ms == date(2026, 1, 1)
        assert dim == 31 and elapsed == 31

    def test_future_month_zero(self) -> None:
        ms, end, dim, elapsed = _month_bounds("2026-12", as_of=date(2026, 6, 1))
        assert elapsed == 0

    def test_in_progress(self) -> None:
        ms, end, dim, elapsed = _month_bounds("2026-06", as_of=date(2026, 6, 15))
        assert end == date(2026, 6, 15)
        assert elapsed == 15


class TestPlanActuals:
    def test_actuals_with_data(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _seed_facts(db_session, tid, "2026-03")
        plan = _make_plan(db_session, tid, "2026-03")
        # as_of after the month → full actuals (3 days * 1000 = 3000 spend)
        result = plan_actuals(db_session, tid, plan, as_of=date(2026, 6, 1))
        assert result["totals"]["actual_spend"] == 3000.0
        assert result["totals"]["planned_budget"] == 10000.0
        assert result["totals"]["pace_pct"] == 30.0  # 3000/10000
        meta = next(c for c in result["channels"] if c["channel"] == "meta_ads")
        assert meta["actual_spend"] == 3000.0
        assert meta["actual_roas"] == 4.0  # 12000 rev / 3000 spend
        assert "notes" in result and result["notes"]

    def test_no_actuals_future(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        plan = _make_plan(db_session, tid, "2026-12")
        result = plan_actuals(db_session, tid, plan, as_of=date(2026, 6, 1))
        assert result["totals"]["actual_spend"] == 0.0
        assert result["days_elapsed"] == 0


class TestActualsEndpoint:
    def _client(self, db: Session, tenant_id: uuid.UUID) -> TestClient:
        app = FastAPI()
        app.include_router(budget_module.router, prefix="/api/v1")
        membership = Membership(
            id=uuid.uuid4(), tenant_id=tenant_id, user_id=uuid.uuid4(),
            role=MembershipRole.owner,
        )

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_membership] = lambda: membership
        return TestClient(app)

    def test_endpoint_returns_actuals(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        _seed_facts(db_session, tid, "2026-03")
        plan = _make_plan(db_session, tid, "2026-03")
        client = self._client(db_session, tid)
        resp = client.get(f"/api/v1/budget/plans/{plan.id}/actuals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["period_month"] == "2026-03"
        assert "totals" in body and "channels" in body

    def test_endpoint_404_other_tenant(self, db_session: Session) -> None:
        tid = uuid.uuid4()
        client = self._client(db_session, tid)
        resp = client.get(f"/api/v1/budget/plans/{uuid.uuid4()}/actuals")
        assert resp.status_code == 404
