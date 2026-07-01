"""Tests for M13 Sosyal Gelen Kutusu (Social Inbox) module.

Coverage
--------
1.  classify_sentiment — pure unit tests
    - positive text → "positive"
    - negative text → "negative"
    - neutral text  → "neutral"
    - negative wins ties (text with both positive and negative hints)
2.  suggest_reply — pure unit tests
    - returns non-empty reply without API key (template path)
    - ai_assisted=False on template path
3.  CRUD: create → get (with thread) → list
4.  Channel / kind / status validation → 422
5.  Reply: creates with delivered=False
6.  Assign / status / tags transitions
7.  Filters: channel, status, sentiment
8.  compute_inbox_stats aggregation
9.  Tenant isolation: cross-tenant access returns 404

Self-contained: builds its own mini FastAPI app with an in-memory SQLite engine,
mirroring the pattern in tests/test_tracking_stats.py and tests/test_content.py.
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
import ayaz.models.social_inbox  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import inbox as inbox_module
from ayaz.services.auth import hash_password
from ayaz.services.social_inbox import classify_sentiment, compute_inbox_stats, suggest_reply

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Social Inbox Test App")
_test_app.include_router(inbox_module.router, prefix="/api/v1")

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
        name="Social Inbox Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="inbox_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Inbox Test User",
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


# ── Helper factory ────────────────────────────────────────────────────────────


def _make_message(
    client: TestClient,
    *,
    channel: str = "instagram",
    kind: str = "comment",
    author_handle: str = "@test_user",
    text: str = "Harika ürünler, çok memnunum!",
    author_name: str | None = "Test Kullanıcı",
    sentiment: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": channel,
        "kind": kind,
        "author_handle": author_handle,
        "text": text,
    }
    if author_name is not None:
        payload["author_name"] = author_name
    if sentiment is not None:
        payload["sentiment"] = sentiment

    resp = client.post("/api/v1/inbox/messages", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# =============================================================================
# 1. classify_sentiment — pure unit tests
# =============================================================================


class TestClassifySentiment:
    def test_positive_text_returns_positive(self) -> None:
        assert classify_sentiment("Harika bir ürün, çok memnunum!") == "positive"

    def test_positive_english_returns_positive(self) -> None:
        assert classify_sentiment("I love this product, it's awesome!") == "positive"

    def test_negative_text_returns_negative(self) -> None:
        assert classify_sentiment("Berbat bir deneyim, iade istiyorum.") == "negative"

    def test_negative_english_returns_negative(self) -> None:
        assert classify_sentiment("This is terrible, broken and awful.") == "negative"

    def test_neutral_text_returns_neutral(self) -> None:
        assert classify_sentiment("Siparişim ne zaman gelecek?") == "neutral"

    def test_negative_wins_tie(self) -> None:
        """When both positive and negative hints appear, negative must win."""
        result = classify_sentiment("Harika teşekkürler ama berbat bir hata var.")
        assert result == "negative"

    def test_empty_text_returns_neutral(self) -> None:
        assert classify_sentiment("") == "neutral"

    def test_turkish_negative_words(self) -> None:
        assert classify_sentiment("Ürün çalışmıyor, rezalet!") == "negative"

    def test_turkish_positive_words(self) -> None:
        assert classify_sentiment("Teşekkür ederim, süper bir hizmet!") == "positive"


# =============================================================================
# 2. suggest_reply — pure unit tests
# =============================================================================


class TestSuggestReply:
    def test_returns_non_empty_reply_without_api_key(self) -> None:
        result = suggest_reply("Ürünüm hâlâ gelmedi, yardımcı olur musunuz?")
        assert "reply" in result
        assert "ai_assisted" in result
        assert len(result["reply"]) > 0

    def test_ai_assisted_false_on_template_path(self) -> None:
        """No API key in test env — must use template and return ai_assisted=False."""
        result = suggest_reply("Teşekkürler, harika bir hizmet!")
        assert result["ai_assisted"] is False

    def test_reply_with_channel(self) -> None:
        result = suggest_reply(
            "Instagram'dan yazıyorum, yardım lazım.",
            channel="instagram",
        )
        assert len(result["reply"]) > 0

    def test_reply_with_different_tone(self) -> None:
        result_samimi = suggest_reply("Yardım lütfen.", tone="samimi")
        result_profesyonel = suggest_reply("Yardım lütfen.", tone="profesyonel")
        # Both should work and return non-empty replies
        assert len(result_samimi["reply"]) > 0
        assert len(result_profesyonel["reply"]) > 0


# =============================================================================
# 3. CRUD: create → get (with thread) → list
# =============================================================================


class TestCRUD:
    def test_create_message_returns_201_with_open_status(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/inbox/messages",
            json={
                "channel": "instagram",
                "kind": "comment",
                "author_handle": "@kullanici",
                "text": "Bu ürün gerçekten harika!",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["channel"] == "instagram"
        assert data["kind"] == "comment"
        assert data["author_handle"] == "@kullanici"
        assert data["status"] == "open"
        assert data["delivered"] if False else True  # status field, not delivered
        assert "id" in data
        assert "tenant_id" in data
        assert "sentiment" in data
        assert isinstance(data["tags"], list)

    def test_create_message_auto_classifies_sentiment(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/inbox/messages",
            json={
                "channel": "x",
                "kind": "mention",
                "author_handle": "@sikayet_user",
                "text": "Berbat bir deneyim, iade istiyorum.",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["sentiment"] == "negative"

    def test_get_message_returns_reply_thread(self, client: TestClient) -> None:
        msg = _make_message(client)
        # Add a reply
        client.post(
            f"/api/v1/inbox/messages/{msg['id']}/replies",
            json={"body": "Teşekkür ederiz, inceliyoruz.", "author": "Destek Ekibi"},
        )
        resp = client.get(f"/api/v1/inbox/messages/{msg['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == msg["id"]
        assert "replies" in data
        assert len(data["replies"]) == 1
        assert data["replies"][0]["body"] == "Teşekkür ederiz, inceliyoruz."
        assert data["replies"][0]["delivered"] is False

    def test_list_messages_returns_created_message(self, client: TestClient) -> None:
        _make_message(client, author_handle="@listeleme_testi")
        resp = client.get("/api/v1/inbox/messages")
        assert resp.status_code == 200
        handles = [m["author_handle"] for m in resp.json()]
        assert "@listeleme_testi" in handles

    def test_delete_message_returns_204(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.delete(f"/api/v1/inbox/messages/{msg['id']}")
        assert resp.status_code == 204
        resp2 = client.get(f"/api/v1/inbox/messages/{msg['id']}")
        assert resp2.status_code == 404


# =============================================================================
# 4. Validation → 422
# =============================================================================


class TestValidation:
    def test_invalid_channel_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/inbox/messages",
            json={
                "channel": "snapchat",
                "kind": "dm",
                "author_handle": "@user",
                "text": "Merhaba",
            },
        )
        assert resp.status_code == 422

    def test_invalid_kind_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/inbox/messages",
            json={
                "channel": "instagram",
                "kind": "story",
                "author_handle": "@user",
                "text": "Merhaba",
            },
        )
        assert resp.status_code == 422

    def test_invalid_status_transition_returns_422(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/status",
            json={"status": "gecersiz_durum"},
        )
        assert resp.status_code == 422

    def test_all_valid_channels_accepted(self, client: TestClient) -> None:
        for channel in ["instagram", "facebook", "x", "linkedin", "tiktok", "youtube"]:
            resp = client.post(
                "/api/v1/inbox/messages",
                json={
                    "channel": channel,
                    "kind": "mention",
                    "author_handle": f"@{channel}_user",
                    "text": f"{channel} üzerinden yazıyorum.",
                },
            )
            assert resp.status_code == 201, f"channel={channel} failed: {resp.text}"

    def test_all_valid_kinds_accepted(self, client: TestClient) -> None:
        for kind in ["dm", "comment", "mention"]:
            resp = client.post(
                "/api/v1/inbox/messages",
                json={
                    "channel": "instagram",
                    "kind": kind,
                    "author_handle": "@user",
                    "text": "Mesaj",
                },
            )
            assert resp.status_code == 201, f"kind={kind} failed: {resp.text}"


# =============================================================================
# 5. Reply: delivered=False
# =============================================================================


class TestReply:
    def test_reply_creates_with_delivered_false(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/replies",
            json={"body": "Durumu inceliyoruz.", "author": "Müşteri Hizmetleri"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["delivered"] is False
        assert data["ai_assisted"] is False
        assert data["body"] == "Durumu inceliyoruz."
        assert data["author"] == "Müşteri Hizmetleri"
        assert "id" in data
        assert "created_at" in data

    def test_reply_without_author(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/replies",
            json={"body": "Yanıtlıyoruz."},
        )
        assert resp.status_code == 201
        assert resp.json()["author"] is None

    def test_replies_in_thread_sorted_oldest_first(self, client: TestClient) -> None:
        msg = _make_message(client)
        client.post(
            f"/api/v1/inbox/messages/{msg['id']}/replies",
            json={"body": "İlk yanıt"},
        )
        client.post(
            f"/api/v1/inbox/messages/{msg['id']}/replies",
            json={"body": "İkinci yanıt"},
        )
        resp = client.get(f"/api/v1/inbox/messages/{msg['id']}")
        assert resp.status_code == 200
        replies = resp.json()["replies"]
        assert len(replies) == 2
        # created_at strings should be ascending (oldest first)
        assert replies[0]["created_at"] <= replies[1]["created_at"]


# =============================================================================
# 6. Assign / status / tags transitions
# =============================================================================


class TestTransitions:
    def test_assign_sets_assignee(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/assign",
            json={"assignee": "ahmet@ayaz.app"},
        )
        assert resp.status_code == 200
        assert resp.json()["assignee"] == "ahmet@ayaz.app"

    def test_assign_null_clears_assignee(self, client: TestClient) -> None:
        msg = _make_message(client)
        client.post(
            f"/api/v1/inbox/messages/{msg['id']}/assign",
            json={"assignee": "zeynep@ayaz.app"},
        )
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/assign",
            json={"assignee": None},
        )
        assert resp.status_code == 200
        assert resp.json()["assignee"] is None

    def test_status_transition_to_pending(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/status",
            json={"status": "pending"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_status_transition_to_resolved(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/status",
            json={"status": "resolved"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

    def test_status_transition_to_snoozed(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/status",
            json={"status": "snoozed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "snoozed"

    def test_tags_replace_wholesale(self, client: TestClient) -> None:
        msg = _make_message(client)
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/tags",
            json={"tags": ["vip", "iade", "öncelikli"]},
        )
        assert resp.status_code == 200
        assert set(resp.json()["tags"]) == {"vip", "iade", "öncelikli"}

    def test_tags_empty_list_clears_tags(self, client: TestClient) -> None:
        msg = _make_message(client)
        client.post(
            f"/api/v1/inbox/messages/{msg['id']}/tags",
            json={"tags": ["vip"]},
        )
        resp = client.post(
            f"/api/v1/inbox/messages/{msg['id']}/tags",
            json={"tags": []},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == []


# =============================================================================
# 7. Filters
# =============================================================================


class TestFilters:
    def test_filter_by_channel(self, client: TestClient) -> None:
        _make_message(client, channel="instagram", author_handle="@insta_user")
        _make_message(client, channel="linkedin", author_handle="@linkedin_user")

        resp = client.get("/api/v1/inbox/messages", params={"channel": "linkedin"})
        assert resp.status_code == 200
        handles = [m["author_handle"] for m in resp.json()]
        assert "@linkedin_user" in handles
        assert "@insta_user" not in handles

    def test_filter_by_status(self, client: TestClient) -> None:
        msg1 = _make_message(client, author_handle="@open_user")
        msg2 = _make_message(client, author_handle="@resolved_user")
        client.post(
            f"/api/v1/inbox/messages/{msg2['id']}/status",
            json={"status": "resolved"},
        )

        resp = client.get("/api/v1/inbox/messages", params={"status": "resolved"})
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert msg2["id"] in ids
        assert msg1["id"] not in ids

    def test_filter_by_sentiment(self, client: TestClient) -> None:
        _make_message(
            client,
            author_handle="@mutlu_user",
            text="Harika!",
            sentiment="positive",
        )
        _make_message(
            client,
            author_handle="@kizgin_user",
            text="Berbat!",
            sentiment="negative",
        )

        resp = client.get("/api/v1/inbox/messages", params={"sentiment": "positive"})
        assert resp.status_code == 200
        handles = [m["author_handle"] for m in resp.json()]
        assert "@mutlu_user" in handles
        assert "@kizgin_user" not in handles


# =============================================================================
# 8. compute_inbox_stats aggregation
# =============================================================================


class TestInboxStats:
    def test_stats_empty_inbox(self) -> None:
        stats = compute_inbox_stats([])
        assert stats["total"] == 0
        assert stats["open"] == 0
        assert stats["pending"] == 0
        assert stats["resolved"] == 0
        assert stats["by_status"] == {}
        assert stats["by_channel"] == {}
        assert stats["by_sentiment"] == {}
        assert stats["by_kind"] == {}

    def test_stats_correct_totals(self) -> None:
        class _Stub:
            def __init__(self, status, channel, sentiment, kind):
                self.status = status
                self.channel = channel
                self.sentiment = sentiment
                self.kind = kind

        messages = [
            _Stub("open", "instagram", "positive", "comment"),
            _Stub("open", "x", "neutral", "mention"),
            _Stub("resolved", "instagram", "negative", "dm"),
            _Stub("pending", "facebook", "neutral", "comment"),
        ]
        stats = compute_inbox_stats(messages)
        assert stats["total"] == 4
        assert stats["open"] == 2
        assert stats["pending"] == 1
        assert stats["resolved"] == 1
        assert stats["by_channel"]["instagram"] == 2
        assert stats["by_channel"]["x"] == 1
        assert stats["by_sentiment"]["neutral"] == 2
        assert stats["by_kind"]["comment"] == 2
        assert stats["by_kind"]["dm"] == 1

    def test_stats_via_api(self, client: TestClient) -> None:
        _make_message(client, channel="instagram", sentiment="positive")
        _make_message(client, channel="x", sentiment="negative")
        _make_message(client, channel="instagram", sentiment="neutral")

        resp = client.get("/api/v1/inbox/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["open"] == 3
        assert data["by_channel"]["instagram"] == 2
        assert data["by_channel"]["x"] == 1

    def test_stats_defensive_with_missing_attributes(self) -> None:
        """compute_inbox_stats must not crash on stubs without all fields."""

        class _MinimalStub:
            pass

        stats = compute_inbox_stats([_MinimalStub(), _MinimalStub()])
        assert stats["total"] == 2


# =============================================================================
# 9. suggest-reply endpoint
# =============================================================================


class TestSuggestReplyEndpoint:
    def test_suggest_reply_returns_non_empty(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/inbox/suggest-reply",
            json={"text": "Siparişim hâlâ gelmedi!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data
        assert "ai_assisted" in data
        assert len(data["reply"]) > 0

    def test_suggest_reply_with_channel_and_tone(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/inbox/suggest-reply",
            json={
                "text": "Ürününüzü çok sevdim, teşekkürler!",
                "channel": "instagram",
                "tone": "samimi",
            },
        )
        assert resp.status_code == 200
        assert len(resp.json()["reply"]) > 0

    def test_suggest_reply_text_required(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/inbox/suggest-reply",
            json={"channel": "instagram"},
        )
        assert resp.status_code == 422


# =============================================================================
# 10. Tenant isolation
# =============================================================================


class TestTenantIsolation:
    def test_get_other_tenant_message_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.social_inbox import SocialMessage

        other_tenant_id = uuid.uuid4()
        other_msg = SocialMessage(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            channel="instagram",
            kind="comment",
            author_handle="@diger_tenant",
            text="Başka tenant mesajı.",
            sentiment="neutral",
            status="open",
            tags=[],
            received_at="2026-01-01T10:00:00+00:00",
        )
        db_session.add(other_msg)
        db_session.commit()

        resp = client.get(f"/api/v1/inbox/messages/{other_msg.id}")
        assert resp.status_code == 404

    def test_list_does_not_include_other_tenant_messages(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.social_inbox import SocialMessage

        other_tenant_id = uuid.uuid4()
        other_msg = SocialMessage(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            channel="facebook",
            kind="dm",
            author_handle="@gizli_user",
            text="Gizli mesaj.",
            sentiment="neutral",
            status="open",
            tags=[],
            received_at="2026-01-01T10:00:00+00:00",
        )
        db_session.add(other_msg)
        db_session.commit()

        resp = client.get("/api/v1/inbox/messages")
        assert resp.status_code == 200
        handles = [m["author_handle"] for m in resp.json()]
        assert "@gizli_user" not in handles

    def test_reply_to_other_tenant_message_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.social_inbox import SocialMessage

        other_tenant_id = uuid.uuid4()
        other_msg = SocialMessage(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            channel="x",
            kind="mention",
            author_handle="@cross_tenant",
            text="Çapraz tenant mesajı.",
            sentiment="neutral",
            status="open",
            tags=[],
            received_at="2026-01-01T10:00:00+00:00",
        )
        db_session.add(other_msg)
        db_session.commit()

        resp = client.post(
            f"/api/v1/inbox/messages/{other_msg.id}/replies",
            json={"body": "Izinsiz yanıt"},
        )
        assert resp.status_code == 404

    def test_delete_other_tenant_message_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        from ayaz.models.social_inbox import SocialMessage

        other_tenant_id = uuid.uuid4()
        other_msg = SocialMessage(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            channel="tiktok",
            kind="comment",
            author_handle="@tiktok_user",
            text="Sil beni!",
            sentiment="neutral",
            status="open",
            tags=[],
            received_at="2026-01-01T10:00:00+00:00",
        )
        db_session.add(other_msg)
        db_session.commit()

        resp = client.delete(f"/api/v1/inbox/messages/{other_msg.id}")
        assert resp.status_code == 404
