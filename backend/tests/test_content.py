"""Tests for M8 İçerik Planlayıcı (Content Planner) module.

Coverage
--------
1. ContentPost CRUD
   - create → get → list
   - channel/status validation (422)
2. Status workflow transitions
   - submit, approve, reject, schedule set the correct status
   - publish returns 501 (credential gate)
3. AI-caption endpoint
   - returns non-empty caption + hashtags without any API key (template path)
4. Tenant isolation
   - get/list/transition for another tenant's post returns 404
5. generate_caption unit tests
   - template path always works, returns required keys
   - channel-specific path

Self-contained: builds its own mini FastAPI app with an in-memory SQLite engine,
mirroring the pattern in tests/test_tracking_stats.py.
"""

from __future__ import annotations

import uuid
from typing import Any

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
import ayaz.models.content  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import content as content_module
from ayaz.services.auth import hash_password
from ayaz.services.content import generate_caption

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Content Planner Test App")
_test_app.include_router(content_module.router, prefix="/api/v1")

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
        name="Content Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="content_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Content Test User",
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


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_post(
    client: TestClient,
    *,
    title: str = "Test Gönderisi",
    body: str = "Bu bir test gönderisidir.",
    channels: list[str] | None = None,
    scheduled_at: str | None = None,
    media_url: str | None = None,
    ai_assisted: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "channels": channels if channels is not None else ["instagram"],
        "ai_assisted": ai_assisted,
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    if media_url is not None:
        payload["media_url"] = media_url

    resp = client.post("/api/v1/content/posts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CRUD: create → get → list
# ═══════════════════════════════════════════════════════════════════════════════


class TestCRUD:
    def test_create_post_returns_201_with_draft_status(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/content/posts",
            json={"title": "İlk Gönderi", "body": "Merhaba dünya!", "channels": ["instagram", "facebook"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "İlk Gönderi"
        assert data["body"] == "Merhaba dünya!"
        assert set(data["channels"]) == {"instagram", "facebook"}
        assert data["status"] == "draft"
        assert data["ai_assisted"] is False
        assert data["approval_note"] is None
        assert "id" in data
        assert "tenant_id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_get_post_by_id(self, client: TestClient) -> None:
        post = _make_post(client, title="Getirme Testi")
        resp = client.get(f"/api/v1/content/posts/{post['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == post["id"]
        assert resp.json()["title"] == "Getirme Testi"

    def test_list_posts_returns_created_post(self, client: TestClient) -> None:
        _make_post(client, title="Listeleme Testi")
        resp = client.get("/api/v1/content/posts")
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "Listeleme Testi" in titles

    def test_list_posts_ordered_newest_first(self, client: TestClient) -> None:
        _make_post(client, title="Birinci")
        _make_post(client, title="İkinci")
        resp = client.get("/api/v1/content/posts")
        assert resp.status_code == 200
        posts = resp.json()
        assert len(posts) >= 2
        # created_at should be descending
        created_ats = [p["created_at"] for p in posts]
        assert created_ats == sorted(created_ats, reverse=True)

    def test_patch_post_updates_fields(self, client: TestClient) -> None:
        post = _make_post(client, title="Eski Başlık")
        resp = client.patch(
            f"/api/v1/content/posts/{post['id']}",
            json={"title": "Yeni Başlık", "body": "Güncellenmiş metin."},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Yeni Başlık"
        assert resp.json()["body"] == "Güncellenmiş metin."

    def test_patch_clears_scheduled_at_when_null(self, client: TestClient) -> None:
        post = _make_post(client, title="Zamanlanmış", scheduled_at="2026-08-01T10:00:00Z")
        assert post["scheduled_at"] == "2026-08-01T10:00:00Z"
        resp = client.patch(
            f"/api/v1/content/posts/{post['id']}",
            json={"scheduled_at": None},
        )
        assert resp.status_code == 200
        assert resp.json()["scheduled_at"] is None

    def test_delete_post_returns_204(self, client: TestClient) -> None:
        post = _make_post(client, title="Silinecek")
        resp = client.delete(f"/api/v1/content/posts/{post['id']}")
        assert resp.status_code == 204
        # Confirm gone
        resp2 = client.get(f"/api/v1/content/posts/{post['id']}")
        assert resp2.status_code == 404

    def test_create_post_defaults_body_empty_string(self, client: TestClient) -> None:
        resp = client.post("/api/v1/content/posts", json={"title": "Sadece Başlık"})
        assert resp.status_code == 201
        assert resp.json()["body"] == ""
        assert resp.json()["channels"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Validation: channels and status
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_invalid_channel_in_create_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/posts",
            json={"title": "Geçersiz Kanal", "channels": ["snapchat"]},
        )
        assert resp.status_code == 422

    def test_invalid_channel_in_patch_returns_422(self, client: TestClient) -> None:
        post = _make_post(client)
        resp = client.patch(
            f"/api/v1/content/posts/{post['id']}",
            json={"channels": ["snapchat", "instagram"]},
        )
        assert resp.status_code == 422

    def test_invalid_status_in_patch_returns_422(self, client: TestClient) -> None:
        post = _make_post(client)
        resp = client.patch(
            f"/api/v1/content/posts/{post['id']}",
            json={"status": "gecersiz_durum"},
        )
        assert resp.status_code == 422

    def test_all_valid_channels_accepted(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/posts",
            json={
                "title": "Tüm Kanallar",
                "channels": ["instagram", "facebook", "x", "linkedin", "tiktok", "youtube"],
            },
        )
        assert resp.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Status workflow transitions
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowTransitions:
    def test_submit_sets_pending_approval(self, client: TestClient) -> None:
        post = _make_post(client)
        resp = client.post(f"/api/v1/content/posts/{post['id']}/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_approval"

    def test_approve_sets_approved(self, client: TestClient) -> None:
        post = _make_post(client)
        client.post(f"/api/v1/content/posts/{post['id']}/submit")
        resp = client.post(f"/api/v1/content/posts/{post['id']}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_sets_draft_and_note(self, client: TestClient) -> None:
        post = _make_post(client)
        client.post(f"/api/v1/content/posts/{post['id']}/submit")
        resp = client.post(
            f"/api/v1/content/posts/{post['id']}/reject",
            json={"note": "Lütfen görseli değiştirin."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "draft"
        assert data["approval_note"] == "Lütfen görseli değiştirin."

    def test_reject_without_note(self, client: TestClient) -> None:
        post = _make_post(client)
        resp = client.post(
            f"/api/v1/content/posts/{post['id']}/reject",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft"
        assert resp.json()["approval_note"] is None

    def test_schedule_sets_scheduled_status_and_time(self, client: TestClient) -> None:
        post = _make_post(client)
        resp = client.post(
            f"/api/v1/content/posts/{post['id']}/schedule",
            json={"scheduled_at": "2026-09-01T08:00:00Z"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert data["scheduled_at"] == "2026-09-01T08:00:00Z"

    def test_publish_returns_501(self, client: TestClient) -> None:
        """Live publish always returns 501 — credential gate is intentional."""
        post = _make_post(client)
        resp = client.post(f"/api/v1/content/posts/{post['id']}/publish")
        assert resp.status_code == 501
        assert "OAuth" in resp.json()["detail"] or "kimlik doğrulama" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Filtering
# ═══════════════════════════════════════════════════════════════════════════════


class TestFiltering:
    def test_filter_by_status(self, client: TestClient) -> None:
        p1 = _make_post(client, title="Taslak")
        p2 = _make_post(client, title="Beklemede")
        client.post(f"/api/v1/content/posts/{p2['id']}/submit")

        resp = client.get("/api/v1/content/posts", params={"status": "pending_approval"})
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert p2["id"] in ids
        assert p1["id"] not in ids

    def test_filter_by_channel(self, client: TestClient) -> None:
        _make_post(client, title="Instagram", channels=["instagram"])
        _make_post(client, title="LinkedIn", channels=["linkedin"])

        resp = client.get("/api/v1/content/posts", params={"channel": "linkedin"})
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "LinkedIn" in titles
        assert "Instagram" not in titles

    def test_filter_by_date_range_excludes_null_scheduled(
        self, client: TestClient
    ) -> None:
        # Post without scheduled_at should be excluded when date filter given
        _make_post(client, title="Tarihi Yok")
        _make_post(client, title="Planlanmış", scheduled_at="2026-07-15T10:00:00Z")

        resp = client.get(
            "/api/v1/content/posts",
            params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "Planlanmış" in titles
        assert "Tarihi Yok" not in titles

    def test_filter_by_date_range_out_of_range_excluded(
        self, client: TestClient
    ) -> None:
        _make_post(client, title="Ağustos Gönderisi", scheduled_at="2026-08-15T10:00:00Z")

        resp = client.get(
            "/api/v1/content/posts",
            params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "Ağustos Gönderisi" not in titles


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_get_other_tenant_post_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.content import ContentPost

        # Create a post for a different tenant directly in the DB
        other_tenant_id = uuid.uuid4()
        other_post = ContentPost(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            title="Başka Tenant Gönderisi",
            body="Bu başka bir tenanta ait.",
            channels=["instagram"],
            status="draft",
            ai_assisted=False,
        )
        db_session.add(other_post)
        db_session.commit()

        resp = client.get(f"/api/v1/content/posts/{other_post.id}")
        assert resp.status_code == 404

    def test_list_does_not_include_other_tenant_posts(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.content import ContentPost

        other_tenant_id = uuid.uuid4()
        other_post = ContentPost(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            title="Gizli Gönderi",
            body="Gizli.",
            channels=["x"],
            status="draft",
            ai_assisted=False,
        )
        db_session.add(other_post)
        db_session.commit()

        resp = client.get("/api/v1/content/posts")
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "Gizli Gönderi" not in titles

    def test_transition_other_tenant_post_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.content import ContentPost

        other_tenant_id = uuid.uuid4()
        other_post = ContentPost(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            title="Başka Tenant",
            body=".",
            channels=[],
            status="draft",
            ai_assisted=False,
        )
        db_session.add(other_post)
        db_session.commit()

        resp = client.post(f"/api/v1/content/posts/{other_post.id}/submit")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 6. AI-caption endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestAICaption:
    def test_ai_caption_returns_non_empty_caption_and_hashtags(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/content/ai-caption",
            json={"brief": "Yeni ürün lansmanımızı duyuruyoruz."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "caption" in data
        assert "hashtags" in data
        assert "ai_assisted" in data
        assert len(data["caption"]) > 0
        assert isinstance(data["hashtags"], list)
        assert len(data["hashtags"]) >= 3

    def test_ai_caption_without_api_key_uses_template(
        self, client: TestClient
    ) -> None:
        """Template path must work deterministically without any API key."""
        resp = client.post(
            "/api/v1/content/ai-caption",
            json={
                "brief": "Sosyal medya stratejinizi güçlendirin.",
                "channel": "linkedin",
                "tone": "profesyonel",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Template path: ai_assisted=False (no API key in test env)
        assert data["ai_assisted"] is False
        assert len(data["caption"]) > 0
        assert len(data["hashtags"]) >= 3

    def test_ai_caption_with_channel(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/ai-caption",
            json={"brief": "Yeni koleksiyon çıktı!", "channel": "instagram"},
        )
        assert resp.status_code == 200
        assert resp.json()["caption"]

    def test_ai_caption_brief_required(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/ai-caption",
            json={"channel": "instagram"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 7. generate_caption unit tests (pure service layer)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateCaptionUnit:
    def test_template_returns_required_keys(self) -> None:
        result = generate_caption("Yeni ürün tanıtımı yapıyoruz.")
        assert "caption" in result
        assert "hashtags" in result
        assert "ai_assisted" in result

    def test_template_returns_non_empty_caption(self) -> None:
        result = generate_caption("Kampanya başlıyor!")
        assert len(result["caption"]) > 0

    def test_template_returns_at_least_3_hashtags(self) -> None:
        result = generate_caption("Dijital pazarlama dünyasına hoş geldiniz.")
        assert len(result["hashtags"]) >= 3

    def test_template_ai_assisted_is_false(self) -> None:
        result = generate_caption("Test içeriği.", channel="instagram")
        # No API key configured in test env → always False
        assert result["ai_assisted"] is False

    def test_template_channel_affects_caption(self) -> None:
        result_instagram = generate_caption("Ürün tanıtımı", channel="instagram")
        result_linkedin = generate_caption("Ürün tanıtımı", channel="linkedin")
        # Channel-specific CTA should differ
        assert result_instagram["caption"] != result_linkedin["caption"]

    def test_template_hashtags_are_lowercase_strings(self) -> None:
        result = generate_caption("Marka stratejisi ve dijital büyüme hedefleri.")
        for tag in result["hashtags"]:
            assert isinstance(tag, str)
            assert tag.startswith("#")
            assert tag == tag.lower()

    def test_template_different_tones(self) -> None:
        result_pro = generate_caption("İçerik üretimi", tone="profesyonel")
        result_fun = generate_caption("İçerik üretimi", tone="eğlenceli")
        # Tones should produce different captions
        assert result_pro["caption"] != result_fun["caption"]


# ═══════════════════════════════════════════════════════════════════════════════
# Creative → content bridge (Kreatif → İçerik köprüsü)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreativeBridgeHelpers:
    """Pure unit tests for the service-layer bridge helpers."""

    def test_map_ad_channel_to_social_known(self) -> None:
        from ayaz.services.content import map_ad_channel_to_social

        assert map_ad_channel_to_social("meta") == ["instagram", "facebook"]
        assert map_ad_channel_to_social("tiktok") == ["tiktok"]
        assert map_ad_channel_to_social("google") == ["youtube"]
        assert map_ad_channel_to_social("LinkedIn") == ["linkedin"]

    def test_map_ad_channel_to_social_unknown_and_empty(self) -> None:
        from ayaz.services.content import map_ad_channel_to_social

        assert map_ad_channel_to_social(None) == ["instagram", "facebook"]
        assert map_ad_channel_to_social("") == ["instagram", "facebook"]
        assert map_ad_channel_to_social("pinterest") == ["instagram", "facebook"]

    def test_clean_ad_name_strips_jargon(self) -> None:
        from ayaz.services.content import clean_ad_name

        assert "karusel" not in clean_ad_name("Yaz İndirimi - Karusel v2").lower()
        assert "Yaz" in clean_ad_name("Yaz İndirimi - Karusel v2")

    def test_clean_ad_name_falls_back_when_all_jargon(self) -> None:
        from ayaz.services.content import clean_ad_name

        # Stripping everything would be empty → fall back to the original
        assert clean_ad_name("video kopya v1").strip() != ""

    def test_build_creative_brief_includes_theme(self) -> None:
        from ayaz.services.content import build_creative_brief

        brief = build_creative_brief("Yaz İndirimi - Karusel", "Yaz Kampanyası", "meta")
        assert "Yaz" in brief


class TestCreativeBridgeEndpoint:
    def test_from_creative_creates_draft(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/from-creative",
            json={
                "ad_name": "Yaz İndirimi - Karusel v2",
                "campaign_name": "Yaz Kampanyası",
                "channel": "meta",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["channels"] == ["instagram", "facebook"]
        assert data["body"]  # non-empty caption
        assert "karusel" not in data["title"].lower()

    def test_from_creative_maps_tiktok(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/from-creative",
            json={"ad_name": "Dans Challenge", "channel": "tiktok"},
        )
        assert resp.status_code == 201
        assert resp.json()["channels"] == ["tiktok"]

    def test_from_creative_unknown_channel_defaults(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/from-creative",
            json={"ad_name": "Genel Kampanya"},
        )
        assert resp.status_code == 201
        assert resp.json()["channels"] == ["instagram", "facebook"]

    def test_from_creative_appends_hashtags_to_body(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/content/from-creative",
            json={"ad_name": "Sürdürülebilir Moda Koleksiyonu", "channel": "instagram"},
        )
        assert resp.status_code == 201
        assert "#" in resp.json()["body"]

    def test_from_creative_requires_ad_name(self, client: TestClient) -> None:
        resp = client.post("/api/v1/content/from-creative", json={})
        assert resp.status_code == 422
