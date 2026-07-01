"""Müşteri Yolculuğu / Dönüşüm Hunisi testleri.

Kapsam
------
1. build_funnel — servis düzeyinde testler (veritabanı ile)
   - Aşama sayıları + sıraları
   - conversion_from_prev_pct matematiği (stage.count / prev.count * 100)
   - dropoff_pct = 100 - conversion_from_prev_pct
   - share_of_entry_pct doğruluğu
   - İlk aşama: conversion_from_prev_pct ve dropoff_pct null olmalı
   - overall_conversion_pct = final / entry * 100
   - entry = 0 → overall_conversion_pct = 0.0, çökme yok
   - biggest_dropoff en büyük geçiş düşüşünü bulmalı
   - 5 aşama dışındaki olaylar yoksayılmalı
   - Tarih penceresi filtresi çalışmalı
   - Tarihsiz çağrı → tüm kayıtlar dahil

2. HTTP endpoint
   - GET /funnel/overview → 200
   - date_from > date_to → 422
   - Kimlik doğrulamasız → 401 veya 403
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata.create_all works
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401
import ayaz.models.insights  # noqa: F401
import ayaz.models.reports  # noqa: F401
import ayaz.models.automation  # noqa: F401
import ayaz.models.tracking  # noqa: F401
import ayaz.models.goals  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.briefing  # noqa: F401
import ayaz.models.budget  # noqa: F401
import ayaz.models.content  # noqa: F401
import ayaz.models.notifications  # noqa: F401
import ayaz.models.social_inbox  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.tracking import ConversionEvent, TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import funnel as funnel_module
from ayaz.services.auth import hash_password
from ayaz.services.funnel import FUNNEL_STAGES, build_funnel

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Funnel Test App")
_test_app.include_router(funnel_module.router, prefix="/api/v1")


# ── DB fixture ─────────────────────────────────────────────────────────────────


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


# ── Client fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Funnel Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="funnel_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Funnel Test User",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db_session.add(membership)
    db_session.commit()

    def _override_db():
        yield db_session

    def _override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = _override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override — tests 401 behaviour."""

    def _override_db():
        yield db_session

    _test_app.dependency_overrides[get_db] = _override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Funnel Tenant") -> Tenant:
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


def _make_source(db: Session, tenant_id: uuid.UUID) -> TrackingSource:
    src = TrackingSource(
        tenant_id=tenant_id,
        name="Funnel Test Source",
        public_token=f"tok-funnel-{uuid.uuid4().hex[:16]}",
        is_active=True,
    )
    db.add(src)
    db.flush()
    return src


def _make_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    event_name: str,
    event_time: str = "2026-03-15T10:00:00+00:00",
    status: str = "forwarded",
) -> ConversionEvent:
    """Insert a single ConversionEvent satisfying all NOT NULL constraints."""
    evt = ConversionEvent(
        tenant_id=tenant_id,
        tracking_source_id=source_id,
        event_name=event_name,
        event_time=event_time,
        event_id=f"evt-{uuid.uuid4().hex}",
        user_data={},
        custom_data={},
        consent=True,
        status=status,
        forwarded_count=1,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(evt)
    db.flush()
    return evt


def _seed_funnel(
    db: Session,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    counts: dict[str, int],
    event_time: str = "2026-03-15T10:00:00+00:00",
) -> None:
    """Seed events for each event_name in counts."""
    for event_name, n in counts.items():
        for _ in range(n):
            _make_event(
                db,
                tenant_id=tenant_id,
                source_id=source_id,
                event_name=event_name,
                event_time=event_time,
            )
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. build_funnel — servis düzeyinde testler
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildFunnelStages:
    """Aşama sayıları, sıraları ve matematiksel doğruluğu."""

    def test_stage_count_and_order(self, db_session: Session) -> None:
        """build_funnel tam olarak 5 aşama döndürmeli ve FUNNEL_STAGES sırasını korumalı."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26, "AddToCart": 18,
             "InitiateCheckout": 10, "Purchase": 6},
        )
        result = build_funnel(db_session, tenant.id)
        stages = result["stages"]
        assert len(stages) == 5
        keys = [s["key"] for s in stages]
        assert keys == [k for k, _ in FUNNEL_STAGES]

    def test_stage_labels_match_funnel_stages(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        result = build_funnel(db_session, tenant.id)
        for stage, (key, label) in zip(result["stages"], FUNNEL_STAGES):
            assert stage["key"] == key
            assert stage["label"] == label

    def test_stage_counts_correct(self, db_session: Session) -> None:
        """Her aşamanın count alanı eklenen olay sayısıyla eslesmelidir."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        expected = {"PageView": 40, "ViewContent": 26, "AddToCart": 18,
                    "InitiateCheckout": 10, "Purchase": 6}
        _seed_funnel(db_session, tenant.id, src.id, expected)
        result = build_funnel(db_session, tenant.id)
        for stage in result["stages"]:
            assert stage["count"] == expected[stage["key"]]

    def test_total_events_is_sum_of_five_stages(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26, "AddToCart": 18,
             "InitiateCheckout": 10, "Purchase": 6},
        )
        result = build_funnel(db_session, tenant.id)
        assert result["total_events"] == 40 + 26 + 18 + 10 + 6

    def test_entry_count_is_first_stage(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40, "Purchase": 6})
        result = build_funnel(db_session, tenant.id)
        assert result["entry_count"] == 40

    def test_final_count_is_last_stage(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40, "Purchase": 6})
        result = build_funnel(db_session, tenant.id)
        assert result["final_count"] == 6

    def test_first_stage_has_null_conversion_and_dropoff(self, db_session: Session) -> None:
        """Ilk aşama icin conversion_from_prev_pct ve dropoff_pct null olmalidir."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40})
        result = build_funnel(db_session, tenant.id)
        first = result["stages"][0]
        assert first["conversion_from_prev_pct"] is None
        assert first["dropoff_pct"] is None
        assert first["dropoff_count"] == 0

    def test_conversion_from_prev_pct_math(self, db_session: Session) -> None:
        """conversion_from_prev_pct = stage.count / prev.count * 100."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        # PageView=40, ViewContent=26 → 26/40*100 = 65.0
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26},
        )
        result = build_funnel(db_session, tenant.id)
        vc = next(s for s in result["stages"] if s["key"] == "ViewContent")
        assert vc["conversion_from_prev_pct"] == pytest.approx(65.0, abs=0.01)

    def test_dropoff_pct_equals_100_minus_conversion(self, db_session: Session) -> None:
        """dropoff_pct = 100 - conversion_from_prev_pct."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26},
        )
        result = build_funnel(db_session, tenant.id)
        vc = next(s for s in result["stages"] if s["key"] == "ViewContent")
        assert vc["dropoff_pct"] == pytest.approx(35.0, abs=0.01)

    def test_dropoff_count_is_prev_minus_count(self, db_session: Session) -> None:
        """dropoff_count = prev_stage.count - this_stage.count."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26, "AddToCart": 18},
        )
        result = build_funnel(db_session, tenant.id)
        cart = next(s for s in result["stages"] if s["key"] == "AddToCart")
        assert cart["dropoff_count"] == 26 - 18  # 8

    def test_share_of_entry_pct_is_count_over_entry(self, db_session: Session) -> None:
        """share_of_entry_pct = count / entry_count * 100."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "ViewContent": 26, "AddToCart": 18,
             "InitiateCheckout": 10, "Purchase": 6},
        )
        result = build_funnel(db_session, tenant.id)
        for stage in result["stages"]:
            key = stage["key"]
            expected_share = round(stage["count"] / 40 * 100, 2)
            assert stage["share_of_entry_pct"] == pytest.approx(expected_share, abs=0.1)

    def test_first_stage_share_is_100(self, db_session: Session) -> None:
        """Ilk aşamanin share_of_entry_pct degeri 100.0 olmalidir."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40})
        result = build_funnel(db_session, tenant.id)
        assert result["stages"][0]["share_of_entry_pct"] == 100.0


class TestBuildFunnelOverallConversion:
    """overall_conversion_pct ve sifir koruması."""

    def test_overall_conversion_pct_correct(self, db_session: Session) -> None:
        """overall_conversion_pct = final_count / entry_count * 100."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 40, "Purchase": 6},
        )
        result = build_funnel(db_session, tenant.id)
        # 6 / 40 * 100 = 15.0
        assert result["overall_conversion_pct"] == pytest.approx(15.0, abs=0.01)

    def test_entry_zero_gives_zero_overall_conversion(self, db_session: Session) -> None:
        """Hic olay yoksa overall_conversion_pct 0.0 olmali, hata verilmemeli."""
        tenant = _make_tenant(db_session)
        result = build_funnel(db_session, tenant.id)
        assert result["overall_conversion_pct"] == 0.0
        assert result["entry_count"] == 0
        assert result["final_count"] == 0

    def test_no_purchase_gives_zero_overall_conversion(self, db_session: Session) -> None:
        """Purchase olayı yoksa overall_conversion_pct 0.0 olmali."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40})
        result = build_funnel(db_session, tenant.id)
        assert result["overall_conversion_pct"] == 0.0


class TestBuildFunnelBiggestDropoff:
    """biggest_dropoff dogru gecisi tanimlamalidir."""

    def test_biggest_dropoff_identifies_largest_transition(self, db_session: Session) -> None:
        """En büyük düşüş geçişini bulmali.

        PageView=100, ViewContent=40 → %60 düşüş
        ViewContent=40, AddToCart=30  → %25 düşüş
        AddToCart=30, InitiateCheckout=25 → ~16.67% düşüş
        InitiateCheckout=25, Purchase=20 → %20 düşüş

        Beklenen: PageView → ViewContent (%60 düşüş).
        """
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 100, "ViewContent": 40, "AddToCart": 30,
             "InitiateCheckout": 25, "Purchase": 20},
        )
        result = build_funnel(db_session, tenant.id)
        bd = result["biggest_dropoff"]
        assert bd is not None
        assert bd["from_label"] == "Sayfa Görüntüleme"
        assert bd["to_label"] == "Ürün Görüntüleme"
        assert bd["dropoff_pct"] == pytest.approx(60.0, abs=0.1)

    def test_biggest_dropoff_null_when_entry_only(self, db_session: Session) -> None:
        """Yalnizca bir aşamada veri varsa biggest_dropoff null olmali.

        Ikinci aşama icin prev.count = entry ama bir sonraki aşamalar icin
        prev.count'un sifir olma durumunu da test eder.
        Hic veri yokken biggest_dropoff null doner.
        """
        tenant = _make_tenant(db_session)
        result = build_funnel(db_session, tenant.id)
        assert result["biggest_dropoff"] is None

    def test_biggest_dropoff_null_when_prev_count_is_zero_for_all(
        self, db_session: Session
    ) -> None:
        """Yalnizca ilk aşamada olay varsa, dropoff_pct hesaplanamaz."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        # Sadece PageView, diger aşamalar sifir
        _seed_funnel(db_session, tenant.id, src.id, {"PageView": 40})
        result = build_funnel(db_session, tenant.id)
        # ViewContent.count=0, prev=40 → dropoff_pct=100.0 → biggest_dropoff mevcut olmali
        bd = result["biggest_dropoff"]
        assert bd is not None
        assert bd["dropoff_pct"] == pytest.approx(100.0, abs=0.01)

    def test_biggest_dropoff_correct_between_two_nonzero_stages(
        self, db_session: Session
    ) -> None:
        """En büyük düşüş geçişi dogru tanimlanmalidir.

        Tüm 5 aşama için sayımlar:
          PageView=100, ViewContent=80, AddToCart=40, InitiateCheckout=30, Purchase=20
          PV→VC: %20 düşüş, VC→Cart: %50 düşüş,
          Cart→Init: %25 düşüş, Init→Purchase: ~%33.3 düşüş

        En büyük düşüş: ViewContent → AddToCart (%50).
        """
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 100, "ViewContent": 80, "AddToCart": 40,
             "InitiateCheckout": 30, "Purchase": 20},
        )
        result = build_funnel(db_session, tenant.id)
        bd = result["biggest_dropoff"]
        assert bd is not None
        assert bd["from_label"] == "Ürün Görüntüleme"
        assert bd["to_label"] == "Sepete Ekleme"
        assert bd["dropoff_pct"] == pytest.approx(50.0, abs=0.1)


class TestBuildFunnelIgnoresOutsideStages:
    """Huni disi event_name'ler yoksayilmalidir."""

    def test_outside_events_not_counted(self, db_session: Session) -> None:
        """'Lead', 'Search' gibi olaylar total_events'e dahil edilmemeli."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 10, "Purchase": 5, "Lead": 50, "Search": 30},
        )
        result = build_funnel(db_session, tenant.id)
        assert result["total_events"] == 15  # Lead + Search yoksayildi

    def test_outside_events_do_not_appear_in_stages(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"Lead": 50, "Search": 30},
        )
        result = build_funnel(db_session, tenant.id)
        stage_keys = {s["key"] for s in result["stages"]}
        assert "Lead" not in stage_keys
        assert "Search" not in stage_keys
        # Tum aşamalar count=0 olmali
        for stage in result["stages"]:
            assert stage["count"] == 0


class TestBuildFunnelDateFilter:
    """Tarih penceresi filtresi."""

    def test_date_window_filters_events(self, db_session: Session) -> None:
        """Tarih araligi dışındaki olaylar dahil edilmemeli."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        # Ocak ayı olayları
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 10, "Purchase": 5},
            event_time="2026-01-15T10:00:00+00:00",
        )
        # Mart ayı olayları
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 20, "Purchase": 8},
            event_time="2026-03-15T10:00:00+00:00",
        )
        # Yalnızca Mart filtrelendiginde
        result = build_funnel(
            db_session, tenant.id,
            date_from="2026-03-01",
            date_to="2026-03-31",
        )
        pv = next(s for s in result["stages"] if s["key"] == "PageView")
        pu = next(s for s in result["stages"] if s["key"] == "Purchase")
        assert pv["count"] == 20
        assert pu["count"] == 8

    def test_omitted_dates_includes_all_events(self, db_session: Session) -> None:
        """Tarih parametresi verilmezse tüm olaylar dahil edilmeli."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 10},
            event_time="2026-01-15T10:00:00+00:00",
        )
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 20},
            event_time="2026-03-15T10:00:00+00:00",
        )
        result = build_funnel(db_session, tenant.id)  # Tarih yok
        pv = next(s for s in result["stages"] if s["key"] == "PageView")
        assert pv["count"] == 30

    def test_date_inclusive_end(self, db_session: Session) -> None:
        """date_to gunun sonu dahil (T23:59:59 cevabindan once)."""
        tenant = _make_tenant(db_session)
        src = _make_source(db_session, tenant.id)
        # Gun sonunda olay
        _seed_funnel(
            db_session, tenant.id, src.id,
            {"PageView": 5},
            event_time="2026-03-15T23:59:58+00:00",
        )
        result = build_funnel(
            db_session, tenant.id,
            date_from="2026-03-15",
            date_to="2026-03-15",
        )
        pv = next(s for s in result["stages"] if s["key"] == "PageView")
        assert pv["count"] == 5

    def test_period_returned_in_result(self, db_session: Session) -> None:
        """period alanı verilen tarih parametrelerini yansiitmalidir."""
        tenant = _make_tenant(db_session)
        result = build_funnel(
            db_session, tenant.id,
            date_from="2026-01-01",
            date_to="2026-01-31",
        )
        assert result["period"]["date_from"] == "2026-01-01"
        assert result["period"]["date_to"] == "2026-01-31"

    def test_period_null_when_no_dates(self, db_session: Session) -> None:
        """Tarih parametresi yoksa period alanları null olmali."""
        tenant = _make_tenant(db_session)
        result = build_funnel(db_session, tenant.id)
        assert result["period"]["date_from"] is None
        assert result["period"]["date_to"] is None

    def test_tenant_isolation(self, db_session: Session) -> None:
        """Baska kiracinin olayları görünmemeli."""
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")
        src_a = _make_source(db_session, tenant_a.id)
        src_b = _make_source(db_session, tenant_b.id)

        _seed_funnel(db_session, tenant_a.id, src_a.id, {"PageView": 50, "Purchase": 10})
        _seed_funnel(db_session, tenant_b.id, src_b.id, {"PageView": 99, "Purchase": 99})

        result = build_funnel(db_session, tenant_a.id)
        pv = next(s for s in result["stages"] if s["key"] == "PageView")
        pu = next(s for s in result["stages"] if s["key"] == "Purchase")
        assert pv["count"] == 50
        assert pu["count"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 2. HTTP endpoint testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestFunnelEndpoint:
    def test_happy_path_200(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/funnel/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert resp.status_code == 200

    def test_response_shape_correct(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/funnel/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {
            "period", "total_events", "stages",
            "entry_count", "final_count", "overall_conversion_pct", "biggest_dropoff",
        }
        assert len(body["stages"]) == 5
        assert set(body["period"].keys()) >= {"date_from", "date_to"}
        for stage in body["stages"]:
            assert set(stage.keys()) >= {
                "key", "label", "count",
                "conversion_from_prev_pct", "dropoff_count",
                "dropoff_pct", "share_of_entry_pct",
            }

    def test_no_date_params_returns_200(self, client: TestClient) -> None:
        """Tarih parametresi olmadan da 200 dönmeli."""
        resp = client.get("/api/v1/funnel/overview")
        assert resp.status_code == 200

    def test_date_from_after_date_to_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/funnel/overview",
            params={"date_from": "2026-01-31", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get(
            "/api/v1/funnel/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert resp.status_code in (401, 403)

    def test_stage_keys_in_order(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/funnel/overview",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )
        assert resp.status_code == 200
        keys = [s["key"] for s in resp.json()["stages"]]
        assert keys == [k for k, _ in FUNNEL_STAGES]
