"""Tests for Marcom Kreatif Lensi — creative engagement insights.

Coverage
--------
1. _engagement_insight (pure unit tests — no HTTP, no DB)
   - high engagement tier (ctr >= 1.2 * avg)
   - medium engagement tier
   - low engagement tier (ctr < 0.8 * avg)
   - traffic share reflected in text
   - zero avg_ctr falls back gracefully (orta ilgi)

2. creative_insights service (seeded SQLite DB)
   - totals correct (impressions, clicks, conversions, ctr, count)
   - sorted by clicks descending
   - traffic_share_pct sums to ~100 across all returned creatives (all ≤ limit)
   - top_creatives limited by limit parameter
   - empty warehouse → empty top_creatives + fallback headline

3. GET /marcom/creative-insights endpoint
   - happy path: 200, response shape validated
   - default date range applied when params omitted
   - explicit date_from/date_to used when provided
   - date_from > date_to → 422
   - unauthenticated → 401/403
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta, timezone, datetime as _dt
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata.create_all works
import ayaz.models.oltp        # noqa: F401
import ayaz.models.analytics   # noqa: F401
import ayaz.models.feeds       # noqa: F401
import ayaz.models.insights    # noqa: F401
import ayaz.models.reports     # noqa: F401
import ayaz.models.automation  # noqa: F401
import ayaz.models.tracking    # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import (
    ConnectedAccount, Membership, MembershipRole, Platform,
    SyncStatus, Tenant, User,
)
from ayaz.models.analytics import (
    DimAd, DimAdSet, DimCampaign, DimChannel, DimDate, FactDailyMetrics,
)
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import marcom as marcom_module
from ayaz.services.marcom import _engagement_insight, creative_insights
from ayaz.services.auth import hash_password

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Marcom Test App")
_test_app.include_router(marcom_module.router, prefix="/api/v1")

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


# ── Tenant/user/membership helpers ───────────────────────────────────────────


def _make_tenant_and_membership(db: Session) -> tuple[Tenant, User, Membership]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Marcom Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email=f"marcom_{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Marcom Test User",
    )
    db.add(tenant)
    db.add(user)
    db.flush()

    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.commit()
    return tenant, user, membership


# ── Warehouse seeding helpers ─────────────────────────────────────────────────


def _ensure_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week, day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _make_channel(db: Session, key: str = "google_ads") -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_connected_account(db: Session, tenant_id: uuid.UUID) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant_id, platform=Platform.google_ads,
        external_account_id=f"ext-{uuid.uuid4().hex}",
        display_name="Test Account", vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_campaign(db: Session, tenant_id: uuid.UUID, channel_id: uuid.UUID,
                   name: str = "Test Kampanyası") -> DimCampaign:
    camp = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=channel_id,
        external_id=f"ext-{uuid.uuid4().hex}", name=name,
    )
    db.add(camp)
    db.flush()
    return camp


def _make_adset(db: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID,
                name: str = "Test AdSet") -> DimAdSet:
    adset = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=campaign_id,
        external_id=f"ext-{uuid.uuid4().hex}", name=name,
    )
    db.add(adset)
    db.flush()
    return adset


def _make_ad(db: Session, tenant_id: uuid.UUID, adset_id: uuid.UUID,
             name: str = "Test Reklam") -> DimAd:
    # DimAd uses ad_set_id (not adset_id) as the mapped attribute name.
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_id,
        external_id=f"ext-{uuid.uuid4().hex}", name=name,
    )
    db.add(ad)
    db.flush()
    return ad


def _make_fact(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    channel_id: uuid.UUID,
    campaign_id: uuid.UUID,
    adset_id: uuid.UUID,
    ad_id: uuid.UUID,
    date_key: date,
    impressions: int = 0,
    clicks: int = 0,
    cost_raw: float = 0.0,
    conversions: float = 0.0,
    conversion_value: float = 0.0,
) -> FactDailyMetrics:
    from decimal import Decimal as D
    _ensure_dim_date(db, date_key)
    fact = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connected_account_id=account_id,
        channel_id=channel_id,
        campaign_id=campaign_id,
        adset_id=adset_id,
        ad_id=ad_id,
        date_key=date_key,
        impressions=impressions,
        clicks=clicks,
        cost_raw=D(str(cost_raw)),
        cost_base_ccy=D(str(cost_raw)),
        cost_ccy="TRY",
        conversions=D(str(conversions)),
        conversion_value_raw=D(str(conversion_value)),
        conversion_value_ccy="TRY",
        conv_value_base_ccy=D(str(conversion_value)),
        ingested_at=_dt.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


def _seed_three_ads(db: Session, tenant_id: uuid.UUID, ref_date: date) -> None:
    """Seed three ads with different click levels for sorting / tiering tests."""
    ch    = _make_channel(db, "google_ads")
    acct  = _make_connected_account(db, tenant_id)
    camp  = _make_campaign(db, tenant_id, ch.id, "Yaz Kampanyası")
    adset = _make_adset(db, tenant_id, camp.id)

    # Ad A: highest clicks (500), high CTR 5%
    ad_a = _make_ad(db, tenant_id, adset.id, "Banner A")
    _make_fact(db, tenant_id=tenant_id, account_id=acct.id,
               channel_id=ch.id, campaign_id=camp.id,
               adset_id=adset.id, ad_id=ad_a.id, date_key=ref_date,
               impressions=10_000, clicks=500, cost_raw=200.0, conversions=20.0)

    # Ad B: middle clicks (200), CTR 2%
    ad_b = _make_ad(db, tenant_id, adset.id, "Carousel B")
    _make_fact(db, tenant_id=tenant_id, account_id=acct.id,
               channel_id=ch.id, campaign_id=camp.id,
               adset_id=adset.id, ad_id=ad_b.id, date_key=ref_date,
               impressions=10_000, clicks=200, cost_raw=100.0, conversions=8.0)

    # Ad C: lowest clicks (100), CTR 1%
    ad_c = _make_ad(db, tenant_id, adset.id, "Video C")
    _make_fact(db, tenant_id=tenant_id, account_id=acct.id,
               channel_id=ch.id, campaign_id=camp.id,
               adset_id=adset.id, ad_id=ad_c.id, date_key=ref_date,
               impressions=10_000, clicks=100, cost_raw=50.0, conversions=2.0)

    db.commit()


# ── Client fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    _, _, membership = _make_tenant_and_membership(db_session)

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


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override (tests 401/403 behaviour)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()

    def override_db():
        try:
            yield session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(engine)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _engagement_insight — pure unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngagementInsight:
    """Unit-test the pure insight helper with synthetic ad dicts."""

    def _ad(self, clicks: int, ctr_ratio: float) -> dict[str, Any]:
        return {"ad_name": "Test Reklam", "clicks": clicks, "ctr": ctr_ratio}

    def test_high_engagement_tier(self) -> None:
        """CTR well above average → 'yüksek ilgi' in insight."""
        ad = self._ad(clicks=1000, ctr_ratio=0.06)   # 6%
        avg = 0.04                                    # 4%; 6 >= 4*1.2 = 4.8 → high
        result = _engagement_insight(ad, avg, total_clicks=2000.0)
        assert "yüksek ilgi" in result

    def test_low_engagement_tier(self) -> None:
        """CTR well below average → 'düşük ilgi' in insight."""
        ad = self._ad(clicks=50, ctr_ratio=0.01)    # 1%
        avg = 0.05                                   # 5%; 1 < 5*0.8 = 4 → low
        result = _engagement_insight(ad, avg, total_clicks=500.0)
        assert "düşük ilgi" in result

    def test_medium_engagement_tier(self) -> None:
        """CTR close to average → 'orta ilgi' in insight."""
        ad = self._ad(clicks=300, ctr_ratio=0.04)   # 4%
        avg = 0.04                                   # exactly average → medium
        result = _engagement_insight(ad, avg, total_clicks=1000.0)
        assert "orta ilgi" in result

    def test_zero_avg_ctr_falls_back_to_orta(self) -> None:
        """When avg_ctr is 0 (no impressions), fallback to 'orta ilgi'."""
        ad = self._ad(clicks=0, ctr_ratio=0.0)
        result = _engagement_insight(ad, 0.0, total_clicks=0.0)
        assert "orta ilgi" in result

    def test_traffic_share_in_text(self) -> None:
        """Traffic share percent appears in the returned string."""
        # 500 clicks out of 1000 total = 50%
        ad = self._ad(clicks=500, ctr_ratio=0.05)
        result = _engagement_insight(ad, 0.05, total_clicks=1000.0)
        # 50.0 with Turkish decimal separator → "50,0"
        assert "50,0" in result

    def test_ctr_formatted_as_percent_in_text(self) -> None:
        """CTR displayed as percent string (e.g. 5.00 → '5,00')."""
        ad = self._ad(clicks=100, ctr_ratio=0.05)  # 5%
        result = _engagement_insight(ad, 0.05, total_clicks=200.0)
        assert "5,00" in result

    def test_clicks_formatted_with_turkish_thousands(self) -> None:
        """Large click counts use Turkish period thousands separator."""
        ad = self._ad(clicks=12_400, ctr_ratio=0.03)
        result = _engagement_insight(ad, 0.03, total_clicks=50_000.0)
        assert "12.400" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. creative_insights service — seeded SQLite DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreativeInsightsService:
    """Integration tests for the service layer against a real (SQLite) DB."""

    def _ref_date(self) -> date:
        return _dt.now(timezone.utc).date() - timedelta(days=1)

    def test_totals_correct(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref)

        totals = result["totals"]
        # Seeded: 10000+10000+10000 impressions, 500+200+100 clicks, 30 conversions
        assert totals["impressions"] == 30_000
        assert totals["clicks"] == 800
        assert totals["creatives_count"] == 3
        assert totals["conversions"] == pytest.approx(30.0, abs=0.001)
        # CTR = 800/30000 * 100 ≈ 2.67%
        assert totals["ctr"] == pytest.approx(800 / 30_000 * 100, abs=0.01)

    def test_sorted_by_clicks_descending(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref)
        clicks_list = [c["clicks"] for c in result["top_creatives"]]
        assert clicks_list == sorted(clicks_list, reverse=True), (
            f"top_creatives not sorted by clicks desc: {clicks_list}"
        )

    def test_traffic_share_sums_to_100(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        # Use limit >= number of ads so all are returned
        result = creative_insights(db_session, membership.tenant_id, ref, ref, limit=10)
        shares = [c["traffic_share_pct"] for c in result["top_creatives"]]
        total_share = sum(shares)
        assert abs(total_share - 100.0) < 0.2, (
            f"traffic shares sum to {total_share}, expected ~100"
        )

    def test_top_creatives_limited(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref, limit=2)
        assert len(result["top_creatives"]) == 2

    def test_top_creative_has_required_keys(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref)
        required = {
            "ad_id", "ad_name", "campaign_name", "channel",
            "impressions", "clicks", "ctr", "conversions",
            "traffic_share_pct", "insight",
        }
        for creative in result["top_creatives"]:
            assert required <= set(creative.keys()), (
                f"Missing keys: {required - set(creative.keys())}"
            )

    def test_ctr_is_percent_not_ratio(self, db_session: Session) -> None:
        """CTR values should be >1 for typical ad campaigns (percent, not ratio)."""
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref)
        # Seeded CTRs: 500/10000=5%, 200/10000=2%, 100/10000=1% — all > 0.1
        for creative in result["top_creatives"]:
            assert creative["ctr"] > 0.1, (
                f"CTR {creative['ctr']} looks like a ratio, expected percent"
            )

    def test_empty_warehouse_returns_fallback(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()

        result = creative_insights(db_session, membership.tenant_id, ref, ref)
        assert result["top_creatives"] == []
        assert result["headline"] == "Bu dönemde kreatif verisi bulunamadı."
        assert result["totals"]["creatives_count"] == 0
        assert result["totals"]["clicks"] == 0

    def test_headline_contains_ad_name(self, db_session: Session) -> None:
        _, _, membership = _make_tenant_and_membership(db_session)
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        result = creative_insights(db_session, membership.tenant_id, ref, ref)
        # The top ad by clicks is "Banner A" (500 clicks)
        assert "Banner A" in result["headline"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET /marcom/creative-insights — HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreativeInsightsEndpoint:
    def _ref_date(self) -> date:
        return _dt.now(timezone.utc).date() - timedelta(days=1)

    def _get_membership(self) -> Membership:
        return _test_app.dependency_overrides[get_current_membership]()

    def test_happy_path_200_and_shape(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = self._get_membership()
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": ref.isoformat(), "date_to": ref.isoformat()},
        )
        assert resp.status_code == 200
        body = resp.json()

        # Top-level keys
        assert set(body.keys()) >= {"period", "totals", "headline", "top_creatives"}

        # Period shape
        assert "date_from" in body["period"]
        assert "date_to" in body["period"]

        # Totals shape
        totals = body["totals"]
        assert set(totals.keys()) >= {
            "impressions", "clicks", "ctr", "conversions", "creatives_count"
        }
        assert totals["creatives_count"] == 3
        assert totals["clicks"] == 800

        # top_creatives shape
        top = body["top_creatives"]
        assert isinstance(top, list)
        assert len(top) > 0
        first = top[0]
        assert set(first.keys()) >= {
            "ad_id", "ad_name", "campaign_name", "channel",
            "impressions", "clicks", "ctr", "conversions",
            "traffic_share_pct", "insight",
        }

    def test_default_date_range_applied(self, client: TestClient) -> None:
        """Omitting dates yields a 30-day window ending today."""
        resp = client.get("/api/v1/marcom/creative-insights")
        assert resp.status_code == 200
        body = resp.json()
        today = _dt.now(timezone.utc).date()
        expected_from = today - timedelta(days=29)

        assert body["period"]["date_to"] == today.isoformat()
        assert body["period"]["date_from"] == expected_from.isoformat()

    def test_explicit_dates_used(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = self._get_membership()
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": ref.isoformat(), "date_to": ref.isoformat()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"]["date_from"] == ref.isoformat()
        assert body["period"]["date_to"] == ref.isoformat()

    def test_date_from_after_date_to_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": "2026-06-01", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get("/api/v1/marcom/creative-insights")
        assert resp.status_code in (401, 403)

    def test_empty_warehouse_returns_200_with_fallback(
        self, client: TestClient, db_session: Session
    ) -> None:
        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": "2020-01-01", "date_to": "2020-01-31"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["top_creatives"] == []
        assert body["headline"] == "Bu dönemde kreatif verisi bulunamadı."

    def test_top_creatives_sorted_by_clicks_desc(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = self._get_membership()
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": ref.isoformat(), "date_to": ref.isoformat()},
        )
        assert resp.status_code == 200
        clicks_list = [c["clicks"] for c in resp.json()["top_creatives"]]
        assert clicks_list == sorted(clicks_list, reverse=True)

    def test_headline_is_nonempty_string(
        self, client: TestClient, db_session: Session
    ) -> None:
        membership = self._get_membership()
        ref = self._ref_date()
        _seed_three_ads(db_session, membership.tenant_id, ref)

        resp = client.get(
            "/api/v1/marcom/creative-insights",
            params={"date_from": ref.isoformat(), "date_to": ref.isoformat()},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["headline"], str)
        assert len(resp.json()["headline"]) > 0
