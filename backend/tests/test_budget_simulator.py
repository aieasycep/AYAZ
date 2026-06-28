"""Bütçe Senaryo Simülatörü testleri (M15).

Kapsam
------
1. Saf birim testler (DB yok)
   - get_baseline: DB çıktısı yok → boş döner
   - simulate: ValueError — boş allocations
   - simulate: ValueError — negatif spend

2. Servis testleri (SQLite in-memory DB)
   - get_baseline: cpc/cpm/cvr/roas/aov/cpa verimlilik matematiği
   - get_baseline: sıfıra bölme koruması (0 click/impression/spend)
   - get_baseline: spend_share_pct toplamı ~100
   - get_baseline: lookback_days penceresi doğru filtreler
   - simulate: bütçeyi 2x yapmak → tıklamaları ~2x yapar (doğrusal)
   - simulate: bütçeyi 2x yapmak → kanal ROAS değişmez (doğrusal)
   - simulate: deltas doğru işaret/büyüklük
   - simulate: geçmişi olmayan kanal → sıfır projeksiyon + varsayım notu
   - simulate: baseline_totals mevcut pencerenin gerçek toplamlarını içerir

3. HTTP uç nokta testleri
   - GET /budget-simulator/baseline → 200, geçerli yapı
   - GET /budget-simulator/baseline?lookback_days=7 → 200 (minimum)
   - GET /budget-simulator/baseline?lookback_days=90 → 200 (maksimum)
   - POST /budget-simulator/simulate → 200, geçerli yapı
   - POST /budget-simulator/simulate negatif spend → 422
   - POST /budget-simulator/simulate boş allocations → 422
   - Kimlik doğrulama yok → 401/403
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

# Tüm modelleri kaydet — Base.metadata.create_all çalışsın diye
import ayaz.models.oltp          # noqa: F401
import ayaz.models.analytics     # noqa: F401
import ayaz.models.feeds         # noqa: F401
import ayaz.models.insights      # noqa: F401
import ayaz.models.reports       # noqa: F401
import ayaz.models.automation    # noqa: F401
import ayaz.models.tracking      # noqa: F401
import ayaz.models.goals         # noqa: F401
import ayaz.models.billing       # noqa: F401
import ayaz.models.briefing      # noqa: F401
import ayaz.models.budget        # noqa: F401
import ayaz.models.content       # noqa: F401
import ayaz.models.notifications # noqa: F401
import ayaz.models.social_inbox  # noqa: F401
import ayaz.models.copilot       # noqa: F401
import ayaz.models.auth          # noqa: F401
import ayaz.models.recommendations  # noqa: F401
import ayaz.models.ad_studio     # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.analytics import (
    DimAdSet, DimAd, DimChannel, DimCampaign, DimDate, FactDailyMetrics,
)
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import budget_simulator as simulator_module
from ayaz.services.auth import hash_password
from ayaz.services.budget_simulator import get_baseline, simulate

# ── Minimal test uygulaması ───────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Budget Simulator Test App")
_test_app.include_router(simulator_module.router, prefix="/api/v1")


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


# ── Kiracı / üyelik yardımcıları ──────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Sim Test Kiracısı") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name=name,
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_user_and_membership(
    db: Session, tenant: Tenant
) -> tuple[User, Membership]:
    u = User(
        id=uuid.uuid4(),
        email=f"sim_test_{uuid.uuid4().hex[:8]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Sim Test Kullanıcısı",
    )
    db.add(u)
    db.flush()
    m = Membership(
        id=uuid.uuid4(),
        user_id=u.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(m)
    db.commit()
    return u, m


# ── Warehouse seed yardımcısı ─────────────────────────────────────────────────


def _seed_warehouse(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> tuple[DimChannel, DimChannel]:
    """İki kanal ve iki kampanya ile fact satırları oluşturur.

    Google Ads:  spend=10_000, clicks=500, impressions=100_000,
                 conversions=50, conversion_value=30_000
      → cpc=20, cpm=100, cvr=0.10, roas=3.0, aov=600, cpa=200

    Meta Ads:    spend=5_000, clicks=200, impressions=50_000,
                 conversions=10, conversion_value=8_000
      → cpc=25, cpm=100, cvr=0.05, roas=1.6, aov=800, cpa=500
    """
    from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus

    today = as_of or date.today()

    ch_google = DimChannel(id=uuid.uuid4(), key="google_ads", label="Google Ads")
    ch_meta = DimChannel(id=uuid.uuid4(), key="meta_ads", label="Meta Ads")
    db.add_all([ch_google, ch_meta])
    db.flush()

    acc = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        platform=Platform.google_ads,
        external_account_id="acc-sim-001",
        display_name="Sim Test Hesabı",
        vault_secret_ref="test/sim/secret",
        sync_status=SyncStatus.idle,
    )
    db.add(acc)
    db.flush()

    camp_g = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=ch_google.id,
        external_id="g-sim-1", name="Google Sim Kampanya",
    )
    camp_m = DimCampaign(
        id=uuid.uuid4(), tenant_id=tenant_id, channel_id=ch_meta.id,
        external_id="m-sim-1", name="Meta Sim Kampanya",
    )
    db.add_all([camp_g, camp_m])
    db.flush()

    adset_g = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=camp_g.id,
        external_id="as-g-sim", name="AdSet G Sim",
    )
    adset_m = DimAdSet(
        id=uuid.uuid4(), tenant_id=tenant_id, campaign_id=camp_m.id,
        external_id="as-m-sim", name="AdSet M Sim",
    )
    ad_g = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_g.id,
        external_id="ad-g-sim", name="Ad G Sim",
    )
    ad_m = DimAd(
        id=uuid.uuid4(), tenant_id=tenant_id, ad_set_id=adset_m.id,
        external_id="ad-m-sim", name="Ad M Sim",
    )
    db.add_all([adset_g, adset_m, ad_g, ad_m])
    db.flush()

    # Tarih boyutu
    fact_date = today - timedelta(days=5)
    existing = db.get(DimDate, fact_date)
    if existing is None:
        db.add(DimDate(
            date_key=fact_date,
            year=fact_date.year,
            quarter=(fact_date.month - 1) // 3 + 1,
            month=fact_date.month,
            week=fact_date.isocalendar()[1],
            day_of_week=fact_date.weekday(),
            is_weekend=fact_date.weekday() >= 5,
        ))
    db.flush()

    now = datetime.now(timezone.utc)

    # Google Ads fact satırı
    db.add(FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connected_account_id=acc.id,
        channel_id=ch_google.id,
        campaign_id=camp_g.id,
        adset_id=adset_g.id,
        ad_id=ad_g.id,
        date_key=fact_date,
        impressions=100_000,
        clicks=500,
        cost_raw=Decimal("10000.00"),
        cost_ccy="TRY",
        cost_base_ccy=Decimal("10000.00"),
        conversions=Decimal("50.00"),
        conversion_value_raw=Decimal("30000.00"),
        conversion_value_ccy="TRY",
        conv_value_base_ccy=Decimal("30000.00"),
        ingested_at=now,
    ))

    # Meta Ads fact satırı
    db.add(FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connected_account_id=acc.id,
        channel_id=ch_meta.id,
        campaign_id=camp_m.id,
        adset_id=adset_m.id,
        ad_id=ad_m.id,
        date_key=fact_date,
        impressions=50_000,
        clicks=200,
        cost_raw=Decimal("5000.00"),
        cost_ccy="TRY",
        cost_base_ccy=Decimal("5000.00"),
        conversions=Decimal("10.00"),
        conversion_value_raw=Decimal("8000.00"),
        conversion_value_ccy="TRY",
        conv_value_base_ccy=Decimal("8000.00"),
        ingested_at=now,
    ))

    db.commit()
    return ch_google, ch_meta


# ── Kimlik doğrulamalı istemci fixture'ı ─────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """DB + üyelik bağımlılıkları geçersiz kılınmış TestClient."""
    tenant = _make_tenant(db_session)
    _seed_warehouse(db_session, tenant.id)
    _user, membership = _make_user_and_membership(db_session, tenant)

    def _override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    """Kimlik doğrulama geçersiz kılınmamış TestClient — 401/403 testleri için."""
    def _override_db():
        yield db_session

    _test_app.dependency_overrides[get_db] = _override_db
    # get_current_membership geçersiz kılınmadı → gerçek impl → 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Saf birim testler (DB yok)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulateValidation:
    """simulate() giriş doğrulama — DB gerekmez."""

    def test_empty_allocations_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError, match="boş olamaz"):
            simulate(db_session, tenant.id, {})

    def test_negative_spend_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        with pytest.raises(ValueError, match="[Nn]egatif"):
            simulate(db_session, tenant.id, {"google_ads": -100.0})

    def test_zero_spend_is_allowed(self, db_session: Session) -> None:
        """Sıfır harcama geçerlidir — negatif değil."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(db_session, tenant.id, {"google_ads": 0.0})
        assert result is not None
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        assert ch["spend"] == 0.0
        assert ch["clicks"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Servis testleri (SQLite in-memory DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetBaseline:
    """get_baseline() matematik ve yapı testleri."""

    def test_empty_db_returns_empty_channels(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = get_baseline(db_session, tenant.id)
        assert result["channels"] == []
        assert result["total_spend"] == 0.0

    def test_returns_required_top_level_keys(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        for key in ("lookback_days", "period", "total_spend", "channels", "totals"):
            assert key in result, f"Eksik anahtar: {key}"

    def test_period_dates_are_correct(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        ref = date(2026, 6, 28)
        result = get_baseline(db_session, tenant.id, lookback_days=30, as_of=ref)
        assert result["period"]["date_to"] == "2026-06-28"
        assert result["period"]["date_from"] == "2026-05-29"

    def test_cpc_math(self, db_session: Session) -> None:
        """cpc = spend / clicks."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # spend=10_000, clicks=500 → cpc=20.0
        assert abs(ch["cpc"] - 20.0) < 0.01

    def test_cpm_math(self, db_session: Session) -> None:
        """cpm = spend / impressions * 1000."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # spend=10_000, impressions=100_000 → cpm=100.0
        assert abs(ch["cpm"] - 100.0) < 0.01

    def test_cvr_math(self, db_session: Session) -> None:
        """cvr = conversions / clicks."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # conversions=50, clicks=500 → cvr=0.10
        assert abs(ch["cvr"] - 0.10) < 0.001

    def test_roas_math(self, db_session: Session) -> None:
        """roas = conversion_value / spend."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # conv_value=30_000, spend=10_000 → roas=3.0
        assert abs(ch["roas"] - 3.0) < 0.001

    def test_aov_math(self, db_session: Session) -> None:
        """aov = conversion_value / conversions."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # conv_value=30_000, conversions=50 → aov=600.0
        assert abs(ch["aov"] - 600.0) < 0.01

    def test_cpa_math(self, db_session: Session) -> None:
        """cpa = spend / conversions."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # spend=10_000, conversions=50 → cpa=200.0
        assert abs(ch["cpa"] - 200.0) < 0.01

    def test_spend_share_pct_sums_to_100(self, db_session: Session) -> None:
        """spend_share_pct toplamı ~100 olmalı."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        total_share = sum(c["spend_share_pct"] for c in result["channels"])
        assert abs(total_share - 100.0) < 0.1

    def test_spend_share_pct_correct_values(self, db_session: Session) -> None:
        """Google 10_000 / 15_000 = ~66.67%, Meta 5_000 / 15_000 = ~33.33%."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        g = next(c for c in result["channels"] if c["key"] == "google_ads")
        m = next(c for c in result["channels"] if c["key"] == "meta_ads")
        assert abs(g["spend_share_pct"] - 66.67) < 0.1
        assert abs(m["spend_share_pct"] - 33.33) < 0.1

    def test_divide_by_zero_guard_zero_clicks(self, db_session: Session) -> None:
        """0 tıklama → cpc=0, cvr=0 (çökme yok)."""
        from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus

        tenant = _make_tenant(db_session)
        ch = DimChannel(id=uuid.uuid4(), key="zero_clicks", label="Zero Clicks")
        db_session.add(ch)
        db_session.flush()

        acc = ConnectedAccount(
            id=uuid.uuid4(), tenant_id=tenant.id,
            platform=Platform.google_ads,
            external_account_id="acc-zero",
            display_name="Zero Acc",
            vault_secret_ref="test/zero/secret",
            sync_status=SyncStatus.idle,
        )
        db_session.add(acc)
        db_session.flush()

        camp = DimCampaign(
            id=uuid.uuid4(), tenant_id=tenant.id, channel_id=ch.id,
            external_id="zero-camp", name="Zero Camp",
        )
        db_session.add(camp)
        db_session.flush()

        adset = DimAdSet(
            id=uuid.uuid4(), tenant_id=tenant.id, campaign_id=camp.id,
            external_id="zero-adset", name="Zero AdSet",
        )
        ad = DimAd(
            id=uuid.uuid4(), tenant_id=tenant.id, ad_set_id=adset.id,
            external_id="zero-ad", name="Zero Ad",
        )
        db_session.add_all([adset, ad])
        db_session.flush()

        today = date.today()
        fact_date = today - timedelta(days=1)
        existing = db_session.get(DimDate, fact_date)
        if existing is None:
            db_session.add(DimDate(
                date_key=fact_date, year=fact_date.year,
                quarter=(fact_date.month - 1) // 3 + 1,
                month=fact_date.month, week=fact_date.isocalendar()[1],
                day_of_week=fact_date.weekday(), is_weekend=fact_date.weekday() >= 5,
            ))
        db_session.flush()

        db_session.add(FactDailyMetrics(
            id=uuid.uuid4(), tenant_id=tenant.id,
            connected_account_id=acc.id,
            channel_id=ch.id, campaign_id=camp.id,
            adset_id=adset.id, ad_id=ad.id,
            date_key=fact_date,
            impressions=0, clicks=0,
            cost_raw=Decimal("1000.00"), cost_ccy="TRY",
            cost_base_ccy=Decimal("1000.00"),
            conversions=Decimal("0.00"),
            conversion_value_raw=Decimal("0.00"),
            conversion_value_ccy="TRY",
            conv_value_base_ccy=Decimal("0.00"),
            ingested_at=datetime.now(timezone.utc),
        ))
        db_session.commit()

        result = get_baseline(db_session, tenant.id)
        ch_row = next(c for c in result["channels"] if c["key"] == "zero_clicks")
        assert ch_row["cpc"] == 0.0
        assert ch_row["cvr"] == 0.0
        assert ch_row["cpm"] == 0.0
        assert ch_row["cpa"] == 0.0

    def test_lookback_days_filters_old_data(self, db_session: Session) -> None:
        """lookback_days=3 → 10 gün öncesindeki veri dışarıda kalır."""
        tenant = _make_tenant(db_session)
        # 5 gün önce veri ile seed et
        _seed_warehouse(db_session, tenant.id)

        # lookback=3 → 5 gün önceki veri pencere dışında
        result = get_baseline(db_session, tenant.id, lookback_days=3)
        assert result["channels"] == []
        assert result["total_spend"] == 0.0

    def test_lookback_days_includes_recent_data(self, db_session: Session) -> None:
        """lookback_days=30 → 5 gün önceki veri pencere içinde."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = get_baseline(db_session, tenant.id, lookback_days=30)
        assert len(result["channels"]) == 2

    def test_totals_structure(self, db_session: Session) -> None:
        """totals anahtarları eksiksiz."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        expected = {"spend", "impressions", "clicks", "conversions",
                    "conversion_value", "roas", "cpc", "cvr", "cpa"}
        assert expected <= set(result["totals"].keys())

    def test_totals_spend_matches_sum(self, db_session: Session) -> None:
        """totals.spend = sum(channel.spend)."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        channel_sum = sum(c["spend"] for c in result["channels"])
        assert abs(result["totals"]["spend"] - channel_sum) < 0.01

    def test_channel_fields_complete(self, db_session: Session) -> None:
        """Her kanal satırı gerekli tüm alanları içeriyor."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = get_baseline(db_session, tenant.id)
        required = {
            "key", "label", "spend", "impressions", "clicks",
            "conversions", "conversion_value",
            "cpc", "cpm", "cvr", "roas", "aov", "cpa", "spend_share_pct",
        }
        for ch in result["channels"]:
            assert required <= set(ch.keys()), f"Eksik alan: {required - set(ch.keys())}"


class TestSimulate:
    """simulate() matematik ve yapı testleri."""

    def test_returns_required_top_level_keys(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        for key in (
            "lookback_days", "total_spend", "channels",
            "projected_totals", "baseline_totals", "deltas", "assumptions",
        ):
            assert key in result, f"Eksik anahtar: {key}"

    def test_total_spend_is_sum_of_allocations(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(
            db_session, tenant.id,
            {"google_ads": 12_000.0, "meta_ads": 3_000.0}
        )
        assert abs(result["total_spend"] - 15_000.0) < 0.01

    def test_doubling_spend_doubles_clicks(self, db_session: Session) -> None:
        """Doğrusal projeksiyon: bütçe 2x → tıklama ~2x."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        # Baz: google_ads spend=10_000 (seed'den aynı)
        result_1x = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        result_2x = simulate(db_session, tenant.id, {"google_ads": 20_000.0})

        ch_1x = next(c for c in result_1x["channels"] if c["key"] == "google_ads")
        ch_2x = next(c for c in result_2x["channels"] if c["key"] == "google_ads")

        assert ch_1x["clicks"] > 0
        ratio = ch_2x["clicks"] / ch_1x["clicks"]
        assert abs(ratio - 2.0) < 0.01, f"Beklenen ~2.0, alınan {ratio}"

    def test_doubling_spend_doubles_conversions(self, db_session: Session) -> None:
        """Doğrusal projeksiyon: bütçe 2x → dönüşüm ~2x."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result_1x = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        result_2x = simulate(db_session, tenant.id, {"google_ads": 20_000.0})

        ch_1x = next(c for c in result_1x["channels"] if c["key"] == "google_ads")
        ch_2x = next(c for c in result_2x["channels"] if c["key"] == "google_ads")

        assert ch_1x["conversions"] > 0
        ratio = ch_2x["conversions"] / ch_1x["conversions"]
        assert abs(ratio - 2.0) < 0.01

    def test_channel_roas_unchanged_when_spend_doubles(self, db_session: Session) -> None:
        """Doğrusal projeksiyon: bütçe değişse de kanal ROAS sabit kalır."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result_1x = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        result_2x = simulate(db_session, tenant.id, {"google_ads": 20_000.0})

        ch_1x = next(c for c in result_1x["channels"] if c["key"] == "google_ads")
        ch_2x = next(c for c in result_2x["channels"] if c["key"] == "google_ads")

        # Kanal ROAS aynı kalmalı (doğrusal projeksiyon)
        assert abs(ch_1x["roas"] - ch_2x["roas"]) < 0.001

    def test_projection_click_math_exact(self, db_session: Session) -> None:
        """clicks = planned_spend / cpc. Google: spend=10_000, cpc=20 → 500."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # cpc=20 → clicks = 10_000 / 20 = 500
        assert abs(ch["clicks"] - 500.0) < 0.01

    def test_projection_impression_math_exact(self, db_session: Session) -> None:
        """impressions = planned_spend / cpm * 1000. Google: cpm=100 → 100_000."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        # cpm=100 → impressions = 10_000 / 100 * 1000 = 100_000
        assert abs(ch["impressions"] - 100_000.0) < 1.0

    def test_projection_conversion_math_exact(self, db_session: Session) -> None:
        """conversions = clicks * cvr. Google: 500 * 0.10 = 50."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        assert abs(ch["conversions"] - 50.0) < 0.01

    def test_positive_delta_when_spend_increases(self, db_session: Session) -> None:
        """Bütçe artışı → conversions_pct ve clicks_pct pozitif."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        # Baz toplam spend=15_000. Biz 20_000 veriyoruz → artış
        result = simulate(
            db_session, tenant.id,
            {"google_ads": 15_000.0, "meta_ads": 5_000.0}
        )
        assert result["deltas"]["clicks_pct"] > 0
        assert result["deltas"]["conversions_pct"] > 0

    def test_negative_delta_when_spend_decreases(self, db_session: Session) -> None:
        """Bütçe azalışı → conversions_pct negatif."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        # Baz toplam spend=15_000. Biz 3_000 veriyoruz → azalış
        result = simulate(
            db_session, tenant.id,
            {"google_ads": 2_000.0, "meta_ads": 1_000.0}
        )
        assert result["deltas"]["conversions_pct"] < 0

    def test_zero_history_channel_gets_zero_projection(
        self, db_session: Session
    ) -> None:
        """Geçmişi olmayan kanal → sıfır projeksiyon."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(
            db_session, tenant.id,
            {"google_ads": 5_000.0, "tiktok_ads": 2_000.0}
        )
        tiktok = next(c for c in result["channels"] if c["key"] == "tiktok_ads")
        assert tiktok["clicks"] == 0.0
        assert tiktok["conversions"] == 0.0
        assert tiktok["roas"] == 0.0

    def test_zero_history_channel_adds_assumption_note(
        self, db_session: Session
    ) -> None:
        """Geçmişi olmayan kanal → varsayım listesinde not var."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(
            db_session, tenant.id,
            {"google_ads": 5_000.0, "tiktok_ads": 2_000.0}
        )
        assert any("tiktok_ads" in a for a in result["assumptions"])

    def test_baseline_totals_reflect_actual_spend(self, db_session: Session) -> None:
        """baseline_totals.spend = baz dönemdeki gerçek toplam harcama."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(
            db_session, tenant.id,
            {"google_ads": 10_000.0, "meta_ads": 5_000.0}
        )
        # Seed: google=10_000 + meta=5_000 = 15_000
        assert abs(result["baseline_totals"]["spend"] - 15_000.0) < 0.01

    def test_spend_delta_and_spend_delta_pct(self, db_session: Session) -> None:
        """spend_delta = planned - baseline; spend_delta_pct doğru işaret."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        # Google baseline=10_000, planlanan=15_000 → delta=+5_000 → +50%
        result = simulate(db_session, tenant.id, {"google_ads": 15_000.0})
        ch = next(c for c in result["channels"] if c["key"] == "google_ads")
        assert abs(ch["spend_delta"] - 5_000.0) < 0.01
        assert abs(ch["spend_delta_pct"] - 50.0) < 0.1

    def test_channel_not_in_allocations_is_dropped(self, db_session: Session) -> None:
        """Tahsislerde yer almayan kanal sonuca dahil edilmez."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)

        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        keys = {c["key"] for c in result["channels"]}
        assert "meta_ads" not in keys

    def test_channel_fields_complete(self, db_session: Session) -> None:
        """Her kanal satırı gerekli alanları içeriyor."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(
            db_session, tenant.id,
            {"google_ads": 10_000.0, "meta_ads": 5_000.0}
        )
        required = {
            "key", "label", "spend", "impressions", "clicks",
            "conversions", "conversion_value", "roas", "cpa",
            "baseline_spend", "spend_delta", "spend_delta_pct",
        }
        for ch in result["channels"]:
            assert required <= set(ch.keys())

    def test_projected_totals_fields(self, db_session: Session) -> None:
        """projected_totals gerekli alanları içeriyor."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        required = {
            "spend", "impressions", "clicks", "conversions",
            "conversion_value", "roas", "cpa", "cvr",
        }
        assert required <= set(result["projected_totals"].keys())

    def test_deltas_fields_present(self, db_session: Session) -> None:
        """deltas gerekli yüzde alanlarını içeriyor."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        required = {
            "impressions_pct", "clicks_pct", "conversions_pct",
            "conversion_value_pct", "roas_pct",
        }
        assert required <= set(result["deltas"].keys())

    def test_assumptions_list_not_empty(self, db_session: Session) -> None:
        """assumptions listesi en az bir Türkçe madde içeriyor."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        result = simulate(db_session, tenant.id, {"google_ads": 10_000.0})
        assert len(result["assumptions"]) >= 1

    def test_multi_channel_total_spend(self, db_session: Session) -> None:
        """Çok kanallı: total_spend = tahsis toplamı."""
        tenant = _make_tenant(db_session)
        _seed_warehouse(db_session, tenant.id)
        allocs = {"google_ads": 8_000.0, "meta_ads": 4_000.0}
        result = simulate(db_session, tenant.id, allocs)
        assert abs(result["total_spend"] - 12_000.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HTTP uç nokta testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaselineEndpoint:
    def test_get_baseline_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/budget-simulator/baseline")
        assert resp.status_code == 200

    def test_get_baseline_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/budget-simulator/baseline")
        data = resp.json()
        for key in ("lookback_days", "period", "total_spend", "channels", "totals"):
            assert key in data, f"Eksik anahtar: {key}"

    def test_get_baseline_channels_have_efficiency_fields(
        self, client: TestClient
    ) -> None:
        resp = client.get("/api/v1/budget-simulator/baseline")
        data = resp.json()
        for ch in data["channels"]:
            for field in ("cpc", "cpm", "cvr", "roas", "aov", "cpa",
                          "spend_share_pct"):
                assert field in ch, f"Kanalda eksik alan: {field}"

    def test_get_baseline_lookback_minimum(self, client: TestClient) -> None:
        """lookback_days=7 (minimum) → 200."""
        resp = client.get("/api/v1/budget-simulator/baseline?lookback_days=7")
        assert resp.status_code == 200
        assert resp.json()["lookback_days"] == 7

    def test_get_baseline_lookback_maximum(self, client: TestClient) -> None:
        """lookback_days=90 (maksimum) → 200."""
        resp = client.get("/api/v1/budget-simulator/baseline?lookback_days=90")
        assert resp.status_code == 200
        assert resp.json()["lookback_days"] == 90

    def test_get_baseline_lookback_clamped_via_query_ge_le(
        self, client: TestClient
    ) -> None:
        """FastAPI ge/le kısıtı: lookback_days=5 → 422 (ge=7)."""
        resp = client.get("/api/v1/budget-simulator/baseline?lookback_days=5")
        assert resp.status_code == 422

    def test_get_baseline_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/budget-simulator/baseline")
        assert resp.status_code in {401, 403}


class TestSimulateEndpoint:
    def test_post_simulate_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"google_ads": 12_000.0}},
        )
        assert resp.status_code == 200

    def test_post_simulate_response_shape(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={
                "allocations": {"google_ads": 10_000.0, "meta_ads": 5_000.0},
                "lookback_days": 30,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "lookback_days", "total_spend", "channels",
            "projected_totals", "baseline_totals", "deltas", "assumptions",
        ):
            assert key in data, f"Eksik anahtar: {key}"

    def test_post_simulate_negative_spend_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"google_ads": -500.0}},
        )
        assert resp.status_code == 422

    def test_post_simulate_empty_allocations_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {}},
        )
        assert resp.status_code == 422

    def test_post_simulate_missing_allocations_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"lookback_days": 30},
        )
        assert resp.status_code == 422

    def test_post_simulate_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"google_ads": 5_000.0}},
        )
        assert resp.status_code in {401, 403}

    def test_post_simulate_deltas_keys(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"google_ads": 10_000.0}},
        )
        data = resp.json()
        for delta_key in (
            "impressions_pct", "clicks_pct", "conversions_pct",
            "conversion_value_pct", "roas_pct",
        ):
            assert delta_key in data["deltas"]

    def test_post_simulate_lookback_clamped_by_pydantic(
        self, client: TestClient
    ) -> None:
        """Pydantic validator lookback_days=200 → 90'a sıkıştırır."""
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"google_ads": 5_000.0}, "lookback_days": 200},
        )
        # Pydantic clamp validator çalışır → 200 değil 90 olur
        assert resp.status_code == 200
        assert resp.json()["lookback_days"] == 90

    def test_post_simulate_unknown_channel_zero_projection(
        self, client: TestClient
    ) -> None:
        """Geçmişi olmayan kanal → sıfır projeksiyon, yine de 200 döner."""
        resp = client.post(
            "/api/v1/budget-simulator/simulate",
            json={"allocations": {"unknown_channel_xyz": 1_000.0}},
        )
        assert resp.status_code == 200
        data = resp.json()
        ch = next(
            c for c in data["channels"] if c["key"] == "unknown_channel_xyz"
        )
        assert ch["clicks"] == 0.0
        assert ch["conversions"] == 0.0
