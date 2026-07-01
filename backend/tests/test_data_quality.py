"""Tests for the DATA-TRUST layer — data quality detection and drill-down.

Covers
------
1. detect_duplicate_accounts        — finds (platform, ext_id) pairs with count > 1
2. detect_double_count_risk         — confirms fact rows from duplicate accounts overlap
3. detect_kpi_inconsistencies       — clicks>impressions, conversions>clicks, spend+zero-imp
4. run_data_quality_detectors       — returns DetectorResult objects (no DB writes)
5. get_metric_breakdown             — drill-down by account; duplicate_warning flag
6. check_duplicate_before_link      — pre-flight check before create_account
7. POST /connectors/accounts        — duplicate guard (409 Conflict); allow_duplicate bypass
8. GET  /data-quality/duplicate-accounts
9. GET  /data-quality/drill-down
10. GET  /data-quality/kpi-check
11. POST /data-quality/detect
12. Tenant isolation                — tenant A cannot see tenant B's duplicates

SQLite compatibility
--------------------
Uses ``sqlite://`` in-memory DB with the GUID portable type (CHAR(32) on SQLite).
No Postgres-only types are used.  All models use String columns, not PG ENUMs.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1.connectors import router as connectors_router
from ayaz.api.v1.data_quality import router as dq_router
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
from ayaz.models.insights import Insight
from ayaz.models.oltp import (
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
)
from ayaz.services.auth import hash_password
from ayaz.services.data_quality import (
    check_duplicate_before_link,
    detect_double_count_risk,
    detect_duplicate_accounts,
    detect_kpi_inconsistencies,
    get_metric_breakdown,
    run_data_quality_detectors,
)

# ── In-memory SQLite engine ───────────────────────────────────────────────────

_SQLITE_URL = "sqlite://"

_engine = create_engine(
    _SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

Base.metadata.create_all(bind=_engine)


# ── Minimal FastAPI test app ──────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(dq_router, prefix="/api/v1")
_test_app.include_router(connectors_router, prefix="/api/v1")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db() -> Session:
    """Return a fresh session; rollback after each test."""
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    t = Tenant(name=name, country="TR", base_currency="TRY")
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "test@example.com") -> User:
    u = User(
        email=email,
        hashed_password=hash_password("secret"),
        full_name="Test User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(
    db: Session,
    user: User,
    tenant: Tenant,
    role: MembershipRole = MembershipRole.owner,
) -> Membership:
    m = Membership(user_id=user.id, tenant_id=tenant.id, role=role)
    db.add(m)
    db.flush()
    return m


def _make_account(
    db: Session,
    tenant: Tenant,
    platform: Platform = Platform.meta_ads,
    ext_id: str = "ACT_123",
    display_name: str = "Meta Account 1",
) -> ConnectedAccount:
    a = ConnectedAccount(
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=ext_id,
        display_name=display_name,
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_channel(db: Session, key: str = "meta_ads") -> DimChannel:
    ch = DimChannel(key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_date_dim(db: Session, d: date) -> DimDate:
    dd = DimDate(
        date_key=d,
        year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month,
        week=d.isocalendar()[1],
        day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    )
    db.add(dd)
    db.flush()
    return dd


def _make_dim_campaign(db: Session, tenant: Tenant, channel: DimChannel) -> DimCampaign:
    c = DimCampaign(
        tenant_id=tenant.id, channel_id=channel.id, external_id="camp1", name="Campaign 1"
    )
    db.add(c)
    db.flush()
    return c


def _make_dim_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        tenant_id=tenant.id, campaign_id=campaign.id, external_id="adset1", name="AdSet 1"
    )
    db.add(a)
    db.flush()
    return a


def _make_dim_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    a = DimAd(
        tenant_id=tenant.id, ad_set_id=adset.id, external_id="ad1", name="Ad 1"
    )
    db.add(a)
    db.flush()
    return a


def _make_fact_row(
    db: Session,
    tenant: Tenant,
    account: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    day: date,
    impressions: int = 1000,
    clicks: int = 50,
    cost: float = 100.0,
    conversions: float = 5.0,
    conversion_value: float = 500.0,
) -> FactDailyMetrics:
    dd = db.get(DimDate, day)
    if dd is None:
        dd = _make_date_dim(db, day)

    row = FactDailyMetrics(
        tenant_id=tenant.id,
        connected_account_id=account.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=day,
        impressions=impressions,
        clicks=clicks,
        cost_raw=Decimal(str(cost)),
        cost_ccy="TRY",
        conversions=Decimal(str(conversions)),
        conversion_value_raw=Decimal(str(conversion_value)),
        conversion_value_ccy="TRY",
        cost_base_ccy=Decimal(str(cost)),
        conv_value_base_ccy=Decimal(str(conversion_value)),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def client_with_membership(db: Session):
    """Return (TestClient, membership) with an overridden DB and membership."""
    from ayaz.services.billing import require_within_data_source_limit

    tenant = _make_tenant(db)
    user = _make_user(db)
    membership = _make_membership(db, user, tenant)

    def _override_db():
        yield db

    def _override_membership():
        return membership

    def _override_billing():
        return None  # always allow — no billing constraints in tests

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = _override_membership
    _test_app.dependency_overrides[require_within_data_source_limit] = _override_billing

    client = TestClient(_test_app, raise_server_exceptions=True)
    yield client, membership, tenant
    _test_app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. detect_duplicate_accounts
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectDuplicateAccounts:
    def test_no_duplicates_returns_empty(self, db: Session):
        tenant = _make_tenant(db)
        _make_account(db, tenant, ext_id="UNIQUE_1")
        _make_account(db, tenant, ext_id="UNIQUE_2")
        result = detect_duplicate_accounts(db, tenant.id)
        assert result == []

    def test_single_duplicate_pair(self, db: Session):
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="ACT_999", display_name="Primary")
        a2 = _make_account(db, tenant, ext_id="ACT_999", display_name="Duplicate")
        result = detect_duplicate_accounts(db, tenant.id)
        assert len(result) == 1
        group = result[0]
        assert group["count"] == 2
        assert group["external_account_id"] == "ACT_999"
        assert set(group["account_ids"]) == {str(a1.id), str(a2.id)}

    def test_triple_duplicate(self, db: Session):
        tenant = _make_tenant(db)
        _make_account(db, tenant, ext_id="ACT_TRIPLE", display_name="First")
        _make_account(db, tenant, ext_id="ACT_TRIPLE", display_name="Second")
        _make_account(db, tenant, ext_id="ACT_TRIPLE", display_name="Third")
        result = detect_duplicate_accounts(db, tenant.id)
        assert len(result) == 1
        assert result[0]["count"] == 3

    def test_tenant_isolation(self, db: Session):
        """Tenant A's duplicates must not appear for Tenant B."""
        tenant_a = _make_tenant(db, "Tenant A")
        tenant_b = _make_tenant(db, "Tenant B")
        _make_account(db, tenant_a, ext_id="SHARED_ACT")
        _make_account(db, tenant_a, ext_id="SHARED_ACT")
        # Tenant B has the same ext_id but only once
        _make_account(db, tenant_b, ext_id="SHARED_ACT")

        dupes_a = detect_duplicate_accounts(db, tenant_a.id)
        dupes_b = detect_duplicate_accounts(db, tenant_b.id)

        assert len(dupes_a) == 1  # Tenant A has a duplicate
        assert dupes_b == []       # Tenant B does not


# ═══════════════════════════════════════════════════════════════════════════════
# 2. detect_double_count_risk
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectDoubleCountRisk:
    def test_no_duplicates_returns_empty(self, db: Session):
        tenant = _make_tenant(db)
        result = detect_double_count_risk(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result == []

    def test_duplicate_accounts_with_overlapping_fact_rows(self, db: Session):
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="DUPE_ACT", display_name="Primary")
        a2 = _make_account(db, tenant, ext_id="DUPE_ACT", display_name="Duplicate")

        channel = _make_channel(db)
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)

        test_date = date(2026, 6, 15)
        _make_fact_row(db, tenant, a1, channel, campaign, adset, ad, test_date)
        _make_fact_row(db, tenant, a2, channel, campaign, adset, ad, test_date)

        risks = detect_double_count_risk(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert len(risks) == 1
        risk = risks[0]
        assert risk["external_account_id"] == "DUPE_ACT"
        assert risk["overlapping_rows"] >= 2
        assert len(risk["duplicate_account_ids"]) == 2
        assert str(test_date) in risk["affected_dates"]

    def test_duplicate_accounts_only_one_has_facts(self, db: Session):
        """If only one of the duplicate pair has fact rows, no double-count risk."""
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="DUPE_HALF", display_name="Primary")
        _make_account(db, tenant, ext_id="DUPE_HALF", display_name="No Facts")

        channel = _make_channel(db, key="google_ads")
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)

        _make_fact_row(db, tenant, a1, channel, campaign, adset, ad, date(2026, 6, 15))

        risks = detect_double_count_risk(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        # Only one account contributes rows — not a double-count risk
        assert risks == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. detect_kpi_inconsistencies
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectKpiInconsistencies:
    def _setup_channel(self, db: Session, tenant: Tenant, key: str = "meta_ads"):
        channel = _make_channel(db, key)
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)
        account = _make_account(db, tenant)
        return account, channel, campaign, adset, ad

    def test_no_inconsistencies_on_clean_data(self, db: Session):
        tenant = _make_tenant(db)
        account, channel, campaign, adset, ad = self._setup_channel(db, tenant)
        _make_fact_row(
            db, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 15),
            impressions=1000, clicks=50, cost=100, conversions=5,
        )
        result = detect_kpi_inconsistencies(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result == []

    def test_clicks_exceed_impressions(self, db: Session):
        tenant = _make_tenant(db)
        account, channel, campaign, adset, ad = self._setup_channel(db, tenant)
        # clicks (200) > impressions (100) — impossible
        _make_fact_row(
            db, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 15),
            impressions=100, clicks=200, cost=50, conversions=2,
        )
        result = detect_kpi_inconsistencies(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        rules = [r["rule"] for r in result]
        assert "clicks_exceed_impressions" in rules
        row = next(r for r in result if r["rule"] == "clicks_exceed_impressions")
        assert row["details"]["clicks"] == 200
        assert row["details"]["impressions"] == 100

    def test_conversions_exceed_clicks(self, db: Session):
        tenant = _make_tenant(db)
        account, channel, campaign, adset, ad = self._setup_channel(db, tenant)
        # conversions (100) > clicks (50) — suspicious
        _make_fact_row(
            db, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 15),
            impressions=5000, clicks=50, cost=100, conversions=100.0,
        )
        result = detect_kpi_inconsistencies(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        rules = [r["rule"] for r in result]
        assert "conversions_exceed_clicks" in rules

    def test_spend_without_impressions(self, db: Session):
        tenant = _make_tenant(db)
        account, channel, campaign, adset, ad = self._setup_channel(db, tenant)
        # impressions = 0, cost > 0
        _make_fact_row(
            db, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 15),
            impressions=0, clicks=0, cost=500, conversions=0,
        )
        result = detect_kpi_inconsistencies(
            db, tenant.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        rules = [r["rule"] for r in result]
        assert "spend_without_impressions" in rules

    def test_tenant_isolation_kpi(self, db: Session):
        tenant_a = _make_tenant(db, "Tenant A")
        tenant_b = _make_tenant(db, "Tenant B")

        for tenant in [tenant_a, tenant_b]:
            account, channel, campaign, adset, ad = self._setup_channel(db, tenant, f"ch_{tenant.id}")
            _make_fact_row(
                db, tenant, account, channel, campaign, adset, ad,
                date(2026, 6, 15),
                impressions=100, clicks=200,  # violation for each
            )

        issues_a = detect_kpi_inconsistencies(
            db, tenant_a.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        issues_b = detect_kpi_inconsistencies(
            db, tenant_b.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        # Each tenant only sees their own issues
        assert len(issues_a) == 1
        assert len(issues_b) == 1
        assert issues_a[0]["connected_account_id"] != issues_b[0]["connected_account_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. run_data_quality_detectors
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunDataQualityDetectors:
    def test_returns_detector_results_for_duplicates(self, db: Session):
        from ayaz.services.insights import DetectorResult

        tenant = _make_tenant(db)
        _make_account(db, tenant, ext_id="DUPE_DET")
        _make_account(db, tenant, ext_id="DUPE_DET")

        results = run_data_quality_detectors(db, tenant.id, date(2026, 6, 30))

        assert len(results) >= 1
        dupe_results = [r for r in results if r.data.get("rule") == "duplicate_accounts"]
        assert len(dupe_results) == 1
        r = dupe_results[0]
        assert r.category == "data_quality"
        assert r.severity in ("warning", "critical")
        assert isinstance(r, DetectorResult)
        assert r.period_start <= r.period_end

    def test_kpi_inconsistency_in_detector_results(self, db: Session):
        tenant = _make_tenant(db)
        account = _make_account(db, tenant)
        channel = _make_channel(db, "google_ads")
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)

        _make_fact_row(
            db, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 25),
            impressions=100, clicks=500,  # violation
        )

        results = run_data_quality_detectors(db, tenant.id, date(2026, 6, 30))
        categories = {r.category for r in results}
        assert "data_quality" in categories

        kpi_results = [r for r in results if r.data.get("rule") == "clicks_exceed_impressions"]
        assert len(kpi_results) == 1
        assert kpi_results[0].severity == "critical"

    def test_no_results_for_clean_tenant(self, db: Session):
        tenant = _make_tenant(db)
        _make_account(db, tenant, ext_id="CLEAN_ACT")
        results = run_data_quality_detectors(db, tenant.id, date(2026, 6, 30))
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_metric_breakdown (drill-down)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetMetricBreakdown:
    def _setup(self, db: Session, tenant: Tenant):
        channel = _make_channel(db)
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)
        a1 = _make_account(db, tenant, ext_id="A1", display_name="Account One")
        a2 = _make_account(db, tenant, ext_id="A2", display_name="Account Two")
        return a1, a2, channel, campaign, adset, ad

    def test_spend_breakdown_two_accounts(self, db: Session):
        tenant = _make_tenant(db)
        a1, a2, channel, campaign, adset, ad = self._setup(db, tenant)

        test_date = date(2026, 6, 15)
        _make_fact_row(
            db, tenant, a1, channel, campaign, adset, ad, test_date,
            cost=300.0, impressions=3000, clicks=100, conversions=10,
        )
        _make_fact_row(
            db, tenant, a2, channel, campaign, adset, ad, test_date,
            cost=100.0, impressions=1000, clicks=30, conversions=3,
        )

        result = get_metric_breakdown(
            db, tenant.id, "spend", date(2026, 6, 1), date(2026, 6, 30)
        )

        assert result["metric"] == "spend"
        assert abs(result["total"] - 400.0) < 0.01
        assert len(result["breakdown"]) == 2

        # Verify percentages add up to ~100
        total_pct = sum(e["pct_of_total"] for e in result["breakdown"])
        assert abs(total_pct - 100.0) < 0.1

    def test_duplicate_warning_set_when_duplicates_present(self, db: Session):
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="DUPE_FACT", display_name="Primary")
        a2 = _make_account(db, tenant, ext_id="DUPE_FACT", display_name="Duplicate")

        channel = _make_channel(db, "tiktok_ads")
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)

        test_date = date(2026, 6, 20)
        _make_fact_row(
            db, tenant, a1, channel, campaign, adset, ad, test_date, cost=200.0,
        )
        _make_fact_row(
            db, tenant, a2, channel, campaign, adset, ad, test_date, cost=200.0,
        )

        result = get_metric_breakdown(
            db, tenant.id, "spend", date(2026, 6, 1), date(2026, 6, 30)
        )

        assert result["duplicate_warning"] is True
        assert len(result["duplicate_groups"]) >= 1

    def test_no_duplicate_warning_for_clean_accounts(self, db: Session):
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="CLEAN_1")
        channel = _make_channel(db, "search_console")
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)
        _make_fact_row(
            db, tenant, a1, channel, campaign, adset, ad, date(2026, 6, 20),
        )

        result = get_metric_breakdown(
            db, tenant.id, "spend", date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result["duplicate_warning"] is False

    def test_invalid_metric_raises(self, db: Session):
        tenant = _make_tenant(db)
        with pytest.raises(ValueError, match="Unknown metric"):
            get_metric_breakdown(
                db, tenant.id, "invalid_metric", date(2026, 6, 1), date(2026, 6, 30)
            )

    def test_derived_metric_roas_breakdown(self, db: Session):
        tenant = _make_tenant(db)
        a1 = _make_account(db, tenant, ext_id="ROAS_ACC")
        channel = _make_channel(db, "linkedin_ads")
        campaign = _make_dim_campaign(db, tenant, channel)
        adset = _make_dim_adset(db, tenant, campaign)
        ad = _make_dim_ad(db, tenant, adset)
        _make_fact_row(
            db, tenant, a1, channel, campaign, adset, ad, date(2026, 6, 20),
            cost=100.0, conversion_value=500.0,
        )
        result = get_metric_breakdown(
            db, tenant.id, "roas", date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result["metric"] == "roas"
        # ROAS = 500 / 100 = 5.0
        assert abs(result["total"] - 5.0) < 0.1

    def test_tenant_isolation_breakdown(self, db: Session):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")

        for tenant in [tenant_a, tenant_b]:
            a = _make_account(db, tenant, ext_id="SHARED_EXT")
            ch = _make_channel(db, f"ch_{tenant.id}")
            camp = _make_dim_campaign(db, tenant, ch)
            adset = _make_dim_adset(db, tenant, camp)
            ad = _make_dim_ad(db, tenant, adset)
            _make_fact_row(db, tenant, a, ch, camp, adset, ad, date(2026, 6, 20), cost=999.0)

        result_a = get_metric_breakdown(
            db, tenant_a.id, "spend", date(2026, 6, 1), date(2026, 6, 30)
        )
        result_b = get_metric_breakdown(
            db, tenant_b.id, "spend", date(2026, 6, 1), date(2026, 6, 30)
        )
        # Each tenant sees only their own spend (999 each, not 1998)
        assert abs(result_a["total"] - 999.0) < 0.1
        assert abs(result_b["total"] - 999.0) < 0.1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. check_duplicate_before_link
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckDuplicateBeforeLink:
    def test_no_existing_account_is_not_duplicate(self, db: Session):
        tenant = _make_tenant(db)
        result = check_duplicate_before_link(
            db, tenant.id, Platform.meta_ads, "NEW_ACT_001"
        )
        assert result["is_duplicate"] is False
        assert result["existing_accounts"] == []
        assert result["warning"] is None

    def test_existing_account_is_duplicate(self, db: Session):
        tenant = _make_tenant(db)
        _make_account(db, tenant, platform=Platform.google_ads, ext_id="GA_123")

        result = check_duplicate_before_link(
            db, tenant.id, Platform.google_ads, "GA_123"
        )
        assert result["is_duplicate"] is True
        assert len(result["existing_accounts"]) == 1
        assert result["warning"] is not None
        assert "GA_123" in result["warning"]

    def test_different_tenant_not_considered_duplicate(self, db: Session):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        _make_account(db, tenant_a, ext_id="SAME_EXT")

        result = check_duplicate_before_link(
            db, tenant_b.id, Platform.meta_ads, "SAME_EXT"
        )
        assert result["is_duplicate"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POST /connectors/accounts — duplicate guard
# ═══════════════════════════════════════════════════════════════════════════════


class TestConnectorsDuplicateGuard:
    def test_second_link_same_account_returns_409(self, client_with_membership):
        client, membership, tenant = client_with_membership
        payload = {
            "platform": "meta_ads",
            "external_account_id": "GUARD_TEST_ACT",
            "display_name": "First Link",
        }
        # First link should succeed
        resp1 = client.post("/api/v1/connectors/accounts", json=payload)
        assert resp1.status_code == 201

        # Second link should be blocked
        payload["display_name"] = "Second Link"
        resp2 = client.post("/api/v1/connectors/accounts", json=payload)
        assert resp2.status_code == 409
        body = resp2.json()
        assert body["detail"]["code"] == "duplicate_account"
        assert "GUARD_TEST_ACT" in body["detail"]["message"]
        assert len(body["detail"]["existing_accounts"]) == 1

    def test_allow_duplicate_bypass(self, client_with_membership):
        client, membership, tenant = client_with_membership
        payload = {
            "platform": "google_ads",
            "external_account_id": "BYPASS_ACT",
            "display_name": "First",
        }
        resp1 = client.post("/api/v1/connectors/accounts", json=payload)
        assert resp1.status_code == 201

        payload["display_name"] = "Second (forced)"
        resp2 = client.post(
            "/api/v1/connectors/accounts?allow_duplicate=true", json=payload
        )
        assert resp2.status_code == 201

    def test_unique_account_is_not_blocked(self, client_with_membership):
        client, _, _ = client_with_membership
        resp = client.post(
            "/api/v1/connectors/accounts",
            json={
                "platform": "tiktok_ads",
                "external_account_id": "TIKTOK_UNIQUE",
                "display_name": "TikTok Account",
            },
        )
        assert resp.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET /data-quality/duplicate-accounts
# ═══════════════════════════════════════════════════════════════════════════════


class TestDuplicateAccountsEndpoint:
    def test_empty_for_clean_tenant(self, client_with_membership):
        client, membership, tenant = client_with_membership
        resp = client.get("/api/v1/data-quality/duplicate-accounts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_duplicate_groups(self, client_with_membership):
        client, membership, tenant = client_with_membership
        db_session = next(iter(_test_app.dependency_overrides[get_db]()))

        _make_account(db_session, tenant, ext_id="DUP_API_1", display_name="Alpha")
        _make_account(db_session, tenant, ext_id="DUP_API_1", display_name="Beta")
        db_session.flush()

        resp = client.get("/api/v1/data-quality/duplicate-accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["count"] == 2
        assert data[0]["external_account_id"] == "DUP_API_1"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GET /data-quality/drill-down
# ═══════════════════════════════════════════════════════════════════════════════


class TestDrillDownEndpoint:
    def test_returns_breakdown_for_spend(self, client_with_membership):
        client, membership, tenant = client_with_membership
        db_session = next(iter(_test_app.dependency_overrides[get_db]()))

        account = _make_account(db_session, tenant, ext_id="DD_ACT")
        channel = _make_channel(db_session, "google_ads")
        campaign = _make_dim_campaign(db_session, tenant, channel)
        adset = _make_dim_adset(db_session, tenant, campaign)
        ad = _make_dim_ad(db_session, tenant, adset)
        _make_fact_row(
            db_session, tenant, account, channel, campaign, adset, ad,
            date(2026, 6, 20), cost=250.0,
        )
        db_session.flush()

        resp = client.get(
            "/api/v1/data-quality/drill-down",
            params={
                "metric": "spend",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric"] == "spend"
        assert abs(data["total"] - 250.0) < 0.01
        assert len(data["breakdown"]) == 1

    def test_invalid_metric_returns_422(self, client_with_membership):
        client, _, _ = client_with_membership
        resp = client.get(
            "/api/v1/data-quality/drill-down",
            params={
                "metric": "bad_metric",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
            },
        )
        assert resp.status_code == 422

    def test_date_range_reversed_returns_422(self, client_with_membership):
        client, _, _ = client_with_membership
        resp = client.get(
            "/api/v1/data-quality/drill-down",
            params={
                "metric": "spend",
                "date_from": "2026-06-30",
                "date_to": "2026-06-01",
            },
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 10. GET /data-quality/kpi-check
# ═══════════════════════════════════════════════════════════════════════════════


class TestKpiCheckEndpoint:
    def test_no_violations_returns_empty(self, client_with_membership):
        client, _, _ = client_with_membership
        resp = client.get("/api/v1/data-quality/kpi-check")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_kpi_violations(self, client_with_membership):
        client, membership, tenant = client_with_membership
        db_session = next(iter(_test_app.dependency_overrides[get_db]()))

        account = _make_account(db_session, tenant)
        channel = _make_channel(db_session, "ms_ads")
        campaign = _make_dim_campaign(db_session, tenant, channel)
        adset = _make_dim_adset(db_session, tenant, campaign)
        ad = _make_dim_ad(db_session, tenant, adset)

        # Insert a row that violates clicks > impressions
        yesterday = date.today() - timedelta(days=1)
        _make_fact_row(
            db_session, tenant, account, channel, campaign, adset, ad,
            yesterday,
            impressions=10, clicks=500,
        )
        db_session.flush()

        resp = client.get("/api/v1/data-quality/kpi-check")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        rules = [row["rule"] for row in data]
        assert "clicks_exceed_impressions" in rules


# ═══════════════════════════════════════════════════════════════════════════════
# 11. POST /data-quality/detect
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectEndpoint:
    def test_no_data_returns_zero_counts(self, client_with_membership):
        client, _, _ = client_with_membership
        resp = client.post("/api/v1/data-quality/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_warning"] == 0
        assert data["new_critical"] == 0

    def test_detect_creates_insight_for_duplicate(self, client_with_membership):
        client, membership, tenant = client_with_membership
        db_session = next(iter(_test_app.dependency_overrides[get_db]()))

        # Create duplicate accounts AND fact data so as_of_date is not None
        a1 = _make_account(db_session, tenant, ext_id="DETECT_DUPE")
        a2 = _make_account(db_session, tenant, ext_id="DETECT_DUPE")
        channel = _make_channel(db_session, "sample")
        campaign = _make_dim_campaign(db_session, tenant, channel)
        adset = _make_dim_adset(db_session, tenant, campaign)
        ad = _make_dim_ad(db_session, tenant, adset)
        today = date.today()
        _make_fact_row(db_session, tenant, a1, channel, campaign, adset, ad, today)
        db_session.flush()

        resp = client.post("/api/v1/data-quality/detect")
        assert resp.status_code == 200
        data = resp.json()
        total_new = data["new_info"] + data["new_warning"] + data["new_critical"]
        assert total_new >= 1

    def test_detect_deduplicates_on_second_run(self, client_with_membership):
        """Running detect twice should not create duplicate Insight rows."""
        client, membership, tenant = client_with_membership
        db_session = next(iter(_test_app.dependency_overrides[get_db]()))

        a1 = _make_account(db_session, tenant, ext_id="DEDUP_DUPE")
        a2 = _make_account(db_session, tenant, ext_id="DEDUP_DUPE")
        channel = _make_channel(db_session, "linkedin_ads")
        campaign = _make_dim_campaign(db_session, tenant, channel)
        adset = _make_dim_adset(db_session, tenant, campaign)
        ad = _make_dim_ad(db_session, tenant, adset)
        today = date.today()
        _make_fact_row(db_session, tenant, a1, channel, campaign, adset, ad, today)
        db_session.flush()

        resp1 = client.post("/api/v1/data-quality/detect")
        data1 = resp1.json()
        first_run = data1["new_warning"] + data1["new_critical"]

        resp2 = client.post("/api/v1/data-quality/detect")
        data2 = resp2.json()
        assert data2["skipped"] >= first_run
        assert data2["new_warning"] + data2["new_critical"] == 0
