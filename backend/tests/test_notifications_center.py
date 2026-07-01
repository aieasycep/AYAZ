"""Bildirim Merkezi (Dalga 26) testleri.

Strateji
--------
* In-memory SQLite DB kullanılır (test_insights.py ile aynı fixture pattern).
* FastAPI TestClient ile bağımlılıklar (DB, membership) override edilir.
* Ağ çağrısı yapılmaz.

Kapsam
------
- Boş liste → []
- Insight seed'lendikten sonra GET list gecikmeli bildirim oluşturur
- Aynı çağrı ikinci kez yapıldığında yineleme olmaz (source_ref tekilleştirme)
- unread-count
- Tek bildirim okundu işaretleme (unread-count'tan düşer, unread_only listesinden çıkar)
- read-all
- Olmayan / başka kiracı ID ile mark-read → 404
- Kiracı izolasyonu (kiracı B, kiracı A'nın bildirimlerini göremez)
- Auth gerekli (401)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership
from ayaz.api.v1.notifications import router as notifications_router
from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.insights import Insight
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import hash_password

# ── Minimal test uygulaması ───────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(notifications_router, prefix="/api/v1")

# Auth gerektiren endpoint'leri test etmek için ham AYAZ uygulaması
from ayaz.main import app as _real_app  # noqa: E402

_SQLITE_URL = "sqlite://"


# ── Fixture: in-memory SQLite DB ──────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Her test için temiz bir in-memory SQLite DB oluşturur."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Tüm model modüllerini import et — tablolar Base.metadata'ya kaydedilsin
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.notifications  # noqa: F401
    import ayaz.models.oltp  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Yardımcı fabrika fonksiyonları ────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Kiracı") -> Tenant:
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


def _make_insight(
    db: Session,
    tenant: Tenant,
    title: str = "ROAS düştü",
    severity: str = "warning",
) -> Insight:
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="roas_drop",
        severity=severity,
        title=title,
        body="ROAS önemli ölçüde geriledi.",
        metric="roas",
        channel="google_ads",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 7),
        status="new",
        score=75.0,
        data={"pct_drop": 0.25},
    )
    db.add(ins)
    db.flush()
    return ins


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def notif_client(db_session: Session):
    """TestClient: DB ve membership bağımlılıkları override edilmiş."""
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
    yield client, tenant, membership, db_session

    _test_app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# Boş durum testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyState:
    """Insight olmadığında bildirim listesi boş dönmeli."""

    def test_list_returns_empty(self, notif_client) -> None:
        client, *_ = notif_client
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unread_count_zero(self, notif_client) -> None:
        client, *_ = notif_client
        resp = client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 200
        assert resp.json() == {"count": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# Gecikmeli üretim ve tekilleştirme testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestLazySyncFromInsights:
    """GET /notifications Insight'lardan gecikmeli bildirim oluşturmalı."""

    def test_list_creates_notifications_from_insights(
        self, notif_client
    ) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant, title="İlk insight")
        _make_insight(db, tenant, title="İkinci insight")
        db.commit()

        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2

    def test_list_is_idempotent_no_duplicates(self, notif_client) -> None:
        """Aynı çağrı iki kez yapıldığında bildirim sayısı artmamalı."""
        client, tenant, _, db = notif_client
        _make_insight(db, tenant, title="Tek insight")
        db.commit()

        resp1 = client.get("/api/v1/notifications")
        assert resp1.status_code == 200
        assert len(resp1.json()) == 1

        resp2 = client.get("/api/v1/notifications")
        assert resp2.status_code == 200
        # source_ref tekilleştirmesi: ikinci çağrıda yineleme olmamalı
        assert len(resp2.json()) == 1

    def test_source_ref_deduplication(self, notif_client) -> None:
        """Aynı Insight için iki kez sync yapılsa bile bir bildirim olmalı."""
        from ayaz.services.notifications_center import sync_from_insights

        client, tenant, _, db = notif_client
        insight = _make_insight(db, tenant)
        db.commit()

        created1 = sync_from_insights(db, tenant.id)
        created2 = sync_from_insights(db, tenant.id)

        assert created1 == 1
        assert created2 == 0  # yineleme yapılmadı

    def test_notification_fields_mapped_correctly(self, notif_client) -> None:
        """Bildirim alanları Insight'tan doğru aktarılmalı."""
        client, tenant, _, db = notif_client
        _make_insight(db, tenant, title="ROAS düştü", severity="critical")
        db.commit()

        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        n = resp.json()[0]

        assert n["type"] == "insight"
        assert n["severity"] == "critical"
        assert n["title"] == "ROAS düştü"
        assert n["link"] == "/insights"
        assert n["read"] is False

    def test_unread_count_after_sync(self, notif_client) -> None:
        """Insight eklendikten sonra unread-count artmalı."""
        client, tenant, _, db = notif_client
        _make_insight(db, tenant)
        _make_insight(db, tenant)
        db.commit()

        resp = client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Mark-read testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkRead:
    """POST /notifications/{id}/read"""

    def test_mark_one_read_returns_updated(self, notif_client) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant)
        db.commit()

        list_resp = client.get("/api/v1/notifications")
        notif_id = list_resp.json()[0]["id"]

        resp = client.post(f"/api/v1/notifications/{notif_id}/read")
        assert resp.status_code == 200
        assert resp.json()["read"] is True

    def test_mark_read_reduces_unread_count(self, notif_client) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant)
        _make_insight(db, tenant)
        db.commit()

        list_resp = client.get("/api/v1/notifications")
        notif_id = list_resp.json()[0]["id"]

        count_before = client.get("/api/v1/notifications/unread-count").json()["count"]
        assert count_before == 2

        client.post(f"/api/v1/notifications/{notif_id}/read")

        count_after = client.get("/api/v1/notifications/unread-count").json()["count"]
        assert count_after == 1

    def test_mark_read_removes_from_unread_only_list(self, notif_client) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant, title="Okunacak")
        db.commit()

        list_resp = client.get("/api/v1/notifications")
        notif_id = list_resp.json()[0]["id"]

        client.post(f"/api/v1/notifications/{notif_id}/read")

        unread_resp = client.get("/api/v1/notifications", params={"unread_only": True})
        assert unread_resp.status_code == 200
        assert unread_resp.json() == []

    def test_mark_read_nonexistent_returns_404(self, notif_client) -> None:
        client, *_ = notif_client
        fake_id = uuid.uuid4()
        resp = client.post(f"/api/v1/notifications/{fake_id}/read")
        assert resp.status_code == 404

    def test_mark_read_cross_tenant_returns_404(
        self, notif_client
    ) -> None:
        """Başka kiracının bildirimi 404 dönmeli."""
        client, tenant_a, _, db = notif_client

        # Kiracı B'nin insight'ı → bildirimini doğrudan oluştur
        tenant_b = _make_tenant(db, "Kiracı B")
        db.commit()

        from ayaz.models.notifications import Notification

        other_notif = Notification(
            tenant_id=tenant_b.id,
            type="insight",
            severity="info",
            title="B insight",
            body="",
            link="/insights",
            source_ref=f"insight:{uuid.uuid4()}",
        )
        db.add(other_notif)
        db.commit()

        resp = client.post(f"/api/v1/notifications/{other_notif.id}/read")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Mark-all-read testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkAllRead:
    """POST /notifications/read-all"""

    def test_read_all_marks_all_unread(self, notif_client) -> None:
        client, tenant, _, db = notif_client
        for i in range(3):
            _make_insight(db, tenant, title=f"Insight {i}")
        db.commit()

        # Önce senkronize et
        client.get("/api/v1/notifications")

        resp = client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3

    def test_read_all_returns_zero_if_all_already_read(
        self, notif_client
    ) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant)
        db.commit()

        client.get("/api/v1/notifications")
        client.post("/api/v1/notifications/read-all")

        # İkinci çağrıda tüm bildirimler zaten okunmuş
        resp = client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0

    def test_read_all_reduces_unread_count_to_zero(self, notif_client) -> None:
        client, tenant, _, db = notif_client
        _make_insight(db, tenant)
        _make_insight(db, tenant)
        db.commit()

        client.get("/api/v1/notifications")
        client.post("/api/v1/notifications/read-all")

        count_resp = client.get("/api/v1/notifications/unread-count")
        assert count_resp.json()["count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Kiracı izolasyon testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    """Kiracı B, kiracı A'nın bildirimlerini göremez."""

    def test_tenant_b_cannot_see_tenant_a_notifications(
        self, notif_client
    ) -> None:
        client, tenant_a, _, db = notif_client
        _make_insight(db, tenant_a, title="A insight")
        db.commit()

        # Kiracı A'nın bildirimlerini oluştur
        resp_a = client.get("/api/v1/notifications")
        assert len(resp_a.json()) == 1

        # Kiracı B kurulumu
        tenant_b = _make_tenant(db, "Kiracı B")
        user_b = _make_user(db)
        membership_b = _make_membership(db, user_b, tenant_b)
        db.commit()

        def override_b():
            return membership_b

        _test_app.dependency_overrides[get_current_membership] = override_b
        try:
            resp_b = client.get("/api/v1/notifications")
            assert resp_b.status_code == 200
            assert resp_b.json() == []
        finally:
            # Teardown: notif_client fixture cleanup'ı override'ları temizleyecek
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Auth testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthRequired:
    """Token olmadan tüm endpoint'ler 401/403 dönmeli."""

    def test_list_without_auth_returns_401_or_403(self) -> None:
        """Ham uygulama (override yok) token gerektirmeli."""
        client = TestClient(_real_app, raise_server_exceptions=False)
        resp = client.get("/api/v1/notifications")
        assert resp.status_code in (401, 403)

    def test_unread_count_without_auth_returns_401_or_403(self) -> None:
        client = TestClient(_real_app, raise_server_exceptions=False)
        resp = client.get("/api/v1/notifications/unread-count")
        assert resp.status_code in (401, 403)

    def test_mark_read_without_auth_returns_401_or_403(self) -> None:
        client = TestClient(_real_app, raise_server_exceptions=False)
        resp = client.post(f"/api/v1/notifications/{uuid.uuid4()}/read")
        assert resp.status_code in (401, 403)

    def test_read_all_without_auth_returns_401_or_403(self) -> None:
        client = TestClient(_real_app, raise_server_exceptions=False)
        resp = client.post("/api/v1/notifications/read-all")
        assert resp.status_code in (401, 403)
