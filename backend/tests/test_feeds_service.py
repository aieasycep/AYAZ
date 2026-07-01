"""Service-layer tests for Feed Management (M5).

Strategy
--------
* In-memory SQLite, no live network, no live Postgres.
* fixture XML loaded from tests/fixtures/sample_feed.xml.
* Service functions are tested directly (no FastAPI TestClient here).
* apply_rules is a pure function — tested without a DB session.
* generate_channel_feed is tested against a seeded SQLite DB.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.feeds import FeedChannel, FeedProduct, FeedRule, FeedSource

# Register all models on Base.metadata
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401

from ayaz.services.feeds import (
    apply_rules,
    generate_channel_feed,
    ingest_feed_source,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_XML = (FIXTURES_DIR / "sample_feed.xml").read_bytes()

TENANT_ID = uuid.uuid4()


# ── In-memory DB fixture ──────────────────────────────────────────────────────


@pytest.fixture()
def db() -> Session:
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


# ── Feed source factory ───────────────────────────────────────────────────────


def _make_source(db: Session, source_type: str = "url_xml") -> FeedSource:
    src = FeedSource(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        name="Test Source",
        source_type=source_type,
        source_url=None,
        status="pending",
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
    output_format: str = "xml",
) -> FeedChannel:
    ch = FeedChannel(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        feed_source_id=source.id,
        name="Test Channel",
        channel_type=channel_type,
        output_format=output_format,
        public_token="test_token_" + secrets_token(),
        is_active=True,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


def secrets_token() -> str:
    import secrets
    return secrets.token_hex(8)


def _make_rule(
    db: Session,
    channel: FeedChannel,
    rule_type: str,
    config: dict,
    position: int = 0,
) -> FeedRule:
    rule = FeedRule(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        feed_channel_id=channel.id,
        rule_type=rule_type,
        config=config,
        position=position,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# ── ingest_feed_source tests ──────────────────────────────────────────────────


class TestIngestFeedSource:
    def test_xml_ingest_count(self, db: Session) -> None:
        """Ingesting the 3-product fixture should upsert 3 FeedProduct rows."""
        src = _make_source(db, "url_xml")
        count = ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        assert count == 3

    def test_xml_updates_item_count(self, db: Session) -> None:
        src = _make_source(db, "url_xml")
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        db.refresh(src)
        assert src.item_count == 3

    def test_xml_updates_status_to_ok(self, db: Session) -> None:
        src = _make_source(db, "url_xml")
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        db.refresh(src)
        assert src.status == "ok"

    def test_xml_sets_last_synced_at(self, db: Session) -> None:
        src = _make_source(db, "url_xml")
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        db.refresh(src)
        assert src.last_synced_at is not None

    def test_xml_product_data_stored(self, db: Session) -> None:
        """First product should have title = 'Running Shoes Pro'."""
        from sqlalchemy import select

        src = _make_source(db, "url_xml")
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        products = list(
            db.scalars(
                select(FeedProduct).where(FeedProduct.feed_source_id == src.id)
            )
        )
        titles = {p.data.get("title") for p in products}
        assert "Running Shoes Pro" in titles

    def test_xml_idempotent_reingest(self, db: Session) -> None:
        """Re-ingesting the same feed should not duplicate rows."""
        from sqlalchemy import select, func

        src = _make_source(db, "url_xml")
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        ingest_feed_source(db, src, raw_bytes=SAMPLE_XML)
        cnt = db.scalar(
            select(func.count(FeedProduct.id)).where(
                FeedProduct.feed_source_id == src.id
            )
        )
        assert cnt == 3

    def test_csv_ingest(self, db: Session) -> None:
        """A simple CSV with 2 products should produce 2 rows."""
        csv_bytes = b"id,title,price\nA1,Widget Alpha,9.99\nB2,Widget Beta,19.99\n"
        src = _make_source(db, "url_csv")
        count = ingest_feed_source(db, src, raw_bytes=csv_bytes)
        assert count == 2

    def test_csv_product_fields(self, db: Session) -> None:
        from sqlalchemy import select

        csv_bytes = b"id,title,price\nA1,Widget Alpha,9.99\n"
        src = _make_source(db, "url_csv")
        ingest_feed_source(db, src, raw_bytes=csv_bytes)
        product = db.scalar(
            select(FeedProduct).where(FeedProduct.feed_source_id == src.id)
        )
        assert product is not None
        assert product.data["title"] == "Widget Alpha"
        assert product.data["price"] == "9.99"
        assert product.external_id == "A1"


# ── apply_rules tests (pure function) ────────────────────────────────────────


class _StubRule:
    """Lightweight stand-in for FeedRule used in pure-function tests.

    apply_rules only reads .rule_type, .config, and .position — no ORM state
    needed.
    """

    def __init__(self, rule_type: str, config: dict, position: int = 0) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = TENANT_ID
        self.feed_channel_id = uuid.uuid4()
        self.rule_type = rule_type
        self.config = config
        self.position = position


def _make_stub_rule(rule_type: str, config: dict, position: int = 0) -> "_StubRule":
    """Create a lightweight FeedRule stand-in without touching the DB."""
    return _StubRule(rule_type, config, position)


SAMPLE_PRODUCTS = [
    {"id": "P1", "title": "Widget Alpha", "price": "10.00",
     "availability": "in stock", "brand": "Acme", "description": "A widget"},
    {"id": "P2", "title": "Widget  Beta", "price": "20.00",
     "availability": "out of stock", "brand": "Beta Corp", "description": "Another widget"},
    {"id": "P3", "title": "Gadget Gamma", "price": "5.00",
     "availability": "in stock", "brand": "Acme", "description": "A gadget"},
]


class TestApplyRules:
    def test_set_value_overwrites_field(self) -> None:
        rules = [_make_stub_rule("set_value", {"field": "condition", "value": "new"})]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert all(p["condition"] == "new" for p in result)

    def test_set_value_does_not_affect_other_fields(self) -> None:
        rules = [_make_stub_rule("set_value", {"field": "condition", "value": "new"})]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[0]["title"] == "Widget Alpha"

    def test_rename_field_copies_value(self) -> None:
        rules = [_make_stub_rule(
            "rename_field",
            {"from_field": "brand", "to_field": "g_brand", "drop_original": False},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[0]["g_brand"] == "Acme"
        assert "brand" in result[0]  # original preserved

    def test_rename_field_drop_original(self) -> None:
        rules = [_make_stub_rule(
            "rename_field",
            {"from_field": "brand", "to_field": "g_brand", "drop_original": True},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[0]["g_brand"] == "Acme"
        assert "brand" not in result[0]

    def test_find_replace_substring(self) -> None:
        rules = [_make_stub_rule(
            "find_replace",
            {"field": "title", "pattern": "Widget", "replacement": "Product", "use_regex": False},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[0]["title"] == "Product Alpha"
        assert result[2]["title"] == "Gadget Gamma"  # unchanged

    def test_find_replace_regex(self) -> None:
        """Collapse multiple spaces in title."""
        rules = [_make_stub_rule(
            "find_replace",
            {"field": "title", "pattern": r"\s+", "replacement": " ", "use_regex": True},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[1]["title"] == "Widget Beta"  # double space collapsed

    def test_filter_include_eq(self) -> None:
        rules = [_make_stub_rule(
            "filter_include",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "in stock"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert len(result) == 2
        assert all(p["availability"] == "in stock" for p in result)

    def test_filter_exclude_eq(self) -> None:
        rules = [_make_stub_rule(
            "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "out of stock"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert len(result) == 2
        assert all(p["availability"] != "out of stock" for p in result)

    def test_filter_include_contains(self) -> None:
        rules = [_make_stub_rule(
            "filter_include",
            {"condition_field": "brand", "condition_op": "contains",
             "condition_value": "Acme"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert len(result) == 2
        assert all(p["brand"] == "Acme" for p in result)

    def test_filter_include_gt(self) -> None:
        """Keep only products with price > 9.00."""
        rules = [_make_stub_rule(
            "filter_include",
            {"condition_field": "price", "condition_op": "gt",
             "condition_value": "9.00"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert len(result) == 2
        prices = {p["price"] for p in result}
        assert "5.00" not in prices

    def test_calculated_template(self) -> None:
        """custom_label_0 = '{title} - {brand}'."""
        rules = [_make_stub_rule(
            "calculated",
            {"field": "custom_label_0", "expression": "{title} - {brand}"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert result[0]["custom_label_0"] == "Widget Alpha - Acme"

    def test_calculated_arithmetic(self) -> None:
        """sale_price = price * 0.9 (10.00 * 0.9 = 9.0)."""
        rules = [_make_stub_rule(
            "calculated",
            {"field": "sale_price", "expression": "{price} * 0.9"},
        )]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert float(result[0]["sale_price"]) == pytest.approx(9.0)

    def test_rules_applied_in_position_order(self) -> None:
        """set_value at pos 0, then rename_field at pos 1."""
        r1 = _make_stub_rule("set_value", {"field": "brand", "value": "NewBrand"}, position=0)
        r2 = _make_stub_rule(
            "rename_field",
            {"from_field": "brand", "to_field": "g_brand", "drop_original": False},
            position=1,
        )
        result = apply_rules(list(SAMPLE_PRODUCTS), [r1, r2])
        # brand was set to "NewBrand" by r1, then copied to g_brand by r2
        assert all(p["g_brand"] == "NewBrand" for p in result)

    def test_unknown_rule_type_skipped(self) -> None:
        """An unknown rule_type should be silently skipped."""
        rules = [_make_stub_rule("future_rule_type", {"field": "x", "value": "y"})]
        result = apply_rules(list(SAMPLE_PRODUCTS), rules)
        assert len(result) == len(SAMPLE_PRODUCTS)

    def test_empty_products_returns_empty(self) -> None:
        rules = [_make_stub_rule("set_value", {"field": "x", "value": "y"})]
        assert apply_rules([], rules) == []

    def test_no_rules_returns_unchanged(self) -> None:
        result = apply_rules(list(SAMPLE_PRODUCTS), [])
        assert result == SAMPLE_PRODUCTS


# ── generate_channel_feed tests ───────────────────────────────────────────────


class TestGenerateChannelFeed:
    def _seed_products(self, db: Session, source: FeedSource) -> None:
        ingest_feed_source(db, source, raw_bytes=SAMPLE_XML)

    def test_google_shopping_returns_xml_content_type(self, db: Session) -> None:
        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        _, ct = generate_channel_feed(db, ch)
        assert ct == "application/xml"

    def test_google_shopping_xml_is_valid(self, db: Session) -> None:
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        content, _ = generate_channel_feed(db, ch)
        # Should not raise
        root = ET.fromstring(content)
        assert root.tag == "rss"

    def test_google_shopping_has_g_namespace_fields(self, db: Session) -> None:
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        content, _ = generate_channel_feed(db, ch)
        root = ET.fromstring(content)
        NS = "http://base.google.com/ns/1.0"
        items = root.findall(f"channel/item")
        assert len(items) == 3
        for item in items:
            assert item.find(f"{{{NS}}}id") is not None
            assert item.find(f"{{{NS}}}title") is not None
            assert item.find(f"{{{NS}}}price") is not None
            assert item.find(f"{{{NS}}}availability") is not None

    def test_google_shopping_title_values(self, db: Session) -> None:
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        content, _ = generate_channel_feed(db, ch)
        root = ET.fromstring(content)
        NS = "http://base.google.com/ns/1.0"
        g_titles = [
            el.text
            for el in root.findall(f"channel/item/{{{NS}}}title")
        ]
        assert "Running Shoes Pro" in g_titles

    def test_meta_catalog_returns_csv(self, db: Session) -> None:
        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="meta_catalog", output_format="csv")
        content, ct = generate_channel_feed(db, ch)
        assert "text/csv" in ct
        assert "id" in content.split("\n")[0]
        assert "title" in content.split("\n")[0]

    def test_meta_catalog_has_3_data_rows(self, db: Session) -> None:
        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="meta_catalog", output_format="csv")
        content, _ = generate_channel_feed(db, ch)
        lines = [l for l in content.strip().split("\n") if l]
        # header + 3 data rows
        assert len(lines) == 4

    def test_tiktok_catalog_has_sku_id_column(self, db: Session) -> None:
        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="tiktok_catalog", output_format="csv")
        content, ct = generate_channel_feed(db, ch)
        assert "text/csv" in ct
        header = content.split("\n")[0]
        assert "sku_id" in header

    def test_custom_xml_format(self, db: Session) -> None:
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="custom", output_format="xml")
        content, ct = generate_channel_feed(db, ch)
        assert "application/xml" in ct
        root = ET.fromstring(content)
        assert root.tag == "feed"
        assert len(list(root)) == 3  # 3 <product> children

    def test_custom_csv_format(self, db: Session) -> None:
        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="custom", output_format="csv")
        content, ct = generate_channel_feed(db, ch)
        assert "text/csv" in ct
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 4  # header + 3 rows

    def test_rules_applied_before_rendering(self, db: Session) -> None:
        """A set_value rule setting condition='new' should appear in the g: feed."""
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        _make_rule(db, ch, "set_value", {"field": "brand", "value": "AYAZ Brand"}, position=0)

        content, _ = generate_channel_feed(db, ch)
        root = ET.fromstring(content)
        NS = "http://base.google.com/ns/1.0"
        brands = [
            el.text
            for el in root.findall(f"channel/item/{{{NS}}}brand")
        ]
        assert all(b == "AYAZ Brand" for b in brands)

    def test_filter_exclude_reduces_item_count(self, db: Session) -> None:
        """Excluding out-of-stock products should leave 2 items in the feed."""
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        self._seed_products(db, src)
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        _make_rule(
            db, ch,
            "filter_exclude",
            {"condition_field": "availability",
             "condition_op": "eq",
             "condition_value": "out of stock"},
            position=0,
        )
        content, _ = generate_channel_feed(db, ch)
        root = ET.fromstring(content)
        items = root.findall("channel/item")
        assert len(items) == 2

    def test_empty_source_produces_valid_xml(self, db: Session) -> None:
        """A channel with no products should still render valid XML."""
        import xml.etree.ElementTree as ET

        src = _make_source(db)
        # No ingest — zero products
        ch = _make_channel(db, src, channel_type="google_shopping", output_format="xml")
        content, _ = generate_channel_feed(db, ch)
        root = ET.fromstring(content)
        assert root.tag == "rss"
        assert len(root.findall("channel/item")) == 0
