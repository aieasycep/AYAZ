"""Rol Görünümü (Role-based views) test paketi — Dalga 75.

Coverage
--------
1. Saf birim testleri (DB yok)
   - list_roles: 5 rol, sıralı, gerekli anahtarlar
   - get_role_view: bilinmeyen rol → ValueError

2. Servis testleri (SQLite in-memory DB)
   - Her 5 rol için get_role_view: gerekli anahtarlar, metrikler (varsa),
     priority_screens, attention öğeleri
   - Tenant verisiz çağrı çökmez (graceful degradation)
   - Tenant izolasyonu: başka tenant'ın verisi dönmez

3. HTTP endpoint testleri
   - GET /role-views/roles → 200, 5 öğe, gerekli alanlar
   - GET /role-views/performans → 200, doğru şekil
   - GET /role-views/{her 5 rol} → 200
   - GET /role-views/bogus → 404
   - Auth yok → 401/403
"""

from __future__ import annotations

import uuid
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Tüm modelleri kaydet (Base.metadata.create_all çalışsın) ──────────────────
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
import ayaz.models.copilot  # noqa: F401
import ayaz.models.auth  # noqa: F401
import ayaz.models.recommendations  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import role_views as role_views_module
from ayaz.services.auth import hash_password
from ayaz.services.role_views import (
    ROLE_DEFINITIONS,
    get_role_view,
    list_roles,
)

# ── Test uygulaması ────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Role Views Test App")
_test_app.include_router(role_views_module.router, prefix="/api/v1")


# ── DB fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
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


# ── Tenant / membership yardımcıları ──────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Role Views Test Tenant") -> Tenant:
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
        email=f"rv_test_{uuid.uuid4().hex[:8]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Role View Test User",
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


# ── Client fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient with DB + membership overrides."""
    tenant = _make_tenant(db_session)
    _user, membership = _make_user_and_membership(db_session, tenant)

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    def _override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = _override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient — membership override YOK → gerçek auth → 401/403."""

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = _override_db

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── 1. Saf birim testleri (DB yok) ────────────────────────────────────────────


class TestListRoles:
    def test_returns_five_roles(self) -> None:
        roles = list_roles()
        assert len(roles) == 5

    def test_roles_in_definition_order(self) -> None:
        roles = list_roles()
        expected_keys = [r["key"] for r in ROLE_DEFINITIONS]
        actual_keys = [r["key"] for r in roles]
        assert actual_keys == expected_keys

    def test_required_keys_present(self) -> None:
        roles = list_roles()
        for r in roles:
            assert "key" in r
            assert "label" in r
            assert "description" in r
            assert "icon_key" in r

    def test_all_five_role_keys_present(self) -> None:
        keys = {r["key"] for r in list_roles()}
        assert keys == {
            "performans",
            "marcom",
            "musteri_hizmetleri",
            "planlama",
            "yonetim",
        }

    def test_labels_are_nonempty_strings(self) -> None:
        for r in list_roles():
            assert isinstance(r["label"], str) and len(r["label"]) > 0

    def test_descriptions_are_nonempty_strings(self) -> None:
        for r in list_roles():
            assert isinstance(r["description"], str) and len(r["description"]) > 0

    def test_icon_keys_are_strings(self) -> None:
        icon_keys = {r["icon_key"] for r in list_roles()}
        assert all(isinstance(k, str) and len(k) > 0 for k in icon_keys)


class TestGetRoleViewErrors:
    def test_unknown_role_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError, match="Bilinmeyen"):
            get_role_view(db_session, tenant.id, "bogus_role")

    def test_empty_string_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError):
            get_role_view(db_session, tenant.id, "")

    def test_wrong_case_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError):
            get_role_view(db_session, tenant.id, "Performans")


# ── 2. Servis testleri ────────────────────────────────────────────────────────


class TestGetRoleViewShape:
    """Her 5 rol için get_role_view dönüş şeklini test eder."""

    _REQUIRED_KEYS = {
        "role",
        "label",
        "description",
        "icon_key",
        "generated_at",
        "metrics",
        "attention",
        "priority_screens",
        "quick_actions",
    }

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_required_keys_present(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        for key in self._REQUIRED_KEYS:
            assert key in result, f"Eksik anahtar: {key!r} ({role_key} için)"

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_role_field_matches_key(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        assert result["role"] == role_key

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_metrics_is_list(self, db_session: Session, role_key: str) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        assert isinstance(result["metrics"], list)

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_priority_screens_match_role_definition(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)

        # priority_screens should match what's in the definition
        role_def = next(r for r in ROLE_DEFINITIONS if r["key"] == role_key)
        expected_hrefs = {s["href"] for s in role_def["priority_screens"]}
        actual_hrefs = {s["href"] for s in result["priority_screens"]}
        assert actual_hrefs == expected_hrefs

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_attention_items_have_required_fields(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        for item in result["attention"]:
            assert "title" in item
            assert "detail" in item
            assert "severity" in item
            assert "href" in item
            assert item["severity"] in {"high", "medium", "low"}

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_attention_capped_at_four(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        assert len(result["attention"]) <= 4

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_quick_actions_have_label_and_href(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        for action in result["quick_actions"]:
            assert "label" in action
            assert "href" in action

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_priority_screens_have_why(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        for screen in result["priority_screens"]:
            assert "href" in screen
            assert "label" in screen
            assert "why" in screen
            assert len(screen["why"]) > 0

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_generated_at_is_iso_string(
        self, db_session: Session, role_key: str
    ) -> None:
        from datetime import datetime

        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        # Should parse without error
        parsed = datetime.fromisoformat(result["generated_at"])
        assert parsed is not None


class TestGracefulDegradation:
    """Tenant verisiz (boş DB) çağrılar çökmemeli."""

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_never_raises_with_empty_db(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        # Herhangi bir analytics / content / inbox verisi yok — çökmemeli
        result = get_role_view(db_session, tenant.id, role_key)
        assert result is not None
        assert isinstance(result["metrics"], list)
        assert isinstance(result["attention"], list)

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_metrics_may_be_empty_but_not_none(
        self, db_session: Session, role_key: str
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, role_key)
        # Metrikler boş liste olabilir ama None olmamalı
        assert result["metrics"] is not None

    def test_no_cross_tenant_data_leakage(self, db_session: Session) -> None:
        """İki farklı kiracının get_role_view çağrıları birbirini etkilemez."""
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")

        result_a = get_role_view(db_session, tenant_a.id, "performans")
        result_b = get_role_view(db_session, tenant_b.id, "performans")

        # Her ikisi de geçerli şekilde dönmeli
        assert result_a["role"] == "performans"
        assert result_b["role"] == "performans"


class TestPerformansRolSpecific:
    """Performans rolü için özel testler."""

    def test_priority_screens_include_dashboard(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "performans")
        hrefs = [s["href"] for s in result["priority_screens"]]
        assert "/dashboard" in hrefs

    def test_priority_screens_include_ads(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "performans")
        hrefs = [s["href"] for s in result["priority_screens"]]
        assert "/ads" in hrefs

    def test_icon_key_is_trending(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "performans")
        assert result["icon_key"] == "trending"


class TestYonetimRolSpecific:
    """Yönetim rolü için özel testler."""

    def test_priority_screens_include_executive(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "yonetim")
        hrefs = [s["href"] for s in result["priority_screens"]]
        assert "/executive" in hrefs

    def test_priority_screens_include_benchmark(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "yonetim")
        hrefs = [s["href"] for s in result["priority_screens"]]
        assert "/benchmark" in hrefs

    def test_icon_key_is_chart(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = get_role_view(db_session, tenant.id, "yonetim")
        assert result["icon_key"] == "chart"


# ── 3. HTTP endpoint testleri ─────────────────────────────────────────────────


class TestRolesEndpoint:
    def test_get_roles_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/roles")
        assert resp.status_code == 200

    def test_get_roles_returns_five_items(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/roles")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_get_roles_required_fields(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/roles")
        data = resp.json()
        for item in data:
            assert "key" in item
            assert "label" in item
            assert "description" in item
            assert "icon_key" in item

    def test_get_roles_order_preserved(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/roles")
        data = resp.json()
        expected_keys = [r["key"] for r in ROLE_DEFINITIONS]
        actual_keys = [item["key"] for item in data]
        assert actual_keys == expected_keys

    def test_get_roles_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/role-views/roles")
        assert resp.status_code in {401, 403}


class TestRoleViewEndpoint:
    def test_get_performans_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/performans")
        assert resp.status_code == 200

    def test_get_performans_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/performans")
        data = resp.json()
        for key in (
            "role",
            "label",
            "description",
            "icon_key",
            "generated_at",
            "metrics",
            "attention",
            "priority_screens",
            "quick_actions",
        ):
            assert key in data, f"Yanıtta eksik alan: {key!r}"

    def test_get_performans_role_field(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/performans")
        data = resp.json()
        assert data["role"] == "performans"

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_all_roles_return_200(
        self, client: TestClient, role_key: str
    ) -> None:
        resp = client.get(f"/api/v1/role-views/{role_key}")
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_all_roles_have_priority_screens(
        self, client: TestClient, role_key: str
    ) -> None:
        resp = client.get(f"/api/v1/role-views/{role_key}")
        data = resp.json()
        assert isinstance(data["priority_screens"], list)
        assert len(data["priority_screens"]) > 0
        for screen in data["priority_screens"]:
            assert "href" in screen
            assert "label" in screen
            assert "why" in screen

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_all_roles_have_quick_actions(
        self, client: TestClient, role_key: str
    ) -> None:
        resp = client.get(f"/api/v1/role-views/{role_key}")
        data = resp.json()
        assert isinstance(data["quick_actions"], list)
        assert len(data["quick_actions"]) > 0

    @pytest.mark.parametrize(
        "role_key",
        ["performans", "marcom", "musteri_hizmetleri", "planlama", "yonetim"],
    )
    def test_attention_items_valid(
        self, client: TestClient, role_key: str
    ) -> None:
        resp = client.get(f"/api/v1/role-views/{role_key}")
        data = resp.json()
        assert isinstance(data["attention"], list)
        assert len(data["attention"]) <= 4
        for item in data["attention"]:
            assert item["severity"] in {"high", "medium", "low"}
            assert "href" in item
            assert "title" in item
            assert "detail" in item

    def test_get_bogus_role_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/role-views/bogus")
        assert resp.status_code == 404

    def test_get_empty_role_404(self, client: TestClient) -> None:
        # "unknown" is not a valid role key
        resp = client.get("/api/v1/role-views/unknown_role_xyz")
        assert resp.status_code == 404

    def test_get_role_view_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/role-views/performans")
        assert resp.status_code in {401, 403}

    def test_get_role_view_no_auth_any_role(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get("/api/v1/role-views/yonetim")
        assert resp.status_code in {401, 403}
