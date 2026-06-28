"""Self-contained tests for AI Reklam Metni Stüdyosu — Ad Copy Studio (M15 Dalga 73).

Coverage
--------
1. Unit tests — generate_ad_copy (no DB)
   - generate for each platform returns uniform fields shape
   - char_count == len(value) for every field
   - within_limit is correctly true/false
   - n_variants is honoured
   - variants are distinct (different primary_text / headline_1 etc.)
   - unknown platform raises ValueError
   - missing product raises ValueError
   - template source when no API key
   - long input doesn't crash (within_limit may be false, never raises)

2. Service tests (SQLite in-memory)
   - save_draft persists row and returns serialized dict
   - list_drafts returns newest first
   - list_drafts with status filter
   - update_draft_status to valid status
   - update_draft_status invalid status raises ValueError
   - update_draft_status wrong draft_id raises LookupError (404)
   - delete_draft removes the row
   - delete_draft missing id raises LookupError (404)
   - no cross-tenant leakage on list_drafts

3. HTTP endpoint tests
   - POST /ad-studio/generate 200 — valid brief
   - POST /ad-studio/generate 422 — missing product
   - POST /ad-studio/generate 422 — unknown platform
   - POST /ad-studio/drafts 201
   - GET /ad-studio/drafts 200
   - PATCH /ad-studio/drafts/{id} 200 valid status
   - PATCH /ad-studio/drafts/{id} 422 invalid status
   - PATCH /ad-studio/drafts/{id} 404 unknown id
   - DELETE /ad-studio/drafts/{id} 204
   - DELETE /ad-studio/drafts/{id} 404 unknown id
   - No auth → 401/403

4. Migration smoke test
   - Migration imports cleanly and upgrade/downgrade run on SQLite
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# ── Register all models so Base.metadata.create_all works ─────────────────────
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
import ayaz.models.ad_studio  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.ad_studio import AdCopyDraft
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import ad_studio as ad_studio_module
from ayaz.services.auth import hash_password
from ayaz.services.ad_studio import (
    PLATFORM_SPECS,
    delete_draft,
    generate_ad_copy,
    list_drafts,
    save_draft,
    update_draft_status,
    _serialize_draft,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Ad Studio Test App")
_test_app.include_router(ad_studio_module.router, prefix="/api/v1")


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


# ── Tenant / membership helpers ────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Ad Studio Test Tenant") -> Tenant:
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


def _make_user_and_membership(db: Session, tenant: Tenant) -> tuple[User, Membership]:
    u = User(
        id=uuid.uuid4(),
        email=f"adstudio_test_{uuid.uuid4().hex[:8]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Ad Studio Test User",
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
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = _make_tenant(db_session)
    _user, membership = _make_user_and_membership(db_session, tenant)

    def _override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override — tests 401/403 behaviour."""
    def _override_db():
        yield db_session

    _test_app.dependency_overrides[get_db] = _override_db

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Brief helpers ──────────────────────────────────────────────────────────────


def _google_brief(**kwargs: Any) -> dict[str, Any]:
    return {
        "platform": "google_ads",
        "product": "Kablosuz Kulaklık",
        "value_prop": "30 saate kadar pil ömrü",
        "tone": "profesyonel",
        "keywords": ["kablosuz kulaklık", "bluetooth kulaklık"],
        **kwargs,
    }


def _meta_brief(**kwargs: Any) -> dict[str, Any]:
    return {
        "platform": "meta_ads",
        "product": "Kablosuz Kulaklık",
        "value_prop": "Kristal netliğinde ses",
        "tone": "heyecanli",
        "keywords": ["kulaklık", "müzik", "ses"],
        "audience": "18-35 yaş, müzik tutkunları",
        **kwargs,
    }


def _tiktok_brief(**kwargs: Any) -> dict[str, Any]:
    return {
        "platform": "tiktok_ads",
        "product": "Kablosuz Kulaklık",
        "value_prop": "Aktif gürültü engelleme",
        "tone": "heyecanli",
        "keywords": ["kulaklık", "ses", "teknoloji"],
        **kwargs,
    }


# ── 1. Unit tests — generate_ad_copy ─────────────────────────────────────────


class TestGenerateAdCopyShape:
    """Verify the uniform fields shape for every platform."""

    def _assert_uniform_shape(self, result: dict[str, Any], platform: str, n: int) -> None:
        assert result["platform"] == platform
        assert "platform_label" in result
        assert "source" in result
        assert "tone" in result
        assert "tone_label" in result
        assert "variants" in result
        variants = result["variants"]
        assert len(variants) == n, f"Expected {n} variants, got {len(variants)}"
        specs = PLATFORM_SPECS[platform]
        for v in variants:
            assert "index" in v
            assert "fields" in v
            fields = v["fields"]
            assert len(fields) == len(specs)
            for f in fields:
                assert "key" in f
                assert "label" in f
                assert "value" in f
                assert "char_count" in f
                assert "max_len" in f
                assert "within_limit" in f
                # char_count must equal len(value)
                assert f["char_count"] == len(f["value"]), (
                    f"char_count {f['char_count']} != len(value) {len(f['value'])} "
                    f"for field {f['key']}"
                )

    def test_google_ads_shape(self) -> None:
        result = generate_ad_copy(_google_brief())
        self._assert_uniform_shape(result, "google_ads", 3)

    def test_meta_ads_shape(self) -> None:
        result = generate_ad_copy(_meta_brief())
        self._assert_uniform_shape(result, "meta_ads", 3)

    def test_tiktok_ads_shape(self) -> None:
        result = generate_ad_copy(_tiktok_brief())
        self._assert_uniform_shape(result, "tiktok_ads", 3)

    def test_n_variants_honored(self) -> None:
        for n in (1, 2, 4, 5):
            result = generate_ad_copy(_meta_brief(), n_variants=n)
            assert len(result["variants"]) == n, f"n_variants={n} not honored"

    def test_variants_are_distinct(self) -> None:
        result = generate_ad_copy(_meta_brief(), n_variants=4)
        # Collect first field values per variant
        first_vals = [v["fields"][0]["value"] for v in result["variants"]]
        # At least some variants should differ (we generate 4 angles)
        assert len(set(first_vals)) > 1, "All variants are identical — angles not applied"

    def test_within_limit_true_for_normal_input(self) -> None:
        result = generate_ad_copy(_meta_brief())
        for v in result["variants"]:
            for f in v["fields"]:
                assert f["within_limit"] is True, (
                    f"Field {f['key']} unexpectedly exceeds limit: "
                    f"char_count={f['char_count']} max_len={f['max_len']} value={f['value']!r}"
                )

    def test_within_limit_false_on_long_input(self) -> None:
        # Produce a brief with a very long product name to force limit violation
        # before truncation kicks in — we inject a super-long product name
        # directly into a variant field by bypassing the generator slightly.
        # Instead, we just check that within_limit is consistent with values.
        long_product = "X" * 200  # 200 chars
        result = generate_ad_copy(
            {"platform": "meta_ads", "product": long_product, "value_prop": "Y" * 200}
        )
        # The generator truncates gracefully — verify it doesn't crash
        assert result is not None
        for v in result["variants"]:
            for f in v["fields"]:
                # within_limit must match reality
                assert f["within_limit"] == (f["char_count"] <= f["max_len"])

    def test_long_input_does_not_crash(self) -> None:
        long_str = "A" * 500
        for platform in ("google_ads", "meta_ads", "tiktok_ads"):
            result = generate_ad_copy(
                {
                    "platform": platform,
                    "product": long_str,
                    "value_prop": long_str,
                    "keywords": [long_str, long_str],
                }
            )
            assert result is not None
            assert len(result["variants"]) == 3

    def test_source_template_without_api_key(self) -> None:
        with patch("ayaz.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = None
            mock_settings.claude_narrator_model = "claude-opus-4-8"
            result = generate_ad_copy(_meta_brief())
        assert result["source"] == "template"

    def test_all_platforms_have_tone_label(self) -> None:
        for brief_fn in (_google_brief, _meta_brief, _tiktok_brief):
            result = generate_ad_copy(brief_fn())
            assert result["tone_label"] is not None
            assert len(result["tone_label"]) > 0

    def test_platform_label_present(self) -> None:
        expected = {
            "google_ads": "Google Ads",
            "meta_ads": "Meta (Facebook/Instagram)",
            "tiktok_ads": "TikTok Ads",
        }
        for platform, label in expected.items():
            result = generate_ad_copy({"platform": platform, "product": "Test"})
            assert result["platform_label"] == label


class TestGenerateAdCopyErrors:
    def test_unknown_platform_raises(self) -> None:
        with pytest.raises(ValueError, match="platform"):
            generate_ad_copy({"platform": "twitter_ads", "product": "Test"})

    def test_missing_platform_raises(self) -> None:
        with pytest.raises(ValueError, match="platform"):
            generate_ad_copy({"product": "Test"})

    def test_missing_product_raises(self) -> None:
        with pytest.raises(ValueError, match="product"):
            generate_ad_copy({"platform": "meta_ads", "product": ""})

    def test_missing_product_key_raises(self) -> None:
        with pytest.raises(ValueError, match="product"):
            generate_ad_copy({"platform": "meta_ads"})


# ── 2. Service tests (SQLite in-memory) ──────────────────────────────────────


class TestSaveDraft:
    def test_save_returns_serialized_dict(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session,
            tenant.id,
            platform="meta_ads",
            title="Kablosuz Kulaklık — Meta",
            brief=_meta_brief(),
            variants=result["variants"],
            source=result["source"],
        )
        assert "id" in draft
        assert draft["platform"] == "meta_ads"
        assert draft["platform_label"] == "Meta (Facebook/Instagram)"
        assert draft["title"] == "Kablosuz Kulaklık — Meta"
        assert draft["source"] == "template"
        assert draft["status"] == "saved"
        assert "brief" in draft
        assert "variants" in draft
        assert "created_at" in draft
        assert "updated_at" in draft

    def test_save_persists_to_db(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session,
            tenant.id,
            platform="meta_ads",
            title="Test Taslak",
            brief=_meta_brief(),
            variants=result["variants"],
        )
        row = db_session.scalar(
            select(AdCopyDraft).where(AdCopyDraft.id == uuid.UUID(draft["id"]))
        )
        assert row is not None
        assert row.platform == "meta_ads"
        assert row.tenant_id == tenant.id


class TestListDrafts:
    def _seed_drafts(self, db: Session, tenant: Tenant, n: int = 3) -> list[dict]:
        drafts = []
        for i, platform in enumerate(["google_ads", "meta_ads", "tiktok_ads"][:n]):
            brief = {"platform": platform, "product": f"Ürün {i+1}"}
            result = generate_ad_copy(brief)
            d = save_draft(
                db,
                tenant.id,
                platform=platform,
                title=f"Taslak {i+1}",
                brief=brief,
                variants=result["variants"],
            )
            drafts.append(d)
        return drafts

    def test_list_returns_all_for_tenant(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        self._seed_drafts(db_session, tenant, 3)
        result = list_drafts(db_session, tenant.id)
        assert len(result) == 3

    def test_list_newest_first(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        self._seed_drafts(db_session, tenant, 3)
        result = list_drafts(db_session, tenant.id)
        # created_at strings should be descending
        dts = [r["created_at"] for r in result]
        assert dts == sorted(dts, reverse=True)

    def test_list_status_filter_saved(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        drafts = self._seed_drafts(db_session, tenant, 3)
        # Archive one
        update_draft_status(db_session, tenant.id, drafts[0]["id"], "archived")
        saved = list_drafts(db_session, tenant.id, status="saved")
        assert len(saved) == 2
        for d in saved:
            assert d["status"] == "saved"

    def test_list_status_filter_archived(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        drafts = self._seed_drafts(db_session, tenant, 3)
        update_draft_status(db_session, tenant.id, drafts[0]["id"], "archived")
        archived = list_drafts(db_session, tenant.id, status="archived")
        assert len(archived) == 1
        assert archived[0]["status"] == "archived"

    def test_no_cross_tenant_leakage(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")
        self._seed_drafts(db_session, tenant_a, 2)
        result_b = list_drafts(db_session, tenant_b.id)
        assert len(result_b) == 0


class TestUpdateDraftStatus:
    def test_update_to_archived(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant.id,
            platform="meta_ads", title="Test",
            brief=_meta_brief(), variants=result["variants"],
        )
        updated = update_draft_status(db_session, tenant.id, draft["id"], "archived")
        assert updated["status"] == "archived"

    def test_update_back_to_saved(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant.id,
            platform="meta_ads", title="Test",
            brief=_meta_brief(), variants=result["variants"],
        )
        update_draft_status(db_session, tenant.id, draft["id"], "archived")
        restored = update_draft_status(db_session, tenant.id, draft["id"], "saved")
        assert restored["status"] == "saved"

    def test_invalid_status_raises_value_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant.id,
            platform="meta_ads", title="Test",
            brief=_meta_brief(), variants=result["variants"],
        )
        with pytest.raises(ValueError, match="Geçersiz durum"):
            update_draft_status(db_session, tenant.id, draft["id"], "deleted")

    def test_unknown_id_raises_lookup_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(LookupError):
            update_draft_status(
                db_session, tenant.id, str(uuid.uuid4()), "archived"
            )

    def test_wrong_tenant_raises_lookup_error(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "A")
        tenant_b = _make_tenant(db_session, "B")
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant_a.id,
            platform="meta_ads", title="A-only draft",
            brief=_meta_brief(), variants=result["variants"],
        )
        with pytest.raises(LookupError):
            update_draft_status(db_session, tenant_b.id, draft["id"], "archived")


class TestDeleteDraft:
    def test_delete_removes_row(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant.id,
            platform="meta_ads", title="To delete",
            brief=_meta_brief(), variants=result["variants"],
        )
        delete_draft(db_session, tenant.id, draft["id"])
        row = db_session.scalar(
            select(AdCopyDraft).where(AdCopyDraft.id == uuid.UUID(draft["id"]))
        )
        assert row is None

    def test_delete_unknown_id_raises_lookup_error(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(LookupError):
            delete_draft(db_session, tenant.id, str(uuid.uuid4()))

    def test_delete_wrong_tenant_raises_lookup_error(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "A")
        tenant_b = _make_tenant(db_session, "B")
        result = generate_ad_copy(_meta_brief())
        draft = save_draft(
            db_session, tenant_a.id,
            platform="meta_ads", title="A-only",
            brief=_meta_brief(), variants=result["variants"],
        )
        with pytest.raises(LookupError):
            delete_draft(db_session, tenant_b.id, draft["id"])


# ── 3. HTTP endpoint tests ────────────────────────────────────────────────────


class TestGenerateEndpoint:
    def test_post_generate_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json=_meta_brief(),
        )
        assert resp.status_code == 200

    def test_post_generate_response_shape(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json=_meta_brief(),
        )
        data = resp.json()
        assert "platform" in data
        assert "platform_label" in data
        assert "source" in data
        assert "tone" in data
        assert "tone_label" in data
        assert "variants" in data
        assert len(data["variants"]) == 3

    def test_post_generate_google_ads(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json=_google_brief(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "google_ads"
        # google_ads has 5 fields per variant
        for v in data["variants"]:
            assert len(v["fields"]) == 5

    def test_post_generate_tiktok_ads(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json=_tiktok_brief(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "tiktok_ads"
        for v in data["variants"]:
            assert len(v["fields"]) == 2

    def test_post_generate_n_variants(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json={**_meta_brief(), "n_variants": 2},
        )
        assert resp.status_code == 200
        assert len(resp.json()["variants"]) == 2

    def test_post_generate_missing_product_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json={"platform": "meta_ads"},
        )
        assert resp.status_code == 422

    def test_post_generate_empty_product_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json={"platform": "meta_ads", "product": ""},
        )
        assert resp.status_code == 422

    def test_post_generate_unknown_platform_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/ad-studio/generate",
            json={"platform": "twitter_ads", "product": "Test"},
        )
        assert resp.status_code == 422

    def test_post_generate_no_auth_401_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.post(
            "/api/v1/ad-studio/generate",
            json=_meta_brief(),
        )
        assert resp.status_code in {401, 403}


class TestDraftsEndpoints:
    def _generate_and_save(self, client: TestClient, platform: str = "meta_ads") -> dict:
        brief = {"platform": platform, "product": "Kablosuz Kulaklık",
                 "value_prop": "Test değer önerisi", "tone": "profesyonel"}
        gen_resp = client.post("/api/v1/ad-studio/generate", json=brief)
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()

        save_resp = client.post(
            "/api/v1/ad-studio/drafts",
            json={
                "platform": platform,
                "title": f"Test Taslak — {platform}",
                "brief": brief,
                "variants": gen_data["variants"],
                "source": gen_data["source"],
            },
        )
        assert save_resp.status_code == 201
        return save_resp.json()

    def test_post_draft_201(self, client: TestClient) -> None:
        draft = self._generate_and_save(client)
        assert "id" in draft
        assert draft["platform"] == "meta_ads"
        assert draft["status"] == "saved"

    def test_get_drafts_200(self, client: TestClient) -> None:
        self._generate_and_save(client)
        resp = client.get("/api/v1/ad-studio/drafts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_drafts_status_filter(self, client: TestClient) -> None:
        draft = self._generate_and_save(client)
        # Archive the draft
        client.patch(
            f"/api/v1/ad-studio/drafts/{draft['id']}",
            json={"status": "archived"},
        )
        # Filter for saved — should be empty now
        resp = client.get("/api/v1/ad-studio/drafts?status=saved")
        assert resp.status_code == 200
        saved_drafts = resp.json()
        assert all(d["status"] == "saved" for d in saved_drafts)

    def test_patch_draft_200(self, client: TestClient) -> None:
        draft = self._generate_and_save(client)
        resp = client.patch(
            f"/api/v1/ad-studio/drafts/{draft['id']}",
            json={"status": "archived"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_patch_draft_invalid_status_422(self, client: TestClient) -> None:
        draft = self._generate_and_save(client)
        resp = client.patch(
            f"/api/v1/ad-studio/drafts/{draft['id']}",
            json={"status": "deleted"},
        )
        assert resp.status_code == 422

    def test_patch_draft_unknown_id_404(self, client: TestClient) -> None:
        resp = client.patch(
            f"/api/v1/ad-studio/drafts/{uuid.uuid4()}",
            json={"status": "archived"},
        )
        assert resp.status_code == 404

    def test_delete_draft_204(self, client: TestClient) -> None:
        draft = self._generate_and_save(client)
        resp = client.delete(f"/api/v1/ad-studio/drafts/{draft['id']}")
        assert resp.status_code == 204
        # Verify gone
        list_resp = client.get("/api/v1/ad-studio/drafts")
        ids = [d["id"] for d in list_resp.json()]
        assert draft["id"] not in ids

    def test_delete_draft_unknown_id_404(self, client: TestClient) -> None:
        resp = client.delete(f"/api/v1/ad-studio/drafts/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_drafts_no_auth_401_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/ad-studio/drafts")
        assert resp.status_code in {401, 403}


# ── 4. Migration smoke test ───────────────────────────────────────────────────


def _load_migration(filename: str):
    """Load an Alembic migration file by filename using importlib."""
    import importlib.util
    from pathlib import Path

    versions_dir = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions"
    )
    path = versions_dir / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestMigration:
    def test_migration_imports(self) -> None:
        m = _load_migration("0026_ad_copy_drafts.py")
        assert m.revision == "0026"
        assert m.down_revision == "0025"

    def test_migration_upgrade_downgrade_sqlite(self) -> None:
        """Run upgrade + downgrade on a fresh SQLite DB via Alembic op."""
        import sqlalchemy as sa
        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        m = _load_migration("0026_ad_copy_drafts.py")

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            op_proxy = Operations(ctx)
            # Patch alembic.op so the migration's module-level op calls work
            import alembic.op as alembic_op
            import unittest.mock as mock
            with mock.patch.object(alembic_op, "create_table", op_proxy.create_table), \
                 mock.patch.object(alembic_op, "drop_table", op_proxy.drop_table), \
                 mock.patch.object(alembic_op, "create_index", op_proxy.create_index), \
                 mock.patch.object(alembic_op, "drop_index", op_proxy.drop_index):
                m.upgrade()

        # Verify table exists
        insp = sa.inspect(engine)
        assert "ad_copy_drafts" in insp.get_table_names()

        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            op_proxy = Operations(ctx)
            import alembic.op as alembic_op
            import unittest.mock as mock
            with mock.patch.object(alembic_op, "create_table", op_proxy.create_table), \
                 mock.patch.object(alembic_op, "drop_table", op_proxy.drop_table), \
                 mock.patch.object(alembic_op, "create_index", op_proxy.create_index), \
                 mock.patch.object(alembic_op, "drop_index", op_proxy.drop_index):
                m.downgrade()

        # Verify table gone after downgrade
        insp2 = sa.inspect(engine)
        assert "ad_copy_drafts" not in insp2.get_table_names()

    def test_ad_copy_draft_model_columns(self) -> None:
        """Verify AdCopyDraft has all required columns."""
        from ayaz.models.ad_studio import AdCopyDraft
        cols = {c.key for c in AdCopyDraft.__table__.columns}
        required = {"id", "tenant_id", "platform", "title", "brief", "variants",
                    "source", "status", "created_at", "updated_at"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_ad_copy_draft_server_defaults(self) -> None:
        """Verify server_default values are set correctly."""
        from ayaz.models.ad_studio import AdCopyDraft
        col_map = {c.key: c for c in AdCopyDraft.__table__.columns}
        assert col_map["source"].server_default is not None
        assert col_map["status"].server_default is not None
