"""Tests for the M4 AI Insights & Alerts engine.

Strategy
--------
* Uses an in-memory SQLite DB (same pattern as test_dashboard_api.py).
* Detector functions are tested with synthetic DailyPoint / fact data.
* Narrator tests verify Turkish output without any network calls.
* API tests use FastAPI TestClient with dependency overrides.
* No live network calls in any test.

SQLite compatibility
--------------------
All models use String columns (not Postgres ENUMs) and JSON (not JSONB), so
SQLite handles them transparently.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ayaz.database import get_db
from ayaz.api.v1.insights import router as insights_router

# Build a minimal test app that includes only the insights router.
# The production app (main.py) is not modified — team lead wires the router.
_test_app = FastAPI()
_test_app.include_router(insights_router, prefix="/api/v1")

from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
from ayaz.models.insights import AlertRule, Insight
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
from ayaz.services.auth import hash_password
from ayaz.services.insights import (
    DailyPoint,
    DetectorResult,
    _group_by_channel,
    _sum_period,
    detect_anomaly,
    detect_cpc_rise,
    detect_ctr_drop,
    detect_roas_drop,
    detect_spend_spike,
    detect_zero_conversions,
    generate_insights,
)
from ayaz.services.narrator import ClaudeNarrator, TemplateNarrator


# ── In-memory SQLite engine ───────────────────────────────────────────────────

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite DB, yield a Session, then drop everything."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import all model modules so their tables are registered on Base.metadata
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── DB fixture helpers ────────────────────────────────────────────────────────


def _make_tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name="Insights Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4()}@ayaz.app",
        hashed_password=hash_password("pass1234"),
        full_name="Test User",
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
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str
) -> DimCampaign:
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
        external_account_id="ACC-TEST",
        display_name="Test Account",
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
    clicks: int = 50,
    cost_raw: str = "100.00",
    conversions: str = "10",
    conversion_value_raw: str = "500.00",
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


# ── Daily point helpers ───────────────────────────────────────────────────────


def _pt(
    d: date,
    channel: str = "google_ads",
    spend: float = 100.0,
    impressions: float = 1000.0,
    clicks: float = 50.0,
    conversions: float = 10.0,
    conversion_value: float = 500.0,
) -> DailyPoint:
    p = DailyPoint(
        date_key=d,
        channel_key=channel,
        impressions=Decimal(str(impressions)),
        clicks=Decimal(str(clicks)),
        spend=Decimal(str(spend)),
        conversions=Decimal(str(conversions)),
        conversion_value=Decimal(str(conversion_value)),
    )
    from ayaz.services.metrics import ctr as _ctr, cpc as _cpc, roas as _roas
    p.ctr_val = float(_ctr(p.impressions, p.clicks))
    p.cpc_val = float(_cpc(p.spend, p.clicks))
    p.roas_val = float(_roas(p.conversion_value, p.spend))
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# Detector unit tests (pure Python — no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectAnomaly:
    """Z-score anomaly detector tests."""

    def _baseline_points(self, n: int = 14) -> list[DailyPoint]:
        """14 days of naturally-varying data (spend oscillates 90–110) so stdev > 0."""
        base = date(2024, 1, 1)
        # Use oscillating values to guarantee non-zero standard deviation
        spend_vals = [90, 105, 95, 110, 100, 98, 102, 97, 103, 99, 101, 108, 96, 104]
        return [
            _pt(
                date.fromordinal(base.toordinal() + i),
                spend=float(spend_vals[i % len(spend_vals)]),
            )
            for i in range(n)
        ]

    def test_no_anomaly_on_stable_series(self) -> None:
        pts = self._baseline_points(14)
        by_ch = _group_by_channel(pts)
        results = detect_anomaly(by_ch, pts[-1].date_key)
        # Values vary between 90-110 → no spend anomaly expected
        spend_anomalies = [r for r in results if r.metric == "spend"]
        assert spend_anomalies == []

    def test_detects_spend_spike(self) -> None:
        """Inject a massive spend spike on the last day (5000 vs ~100 baseline)."""
        pts = self._baseline_points(14)
        # Replace last point with a huge spend value — many sigma above mean
        pts[-1] = _pt(pts[-1].date_key, spend=5000.0)
        by_ch = _group_by_channel(pts)
        results = detect_anomaly(by_ch, pts[-1].date_key)
        spend_anomalies = [r for r in results if r.metric == "spend"]
        assert len(spend_anomalies) >= 1
        assert spend_anomalies[0].category == "anomaly"
        assert spend_anomalies[0].channel == "google_ads"

    def test_anomaly_severity_is_warning_or_critical(self) -> None:
        pts = self._baseline_points(14)
        pts[-1] = _pt(pts[-1].date_key, spend=5000.0)
        by_ch = _group_by_channel(pts)
        results = detect_anomaly(by_ch, pts[-1].date_key)
        for r in results:
            assert r.severity in ("warning", "critical")

    def test_skips_short_series(self) -> None:
        """Fewer than 4 points → no anomaly output."""
        pts = [_pt(date(2024, 1, i)) for i in range(1, 4)]
        by_ch = _group_by_channel(pts)
        results = detect_anomaly(by_ch, pts[-1].date_key)
        assert results == []

    def test_score_is_positive(self) -> None:
        pts = self._baseline_points(14)
        pts[-1] = _pt(pts[-1].date_key, spend=9999.0)
        by_ch = _group_by_channel(pts)
        results = detect_anomaly(by_ch, pts[-1].date_key)
        for r in results:
            assert r.score > 0


class TestDetectRoasDrop:
    """ROAS drop detector tests."""

    def _make_series(
        self, prior_roas: float = 5.0, current_roas: float = 5.0, days: int = 14
    ) -> dict[str, list[DailyPoint]]:
        """Create a series where the first half has prior_roas and second has current_roas."""
        base = date(2024, 1, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            if i < days // 2:
                cv = prior_roas * 100.0
            else:
                cv = current_roas * 100.0
            pts.append(_pt(d, spend=100.0, conversion_value=cv))
        return _group_by_channel(pts)

    def test_no_drop_no_signal(self) -> None:
        by_ch = self._make_series(prior_roas=5.0, current_roas=5.0)
        results = detect_roas_drop(by_ch, date(2024, 1, 14), recent_days=7)
        assert results == []

    def test_detects_25_pct_drop(self) -> None:
        by_ch = self._make_series(prior_roas=4.0, current_roas=3.0)
        results = detect_roas_drop(by_ch, date(2024, 1, 14), recent_days=7, threshold=0.20)
        assert len(results) >= 1
        assert results[0].category == "roas_drop"
        assert results[0].metric == "roas"

    def test_severity_escalates_at_critical_threshold(self) -> None:
        # 50% drop → critical
        by_ch = self._make_series(prior_roas=4.0, current_roas=2.0)
        results = detect_roas_drop(
            by_ch,
            date(2024, 1, 14),
            recent_days=7,
            threshold=0.20,
            critical_threshold=0.40,
        )
        assert results[0].severity == "critical"

    def test_warning_severity_at_moderate_drop(self) -> None:
        # 25% drop → warning (below critical 40%)
        by_ch = self._make_series(prior_roas=4.0, current_roas=3.0)
        results = detect_roas_drop(
            by_ch,
            date(2024, 1, 14),
            recent_days=7,
            threshold=0.20,
            critical_threshold=0.40,
        )
        assert results[0].severity == "warning"

    def test_data_contains_values(self) -> None:
        by_ch = self._make_series(prior_roas=5.0, current_roas=2.0)
        results = detect_roas_drop(by_ch, date(2024, 1, 14), recent_days=7)
        assert "current_roas" in results[0].data
        assert "prior_roas" in results[0].data
        assert "pct_drop" in results[0].data


class TestDetectSpendSpike:
    """Spend spike detector tests."""

    def _make_series(
        self, prior_spend: float = 100.0, current_spend: float = 100.0, days: int = 14
    ) -> dict[str, list[DailyPoint]]:
        base = date(2024, 1, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            spend = current_spend if i >= days // 2 else prior_spend
            pts.append(_pt(d, spend=spend))
        return _group_by_channel(pts)

    def test_no_spike_no_signal(self) -> None:
        by_ch = self._make_series(prior_spend=100.0, current_spend=105.0)
        results = detect_spend_spike(by_ch, date(2024, 1, 14), recent_days=7, threshold=0.30)
        assert results == []

    def test_detects_50_pct_spike(self) -> None:
        by_ch = self._make_series(prior_spend=100.0, current_spend=200.0)
        results = detect_spend_spike(by_ch, date(2024, 1, 14), recent_days=7, threshold=0.30)
        assert len(results) >= 1
        assert results[0].category == "spend_spike"

    def test_critical_at_large_spike(self) -> None:
        by_ch = self._make_series(prior_spend=100.0, current_spend=300.0)
        results = detect_spend_spike(
            by_ch,
            date(2024, 1, 14),
            recent_days=7,
            threshold=0.30,
            critical_threshold=0.80,
        )
        assert results[0].severity == "critical"


class TestDetectZeroConversions:
    """Zero conversions detector tests."""

    def test_no_signal_when_conversions_present(self) -> None:
        pts = [_pt(date(2024, 1, i), conversions=5.0) for i in range(1, 8)]
        by_ch = _group_by_channel(pts)
        results = detect_zero_conversions(by_ch, date(2024, 1, 7))
        assert results == []

    def test_no_signal_when_no_spend(self) -> None:
        pts = [_pt(date(2024, 1, i), spend=0.0, conversions=0.0) for i in range(1, 8)]
        by_ch = _group_by_channel(pts)
        results = detect_zero_conversions(by_ch, date(2024, 1, 7))
        assert results == []

    def test_detects_spend_with_no_conversions(self) -> None:
        pts = [_pt(date(2024, 1, i), spend=100.0, conversions=0.0) for i in range(1, 8)]
        by_ch = _group_by_channel(pts)
        results = detect_zero_conversions(by_ch, date(2024, 1, 7))
        assert len(results) == 1
        assert results[0].category == "zero_conversions"

    def test_critical_above_spend_threshold(self) -> None:
        pts = [
            _pt(date(2024, 1, i), spend=200.0, conversions=0.0)
            for i in range(1, 8)
        ]
        by_ch = _group_by_channel(pts)
        results = detect_zero_conversions(
            by_ch,
            date(2024, 1, 7),
            critical_spend=Decimal("500"),
        )
        # 7 days * 200 = 1400 spend — above 500 critical threshold
        assert results[0].severity == "critical"


class TestDetectCtrDrop:
    """CTR drop detector tests."""

    def _make_series(
        self, prior_ctr_clicks: float = 50.0, current_ctr_clicks: float = 50.0, days: int = 14
    ) -> dict[str, list[DailyPoint]]:
        base = date(2024, 1, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            clicks = current_ctr_clicks if i >= days // 2 else prior_ctr_clicks
            pts.append(_pt(d, impressions=1000.0, clicks=clicks))
        return _group_by_channel(pts)

    def test_no_drop_no_signal(self) -> None:
        by_ch = self._make_series(prior_ctr_clicks=50.0, current_ctr_clicks=50.0)
        results = detect_ctr_drop(by_ch, date(2024, 1, 14), recent_days=7)
        assert results == []

    def test_detects_ctr_drop(self) -> None:
        # From 50 clicks to 20 clicks (same impressions) → 60% CTR drop
        by_ch = self._make_series(prior_ctr_clicks=50.0, current_ctr_clicks=20.0)
        results = detect_ctr_drop(by_ch, date(2024, 1, 14), recent_days=7, threshold=0.25)
        assert len(results) >= 1
        assert results[0].category == "ctr_drop"
        assert results[0].metric == "ctr"


class TestDetectCpcRise:
    """CPC rise detector tests."""

    def _make_series(
        self, prior_spend: float = 100.0, current_spend: float = 100.0, days: int = 14
    ) -> dict[str, list[DailyPoint]]:
        base = date(2024, 1, 1)
        pts = []
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            spend = current_spend if i >= days // 2 else prior_spend
            pts.append(_pt(d, spend=spend, clicks=10.0))
        return _group_by_channel(pts)

    def test_no_rise_no_signal(self) -> None:
        by_ch = self._make_series(prior_spend=100.0, current_spend=100.0)
        results = detect_cpc_rise(by_ch, date(2024, 1, 14), recent_days=7)
        assert results == []

    def test_detects_cpc_rise(self) -> None:
        # prior CPC = 100/10 = 10, current CPC = 200/10 = 20 → 100% rise
        by_ch = self._make_series(prior_spend=100.0, current_spend=200.0)
        results = detect_cpc_rise(by_ch, date(2024, 1, 14), recent_days=7, threshold=0.25)
        assert len(results) >= 1
        assert results[0].category == "cpc_rise"
        assert results[0].metric == "cpc"


# ═══════════════════════════════════════════════════════════════════════════════
# Narrator tests (no network)
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
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 7),
        score=50.0,
        data=data or {},
    )


class TestTemplateNarrator:
    """TemplateNarrator must return non-empty Turkish strings for all categories."""

    def setup_method(self) -> None:
        self.narrator = TemplateNarrator()

    def _assert_turkish_output(self, title: str, body: str) -> None:
        assert isinstance(title, str) and len(title) > 0
        assert isinstance(body, str) and len(body) > 0

    def test_roas_drop(self) -> None:
        result = _make_result(
            "roas_drop",
            data={"current_roas": 2.0, "prior_roas": 4.0, "pct_drop": 0.50},
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)
        assert "ROAS" in title or "roas" in title.lower()

    def test_spend_spike(self) -> None:
        result = _make_result(
            "spend_spike",
            metric="spend",
            data={"current_spend": 300.0, "prior_spend": 100.0, "pct_rise": 2.0},
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_zero_conversions(self) -> None:
        result = _make_result(
            "zero_conversions",
            metric="conversions",
            data={"spend": 500.0, "conversions": 0.0},
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_ctr_drop(self) -> None:
        result = _make_result(
            "ctr_drop",
            metric="ctr",
            data={"current_ctr": 0.02, "prior_ctr": 0.05, "pct_drop": 0.6},
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_cpc_rise(self) -> None:
        result = _make_result(
            "cpc_rise",
            metric="cpc",
            data={"current_cpc": 5.0, "prior_cpc": 2.0, "pct_rise": 1.5},
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_anomaly(self) -> None:
        result = _make_result(
            "anomaly",
            metric="spend",
            data={
                "candidate_value": 999.0,
                "history_mean": 100.0,
                "history_stdev": 10.0,
                "z_score": 8.9,
                "direction": "yuksek",
                "candidate_date": "2024-01-07",
            },
        )
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_unknown_category_uses_generic(self) -> None:
        result = _make_result("budget_pacing", metric="spend")
        title, body = self.narrator.narrate(result)
        self._assert_turkish_output(title, body)

    def test_all_categories_return_strings(self) -> None:
        categories = [
            ("roas_drop", "roas", {"current_roas": 1.0, "prior_roas": 2.0, "pct_drop": 0.5}),
            ("spend_spike", "spend", {"current_spend": 200.0, "prior_spend": 100.0, "pct_rise": 1.0}),
            ("zero_conversions", "conversions", {"spend": 100.0, "conversions": 0.0}),
            ("ctr_drop", "ctr", {"current_ctr": 0.01, "prior_ctr": 0.05, "pct_drop": 0.8}),
            ("cpc_rise", "cpc", {"current_cpc": 10.0, "prior_cpc": 5.0, "pct_rise": 1.0}),
            ("anomaly", "spend", {"candidate_value": 999.0, "history_mean": 100.0,
                                   "history_stdev": 10.0, "z_score": 9.0,
                                   "direction": "yuksek", "candidate_date": "2024-01-07"}),
        ]
        for category, metric, data in categories:
            result = _make_result(category, metric=metric, data=data)
            title, body = self.narrator.narrate(result)
            assert isinstance(title, str) and title, f"Empty title for {category}"
            assert isinstance(body, str) and body, f"Empty body for {category}"


class TestClaudeNarrator:
    """ClaudeNarrator falls back to TemplateNarrator when no API key is present."""

    def test_falls_back_without_api_key(self) -> None:
        narrator = ClaudeNarrator(api_key="")
        result = _make_result(
            "roas_drop",
            data={"current_roas": 2.0, "prior_roas": 4.0, "pct_drop": 0.5},
        )
        title, body = narrator.narrate(result)
        # Should get template output without error
        assert isinstance(title, str) and len(title) > 0
        assert isinstance(body, str) and len(body) > 0

    def test_falls_back_on_http_error(self) -> None:
        """Mock a failed HTTP call — should fall back silently."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.post.return_value = mock_response

        narrator = ClaudeNarrator(api_key="fake-key", http_client=mock_client)
        result = _make_result("roas_drop", data={"current_roas": 1.0, "prior_roas": 3.0, "pct_drop": 0.66})
        title, body = narrator.narrate(result)
        # Falls back to template
        assert isinstance(title, str) and len(title) > 0

    def test_falls_back_on_bad_json(self) -> None:
        """Mock a 200 but with non-JSON body."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"text": "not valid json {{{"}]
        }
        mock_client.post.return_value = mock_response

        narrator = ClaudeNarrator(api_key="fake-key", http_client=mock_client)
        result = _make_result("roas_drop", data={"current_roas": 1.0, "prior_roas": 3.0, "pct_drop": 0.5})
        title, body = narrator.narrate(result)
        assert isinstance(title, str) and len(title) > 0

    def test_uses_api_when_key_and_client_present(self) -> None:
        """Mock a successful API response."""
        import json
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {
                    "text": json.dumps({
                        "title": "ROAS ciddi düştü",
                        "body": "Google Ads kanalında ROAS önemli ölçüde geriledi.",
                    })
                }
            ]
        }
        mock_client.post.return_value = mock_response

        narrator = ClaudeNarrator(api_key="fake-key", http_client=mock_client)
        result = _make_result("roas_drop", data={"current_roas": 1.0, "prior_roas": 5.0, "pct_drop": 0.8})
        title, body = narrator.narrate(result)
        assert title == "ROAS ciddi düştü"
        assert "ROAS" in body


# ═══════════════════════════════════════════════════════════════════════════════
# generate_insights integration tests (with SQLite)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateInsights:
    """generate_insights end-to-end with SQLite facts."""

    def _setup_stable_data(
        self, db: Session, tenant: Tenant, days: int = 20
    ) -> tuple[DimChannel, ConnectedAccount]:
        acct = _make_connected_account(db, tenant)
        channel = _make_channel(db, "google_ads")
        campaign = _make_campaign(db, tenant, channel, "Test Campaign")
        adset = _make_adset(db, tenant, campaign)
        ad = _make_ad(db, tenant, adset)

        base = date(2024, 3, 1)
        for i in range(days):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db, tenant, acct, channel, campaign, adset, ad, d,
                impressions=1000, clicks=50,
                cost_raw="100.00", conversions="10",
                conversion_value_raw="500.00",
            )
        db.commit()
        return channel, acct

    def test_returns_counts_dict(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        self._setup_stable_data(db_session, tenant)
        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 3, 20)
        )
        assert "new_info" in counts
        assert "new_warning" in counts
        assert "new_critical" in counts
        assert "skipped" in counts

    def test_no_data_returns_zero_counts(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 3, 20)
        )
        assert counts == {"new_info": 0, "new_warning": 0, "new_critical": 0, "skipped": 0}

    def test_idempotent_second_run_skips_duplicates(self, db_session: Session) -> None:
        """Running generate_insights twice should not create duplicate open insights."""
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "meta_ads")
        campaign = _make_campaign(db_session, tenant, channel, "Camp")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 3, 1)
        # Stable first 13 days then spend drops to 0 with no conversions
        for i in range(13):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00", conversions="5",
                conversion_value_raw="500.00",
            )
        # Last 7 days: spend present but zero conversions
        for i in range(13, 20):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00", conversions="0",
                conversion_value_raw="0.00",
            )
        db_session.commit()

        as_of = date(2024, 3, 20)
        counts1 = generate_insights(db_session, tenant.id, as_of_date=as_of)
        db_session.commit()

        counts2 = generate_insights(db_session, tenant.id, as_of_date=as_of)
        db_session.commit()

        # All of round 2 should be skipped (same period, same category)
        total1 = counts1["new_info"] + counts1["new_warning"] + counts1["new_critical"]
        assert counts2["skipped"] >= total1

    def test_ga4_channel_isolated_from_google_ads_no_cross_contamination(
        self, db_session: Session
    ) -> None:
        """Kaynak-tipi mutabakatı regresyon testi (Batch A.2).

        insights.py's detectors are ALREADY channel-scoped (every detector
        loops ``by_channel.items()`` and sums only WITHIN one channel's own
        time series) — a campaign/channel never spans both an ad platform
        and an analytics source, so there is no cross-channel blind SUM to
        fix here. This test locks that property: seeding google_ads (ad,
        real spend+clicks+conversions) alongside ga4 (analytics, 0 spend/
        clicks, large conversions) on the SAME days must produce insights
        whose numeric ``data`` reflects ONLY the channel they're tagged
        with — google_ads's own signals must never include GA4's numbers
        and vice versa.
        """
        from ayaz.services.insights import _load_daily_points

        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)

        ch_ads = _make_channel(db_session, "google_ads")
        camp_ads = _make_campaign(db_session, tenant, ch_ads, "Ads Camp")
        adset_ads = _make_adset(db_session, tenant, camp_ads)
        ad_ads = _make_ad(db_session, tenant, adset_ads)

        ch_ga4 = _make_channel(db_session, "ga4")
        camp_ga4 = _make_campaign(db_session, tenant, ch_ga4, "(not set)")
        adset_ga4 = _make_adset(db_session, tenant, camp_ga4)
        ad_ga4 = _make_ad(db_session, tenant, adset_ga4)

        base = date(2024, 4, 1)
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, ch_ads, camp_ads, adset_ads, ad_ads, d,
                impressions=1000, clicks=50,
                cost_raw="100.00", conversions="10",
                conversion_value_raw="500.00",
            )
            # GA4: zero spend/clicks, LARGE conversions — if channel
            # isolation were broken this would inflate google_ads' own CVR
            # or ROAS-adjacent signals.
            _insert_fact(
                db_session, tenant, acct, ch_ga4, camp_ga4, adset_ga4, ad_ga4, d,
                impressions=0, clicks=0,
                cost_raw="0", conversions="500",
                conversion_value_raw="50000.00",
            )
        db_session.commit()

        points = _load_daily_points(db_session, tenant.id, base, date.fromordinal(base.toordinal() + 13))
        by_channel = _group_by_channel(points)

        assert set(by_channel.keys()) == {"google_ads", "ga4"}

        # google_ads points must show ONLY the ad numbers — never GA4's.
        for p in by_channel["google_ads"]:
            assert p.conversions == Decimal("10")
            assert p.conversion_value == Decimal("500.00")
            assert p.spend == Decimal("100.00")

        # ga4 points must show ONLY GA4's own numbers — never blended with ads.
        for p in by_channel["ga4"]:
            assert p.conversions == Decimal("500")
            assert p.spend == Decimal("0")
            assert p.clicks == Decimal("0")

        # generate_insights end-to-end: any signal tagged channel="google_ads"
        # must carry ad-only numbers in its data payload (spot-check the
        # fields detectors commonly report).
        counts = generate_insights(db_session, tenant.id, as_of_date=date.fromordinal(base.toordinal() + 13))
        assert counts["new_info"] + counts["new_warning"] + counts["new_critical"] >= 0  # no crash

        insights = db_session.scalars(select(Insight).where(Insight.tenant_id == tenant.id)).all()
        for ins in insights:
            if ins.channel == "google_ads":
                for key in ("current_spend", "current_conversions", "current_conversion_value"):
                    if key in (ins.data or {}):
                        # Ad-only values are always <= the tiny ad-scale numbers
                        # seeded (100/10/500) times the lookback window — GA4's
                        # 500-conversion/50000-value scale must never appear here.
                        assert ins.data[key] < 5000, (
                            f"Insight for google_ads has suspiciously large "
                            f"{key}={ins.data[key]} — GA4 data may have leaked in"
                        )

    def test_zero_conversion_anomaly_creates_insight(self, db_session: Session) -> None:
        """Spend with zero conversions should produce at least one insight."""
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "tiktok_ads")
        campaign = _make_campaign(db_session, tenant, channel, "Camp")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 3, 1)
        for i in range(7):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00", conversions="0",
                conversion_value_raw="0.00",
            )
        db_session.commit()

        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 3, 7), lookback_days=7
        )
        total_new = counts["new_info"] + counts["new_warning"] + counts["new_critical"]
        assert total_new >= 1

    def test_roas_drop_creates_insight(self, db_session: Session) -> None:
        """A large ROAS drop should produce a warning or critical insight."""
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "google_ads_roas")
        campaign = _make_campaign(db_session, tenant, channel, "ROAS Camp")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 3, 1)
        # First 14 days: ROAS = 5.0 (spend=100, cv=500)
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00", conversions="5",
                conversion_value_raw="500.00",
            )
        # Last 7 days: ROAS = 1.0 (spend=100, cv=100)
        for i in range(14, 21):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00", conversions="1",
                conversion_value_raw="100.00",
            )
        db_session.commit()

        counts = generate_insights(
            db_session, tenant.id, as_of_date=date(2024, 3, 21), lookback_days=21
        )
        total_new = counts["new_info"] + counts["new_warning"] + counts["new_critical"]
        assert total_new >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# API tests (FastAPI TestClient with SQLite)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def insights_client(db_session: Session):
    """TestClient with DB and membership overridden; basic entities pre-seeded."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_get_db
    _test_app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(_test_app)
    yield client, tenant, membership

    _test_app.dependency_overrides.clear()


class TestInsightsListEndpoint:
    """GET /api/v1/insights"""

    def test_returns_empty_list_initially(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_created_insight(self, insights_client, db_session: Session) -> None:
        client, tenant, membership = insights_client
        insight = Insight(
            tenant_id=tenant.id,
            category="roas_drop",
            severity="warning",
            title="ROAS düştü",
            body="ROAS önemli ölçüde geriledi.",
            metric="roas",
            channel="google_ads",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 7),
            status="new",
            score=75.0,
            data={"pct_drop": 0.25},
        )
        db_session.add(insight)
        db_session.commit()

        resp = client.get("/api/v1/insights")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["category"] == "roas_drop"
        assert body[0]["title"] == "ROAS düştü"

    def test_filter_by_severity(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        for sev in ("info", "warning", "critical"):
            db_session.add(Insight(
                tenant_id=tenant.id,
                category="anomaly",
                severity=sev,
                title=f"Insight {sev}",
                body="body",
                metric="spend",
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 7),
                status="new",
                score=50.0,
                data={},
            ))
        db_session.commit()

        resp = client.get("/api/v1/insights", params={"severity": "critical"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["severity"] == "critical"

    def test_filter_by_status(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        for st in ("new", "seen", "dismissed"):
            db_session.add(Insight(
                tenant_id=tenant.id,
                category="anomaly",
                severity="info",
                title=f"Status {st}",
                body="body",
                metric="roas",
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 7),
                status=st,
                score=10.0,
                data={},
            ))
        db_session.commit()

        resp = client.get("/api/v1/insights", params={"status": "seen"})
        assert resp.status_code == 200
        body = resp.json()
        assert all(r["status"] == "seen" for r in body)


class TestInsightStatusUpdate:
    """PATCH /api/v1/insights/{id}"""

    def test_mark_seen(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        insight = Insight(
            tenant_id=tenant.id,
            category="roas_drop",
            severity="warning",
            title="title",
            body="body",
            metric="roas",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 7),
            status="new",
            score=50.0,
            data={},
        )
        db_session.add(insight)
        db_session.commit()

        resp = client.patch(
            f"/api/v1/insights/{insight.id}",
            json={"status": "seen"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "seen"

    def test_mark_dismissed(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        insight = Insight(
            tenant_id=tenant.id,
            category="spend_spike",
            severity="critical",
            title="title",
            body="body",
            metric="spend",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 7),
            status="new",
            score=90.0,
            data={},
        )
        db_session.add(insight)
        db_session.commit()

        resp = client.patch(
            f"/api/v1/insights/{insight.id}",
            json={"status": "dismissed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    def test_invalid_status_returns_422(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        insight = Insight(
            tenant_id=tenant.id,
            category="anomaly",
            severity="info",
            title="t",
            body="b",
            metric="spend",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 7),
            status="new",
            score=10.0,
            data={},
        )
        db_session.add(insight)
        db_session.commit()

        resp = client.patch(
            f"/api/v1/insights/{insight.id}",
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 422

    def test_404_on_wrong_tenant(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        other_tenant_id = uuid.uuid4()
        insight = Insight(
            tenant_id=other_tenant_id,  # different tenant
            category="anomaly",
            severity="info",
            title="t",
            body="b",
            metric="roas",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 7),
            status="new",
            score=10.0,
            data={},
        )
        db_session.add(insight)
        db_session.commit()

        resp = client.patch(
            f"/api/v1/insights/{insight.id}",
            json={"status": "seen"},
        )
        assert resp.status_code == 404


class TestGenerateEndpoint:
    """POST /api/v1/insights/generate"""

    def test_returns_counts_with_no_data(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.post("/api/v1/insights/generate")
        assert resp.status_code == 200
        body = resp.json()
        assert "new_info" in body
        assert "new_warning" in body
        assert "new_critical" in body
        assert "skipped" in body
        assert "as_of_date" in body

    def test_generate_with_fact_data(self, insights_client, db_session: Session) -> None:
        client, tenant, _ = insights_client
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "google_ads")
        campaign = _make_campaign(db_session, tenant, channel, "Camp")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 3, 1)
        for i in range(10):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="50.00", conversions="0", conversion_value_raw="0.00",
            )
        db_session.commit()

        resp = client.post("/api/v1/insights/generate")
        assert resp.status_code == 200
        body = resp.json()
        total = body["new_info"] + body["new_warning"] + body["new_critical"]
        assert total >= 0  # may be 0 or more depending on detectors


class TestAlertRuleCRUD:
    """CRUD for /api/v1/insights/alert-rules"""

    def test_list_empty(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.get("/api/v1/insights/alert-rules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_rule(self, insights_client) -> None:
        client, *_ = insights_client
        payload = {
            "name": "ROAS Düşüş Uyarısı",
            "metric": "roas",
            "comparator": "pct_drop",
            "threshold": 20.0,
            "channel_filter": "google_ads",
            "delivery": "email",
            "destination": "alerts@company.com",
            "is_active": True,
        }
        resp = client.post("/api/v1/insights/alert-rules", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "ROAS Düşüş Uyarısı"
        assert body["metric"] == "roas"
        assert body["comparator"] == "pct_drop"
        assert body["threshold"] == 20.0
        assert body["delivery"] == "email"
        assert body["is_active"] is True

    def test_create_and_list(self, insights_client) -> None:
        client, *_ = insights_client
        client.post("/api/v1/insights/alert-rules", json={
            "name": "Anomaly Watch",
            "metric": "spend",
            "comparator": "anomaly",
            "delivery": "slack",
            "destination": "https://hooks.slack.com/services/XXX",
        })
        resp = client.get("/api/v1/insights/alert-rules")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_rule_by_id(self, insights_client) -> None:
        client, *_ = insights_client
        create_resp = client.post("/api/v1/insights/alert-rules", json={
            "name": "Test Rule",
            "metric": "ctr",
            "comparator": "pct_drop",
            "threshold": 25.0,
            "delivery": "none",
        })
        rule_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/insights/alert-rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == rule_id

    def test_update_rule(self, insights_client) -> None:
        client, *_ = insights_client
        create_resp = client.post("/api/v1/insights/alert-rules", json={
            "name": "Initial Name",
            "metric": "roas",
            "comparator": "pct_drop",
            "threshold": 20.0,
            "delivery": "none",
        })
        rule_id = create_resp.json()["id"]

        patch_resp = client.patch(
            f"/api/v1/insights/alert-rules/{rule_id}",
            json={"name": "Updated Name", "is_active": False},
        )
        assert patch_resp.status_code == 200
        updated = patch_resp.json()
        assert updated["name"] == "Updated Name"
        assert updated["is_active"] is False
        # Unchanged fields preserved
        assert updated["metric"] == "roas"

    def test_delete_rule(self, insights_client) -> None:
        client, *_ = insights_client
        create_resp = client.post("/api/v1/insights/alert-rules", json={
            "name": "To Delete",
            "metric": "spend",
            "comparator": "above",
            "threshold": 1000.0,
            "delivery": "none",
        })
        rule_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/insights/alert-rules/{rule_id}")
        assert del_resp.status_code == 204

        get_resp = client.get(f"/api/v1/insights/alert-rules/{rule_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_rule_returns_404(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.get(f"/api/v1/insights/alert-rules/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_invalid_comparator_returns_422(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.post("/api/v1/insights/alert-rules", json={
            "name": "Bad Rule",
            "metric": "roas",
            "comparator": "invalid_op",
            "delivery": "none",
        })
        assert resp.status_code == 422

    def test_invalid_delivery_returns_422(self, insights_client) -> None:
        client, *_ = insights_client
        resp = client.post("/api/v1/insights/alert-rules", json={
            "name": "Bad Delivery",
            "metric": "roas",
            "comparator": "pct_drop",
            "delivery": "telegram",
        })
        assert resp.status_code == 422

    def test_tenant_isolation(self, insights_client, db_session: Session) -> None:
        """A rule created for tenant A should not appear for tenant B."""
        client, tenant_a, _ = insights_client
        client.post("/api/v1/insights/alert-rules", json={
            "name": "Tenant A Rule",
            "metric": "roas",
            "comparator": "pct_drop",
            "delivery": "none",
        })

        # Simulate a different tenant
        tenant_b = _make_tenant(db_session)
        user_b = _make_user(db_session)
        membership_b = _make_membership(db_session, user_b, tenant_b)
        db_session.commit()

        # Override membership to tenant B
        def override_b():
            return membership_b

        _test_app.dependency_overrides[get_current_membership] = override_b
        try:
            resp = client.get("/api/v1/insights/alert-rules")
            assert resp.status_code == 200
            # Tenant B should see 0 rules
            assert resp.json() == []
        finally:
            # Restore: the fixture teardown will call _test_app.dependency_overrides.clear()
            pass
