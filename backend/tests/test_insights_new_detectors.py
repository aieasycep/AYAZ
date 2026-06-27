"""Tests for the two new M4 insight detectors:
- detect_conversion_rate_drop  (category "cvr_drop")
- detect_positive_movement     (category "positive_movement")

Pattern mirrors test_insights.py:
- Pure-Python DailyPoint unit tests (no DB).
- generate_insights integration tests with SQLite.
- Narrator template tests.
- Deduplication tests.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

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
from ayaz.services.insights import (
    DailyPoint,
    DetectorResult,
    _group_by_channel,
    _sum_period,
    detect_conversion_rate_drop,
    detect_positive_movement,
    generate_insights,
    CVR_DROP_THRESHOLD,
    CVR_DROP_CRITICAL,
    POSITIVE_MOVEMENT_THRESHOLD,
    POSITIVE_MOVEMENT_MIN_SPEND,
    POSITIVE_MOVEMENT_MIN_CONVERSIONS,
)
from ayaz.services.narrator import TemplateNarrator


# ── In-memory SQLite engine ───────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp      # noqa: F401
    import ayaz.models.analytics # noqa: F401
    import ayaz.models.feeds     # noqa: F401
    import ayaz.models.insights  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── DB fixture helpers (duplicated here so this file is self-contained) ────────


def _make_tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name="New Detector Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel, name: str) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=f"camp-{uuid.uuid4()}",
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id="adset-1",
        name="adset-1",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id="ad-1",
        name="ad-1",
    )
    db.add(ad)
    db.flush()
    return ad


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.sample,
        external_account_id="ACC-NEWDET",
        display_name="New Det Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


def _ensure_dim_date(db: Session, d: date) -> None:
    existing = db.get(DimDate, d)
    if existing:
        return
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
    impressions: int = 1000,
    clicks: int = 100,
    cost_raw: str = "200.00",
    conversions: str = "20",
    conversion_value_raw: str = "1000.00",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(cost_raw)
    f = FactDailyMetrics(
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
        cost_ccy="TRY",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value_raw),
        conversion_value_ccy="TRY",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value_raw),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.flush()
    return f


# ── DailyPoint builder ────────────────────────────────────────────────────────


def _pt(
    d: date,
    channel: str = "google_ads",
    spend: float = 200.0,
    impressions: float = 1000.0,
    clicks: float = 100.0,
    conversions: float = 20.0,
    conversion_value: float = 1000.0,
) -> DailyPoint:
    from ayaz.services.metrics import ctr as _ctr, cpc as _cpc, roas as _roas

    p = DailyPoint(
        date_key=d,
        channel_key=channel,
        impressions=Decimal(str(impressions)),
        clicks=Decimal(str(clicks)),
        spend=Decimal(str(spend)),
        conversions=Decimal(str(conversions)),
        conversion_value=Decimal(str(conversion_value)),
    )
    p.ctr_val = float(_ctr(p.impressions, p.clicks))
    p.cpc_val = float(_cpc(p.spend, p.clicks))
    p.roas_val = float(_roas(p.conversion_value, p.spend))
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# Detector unit tests — detect_conversion_rate_drop
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectConversionRateDrop:
    """CVR drop detector — pure Python, no DB."""

    def _make_series(
        self,
        prior_conversions: float = 20.0,
        current_conversions: float = 20.0,
        clicks: float = 100.0,
        days: int = 14,
    ) -> dict[str, list[DailyPoint]]:
        """Build a 14-day series with stable clicks and varying conversions."""
        base = date(2024, 4, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            conv = current_conversions if i >= days // 2 else prior_conversions
            pts.append(_pt(d, clicks=clicks, conversions=conv))
        return _group_by_channel(pts)

    # ── Trigger cases ──────────────────────────────────────────────────────

    def test_detects_50pct_cvr_drop(self) -> None:
        # Prior CVR = 20/100 = 0.20; current = 10/100 = 0.10 → 50% drop
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=10.0)
        results = detect_conversion_rate_drop(
            by_ch, date(2024, 4, 14), recent_days=7, threshold=0.25
        )
        assert len(results) >= 1
        assert results[0].category == "cvr_drop"
        assert results[0].metric == "conversion_rate"

    def test_detects_60pct_cvr_drop_is_critical(self) -> None:
        # Prior = 20/100; current = 8/100 → 60% drop → critical
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=8.0)
        results = detect_conversion_rate_drop(
            by_ch,
            date(2024, 4, 14),
            recent_days=7,
            threshold=0.25,
            critical_threshold=0.50,
        )
        assert results[0].severity == "critical"

    def test_detects_30pct_drop_is_warning(self) -> None:
        # Prior = 20/100; current = 14/100 → 30% drop → warning (below 50% critical)
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=14.0)
        results = detect_conversion_rate_drop(
            by_ch,
            date(2024, 4, 14),
            recent_days=7,
            threshold=0.25,
            critical_threshold=0.50,
        )
        assert len(results) >= 1
        assert results[0].severity == "warning"

    def test_data_fields_present(self) -> None:
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=10.0)
        results = detect_conversion_rate_drop(
            by_ch, date(2024, 4, 14), recent_days=7, threshold=0.25
        )
        d = results[0].data
        assert "current_cvr" in d
        assert "prior_cvr" in d
        assert "pct_drop" in d
        assert "current_clicks" in d
        assert "current_conversions" in d

    def test_score_bounded_100(self) -> None:
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=1.0)
        results = detect_conversion_rate_drop(
            by_ch, date(2024, 4, 14), recent_days=7, threshold=0.25
        )
        assert 0 < results[0].score <= 100.0

    # ── No-trigger cases ───────────────────────────────────────────────────

    def test_no_signal_on_stable_cvr(self) -> None:
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=20.0)
        results = detect_conversion_rate_drop(
            by_ch, date(2024, 4, 14), recent_days=7, threshold=0.25
        )
        assert results == []

    def test_no_signal_on_small_drop_below_threshold(self) -> None:
        # 10% drop — below 25% threshold
        by_ch = self._make_series(prior_conversions=20.0, current_conversions=18.0)
        results = detect_conversion_rate_drop(
            by_ch, date(2024, 4, 14), recent_days=7, threshold=0.25
        )
        assert results == []

    def test_no_signal_when_recent_clicks_zero(self) -> None:
        """Recent period has zero clicks — divide-by-zero guard must skip."""
        base = date(2024, 4, 1)
        pts = []
        # Prior 7 days: 100 clicks, 20 conversions
        for i in range(7):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), clicks=100.0, conversions=20.0))
        # Recent 7 days: 0 clicks (no traffic)
        for i in range(7, 14):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), clicks=0.0, conversions=0.0))
        by_ch = _group_by_channel(pts)
        results = detect_conversion_rate_drop(by_ch, date(2024, 4, 14), recent_days=7)
        assert results == []

    def test_no_signal_when_prior_clicks_zero(self) -> None:
        """Prior period has zero clicks — divide-by-zero guard must skip."""
        base = date(2024, 4, 1)
        pts = []
        # Prior 7 days: 0 clicks
        for i in range(7):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), clicks=0.0, conversions=0.0))
        # Recent 7 days: 100 clicks, 20 conversions
        for i in range(7, 14):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), clicks=100.0, conversions=20.0))
        by_ch = _group_by_channel(pts)
        results = detect_conversion_rate_drop(by_ch, date(2024, 4, 14), recent_days=7)
        assert results == []

    def test_no_signal_when_too_few_points(self) -> None:
        pts = [_pt(date(2024, 4, 1))]
        by_ch = _group_by_channel(pts)
        results = detect_conversion_rate_drop(by_ch, date(2024, 4, 1))
        assert results == []

    def test_no_signal_when_prior_period_empty(self) -> None:
        """Only recent days available, no prior window."""
        pts = [_pt(date(2024, 4, i)) for i in range(1, 8)]
        by_ch = _group_by_channel(pts)
        # recent_days=7 requires 14 points total for a prior window; only 7 exist
        results = detect_conversion_rate_drop(by_ch, date(2024, 4, 7), recent_days=7)
        assert results == []

    def test_channel_key_propagated(self) -> None:
        base = date(2024, 4, 1)
        pts = [
            _pt(date.fromordinal(base.toordinal() + i), channel="meta_ads",
                conversions=20.0 if i < 7 else 5.0)
            for i in range(14)
        ]
        by_ch = _group_by_channel(pts)
        results = detect_conversion_rate_drop(by_ch, date(2024, 4, 14), recent_days=7)
        assert results[0].channel == "meta_ads"


# ═══════════════════════════════════════════════════════════════════════════════
# Detector unit tests — detect_positive_movement
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectPositiveMovement:
    """Positive movement detector — pure Python, no DB."""

    def _make_series_roas(
        self,
        prior_cv: float = 1000.0,
        current_cv: float = 1000.0,
        spend: float = 200.0,
        days: int = 14,
    ) -> dict[str, list[DailyPoint]]:
        base = date(2024, 5, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            cv = current_cv if i >= days // 2 else prior_cv
            pts.append(_pt(d, spend=spend, conversion_value=cv))
        return _group_by_channel(pts)

    def _make_series_conversions(
        self,
        prior_conv: float = 10.0,
        current_conv: float = 10.0,
        spend: float = 200.0,
        days: int = 14,
    ) -> dict[str, list[DailyPoint]]:
        base = date(2024, 5, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            conv = current_conv if i >= days // 2 else prior_conv
            pts.append(_pt(d, spend=spend, conversions=conv))
        return _group_by_channel(pts)

    # ── ROAS trigger cases ─────────────────────────────────────────────────

    def test_detects_roas_improvement(self) -> None:
        # Prior ROAS = 1000/200 = 5.0; current = 1500/200 = 7.5 → 50% gain
        by_ch = self._make_series_roas(prior_cv=1000.0, current_cv=1500.0, spend=200.0)
        results = detect_positive_movement(
            by_ch,
            date(2024, 5, 14),
            recent_days=7,
            threshold=0.30,
            min_spend=Decimal("50"),
            min_conversions=Decimal("5"),
        )
        assert len(results) >= 1
        assert results[0].category == "positive_movement"
        assert results[0].metric == "roas"
        assert results[0].severity == "info"

    def test_roas_trigger_data_fields(self) -> None:
        by_ch = self._make_series_roas(prior_cv=1000.0, current_cv=1500.0, spend=200.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7,
            threshold=0.30, min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        d = results[0].data
        assert "current_roas" in d
        assert "prior_roas" in d
        assert "pct_gain" in d
        assert d["trigger"] == "roas"

    def test_roas_improvement_score_bounded(self) -> None:
        # Enormous ROAS gain — score should be capped at 100
        by_ch = self._make_series_roas(prior_cv=100.0, current_cv=10000.0, spend=200.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        assert results[0].score <= 100.0

    # ── Conversions trigger cases ──────────────────────────────────────────

    def test_detects_conversion_improvement_when_roas_flat(self) -> None:
        """ROAS is flat but conversions rise — conversions trigger should fire."""
        base = date(2024, 5, 1)
        pts = []
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            # Same spend and conversion_value so ROAS is constant; conversions vary
            conv = 20.0 if i >= 7 else 10.0
            pts.append(_pt(d, spend=200.0, conversions=conv, conversion_value=1000.0))
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        assert len(results) >= 1
        cvr_results = [r for r in results if r.metric == "conversions"]
        assert len(cvr_results) >= 1
        assert cvr_results[0].data["trigger"] == "conversions"

    def test_conversion_trigger_data_fields(self) -> None:
        base = date(2024, 5, 1)
        pts = []
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            conv = 20.0 if i >= 7 else 10.0
            pts.append(_pt(d, spend=200.0, conversions=conv, conversion_value=1000.0))
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        conv_r = [r for r in results if r.metric == "conversions"][0]
        assert "current_conversions" in conv_r.data
        assert "prior_conversions" in conv_r.data
        assert "pct_gain" in conv_r.data

    def test_roas_takes_precedence_when_both_fire(self) -> None:
        """When both ROAS and conversions improve, only one result per channel (ROAS)."""
        base = date(2024, 5, 1)
        pts = []
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            if i >= 7:
                pts.append(_pt(d, spend=200.0, conversions=25.0, conversion_value=2000.0))
            else:
                pts.append(_pt(d, spend=200.0, conversions=10.0, conversion_value=1000.0))
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        # Only one result per channel because ROAS fired and conversions is skipped
        channel_results = [r for r in results if r.channel == "google_ads"]
        assert len(channel_results) == 1
        assert channel_results[0].metric == "roas"

    # ── No-trigger / noise floor cases ─────────────────────────────────────

    def test_no_signal_on_stable_roas(self) -> None:
        by_ch = self._make_series_roas(prior_cv=1000.0, current_cv=1000.0, spend=200.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        assert results == []

    def test_no_signal_when_improvement_below_threshold(self) -> None:
        # 10% ROAS gain — below 30% threshold
        by_ch = self._make_series_roas(prior_cv=1000.0, current_cv=1100.0, spend=200.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        assert results == []

    def test_no_signal_when_spend_below_floor(self) -> None:
        """ROAS improves significantly but spend is below min_spend floor."""
        # Tiny spend (1.0) — should not trigger ROAS win
        by_ch = self._make_series_roas(prior_cv=1.0, current_cv=2.0, spend=1.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"),  # floor higher than spend
            min_conversions=Decimal("5"),
        )
        # spend per day is 1.0; 7 days = 7.0 total — below min_spend=50
        assert results == []

    def test_no_signal_when_conversions_below_floor(self) -> None:
        """Conversions improve but count is below min_conversions floor."""
        base = date(2024, 5, 1)
        pts = []
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            conv = 2.0 if i >= 7 else 1.0  # tiny absolute numbers
            pts.append(_pt(d, spend=200.0, conversions=conv, conversion_value=1000.0))
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"),
            min_conversions=Decimal("20"),  # floor above actual 14 total conversions
        )
        # Recent conversions = 7 * 2.0 = 14 — below min_conversions=20
        assert results == []

    def test_no_signal_on_roas_drop(self) -> None:
        """ROAS decline must NOT fire a positive insight."""
        by_ch = self._make_series_roas(prior_cv=2000.0, current_cv=500.0, spend=200.0)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        assert results == []

    def test_no_signal_when_prior_spend_zero(self) -> None:
        """No prior spend — prior ROAS undefined, should skip."""
        base = date(2024, 5, 1)
        pts = []
        # Prior 7 days: zero spend
        for i in range(7):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), spend=0.0, conversion_value=0.0))
        # Recent 7 days: positive spend
        for i in range(7, 14):
            pts.append(_pt(date.fromordinal(base.toordinal() + i), spend=200.0, conversion_value=1000.0))
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(
            by_ch, date(2024, 5, 14), recent_days=7, threshold=0.30,
            min_spend=Decimal("50"), min_conversions=Decimal("5"),
        )
        # ROAS win should not fire (prior_spend=0); conversions win requires prior_conv>0
        assert results == []

    def test_no_signal_when_too_few_points(self) -> None:
        pts = [_pt(date(2024, 5, 1))]
        by_ch = _group_by_channel(pts)
        results = detect_positive_movement(by_ch, date(2024, 5, 1))
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# Narrator tests for the two new categories
# ═══════════════════════════════════════════════════════════════════════════════


def _make_result(
    category: str,
    metric: str = "roas",
    channel: str = "google_ads",
    severity: str = "warning",
    data: dict | None = None,
) -> DetectorResult:
    return DetectorResult(
        category=category,
        severity=severity,
        metric=metric,
        channel=channel,
        period_start=date(2024, 5, 1),
        period_end=date(2024, 5, 7),
        score=50.0,
        data=data or {},
    )


class TestTemplateNarratorNewCategories:

    def setup_method(self) -> None:
        self.narrator = TemplateNarrator()

    def _assert_non_empty_strings(self, title: str, body: str) -> None:
        assert isinstance(title, str) and len(title) > 0
        assert isinstance(body, str) and len(body) > 0

    def test_cvr_drop_template(self) -> None:
        result = _make_result(
            "cvr_drop",
            metric="conversion_rate",
            data={"current_cvr": 0.08, "prior_cvr": 0.20, "pct_drop": 0.60},
        )
        title, body = self.narrator.narrate(result)
        self._assert_non_empty_strings(title, body)
        # Title should mention the channel and CVR / dönüşüm
        assert "google" in title.lower() or "ads" in title.lower() or "dönüşüm" in title.lower() or "donusum" in title.lower()

    def test_cvr_drop_contains_pct_in_title(self) -> None:
        result = _make_result(
            "cvr_drop",
            metric="conversion_rate",
            data={"current_cvr": 0.10, "prior_cvr": 0.20, "pct_drop": 0.50},
        )
        title, body = self.narrator.narrate(result)
        # The pct drop fraction should show up somewhere in the narrative
        assert "%" in title or "%" in body

    def test_positive_movement_roas_template(self) -> None:
        result = _make_result(
            "positive_movement",
            metric="roas",
            severity="info",
            data={
                "current_roas": 7.0,
                "prior_roas": 5.0,
                "pct_gain": 0.40,
                "current_spend": 1400.0,
                "trigger": "roas",
            },
        )
        title, body = self.narrator.narrate(result)
        self._assert_non_empty_strings(title, body)
        # Should mention ROAS and an upbeat tone
        assert "ROAS" in title or "roas" in title.lower() or "yukseldi" in title.lower()

    def test_positive_movement_conversions_template(self) -> None:
        result = _make_result(
            "positive_movement",
            metric="conversions",
            severity="info",
            data={
                "current_conversions": 50.0,
                "prior_conversions": 30.0,
                "pct_gain": 0.67,
                "trigger": "conversions",
            },
        )
        title, body = self.narrator.narrate(result)
        self._assert_non_empty_strings(title, body)

    def test_positive_movement_none_channel(self) -> None:
        """channel=None should not raise — uses 'tüm kanallar' fallback."""
        result = DetectorResult(
            category="positive_movement",
            severity="info",
            metric="roas",
            channel=None,
            period_start=date(2024, 5, 1),
            period_end=date(2024, 5, 7),
            score=40.0,
            data={"current_roas": 6.0, "prior_roas": 4.0, "pct_gain": 0.50,
                  "current_spend": 500.0, "trigger": "roas"},
        )
        title, body = self.narrator.narrate(result)
        self._assert_non_empty_strings(title, body)

    def test_cvr_drop_none_channel(self) -> None:
        result = DetectorResult(
            category="cvr_drop",
            severity="warning",
            metric="conversion_rate",
            channel=None,
            period_start=date(2024, 5, 1),
            period_end=date(2024, 5, 7),
            score=40.0,
            data={"current_cvr": 0.05, "prior_cvr": 0.15, "pct_drop": 0.67},
        )
        title, body = self.narrator.narrate(result)
        self._assert_non_empty_strings(title, body)


# ═══════════════════════════════════════════════════════════════════════════════
# generate_insights integration tests (SQLite)
# ═══════════════════════════════════════════════════════════════════════════════


def _setup_channel_entities(
    db: Session, tenant: Tenant, channel_key: str
) -> tuple[DimChannel, ConnectedAccount, DimCampaign, DimAdSet, DimAd]:
    acct = _make_connected_account(db, tenant)
    channel = _make_channel(db, channel_key)
    campaign = _make_campaign(db, tenant, channel, f"Camp {channel_key}")
    adset = _make_adset(db, tenant, campaign)
    ad = _make_ad(db, tenant, adset)
    return channel, acct, campaign, adset, ad


class TestGenerateInsightsCvrDrop:
    """generate_insights produces cvr_drop insights end-to-end."""

    def test_cvr_drop_insight_created(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        channel, acct, campaign, adset, ad = _setup_channel_entities(
            db_session, tenant, "meta_cvr"
        )
        base = date(2024, 6, 1)
        # Prior 14 days: 100 clicks, 20 conversions → CVR=0.20
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="20", cost_raw="200.00",
                conversion_value_raw="1000.00",
            )
        # Recent 7 days: 100 clicks, 5 conversions → CVR=0.05 (75% drop)
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="5", cost_raw="200.00",
                conversion_value_raw="50.00",
            )
        db_session.commit()

        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 6, 21), lookback_days=21
        )
        total_new = counts["new_info"] + counts["new_warning"] + counts["new_critical"]
        assert total_new >= 1

        # Confirm at least one cvr_drop insight exists
        from sqlalchemy import select
        cvr_insights = db_session.execute(
            select(Insight).where(
                Insight.tenant_id == tenant.id,
                Insight.category == "cvr_drop",
            )
        ).scalars().all()
        assert len(cvr_insights) >= 1

    def test_cvr_drop_deduplication(self, db_session: Session) -> None:
        """Running generate_insights twice for the same date must not produce
        duplicate cvr_drop insights."""
        tenant = _make_tenant(db_session)
        channel, acct, campaign, adset, ad = _setup_channel_entities(
            db_session, tenant, "gg_cvr_dedup"
        )
        base = date(2024, 6, 1)
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="20", cost_raw="200.00",
                conversion_value_raw="1000.00",
            )
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="5", cost_raw="200.00",
                conversion_value_raw="50.00",
            )
        db_session.commit()

        as_of = date(2024, 6, 21)
        counts1 = generate_insights(db_session, tenant.id, as_of_date=as_of, lookback_days=21)
        db_session.commit()
        counts2 = generate_insights(db_session, tenant.id, as_of_date=as_of, lookback_days=21)
        db_session.commit()

        # Second run should not add new cvr_drop insights for the same slot
        total1 = counts1["new_info"] + counts1["new_warning"] + counts1["new_critical"]
        assert counts2["skipped"] >= total1


class TestGenerateInsightsPositiveMovement:
    """generate_insights produces positive_movement insights end-to-end."""

    def test_positive_roas_insight_created(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        channel, acct, campaign, adset, ad = _setup_channel_entities(
            db_session, tenant, "gg_positive"
        )
        base = date(2024, 7, 1)
        # Prior 14 days: ROAS = 1000/200 = 5.0
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="10", cost_raw="200.00",
                conversion_value_raw="1000.00",
            )
        # Recent 7 days: ROAS = 2000/200 = 10.0 → 100% gain
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="20", cost_raw="200.00",
                conversion_value_raw="2000.00",
            )
        db_session.commit()

        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 7, 21), lookback_days=21
        )
        total_new = counts["new_info"] + counts["new_warning"] + counts["new_critical"]
        assert total_new >= 1

        from sqlalchemy import select
        pos_insights = db_session.execute(
            select(Insight).where(
                Insight.tenant_id == tenant.id,
                Insight.category == "positive_movement",
            )
        ).scalars().all()
        assert len(pos_insights) >= 1
        assert all(i.severity == "info" for i in pos_insights)

    def test_positive_movement_deduplication(self, db_session: Session) -> None:
        """Running twice for the same date must not create duplicate positive insights."""
        tenant = _make_tenant(db_session)
        channel, acct, campaign, adset, ad = _setup_channel_entities(
            db_session, tenant, "gg_pos_dedup"
        )
        base = date(2024, 7, 1)
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="10", cost_raw="200.00",
                conversion_value_raw="1000.00",
            )
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=100, conversions="20", cost_raw="200.00",
                conversion_value_raw="2000.00",
            )
        db_session.commit()

        as_of = date(2024, 7, 21)
        counts1 = generate_insights(db_session, tenant.id, as_of_date=as_of, lookback_days=21)
        db_session.commit()
        counts2 = generate_insights(db_session, tenant.id, as_of_date=as_of, lookback_days=21)
        db_session.commit()

        total1 = counts1["new_info"] + counts1["new_warning"] + counts1["new_critical"]
        assert counts2["skipped"] >= total1

    def test_no_positive_insight_on_noise_spend(self, db_session: Session) -> None:
        """Tiny spend should not fire a positive insight even with huge ROAS gain."""
        tenant = _make_tenant(db_session)
        channel, acct, campaign, adset, ad = _setup_channel_entities(
            db_session, tenant, "gg_noise"
        )
        base = date(2024, 7, 1)
        # Prior: 1 click, 1 conversion, spend=1, cv=5 → ROAS=5
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=1, conversions="1", cost_raw="1.00",
                conversion_value_raw="5.00",
            )
        # Recent: same 1 click, 1 conversion, spend=1, cv=15 → ROAS=15 (200% gain)
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                clicks=1, conversions="1", cost_raw="1.00",
                conversion_value_raw="15.00",
            )
        db_session.commit()

        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 7, 21), lookback_days=21
        )

        from sqlalchemy import select
        pos_insights = db_session.execute(
            select(Insight).where(
                Insight.tenant_id == tenant.id,
                Insight.category == "positive_movement",
            )
        ).scalars().all()
        # spend = 7 * 1.00 = 7.00 — below min_spend floor of 50 → no positive insight
        assert len(pos_insights) == 0
