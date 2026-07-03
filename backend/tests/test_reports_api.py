"""Integration tests for the Advanced Reporting module (M3+).

Strategy
--------
* FastAPI TestClient with a minimal test app that includes only the reports router.
  This avoids touching main.py (owned by the team lead) while still exercising
  the full HTTP layer.
* get_db overridden to an in-memory SQLite session.
* get_current_membership overridden to a pre-built Membership (no auth round-trip).
* A ``seeded_client`` fixture inserts a known set of fact rows (same data as
  test_dashboard_api.py) so report payload math can be verified against the
  known dashboard summary values.

Hermeticity
-----------
* No live Postgres, no live network, no fixture files read by this module.
* All fact data is inserted directly into the SQLite DB using the ORM.

Fact data seed (mirrors test_dashboard_api.py)
----------------------------------------------
  Channel: sample
    2024-03-15: impressions=100, clicks=10, spend=50.00, conv=2, cv=200.00
    2024-03-16: impressions=200, clicks=20, spend=100.00, conv=4, cv=400.00

  Channel: google_ads
    2024-03-15: impressions=500, clicks=25, spend=75.00, conv=5, cv=375.00

  Summary totals for 2024-03-15 → 2024-03-16:
    impressions=800, clicks=55, spend=225.00, conv=11, cv=975.00
    CTR  = 55/800   = 0.06875
    CPC  = 225/55   ≈ 4.0909...
    CPA  = 225/11   ≈ 20.4545...
    ROAS = 975/225  ≈ 4.3333...
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

# Register all model modules on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401
import ayaz.models.insights  # noqa: F401
import ayaz.models.reports  # noqa: F401

from ayaz.database import get_db
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
from ayaz.models.reports import ReportDefinition, ReportSchedule, SharedReport
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import reports as reports_module
from ayaz.services.auth import hash_password
from ayaz.services.reports import (
    build_report_payload,
    due_schedules,
    mark_sent,
    render_report_html,
)

# Minimal test app — only the reports router.
_test_app = FastAPI(title="AYAZ Reports Test App")
_test_app.include_router(reports_module.router, prefix="/api/v1")


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


# ── Data helpers ──────────────────────────────────────────────────────────────


def _make_tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name="Test Tenant", base_currency="USD",
        country="US", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user(db: Session) -> User:
    u = User(
        id=uuid.uuid4(), email="reports@ayaz.app",
        hashed_password=hash_password("secret"),
        full_name="Reports User",
    )
    db.add(u)
    db.flush()
    return u


def _make_membership(db: Session, user: User, tenant: Tenant) -> Membership:
    m = Membership(
        id=uuid.uuid4(), user_id=user.id,
        tenant_id=tenant.id, role=MembershipRole.owner,
    )
    db.add(m)
    db.flush()
    return m


def _ensure_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d, year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week,
        day_of_week=d.weekday(), is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel, ext_id: str, name: str) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant.id, channel_id=channel.id,
        external_id=ext_id, name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign, ext_id: str) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant.id,
        campaign_id=campaign.id, external_id=ext_id, name=ext_id,
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet, ext_id: str) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(), tenant_id=tenant.id,
        ad_set_id=adset.id, external_id=ext_id, name=ext_id,
    )
    db.add(ad)
    db.flush()
    return ad


def _insert_fact(
    db: Session, tenant: Tenant, acct: ConnectedAccount,
    channel: DimChannel, campaign: DimCampaign, adset: DimAdSet, ad: DimAd,
    d: date, *, impressions: int = 0, clicks: int = 0,
    cost_raw: str = "0", conversions: str = "0", conversion_value_raw: str = "0",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(cost_raw)
    fact = FactDailyMetrics(
        id=uuid.uuid4(), tenant_id=tenant.id,
        connected_account_id=acct.id, channel_id=channel.id,
        campaign_id=campaign.id, adset_id=adset.id, ad_id=ad.id,
        date_key=d, impressions=impressions, clicks=clicks,
        cost_raw=cost, cost_ccy="USD",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value_raw),
        conversion_value_ccy="USD",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value_raw),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.flush()
    return fact


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with seeded fact data and dependency overrides."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)

    acct_sample = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=Platform.sample, external_account_id="ACC-001",
        display_name="Sample", vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    acct_gads = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id,
        platform=Platform.google_ads, external_account_id="GADS-001",
        display_name="Google Ads", vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add_all([acct_sample, acct_gads])
    db_session.flush()

    ch_sample = _make_channel(db_session, "sample")
    ch_gads = _make_channel(db_session, "google_ads")

    camp_s = _make_campaign(db_session, tenant, ch_sample, "CAMP-100", "Spring Sale")
    adset_s = _make_adset(db_session, tenant, camp_s, "ADSET-200")
    ad_s = _make_ad(db_session, tenant, adset_s, "AD-300")

    camp_g = _make_campaign(db_session, tenant, ch_gads, "111", "Summer Promo")
    adset_g = _make_adset(db_session, tenant, camp_g, "(not set)")
    ad_g = _make_ad(db_session, tenant, adset_g, "(not set)")

    _insert_fact(
        db_session, tenant, acct_sample, ch_sample, camp_s, adset_s, ad_s,
        date(2024, 3, 15),
        impressions=100, clicks=10, cost_raw="50.00",
        conversions="2", conversion_value_raw="200.00",
    )
    _insert_fact(
        db_session, tenant, acct_sample, ch_sample, camp_s, adset_s, ad_s,
        date(2024, 3, 16),
        impressions=200, clicks=20, cost_raw="100.00",
        conversions="4", conversion_value_raw="400.00",
    )
    _insert_fact(
        db_session, tenant, acct_gads, ch_gads, camp_g, adset_g, ad_g,
        date(2024, 3, 15),
        impressions=500, clicks=25, cost_raw="75.00",
        conversions="5", conversion_value_raw="375.00",
    )
    db_session.commit()

    # Store tenant on the membership object so tests can reference it
    membership._tenant_obj = tenant

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_get_db
    _test_app.dependency_overrides[get_current_membership] = override_get_membership

    tc = TestClient(_test_app)
    tc._db_session = db_session
    tc._membership = membership
    tc._tenant = tenant
    yield tc

    _test_app.dependency_overrides.clear()


# ── ReportDefinition CRUD tests ───────────────────────────────────────────────


class TestReportDefinitionCRUD:
    def test_create_definition(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "My Report", "config": {"sections": ["totals", "by_channel"]}},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "My Report"
        assert "id" in body
        assert body["config"]["sections"] == ["totals", "by_channel"]

    def test_list_definitions_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/reports/definitions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_definitions_with_data(self, client: TestClient) -> None:
        client.post(
            "/api/v1/reports/definitions",
            json={"name": "Report A", "config": {}},
        )
        client.post(
            "/api/v1/reports/definitions",
            json={"name": "Report B", "config": {}},
        )
        resp = client.get("/api/v1/reports/definitions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_definition(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Get Me", "config": {}},
        )
        def_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/reports/definitions/{def_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Me"

    def test_get_nonexistent_definition_returns_404(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/reports/definitions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patch_definition_name(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Old Name", "config": {}},
        )
        def_id = create_resp.json()["id"]
        resp = client.patch(
            f"/api/v1/reports/definitions/{def_id}",
            json={"name": "New Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_delete_definition(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Delete Me", "config": {}},
        )
        def_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/v1/reports/definitions/{def_id}")
        assert del_resp.status_code == 204

        # Verify gone
        get_resp = client.get(f"/api/v1/reports/definitions/{def_id}")
        assert get_resp.status_code == 404


# ── build_report_payload math tests ──────────────────────────────────────────


class TestBuildReportPayload:
    """Verify payload math against the known seeded fact rows."""

    def _defn(self, db: Session, tenant: Tenant) -> ReportDefinition:
        """Create a minimal ReportDefinition ORM object (not persisted)."""
        defn = ReportDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Test Report",
            config={
                "sections": ["totals", "by_channel", "timeseries"],
            },
        )
        db.add(defn)
        db.flush()
        return defn

    def test_totals_spend(self, client: TestClient) -> None:
        """Total spend 50+100+75 = 225."""
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert payload["totals"]["spend"] == pytest.approx(225.0)

    def test_totals_impressions(self, client: TestClient) -> None:
        """100+200+500 = 800."""
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert payload["totals"]["impressions"] == pytest.approx(800.0)

    def test_totals_clicks(self, client: TestClient) -> None:
        """10+20+25 = 55."""
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert payload["totals"]["clicks"] == pytest.approx(55.0)

    def test_totals_roas(self, client: TestClient) -> None:
        """ROAS = 975 / 225 ≈ 4.333."""
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert payload["totals"]["roas"] == pytest.approx(975 / 225, rel=1e-4)

    def test_by_channel_count(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert len(payload["by_channel"]) == 2

    def test_by_channel_names(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        names = {ch["channel"] for ch in payload["by_channel"]}
        assert names == {"sample", "google_ads"}

    def test_timeseries_has_two_dates(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert len(payload["timeseries"]) == 2

    def test_timeseries_day1_spend(self, client: TestClient) -> None:
        """2024-03-15 spend = 50 + 75 = 125."""
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        by_date = {p["date"]: p["spend"] for p in payload["timeseries"]}
        assert by_date["2024-03-15"] == pytest.approx(125.0)

    def test_channel_filter_limits_results(self, client: TestClient) -> None:
        """config.channels=['sample'] should return only sample channel."""
        db = client._db_session
        tenant = client._tenant
        defn = ReportDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Filtered",
            config={"sections": ["totals", "by_channel"], "channels": ["sample"]},
        )
        db.add(defn)
        db.flush()
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert len(payload["by_channel"]) == 1
        assert payload["by_channel"][0]["channel"] == "sample"
        # Total spend should only be the sample channel: 50+100=150
        assert payload["totals"]["spend"] == pytest.approx(150.0)

    def test_no_data_returns_zero_totals(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._defn(db, tenant)
        payload = build_report_payload(db, defn, date(2025, 1, 1), date(2025, 1, 31))
        assert payload["totals"]["spend"] == 0.0
        assert payload["by_channel"] == []
        assert payload["timeseries"] == []

    def test_payload_has_branding(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = ReportDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Branded",
            config={
                "brand_name": "AcmeCorp",
                "primary_color": "#FF0000",
                "sections": ["totals"],
            },
        )
        db.add(defn)
        db.flush()
        payload = build_report_payload(db, defn, date(2024, 3, 15), date(2024, 3, 16))
        assert payload["branding"]["brand_name"] == "AcmeCorp"
        assert payload["branding"]["primary_color"] == "#FF0000"


# ── render_report_html tests ──────────────────────────────────────────────────


class TestRenderReportHtml:
    """Verify the HTML renderer produces Turkish labels and correct KPI values."""

    def _make_payload(
        self,
        *,
        brand_name: str = "TestBrand",
        spend: float = 225.0,
    ) -> dict:
        return {
            "report_id": str(uuid.uuid4()),
            "report_name": "Test Raporu",
            "date_from": "2024-03-15",
            "date_to": "2024-03-16",
            "generated_at": "2024-03-17T00:00:00+00:00",
            "branding": {
                "brand_name": brand_name,
                "logo_url": None,
                "primary_color": "#1A73E8",
            },
            "sections": ["totals", "by_channel", "timeseries", "insights"],
            "totals": {
                "spend": spend,
                "impressions": 800.0,
                "clicks": 55.0,
                "conversions": 11.0,
                "conversion_value": 975.0,
                "ctr": 55 / 800,
                "cpc": 225 / 55,
                "cpa": 225 / 11,
                "roas": 975 / 225,
            },
            "by_channel": [
                {
                    "channel": "sample",
                    "spend": 150.0, "impressions": 300.0, "clicks": 30.0,
                    "conversions": 6.0, "conversion_value": 600.0,
                    "ctr": 0.1, "cpc": 5.0, "cpa": 25.0, "roas": 4.0,
                },
                {
                    "channel": "google_ads",
                    "spend": 75.0, "impressions": 500.0, "clicks": 25.0,
                    "conversions": 5.0, "conversion_value": 375.0,
                    "ctr": 0.05, "cpc": 3.0, "cpa": 15.0, "roas": 5.0,
                },
            ],
            "timeseries": [
                {"date": "2024-03-15", "spend": 125.0},
                {"date": "2024-03-16", "spend": 100.0},
            ],
            "insights": [
                {
                    "category": "roas_drop",
                    "severity": "warning",
                    "title": "ROAS Dusuk",
                    "body": "ROAS son 7 gunde %25 dustu.",
                    "score": 40.0,
                },
            ],
        }

    def test_contains_brand_name(self) -> None:
        payload = self._make_payload(brand_name="AcmeCorp")
        html_str = render_report_html(payload, payload["branding"])
        assert "AcmeCorp" in html_str

    def test_contains_turkish_label_harcama(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "Harcama" in html_str

    def test_contains_turkish_label_donusum(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "Donusum" in html_str

    def test_contains_turkish_label_kanal(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "Kanal" in html_str

    def test_contains_spend_value(self) -> None:
        payload = self._make_payload(spend=225.0)
        html_str = render_report_html(payload, payload["branding"])
        assert "225,00" in html_str  # TR biçim (binlik nokta, ondalık virgül)

    def test_contains_channel_names(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "sample" in html_str
        assert "google_ads" in html_str

    def test_contains_insights_title(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "ROAS Dusuk" in html_str

    def test_contains_date_range(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "2024-03-15" in html_str
        assert "2024-03-16" in html_str

    def test_is_valid_html_doctype(self) -> None:
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert html_str.strip().startswith("<!DOCTYPE html>")

    def test_no_external_script_tags(self) -> None:
        """HTML must be fully self-contained — no external CDN or <script> tags."""
        payload = self._make_payload()
        html_str = render_report_html(payload, payload["branding"])
        assert "<script" not in html_str.lower()

    def test_custom_primary_color_in_html(self) -> None:
        payload = self._make_payload()
        payload["branding"]["primary_color"] = "#FF1234"
        html_str = render_report_html(payload, payload["branding"])
        assert "#FF1234" in html_str


# ── Preview endpoint tests ────────────────────────────────────────────────────


class TestPreviewEndpoint:
    def test_preview_returns_json(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Preview Test", "config": {"sections": ["totals"]}},
        )
        def_id = create_resp.json()["id"]
        resp = client.get(
            f"/api/v1/reports/definitions/{def_id}/preview",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "totals" in body
        assert body["totals"]["spend"] == pytest.approx(225.0)

    def test_preview_invalid_date_range_returns_422(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Bad Dates", "config": {}},
        )
        def_id = create_resp.json()["id"]
        resp = client.get(
            f"/api/v1/reports/definitions/{def_id}/preview",
            params={"date_from": "2024-03-16", "date_to": "2024-03-15"},
        )
        assert resp.status_code == 422


# ── Share / public link tests ─────────────────────────────────────────────────


class TestShareAndPublicEndpoint:
    def _create_def(self, client: TestClient) -> str:
        resp = client.post(
            "/api/v1/reports/definitions",
            json={
                "name": "Share Me",
                "config": {
                    "sections": ["totals", "by_channel"],
                    "brand_name": "ClientBrand",
                },
            },
        )
        return resp.json()["id"]

    def test_share_creates_public_token(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "public_token" in body
        assert len(body["public_token"]) > 10
        assert "public_url" in body
        assert body["public_url"].endswith(body["public_token"])

    def test_public_link_returns_html(self, client: TestClient) -> None:
        """The public endpoint must return text/html without auth."""
        def_id = self._create_def(client)
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        token = share_resp.json()["public_token"]

        # Access without any auth headers
        resp = client.get(
            f"/api/v1/reports/public/{token}",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<!DOCTYPE html>" in resp.text

    def test_public_link_contains_brand_name(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        token = share_resp.json()["public_token"]
        resp = client.get(
            f"/api/v1/reports/public/{token}",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert "ClientBrand" in resp.text

    def test_public_link_contains_kpi_values(self, client: TestClient) -> None:
        """spend=225 must appear in the rendered HTML."""
        def_id = self._create_def(client)
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        token = share_resp.json()["public_token"]
        resp = client.get(
            f"/api/v1/reports/public/{token}",
            params={"date_from": "2024-03-15", "date_to": "2024-03-16"},
        )
        assert "225,00" in resp.text  # TR biçim

    def test_public_link_increments_view_count(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        token = share_resp.json()["public_token"]

        # Access twice
        client.get(f"/api/v1/reports/public/{token}")
        client.get(f"/api/v1/reports/public/{token}")

        # Check view_count via the shares list
        shares_resp = client.get("/api/v1/reports/shares")
        share = next(s for s in shares_resp.json() if s["public_token"] == token)
        assert share["view_count"] == 2

    def test_revoked_link_returns_404(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={},
        )
        share_id = share_resp.json()["id"]
        token = share_resp.json()["public_token"]

        # Revoke
        client.delete(f"/api/v1/reports/shares/{share_id}")

        # Access should be 404
        resp = client.get(f"/api/v1/reports/public/{token}")
        assert resp.status_code == 404

    def test_expired_link_returns_404(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        # Set expiry in the past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        share_resp = client.post(
            f"/api/v1/reports/definitions/{def_id}/share",
            json={"expires_at": past},
        )
        token = share_resp.json()["public_token"]

        resp = client.get(f"/api/v1/reports/public/{token}")
        assert resp.status_code == 404

    def test_unknown_token_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/reports/public/nonexistent-token-xyz")
        assert resp.status_code == 404

    def test_list_shares(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        client.post(f"/api/v1/reports/definitions/{def_id}/share", json={})
        client.post(f"/api/v1/reports/definitions/{def_id}/share", json={})
        resp = client.get("/api/v1/reports/shares")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── ReportSchedule CRUD tests ─────────────────────────────────────────────────


class TestReportScheduleCRUD:
    def _create_def(self, client: TestClient) -> str:
        resp = client.post(
            "/api/v1/reports/definitions",
            json={"name": "Scheduled Report", "config": {}},
        )
        return resp.json()["id"]

    def test_create_daily_schedule(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        resp = client.post(
            "/api/v1/reports/schedules",
            json={
                "report_definition_id": def_id,
                "cadence": "daily",
                "hour": 9,
                "delivery": "email",
                "recipients": ["cmo@example.com"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["cadence"] == "daily"
        assert body["hour"] == 9
        assert "cmo@example.com" in body["recipients"]

    def test_create_weekly_schedule(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        resp = client.post(
            "/api/v1/reports/schedules",
            json={
                "report_definition_id": def_id,
                "cadence": "weekly",
                "weekday": 0,  # Monday
                "hour": 8,
                "delivery": "email",
                "recipients": [],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["weekday"] == 0

    def test_create_monthly_schedule(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        resp = client.post(
            "/api/v1/reports/schedules",
            json={
                "report_definition_id": def_id,
                "cadence": "monthly",
                "hour": 7,
                "delivery": "email",
                "recipients": [],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["cadence"] == "monthly"

    def test_invalid_cadence_returns_422(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        resp = client.post(
            "/api/v1/reports/schedules",
            json={
                "report_definition_id": def_id,
                "cadence": "hourly",
                "hour": 0,
                "delivery": "email",
                "recipients": [],
            },
        )
        assert resp.status_code == 422

    def test_list_schedules(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        client.post(
            "/api/v1/reports/schedules",
            json={"report_definition_id": def_id, "cadence": "daily",
                  "hour": 8, "delivery": "email", "recipients": []},
        )
        resp = client.get("/api/v1/reports/schedules")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_patch_schedule_is_active(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        create_resp = client.post(
            "/api/v1/reports/schedules",
            json={"report_definition_id": def_id, "cadence": "daily",
                  "hour": 8, "delivery": "email", "recipients": []},
        )
        sched_id = create_resp.json()["id"]
        patch_resp = client.patch(
            f"/api/v1/reports/schedules/{sched_id}",
            json={"is_active": False},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_active"] is False

    def test_delete_schedule(self, client: TestClient) -> None:
        def_id = self._create_def(client)
        create_resp = client.post(
            "/api/v1/reports/schedules",
            json={"report_definition_id": def_id, "cadence": "daily",
                  "hour": 8, "delivery": "email", "recipients": []},
        )
        sched_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/v1/reports/schedules/{sched_id}")
        assert del_resp.status_code == 204

        get_resp = client.get(f"/api/v1/reports/schedules/{sched_id}")
        assert get_resp.status_code == 404


# ── due_schedules logic tests ─────────────────────────────────────────────────


class TestDueSchedules:
    """Unit-test the scheduling logic directly via the service function."""

    def _make_sched(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        defn_id: uuid.UUID,
        cadence: str,
        hour: int = 8,
        weekday: int | None = None,
        last_sent_at: str | None = None,
        is_active: bool = True,
    ) -> ReportSchedule:
        s = ReportSchedule(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            report_definition_id=defn_id,
            cadence=cadence,
            weekday=weekday,
            hour=hour,
            delivery="email",
            recipients=[],
            is_active=is_active,
            last_sent_at=last_sent_at,
        )
        db.add(s)
        db.flush()
        return s

    def _make_defn(self, db: Session, tenant_id: uuid.UUID) -> ReportDefinition:
        d = ReportDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name="Sched Test Defn",
            config={},
        )
        db.add(d)
        db.flush()
        return d

    def test_daily_due_when_hour_reached(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        self._make_sched(db, tenant.id, defn.id, "daily", hour=9)
        db.commit()

        # "now" is 09:30 UTC — should be due
        now = datetime(2024, 6, 15, 9, 30, tzinfo=timezone.utc)
        result = due_schedules(db, now)
        assert len(result) == 1

    def test_daily_not_due_before_hour(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        self._make_sched(db, tenant.id, defn.id, "daily", hour=10)
        db.commit()

        now = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        result = due_schedules(db, now)
        assert result == []

    def test_daily_not_due_if_already_sent_today(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        today_str = "2024-06-15T08:00:00+00:00"
        self._make_sched(db, tenant.id, defn.id, "daily", hour=8, last_sent_at=today_str)
        db.commit()

        now = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        result = due_schedules(db, now)
        assert result == []

    def test_weekly_due_on_correct_weekday(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        # weekday=0 = Monday; 2024-06-17 is a Monday
        self._make_sched(db, tenant.id, defn.id, "weekly", hour=8, weekday=0)
        db.commit()

        now = datetime(2024, 6, 17, 9, 0, tzinfo=timezone.utc)  # Monday
        result = due_schedules(db, now)
        assert len(result) == 1

    def test_weekly_not_due_on_wrong_weekday(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        # weekday=0 = Monday; 2024-06-18 is a Tuesday
        self._make_sched(db, tenant.id, defn.id, "weekly", hour=8, weekday=0)
        db.commit()

        now = datetime(2024, 6, 18, 9, 0, tzinfo=timezone.utc)  # Tuesday
        result = due_schedules(db, now)
        assert result == []

    def test_monthly_due_on_first(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        self._make_sched(db, tenant.id, defn.id, "monthly", hour=7)
        db.commit()

        now = datetime(2024, 7, 1, 8, 0, tzinfo=timezone.utc)  # 1st of month
        result = due_schedules(db, now)
        assert len(result) == 1

    def test_monthly_not_due_on_other_days(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        self._make_sched(db, tenant.id, defn.id, "monthly", hour=7)
        db.commit()

        now = datetime(2024, 7, 15, 8, 0, tzinfo=timezone.utc)  # 15th
        result = due_schedules(db, now)
        assert result == []

    def test_inactive_schedule_never_due(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        self._make_sched(db, tenant.id, defn.id, "daily", hour=1, is_active=False)
        db.commit()

        now = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        result = due_schedules(db, now)
        assert result == []

    def test_mark_sent_updates_last_sent_at(self, client: TestClient) -> None:
        db = client._db_session
        tenant = client._tenant
        defn = self._make_defn(db, tenant.id)
        sched = self._make_sched(db, tenant.id, defn.id, "daily", hour=8)
        db.commit()

        assert sched.last_sent_at is None
        mark_sent(db, sched)
        assert sched.last_sent_at is not None
        # Should be a valid ISO-8601 string
        dt = datetime.fromisoformat(sched.last_sent_at.replace("Z", "+00:00"))
        assert dt.year >= 2024
