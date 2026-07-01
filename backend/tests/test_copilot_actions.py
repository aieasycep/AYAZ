"""Tests for Copilot v2 action tools — create_automation_rule, create_goal.

Coverage
--------
* create_automation_rule tool: real DB write, tenant-scoped, validated.
* create_goal tool: real DB write, tenant-scoped, validated.
* Stub router: clarifying question when params missing.
* Stub router: creates entity when params are present.
* Claude path mock: exercises create_automation_rule action tool.
* Tenant isolation: action only affects the correct tenant's data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.automation import AutomationRule
from ayaz.models.base import Base
from ayaz.models.copilot import Conversation, Message
from ayaz.models.goals import Goal
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

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite with all AYAZ tables."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.tracking  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.copilot  # noqa: F401
    import ayaz.models.goals  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    t = Tenant(id=uuid.uuid4(), name=name, base_currency="TRY", country="TR", kvkk_region="TR")
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
    m = Membership(id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id, role=MembershipRole.owner)
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


def _make_campaign(db: Session, tenant: Tenant, channel: DimChannel, name: str) -> DimCampaign:
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
        impressions=50000,
        clicks=500,
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
    """Tenant + 5 days of fact data."""
    db = db_session
    tenant = _make_tenant(db)
    user = _make_user(db)
    membership = _make_membership(db, user, tenant)
    acct = _make_connected_account(db, tenant)
    channel = _make_channel(db, "google_ads")
    campaign = _make_campaign(db, tenant, channel, "Alpha Campaign")
    today = date.today()
    for i in range(5):
        _make_fact(db, tenant, acct, channel, campaign, today - timedelta(days=i))
    db.commit()
    return db, tenant, user, membership, channel, campaign


# ── Tool dispatch: action tools ───────────────────────────────────────────────


class TestCreateAutomationRuleTool:
    def test_creates_rule_in_db(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_automation_rule",
            db,
            tenant.id,
            {
                "name": "ROAS Alarm",
                "metric": "roas",
                "comparator": "pct_drop",
                "threshold": 20.0,
                "action": "alert",
            },
        )
        assert result["created"] is True
        assert "rule_id" in result
        # Verify persisted
        rule = db.get(AutomationRule, uuid.UUID(result["rule_id"]))
        assert rule is not None
        assert rule.tenant_id == tenant.id
        assert rule.metric == "roas"
        assert rule.comparator == "pct_drop"
        assert rule.threshold == pytest.approx(20.0)

    def test_rule_is_tenant_scoped(self, db_session: Session):
        """Rule created for tenant A is not visible to tenant B."""
        db = db_session
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_automation_rule",
            db,
            tenant_a.id,
            {
                "name": "A's Rule",
                "metric": "spend",
                "comparator": "pct_rise",
                "threshold": 30.0,
                "action": "alert",
            },
        )
        assert result["created"] is True
        rule_id = uuid.UUID(result["rule_id"])
        rule = db.get(AutomationRule, rule_id)
        assert rule.tenant_id == tenant_a.id
        # Tenant B cannot find it via tenant-scoped query
        b_rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant_b.id)
        ).all()
        assert len(b_rules) == 0

    def test_invalid_metric_returns_error(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_automation_rule",
            db,
            tenant.id,
            {
                "name": "Bad Rule",
                "metric": "not_a_metric",
                "comparator": "pct_drop",
                "threshold": 10.0,
                "action": "alert",
            },
        )
        assert result["created"] is False
        assert "errors" in result
        # Nothing written
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 0

    def test_rule_with_scope_filter(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_automation_rule",
            db,
            tenant.id,
            {
                "name": "Channel Rule",
                "metric": "ctr",
                "comparator": "pct_drop",
                "threshold": 25.0,
                "action": "alert",
                "scope": "channel",
                "scope_filter": "google_ads",
                "window_days": 14,
            },
        )
        assert result["created"] is True
        rule = db.get(AutomationRule, uuid.UUID(result["rule_id"]))
        assert rule.scope == "channel"
        assert rule.scope_filter == "google_ads"
        assert rule.window_days == 14

    def test_anomaly_rule_no_threshold(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_automation_rule",
            db,
            tenant.id,
            {
                "name": "Anomali Kuralı",
                "metric": "spend",
                "comparator": "anomaly",
                "action": "alert",
            },
        )
        assert result["created"] is True
        rule = db.get(AutomationRule, uuid.UUID(result["rule_id"]))
        assert rule.comparator == "anomaly"
        assert rule.threshold is None


class TestCreateGoalTool:
    def test_creates_goal_in_db(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "create_goal",
            db,
            tenant.id,
            {
                "name": "Haziran ROAS Hedefi",
                "metric": "roas",
                "target_value": 3.5,
                "period_start": today.replace(day=1).isoformat(),
                "period_end": today.isoformat(),
            },
        )
        assert result["created"] is True
        assert "goal_id" in result
        goal = db.get(Goal, uuid.UUID(result["goal_id"]))
        assert goal is not None
        assert goal.tenant_id == tenant.id
        assert goal.metric == "roas"
        assert goal.target_value == pytest.approx(3.5)

    def test_goal_is_tenant_scoped(self, db_session: Session):
        db = db_session
        tenant_a = _make_tenant(db, "GA")
        tenant_b = _make_tenant(db, "GB")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "create_goal",
            db,
            tenant_a.id,
            {
                "name": "A's Goal",
                "metric": "spend",
                "target_value": 100000.0,
                "period_start": today.replace(day=1).isoformat(),
                "period_end": today.isoformat(),
            },
        )
        assert result["created"] is True
        goal = db.get(Goal, uuid.UUID(result["goal_id"]))
        assert goal.tenant_id == tenant_a.id
        # Tenant B sees nothing
        b_goals = db.scalars(
            select(Goal).where(Goal.tenant_id == tenant_b.id)
        ).all()
        assert len(b_goals) == 0

    def test_invalid_metric_returns_error(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch(
            "create_goal",
            db,
            tenant.id,
            {
                "name": "Bad Goal",
                "metric": "not_a_metric",
                "target_value": 100.0,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
        assert result["created"] is False
        assert "errors" in result
        goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant.id)).all()
        assert len(goals) == 0

    def test_goal_with_channel_filter(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today()
        result = dispatch(
            "create_goal",
            db,
            tenant.id,
            {
                "name": "Google ROAS Hedefi",
                "metric": "roas",
                "target_value": 4.0,
                "period_start": today.replace(day=1).isoformat(),
                "period_end": today.isoformat(),
                "channel_filter": "google_ads",
            },
        )
        assert result["created"] is True
        goal = db.get(Goal, uuid.UUID(result["goal_id"]))
        assert goal.channel_filter == "google_ads"


# ── Stub router: action intents ───────────────────────────────────────────────


class TestStubActionIntents:
    def _run_stub(self, db, tenant_id, text):
        from ayaz.services.copilot import _stub_chat
        return _stub_chat(db, tenant_id, text)

    # ── create_automation_rule ─────────────────────────────────────────────

    def test_rule_intent_missing_params_asks_clarification(self, seeded):
        db, tenant, *_ = seeded
        # "kural oluştur" with no metric → should ask for missing info
        reply = self._run_stub(db, tenant.id, "kural oluştur")
        # Should NOT have created any rules
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 0
        # Reply should ask for what's needed
        assert any(
            kw in reply.text.lower()
            for kw in ["hangi", "bilgi", "belirt", "ihtiyac", "gerekl"]
        )

    def test_rule_intent_with_params_creates_rule(self, seeded):
        db, tenant, *_ = seeded
        # Enough info to create a rule
        reply = self._run_stub(
            db, tenant.id,
            "kural oluştur: ROAS %20 düştüğünde alert ver"
        )
        # A rule should have been created
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 1
        assert rules[0].metric == "roas"
        assert rules[0].comparator == "pct_drop"
        # Reply should confirm creation
        assert any(
            kw in reply.text
            for kw in ["Oluşturuldu", "oluşturuldu", "kural"]
        )
        # Tool used recorded
        assert any(tu.name == "create_automation_rule" for tu in reply.tools_used)

    def test_rule_intent_alternative_keywords(self, seeded):
        db, tenant, *_ = seeded
        # "uyarı kur" should also trigger create rule intent
        reply = self._run_stub(
            db, tenant.id,
            "uyarı kur: harcama %30 arttığında bildir"
        )
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 1
        assert rules[0].metric == "spend"
        assert rules[0].comparator == "pct_rise"

    # ── create_goal ────────────────────────────────────────────────────────

    def test_goal_intent_missing_params_asks_clarification(self, seeded):
        db, tenant, *_ = seeded
        # "hedef koy" with no metric → should ask
        reply = self._run_stub(db, tenant.id, "hedef koy")
        goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant.id)).all()
        assert len(goals) == 0
        assert any(
            kw in reply.text.lower()
            for kw in ["hangi", "bilgi", "belirt", "ihtiyac", "gerekl"]
        )

    def test_goal_intent_with_params_creates_goal(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run_stub(
            db, tenant.id,
            "hedef koy: ROAS için 3.5 hedefi"
        )
        goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant.id)).all()
        assert len(goals) == 1
        assert goals[0].metric == "roas"
        assert goals[0].target_value == pytest.approx(3.5)
        assert any(
            kw in reply.text
            for kw in ["Oluşturuldu", "oluşturuldu", "hedef"]
        )
        assert any(tu.name == "create_goal" for tu in reply.tools_used)

    def test_goal_intent_alternative_keyword(self, seeded):
        db, tenant, *_ = seeded
        reply = self._run_stub(
            db, tenant.id,
            "hedef oluştur: dönüşüm 500 hedefi"
        )
        goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant.id)).all()
        assert len(goals) == 1
        assert goals[0].metric == "conversions"


# ── Claude path: action tool round-trip ──────────────────────────────────────


class TestClaudeActionPath:
    def _build_mock_client_for_action(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: dict,
        final_text: str,
    ) -> MagicMock:
        mock_client = MagicMock()
        first_response = MagicMock()
        first_response.status_code = 200
        first_response.json.return_value = {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": tool_id, "name": tool_name, "input": tool_input}
            ],
        }
        second_response = MagicMock()
        second_response.status_code = 200
        second_response.json.return_value = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": final_text}],
        }
        mock_client.post.side_effect = [first_response, second_response]
        return mock_client

    def test_claude_calls_create_automation_rule(self, seeded):
        db, tenant, user, *_ = seeded
        from ayaz.services.copilot import chat

        today = date.today()
        tool_input = {
            "name": "ROAS Alarm",
            "metric": "roas",
            "comparator": "pct_drop",
            "threshold": 20.0,
            "action": "alert",
        }
        mock_client = self._build_mock_client_for_action(
            tool_name="create_automation_rule",
            tool_id="toolu_action_001",
            tool_input=tool_input,
            final_text="Oluşturuldu: ROAS Alarm kuralı.",
        )

        conv = Conversation(tenant_id=tenant.id, user_id=user.id)
        db.add(conv)
        db.flush()

        from ayaz.config import settings
        original_key = settings.anthropic_api_key
        settings.__dict__["anthropic_api_key"] = "sk-test-action-key"

        try:
            reply = chat(
                db, tenant.id, user.id, conv,
                "ROAS için kural oluştur",
                http_client=mock_client,
            )
        finally:
            settings.__dict__["anthropic_api_key"] = original_key

        assert mock_client.post.call_count == 2
        # Rule should be persisted
        rules = db.scalars(
            select(AutomationRule).where(AutomationRule.tenant_id == tenant.id)
        ).all()
        assert len(rules) == 1
        assert rules[0].metric == "roas"
        # Tool usage recorded
        assert any(tu.name == "create_automation_rule" for tu in reply.tools_used)
