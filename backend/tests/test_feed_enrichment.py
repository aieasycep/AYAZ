"""AI Product Enrichment tests — Dalga 49.

Strategy
--------
* All tests run WITHOUT an ANTHROPIC_API_KEY → deterministic heuristics only.
* FastAPI TestClient + in-memory SQLite (same pattern as test_feed_rule_from_text.py).
* suggest_enrichment is also tested as a pure function with no HTTP/DB.

Coverage
--------
1. Pure heuristic function: color, brand, category, material, title cleanup.
2. suggest_enrichment skips fields that already have a value.
3. suggest_enrichment returns empty list when no products / no eligible fields.
4. POST /sources/{source_id}/enrich — suggestions only; nothing persisted.
5. POST /sources/{source_id}/enrich/apply — writes only approved values,
   leaves unapproved fields untouched; re-reading the product shows them.
6. Both endpoints require auth (401 without token).
7. Both endpoints enforce tenant isolation (404 for wrong tenant's source).
8. apply with empty approvals returns applied_count=0.
9. apply with product_id not in source is silently skipped.
"""

from __future__ import annotations

import secrets as _secrets
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# Register all models on Base.metadata
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.feeds import FeedProduct, FeedSource
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import feeds as feeds_module
from ayaz.services.auth import hash_password
from ayaz.services.feed_enrichment import (
    suggest_enrichment,
    _extract_color,
    _extract_brand,
    _extract_category,
    _extract_material,
    _clean_title,
)

# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Feed Enrichment Test App")
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


def _seed_tenant_user(db: Session, suffix: str = "") -> tuple[Tenant, User, Membership]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"Enrich Test Tenant {suffix}",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email=f"enrich_{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Enrich Test User",
    )
    db.add(tenant)
    db.add(user)
    db.flush()
    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.commit()
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
    """TestClient with NO dependency overrides — membership dep will raise 401."""
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c


# ── ORM seed helpers ──────────────────────────────────────────────────────────


def _make_source(db: Session, tenant_id: uuid.UUID) -> FeedSource:
    src = FeedSource(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Enrich Test Source",
        source_type="upload",
        status="ok",
        item_count=0,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _seed_product(db: Session, source: FeedSource, data: dict, ext_id: str | None = None) -> FeedProduct:
    fp = FeedProduct(
        id=uuid.uuid4(),
        tenant_id=source.tenant_id,
        feed_source_id=source.id,
        external_id=ext_id or uuid.uuid4().hex,
        data=data,
    )
    db.add(fp)
    db.commit()
    db.refresh(fp)
    return fp


# ── Pure heuristic unit tests (no HTTP, no DB) ────────────────────────────────


class TestHeuristics:
    """Test the individual heuristic extractors directly."""

    # color
    def test_extract_color_turkish(self):
        assert _extract_color("Siyah Deri Kemer") == "Siyah"

    def test_extract_color_english(self):
        assert _extract_color("Blue Cotton T-Shirt") == "Mavi"

    def test_extract_color_mixed(self):
        assert _extract_color("Nike beyaz Spor Ayakkabı") == "Beyaz"

    def test_extract_color_none(self):
        assert _extract_color("Ahşap Masa") is None

    def test_extract_color_lacivert(self):
        assert _extract_color("Lacivert Kaban") == "Lacivert"

    def test_extract_color_grey(self):
        assert _extract_color("grey hoodie") == "Gri"

    # brand
    def test_extract_brand_title_case(self):
        assert _extract_brand("Nike Erkek Koşu Ayakkabısı") == "Nike"

    def test_extract_brand_all_caps(self):
        assert _extract_brand("ADIDAS Spor Şort") == "ADIDAS"

    def test_extract_brand_none_for_lowercase(self):
        # A purely lowercase first word should not be suggested
        assert _extract_brand("pamuklu tişört") is None

    def test_extract_brand_none_for_common_word(self):
        assert _extract_brand("Yeni Model Laptop") is None

    def test_extract_brand_none_for_number(self):
        assert _extract_brand("123 Widget") is None

    # category
    def test_extract_category_shoe(self):
        assert _extract_category("Erkek Spor Ayakkabı Nike") == "Giyim > Ayakkabı"

    def test_extract_category_phone(self):
        assert _extract_category("Samsung telefon kılıfı") == "Elektronik > Telefon Aksesuarları"

    def test_extract_category_laptop(self):
        assert _extract_category("Apple laptop bilgisayar") == "Elektronik > Bilgisayarlar"

    def test_extract_category_clothing(self):
        assert _extract_category("Kadın Elbise Yazlık") == "Giyim > Elbise"

    def test_extract_category_none(self):
        assert _extract_category("12345") is None

    # material
    def test_extract_material_turkish(self):
        assert _extract_material("Pamuk Tişört") == "Pamuk"

    def test_extract_material_english(self):
        assert _extract_material("Genuine leather wallet") == "Deri"

    def test_extract_material_metal(self):
        assert _extract_material("Metal çerçeveli gözlük") == "Metal"

    def test_extract_material_none(self):
        assert _extract_material("Fırça modeli kalem") is None

    # title cleanup
    def test_clean_title_double_space(self):
        assert _clean_title("Nike  Spor  Ayakkabı") == "Nike Spor Ayakkabı"

    def test_clean_title_trim(self):
        assert _clean_title("  Nike Ayakkabı  ") == "Nike Ayakkabı"

    def test_clean_title_all_caps(self):
        result = _clean_title("NIKE SPOR AYAKKABI")
        assert result is not None
        assert result != "NIKE SPOR AYAKKABI"
        # Should be title-cased
        assert result[0].isupper()

    def test_clean_title_no_change(self):
        assert _clean_title("Nike Spor Ayakkabı") is None

    def test_clean_title_empty(self):
        assert _clean_title("") is None


class TestSuggestEnrichment:
    """Test the pure suggest_enrichment function."""

    def test_color_suggestion_when_empty(self):
        products = [{"id": "1", "title": "Siyah Deri Cüzdan", "color": ""}]
        result = suggest_enrichment(products, ["color"])
        assert len(result["suggestions"]) == 1
        s = result["suggestions"][0]
        assert s["field"] == "color"
        assert s["suggested"] == "Siyah"
        assert s["source"] == "heuristic"

    def test_no_suggestion_when_field_already_filled(self):
        products = [{"id": "1", "title": "Siyah Deri Cüzdan", "color": "Siyah"}]
        result = suggest_enrichment(products, ["color"])
        assert result["suggestions"] == []

    def test_brand_suggestion_low_confidence(self):
        products = [{"id": "1", "title": "Nike Erkek Koşu Ayakkabısı", "brand": ""}]
        result = suggest_enrichment(products, ["brand"])
        assert len(result["suggestions"]) == 1
        s = result["suggestions"][0]
        assert s["field"] == "brand"
        assert s["suggested"] == "Nike"
        assert s["confidence"] == "low"

    def test_category_suggestion(self):
        products = [{"id": "1", "title": "Erkek Ayakkabı Spor", "category": ""}]
        result = suggest_enrichment(products, ["category"])
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["field"] == "category"

    def test_material_suggestion(self):
        products = [{"id": "1", "title": "Pamuk Tişört", "material": ""}]
        result = suggest_enrichment(products, ["material"])
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["suggested"] == "Pamuk"

    def test_title_cleanup_suggestion(self):
        products = [{"id": "1", "title": "Nike  Spor  Ayakkabı"}]
        result = suggest_enrichment(products, ["title"])
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["suggested"] == "Nike Spor Ayakkabı"

    def test_empty_products_returns_empty(self):
        result = suggest_enrichment([], ["color", "brand"])
        assert result["suggestions"] == []

    def test_no_eligible_fields_returns_empty(self):
        # All fields filled
        products = [{"id": "1", "title": "T", "color": "Mavi", "brand": "Nike"}]
        result = suggest_enrichment(products, ["color", "brand"])
        assert result["suggestions"] == []

    def test_multiple_products_multiple_fields(self):
        products = [
            {"id": "1", "title": "Siyah Deri Çanta", "color": "", "brand": ""},
            {"id": "2", "title": "Beyaz Pamuk Tişört", "color": "", "material": ""},
        ]
        result = suggest_enrichment(
            products, ["color", "brand", "material"],
            product_ids=["p1", "p2"],
        )
        pids = {s["product_id"] for s in result["suggestions"]}
        fields = {s["field"] for s in result["suggestions"]}
        # p1 should have color + brand suggestions, p2 color + material
        assert "p1" in pids
        assert "p2" in pids
        assert "color" in fields

    def test_deduplicated_suggestions(self):
        # Same product_id + field should only appear once
        products = [{"id": "1", "title": "Siyah Siyah Ürün", "color": ""}]
        result = suggest_enrichment(products, ["color"])
        color_suggestions = [s for s in result["suggestions"] if s["field"] == "color"]
        assert len(color_suggestions) == 1

    def test_unknown_field_ignored(self):
        products = [{"id": "1", "title": "Siyah Çanta", "color": ""}]
        # "nonexistent" is not in ENRICHABLE_FIELDS and should be silently ignored
        result = suggest_enrichment(products, ["color", "nonexistent"])
        fields = {s["field"] for s in result["suggestions"]}
        assert "nonexistent" not in fields

    def test_product_ids_are_used(self):
        products = [{"title": "Siyah Çanta"}]
        result = suggest_enrichment(products, ["color"], product_ids=["custom-id-99"])
        if result["suggestions"]:
            assert result["suggestions"][0]["product_id"] == "custom-id-99"


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


class TestEnrichEndpoint:
    """Integration tests for POST /sources/{source_id}/enrich."""

    def _enrich_url(self, source_id: uuid.UUID) -> str:
        return f"/api/v1/feeds/sources/{source_id}/enrich"

    def test_auth_required(self, client_no_auth: TestClient):
        resp = client_no_auth.post(
            self._enrich_url(uuid.uuid4()),
            json={"fields": ["color"]},
        )
        assert resp.status_code == 401

    def test_source_not_found(self, client: TestClient):
        resp = client.post(
            self._enrich_url(uuid.uuid4()),
            json={"fields": ["color"]},
        )
        assert resp.status_code == 404

    def test_tenant_isolation_404(self, db_session: Session):
        """Source belonging to tenant A is 404 when accessed via tenant B."""
        tenant_a, _, _ = _seed_tenant_user(db_session, "EnrichIsoA")
        _, _, membership_b = _seed_tenant_user(db_session, "EnrichIsoB")
        source_a = _make_source(db_session, tenant_a.id)

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
                    self._enrich_url(source_a.id),
                    json={"fields": ["color"]},
                )
            assert resp.status_code == 404
        finally:
            _test_app.dependency_overrides.clear()

    def test_nothing_persisted(self, client: TestClient, db_session: Session):
        """Enrichment suggest endpoint must not modify any FeedProduct rows."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Persist Test Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])

        # Seed a product directly
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        fp = _seed_product(db_session, src_row, {"title": "Siyah Deri Çanta", "color": ""})
        data_before = dict(fp.data)

        resp = client.post(
            self._enrich_url(src_id),
            json={"fields": ["color", "brand"]},
        )
        assert resp.status_code == 200

        # Re-read from DB
        db_session.expire(fp)
        fp_after = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp.id))
        assert fp_after.data == data_before, "enrich endpoint must not persist anything"

    def test_returns_suggestions(self, client: TestClient, db_session: Session):
        """Suggestions are returned for products with empty fields."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Suggest Test", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        _seed_product(db_session, src_row, {"title": "Siyah Deri Çanta", "color": ""})
        _seed_product(db_session, src_row, {"title": "Mavi Pamuk Tişört", "color": ""})

        resp = client.post(
            self._enrich_url(src_id),
            json={"fields": ["color", "material"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "suggestions" in body
        assert "sampled" in body
        # We should have color suggestions for both products
        color_suggestions = [s for s in body["suggestions"] if s["field"] == "color"]
        assert len(color_suggestions) >= 1
        # Each suggestion has the required keys
        for s in body["suggestions"]:
            for key in ("product_id", "field", "current", "suggested", "confidence", "source"):
                assert key in s, f"Missing key '{key}' in suggestion"

    def test_empty_source_returns_empty_suggestions(self, client: TestClient):
        """No products → empty suggestions, no crash."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Empty Source", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]

        resp = client.post(
            self._enrich_url(uuid.UUID(src_id)),
            json={"fields": ["color", "brand"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["suggestions"] == []

    def test_filled_fields_not_suggested(self, client: TestClient, db_session: Session):
        """Products with existing color values must not appear in suggestions."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Full Color Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        _seed_product(db_session, src_row, {"title": "Siyah Çanta", "color": "Siyah"})

        resp = client.post(
            self._enrich_url(src_id),
            json={"fields": ["color"]},
        )
        assert resp.status_code == 200
        color_suggestions = [s for s in resp.json()["suggestions"] if s["field"] == "color"]
        assert color_suggestions == []

    def test_invalid_field_rejected(self, client: TestClient, db_session: Session):
        """Unknown fields in the request body should return 422."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Invalid Field Source", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]

        resp = client.post(
            self._enrich_url(uuid.UUID(src_id)),
            json={"fields": ["nonexistent_field"]},
        )
        assert resp.status_code == 422


class TestEnrichApplyEndpoint:
    """Integration tests for POST /sources/{source_id}/enrich/apply."""

    def _apply_url(self, source_id: uuid.UUID) -> str:
        return f"/api/v1/feeds/sources/{source_id}/enrich/apply"

    def test_auth_required(self, client_no_auth: TestClient):
        resp = client_no_auth.post(
            self._apply_url(uuid.uuid4()),
            json={"approvals": []},
        )
        assert resp.status_code == 401

    def test_source_not_found(self, client: TestClient):
        resp = client.post(
            self._apply_url(uuid.uuid4()),
            json={"approvals": []},
        )
        assert resp.status_code == 404

    def test_tenant_isolation_404(self, db_session: Session):
        """Source belonging to tenant A is 404 when apply is attempted from tenant B."""
        tenant_a, _, _ = _seed_tenant_user(db_session, "ApplyIsoA")
        _, _, membership_b = _seed_tenant_user(db_session, "ApplyIsoB")
        source_a = _make_source(db_session, tenant_a.id)
        fp_a = _seed_product(db_session, source_a, {"title": "Test"})

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
                    self._apply_url(source_a.id),
                    json={"approvals": [{"product_id": str(fp_a.id), "field": "color", "value": "Siyah"}]},
                )
            assert resp.status_code == 404
        finally:
            _test_app.dependency_overrides.clear()

    def test_apply_writes_approved_values(self, client: TestClient, db_session: Session):
        """Approved values are written into FeedProduct.data."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Apply Test Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        fp = _seed_product(db_session, src_row, {"title": "Siyah Deri Çanta", "color": ""})

        resp = client.post(
            self._apply_url(src_id),
            json={"approvals": [{"product_id": str(fp.id), "field": "color", "value": "Siyah"}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied_count"] == 1

        # Re-read and confirm the value was written
        db_session.expire(fp)
        fp_refreshed = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp.id))
        assert fp_refreshed.data["color"] == "Siyah"

    def test_apply_does_not_clobber_other_fields(self, client: TestClient, db_session: Session):
        """Approving color must not touch title, brand, or other keys."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "No Clobber Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        fp = _seed_product(
            db_session, src_row,
            {"title": "Nike Siyah Ayakkabı", "brand": "Nike", "price": "499.99", "color": ""},
        )

        client.post(
            self._apply_url(src_id),
            json={"approvals": [{"product_id": str(fp.id), "field": "color", "value": "Siyah"}]},
        )

        db_session.expire(fp)
        fp_refreshed = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp.id))
        assert fp_refreshed.data["brand"] == "Nike"
        assert fp_refreshed.data["price"] == "499.99"
        assert fp_refreshed.data["title"] == "Nike Siyah Ayakkabı"
        assert fp_refreshed.data["color"] == "Siyah"

    def test_apply_only_approved_fields(self, client: TestClient, db_session: Session):
        """Only explicitly approved (product, field) pairs are written.

        If the call suggests color and brand but only color is approved, brand
        must remain empty on the product.
        """
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Selective Apply Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        fp = _seed_product(
            db_session, src_row,
            {"title": "Nike Siyah Koşu Ayakkabısı", "color": "", "brand": ""},
        )

        # Only approve color, NOT brand
        resp = client.post(
            self._apply_url(src_id),
            json={"approvals": [{"product_id": str(fp.id), "field": "color", "value": "Siyah"}]},
        )
        assert resp.json()["applied_count"] == 1

        db_session.expire(fp)
        fp_refreshed = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp.id))
        assert fp_refreshed.data["color"] == "Siyah"
        # brand was NOT approved, so it remains as it was (empty string)
        assert fp_refreshed.data.get("brand", "") == ""

    def test_apply_empty_approvals_returns_zero(self, client: TestClient, db_session: Session):
        """Empty approvals list returns applied_count=0."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Empty Apply Source", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]

        resp = client.post(
            self._apply_url(uuid.UUID(src_id)),
            json={"approvals": []},
        )
        assert resp.status_code == 200
        assert resp.json()["applied_count"] == 0

    def test_apply_skips_unknown_product_id(self, client: TestClient, db_session: Session):
        """Approvals referencing a product_id not in the source are silently skipped."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Skip Unknown Source", "source_type": "upload"},
        )
        src_id = resp_src.json()["id"]

        resp = client.post(
            self._apply_url(uuid.UUID(src_id)),
            json={"approvals": [{"product_id": str(uuid.uuid4()), "field": "color", "value": "Mavi"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["applied_count"] == 0

    def test_apply_multiple_products_and_fields(self, client: TestClient, db_session: Session):
        """Multiple approvals across multiple products all applied in one call."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Multi Apply Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))

        fp1 = _seed_product(db_session, src_row, {"title": "Siyah Çanta", "color": "", "brand": ""})
        fp2 = _seed_product(db_session, src_row, {"title": "Mavi Tişört", "color": "", "material": ""})

        resp = client.post(
            self._apply_url(src_id),
            json={
                "approvals": [
                    {"product_id": str(fp1.id), "field": "color", "value": "Siyah"},
                    {"product_id": str(fp1.id), "field": "brand", "value": "TestBrand"},
                    {"product_id": str(fp2.id), "field": "color", "value": "Mavi"},
                    {"product_id": str(fp2.id), "field": "material", "value": "Pamuk"},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["applied_count"] == 4

        for fp in (fp1, fp2):
            db_session.expire(fp)
        fp1_r = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp1.id))
        fp2_r = db_session.scalar(select(FeedProduct).where(FeedProduct.id == fp2.id))
        assert fp1_r.data["color"] == "Siyah"
        assert fp1_r.data["brand"] == "TestBrand"
        assert fp2_r.data["color"] == "Mavi"
        assert fp2_r.data["material"] == "Pamuk"

    def test_apply_unenrichable_field_is_skipped(self, client: TestClient, db_session: Session):
        """Approvals for fields not in ENRICHABLE_FIELDS are silently skipped."""
        resp_src = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Bad Field Source", "source_type": "upload"},
        )
        src_id = uuid.UUID(resp_src.json()["id"])
        src_row = db_session.scalar(select(FeedSource).where(FeedSource.id == src_id))
        fp = _seed_product(db_session, src_row, {"title": "Test"})

        resp = client.post(
            self._apply_url(src_id),
            json={"approvals": [{"product_id": str(fp.id), "field": "not_a_real_field", "value": "X"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["applied_count"] == 0
