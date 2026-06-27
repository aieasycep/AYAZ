"""Feed Quality Gate tests — Dalga 48.

Covers:
  1. Pure compute_feed_quality function:
     - products with missing required fields → correct issue codes + affected_count
     - duplicate ids → duplicate_id error
     - title too long → title_too_long warning (google_shopping only)
     - invalid price → invalid_price error
     - clean product set → score 100, no errors
     - empty feed → score 0, empty_feed info, no crash
     - channel-kind spec dispatch (google_shopping / meta_catalog / generic)
  2. HTTP endpoint GET /feeds/channels/{channel_id}/quality:
     - 404 on unknown channel (tenant isolation)
     - 401 without auth
     - 404 when another tenant tries to access the channel
     - correct score when products have issues vs. all clean
     - sampled flag absent when total <= 1000
  3. Rules are applied before quality check (rules affect score).

Strategy
--------
* FastAPI TestClient with in-memory SQLite (same pattern as test_feed_rule_studio.py).
* Pure-function tests exercise compute_feed_quality directly.
* HTTP tests use the same fixture / override pattern.
"""

from __future__ import annotations

import uuid
import secrets as _secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata is complete
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
from ayaz.services.feeds import compute_feed_quality


# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Feed Quality Gate Test App")
_test_app.include_router(feeds_module.router, prefix="/api/v1")


# ── Shared DB engine ──────────────────────────────────────────────────────────


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


def _seed_tenant_user(db: Session) -> tuple[Tenant, User, Membership]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"QualityTenant_{uuid.uuid4().hex[:6]}",
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email=f"quality_{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Quality User",
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
    _, _, membership = _seed_tenant_user(db_session)

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
    with TestClient(_test_app, raise_server_exceptions=True) as c:
        yield c


# ── ORM helpers ───────────────────────────────────────────────────────────────


def _make_source(db: Session, tenant_id: uuid.UUID) -> FeedSource:
    src = FeedSource(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Quality Source",
        source_type="upload",
        status="ok",
        item_count=0,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_channel(
    db: Session,
    source: FeedSource,
    channel_type: str = "google_shopping",
) -> FeedChannel:
    ch = FeedChannel(
        id=uuid.uuid4(),
        tenant_id=source.tenant_id,
        feed_source_id=source.id,
        name="Quality Channel",
        channel_type=channel_type,
        output_format="xml",
        public_token="quality_tok_" + _secrets.token_hex(8),
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
            external_id=f"ext_{i}_{uuid.uuid4().hex[:4]}",
            data=data,
        )
        db.add(fp)
    db.commit()


def _make_rule(
    db: Session,
    channel: FeedChannel,
    rule_type: str,
    config: dict,
    position: int = 0,
    is_paused: bool = False,
) -> FeedRule:
    rule = FeedRule(
        id=uuid.uuid4(),
        tenant_id=channel.tenant_id,
        feed_channel_id=channel.id,
        rule_type=rule_type,
        config=config,
        position=position,
        is_paused=is_paused,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _make_isolated_client(db: Session, membership: Membership) -> TestClient:
    """Build a TestClient scoped to a specific membership for isolation tests."""
    app = FastAPI()
    app.include_router(feeds_module.router, prefix="/api/v1")

    def override_db():
        try:
            yield db
        finally:
            pass

    _cap = membership

    def override_membership():
        return _cap

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_membership] = override_membership
    return TestClient(app, raise_server_exceptions=True)


# ── Sample products ────────────────────────────────────────────────────────────

# A fully valid google_shopping product.
_CLEAN_PRODUCT = {
    "id": "P1",
    "title": "Awesome Widget",
    "description": "A great product for your needs.",
    "link": "https://example.com/p1",
    "image_link": "https://example.com/p1.jpg",
    "availability": "in stock",
    "price": "29.99 USD",
    "brand": "Acme",
    "condition": "new",
    "gtin": "012345678901",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure compute_feed_quality tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeFeedQualityPure:
    """Direct tests of the pure service function — no HTTP, no DB."""

    # ── Clean data → score 100 ────────────────────────────────────────────────

    def test_all_clean_score_100_google_shopping(self) -> None:
        products = [dict(_CLEAN_PRODUCT, id=f"P{i}") for i in range(5)]
        result = compute_feed_quality(products, "google_shopping")
        assert result["score"] == 100
        assert result["total"] == 5
        assert result["valid"] == 5
        # No error-severity issues
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert errors == []

    def test_all_clean_score_100_meta_catalog(self) -> None:
        products = [
            {
                "id": f"M{i}",
                "title": "Meta Product",
                "description": "Desc",
                "availability": "in stock",
                "condition": "new",
                "price": "9.99",
                "link": "https://example.com",
                "image_link": "https://example.com/img.jpg",
                "brand": "Acme",
            }
            for i in range(3)
        ]
        result = compute_feed_quality(products, "meta_catalog")
        assert result["score"] == 100
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert errors == []

    # ── Empty feed → score 0, no crash ───────────────────────────────────────

    def test_empty_feed_score_0_no_crash(self) -> None:
        result = compute_feed_quality([], "google_shopping")
        assert result["score"] == 0
        assert result["total"] == 0
        assert result["valid"] == 0
        assert len(result["issues"]) == 1
        assert result["issues"][0]["code"] == "empty_feed"
        assert result["issues"][0]["severity"] == "info"

    def test_empty_feed_meta_catalog(self) -> None:
        result = compute_feed_quality([], "meta_catalog")
        assert result["score"] == 0
        assert result["issues"][0]["code"] == "empty_feed"

    def test_empty_feed_unknown_channel_kind(self) -> None:
        result = compute_feed_quality([], "custom")
        assert result["score"] == 0
        assert result["issues"][0]["code"] == "empty_feed"

    # ── Missing required fields ───────────────────────────────────────────────

    def test_missing_title_raises_error(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title=""),
            dict(_CLEAN_PRODUCT, id="P2"),  # clean
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "missing_required_field" in codes
        issue = next(i for i in result["issues"] if i["code"] == "missing_required_field" and i["field"] == "title")
        assert issue["affected_count"] == 1
        assert "P1" in issue["sample_ids"]
        # P1 has an error → valid = 1 out of 2
        assert result["valid"] == 1
        assert result["score"] == 50

    def test_missing_description_raises_error(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", description=""),
            dict(_CLEAN_PRODUCT, id="P2", description="fine"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        errors = [i for i in result["issues"] if i["severity"] == "error" and i["field"] == "description"]
        assert len(errors) == 1
        assert errors[0]["affected_count"] == 1

    def test_missing_image_link_uses_missing_image_code(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", image_link=""),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "missing_image" in codes
        issue = next(i for i in result["issues"] if i["code"] == "missing_image")
        assert issue["severity"] == "error"
        assert issue["affected_count"] == 1

    def test_multiple_missing_fields(self) -> None:
        """A product missing both title and description contributes a single invalid product."""
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title="", description=""),
            dict(_CLEAN_PRODUCT, id="P2"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        # P1 is invalid, P2 is valid
        assert result["valid"] == 1
        assert result["total"] == 2
        assert result["score"] == 50

    def test_all_missing_required_score_0(self) -> None:
        products = [
            {"id": "P1"},  # only id, all other required fields absent
            {"id": "P2"},
        ]
        result = compute_feed_quality(products, "google_shopping")
        # All products have errors → valid = 0
        assert result["valid"] == 0
        assert result["score"] == 0

    # ── Duplicate IDs ─────────────────────────────────────────────────────────

    def test_duplicate_id_detected(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="SAME"),
            dict(_CLEAN_PRODUCT, id="SAME"),
            dict(_CLEAN_PRODUCT, id="UNIQUE"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "duplicate_id" in codes
        dup_issue = next(i for i in result["issues"] if i["code"] == "duplicate_id")
        assert dup_issue["severity"] == "error"
        assert dup_issue["affected_count"] == 2  # 2 products share the same id
        assert "SAME" in dup_issue["sample_ids"]

    def test_no_duplicate_id_when_ids_unique(self) -> None:
        products = [dict(_CLEAN_PRODUCT, id=f"P{i}") for i in range(5)]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "duplicate_id" not in codes

    def test_duplicate_id_marks_product_invalid(self) -> None:
        # 3 products: 2 share the same id (both flagged invalid), 1 clean
        products = [
            dict(_CLEAN_PRODUCT, id="DUP"),
            dict(_CLEAN_PRODUCT, id="DUP"),
            dict(_CLEAN_PRODUCT, id="CLEAN"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        # The 2 duplicates are invalid; CLEAN is valid
        assert result["valid"] == 1
        assert result["score"] == 33  # round(100 * 1/3)

    # ── Invalid price ─────────────────────────────────────────────────────────

    def test_non_numeric_price_flagged(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price="FREE"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "invalid_price" in codes

    def test_zero_price_flagged(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price="0"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "invalid_price" in codes

    def test_negative_price_flagged(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price="-5.00"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "invalid_price" in codes

    def test_valid_price_with_currency_code_ok(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price="19.99 TRY"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "invalid_price" not in codes

    def test_valid_numeric_price_ok(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price="9.99"),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "invalid_price" not in codes

    def test_empty_price_not_double_counted_as_invalid(self) -> None:
        """An empty price is missing_required_field but NOT also invalid_price."""
        products = [
            dict(_CLEAN_PRODUCT, id="P1", price=""),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        # Should have missing_required_field for price, but NOT invalid_price
        assert "invalid_price" not in codes

    # ── Title too long ────────────────────────────────────────────────────────

    def test_title_too_long_google_shopping(self) -> None:
        long_title = "A" * 151  # one over the 150-char limit
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title=long_title),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "title_too_long" in codes
        issue = next(i for i in result["issues"] if i["code"] == "title_too_long")
        assert issue["severity"] == "warning"
        assert issue["affected_count"] == 1

    def test_title_exactly_150_chars_ok(self) -> None:
        title_150 = "A" * 150
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title=title_150),
        ]
        result = compute_feed_quality(products, "google_shopping")
        codes = [i["code"] for i in result["issues"]]
        assert "title_too_long" not in codes

    def test_title_too_long_is_warning_not_error(self) -> None:
        """title_too_long is a warning; a product with ONLY this issue is still valid."""
        long_title = "B" * 200
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title=long_title),
        ]
        result = compute_feed_quality(products, "google_shopping")
        # Only issue is warning; product is still valid
        assert result["valid"] == 1
        assert result["score"] == 100

    def test_title_too_long_not_checked_for_meta_catalog(self) -> None:
        """Meta catalog has no title length limit."""
        long_title = "A" * 500
        products = [
            {
                "id": "M1",
                "title": long_title,
                "description": "Desc",
                "availability": "in stock",
                "condition": "new",
                "price": "9.99",
                "link": "https://example.com",
                "image_link": "https://example.com/img.jpg",
            }
        ]
        result = compute_feed_quality(products, "meta_catalog")
        codes = [i["code"] for i in result["issues"]]
        assert "title_too_long" not in codes

    # ── Missing recommended fields (warnings) ─────────────────────────────────

    def test_missing_brand_is_warning_for_google_shopping(self) -> None:
        products = [
            dict(_CLEAN_PRODUCT, id="P1", brand=""),
        ]
        result = compute_feed_quality(products, "google_shopping")
        rec_issues = [i for i in result["issues"] if i["code"] == "missing_recommended_field"]
        brand_issue = next((i for i in rec_issues if i["field"] == "brand"), None)
        assert brand_issue is not None
        assert brand_issue["severity"] == "warning"

    def test_missing_recommended_does_not_reduce_score(self) -> None:
        """Products missing only recommended fields still count as valid."""
        products = [
            dict(_CLEAN_PRODUCT, id="P1", brand="", condition=""),
        ]
        result = compute_feed_quality(products, "google_shopping")
        assert result["valid"] == 1
        assert result["score"] == 100

    def test_gtin_or_mpn_warning_for_google_shopping(self) -> None:
        """Products missing both gtin and mpn get a warning for google_shopping."""
        product = {k: v for k, v in _CLEAN_PRODUCT.items() if k not in ("gtin", "mpn")}
        product["id"] = "P1"
        result = compute_feed_quality([product], "google_shopping")
        gtin_issues = [
            i for i in result["issues"]
            if i["code"] == "missing_recommended_field" and "gtin" in (i["field"] or "")
        ]
        assert len(gtin_issues) == 1
        assert gtin_issues[0]["severity"] == "warning"

    # ── sample_ids cap ────────────────────────────────────────────────────────

    def test_sample_ids_capped_at_3(self) -> None:
        """Even when 10 products are missing a field, sample_ids has at most 3 entries."""
        products = [
            dict(_CLEAN_PRODUCT, id=f"P{i}", title="") for i in range(10)
        ]
        result = compute_feed_quality(products, "google_shopping")
        title_issue = next(i for i in result["issues"] if i["field"] == "title")
        assert title_issue["affected_count"] == 10
        assert len(title_issue["sample_ids"]) <= 3

    # ── Channel-kind dispatch ─────────────────────────────────────────────────

    def test_generic_channel_requires_only_id_title_link(self) -> None:
        """A 'custom' channel only requires id, title, link."""
        products = [
            {
                "id": "G1",
                "title": "Generic Product",
                "link": "https://example.com/g1",
                # no description, price, image_link — should still be valid
            }
        ]
        result = compute_feed_quality(products, "custom")
        assert result["score"] == 100
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert errors == []

    def test_tiktok_catalog_required_fields(self) -> None:
        # id, title, description, price, availability, image_link, link required
        products = [
            {
                "id": "T1",
                "title": "TikTok Product",
                "description": "Desc",
                "price": "19.99",
                "availability": "in stock",
                "image_link": "https://example.com/t1.jpg",
                "link": "https://example.com/t1",
                "brand": "BrandX",
                "condition": "new",
            }
        ]
        result = compute_feed_quality(products, "tiktok_catalog")
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert errors == []

    def test_tiktok_catalog_missing_description_is_error(self) -> None:
        products = [
            {
                "id": "T1",
                "title": "TikTok Product",
                "description": "",
                "price": "19.99",
                "availability": "in stock",
                "image_link": "https://example.com/t1.jpg",
                "link": "https://example.com/t1",
            }
        ]
        result = compute_feed_quality(products, "tiktok_catalog")
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert any(i["field"] == "description" for i in errors)

    # ── Field alias normalisation ─────────────────────────────────────────────

    def test_g_prefixed_fields_normalised(self) -> None:
        """Products using g: namespace keys (from XML ingestion) are validated correctly."""
        products = [
            {
                "g:id": "GX1",
                "g:title": "XML Product",
                "g:description": "Desc",
                "g:link": "https://example.com/gx1",
                "g:image_link": "https://example.com/gx1.jpg",
                "g:availability": "in stock",
                "g:price": "14.99 USD",
                "g:brand": "BrandX",
                "g:condition": "new",
                "g:gtin": "0123456789012",
            }
        ]
        result = compute_feed_quality(products, "google_shopping")
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert errors == []

    # ── Mixed scenario ────────────────────────────────────────────────────────

    def test_mixed_products_score_computed_correctly(self) -> None:
        """5 products: 3 clean, 1 missing required title, 1 duplicate id → valid=3."""
        clean = [dict(_CLEAN_PRODUCT, id=f"P{i}") for i in range(3)]
        bad_title = dict(_CLEAN_PRODUCT, id="P3", title="")
        dup1 = dict(_CLEAN_PRODUCT, id="DUP")
        dup2 = dict(_CLEAN_PRODUCT, id="DUP")
        products = clean + [bad_title, dup1, dup2]
        # total=6, valid: P0,P1,P2 are valid; P3 invalid (missing title);
        # DUP×2 both invalid → valid=3
        result = compute_feed_quality(products, "google_shopping")
        assert result["total"] == 6
        assert result["valid"] == 3
        assert result["score"] == 50
        codes = {i["code"] for i in result["issues"]}
        assert "missing_required_field" in codes
        assert "duplicate_id" in codes


# ═══════════════════════════════════════════════════════════════════════════════
# 2. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeedQualityEndpoint:
    """Integration tests against GET /api/v1/feeds/channels/{channel_id}/quality."""

    def _setup_clean_channel(
        self,
        db: Session,
        membership: Membership,
        channel_type: str = "google_shopping",
    ) -> tuple[str, FeedSource, FeedChannel]:
        src = _make_source(db, membership.tenant_id)
        ch = _make_channel(db, src, channel_type=channel_type)
        products = [dict(_CLEAN_PRODUCT, id=f"CP{i}") for i in range(3)]
        _seed_products(db, src, products)
        return str(ch.id), src, ch

    def _setup_dirty_channel(
        self,
        db: Session,
        membership: Membership,
    ) -> tuple[str, FeedSource, FeedChannel]:
        """Channel with products that have issues."""
        src = _make_source(db, membership.tenant_id)
        ch = _make_channel(db, src, channel_type="google_shopping")
        products = [
            # valid
            dict(_CLEAN_PRODUCT, id="OK1"),
            # missing title
            dict(_CLEAN_PRODUCT, id="BAD1", title=""),
            # missing description
            dict(_CLEAN_PRODUCT, id="BAD2", description=""),
            # duplicate id
            dict(_CLEAN_PRODUCT, id="DUP"),
            dict(_CLEAN_PRODUCT, id="DUP"),
        ]
        _seed_products(db, src, products)
        return str(ch.id), src, ch

    # ── Basic 200 + response shape ────────────────────────────────────────────

    def test_quality_endpoint_200(self, client: TestClient, db_session: Session) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_clean_channel(db_session, membership)
        resp = client.get(f"/api/v1/feeds/channels/{ch_id}/quality")
        assert resp.status_code == 200

    def test_quality_response_has_required_fields(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_clean_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        assert "score" in body
        assert "total" in body
        assert "valid" in body
        assert "sampled" in body
        assert "sampled_total" in body
        assert "issues" in body
        assert isinstance(body["issues"], list)

    def test_quality_issue_has_required_fields(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_dirty_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        for issue in body["issues"]:
            assert "code" in issue
            assert "severity" in issue
            assert "field" in issue
            assert "message" in issue
            assert "affected_count" in issue
            assert "sample_ids" in issue

    # ── Clean products → score 100 ────────────────────────────────────────────

    def test_clean_products_score_100(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_clean_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        assert body["score"] == 100
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert errors == []

    # ── Dirty products → correct issue codes ─────────────────────────────────

    def test_dirty_products_missing_required_field_in_issues(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_dirty_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        codes = {i["code"] for i in body["issues"]}
        assert "missing_required_field" in codes

    def test_dirty_products_duplicate_id_in_issues(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_dirty_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        codes = {i["code"] for i in body["issues"]}
        assert "duplicate_id" in codes

    def test_dirty_products_score_less_than_100(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_dirty_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        assert body["score"] < 100

    def test_affected_count_correct_for_missing_title(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title=""),
            dict(_CLEAN_PRODUCT, id="P2", title=""),
            dict(_CLEAN_PRODUCT, id="P3"),
        ]
        _seed_products(db_session, src, products)
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        title_issue = next(
            (i for i in body["issues"] if i["code"] == "missing_required_field" and i["field"] == "title"),
            None,
        )
        assert title_issue is not None
        assert title_issue["affected_count"] == 2

    # ── Empty channel → score 0, no crash ────────────────────────────────────

    def test_empty_channel_score_0_no_crash(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src)
        # No products seeded
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        assert body["score"] == 0
        assert body["total"] == 0
        codes = [i["code"] for i in body["issues"]]
        assert "empty_feed" in codes

    # ── Rules applied before quality check ───────────────────────────────────

    def test_filter_rule_reduces_feed_before_quality_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A filter rule removes out-of-stock products; only remaining are checked."""
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="IN1", availability="in stock"),
            dict(_CLEAN_PRODUCT, id="IN2", availability="in stock"),
            dict(_CLEAN_PRODUCT, id="OUT1", availability="out of stock"),
        ]
        _seed_products(db_session, src, products)
        # Rule: exclude out-of-stock
        _make_rule(
            db_session,
            ch,
            "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq", "condition_value": "out of stock"},
            position=0,
        )
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        # After rule: only 2 products remain
        assert body["total"] == 2

    def test_set_value_rule_fixes_field_before_quality_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A set_value rule fills in the missing availability; products become valid."""
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="P1", availability=""),  # availability missing
        ]
        _seed_products(db_session, src, products)
        # Rule: set availability = "in stock"
        _make_rule(
            db_session,
            ch,
            "set_value",
            {"field": "availability", "value": "in stock"},
            position=0,
        )
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        # After rule availability is filled → no error for availability
        avail_errors = [
            i for i in body["issues"]
            if i["severity"] == "error" and i["field"] == "availability"
        ]
        assert avail_errors == []

    def test_paused_rule_not_applied_before_quality(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A paused rule must not affect the products fed into quality check."""
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="P1", availability=""),  # missing availability
        ]
        _seed_products(db_session, src, products)
        # Paused rule — should be skipped
        _make_rule(
            db_session,
            ch,
            "set_value",
            {"field": "availability", "value": "in stock"},
            position=0,
            is_paused=True,
        )
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        # Paused rule not applied → availability still empty → error present
        avail_errors = [
            i for i in body["issues"]
            if i["severity"] == "error" and i["field"] == "availability"
        ]
        assert len(avail_errors) == 1

    # ── sampled flag ──────────────────────────────────────────────────────────

    def test_sampled_false_for_small_catalog(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id, _, _ = self._setup_clean_channel(db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/quality").json()
        assert body["sampled"] is False
        assert body["sampled_total"] is None

    # ── Title too long flagged in HTTP response ───────────────────────────────

    def test_title_too_long_flagged_via_endpoint(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title="X" * 200),
        ]
        _seed_products(db_session, src, products)
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        codes = {i["code"] for i in body["issues"]}
        assert "title_too_long" in codes
        # It's a warning → score still 100
        assert body["score"] == 100

    # ── Issues sorted: errors before warnings ─────────────────────────────────

    def test_issues_sorted_errors_before_warnings(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src, channel_type="google_shopping")
        products = [
            dict(_CLEAN_PRODUCT, id="P1", title="X" * 200, brand=""),  # warning (title_too_long + missing brand)
            dict(_CLEAN_PRODUCT, id="P2", description=""),  # error (missing description)
        ]
        _seed_products(db_session, src, products)
        body = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/quality").json()
        issues = body["issues"]
        if len(issues) >= 2:
            _severity_order = {"error": 0, "warning": 1, "info": 2}
            for i in range(len(issues) - 1):
                assert _severity_order.get(issues[i]["severity"], 99) <= _severity_order.get(issues[i + 1]["severity"], 99), \
                    f"Issues not sorted: {issues[i]['severity']} before {issues[i+1]['severity']}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Auth & tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityAuthIsolation:
    """The quality endpoint must require auth and enforce tenant isolation."""

    def test_quality_requires_auth(self, client_no_auth: TestClient) -> None:
        resp = client_no_auth.get(
            f"/api/v1/feeds/channels/{uuid.uuid4()}/quality"
        )
        assert resp.status_code in (401, 403, 422)

    def test_quality_404_unknown_channel(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/feeds/channels/{uuid.uuid4()}/quality")
        assert resp.status_code == 404

    def test_quality_404_other_tenant(self, db_session: Session) -> None:
        """Tenant B cannot access Tenant A's channel."""
        tenant_a, _, membership_a = _seed_tenant_user(db_session)
        _, _, membership_b = _seed_tenant_user(db_session)

        src_a = _make_source(db_session, tenant_a.id)
        ch_a = _make_channel(db_session, src_a, channel_type="google_shopping")
        products = [dict(_CLEAN_PRODUCT, id="P1")]
        _seed_products(db_session, src_a, products)

        client_b = _make_isolated_client(db_session, membership_b)
        resp = client_b.get(f"/api/v1/feeds/channels/{str(ch_a.id)}/quality")
        assert resp.status_code == 404

    def test_quality_accessible_by_own_tenant(self, db_session: Session) -> None:
        """Tenant A can access its own channel."""
        _, _, membership_a = _seed_tenant_user(db_session)
        src_a = _make_source(db_session, membership_a.tenant_id)
        ch_a = _make_channel(db_session, src_a, channel_type="google_shopping")
        products = [dict(_CLEAN_PRODUCT, id="P1")]
        _seed_products(db_session, src_a, products)

        client_a = _make_isolated_client(db_session, membership_a)
        resp = client_a.get(f"/api/v1/feeds/channels/{str(ch_a.id)}/quality")
        assert resp.status_code == 200
