"""Tests for CSV export endpoints.

Endpoints under test
--------------------
GET /api/v1/dashboard/export?date_from=&date_to=
GET /api/v1/ads/campaigns/export?date_from=&date_to=[&channel=][&status=]
GET /api/v1/creatives/export?date_from=&date_to=

Strategy
--------
* Uses FastAPI TestClient with an in-memory SQLite DB (same pattern as
  test_dashboard_api.py).
* A single ``export_client`` fixture seeds enough data to exercise each export
  endpoint: 2 campaigns across 2 channels, each with one ad row.
* Each test verifies:
    - HTTP 200 response
    - Content-Type contains text/csv
    - Content-Disposition header has the expected filename pattern
    - The first line after the BOM is the Turkish header row
    - At least one data row is present
    - Tenant isolation: a second tenant's data is never exported via Tenant A's session

Seed data (Tenant A)
--------------------
  Channel: google_ads / "Google Campaign":
    ad "Google Ad": 3 days * impressions=100, clicks=10, spend=50, conv=2, cv=200
    Totals: impressions=300, clicks=30, spend=150, conv=6, cv=600 → ROAS=4

  Channel: meta_ads / "Meta Campaign":
    ad "Meta Ad": 3 days * impressions=200, clicks=5, spend=30, conv=1, cv=90
    Totals: impressions=600, clicks=15, spend=90, conv=3, cv=270 → ROAS=3

  Grand totals:
    impressions=900, clicks=45, spend=240, conv=9, cv=870

Tenant B:
  Channel: google_ads / "Tenant B Campaign":
    1 day * spend=99999
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone, timedelta
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


# ── In-memory SQLite engine ───────────────────────────────────────────────────

_SQLITE_URL = "sqlite://"

_EXPORT_DATE_FROM = date(2024, 5, 1)
_EXPORT_DATE_TO = date(2024, 5, 3)  # 3 inclusive days


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


# ── Data helpers ─────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str) -> Tenant:
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


def _make_user(db: Session, email: str) -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test1234"),
        full_name="Export Test User",
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


def _make_connected_account(db: Session, tenant: Tenant, platform: Platform) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=str(uuid.uuid4()),
        display_name=f"{platform.value} export test",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, ext_id: str, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=ext_id,
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign, name: str) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=str(uuid.uuid4()),
        name=name,
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet, name: str) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=str(uuid.uuid4()),
        name=name,
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


# ── Main export fixture ───────────────────────────────────────────────────────


@pytest.fixture()
def export_client(db_session: Session):
    """TestClient with two channels / two campaigns / two ads seeded for Tenant A,
    plus a Tenant B row that must never appear in exports.
    """
    # Tenant A
    tenant_a = _make_tenant(db_session, "Export Tenant A")
    user_a = _make_user(db_session, "export_a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)

    acct_g = _make_connected_account(db_session, tenant_a, Platform.google_ads)
    acct_m = _make_connected_account(db_session, tenant_a, Platform.meta_ads)

    ch_google = _make_channel(db_session, "google_ads")
    ch_meta = _make_channel(db_session, "meta_ads")

    camp_g = _make_campaign(db_session, tenant_a, ch_google, "G-001", "Google Campaign")
    adset_g = _make_adset(db_session, tenant_a, camp_g, "Google AdSet")
    ad_g = _make_ad(db_session, tenant_a, adset_g, "Google Ad")

    camp_m = _make_campaign(db_session, tenant_a, ch_meta, "M-001", "Meta Campaign")
    adset_m = _make_adset(db_session, tenant_a, camp_m, "Meta AdSet")
    ad_m = _make_ad(db_session, tenant_a, adset_m, "Meta Ad")

    # Insert 3 days of facts per channel
    for i in range(3):
        d = _EXPORT_DATE_FROM + timedelta(days=i)
        _insert_fact(
            db_session, tenant_a, acct_g, ch_google, camp_g, adset_g, ad_g, d,
            impressions=100, clicks=10, spend="50.00", conversions="2", cv="200.00",
        )
        _insert_fact(
            db_session, tenant_a, acct_m, ch_meta, camp_m, adset_m, ad_m, d,
            impressions=200, clicks=5, spend="30.00", conversions="1", cv="90.00",
        )

    # Tenant B
    tenant_b = _make_tenant(db_session, "Export Tenant B")
    user_b = _make_user(db_session, "export_b@ayaz.app")
    _make_membership(db_session, user_b, tenant_b)
    acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads)
    ch_b = _make_channel(db_session, "google_ads_b")
    camp_b = _make_campaign(db_session, tenant_b, ch_b, "B-001", "Tenant B Campaign")
    adset_b = _make_adset(db_session, tenant_b, camp_b, "B AdSet")
    ad_b = _make_ad(db_session, tenant_b, adset_b, "B Ad")
    _insert_fact(
        db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b,
        _EXPORT_DATE_FROM,
        impressions=99999, clicks=99999, spend="99999.00", conversions="99999", cv="99999.00",
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


def _parse_csv(content: str) -> list[list[str]]:
    """Parse CSV content (stripping the UTF-8 BOM if present) into rows."""
    stripped = content.lstrip("﻿")
    reader = csv.reader(io.StringIO(stripped))
    return list(reader)


# ── Dashboard export tests ────────────────────────────────────────────────────


class TestDashboardExport:
    _URL = "/api/v1/dashboard/export"

    def test_returns_200(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.status_code == 200

    def test_content_type_is_csv(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_filename(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "ayaz-dashboard-2024-05-01_2024-05-03.csv" in cd

    def test_bom_present(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.text.startswith("﻿"), "UTF-8 BOM must be the first character"

    def test_header_row_is_turkish(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        assert len(rows) >= 1
        headers = rows[0]
        assert "Kanal" in headers
        assert "Harcama" in headers
        assert "Gösterim" in headers
        assert "Tıklama" in headers
        assert "Dönüşüm" in headers
        assert "Dönüşüm Değeri" in headers
        assert "ROAS" in headers
        assert "CPC" in headers
        assert "CTR" in headers

    def test_totals_row_present(self, export_client: TestClient) -> None:
        """First data row must be the totals row (labelled 'Toplam')."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        # rows[0] = headers, rows[1] = totals
        assert len(rows) >= 2
        assert rows[1][0] == "Toplam"

    def test_channel_rows_present(self, export_client: TestClient) -> None:
        """After totals, one row per channel (google_ads, meta_ads)."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        # rows[0] = headers, rows[1] = totals, rows[2..] = channels
        assert len(rows) >= 4  # header + totals + 2 channels
        channel_names = {r[0] for r in rows[2:]}
        assert "google_ads" in channel_names
        assert "meta_ads" in channel_names

    def test_totals_spend_value(self, export_client: TestClient) -> None:
        """Grand total spend: google=150, meta=90 → 240."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        spend_idx = headers.index("Harcama")
        totals_row = rows[1]
        assert float(totals_row[spend_idx]) == pytest.approx(240.0)

    def test_invalid_date_range_returns_422(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-03", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 422

    def test_missing_date_returns_422(self, export_client: TestClient) -> None:
        resp = export_client.get(self._URL, params={"date_to": "2024-05-03"})
        assert resp.status_code == 422

    def test_tenant_isolation(self, export_client: TestClient) -> None:
        """Tenant B spend=99999 must not appear in the totals."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        spend_idx = headers.index("Harcama")
        totals_spend = float(rows[1][spend_idx])
        assert totals_spend != pytest.approx(99999.0, rel=1e-2)
        assert totals_spend < 1000  # sanity: only Tenant A data


# ── Campaigns export tests ────────────────────────────────────────────────────


class TestCampaignsExport:
    _URL = "/api/v1/ads/campaigns/export"

    def test_returns_200(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.status_code == 200

    def test_content_type_is_csv(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_filename(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "ayaz-campaigns-2024-05-01_2024-05-03.csv" in cd

    def test_bom_present(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.text.startswith("﻿")

    def test_header_row_is_turkish(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        assert "Kampanya Adı" in headers
        assert "Kanal" in headers
        assert "Harcama" in headers
        assert "Gösterim" in headers

    def test_two_campaign_data_rows(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        # rows[0] = headers, rows[1..] = campaigns
        data_rows = rows[1:]
        assert len(data_rows) == 2

    def test_campaign_names_in_export(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        name_idx = headers.index("Kampanya Adı")
        names = {r[name_idx] for r in rows[1:]}
        assert "Google Campaign" in names
        assert "Meta Campaign" in names

    def test_channel_filter(self, export_client: TestClient) -> None:
        """channel=google_ads filter returns only 1 row."""
        resp = export_client.get(
            self._URL,
            params={
                "date_from": "2024-05-01",
                "date_to": "2024-05-03",
                "channel": "google_ads",
            },
        )
        rows = _parse_csv(resp.text)
        assert len(rows) == 2  # header + 1 data row
        headers = rows[0]
        name_idx = headers.index("Kampanya Adı")
        assert rows[1][name_idx] == "Google Campaign"

    def test_status_filter_active(self, export_client: TestClient) -> None:
        """All seeded campaigns have spend>0 so status=active returns both."""
        resp = export_client.get(
            self._URL,
            params={
                "date_from": "2024-05-01",
                "date_to": "2024-05-03",
                "status": "active",
            },
        )
        rows = _parse_csv(resp.text)
        assert len(rows) == 3  # header + 2 active campaigns

    def test_status_filter_paused_returns_empty(self, export_client: TestClient) -> None:
        """No paused campaigns → only header row."""
        resp = export_client.get(
            self._URL,
            params={
                "date_from": "2024-05-01",
                "date_to": "2024-05-03",
                "status": "paused",
            },
        )
        rows = _parse_csv(resp.text)
        assert len(rows) == 1  # header only

    def test_invalid_date_range_returns_422(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-03", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 422

    def test_tenant_isolation(self, export_client: TestClient) -> None:
        """Tenant B campaign must not appear."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        name_idx = headers.index("Kampanya Adı")
        names = {r[name_idx] for r in rows[1:]}
        assert "Tenant B Campaign" not in names

    def test_spend_value_google_campaign(self, export_client: TestClient) -> None:
        """Google Campaign: 3 days * 50 = 150 spend."""
        resp = export_client.get(
            self._URL,
            params={
                "date_from": "2024-05-01",
                "date_to": "2024-05-03",
                "channel": "google_ads",
            },
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        spend_idx = headers.index("Harcama")
        assert float(rows[1][spend_idx]) == pytest.approx(150.0)


# ── Creatives export tests ────────────────────────────────────────────────────


class TestCreativesExport:
    _URL = "/api/v1/creatives/export"

    def test_returns_200(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.status_code == 200

    def test_content_type_is_csv(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_filename(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "ayaz-creatives-2024-05-01_2024-05-03.csv" in cd

    def test_bom_present(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        assert resp.text.startswith("﻿")

    def test_header_row_is_turkish(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        assert "Reklam Adı" in headers
        assert "Kampanya Adı" in headers
        assert "Kanal" in headers
        assert "Harcama" in headers
        assert "ROAS" in headers

    def test_two_ad_data_rows(self, export_client: TestClient) -> None:
        """Two ads seeded (Google Ad, Meta Ad) — both must appear."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        data_rows = rows[1:]
        assert len(data_rows) == 2

    def test_ad_names_in_export(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        name_idx = headers.index("Reklam Adı")
        names = {r[name_idx] for r in rows[1:]}
        assert "Google Ad" in names
        assert "Meta Ad" in names

    def test_google_ad_spend_value(self, export_client: TestClient) -> None:
        """Google Ad: 3 days * 50 = 150 spend."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        name_idx = headers.index("Reklam Adı")
        spend_idx = headers.index("Harcama")
        google_row = next(r for r in rows[1:] if r[name_idx] == "Google Ad")
        assert float(google_row[spend_idx]) == pytest.approx(150.0)

    def test_invalid_date_range_returns_422(self, export_client: TestClient) -> None:
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-03", "date_to": "2024-05-01"},
        )
        assert resp.status_code == 422

    def test_missing_date_returns_422(self, export_client: TestClient) -> None:
        resp = export_client.get(self._URL, params={"date_to": "2024-05-03"})
        assert resp.status_code == 422

    def test_tenant_isolation(self, export_client: TestClient) -> None:
        """Tenant B ad must not appear in creatives export."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        # Tenant B ad name is "B Ad"
        all_text = "\n".join(",".join(r) for r in rows[1:])
        assert "B Ad" not in all_text
        # And there must be no spend=99999 row
        headers = rows[0]
        spend_idx = headers.index("Harcama")
        for row in rows[1:]:
            assert float(row[spend_idx]) < 10000, "Tenant B spend leaked"

    def test_no_sentinel_not_set_rows(self, export_client: TestClient) -> None:
        """The '(not set)' sentinel ad rows must be excluded from the export."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2024-05-01", "date_to": "2024-05-03"},
        )
        rows = _parse_csv(resp.text)
        headers = rows[0]
        name_idx = headers.index("Reklam Adı")
        for row in rows[1:]:
            assert row[name_idx] != "(not set)"

    def test_empty_range_returns_header_only(self, export_client: TestClient) -> None:
        """Date range with no data returns just the header row."""
        resp = export_client.get(
            self._URL,
            params={"date_from": "2030-01-01", "date_to": "2030-01-31"},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 1  # header only, no data rows
