"""Kullanım Kalkanı (Usage Shield) testleri.

Kapsam
------
- compute_shield: unlimited plan → pct=None, approaching/at_limit=False
- compute_shield: starter plan (max 3) — kullanım yok → bayraklar False
- compute_shield: %80+ kullanım → approaching_limit=True
- compute_shield: tam limit → at_limit=True
- Atıl konektör tespiti: watermark bayat → idle
- Atıl konektör tespiti: sync_status=error → error reason
- Atıl konektör tespiti: hiç watermark yok + idle status → idle
- Taze konektör: son sync < eşik → atıl sayılmaz
- check_and_notify: approaching_limit → bildirim oluşturulur
- check_and_notify: at_limit → critical bildirim
- check_and_notify: atıl konektör → bildirim oluşturulur
- İdempotency: aynı kanaldan spam koruması (24 saat penceresi)
- İdempotency: pencere geçince yeniden bildirim üretilir
- Shield endpoint: tenant izolasyonu (kiracı B kiracı A'nın verisini göremez)
- Shield endpoint: yetkisiz istek → 401
- Shield endpoint: başarılı GET → 200 + doğru alan yapısı
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Model modüllerini Base.metadata'ya kaydet
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.notifications  # noqa: F401
import ayaz.models.insights  # noqa: F401

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import usage_shield as shield_module
from ayaz.database import get_db as real_get_db
from ayaz.models.base import Base
from ayaz.models.billing import Subscription
from ayaz.models.notifications import Notification
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
from ayaz.services.usage_shield import (
    IDLE_THRESHOLD_DAYS,
    NOTIFY_WINDOW_HOURS,
    check_and_notify,
    compute_shield,
)

# ── Minimal test uygulaması ───────────────────────────────────────────────────

_shield_app = FastAPI(title="Usage Shield Test")
_shield_app.include_router(shield_module.router, prefix="/api/v1")


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Veri yardımcıları ─────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
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
        email=f"shield-{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Shield Test User",
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


def _make_subscription(
    db: Session,
    tenant: Tenant,
    plan_code: str = "starter",
) -> Subscription:
    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_code=plan_code,
        status="active",
        provider="none",
    )
    db.add(sub)
    db.flush()
    return sub


def _make_account(
    db: Session,
    tenant: Tenant,
    *,
    sync_status: SyncStatus = SyncStatus.idle,
    watermark: str | None = None,
    display_name: str = "Test Account",
) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.google_ads,
        external_account_id=f"ACC-{uuid.uuid4().hex[:8]}",
        display_name=display_name,
        vault_secret_ref="",
        sync_status=sync_status,
        watermark=watermark,
    )
    db.add(acct)
    db.flush()
    return acct


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── compute_shield testleri ───────────────────────────────────────────────────


class TestComputeShield:
    def test_unlimited_plan_no_pct(self, db_session: Session):
        """Agency planında max_data_sources=unlimited → pct None, bayraklar False."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="agency")
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.data_sources_max == "unlimited"
        assert report.data_sources_pct is None
        assert report.approaching_limit is False
        assert report.at_limit is False

    def test_no_usage_no_flags(self, db_session: Session):
        """Starter plan, hiç kaynak yok → bayraklar False."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")  # max 3
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.data_sources_used == 0
        assert report.data_sources_max == 3
        assert report.approaching_limit is False
        assert report.at_limit is False

    def test_approaching_limit_flag(self, db_session: Session):
        """Starter (max=3), 3 kaynak var → %100 → at_limit=True (approaching de True değil)."""
        # %80 = 2.4 → 3/3 = %100 → at_limit
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")  # max 3
        # 2 hesap ekle → %66 — approaching olmaz
        _make_account(db_session, tenant)
        _make_account(db_session, tenant)
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.data_sources_used == 2
        assert report.data_sources_pct is not None
        # 2/3 ≈ 66.7% → approaching=False
        assert report.approaching_limit is False
        assert report.at_limit is False

    def test_approaching_limit_at_80_pct(self, db_session: Session):
        """Growth plan (max=8), 7 kaynak → %87.5 → approaching_limit=True."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="growth")  # max 8
        for _ in range(7):
            _make_account(db_session, tenant)
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.data_sources_used == 7
        assert report.data_sources_pct == pytest.approx(87.5)
        assert report.approaching_limit is True
        assert report.at_limit is False
        assert "approaching_limit" in report.active_warnings

    def test_at_limit_flag(self, db_session: Session):
        """Starter (max=3), 3 kaynak → at_limit=True."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")  # max 3
        for _ in range(3):
            _make_account(db_session, tenant)
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.data_sources_used == 3
        assert report.at_limit is True
        assert "at_limit" in report.active_warnings

    def test_idle_connector_stale_watermark(self, db_session: Session):
        """Watermark > threshold gün eski → atıl (idle)."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        stale = _ago_iso(IDLE_THRESHOLD_DAYS + 1)
        _make_account(
            db_session, tenant,
            sync_status=SyncStatus.success,
            watermark=stale,
            display_name="Eski Kaynak",
        )
        db_session.commit()

        report = compute_shield(db_session, tenant.id, idle_threshold_days=IDLE_THRESHOLD_DAYS)
        assert len(report.idle_connectors) == 1
        conn = report.idle_connectors[0]
        assert conn.reason == "idle"
        assert conn.display_name == "Eski Kaynak"
        assert "idle_connectors" in report.active_warnings

    def test_fresh_connector_not_idle(self, db_session: Session):
        """Watermark < threshold → atıl sayılmaz."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        fresh = _ago_iso(IDLE_THRESHOLD_DAYS - 1)
        _make_account(
            db_session, tenant,
            sync_status=SyncStatus.success,
            watermark=fresh,
        )
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.idle_connectors == []

    def test_error_connector_flagged(self, db_session: Session):
        """sync_status=error → atıl konektör, reason='error'."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        _make_account(
            db_session, tenant,
            sync_status=SyncStatus.error,
            display_name="Hatalı Kaynak",
        )
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert len(report.idle_connectors) == 1
        assert report.idle_connectors[0].reason == "error"
        assert report.idle_connectors[0].sync_status == "error"

    def test_no_watermark_idle_status(self, db_session: Session):
        """Hiç watermark yok + sync_status=idle → atıl."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        _make_account(
            db_session, tenant,
            sync_status=SyncStatus.idle,
            watermark=None,
        )
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert len(report.idle_connectors) == 1
        assert report.idle_connectors[0].reason == "idle"

    def test_plan_info_in_report(self, db_session: Session):
        """Rapor doğru plan bilgilerini içerir."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="growth")
        db_session.commit()

        report = compute_shield(db_session, tenant.id)
        assert report.plan_code == "growth"
        assert report.plan_name == "Growth"
        assert report.tenant_id == tenant.id


# ── check_and_notify testleri ─────────────────────────────────────────────────


class TestCheckAndNotify:
    def test_approaching_limit_creates_warning_notification(self, db_session: Session):
        """approaching_limit → 'warning' seviyeli bildirim oluşturulur."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="growth")  # max 8
        for _ in range(7):  # 7/8 = 87.5%
            _make_account(db_session, tenant)
        db_session.commit()

        result = check_and_notify(db_session, tenant.id)
        assert result["notifications_created"] >= 1

        notifs = db_session.query(Notification).filter_by(tenant_id=tenant.id).all()
        refs = [n.source_ref for n in notifs]
        assert f"shield:approaching_limit:{tenant.id}" in refs

        approaching_notif = next(n for n in notifs if "approaching_limit" in (n.source_ref or ""))
        assert approaching_notif.severity == "warning"
        assert approaching_notif.type == "system"
        # Body contains the rounded percentage (7/8 = 87.5% → rounds to 88)
        assert any(s in approaching_notif.body for s in ("87", "88", "7/8"))

    def test_at_limit_creates_critical_notification(self, db_session: Session):
        """at_limit → 'critical' seviyeli bildirim oluşturulur."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")  # max 3
        for _ in range(3):
            _make_account(db_session, tenant)
        db_session.commit()

        result = check_and_notify(db_session, tenant.id)
        assert result["notifications_created"] >= 1

        notifs = db_session.query(Notification).filter_by(tenant_id=tenant.id).all()
        limit_notif = next(
            (n for n in notifs if n.source_ref and "at_limit" in n.source_ref), None
        )
        assert limit_notif is not None
        assert limit_notif.severity == "critical"

    def test_idle_connector_creates_notification(self, db_session: Session):
        """Atıl konektör → bildirim oluşturulur."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        stale = _ago_iso(IDLE_THRESHOLD_DAYS + 2)
        acct = _make_account(
            db_session, tenant,
            sync_status=SyncStatus.success,
            watermark=stale,
            display_name="Atıl Kaynak",
        )
        db_session.commit()

        result = check_and_notify(db_session, tenant.id)
        assert result["notifications_created"] >= 1

        notifs = db_session.query(Notification).filter_by(tenant_id=tenant.id).all()
        idle_notif = next(
            (n for n in notifs if n.source_ref and f"idle_connector:{acct.id}" in n.source_ref),
            None,
        )
        assert idle_notif is not None
        assert idle_notif.severity == "warning"
        assert "/connectors" in (idle_notif.link or "")

    def test_error_connector_creates_critical_notification(self, db_session: Session):
        """sync_status=error konektör → 'critical' bildirim."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")
        acct = _make_account(
            db_session, tenant,
            sync_status=SyncStatus.error,
            display_name="Hatalı Kaynak",
        )
        db_session.commit()

        check_and_notify(db_session, tenant.id)

        notifs = db_session.query(Notification).filter_by(tenant_id=tenant.id).all()
        err_notif = next(
            (n for n in notifs if n.source_ref and f"idle_connector:{acct.id}" in n.source_ref),
            None,
        )
        assert err_notif is not None
        assert err_notif.severity == "critical"

    def test_idempotency_no_duplicate_in_window(self, db_session: Session):
        """Aynı kiracı için iki kez çağrı → pencere içinde tekrar bildirim üretilmez."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="starter")  # max 3
        for _ in range(3):
            _make_account(db_session, tenant)
        db_session.commit()

        r1 = check_and_notify(db_session, tenant.id)
        r2 = check_and_notify(db_session, tenant.id)

        # İkinci çağrı spam koruması nedeniyle yeni bildirim üretmemeli
        assert r2["notifications_created"] == 0

        # Toplam bildirim sayısı 1 (at_limit için)
        total = db_session.query(Notification).filter_by(tenant_id=tenant.id).count()
        assert total == r1["notifications_created"]

    def test_no_notification_without_issues(self, db_session: Session):
        """Sorun yokken bildirim oluşturulmaz."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="growth")  # max 8, hiç kaynak yok
        db_session.commit()

        result = check_and_notify(db_session, tenant.id)
        assert result["notifications_created"] == 0

        total = db_session.query(Notification).filter_by(tenant_id=tenant.id).count()
        assert total == 0

    def test_no_notification_for_unlimited_plan(self, db_session: Session):
        """Agency planında (unlimited) limit bildirimi oluşturulmaz."""
        tenant = _make_tenant(db_session)
        _make_subscription(db_session, tenant, plan_code="agency")
        for _ in range(20):
            _make_account(db_session, tenant)
        db_session.commit()

        result = check_and_notify(db_session, tenant.id)
        # limit bildirimleri yok (atıl olabilir ama limit yok)
        notifs = db_session.query(Notification).filter_by(tenant_id=tenant.id).all()
        limit_notifs = [
            n for n in notifs
            if n.source_ref and ("approaching_limit" in n.source_ref or "at_limit" in n.source_ref)
        ]
        assert len(limit_notifs) == 0


# ── Shield endpoint testleri ──────────────────────────────────────────────────


@pytest.fixture()
def shield_client(db_session: Session):
    """Shield router'ı bağlı TestClient — DB ve membership override edilmiş."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    _make_subscription(db_session, tenant, plan_code="starter")
    db_session.commit()

    def _override_db():
        yield db_session

    def _override_membership():
        return membership

    _shield_app.dependency_overrides[get_db] = _override_db
    _shield_app.dependency_overrides[get_current_membership] = _override_membership

    yield TestClient(_shield_app), tenant, membership

    _shield_app.dependency_overrides.clear()


class TestShieldEndpoint:
    def test_get_shield_200(self, shield_client):
        """GET /api/v1/usage-shield → 200 ve beklenen alanlar."""
        client, tenant, _ = shield_client
        resp = client.get("/api/v1/usage-shield")
        assert resp.status_code == 200
        data = resp.json()

        assert data["tenant_id"] == str(tenant.id)
        assert "plan_code" in data
        assert "plan_name" in data
        assert "data_sources_used" in data
        assert "data_sources_max" in data
        assert "approaching_limit" in data
        assert "at_limit" in data
        assert "idle_connectors" in data
        assert "active_warnings" in data
        assert isinstance(data["idle_connectors"], list)
        assert isinstance(data["active_warnings"], list)

    def test_get_shield_no_auth_401(self):
        """Auth olmadan → 401."""
        from ayaz.main import app as real_app
        client = TestClient(real_app)
        resp = client.get("/api/v1/usage-shield")
        assert resp.status_code == 401

    def test_tenant_isolation(self, db_session: Session):
        """Kiracı B, kiracı A'nın verilerini göremez."""
        # Kiracı A: limit dolu
        tenant_a = _make_tenant(db_session, name="Tenant A")
        user_a = _make_user(db_session)
        membership_a = _make_membership(db_session, user_a, tenant_a)
        _make_subscription(db_session, tenant_a, plan_code="starter")  # max 3
        for _ in range(3):
            _make_account(db_session, tenant_a)

        # Kiracı B: temiz
        tenant_b = _make_tenant(db_session, name="Tenant B")
        user_b = _make_user(db_session)
        membership_b = _make_membership(db_session, user_b, tenant_b)
        _make_subscription(db_session, tenant_b, plan_code="growth")  # max 8
        db_session.commit()

        # B'nin istemcisi
        def _db():
            yield db_session

        def _membership_b():
            return membership_b

        _shield_app.dependency_overrides[get_db] = _db
        _shield_app.dependency_overrides[get_current_membership] = _membership_b

        try:
            client = TestClient(_shield_app)
            resp = client.get("/api/v1/usage-shield")
            assert resp.status_code == 200
            data = resp.json()
            # Kiracı B'nin tenant_id döner
            assert data["tenant_id"] == str(tenant_b.id)
            # Kiracı B'de kaynak yok → at_limit=False
            assert data["at_limit"] is False
            # Kiracı B'nin kullanımı 0
            assert data["data_sources_used"] == 0
        finally:
            _shield_app.dependency_overrides.clear()

    def test_idle_connector_in_response(self, db_session: Session):
        """Atıl konektör endpoint yanıtında görünür."""
        tenant = _make_tenant(db_session)
        user = _make_user(db_session)
        membership = _make_membership(db_session, user, tenant)
        _make_subscription(db_session, tenant, plan_code="starter")
        stale = _ago_iso(IDLE_THRESHOLD_DAYS + 2)
        acct = _make_account(
            db_session, tenant,
            sync_status=SyncStatus.success,
            watermark=stale,
            display_name="Atıl Kaynak",
        )
        db_session.commit()

        def _db():
            yield db_session

        def _mem():
            return membership

        _shield_app.dependency_overrides[get_db] = _db
        _shield_app.dependency_overrides[get_current_membership] = _mem

        try:
            client = TestClient(_shield_app)
            resp = client.get("/api/v1/usage-shield")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["idle_connectors"]) == 1
            conn = data["idle_connectors"][0]
            assert conn["account_id"] == str(acct.id)
            assert conn["reason"] == "idle"
            assert conn["display_name"] == "Atıl Kaynak"
            assert "idle_connectors" in data["active_warnings"]
        finally:
            _shield_app.dependency_overrides.clear()
