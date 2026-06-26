"""API integration tests for Feed Management (M5).

Strategy
--------
* FastAPI TestClient with a minimal test app that includes only the feeds router.
  This avoids touching main.py (owned by the team lead) while still exercising
  the full HTTP layer.
* get_db overridden to an in-memory SQLite session.
* get_current_membership overridden to a pre-built Membership (no auth round-trip).
* Full flow: create source → sync (upload fixture XML) → create channel + rules
  → GET public feed returns valid transformed XML.
* Also covers CRUD endpoints (create/list/patch/delete) for sources, channels, rules.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all model modules on Base.metadata before create_all
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.feeds  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import feeds as feeds_module
from ayaz.services.auth import hash_password

# Minimal test app — only the feeds router.
# The team lead wires feeds.router into main.py for production;
# here we wire it ourselves so tests are self-contained.
_test_app = FastAPI(title="AYAZ Feeds Test App")
_test_app.include_router(feeds_module.router, prefix="/api/v1")

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_XML_BYTES = (FIXTURES_DIR / "sample_feed.xml").read_bytes()

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


# ── Client fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="API Test Tenant",
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="feed_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Feed Test User",
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

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── FeedSource CRUD ───────────────────────────────────────────────────────────


class TestFeedSourceCRUD:
    def test_list_sources_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/feeds/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_source(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "My Feed", "source_type": "url_xml",
                  "source_url": "https://example.com/feed.xml"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "My Feed"
        assert body["source_type"] == "url_xml"
        assert body["status"] == "pending"
        assert body["item_count"] == 0

    def test_create_source_invalid_type_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Bad", "source_type": "invalid_type"},
        )
        assert resp.status_code == 422

    def test_get_source(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "GetTest", "source_type": "upload"},
        )
        src_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/feeds/sources/{src_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == src_id

    def test_get_source_not_found(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/feeds/sources/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patch_source(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Old Name", "source_type": "upload"},
        )
        src_id = create_resp.json()["id"]
        resp = client.patch(
            f"/api/v1/feeds/sources/{src_id}",
            json={"name": "New Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_delete_source(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "ToDelete", "source_type": "upload"},
        )
        src_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/v1/feeds/sources/{src_id}")
        assert del_resp.status_code == 204
        assert client.get(f"/api/v1/feeds/sources/{src_id}").status_code == 404

    def test_list_sources_after_create(self, client: TestClient) -> None:
        client.post("/api/v1/feeds/sources", json={"name": "A", "source_type": "upload"})
        client.post("/api/v1/feeds/sources", json={"name": "B", "source_type": "upload"})
        resp = client.get("/api/v1/feeds/sources")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── Sync endpoint ─────────────────────────────────────────────────────────────


class TestSyncEndpoint:
    def test_sync_upload_xml(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Upload Test", "source_type": "upload"},
        )
        src_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/sync",
            files={"file": ("feed.xml", SAMPLE_XML_BYTES, "application/xml")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["item_count"] == 3
        assert body["status"] == "ok"
        assert body["last_synced_at"] is not None

    def test_sync_updates_source_item_count(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Count Test", "source_type": "upload"},
        )
        src_id = create_resp.json()["id"]
        client.post(
            f"/api/v1/feeds/sources/{src_id}/sync",
            files={"file": ("feed.xml", SAMPLE_XML_BYTES, "application/xml")},
        )
        src_resp = client.get(f"/api/v1/feeds/sources/{src_id}")
        assert src_resp.json()["item_count"] == 3


# ── FeedChannel CRUD ──────────────────────────────────────────────────────────


class TestFeedChannelCRUD:
    def _create_source(self, client: TestClient) -> str:
        resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Src", "source_type": "upload"},
        )
        return resp.json()["id"]

    def test_list_channels_empty(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.get(f"/api/v1/feeds/sources/{src_id}/channels")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_google_shopping_channel(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Google Shopping", "channel_type": "google_shopping"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["channel_type"] == "google_shopping"
        assert body["output_format"] == "xml"
        assert body["is_active"] is True
        assert len(body["public_token"]) > 10

    def test_create_meta_catalog_defaults_to_csv(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Meta", "channel_type": "meta_catalog"},
        )
        assert resp.status_code == 201
        # meta_catalog should default to csv
        assert resp.json()["output_format"] == "csv"

    def test_create_channel_invalid_type(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Bad", "channel_type": "bad_platform"},
        )
        assert resp.status_code == 422

    def test_get_channel(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Ch1", "channel_type": "custom", "output_format": "xml"},
        )
        ch_id = ch_resp.json()["id"]
        resp = client.get(f"/api/v1/feeds/channels/{ch_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == ch_id

    def test_patch_channel(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Ch", "channel_type": "custom", "output_format": "xml"},
        )
        ch_id = ch_resp.json()["id"]
        resp = client.patch(
            f"/api/v1/feeds/channels/{ch_id}",
            json={"name": "Updated Channel", "is_active": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Updated Channel"
        assert body["is_active"] is False

    def test_delete_channel(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Del", "channel_type": "custom", "output_format": "xml"},
        )
        ch_id = ch_resp.json()["id"]
        assert client.delete(f"/api/v1/feeds/channels/{ch_id}").status_code == 204
        assert client.get(f"/api/v1/feeds/channels/{ch_id}").status_code == 404

    def test_public_token_is_unique_per_channel(self, client: TestClient) -> None:
        src_id = self._create_source(client)
        tokens = set()
        for i in range(3):
            r = client.post(
                f"/api/v1/feeds/sources/{src_id}/channels",
                json={"name": f"Ch{i}", "channel_type": "custom", "output_format": "xml"},
            )
            tokens.add(r.json()["public_token"])
        assert len(tokens) == 3


# ── FeedRule CRUD ─────────────────────────────────────────────────────────────


class TestFeedRuleCRUD:
    def _setup(self, client: TestClient) -> tuple[str, str]:
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "RuleSrc", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "RuleCh", "channel_type": "google_shopping"},
        )
        ch_id = ch_resp.json()["id"]
        return src_id, ch_id

    def test_create_rule(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "condition", "value": "new"}},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rule_type"] == "set_value"
        assert body["config"] == {"field": "condition", "value": "new"}

    def test_create_rule_invalid_type(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "bad_type", "position": 0, "config": {}},
        )
        assert resp.status_code == 422

    def test_list_rules(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "f", "value": "v"}},
        )
        client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "rename_field", "position": 1,
                  "config": {"from_field": "a", "to_field": "b"}},
        )
        resp = client.get(f"/api/v1/feeds/channels/{ch_id}/rules")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_patch_rule(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        rule_resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "f", "value": "old"}},
        )
        rule_id = rule_resp.json()["id"]
        resp = client.patch(
            f"/api/v1/feeds/rules/{rule_id}",
            json={"config": {"field": "f", "value": "new"}},
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["value"] == "new"

    def test_delete_rule(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        rule_resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "f", "value": "v"}},
        )
        rule_id = rule_resp.json()["id"]
        assert client.delete(f"/api/v1/feeds/rules/{rule_id}").status_code == 204

    def test_reorder_rules(self, client: TestClient) -> None:
        _, ch_id = self._setup(client)
        r1 = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "a", "value": "1"}},
        ).json()["id"]
        r2 = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 1,
                  "config": {"field": "b", "value": "2"}},
        ).json()["id"]

        # Reverse order
        resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules/reorder",
            json={"rule_ids": [r2, r1]},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result[0]["id"] == r2
        assert result[0]["position"] == 0
        assert result[1]["id"] == r1
        assert result[1]["position"] == 1


# ── Full end-to-end: public feed URL ──────────────────────────────────────────


class TestPublicFeed:
    def _setup_feed(
        self, client: TestClient, channel_type: str = "google_shopping"
    ) -> tuple[str, str]:
        """Create source, sync with fixture XML, create channel, return (ch_id, token)."""
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "E2E Source", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]

        client.post(
            f"/api/v1/feeds/sources/{src_id}/sync",
            files={"file": ("feed.xml", SAMPLE_XML_BYTES, "application/xml")},
        )

        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "E2E Channel", "channel_type": channel_type},
        )
        ch_id = ch_resp.json()["id"]
        token = ch_resp.json()["public_token"]
        return ch_id, token

    def test_public_feed_returns_200(self, client: TestClient) -> None:
        _, token = self._setup_feed(client)
        resp = client.get(f"/api/v1/feeds/public/{token}")
        assert resp.status_code == 200

    def test_public_feed_google_shopping_content_type(self, client: TestClient) -> None:
        _, token = self._setup_feed(client, "google_shopping")
        resp = client.get(f"/api/v1/feeds/public/{token}")
        assert "xml" in resp.headers["content-type"]

    def test_public_feed_google_shopping_is_valid_rss(self, client: TestClient) -> None:
        import xml.etree.ElementTree as ET

        _, token = self._setup_feed(client, "google_shopping")
        resp = client.get(f"/api/v1/feeds/public/{token}")
        root = ET.fromstring(resp.text)
        assert root.tag == "rss"

    def test_public_feed_has_3_items(self, client: TestClient) -> None:
        import xml.etree.ElementTree as ET

        _, token = self._setup_feed(client, "google_shopping")
        resp = client.get(f"/api/v1/feeds/public/{token}")
        root = ET.fromstring(resp.text)
        items = root.findall("channel/item")
        assert len(items) == 3

    def test_public_feed_g_namespace_fields_present(self, client: TestClient) -> None:
        import xml.etree.ElementTree as ET

        _, token = self._setup_feed(client, "google_shopping")
        resp = client.get(f"/api/v1/feeds/public/{token}")
        root = ET.fromstring(resp.text)
        NS = "http://base.google.com/ns/1.0"
        for item in root.findall("channel/item"):
            assert item.find(f"{{{NS}}}id") is not None
            assert item.find(f"{{{NS}}}title") is not None
            assert item.find(f"{{{NS}}}price") is not None

    def test_public_feed_with_rule_transforms_brand(self, client: TestClient) -> None:
        """set_value rule should change all brands in the rendered feed."""
        import xml.etree.ElementTree as ET

        ch_id, token = self._setup_feed(client, "google_shopping")
        client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "brand", "value": "AYAZ"}},
        )
        resp = client.get(f"/api/v1/feeds/public/{token}")
        root = ET.fromstring(resp.text)
        NS = "http://base.google.com/ns/1.0"
        brands = [el.text for el in root.findall(f"channel/item/{{{NS}}}brand")]
        assert all(b == "AYAZ" for b in brands)
        assert len(brands) == 3

    def test_public_feed_filter_exclude_reduces_items(self, client: TestClient) -> None:
        """Excluding out-of-stock should leave 2 items."""
        import xml.etree.ElementTree as ET

        ch_id, token = self._setup_feed(client, "google_shopping")
        client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={
                "rule_type": "filter_exclude",
                "position": 0,
                "config": {
                    "condition_field": "availability",
                    "condition_op": "eq",
                    "condition_value": "out of stock",
                },
            },
        )
        resp = client.get(f"/api/v1/feeds/public/{token}")
        root = ET.fromstring(resp.text)
        assert len(root.findall("channel/item")) == 2

    def test_public_feed_meta_csv(self, client: TestClient) -> None:
        _, token = self._setup_feed(client, "meta_catalog")
        resp = client.get(f"/api/v1/feeds/public/{token}")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        header = resp.text.split("\n")[0]
        for col in ("id", "title", "price"):
            assert col in header

    def test_public_feed_inactive_channel_returns_404(self, client: TestClient) -> None:
        ch_id, token = self._setup_feed(client, "google_shopping")
        client.patch(f"/api/v1/feeds/channels/{ch_id}", json={"is_active": False})
        resp = client.get(f"/api/v1/feeds/public/{token}")
        assert resp.status_code == 404

    def test_public_feed_unknown_token_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/feeds/public/totally_unknown_token_xyz")
        assert resp.status_code == 404
