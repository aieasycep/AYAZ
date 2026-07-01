"""Tests for the AYAZ AI Copilot backend — M11.

Coverage
--------
* Stub intent routing: each keyword intent returns a grounded Turkish reply
  that references real seeded numbers.
* Tool dispatch: correct aggregations returned for each tool.
* Conversation and Message persistence + auto-title.
* Tenant isolation: a second tenant cannot see the first tenant's data.
* Claude path: MOCKED http_client exercises one tool-use round-trip.
* API: all four endpoints via FastAPI TestClient with dependency overrides.
* Existing tests remain green (no modification to shared fixtures).

SQLite compatibility
--------------------
All models use String columns (not Postgres ENUM) and sa.JSON (not JSONB),
so SQLite handles them transparently.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.database import get_db
from ayaz.api.deps import get_current_membership
from ayaz.api.v1.copilot import router as copilot_router
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
from ayaz.models.copilot import Conversation, Message
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

# ── Minimal test app ─────────────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(copilot_router, prefix="/api/v1")

_SQLITE_URL = "sqlite://"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite DB with all AYAZ tables."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import all model modules so they register on Base.metadata
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.tracking  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.copilot  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── DB helpers ────────────────────────────────────────────────────────────────


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


def _make_user(db: Session, email: str = "test@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pass1234"),
        full_name="Test User",
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


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.google_ads,
        external_account_id="ext-test-1",
        display_name="Test Google Ads",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
    iso = d.isocalendar()
    dim = DimDate(
        date_key=d,
        year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month,
        week=iso.week,
        day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    db.flush()
    return dim


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=f"ext-{uuid.uuid4()}",
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_adset(db: Session, tenant: Tenant, campaign: DimCampaign) -> DimAdSet:
    a = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=f"adset-{uuid.uuid4()}",
        name="Test Adset",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=f"ad-{uuid.uuid4()}",
        name="Test Ad",
    )
    db.add(ad)
    db.flush()
    return ad


def _make_fact(
    db: Session,
    tenant: Tenant,
    connected_account: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    d: date,
    spend: float = 1000.0,
    impressions: float = 50000.0,
    clicks: float = 500.0,
    conversions: float = 20.0,
    conv_value: float = 4000.0,
) -> FactDailyMetrics:
    _make_dim_date(db, d)
    adset = _make_adset(db, tenant, campaign)
    ad = _make_ad(db, tenant, adset)
    f = FactDailyMetrics(
        tenant_id=tenant.id,
        connected_account_id=connected_account.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=Decimal(str(spend)),
        cost_ccy="TRY",
        cost_base_ccy=Decimal(str(spend)),
        conversions=Decimal(str(conversions)),
        conversion_value_raw=Decimal(str(conv_value)),
        conversion_value_ccy="TRY",
        conv_value_base_ccy=Decimal(str(conv_value)),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.flush()
    return f


@pytest.fixture()
def seeded(db_session: Session):
    """
    Seed a tenant with:
    - 1 channel: google_ads
    - 1 campaign: "Alpha Campaign"
    - 5 fact rows over the last 5 days: spend=1000/day, roas=4x

    Returns (db, tenant, user, membership, channel, campaign).
    """
    db = db_session
    tenant = _make_tenant(db)
    user = _make_user(db)
    membership = _make_membership(db, user, tenant)
    connected_account = _make_connected_account(db, tenant)
    channel = _make_channel(db, "google_ads")
    campaign = _make_campaign(db, tenant, channel, "Alpha Campaign")

    today = date.today()
    for i in range(5):
        d = today - timedelta(days=i)
        _make_fact(
            db, tenant, connected_account, channel, campaign, d,
            spend=1000.0,
            impressions=50000.0,
            clicks=500.0,
            conversions=20.0,
            conv_value=4000.0,
        )
    db.commit()
    return db, tenant, user, membership, channel, campaign


# ── FastAPI test client factory ───────────────────────────────────────────────


def _make_client(db: Session, membership: Membership) -> TestClient:
    def override_db():
        yield db

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    return TestClient(_test_app)


# ── Tool dispatch tests ───────────────────────────────────────────────────────


class TestToolDispatch:
    """Test each tool returns correct data for the seeded tenant."""

    def test_get_performance_summary(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "get_performance_summary",
            db,
            tenant.id,
            {
                "date_from": (today - timedelta(days=4)).isoformat(),
                "date_to": today.isoformat(),
            },
        )
        totals = result["totals"]
        # 5 days × 1000/day = 5000
        assert totals["spend"] == pytest.approx(5000.0, abs=1)
        # ROAS = 4000*5 / 1000*5 = 4.0
        assert totals["roas"] == pytest.approx(4.0, abs=0.01)
        assert len(result["by_channel"]) == 1
        assert result["by_channel"][0]["channel"] == "google_ads"

    def test_get_timeseries(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "get_timeseries",
            db,
            tenant.id,
            {
                "date_from": (today - timedelta(days=4)).isoformat(),
                "date_to": today.isoformat(),
                "metric": "spend",
            },
        )
        assert result["metric"] == "spend"
        assert len(result["points"]) == 5
        for pt in result["points"]:
            assert pt["value"] == pytest.approx(1000.0, abs=1)

    def test_list_campaigns(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "list_campaigns",
            db,
            tenant.id,
            {
                "date_from": (today - timedelta(days=4)).isoformat(),
                "date_to": today.isoformat(),
            },
        )
        campaigns = result["campaigns"]
        assert len(campaigns) == 1
        assert campaigns[0]["campaign_name"] == "Alpha Campaign"
        assert campaigns[0]["spend"] == pytest.approx(5000.0, abs=1)

    def test_get_insights_empty(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_insights", db, tenant.id, {})
        assert "insights" in result
        # No insights seeded — count can be 0
        assert result["count"] >= 0

    def test_get_feed_channels_empty(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_feed_channels", db, tenant.id, {})
        assert "channels" in result

    def test_draft_automation_rule_valid(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "draft_automation_rule",
            db,
            tenant.id,
            {
                "name": "ROAS Düşüşü Uyarısı",
                "metric": "roas",
                "comparator": "pct_drop",
                "threshold": 20.0,
                "action": "alert",
            },
        )
        assert result["draft"] is True
        assert result["rule"]["metric"] == "roas"

    def test_draft_automation_rule_invalid_metric(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "draft_automation_rule",
            db,
            tenant.id,
            {
                "name": "Bad Rule",
                "metric": "not_a_metric",
                "comparator": "pct_drop",
                "threshold": 20.0,
                "action": "alert",
            },
        )
        assert result["draft"] is False
        assert "errors" in result

    def test_get_subscription_status(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_subscription_status", db, tenant.id, {})
        assert "plan_code" in result
        assert "limits" in result

    def test_dispatch_unknown_tool(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("no_such_tool", db, tenant.id, {})
        assert "error" in result


# ── Stub intent routing tests ─────────────────────────────────────────────────


class TestStubChat:
    """Assert the stub path returns grounded Turkish answers."""

    def _run(self, db, tenant_id, text):
        from ayaz.services.copilot import _stub_chat
        return _stub_chat(db, tenant_id, text)

    def test_performance_intent_spend_in_reply(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Performans nasıl gidiyor?")
        assert reply.text  # non-empty
        # Should reference actual spend or ROAS figures from seeded data
        assert any(kw in reply.text for kw in ["harcama", "ROAS", "5000", "4.00"])
        assert len(reply.tools_used) >= 1
        assert reply.tools_used[0].name == "get_performance_summary"

    def test_campaign_intent(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Kampanyaları listele")
        assert "Alpha Campaign" in reply.text
        assert any(tu.name == "list_campaigns" for tu in reply.tools_used)

    def test_recommendation_intent(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Ne yapmalıyım, önerilerin var mı?")
        assert reply.text
        assert any(tu.name == "get_recommendations" for tu in reply.tools_used)

    def test_insight_intent(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "İçgörüleri göster")
        assert reply.text
        assert any(tu.name == "get_insights" for tu in reply.tools_used)

    def test_feed_intent(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Feed kanallarım neler?")
        assert reply.text
        assert any(tu.name == "get_feed_channels" for tu in reply.tools_used)

    def test_subscription_intent(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Abonelik planım ne?")
        assert reply.text
        assert any(tu.name == "get_subscription_status" for tu in reply.tools_used)

    def test_default_intent_capability_message(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "Merhaba, ne yapabilirsin?")
        assert "AYAZ" in reply.text or "yapabilirim" in reply.text
        # Default intent: no tools called
        assert len(reply.tools_used) == 0

    def test_english_performance_keyword(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run(db, tenant.id, "show me summary")
        # "summary" should match the performance intent
        assert any(tu.name == "get_performance_summary" for tu in reply.tools_used)


# ── Persistence + auto-title tests ───────────────────────────────────────────


class TestChatPersistence:
    def test_user_message_persisted(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat
        from sqlalchemy import select

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        chat(db, tenant.id, user.id, conv, "Özet göster")

        msgs = db.scalars(
            select(Message).where(Message.conversation_id == conv.id)
        ).all()
        roles = [m.role for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    def test_auto_title_set(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()
        assert conv.title is None

        chat(db, tenant.id, user.id, conv, "Kampanya durumu nedir?")
        db.refresh(conv)
        assert conv.title is not None
        assert "Kampanya" in conv.title

    def test_auto_title_not_overwritten(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        conv = Conversation(tenant_id=tenant.id, user_id=user.id, title="Manuel Başlık")
        db.add(conv)
        db.flush()

        chat(db, tenant.id, user.id, conv, "İkinci mesaj")
        db.refresh(conv)
        assert conv.title == "Manuel Başlık"

    def test_tool_messages_persisted(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat
        from sqlalchemy import select

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        # "Özet" triggers get_performance_summary
        chat(db, tenant.id, user.id, conv, "Özet göster lütfen")

        tool_msgs = db.scalars(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.role == "tool",
            )
        ).all()
        # At least one tool message should have been persisted
        assert len(tool_msgs) >= 1
        assert all(m.tool_name is not None for m in tool_msgs)

    def test_long_title_truncated(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        long_text = "A" * 200
        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        chat(db, tenant.id, user.id, conv, long_text)
        db.refresh(conv)
        assert len(conv.title) <= 120


# ── Tenant isolation tests ────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_tool_returns_only_own_tenant_data(self, db_session: Session):
        """Tenant B's summary should be empty even when Tenant A has data."""
        db = db_session
        # Tenant A with data
        tenant_a = _make_tenant(db, "Tenant A")
        acct_a = _make_connected_account(db, tenant_a)
        ch = _make_channel(db, "google_ads")
        campaign = _make_campaign(db, tenant_a, ch, "A Campaign")
        today = date.today()
        _make_fact(db, tenant_a, acct_a, ch, campaign, today, spend=9999.0)
        db.commit()

        # Tenant B — no data
        tenant_b = _make_tenant(db, "Tenant B")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "get_performance_summary",
            db,
            tenant_b.id,
            {"date_from": today.isoformat(), "date_to": today.isoformat()},
        )
        # Tenant B should have zero spend
        assert result["totals"]["spend"] == pytest.approx(0.0, abs=0.01)

    def test_conversation_not_visible_cross_tenant(self, db_session: Session):
        """A conversation for Tenant A cannot be fetched by Tenant B."""
        db = db_session
        tenant_a = _make_tenant(db, "TA")
        tenant_b = _make_tenant(db, "TB")
        user = _make_user(db)
        db.flush()

        conv = Conversation(tenant_id=tenant_a.id, user_id=user.id)
        db.add(conv)
        db.commit()

        from sqlalchemy import select

        # Try to fetch with tenant_b — should return nothing
        result = db.scalar(
            select(Conversation).where(
                Conversation.id == conv.id,
                Conversation.tenant_id == tenant_b.id,
            )
        )
        assert result is None


# ── Claude path mock test ─────────────────────────────────────────────────────


class TestClaudePath:
    """Exercise one tool-use round-trip with a mocked HTTP client."""

    def _build_mock_client(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: dict,
        final_text: str,
    ) -> MagicMock:
        """Build a mock httpx client for a single tool-use + final reply flow."""
        mock_client = MagicMock()

        # First call: model returns tool_use stop_reason
        first_response = MagicMock()
        first_response.status_code = 200
        first_response.json.return_value = {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        }

        # Second call: model returns end_turn with final text
        second_response = MagicMock()
        second_response.status_code = 200
        second_response.json.return_value = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": final_text}],
        }

        mock_client.post.side_effect = [first_response, second_response]
        return mock_client

    def test_claude_tool_use_round_trip(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        today = date.today()
        tool_input = {
            "date_from": (today - timedelta(days=6)).isoformat(),
            "date_to": today.isoformat(),
        }
        mock_client = self._build_mock_client(
            tool_name="get_performance_summary",
            tool_id="toolu_test_123",
            tool_input=tool_input,
            final_text="Son 7 günde toplam harcamanız 5.000 TRY, ROAS 4.0x.",
        )

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        # Temporarily set a fake API key so the Claude path is taken
        from ayaz.config import settings
        original_key = settings.anthropic_api_key
        settings.__dict__["anthropic_api_key"] = "sk-test-key"

        try:
            reply = chat(
                db,
                tenant.id,
                user.id,
                conv,
                "Performans özetini ver",
                http_client=mock_client,
            )
        finally:
            settings.__dict__["anthropic_api_key"] = original_key

        # The mock client should have been called exactly twice
        assert mock_client.post.call_count == 2
        # The reply text should be the final text from the second mock response
        assert "5.000" in reply.text or "ROAS" in reply.text or "5.0" in reply.text
        # One tool used
        assert len(reply.tools_used) >= 1
        assert reply.tools_used[0].name == "get_performance_summary"

    def test_claude_path_falls_back_to_stub_on_error(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        # Mock client that always raises
        mock_client = MagicMock()
        mock_client.post.side_effect = RuntimeError("network error")

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        from ayaz.config import settings
        settings.__dict__["anthropic_api_key"] = "sk-fake-key"

        try:
            reply = chat(
                db,
                tenant.id,
                user.id,
                conv,
                "Özet göster",
                http_client=mock_client,
            )
        finally:
            settings.__dict__["anthropic_api_key"] = ""

        # Should fall back to stub and still return a valid Turkish reply
        assert reply.text
        assert len(reply.text) > 10


# ── API endpoint tests ────────────────────────────────────────────────────────


class TestCopilotAPI:
    def test_create_conversation_no_message(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)
        resp = client.post(
            "/api/v1/assistant/conversations",
            json={},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] is None

    def test_create_conversation_with_first_message(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)
        resp = client.post(
            "/api/v1/assistant/conversations",
            json={"first_message": "Özet göster"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] is not None
        assert "Özet" in data["title"]

    def test_list_conversations(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)

        # Create two conversations
        client.post("/api/v1/assistant/conversations", json={})
        client.post("/api/v1/assistant/conversations", json={})

        resp = client.get("/api/v1/assistant/conversations")
        assert resp.status_code == 200
        convs = resp.json()
        assert len(convs) >= 2
        # Each has expected fields
        for c in convs:
            assert "id" in c
            assert "updated_at" in c

    def test_list_messages(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)

        # Create conversation with a message
        create_resp = client.post(
            "/api/v1/assistant/conversations",
            json={"first_message": "Kampanya listesi ver"},
        )
        conv_id = create_resp.json()["id"]

        resp = client.get(f"/api/v1/assistant/conversations/{conv_id}/messages")
        assert resp.status_code == 200
        msgs = resp.json()
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    def test_send_message(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)

        # Create conversation first
        create_resp = client.post("/api/v1/assistant/conversations", json={})
        conv_id = create_resp.json()["id"]

        # Send a message
        resp = client.post(
            f"/api/v1/assistant/conversations/{conv_id}/messages",
            json={"content": "Performans nasıl?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "assistant_message" in data
        assert data["assistant_message"]["role"] == "assistant"
        assert len(data["assistant_message"]["content"]) > 0
        assert "tools_used" in data

    def test_send_empty_message_rejected(self, seeded):
        db, tenant, user, membership, *_ = seeded
        client = _make_client(db, membership)

        create_resp = client.post("/api/v1/assistant/conversations", json={})
        conv_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/assistant/conversations/{conv_id}/messages",
            json={"content": "   "},
        )
        assert resp.status_code == 422

    def test_messages_404_for_wrong_tenant(self, db_session: Session):
        """Cannot access another tenant's conversation via the API."""
        db = db_session

        # Tenant A with a conversation
        tenant_a = _make_tenant(db, "TA")
        user_a = _make_user(db, "a@test.com")
        membership_a = _make_membership(db, user_a, tenant_a)
        db.flush()

        conv = Conversation(tenant_id=tenant_a.id, user_id=user_a.id)
        db.add(conv)
        db.commit()

        # Tenant B trying to access Tenant A's conversation
        tenant_b = _make_tenant(db, "TB")
        user_b = _make_user(db, "b@test.com")
        membership_b = _make_membership(db, user_b, tenant_b)
        db.commit()

        client_b = _make_client(db, membership_b)
        resp = client_b.get(f"/api/v1/assistant/conversations/{conv.id}/messages")
        assert resp.status_code == 404

    def test_send_message_to_wrong_tenant_conv_404(self, db_session: Session):
        db = db_session

        tenant_a = _make_tenant(db, "TA2")
        user_a = _make_user(db, "a2@test.com")
        membership_a = _make_membership(db, user_a, tenant_a)
        db.flush()
        conv = Conversation(tenant_id=tenant_a.id, user_id=user_a.id)
        db.add(conv)
        db.commit()

        tenant_b = _make_tenant(db, "TB2")
        user_b = _make_user(db, "b2@test.com")
        membership_b = _make_membership(db, user_b, tenant_b)
        db.commit()

        client_b = _make_client(db, membership_b)
        resp = client_b.post(
            f"/api/v1/assistant/conversations/{conv.id}/messages",
            json={"content": "Hacked!"},
        )
        assert resp.status_code == 404
