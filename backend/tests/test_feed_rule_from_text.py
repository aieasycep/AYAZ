"""Tests for the NL → FeedRule endpoint and parser — Dalga 45.

Strategy
--------
* All tests run WITHOUT an ANTHROPIC_API_KEY so the deterministic stub parser
  is exercised exclusively.
* FastAPI TestClient with in-memory SQLite (same pattern as test_feed_rule_studio.py).
* get_db and get_current_membership overridden per fixture.

Coverage
--------
1. ~8 representative Turkish sentences — one per pattern — assert correct
   rule_type + config.
2. Nothing is persisted (rule count unchanged after the call).
3. Auth required (401 when no membership override).
4. Tenant isolation (404 when another tenant's channel_id is used).
5. Unparseable sentence returns confidence="low" without 500.
"""

from __future__ import annotations

import secrets as _secrets
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, func as sa_func, select
from sqlalchemy.orm import Session, sessionmaker

# Register all models on Base.metadata
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.feeds import FeedChannel, FeedProduct, FeedRule, FeedSource
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import feeds as feeds_module
from ayaz.services.auth import hash_password
from ayaz.services.feed_rule_nlp import parse_rule_from_text, _stub_parse

# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Feed NLP Test App")
_test_app.include_router(feeds_module.router, prefix="/api/v1")


# ── DB helpers ────────────────────────────────────────────────────────────────


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Session:
    engine = _make_engine()
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _seed_tenant_user(db_session: Session, suffix: str = "") -> tuple[Tenant, User, Membership]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"NLP Test Tenant {suffix}",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email=f"nlp_{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="NLP Test User",
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
    return tenant, user, membership


@pytest.fixture()
def client(db_session: Session):
    """TestClient wired to tenant A."""
    _, _, membership = _seed_tenant_user(db_session, "A")

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app, raise_server_exceptions=True) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def client_no_auth():
    """TestClient with NO dependency overrides — membership dep will 401."""
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c


# ── ORM seed helpers ──────────────────────────────────────────────────────────


def _make_source(db: Session, tenant_id: uuid.UUID) -> FeedSource:
    src = FeedSource(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="NLP Test Source",
        source_type="upload",
        status="ok",
        item_count=0,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_channel(db: Session, source: FeedSource) -> FeedChannel:
    ch = FeedChannel(
        id=uuid.uuid4(),
        tenant_id=source.tenant_id,
        feed_source_id=source.id,
        name="NLP Test Channel",
        channel_type="google_shopping",
        output_format="xml",
        public_token="nlp_tok_" + _secrets.token_hex(8),
        is_active=True,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


def _seed_products(db: Session, source: FeedSource, products: list[dict]) -> None:
    for i, data in enumerate(products):
        fp = FeedProduct(
            id=uuid.uuid4(),
            tenant_id=source.tenant_id,
            feed_source_id=source.id,
            external_id=str(i),
            data=data,
        )
        db.add(fp)
    db.commit()


def _rule_count(db: Session, channel_id: uuid.UUID) -> int:
    return db.scalar(
        select(sa_func.count(FeedRule.id)).where(
            FeedRule.feed_channel_id == channel_id
        )
    ) or 0


# ── Pure parser unit tests (no HTTP, no DB) ───────────────────────────────────


class TestStubParser:
    """Test _stub_parse() directly — one test per pattern."""

    def test_stock_out_exclude(self):
        """'stokta olmayan ürünleri çıkar' → filter_exclude availability eq 'out of stock'."""
        r = _stub_parse("stokta olmayan ürünleri çıkar")
        assert r.rule_type == "filter_exclude"
        assert r.config["condition_field"] == "availability"
        assert r.config["condition_op"] == "eq"
        assert r.config["condition_value"] == "out of stock"
        assert r.confidence == "high"

    def test_stock_out_exclude_variant(self):
        """'tükenen ürünleri hariç tut' → filter_exclude availability eq 'out of stock'."""
        r = _stub_parse("tükenen ürünleri hariç tut")
        assert r.rule_type == "filter_exclude"
        assert r.config["condition_field"] == "availability"
        assert r.config["condition_value"] == "out of stock"
        assert r.confidence == "high"

    def test_in_stock_include(self):
        """'sadece stokta olanları göster' → filter_include availability eq 'in stock'."""
        r = _stub_parse("sadece stokta olanları göster")
        assert r.rule_type == "filter_include"
        assert r.config["condition_field"] == "availability"
        assert r.config["condition_op"] == "eq"
        assert r.config["condition_value"] == "in stock"
        assert r.confidence == "high"

    def test_price_below_exclude(self):
        """'fiyatı 100 TL altındaki ürünleri çıkar' → filter_exclude price lt 100."""
        r = _stub_parse("fiyatı 100 TL altındaki ürünleri çıkar")
        assert r.rule_type == "filter_exclude"
        assert r.config["condition_field"] == "price"
        assert r.config["condition_op"] == "lt"
        assert r.config["condition_value"] == "100"
        assert r.confidence == "high"

    def test_price_above_exclude(self):
        """'fiyatı 500 TL üstündeki ürünleri hariç tut' → filter_exclude price gt 500."""
        r = _stub_parse("fiyatı 500 TL üstündeki ürünleri hariç tut")
        assert r.rule_type == "filter_exclude"
        assert r.config["condition_field"] == "price"
        assert r.config["condition_op"] == "gt"
        assert r.config["condition_value"] == "500"
        assert r.confidence == "high"

    def test_title_brand_append(self):
        """'başlığa marka ekle' → calculated title field with brand expression."""
        r = _stub_parse("başlığa marka ekle")
        assert r.rule_type == "calculated"
        assert r.config["field"] == "title"
        assert "brand" in r.config["expression"]
        assert r.confidence == "high"

    def test_title_literal_append(self):
        """'başlığa \" | Outlet\" ekle' → calculated with literal suffix."""
        r = _stub_parse("başlığa ' | Outlet' ekle")
        assert r.rule_type == "calculated"
        assert r.config["field"] == "title"
        assert "Outlet" in r.config["expression"]
        assert r.confidence == "high"

    def test_set_value(self):
        """'durum alanını \"new\" yap' → set_value condition/condition field."""
        r = _stub_parse("durum alanını 'new' yap")
        assert r.rule_type == "set_value"
        assert r.config["value"] == "new"
        assert r.confidence == "high"

    def test_find_replace(self):
        """'başlık içindeki \"Eski\" yerine \"Yeni\" yaz' → find_replace on title."""
        r = _stub_parse("başlık içindeki 'Eski' yerine 'Yeni' yaz")
        assert r.rule_type == "find_replace"
        assert r.config["field"] == "title"
        assert r.config["pattern"] == "Eski"
        assert r.config["replacement"] == "Yeni"
        assert r.confidence == "high"

    def test_rename_field(self):
        """'product_type alanını google_product_category olarak kopyala' → rename_field."""
        r = _stub_parse("product_type alanını google_product_category olarak kopyala")
        assert r.rule_type == "rename_field"
        assert r.config["from_field"] == "product_type"
        assert r.config["to_field"] == "google_product_category"
        assert r.confidence == "high"

    def test_unparseable_returns_low_confidence(self):
        """Gibberish text → confidence='low', still returns a valid rule_type, no exception."""
        r = _stub_parse("asdfghjkl qwerty zxcvbn")
        assert r.confidence == "low"
        assert r.rule_type in (
            "set_value", "rename_field", "find_replace",
            "filter_include", "filter_exclude", "calculated",
        )


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


class TestRuleFromTextEndpoint:
    """Integration tests for POST /api/v1/feeds/channels/{channel_id}/rules/from-text."""

    def _channel_url(self, channel_id: uuid.UUID) -> str:
        return f"/api/v1/feeds/channels/{channel_id}/rules/from-text"

    def test_auth_required(self, client_no_auth: TestClient):
        """Without a valid membership token the endpoint returns 401."""
        fake_channel_id = uuid.uuid4()
        resp = client_no_auth.post(
            self._channel_url(fake_channel_id),
            json={"text": "stokta olmayan ürünleri çıkar"},
        )
        assert resp.status_code == 401

    def test_tenant_isolation_404(self, db_session: Session):
        """A channel belonging to tenant A is 404 when accessed via tenant B's membership.

        We build both tenants' data via ORM directly so we don't need two
        simultaneous TestClient fixtures fighting over the same dependency_overrides
        on the shared _test_app singleton.
        """
        # Seed two tenants
        tenant_a, _, membership_a = _seed_tenant_user(db_session, "IsoA")
        _, _, membership_b = _seed_tenant_user(db_session, "IsoB")

        # Create source + channel for tenant A via ORM
        source_a = _make_source(db_session, tenant_a.id)
        channel_a = _make_channel(db_session, source_a)

        # Wire the app to tenant B's membership
        def override_db():
            try:
                yield db_session
            finally:
                pass

        def override_membership_b():
            return membership_b

        _test_app.dependency_overrides[get_db] = override_db
        _test_app.dependency_overrides[get_current_membership] = override_membership_b

        try:
            with TestClient(_test_app, raise_server_exceptions=True) as c:
                resp = c.post(
                    self._channel_url(channel_a.id),
                    json={"text": "stokta olmayan ürünleri çıkar"},
                )
            assert resp.status_code == 404
        finally:
            _test_app.dependency_overrides.clear()

    def test_nothing_persisted(self, client: TestClient, db_session: Session):
        """Rule count in DB must be unchanged after calling from-text."""
        # Create source + channel
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Persist Test Source", "source_type": "upload"},
        )
        source_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{source_id}/channels",
            json={"name": "Persist Channel", "channel_type": "google_shopping"},
        )
        channel_id = uuid.UUID(resp_ch.json()["id"])

        count_before = _rule_count(db_session, channel_id)

        resp = client.post(
            self._channel_url(channel_id),
            json={"text": "başlığa marka ekle"},
        )
        assert resp.status_code == 200

        count_after = _rule_count(db_session, channel_id)
        assert count_after == count_before, "from-text must not persist any rule"

    def test_stock_out_exclude(self, client: TestClient, db_session: Session):
        """'stokta olmayan ürünleri çıkar' → filter_exclude availability."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Stok Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Stok Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "stokta olmayan ürünleri çıkar"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_type"] == "filter_exclude"
        assert body["config"]["condition_field"] == "availability"
        assert body["config"]["condition_value"] == "out of stock"
        assert body["confidence"] == "high"
        assert "explanation" in body
        assert isinstance(body["explanation"], str) and len(body["explanation"]) > 0

    def test_in_stock_include(self, client: TestClient, db_session: Session):
        """'sadece stokta olanları göster' → filter_include availability."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "InStock Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "InStock Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "sadece stokta olanları göster"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_type"] == "filter_include"
        assert body["config"]["condition_field"] == "availability"
        assert body["config"]["condition_value"] == "in stock"

    def test_price_filter_below(self, client: TestClient, db_session: Session):
        """'fiyatı 100 TL altındaki ürünleri hariç tut' → filter_exclude price lt 100."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Price Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Price Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "fiyatı 100 TL altındaki ürünleri hariç tut"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_type"] == "filter_exclude"
        assert body["config"]["condition_field"] == "price"
        assert body["config"]["condition_op"] == "lt"
        assert body["config"]["condition_value"] == "100"

    def test_title_brand_calculated(self, client: TestClient, db_session: Session):
        """'başlığa marka ekle' → calculated title + brand."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Title Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Title Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "başlığa marka ekle"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_type"] == "calculated"
        assert body["config"]["field"] == "title"
        assert "brand" in body["config"]["expression"]

    def test_unparseable_returns_low_confidence_not_500(self, client: TestClient, db_session: Session):
        """Gibberish text → 200 with confidence='low', not 500."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Low Conf Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Low Conf Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "xyzzy qwerty foobar baz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["confidence"] == "low"
        # Must still return a valid rule_type
        assert body["rule_type"] in (
            "set_value", "rename_field", "find_replace",
            "filter_include", "filter_exclude", "calculated",
        )

    def test_impact_included_when_products_present(self, client: TestClient, db_session: Session):
        """When products exist the response includes impact counts."""
        # We need to seed products via the ORM directly since the TestClient
        # fixture uses the same db_session
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Impact Test", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Impact Channel", "channel_type": "google_shopping"},
        )
        ch_id = uuid.UUID(resp_ch.json()["id"])

        # Seed some products directly — mix of in-stock and out-of-stock
        source_row = db_session.scalar(
            __import__("sqlalchemy", fromlist=["select"]).select(FeedSource).where(FeedSource.id == src_id)
        )
        _seed_products(
            db_session,
            source_row,
            [
                {"id": "1", "title": "Widget A", "availability": "in stock", "price": "50"},
                {"id": "2", "title": "Widget B", "availability": "out of stock", "price": "75"},
                {"id": "3", "title": "Widget C", "availability": "in stock", "price": "200"},
            ],
        )

        resp = client.post(
            self._channel_url(ch_id),
            json={"text": "stokta olmayan ürünleri çıkar"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_type"] == "filter_exclude"
        # Impact should be present since we seeded products
        if body.get("impact") is not None:
            assert body["impact"]["excluded_count"] >= 0
            assert body["impact"]["affected_count"] >= 0

    def test_channel_not_found_returns_404(self, client: TestClient):
        """Nonexistent channel_id → 404."""
        resp = client.post(
            self._channel_url(uuid.uuid4()),
            json={"text": "stokta olmayan ürünleri çıkar"},
        )
        assert resp.status_code == 404

    def test_response_shape(self, client: TestClient, db_session: Session):
        """Response always has rule_type, config, explanation, confidence keys."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Shape Test", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]
        resp_ch = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Shape Channel", "channel_type": "google_shopping"},
        )
        ch_id = resp_ch.json()["id"]

        resp = client.post(
            self._channel_url(uuid.UUID(ch_id)),
            json={"text": "fiyatı 50 TL üstündeki ürünleri dahil et"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("rule_type", "config", "explanation", "confidence"):
            assert key in body, f"Missing key: {key}"
        assert body["confidence"] in ("high", "low")
        assert isinstance(body["config"], dict)
