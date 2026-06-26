"""Tests for the Natural-Language Report Builder.

Coverage
--------
1. Stub parser — channel, metric, date-range, comparison, viz extraction.
2. ``build_report`` — correct aggregation using the seeded SQLite DB pattern
   from test_dashboard_api.py (no duplication of DB helpers; they are imported
   directly).
3. API endpoint — POST /api/v1/reports/build via FastAPI TestClient.

No live network calls are made anywhere in this file (stub path only).

Re-use
------
All ORM helpers (_make_tenant, _make_user, etc.) and _insert_fact are imported
from test_dashboard_api to avoid any duplication of fixture code.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta, timezone, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Re-use existing DB/fixture helpers from the dashboard tests
from tests.test_dashboard_api import (
    _insert_fact,
    _make_ad,
    _make_adset,
    _make_campaign,
    _make_channel,
    _make_connected_account,
    _make_membership,
    _make_tenant,
    _make_user,
)

from ayaz.api.deps import get_current_membership, get_db
from ayaz.database import get_db as db_get_db  # same object, alias for clarity
from ayaz.main import app

# Register the report_builder router on the shared test app.
# main.py does not include it yet (the team lead wires it); we add it here
# so the API endpoint tests resolve correctly.  FastAPI de-duplicates routes
# by (method, path) so including the same router twice is harmless when tests
# run in the same process as other test modules.
from ayaz.api.v1 import report_builder as _rb_module

_PREFIX = "/api/v1"
# Guard: only include once even if this module is imported multiple times.
_route_paths = set()
for _r in getattr(app, "routes", []):
    if hasattr(_r, "path"):
        _route_paths.add(_r.path)
if "/api/v1/reports/build" not in _route_paths:
    app.include_router(_rb_module.router, prefix=_PREFIX)
del _route_paths
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
from ayaz.services.report_builder import (
    ReportSpec,
    _extract_channels,
    _extract_comparison,
    _extract_date_range,
    _extract_metrics,
    _extract_viz,
    _stub_parse,
    build_report,
    parse_request,
)

# ── In-memory SQLite helpers ───────────────────────────────────────────────────

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


@pytest.fixture()
def seeded_db(db_session: Session):
    """
    Seed fixture with two channels:

    meta_ads
        2024-03-15: impressions=1000, clicks=50, spend=200.00, conv=10, cv=1000.00

    google_ads
        2024-03-15: impressions=2000, clicks=100, spend=300.00, conv=15, cv=1500.00
        2024-03-16: impressions=500,  clicks=25,  spend=100.00, conv=5,  cv=500.00

    Totals (2024-03-15 → 2024-03-16):
        spend       = 200 + 300 + 100 = 600
        impressions = 1000 + 2000 + 500 = 3500
        clicks      = 50 + 100 + 25 = 175
        conversions = 10 + 15 + 5 = 30
        conv_value  = 1000 + 1500 + 500 = 3000
    """
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_meta = _make_connected_account(db_session, tenant, Platform.sample, "META-001")
    acct_gads = _make_connected_account(db_session, tenant, Platform.google_ads, "GADS-001")

    ch_meta = _make_channel(db_session, "meta_ads")
    ch_gads = _make_channel(db_session, "google_ads")

    camp_meta = _make_campaign(db_session, tenant, ch_meta, "M-100", "Meta Camp")
    adset_meta = _make_adset(db_session, tenant, camp_meta, "M-AS-1")
    ad_meta = _make_ad(db_session, tenant, adset_meta, "M-AD-1")

    camp_gads = _make_campaign(db_session, tenant, ch_gads, "G-100", "Google Camp")
    adset_gads = _make_adset(db_session, tenant, camp_gads, "G-AS-1")
    ad_gads = _make_ad(db_session, tenant, adset_gads, "G-AD-1")

    _insert_fact(
        db_session, tenant, acct_meta, ch_meta, camp_meta, adset_meta, ad_meta,
        date(2024, 3, 15),
        impressions=1000, clicks=50, cost_raw="200.00",
        conversions="10", conversion_value_raw="1000.00",
    )
    _insert_fact(
        db_session, tenant, acct_gads, ch_gads, camp_gads, adset_gads, ad_gads,
        date(2024, 3, 15),
        impressions=2000, clicks=100, cost_raw="300.00",
        conversions="15", conversion_value_raw="1500.00",
    )
    _insert_fact(
        db_session, tenant, acct_gads, ch_gads, camp_gads, adset_gads, ad_gads,
        date(2024, 3, 16),
        impressions=500, clicks=25, cost_raw="100.00",
        conversions="5", conversion_value_raw="500.00",
    )
    db_session.commit()

    return db_session, membership


@pytest.fixture()
def seeded_client(seeded_db):
    """FastAPI TestClient with the seeded DB and membership overridden."""
    db_session, membership = seeded_db

    def override_get_db():
        yield db_session

    def override_get_membership():
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ── Stub parser: channel extraction ──────────────────────────────────────────


class TestChannelExtraction:
    def test_meta_and_google(self):
        channels = _extract_channels("Meta vs Google son 30 gün")
        assert set(channels) == {"meta_ads", "google_ads"}

    def test_facebook_maps_to_meta(self):
        assert "meta_ads" in _extract_channels("Facebook kampanyaları")

    def test_instagram_maps_to_meta(self):
        assert "meta_ads" in _extract_channels("Instagram reklamları harcama")

    def test_tiktok(self):
        assert "tiktok_ads" in _extract_channels("tiktok harcama raporu")

    def test_linkedin(self):
        assert "linkedin_ads" in _extract_channels("LinkedIn reklam performansı")

    def test_microsoft(self):
        assert "microsoft_ads" in _extract_channels("Microsoft Ads son 7 gün")

    def test_criteo(self):
        assert "criteo" in _extract_channels("Criteo dönüşüm")

    def test_pinterest(self):
        assert "pinterest_ads" in _extract_channels("Pinterest gösterim")

    def test_no_channel_returns_empty(self):
        assert _extract_channels("son 30 gün harcama raporu") == []

    def test_deduplication(self):
        channels = _extract_channels("meta facebook instagram")
        assert channels.count("meta_ads") == 1


class TestMetricExtraction:
    def test_harcama_maps_to_spend(self):
        assert "spend" in _extract_metrics("harcama raporu")

    def test_roas(self):
        assert "roas" in _extract_metrics("roas analizi")

    def test_tiklama(self):
        assert "clicks" in _extract_metrics("tıklama sayısı")

    def test_gosterim(self):
        assert "impressions" in _extract_metrics("gösterim raporu")

    def test_donusum(self):
        assert "conversions" in _extract_metrics("dönüşüm analizi")

    def test_ctr(self):
        assert "ctr" in _extract_metrics("CTR raporu")

    def test_cpc(self):
        assert "cpc" in _extract_metrics("CPC nedir")

    def test_cpa(self):
        assert "cpa" in _extract_metrics("CPA optimizasyonu")

    def test_default_when_no_metric(self):
        metrics = _extract_metrics("son 30 gün raporu")
        assert metrics == ["spend", "roas", "conversions"]

    def test_deduplication(self):
        metrics = _extract_metrics("spend harcama")
        assert metrics.count("spend") == 1


class TestDateRangeExtraction:
    def _df(self) -> date:
        return date(2026, 1, 1)

    def _dt(self) -> date:
        return date(2026, 1, 31)

    def test_son_30_gun(self):
        today = date.today()
        d_from, d_to = _extract_date_range("son 30 gün", self._df(), self._dt())
        assert d_to == today
        assert d_from == today - timedelta(days=29)
        assert (d_to - d_from).days == 29  # 30 inclusive days

    def test_son_7_gun(self):
        today = date.today()
        d_from, d_to = _extract_date_range("son 7 gün", self._df(), self._dt())
        assert d_to == today
        assert (d_to - d_from).days == 6

    def test_son_90_gun(self):
        today = date.today()
        d_from, d_to = _extract_date_range("son 90 gün", self._df(), self._dt())
        assert d_to == today
        assert (d_to - d_from).days == 89

    def test_bu_ay(self):
        today = date.today()
        d_from, d_to = _extract_date_range("bu ay raporu", self._df(), self._dt())
        assert d_from == today.replace(day=1)
        assert d_to == today

    def test_gecen_ay(self):
        today = date.today()
        d_from, d_to = _extract_date_range("geçen ay", self._df(), self._dt())
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        assert d_from == first_prev
        assert d_to == last_prev

    def test_fallback_to_defaults(self):
        d_from, d_to = _extract_date_range("performans özeti", self._df(), self._dt())
        assert d_from == self._df()
        assert d_to == self._dt()


class TestComparisonExtraction:
    def test_vs(self):
        assert _extract_comparison("Meta vs Google") is True

    def test_kiyasla(self):
        assert _extract_comparison("Meta kıyas Google") is True

    def test_karsilastir(self):
        assert _extract_comparison("karşılaştır") is True

    def test_no_comparison(self):
        assert _extract_comparison("Meta son 30 gün harcama") is False


class TestVizExtraction:
    def test_trend(self):
        assert _extract_viz("trend raporu") == "timeseries"

    def test_zaman(self):
        assert _extract_viz("zaman serisi analizi") == "timeseries"

    def test_tablo(self):
        assert _extract_viz("tablo görünümü") == "table"

    def test_default_mixed(self):
        assert _extract_viz("meta harcama") == "mixed"


# ── Full stub parse: canonical example ───────────────────────────────────────


class TestStubParse:
    def test_meta_vs_google_son_30_gun(self):
        """The canonical example from the spec."""
        today = date.today()
        default_from = today - timedelta(days=29)
        spec = _stub_parse(
            "Meta vs Google son 30 gün",
            default_from=default_from,
            default_to=today,
        )
        assert set(spec.channels) == {"meta_ads", "google_ads"}
        assert spec.comparison is True
        # 30-day range
        assert spec.date_to == today
        assert (spec.date_to - spec.date_from).days == 29

    def test_spec_has_all_fields(self):
        today = date.today()
        spec = _stub_parse(
            "Meta harcama roas",
            default_from=today - timedelta(days=29),
            default_to=today,
        )
        assert isinstance(spec.title, str) and spec.title
        assert isinstance(spec.metrics, list)
        assert isinstance(spec.channels, list)
        assert isinstance(spec.comparison, bool)
        assert spec.viz in ("timeseries", "table", "mixed")
        assert isinstance(spec.date_from, date)
        assert isinstance(spec.date_to, date)

    def test_metrics_with_no_channel(self):
        today = date.today()
        spec = _stub_parse(
            "dönüşüm ve roas analizi son 7 gün",
            default_from=today - timedelta(days=29),
            default_to=today,
        )
        assert "conversions" in spec.metrics
        assert "roas" in spec.metrics
        assert spec.channels == []

    def test_timeseries_viz_detected(self):
        today = date.today()
        spec = _stub_parse(
            "Google trend raporu",
            default_from=today - timedelta(days=29),
            default_to=today,
        )
        assert spec.viz == "timeseries"

    def test_table_viz_detected(self):
        today = date.today()
        spec = _stub_parse(
            "Meta tablo görünümü",
            default_from=today - timedelta(days=29),
            default_to=today,
        )
        assert spec.viz == "table"

    def test_parse_request_uses_stub_without_api_key(self, monkeypatch):
        """parse_request falls back to stub when anthropic_api_key is empty."""
        from ayaz import config as cfg

        monkeypatch.setattr(cfg.settings, "anthropic_api_key", "")
        today = date.today()
        spec = parse_request(
            "Meta vs Google son 30 gün",
            default_from=today - timedelta(days=29),
            default_to=today,
        )
        assert set(spec.channels) == {"meta_ads", "google_ads"}
        assert spec.comparison is True


# ── build_report: aggregation against seeded SQLite ──────────────────────────


class TestBuildReport:
    def _make_spec(self, channels=None, date_from=None, date_to=None):
        d_from = date_from or date(2024, 3, 15)
        d_to = date_to or date(2024, 3, 16)
        return ReportSpec(
            title="Test Raporu",
            metrics=["spend", "roas", "conversions"],
            channels=channels or [],
            comparison=len(channels or []) > 1,
            viz="mixed",
            date_from=d_from,
            date_to=d_to,
        )

    def test_totals_all_channels(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)

        totals = result["totals"]
        assert totals["spend"] == pytest.approx(600.0)
        assert totals["impressions"] == pytest.approx(3500.0)
        assert totals["clicks"] == pytest.approx(175.0)
        assert totals["conversions"] == pytest.approx(30.0)
        assert totals["conversion_value"] == pytest.approx(3000.0)

    def test_derived_metrics_in_totals(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)
        totals = result["totals"]
        # ROAS = 3000 / 600 = 5.0
        assert totals["roas"] == pytest.approx(5.0)
        # CTR = 175 / 3500 = 0.05
        assert totals["ctr"] == pytest.approx(175 / 3500)
        # CPC = 600 / 175
        assert totals["cpc"] == pytest.approx(600 / 175, rel=1e-4)
        # CPA = 600 / 30 = 20
        assert totals["cpa"] == pytest.approx(20.0)

    def test_by_channel_filtered_to_spec_channels(self, seeded_db):
        db_session, membership = seeded_db
        # Only request google_ads
        spec = self._make_spec(channels=["google_ads"])
        result = build_report(db_session, membership.tenant_id, spec)
        by_channel = result["by_channel"]
        assert len(by_channel) == 1
        assert by_channel[0]["channel"] == "google_ads"

    def test_by_channel_unfiltered_has_both(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec(channels=[])
        result = build_report(db_session, membership.tenant_id, spec)
        channel_names = {c["channel"] for c in result["by_channel"]}
        assert channel_names == {"meta_ads", "google_ads"}

    def test_google_ads_spend_correct(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec(channels=["google_ads"])
        result = build_report(db_session, membership.tenant_id, spec)
        # google_ads: 300 + 100 = 400
        assert result["by_channel"][0]["spend"] == pytest.approx(400.0)

    def test_meta_ads_spend_correct(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec(channels=["meta_ads"])
        result = build_report(db_session, membership.tenant_id, spec)
        # meta_ads: 200 only (one row on 2024-03-15)
        assert result["by_channel"][0]["spend"] == pytest.approx(200.0)

    def test_timeseries_present(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)
        # Two distinct dates → two points
        assert len(result["timeseries"]) == 2

    def test_timeseries_point_structure(self, seeded_db):
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)
        pt = result["timeseries"][0]
        assert "date" in pt
        assert "value" in pt
        assert isinstance(pt["value"], (int, float))

    def test_timeseries_day1_spend(self, seeded_db):
        """2024-03-15 spend = 200 (meta) + 300 (google) = 500."""
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)
        by_date = {p["date"]: p["value"] for p in result["timeseries"]}
        assert by_date["2024-03-15"] == pytest.approx(500.0)

    def test_timeseries_day2_spend(self, seeded_db):
        """2024-03-16 spend = 100 (google only)."""
        db_session, membership = seeded_db
        spec = self._make_spec()
        result = build_report(db_session, membership.tenant_id, spec)
        by_date = {p["date"]: p["value"] for p in result["timeseries"]}
        assert by_date["2024-03-16"] == pytest.approx(100.0)

    def test_tenant_isolation(self, db_session: Session):
        """A different tenant sees no data from the seeded rows."""
        # Seed data under tenant A
        tenant_a = _make_tenant(db_session)
        user_a = _make_user(db_session)
        mem_a = _make_membership(db_session, user_a, tenant_a)

        acct = _make_connected_account(db_session, tenant_a, Platform.sample, "T-001")
        ch = _make_channel(db_session, "google_ads")
        camp = _make_campaign(db_session, tenant_a, ch, "C-1", "Camp")
        adset = _make_adset(db_session, tenant_a, camp, "AS-1")
        ad = _make_ad(db_session, tenant_a, adset, "AD-1")
        _insert_fact(
            db_session, tenant_a, acct, ch, camp, adset, ad,
            date(2024, 3, 15),
            impressions=1000, clicks=50, cost_raw="200.00",
            conversions="10", conversion_value_raw="500.00",
        )
        db_session.commit()

        # Query as tenant B (different UUID, no data)
        tenant_b_id = uuid.uuid4()
        spec = ReportSpec(
            title="Test",
            metrics=["spend"],
            channels=[],
            comparison=False,
            viz="mixed",
            date_from=date(2024, 3, 1),
            date_to=date(2024, 3, 31),
        )
        result = build_report(db_session, tenant_b_id, spec)
        assert result["totals"]["spend"] == 0.0
        assert result["by_channel"] == []
        assert result["timeseries"] == []


# ── API endpoint tests ────────────────────────────────────────────────────────


class TestBuildEndpoint:
    def test_returns_200(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Meta vs Google son 30 gün", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.status_code == 200

    def test_response_has_spec_and_data(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "harcama raporu", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        body = resp.json()
        assert "spec" in body
        assert "data" in body

    def test_spec_fields(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Meta vs Google son 30 gün", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        spec = resp.json()["spec"]
        for key in ("title", "metrics", "channels", "comparison", "viz", "date_from", "date_to"):
            assert key in spec, f"Missing key: {key}"

    def test_channels_parsed_correctly(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Meta vs Google son 30 gün", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        spec = resp.json()["spec"]
        assert set(spec["channels"]) == {"meta_ads", "google_ads"}

    def test_comparison_flag(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Meta vs Google son 30 gün", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.json()["spec"]["comparison"] is True

    def test_data_totals_present(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "harcama", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        data = resp.json()["data"]
        assert "totals" in data
        assert "by_channel" in data
        assert "timeseries" in data

    def test_data_numbers_are_floats(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "harcama", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        totals = resp.json()["data"]["totals"]
        for key in ("spend", "impressions", "clicks", "conversions", "roas", "ctr", "cpc", "cpa"):
            assert isinstance(totals[key], (int, float)), f"{key} should be a number"

    def test_empty_prompt_returns_422(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": ""},
        )
        assert resp.status_code == 422

    def test_whitespace_only_prompt_returns_422(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "   "},
        )
        assert resp.status_code == 422

    def test_missing_prompt_returns_422(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.status_code == 422

    def test_no_dates_uses_last_30_days(self, seeded_client: TestClient):
        """Without date_from/date_to, the spec should default to the last 30 days."""
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "genel harcama raporu"},
        )
        assert resp.status_code == 200
        spec = resp.json()["spec"]
        today = date.today()
        assert spec["date_to"] == today.isoformat()
        assert spec["date_from"] == (today - timedelta(days=29)).isoformat()

    def test_by_channel_filtered_when_channels_in_prompt(self, seeded_client: TestClient):
        """When only google is mentioned, by_channel should only show google_ads."""
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Google harcama", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        by_channel = resp.json()["data"]["by_channel"]
        channel_names = {c["channel"] for c in by_channel}
        assert "meta_ads" not in channel_names
        assert "google_ads" in channel_names

    def test_correct_spend_total_for_date_range(self, seeded_client: TestClient):
        """All channels, 2024-03-15→16: spend = 200+300+100 = 600."""
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "harcama", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.json()["data"]["totals"]["spend"] == pytest.approx(600.0)

    def test_title_is_non_empty_string(self, seeded_client: TestClient):
        resp = seeded_client.post(
            "/api/v1/reports/build",
            json={"prompt": "Meta raporu", "date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        title = resp.json()["spec"]["title"]
        assert isinstance(title, str) and len(title) > 0
