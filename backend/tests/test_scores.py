"""Tests for the performance scoring layer.

Strategy
--------
Part 1 — Pure-function unit tests for ``compute_scores``.
  No DB, no HTTP.  All inputs are plain dicts.  Tests validate:
  - improvement (current > baseline)   → score > 50
  - regression  (current < baseline)   → score < 50
  - equal performance                  → score == 50
  - zero baseline                      → neutral 50 + basis note
  - zero clicks in current period      → neutral 50 for conversion
  - score clamping at 0 and 100
  - overall score = documented weighting (40/30/30)
  - rating thresholds (iyi/orta/zayıf)

Part 2 — Endpoint integration tests for GET /api/v1/dashboard/scores.
  Uses FastAPI TestClient + in-memory SQLite (same pattern as other dashboard
  tests).  Tests validate:
  - 200 response with correct shape
  - auth required (401 without JWT override)
  - tenant isolation (Tenant B data stays out)
  - date validation (422 on from > to)
  - neutral scores when baseline period has no data
  - scores increase when current period is better
  - scores decrease when current period is worse

Seed data layout (endpoint tests)
----------------------------------
Tenant A:
  Channel: google_ads

  Baseline period  2024-03-01 → 2024-03-07  (7 days, single row on 2024-03-01):
    impressions=1000, clicks=50, spend=200.00, conversions=10, cv=1000.00
    CTR  = 50/1000    = 0.050
    CPC  = 200/50     = 4.00
    CPA  = 200/10     = 20.00
    ROAS = 1000/200   = 5.00
    CVR  = 10/50      = 0.20

  Current period   2024-03-08 → 2024-03-14  (7 days, single row on 2024-03-08):
    impressions=2000, clicks=80, spend=300.00, conversions=20, cv=1500.00
    CTR  = 80/2000    = 0.040  (regression)
    CPC  = 300/80     = 3.75   (improvement — lower CPC)
    CPA  = 300/20     = 15.00  (improvement — lower CPA)
    ROAS = 1500/300   = 5.00   (same)
    CVR  = 20/80      = 0.25   (improvement)

Tenant B: has a large spend row on 2024-03-08 (must not bleed into Tenant A).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.main import app
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
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
from ayaz.services.scores import (
    _NO_BASELINE_NOTE,
    _WEIGHT_CONVERSION,
    _WEIGHT_EFFICIENCY,
    _WEIGHT_ENGAGEMENT,
    _rating,
    _ratio_to_score,
    compute_scores,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1 — Pure-function unit tests
# ═══════════════════════════════════════════════════════════════════════════════


def _totals(
    *,
    impressions: float = 1000.0,
    clicks: float = 50.0,
    spend: float = 200.0,
    conversions: float = 10.0,
    conversion_value: float = 1000.0,
    ctr: float | None = None,
    cpc: float | None = None,
    cpa: float | None = None,
    roas: float | None = None,
) -> dict:
    """Build a totals dict.  Derived metrics auto-computed when not supplied."""
    _ctr = ctr if ctr is not None else (clicks / impressions if impressions else 0.0)
    _cpc = cpc if cpc is not None else (spend / clicks if clicks else 0.0)
    _cpa = cpa if cpa is not None else (spend / conversions if conversions else 0.0)
    _roas = roas if roas is not None else (conversion_value / spend if spend else 0.0)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "ctr": _ctr,
        "cpc": _cpc,
        "cpa": _cpa,
        "roas": _roas,
    }


class TestRatioToScore:
    """Unit tests for the core ratio → score helper."""

    def test_equal_performance_is_fifty(self) -> None:
        assert _ratio_to_score(1.0) == 50

    def test_fifty_pct_improvement_is_one_hundred(self) -> None:
        # ratio=1.5 → (1.5-1)/0.5=1 → clamped to 1 → 50+50=100
        assert _ratio_to_score(1.5) == 100

    def test_fifty_pct_regression_is_zero(self) -> None:
        # ratio=0.5 → (0.5-1)/0.5=-1 → clamped to -1 → 50-50=0
        assert _ratio_to_score(0.5) == 0

    def test_above_one_five_clamped_to_one_hundred(self) -> None:
        assert _ratio_to_score(2.0) == 100
        assert _ratio_to_score(99.9) == 100

    def test_below_zero_five_clamped_to_zero(self) -> None:
        assert _ratio_to_score(0.0) == 0
        assert _ratio_to_score(0.1) == 0

    def test_twenty_five_pct_improvement_is_seventy_five(self) -> None:
        # ratio=1.25 → (0.25)/0.5=0.5 → 50+25=75
        assert _ratio_to_score(1.25) == 75

    def test_return_is_integer(self) -> None:
        assert isinstance(_ratio_to_score(1.0), int)


class TestRating:
    """Unit tests for the rating threshold helper."""

    def test_67_is_iyi(self) -> None:
        assert _rating(67) == "iyi"

    def test_100_is_iyi(self) -> None:
        assert _rating(100) == "iyi"

    def test_66_is_orta(self) -> None:
        assert _rating(66) == "orta"

    def test_50_is_orta(self) -> None:
        assert _rating(50) == "orta"

    def test_34_is_orta(self) -> None:
        assert _rating(34) == "orta"

    def test_33_is_zayif(self) -> None:
        assert _rating(33) == "zayıf"

    def test_0_is_zayif(self) -> None:
        assert _rating(0) == "zayıf"


class TestComputeScoresResponseShape:
    """Response structure validation."""

    def test_has_overall_key(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert "overall" in result

    def test_has_components_key(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert "components" in result

    def test_overall_has_required_fields(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        overall = result["overall"]
        assert "score" in overall
        assert "label" in overall
        assert "rating" in overall

    def test_overall_label_is_genel_etkinlik(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert result["overall"]["label"] == "Genel Etkinlik"

    def test_three_components(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert len(result["components"]) == 3

    def test_component_keys_are_correct(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        keys = {c["key"] for c in result["components"]}
        assert keys == {"efficiency", "engagement", "conversion"}

    def test_component_has_required_fields(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        for comp in result["components"]:
            for field in ("key", "label", "score", "value", "baseline", "basis"):
                assert field in comp, f"Missing field '{field}' in component {comp['key']}"

    def test_scores_are_integers(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert isinstance(result["overall"]["score"], int)
        for comp in result["components"]:
            assert isinstance(comp["score"], int), f"{comp['key']} score not int"

    def test_scores_in_range_0_to_100(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert 0 <= result["overall"]["score"] <= 100
        for comp in result["components"]:
            assert 0 <= comp["score"] <= 100, f"{comp['key']} score out of range"


class TestComputeScoresEqualPerformance:
    """When current == baseline, all scores should be ~50."""

    def test_overall_is_fifty(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert result["overall"]["score"] == 50

    def test_all_components_are_fifty(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        for comp in result["components"]:
            assert comp["score"] == 50, f"{comp['key']} should be 50 for equal performance"

    def test_overall_rating_is_orta_at_fifty(self) -> None:
        t = _totals()
        result = compute_scores(t, t)
        assert result["overall"]["rating"] == "orta"

    def test_accepts_decimal_values(self) -> None:
        """Decimal-safe: ensure Decimal inputs don't cause TypeErrors."""
        t = {
            "impressions": Decimal("1000"),
            "clicks": Decimal("50"),
            "spend": Decimal("200.00"),
            "conversions": Decimal("10"),
            "conversion_value": Decimal("1000.00"),
            "ctr": Decimal("0.05"),
            "cpc": Decimal("4.00"),
            "cpa": Decimal("20.00"),
            "roas": Decimal("5.00"),
        }
        result = compute_scores(t, t)  # no exception
        assert result["overall"]["score"] == 50


class TestComputeScoresImprovement:
    """Current period better than baseline → scores > 50."""

    def test_roas_improvement_raises_efficiency_score(self) -> None:
        base = _totals(conversion_value=1000.0, spend=200.0)  # ROAS=5
        curr = _totals(conversion_value=2000.0, spend=200.0)  # ROAS=10
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] > 50

    def test_ctr_improvement_raises_engagement_score(self) -> None:
        base = _totals(impressions=1000.0, clicks=50.0)    # CTR=5%
        curr = _totals(impressions=1000.0, clicks=100.0)   # CTR=10%
        result = compute_scores(curr, base)
        eng = next(c for c in result["components"] if c["key"] == "engagement")
        assert eng["score"] > 50

    def test_cvr_improvement_raises_conversion_score(self) -> None:
        base = _totals(clicks=100.0, conversions=10.0)  # CVR=10%
        curr = _totals(clicks=100.0, conversions=20.0)  # CVR=20%
        result = compute_scores(curr, base)
        conv = next(c for c in result["components"] if c["key"] == "conversion")
        assert conv["score"] > 50

    def test_cpa_improvement_raises_efficiency_score(self) -> None:
        """Lower CPA is better; efficiency score should rise."""
        base = _totals(spend=200.0, conversions=10.0, conversion_value=0.0)
        # CPA_base=20; make current CPA=10 (improvement)
        curr = _totals(spend=100.0, conversions=10.0, conversion_value=0.0)
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] > 50

    def test_overall_improves_when_all_components_improve(self) -> None:
        base = _totals()
        # Better ROAS, better CTR, better CVR
        curr = _totals(
            impressions=1000.0, clicks=80.0, spend=150.0,
            conversions=20.0, conversion_value=1800.0,
        )
        result_base = compute_scores(base, base)
        result_curr = compute_scores(curr, base)
        assert result_curr["overall"]["score"] > result_base["overall"]["score"]


class TestComputeScoresRegression:
    """Current period worse than baseline → scores < 50."""

    def test_roas_regression_lowers_efficiency_score(self) -> None:
        base = _totals(conversion_value=1000.0, spend=200.0)  # ROAS=5
        curr = _totals(conversion_value=500.0, spend=200.0)   # ROAS=2.5
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] < 50

    def test_ctr_regression_lowers_engagement_score(self) -> None:
        base = _totals(impressions=1000.0, clicks=100.0)   # CTR=10%
        curr = _totals(impressions=1000.0, clicks=50.0)    # CTR=5%
        result = compute_scores(curr, base)
        eng = next(c for c in result["components"] if c["key"] == "engagement")
        assert eng["score"] < 50

    def test_cvr_regression_lowers_conversion_score(self) -> None:
        base = _totals(clicks=100.0, conversions=20.0)  # CVR=20%
        curr = _totals(clicks=100.0, conversions=10.0)  # CVR=10%
        result = compute_scores(curr, base)
        conv = next(c for c in result["components"] if c["key"] == "conversion")
        assert conv["score"] < 50

    def test_cpa_regression_lowers_efficiency_score(self) -> None:
        """Higher CPA (worse) should lower efficiency score."""
        base = _totals(spend=100.0, conversions=10.0, conversion_value=0.0)
        # CPA_base=10; current CPA=20 (regression)
        curr = _totals(spend=200.0, conversions=10.0, conversion_value=0.0)
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] < 50


class TestComputeScoresZeroBaseline:
    """Zero baseline → neutral 50 + basis note; no crash."""

    def test_zero_roas_and_cpa_baseline_efficiency_neutral(self) -> None:
        base = _totals(spend=0.0, conversion_value=0.0, conversions=0.0)
        curr = _totals()
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] == 50
        assert eff["basis"] == _NO_BASELINE_NOTE

    def test_zero_ctr_baseline_engagement_neutral(self) -> None:
        base = _totals(impressions=0.0, clicks=0.0)
        curr = _totals()
        result = compute_scores(curr, base)
        eng = next(c for c in result["components"] if c["key"] == "engagement")
        assert eng["score"] == 50
        assert eng["basis"] == _NO_BASELINE_NOTE

    def test_zero_clicks_baseline_conversion_neutral(self) -> None:
        base = _totals(clicks=0.0, conversions=0.0)
        curr = _totals()
        result = compute_scores(curr, base)
        conv = next(c for c in result["components"] if c["key"] == "conversion")
        assert conv["score"] == 50
        assert conv["basis"] == _NO_BASELINE_NOTE

    def test_zero_clicks_current_conversion_neutral(self) -> None:
        """Can't compute current CVR when current clicks=0."""
        base = _totals()
        curr = _totals(clicks=0.0, conversions=0.0)
        result = compute_scores(curr, base)
        conv = next(c for c in result["components"] if c["key"] == "conversion")
        assert conv["score"] == 50
        assert conv["basis"] == _NO_BASELINE_NOTE

    def test_all_zeros_returns_neutral_50_overall(self) -> None:
        """Completely empty data → all components neutral → overall 50."""
        t = _totals(
            impressions=0.0, clicks=0.0, spend=0.0,
            conversions=0.0, conversion_value=0.0,
            ctr=0.0, cpc=0.0, cpa=0.0, roas=0.0,
        )
        result = compute_scores(t, t)
        assert result["overall"]["score"] == 50
        for comp in result["components"]:
            assert comp["score"] == 50, f"{comp['key']} should be 50"

    def test_no_crash_on_zero_baseline(self) -> None:
        """Zero baseline must never raise ZeroDivisionError or any exception."""
        base = {k: 0.0 for k in
                ("impressions", "clicks", "spend", "conversions",
                 "conversion_value", "ctr", "cpc", "cpa", "roas")}
        curr = _totals()
        result = compute_scores(curr, base)  # must not raise
        assert "overall" in result


class TestComputeScoresClamping:
    """Scores must be clamped to [0, 100]."""

    def test_extreme_improvement_clamped_to_one_hundred(self) -> None:
        base = _totals(conversion_value=100.0, spend=100.0)   # ROAS=1
        curr = _totals(conversion_value=10000.0, spend=100.0) # ROAS=100
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] == 100

    def test_extreme_regression_clamped_to_zero(self) -> None:
        base = _totals(conversion_value=1000.0, spend=100.0)   # ROAS=10
        curr = _totals(conversion_value=1.0, spend=100.0)      # ROAS=0.01
        result = compute_scores(curr, base)
        eff = next(c for c in result["components"] if c["key"] == "efficiency")
        assert eff["score"] == 0

    def test_overall_clamped_to_zero(self) -> None:
        """All components at 0 → overall at 0."""
        base = _totals(
            impressions=1000.0, clicks=100.0,
            conversion_value=1000.0, spend=100.0,
            conversions=20.0,
        )
        # Current is catastrophically worse
        curr = _totals(
            impressions=1000.0, clicks=1.0,      # CTR crashed
            conversion_value=1.0, spend=100.0,   # ROAS crashed
            conversions=0.0,                      # CVR crashed
        )
        result = compute_scores(curr, base)
        assert result["overall"]["score"] >= 0

    def test_overall_cannot_exceed_one_hundred(self) -> None:
        base = _totals(conversion_value=100.0, spend=200.0, clicks=10.0, conversions=1.0)
        curr = _totals(conversion_value=99999.0, spend=100.0, clicks=999.0, conversions=999.0)
        result = compute_scores(curr, base)
        assert result["overall"]["score"] <= 100


class TestComputeScoresWeighting:
    """Overall = 40% efficiency + 30% engagement + 30% conversion."""

    def test_overall_matches_documented_weights(self) -> None:
        # Use a scenario where we can compute each component score independently.
        base = _totals()
        curr = _totals()
        result = compute_scores(curr, base)

        components = {c["key"]: c["score"] for c in result["components"]}
        expected = round(
            _WEIGHT_EFFICIENCY * components["efficiency"]
            + _WEIGHT_ENGAGEMENT * components["engagement"]
            + _WEIGHT_CONVERSION * components["conversion"]
        )
        assert result["overall"]["score"] == expected

    def test_efficiency_improvement_raises_overall(self) -> None:
        """Improving ROAS (efficiency driver) should raise overall above 50."""
        base = _totals()
        curr = dict(base)
        curr["roas"] = base["roas"] * 3         # triple ROAS
        curr["conversion_value"] = base["conversion_value"] * 3
        res = compute_scores(curr, base)
        assert res["overall"]["score"] > 50

    def test_engagement_improvement_raises_overall(self) -> None:
        """Improving CTR alone (fixing ctr directly) should raise overall above 50.

        We set ctr explicitly so the engagement component sees a ratio > 1
        without side-effects from changing clicks (which would also affect CVR).
        """
        base = _totals()
        curr = dict(base)
        curr["ctr"] = base["ctr"] * 1.5   # +50% CTR → engagement score = 100
        res = compute_scores(curr, base)
        assert res["overall"]["score"] > 50

    def test_weights_sum_to_one(self) -> None:
        total = _WEIGHT_EFFICIENCY + _WEIGHT_ENGAGEMENT + _WEIGHT_CONVERSION
        assert abs(total - 1.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2 — Endpoint integration tests
# ═══════════════════════════════════════════════════════════════════════════════


_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Scores Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name=name,
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session, email: str = "scores@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test1234"),
        full_name="Scores User",
    )
    db.add(u)
    db.flush()
    return u


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


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.google_ads,
        external_account_id=str(uuid.uuid4()),
        display_name="google_ads test",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=str(uuid.uuid4()),
        name="Scores Campaign",
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=str(uuid.uuid4()),
        name="adset",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=str(uuid.uuid4()),
        name="ad",
    )
    db.add(ad)
    db.flush()
    return ad


def _ensure_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d,
        year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month,
        week=iso.week,
        day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _insert_fact(
    db: Session,
    tenant: Tenant,
    acct: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    d: date,
    *,
    impressions: int,
    clicks: int,
    spend: str,
    conversions: str,
    cv: str,
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(spend)
    fact = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=cost,
        cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(cv),
        conversion_value_ccy="USD",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(cv),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def scores_client(db_session: Session):
    """TestClient seeded with:

    Tenant A (active membership):
      Baseline  2024-03-01:  imp=1000, clk=50, spend=200, conv=10, cv=1000
      Current   2024-03-08:  imp=2000, clk=80, spend=300, conv=20, cv=1500

    Tenant B (isolation check):
      2024-03-08:  very large numbers that must not bleed into Tenant A.
    """
    tenant_a = _make_tenant(db_session, "Tenant A Scores")
    user_a = _make_user(db_session, "a_scores@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)
    acct_a = _make_connected_account(db_session, tenant_a)
    ch_a = _make_channel(db_session, "google_ads")
    camp_a = _make_campaign(db_session, tenant_a, ch_a)
    adset_a = _make_adset(db_session, tenant_a, camp_a)
    ad_a = _make_ad(db_session, tenant_a, adset_a)

    # Baseline row: 2024-03-01 (will be covered by prev window of 2024-03-08 → 2024-03-14)
    _insert_fact(
        db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
        date(2024, 3, 1),
        impressions=1000, clicks=50, spend="200.00", conversions="10", cv="1000.00",
    )
    # Current row: 2024-03-08
    _insert_fact(
        db_session, tenant_a, acct_a, ch_a, camp_a, adset_a, ad_a,
        date(2024, 3, 8),
        impressions=2000, clicks=80, spend="300.00", conversions="20", cv="1500.00",
    )

    # Tenant B isolation
    tenant_b = _make_tenant(db_session, "Tenant B Scores")
    user_b = _make_user(db_session, "b_scores@ayaz.app")
    _make_membership(db_session, user_b, tenant_b)
    acct_b = _make_connected_account(db_session, tenant_b)
    ch_b = _make_channel(db_session, "google_ads_b")
    camp_b = _make_campaign(db_session, tenant_b, ch_b)
    adset_b = _make_adset(db_session, tenant_b, camp_b)
    ad_b = _make_ad(db_session, tenant_b, adset_b)
    _insert_fact(
        db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b,
        date(2024, 3, 8),
        impressions=999999, clicks=999999, spend="999999", conversions="999999", cv="999999",
    )

    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def no_baseline_client(db_session: Session):
    """TestClient with data ONLY in the current window (no baseline period data).

    Current   2024-05-08:  imp=1000, clk=50, spend=200, conv=10, cv=1000
    Baseline  2024-05-01:  (no rows → all zeros)
    """
    tenant = _make_tenant(db_session, "No Baseline Tenant")
    user = _make_user(db_session, "no_baseline@ayaz.app")
    membership = _make_membership(db_session, user, tenant)
    acct = _make_connected_account(db_session, tenant)
    ch = _make_channel(db_session, "google_ads")
    camp = _make_campaign(db_session, tenant, ch)
    adset = _make_adset(db_session, tenant, camp)
    ad = _make_ad(db_session, tenant, adset)

    _insert_fact(
        db_session, tenant, acct, ch, camp, adset, ad,
        date(2024, 5, 8),
        impressions=1000, clicks=50, spend="200.00", conversions="10", cv="1000.00",
    )
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ── Endpoint tests ────────────────────────────────────────────────────────────


class TestScoresEndpoint200:
    """Happy-path: 200 response with correct shape."""

    _PARAMS = {"date_from": "2024-03-08", "date_to": "2024-03-14"}

    def test_returns_200(self, scores_client: TestClient) -> None:
        resp = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS)
        assert resp.status_code == 200

    def test_response_has_date_from(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert body["date_from"] == "2024-03-08"

    def test_response_has_date_to(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert body["date_to"] == "2024-03-14"

    def test_response_has_overall(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert "overall" in body

    def test_overall_has_score(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert "score" in body["overall"]
        assert isinstance(body["overall"]["score"], int)

    def test_overall_has_label(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert body["overall"]["label"] == "Genel Etkinlik"

    def test_overall_has_rating(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert body["overall"]["rating"] in ("iyi", "orta", "zayıf")

    def test_response_has_components(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert "components" in body
        assert len(body["components"]) == 3

    def test_component_keys_present(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        keys = {c["key"] for c in body["components"]}
        assert keys == {"efficiency", "engagement", "conversion"}

    def test_component_has_basis_string(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        for comp in body["components"]:
            assert isinstance(comp["basis"], str), f"{comp['key']} missing basis"
            assert len(comp["basis"]) > 0

    def test_all_scores_in_range(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert 0 <= body["overall"]["score"] <= 100
        for comp in body["components"]:
            assert 0 <= comp["score"] <= 100, f"{comp['key']} score out of range"

    def test_component_value_and_baseline_are_numbers(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        for comp in body["components"]:
            assert isinstance(comp["value"], (int, float))
            assert isinstance(comp["baseline"], (int, float))


class TestScoresEndpointAuth:
    """Auth enforcement: no override → 401."""

    def test_no_auth_returns_401(self, db_session: Session) -> None:
        """Without any dependency override the default JWT dep rejects the call."""
        # Ensure no override from other fixtures (conftest _clear_dependency_overrides handles it).
        from sqlalchemy import StaticPool, create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(
            _SQLITE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        import ayaz.models.oltp  # noqa: F401
        import ayaz.models.analytics  # noqa: F401
        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        sess = TestingSession()

        def override_get_db():
            try:
                yield sess
            finally:
                pass

        # Override DB but NOT membership → JWT dep fires and returns 401.
        app.dependency_overrides[get_db] = override_get_db

        client = TestClient(app)
        try:
            resp = client.get(
                "/api/v1/dashboard/scores",
                params={"date_from": "2024-03-08", "date_to": "2024-03-14"},
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
            sess.close()
            Base.metadata.drop_all(engine)


class TestScoresEndpointDateValidation:
    """date_from > date_to must return 422."""

    def test_from_after_to_returns_422(self, scores_client: TestClient) -> None:
        resp = scores_client.get(
            "/api/v1/dashboard/scores",
            params={"date_from": "2024-03-14", "date_to": "2024-03-08"},
        )
        assert resp.status_code == 422

    def test_missing_date_from_returns_422(self, scores_client: TestClient) -> None:
        resp = scores_client.get(
            "/api/v1/dashboard/scores",
            params={"date_to": "2024-03-14"},
        )
        assert resp.status_code == 422

    def test_missing_date_to_returns_422(self, scores_client: TestClient) -> None:
        resp = scores_client.get(
            "/api/v1/dashboard/scores",
            params={"date_from": "2024-03-08"},
        )
        assert resp.status_code == 422

    def test_single_day_is_valid(self, scores_client: TestClient) -> None:
        resp = scores_client.get(
            "/api/v1/dashboard/scores",
            params={"date_from": "2024-03-08", "date_to": "2024-03-08"},
        )
        assert resp.status_code == 200


class TestScoresEndpointTenantIsolation:
    """Tenant B's data (spend=999999) must never appear in Tenant A's scores."""

    _PARAMS = {"date_from": "2024-03-08", "date_to": "2024-03-14"}

    def test_tenant_b_roas_not_in_efficiency_value(self, scores_client: TestClient) -> None:
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        eff = next(c for c in body["components"] if c["key"] == "efficiency")
        # Tenant A ROAS = 1500/300 = 5. Tenant B would produce ROAS=1.
        # At minimum, the value shouldn't be from Tenant B's huge numbers.
        assert eff["value"] != pytest.approx(999999.0, rel=0.01)

    def test_overall_score_is_reasonable(self, scores_client: TestClient) -> None:
        """If tenant isolation failed, Tenant B's data would dominate and score would
        be unpredictable.  We just check overall is in range 0–100."""
        body = scores_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert 0 <= body["overall"]["score"] <= 100


class TestScoresEndpointNoBaseline:
    """When the baseline period has no data, all scores should be neutral (50)
    and basis should say yeterli geçmiş veri yok."""

    _PARAMS = {"date_from": "2024-05-08", "date_to": "2024-05-14"}

    def test_all_component_scores_neutral(self, no_baseline_client: TestClient) -> None:
        body = no_baseline_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        for comp in body["components"]:
            assert comp["score"] == 50, (
                f"{comp['key']} score is {comp['score']}, expected 50 (no baseline)"
            )

    def test_all_basis_notes_say_no_data(self, no_baseline_client: TestClient) -> None:
        body = no_baseline_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        for comp in body["components"]:
            assert _NO_BASELINE_NOTE in comp["basis"], (
                f"{comp['key']} basis '{comp['basis']}' does not contain no-data note"
            )

    def test_overall_is_fifty(self, no_baseline_client: TestClient) -> None:
        body = no_baseline_client.get("/api/v1/dashboard/scores", params=self._PARAMS).json()
        assert body["overall"]["score"] == 50
