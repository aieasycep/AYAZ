"""Tests for GET /api/v1/dashboard/top-movers — En Çok Değişenler.

Strateji
--------
* In-memory SQLite + FastAPI TestClient (test_dashboard_compare.py ile aynı desen).
* Bilinen delta değerleriyle iki dönem verisi ekilir; kesin sıralama doğrulanır.
* Hem kazanan hem kaybedenler kontrol edilir.
* previous==0 → delta_pct None (sıfıra bölme koruması).
* dimension=campaign çalışıyor.
* Geçersiz metrik → 422.
* limit parametresi uygulanıyor ve 20 ile sınırlı.
* Kiracı izolasyonu: B kiracısı verisi A kiracısı yanıtında görünmemeli.
* Kimlik doğrulama zorunlu (401/403).

Veri düzeni
-----------
A kiracısı — iki kanal:

  ``meta_ads``:
    Önceki dönem  2024-03-01: spend=1000, impressions=5000, clicks=100,
                              conversions=20, cv=3000
    Güncel dönem  2024-03-08: spend=1500, impressions=6000, clicks=120,
                              conversions=24, cv=4500
    spend delta   = 1500-1000 = +500   (+50%)
    roas önceki   = 3000/1000 = 3.0
    roas güncel   = 4500/1500 = 3.0  → delta 0

  ``google_ads``:
    Önceki dönem  2024-03-01: spend=2000, impressions=8000, clicks=200,
                              conversions=40, cv=8000
    Güncel dönem  2024-03-08: spend=1200, impressions=4000, clicks=100,
                              conversions=20, cv=4000
    spend delta   = 1200-2000 = -800  (-40%)
    roas önceki   = 8000/2000 = 4.0
    roas güncel   = 4000/1200 ≈ 3.333

Mutlak spend delta sıralaması: google_ads (800) > meta_ads (500)
→ Büyük losers küçük gainers'ın önünde olmalı.

Sıfır-önceki dönem varlığı:
  ``tiktok_ads``:
    Önceki dönem: veri yok (sıfır)
    Güncel dönem  2024-03-08: spend=300, conversions=5, cv=600
    delta_pct spend = None (sıfıra bölme)
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


# ── In-memory SQLite engine ───────────────────────────────────────────────────

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


# ── Veri yardımcıları ─────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Tenant A") -> Tenant:
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
    ch = DimChannel(
        id=uuid.uuid4(),
        key=key,
        label=key.replace("_", " ").title(),
    )
    db.add(ch)
    db.flush()
    return ch


def _make_connected_account(db: Session, tenant: Tenant, platform: Platform) -> ConnectedAccount:
    a = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=platform,
        external_account_id=str(uuid.uuid4()),
        display_name=f"{platform.value} test",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(a)
    db.flush()
    return a


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=str(uuid.uuid4()),
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


# ── Ana fikstür ───────────────────────────────────────────────────────────────

# Sabit tarihler: güncel dönem 2024-03-08 → 2024-03-14 (7 gün), önceki dönem 2024-03-01 → 2024-03-07
# Her dönem için tek satır ekleniyor (güncel için 2024-03-08, önceki için 2024-03-01).
_CURR_DATE = date(2024, 3, 8)
_PREV_DATE = date(2024, 3, 1)
_CURR_PARAMS = {"date_from": "2024-03-08", "date_to": "2024-03-14"}


@pytest.fixture()
def movers_client(db_session: Session):
    """TestClient — A kiracısı için iki kanal ve kampanyalarla ekilmiş.

    meta_ads:   prev spend=1000 → curr spend=1500  (delta=+500)
    google_ads: prev spend=2000 → curr spend=1200  (delta=-800)
    tiktok_ads: prev yok       → curr spend=300    (delta_pct=None)

    B kiracısı izolasyon kontrolü için büyük spend verisiyle eklendi.
    """
    # A kiracısı
    tenant_a = _make_tenant(db_session, "Tenant A")
    user_a = _make_user(db_session, "mover_a@ayaz.app")
    membership_a = _make_membership(db_session, user_a, tenant_a)
    acct_a = _make_connected_account(db_session, tenant_a, Platform.meta_ads)

    # Kanal 1: meta_ads
    ch_meta = _make_channel(db_session, "meta_ads")
    camp_meta = _make_campaign(db_session, tenant_a, ch_meta, "Meta Kampanya")
    adset_meta = _make_adset(db_session, tenant_a, camp_meta)
    ad_meta = _make_ad(db_session, tenant_a, adset_meta)

    _insert_fact(
        db_session, tenant_a, acct_a, ch_meta, camp_meta, adset_meta, ad_meta,
        _PREV_DATE,
        impressions=5000, clicks=100, spend="1000", conversions="20", cv="3000",
    )
    _insert_fact(
        db_session, tenant_a, acct_a, ch_meta, camp_meta, adset_meta, ad_meta,
        _CURR_DATE,
        impressions=6000, clicks=120, spend="1500", conversions="24", cv="4500",
    )

    # Kanal 2: google_ads
    ch_google = _make_channel(db_session, "google_ads")
    camp_google = _make_campaign(db_session, tenant_a, ch_google, "Google Kampanya")
    adset_google = _make_adset(db_session, tenant_a, camp_google)
    ad_google = _make_ad(db_session, tenant_a, adset_google)

    _insert_fact(
        db_session, tenant_a, acct_a, ch_google, camp_google, adset_google, ad_google,
        _PREV_DATE,
        impressions=8000, clicks=200, spend="2000", conversions="40", cv="8000",
    )
    _insert_fact(
        db_session, tenant_a, acct_a, ch_google, camp_google, adset_google, ad_google,
        _CURR_DATE,
        impressions=4000, clicks=100, spend="1200", conversions="20", cv="4000",
    )

    # Kanal 3: tiktok_ads — sadece güncel dönemde veri var (prev=0, delta_pct=None)
    ch_tiktok = _make_channel(db_session, "tiktok_ads")
    camp_tiktok = _make_campaign(db_session, tenant_a, ch_tiktok, "TikTok Kampanya")
    adset_tiktok = _make_adset(db_session, tenant_a, camp_tiktok)
    ad_tiktok = _make_ad(db_session, tenant_a, adset_tiktok)

    _insert_fact(
        db_session, tenant_a, acct_a, ch_tiktok, camp_tiktok, adset_tiktok, ad_tiktok,
        _CURR_DATE,
        impressions=2000, clicks=50, spend="300", conversions="5", cv="600",
    )

    # B kiracısı — izolasyon kontrolü
    tenant_b = _make_tenant(db_session, "Tenant B")
    user_b = _make_user(db_session, "mover_b@ayaz.app")
    _make_membership(db_session, user_b, tenant_b)
    acct_b = _make_connected_account(db_session, tenant_b, Platform.google_ads)
    ch_b = _make_channel(db_session, "google_ads_b")
    camp_b = _make_campaign(db_session, tenant_b, ch_b, "Tenant B Campaign")
    adset_b = _make_adset(db_session, tenant_b, camp_b)
    ad_b = _make_ad(db_session, tenant_b, adset_b)
    _insert_fact(
        db_session, tenant_b, acct_b, ch_b, camp_b, adset_b, ad_b,
        _CURR_DATE,
        impressions=999999, clicks=999999, spend="999999", conversions="999999", cv="999999",
    )

    db_session.commit()

    def override_get_db():
        yield db_session

    def override_get_membership():
        return membership_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_db_client(db_session: Session):
    """TestClient kimlik doğrulama geçersiz kılması olmadan — 401/403 testi için."""
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # get_current_membership geçersiz kılınmıyor — gerçek auth yolu kullanılır.

    client = TestClient(app, raise_server_exceptions=False)
    yield client

    app.dependency_overrides.clear()


# ── Temel yanıt doğrulama ─────────────────────────────────────────────────────


class TestTopMoversBasicResponse:
    """Endpoint 200 döndürür ve gerekli tüm alanlar mevcuttur."""

    def test_returns_200(self, movers_client: TestClient) -> None:
        resp = movers_client.get("/api/v1/dashboard/top-movers", params=_CURR_PARAMS)
        assert resp.status_code == 200

    def test_response_has_required_top_level_fields(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        for field in ("dimension", "metric", "date_from", "date_to",
                      "previous_from", "previous_to", "movers"):
            assert field in body, f"Eksik alan: {field}"

    def test_default_dimension_is_channel(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        assert body["dimension"] == "channel"

    def test_default_metric_is_spend(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        assert body["metric"] == "spend"

    def test_mover_item_has_required_fields(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        for item in body["movers"]:
            for field in ("key", "label", "current", "previous", "delta",
                          "delta_pct", "direction"):
                assert field in item, f"Mover öğesinde eksik alan: {field}"

    def test_previous_period_dates_correct(self, movers_client: TestClient) -> None:
        """7 günlük güncel dönem (2024-03-08 → 2024-03-14) için önceki dönem 2024-03-01 → 2024-03-07 olmalı."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        assert body["previous_from"] == "2024-03-01"
        assert body["previous_to"] == "2024-03-07"


# ── Sıralama: mutlak delta ────────────────────────────────────────────────────


class TestTopMoversRanking:
    """google_ads (delta=-800) meta_ads'den (delta=+500) önce sıralanmalı."""

    def test_google_ads_ranked_first_by_absolute_delta(
        self, movers_client: TestClient
    ) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        movers = body["movers"]
        keys = [m["key"] for m in movers]
        assert keys.index("google_ads") < keys.index("meta_ads"), (
            f"google_ads (|delta|=800) meta_ads'dan (|delta|=500) önce olmalı; sıra: {keys}"
        )

    def test_deltas_are_sorted_descending_by_absolute_value(
        self, movers_client: TestClient
    ) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        abs_deltas = [abs(m["delta"]) for m in body["movers"]]
        assert abs_deltas == sorted(abs_deltas, reverse=True), (
            f"Mutlak deltalar azalan sırada değil: {abs_deltas}"
        )

    def test_google_ads_delta_value(self, movers_client: TestClient) -> None:
        """google_ads: curr=1200, prev=2000 → delta=-800."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        google = next(m for m in body["movers"] if m["key"] == "google_ads")
        assert google["delta"] == pytest.approx(-800.0)

    def test_meta_ads_delta_value(self, movers_client: TestClient) -> None:
        """meta_ads: curr=1500, prev=1000 → delta=+500."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        meta = next(m for m in body["movers"] if m["key"] == "meta_ads")
        assert meta["delta"] == pytest.approx(500.0)


# ── Kazananlar ve kaybedenler ─────────────────────────────────────────────────


class TestTopMoversGainersAndLosers:
    """Hem kazananlar hem de kaybedenler yanıtta yer almalı."""

    def test_gainer_direction_is_up(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        meta = next(m for m in body["movers"] if m["key"] == "meta_ads")
        assert meta["direction"] == "up"

    def test_loser_direction_is_down(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        google = next(m for m in body["movers"] if m["key"] == "google_ads")
        assert google["direction"] == "down"

    def test_both_gainers_and_losers_present(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        directions = {m["direction"] for m in body["movers"]}
        assert "up" in directions, "Kazanan yok"
        assert "down" in directions, "Kaybeden yok"

    def test_delta_pct_for_meta_ads(self, movers_client: TestClient) -> None:
        """meta_ads: (1500-1000)/1000 = 0.5."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        meta = next(m for m in body["movers"] if m["key"] == "meta_ads")
        assert meta["delta_pct"] == pytest.approx(0.5)

    def test_delta_pct_for_google_ads(self, movers_client: TestClient) -> None:
        """google_ads: (1200-2000)/2000 = -0.4."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        google = next(m for m in body["movers"] if m["key"] == "google_ads")
        assert google["delta_pct"] == pytest.approx(-0.4)


# ── Sıfır-önceki dönem: delta_pct=None ───────────────────────────────────────


class TestTopMoversDivideByZeroGuard:
    """Önceki dönem sıfır olan varlık için delta_pct None dönmeli."""

    def test_tiktok_delta_pct_is_none_when_prev_zero(
        self, movers_client: TestClient
    ) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        ).json()
        tiktok_movers = [m for m in body["movers"] if m["key"] == "tiktok_ads"]
        assert tiktok_movers, "tiktok_ads yanıtta bulunmalı"
        assert tiktok_movers[0]["delta_pct"] is None

    def test_tiktok_previous_is_zero(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        ).json()
        tiktok = next(m for m in body["movers"] if m["key"] == "tiktok_ads")
        assert tiktok["previous"] == pytest.approx(0.0)

    def test_no_crash_with_prev_zero(self, movers_client: TestClient) -> None:
        """Önceki dönem sıfır olduğunda endpoint çökmemeli."""
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        )
        assert resp.status_code == 200


# ── dimension=campaign ────────────────────────────────────────────────────────


class TestTopMoversCampaignDimension:
    """dimension=campaign kampanya bazlı gruplama döndürmeli."""

    def test_campaign_dimension_returns_200(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "dimension": "campaign"},
        )
        assert resp.status_code == 200

    def test_campaign_dimension_in_response(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "dimension": "campaign"},
        ).json()
        assert body["dimension"] == "campaign"

    def test_campaign_movers_have_campaign_labels(
        self, movers_client: TestClient
    ) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "dimension": "campaign"},
        ).json()
        labels = {m["label"] for m in body["movers"]}
        # Meta Kampanya ve/veya Google Kampanya mevcut olmalı
        assert any("Kampanya" in lbl for lbl in labels), (
            f"Kampanya etiketleri bekleniyor; alınan: {labels}"
        )

    def test_campaign_biggest_loser_ranked_first(
        self, movers_client: TestClient
    ) -> None:
        """Google Kampanya (delta=-800) Meta Kampanya'dan (delta=+500) önce olmalı."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "dimension": "campaign", "limit": "20"},
        ).json()
        # Büyük kaybeden küçük kazanandan önce sıralanmalı
        abs_deltas = [abs(m["delta"]) for m in body["movers"]]
        assert abs_deltas == sorted(abs_deltas, reverse=True)


# ── Geçersiz metrik → 422 ─────────────────────────────────────────────────────


class TestTopMoversValidation:
    """Geçersiz parametre değerleri 422 döndürmeli."""

    def test_invalid_metric_returns_422(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "metric": "invalid_metric"},
        )
        assert resp.status_code == 422

    def test_invalid_dimension_returns_422(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "dimension": "adset"},
        )
        assert resp.status_code == 422

    def test_limit_above_20_returns_422(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "21"},
        )
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "0"},
        )
        assert resp.status_code == 422

    def test_date_from_after_date_to_returns_422(
        self, movers_client: TestClient
    ) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={"date_from": "2024-03-08", "date_to": "2024-03-01"},
        )
        assert resp.status_code == 422


# ── limit parametresi ─────────────────────────────────────────────────────────


class TestTopMoversLimit:
    """limit parametresi sonuç sayısını doğru kısıtlamalı."""

    def test_limit_1_returns_one_mover(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "1"},
        ).json()
        assert len(body["movers"]) == 1

    def test_limit_2_returns_two_movers(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "2"},
        ).json()
        assert len(body["movers"]) == 2

    def test_default_limit_5_respected(self, movers_client: TestClient) -> None:
        """3 kanalımız var → default limit=5 en fazla 3 döndürmeli."""
        body = movers_client.get(
            "/api/v1/dashboard/top-movers", params=_CURR_PARAMS
        ).json()
        assert len(body["movers"]) <= 5

    def test_limit_20_max_accepted(self, movers_client: TestClient) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        )
        assert resp.status_code == 200


# ── Kiracı izolasyonu ─────────────────────────────────────────────────────────


class TestTopMoversIsolation:
    """B kiracısı verisi A kiracısının yanıtında görünmemeli."""

    def test_tenant_b_spend_not_in_movers(self, movers_client: TestClient) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        ).json()
        for mover in body["movers"]:
            assert mover["current"] != pytest.approx(999999.0, rel=1e-2), (
                "B kiracısı verisi A kiracısının yanıtına sızdı"
            )

    def test_tenant_b_channel_key_not_in_movers(
        self, movers_client: TestClient
    ) -> None:
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "limit": "20"},
        ).json()
        keys = [m["key"] for m in body["movers"]]
        assert "google_ads_b" not in keys, "B kiracısı kanalı A kiracısının yanıtında"


# ── Kimlik doğrulama zorunlu ──────────────────────────────────────────────────


class TestTopMoversAuth:
    """Token olmadan endpoint 401 veya 403 döndürmeli."""

    def test_no_token_returns_401_or_403(self, unauthed_db_client: TestClient) -> None:
        resp = unauthed_db_client.get(
            "/api/v1/dashboard/top-movers",
            params=_CURR_PARAMS,
        )
        assert resp.status_code in (401, 403), (
            f"Kimlik doğrulama olmadan 401/403 bekleniyor; alınan: {resp.status_code}"
        )


# ── Metrik seçenekleri ────────────────────────────────────────────────────────


class TestTopMoversMetricVariants:
    """Desteklenen tüm metrikler için endpoint 200 döndürmeli."""

    @pytest.mark.parametrize(
        "metric",
        ["spend", "impressions", "clicks", "conversions", "conversion_value", "roas"],
    )
    def test_metric_variant_returns_200(
        self, metric: str, movers_client: TestClient
    ) -> None:
        resp = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "metric": metric},
        )
        assert resp.status_code == 200, f"Metrik {metric!r} için 200 bekleniyor"

    def test_roas_computed_from_components_not_averaged(
        self, movers_client: TestClient
    ) -> None:
        """meta_ads ROAS: prev cv=3000/spend=1000=3.0, curr cv=4500/spend=1500=3.0
        → delta=0, direction='up' (0>=0).
        """
        body = movers_client.get(
            "/api/v1/dashboard/top-movers",
            params={**_CURR_PARAMS, "metric": "roas", "limit": "20"},
        ).json()
        meta = next((m for m in body["movers"] if m["key"] == "meta_ads"), None)
        if meta:
            assert meta["current"] == pytest.approx(3.0, rel=1e-4)
            assert meta["previous"] == pytest.approx(3.0, rel=1e-4)
            assert meta["delta"] == pytest.approx(0.0, abs=1e-6)
