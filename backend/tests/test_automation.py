"""Tests for the M9 Automation & Rules engine.

Strategy
--------
* Uses an in-memory SQLite DB (same pattern as test_insights.py).
* Service functions are tested with synthetic fact data.
* API tests use FastAPI TestClient with dependency overrides.
* No live network calls, Celery broker, or Redis connection required.

Coverage
--------
* Rule CRUD (list / create / get / patch / delete).
* evaluate_rule triggers correctly for pct_drop / below / above / anomaly.
* run_rule creates an Insight and an AutomationRun; idempotent same-day.
* run_all_active_rules processes multiple rules.
* Tenant isolation: a rule from tenant A is invisible to tenant B.
* AutomationRun audit log endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1.automation import router as automation_router
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.automation import AutomationRule, AutomationRun
from ayaz.models.base import Base
from ayaz.models.insights import Insight
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
from ayaz.services.automation import (
    RuleEvaluation,
    evaluate_rule,
    run_all_active_rules,
    run_rule,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(automation_router, prefix="/api/v1")

# ── SQLite engine ─────────────────────────────────────────────────────────────

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite DB, yield a Session, then drop everything."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import all model modules so their tables are registered on Base.metadata
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.automation  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── DB fixture helpers ────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "AutoTest Tenant") -> Tenant:
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


def _make_user(db: Session) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"auto-{uuid.uuid4()}@ayaz.app",
        hashed_password=hash_password("pass1234"),
        full_name="Auto User",
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


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=f"camp-{uuid.uuid4()}",
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
        external_id="adset-1",
        name="adset-1",
    )
    db.add(a)
    db.flush()
    return a


def _make_ad(db: Session, tenant: Tenant, adset: DimAdSet) -> DimAd:
    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id="ad-1",
        name="ad-1",
    )
    db.add(ad)
    db.flush()
    return ad


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    acct = ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.sample,
        external_account_id="ACC-AUTO",
        display_name="Auto Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.flush()
    return acct


def _ensure_dim_date(db: Session, d: date) -> None:
    existing = db.get(DimDate, d)
    if existing:
        return
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


def _insert_fact(
    db: Session,
    tenant: Tenant,
    acct: ConnectedAccount,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    d: date,
    *,
    impressions: int = 1000,
    clicks: int = 50,
    cost_raw: str = "100.00",
    conversions: str = "10",
    conversion_value_raw: str = "500.00",
) -> FactDailyMetrics:
    _ensure_dim_date(db, d)
    cost = Decimal(cost_raw)
    f = FactDailyMetrics(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=cost,
        cost_ccy="TRY",
        conversions=Decimal(conversions),
        conversion_value_raw=Decimal(conversion_value_raw),
        conversion_value_ccy="TRY",
        cost_base_ccy=cost,
        conv_value_base_ccy=Decimal(conversion_value_raw),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.flush()
    return f


def _make_rule(
    db: Session,
    tenant: Tenant,
    *,
    name: str = "Test Rule",
    scope: str = "account",
    scope_filter: str | None = None,
    metric: str = "roas",
    comparator: str = "pct_drop",
    threshold: float | None = 20.0,
    window_days: int = 7,
    action: str = "alert",
    action_config: dict | None = None,
    is_active: bool = True,
) -> AutomationRule:
    rule = AutomationRule(
        tenant_id=tenant.id,
        name=name,
        scope=scope,
        scope_filter=scope_filter,
        metric=metric,
        comparator=comparator,
        threshold=threshold,
        window_days=window_days,
        action=action,
        action_config=action_config or {},
        is_active=is_active,
    )
    db.add(rule)
    db.flush()
    return rule


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _seed_roas_drop_data(
    db: Session,
    tenant: Tenant,
    prior_roas: float = 5.0,
    current_roas: float = 2.0,
    window_days: int = 7,
) -> tuple[DimChannel, ConnectedAccount]:
    """Seed prior + current window fact rows to produce a ROAS drop."""
    acct = _make_connected_account(db, tenant)
    channel = _make_channel(db, f"ch-{uuid.uuid4().hex[:6]}")
    campaign = _make_campaign(db, tenant, channel, "Camp ROAS")
    adset = _make_adset(db, tenant, campaign)
    ad = _make_ad(db, tenant, adset)

    # Prior window: days -(2*w) to -(w+1)
    # Current window: days -(w) to 0
    # Use as_of_date = date(2024, 4, 14) implicitly via window_days=7
    base = date(2024, 4, 1)  # day 0
    for i in range(window_days):
        d = base  # prior window days (index 0..6)
        d = date.fromordinal(base.toordinal() + i)
        _insert_fact(
            db, tenant, acct, channel, campaign, adset, ad, d,
            cost_raw="100.00",
            conversions="5",
            conversion_value_raw=str(prior_roas * 100.0),
        )
    for i in range(window_days):
        d = date.fromordinal(base.toordinal() + window_days + i)
        _insert_fact(
            db, tenant, acct, channel, campaign, adset, ad, d,
            cost_raw="100.00",
            conversions="5",
            conversion_value_raw=str(current_roas * 100.0),
        )
    db.flush()
    return channel, acct


# ═══════════════════════════════════════════════════════════════════════════════
# Service unit tests (no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvaluateRulePctDrop:
    """evaluate_rule with pct_drop comparator."""

    def test_triggers_when_roas_drops_above_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        # prior ROAS=5, current ROAS=2 → 60% drop → should trigger at 20% threshold
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=2.0)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        as_of = date(2024, 4, 14)
        result = evaluate_rule(db_session, rule, as_of)

        assert result.triggered is True
        assert len(result.matched_entities) >= 1

    def test_no_trigger_when_drop_below_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        # prior ROAS=5, current ROAS=4.5 → 10% drop → should NOT trigger at 20% threshold
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=4.5)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        as_of = date(2024, 4, 14)
        result = evaluate_rule(db_session, rule, as_of)

        assert result.triggered is False
        assert result.matched_entities == []

    def test_no_trigger_when_no_data(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule, date(2024, 4, 14))
        assert result.triggered is False


class TestEvaluateRuleBelow:
    """evaluate_rule with below comparator."""

    def test_triggers_when_spend_below_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "google_ads")
        campaign = _make_campaign(db_session, tenant, channel, "C")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        as_of = date(2024, 5, 7)
        for i in range(7):
            d = date.fromordinal(as_of.toordinal() - 6 + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="10.00",  # very low spend
            )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="spend", comparator="below", threshold=1000.0, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule, as_of)
        assert result.triggered is True

    def test_no_trigger_when_spend_above_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "meta_ads")
        campaign = _make_campaign(db_session, tenant, channel, "C2")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        as_of = date(2024, 5, 7)
        for i in range(7):
            d = date.fromordinal(as_of.toordinal() - 6 + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="500.00",
            )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="spend", comparator="below", threshold=100.0, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule, as_of)
        assert result.triggered is False


class TestEvaluateRuleAbove:
    """evaluate_rule with above comparator."""

    def test_triggers_when_spend_above_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "tiktok_ads")
        campaign = _make_campaign(db_session, tenant, channel, "C3")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        as_of = date(2024, 6, 7)
        for i in range(7):
            d = date.fromordinal(as_of.toordinal() - 6 + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="300.00",  # 7 * 300 = 2100 total
            )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="spend", comparator="above", threshold=500.0, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule, as_of)
        assert result.triggered is True


class TestEvaluateRuleAnomaly:
    """evaluate_rule with anomaly comparator."""

    def test_triggers_on_clear_anomaly(self, db_session: Session) -> None:
        """Inject a massive spend spike to trigger anomaly detection.

        The anomaly detector requires non-zero variance in the history.
        We use oscillating spend values as the baseline so stdev > 0, then
        insert a day with spend far above the baseline.
        """
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "anomaly_ch")
        campaign = _make_campaign(db_session, tenant, channel, "C4")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        # 34 baseline days with naturally-varying spend (oscillates 90-110)
        spend_vals = [90, 105, 95, 110, 100, 98, 102, 97, 103, 99,
                      101, 108, 96, 104, 92, 106, 94, 109, 100, 98,
                      103, 97, 101, 108, 95, 105, 99, 102, 96, 107,
                      93, 104, 98, 101]
        base = date(2024, 7, 1)
        for i in range(34):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw=str(float(spend_vals[i])),
                conversion_value_raw="500.00",
            )
        # Last day: spend = 9999 (many sigma above the ~100 baseline)
        last_day = date.fromordinal(base.toordinal() + 34)
        _insert_fact(
            db_session, tenant, acct, channel, campaign, adset, ad, last_day,
            cost_raw="9999.00",
            conversion_value_raw="500.00",
        )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="spend", comparator="anomaly", threshold=None, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule, last_day)
        # Anomaly detector should detect the spend spike
        assert result.triggered is True

    def test_no_trigger_on_stable_series(self, db_session: Session) -> None:
        """Stable data should not trigger anomaly."""
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "stable_ch")
        campaign = _make_campaign(db_session, tenant, channel, "C5")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 8, 1)
        for i in range(14):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00",
                conversion_value_raw="500.00",
            )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="anomaly", threshold=None, window_days=7,
        )
        db_session.commit()

        last_day = date.fromordinal(base.toordinal() + 13)
        result = evaluate_rule(db_session, rule, last_day)
        # Stable ROAS — no anomaly
        assert result.triggered is False


class TestEvaluateRulePctRise:
    """evaluate_rule with pct_rise comparator."""

    def test_triggers_when_spend_rises_above_threshold(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        acct = _make_connected_account(db_session, tenant)
        channel = _make_channel(db_session, "rise_ch")
        campaign = _make_campaign(db_session, tenant, channel, "C6")
        adset = _make_adset(db_session, tenant, campaign)
        ad = _make_ad(db_session, tenant, adset)

        base = date(2024, 9, 1)
        # Prior 7 days: spend 100/day
        for i in range(7):
            d = date.fromordinal(base.toordinal() + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="100.00",
            )
        # Current 7 days: spend 300/day → 200% rise
        for i in range(7):
            d = date.fromordinal(base.toordinal() + 7 + i)
            _insert_fact(
                db_session, tenant, acct, channel, campaign, adset, ad, d,
                cost_raw="300.00",
            )
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="spend", comparator="pct_rise", threshold=50.0, window_days=7,
        )
        db_session.commit()

        as_of = date.fromordinal(base.toordinal() + 13)
        result = evaluate_rule(db_session, rule, as_of)
        assert result.triggered is True


class TestRunRule:
    """run_rule: creates Insight and AutomationRun; idempotent same-day."""

    def test_creates_insight_and_run_when_triggered(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=1.0)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        as_of = date(2024, 4, 14)
        result = run_rule(db_session, rule, as_of)
        db_session.commit()

        assert result.triggered is True

        # AutomationRun was created
        runs = db_session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(AutomationRun)
            .where(AutomationRun.rule_id == rule.id)
        ).all()
        assert len(runs) == 1
        assert runs[0].triggered is True

        # An Insight was created
        insights = db_session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(Insight)
            .where(Insight.tenant_id == tenant.id)
        ).all()
        assert len(insights) >= 1

        # last_triggered_at updated
        db_session.refresh(rule)
        assert rule.last_triggered_at == str(as_of)

    def test_idempotent_same_day(self, db_session: Session) -> None:
        """Running run_rule twice on the same day should not double-fire."""
        tenant = _make_tenant(db_session)
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=1.0)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        as_of = date(2024, 4, 14)

        # First run
        result1 = run_rule(db_session, rule, as_of)
        db_session.commit()
        assert result1.triggered is True

        # Count insights after first run
        from sqlalchemy import select as sa_select
        insight_count_1 = len(
            db_session.scalars(
                sa_select(Insight).where(Insight.tenant_id == tenant.id)
            ).all()
        )

        # Second run on the same day — action should be skipped
        result2 = run_rule(db_session, rule, as_of)
        db_session.commit()

        insight_count_2 = len(
            db_session.scalars(
                sa_select(Insight).where(Insight.tenant_id == tenant.id)
            ).all()
        )

        # No new insights created by the second run
        assert insight_count_2 == insight_count_1

        # Two AutomationRun rows (one per evaluation)
        runs = db_session.scalars(
            sa_select(AutomationRun).where(AutomationRun.rule_id == rule.id)
        ).all()
        assert len(runs) == 2

        # Second run has triggered=False (idempotent)
        assert runs[1].triggered is False

    def test_creates_run_even_when_not_triggered(self, db_session: Session) -> None:
        """An AutomationRun row is always created, even when condition is not met."""
        tenant = _make_tenant(db_session)
        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
        )
        db_session.commit()

        from sqlalchemy import select as sa_select
        result = run_rule(db_session, rule, date(2024, 4, 14))
        db_session.commit()

        assert result.triggered is False

        runs = db_session.scalars(
            sa_select(AutomationRun).where(AutomationRun.rule_id == rule.id)
        ).all()
        assert len(runs) == 1
        assert runs[0].triggered is False

    def test_pause_suggest_creates_insight_not_execution(self, db_session: Session) -> None:
        """pause_suggest action creates an Insight but performs no real execution."""
        tenant = _make_tenant(db_session)
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=1.0)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
            action="pause_suggest",
        )
        db_session.commit()

        from sqlalchemy import select as sa_select
        run_rule(db_session, rule, date(2024, 4, 14))
        db_session.commit()

        insights = db_session.scalars(
            sa_select(Insight).where(Insight.tenant_id == tenant.id)
        ).all()
        assert len(insights) >= 1
        # Category marks it as a suggestion, not an execution
        assert any(i.category == "automation_pause_suggest" for i in insights)
        # Body should mention "öneri" or "öneridir"
        assert any("öneri" in i.body for i in insights)

    def test_notify_email_action(self, db_session: Session) -> None:
        """notify_email action creates an Insight and logs (no real SMTP)."""
        tenant = _make_tenant(db_session)
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=1.0)
        db_session.commit()

        rule = _make_rule(
            db_session, tenant,
            metric="roas", comparator="pct_drop", threshold=20.0, window_days=7,
            action="notify_email",
            action_config={"recipients": ["alert@test.com"]},
        )
        db_session.commit()

        from sqlalchemy import select as sa_select
        run_rule(db_session, rule, date(2024, 4, 14))
        db_session.commit()

        insights = db_session.scalars(
            sa_select(Insight).where(Insight.tenant_id == tenant.id)
        ).all()
        assert len(insights) >= 1


class TestRunAllActiveRules:
    """run_all_active_rules iterates all active rules."""

    def test_processes_multiple_rules(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        _seed_roas_drop_data(db_session, tenant, prior_roas=5.0, current_roas=1.0)
        db_session.commit()

        _make_rule(db_session, tenant, name="Rule A", metric="roas", comparator="pct_drop", threshold=20.0)
        _make_rule(db_session, tenant, name="Rule B", metric="roas", comparator="pct_drop", threshold=20.0)
        _make_rule(db_session, tenant, name="Rule C", is_active=False)  # inactive — skipped
        db_session.commit()

        counts = run_all_active_rules(db_session, tenant_id=tenant.id, as_of_date=date(2024, 4, 14))

        assert counts["evaluated"] == 2  # only active rules
        assert counts["errors"] == 0

    def test_tenant_scoped_when_tenant_id_given(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "TenantA")
        tenant_b = _make_tenant(db_session, "TenantB")

        _make_rule(db_session, tenant_a, name="A Rule")
        _make_rule(db_session, tenant_b, name="B Rule")
        db_session.commit()

        counts = run_all_active_rules(db_session, tenant_id=tenant_a.id, as_of_date=date(2024, 4, 14))
        assert counts["evaluated"] == 1  # only tenant A's rule


class TestTenantIsolation:
    """evaluate_rule never exposes data across tenants."""

    def test_rule_sees_only_own_tenant_data(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "TenantA2")
        tenant_b = _make_tenant(db_session, "TenantB2")

        # Seed data only for tenant_a
        acct_a = _make_connected_account(db_session, tenant_a)
        channel_a = _make_channel(db_session, "ch_a")
        camp_a = _make_campaign(db_session, tenant_a, channel_a, "Camp A")
        adset_a = _make_adset(db_session, tenant_a, camp_a)
        ad_a = _make_ad(db_session, tenant_a, adset_a)

        as_of = date(2024, 10, 14)
        for i in range(14):
            d = date.fromordinal(as_of.toordinal() - 13 + i)
            _insert_fact(
                db_session, tenant_a, acct_a, channel_a, camp_a, adset_a, ad_a, d,
                cost_raw="100.00", conversion_value_raw="100.00",
            )
        db_session.commit()

        # Rule for tenant_b — no data → should not trigger
        rule_b = _make_rule(
            db_session, tenant_b,
            metric="spend", comparator="above", threshold=0.0, window_days=7,
        )
        db_session.commit()

        result = evaluate_rule(db_session, rule_b, as_of)
        # tenant_b has no data; rule should not see tenant_a's data
        assert result.triggered is False


# ═══════════════════════════════════════════════════════════════════════════════
# API tests (FastAPI TestClient with SQLite)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def automation_client(db_session: Session):
    """TestClient with DB and membership overridden."""
    tenant = _make_tenant(db_session)
    user = _make_user(db_session)
    membership = _make_membership(db_session, user, tenant)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_get_db
    _test_app.dependency_overrides[get_current_membership] = override_get_membership

    client = TestClient(_test_app)
    yield client, tenant, membership

    _test_app.dependency_overrides.clear()


_VALID_RULE_PAYLOAD: dict = {
    "name": "ROAS Düşüş Uyarısı",
    "scope": "account",
    "metric": "roas",
    "comparator": "pct_drop",
    "threshold": 20.0,
    "window_days": 7,
    "action": "alert",
    "action_config": {},
    "is_active": True,
}


class TestAutomationRuleCRUD:
    """CRUD for /api/v1/automation/rules"""

    def test_list_empty(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.get("/api/v1/automation/rules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_rule(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "ROAS Düşüş Uyarısı"
        assert body["metric"] == "roas"
        assert body["comparator"] == "pct_drop"
        assert body["threshold"] == 20.0
        assert body["window_days"] == 7
        assert body["action"] == "alert"
        assert body["is_active"] is True
        assert body["last_triggered_at"] is None

    def test_create_and_list(self, automation_client) -> None:
        client, *_ = automation_client
        client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        client.post("/api/v1/automation/rules", json={**_VALID_RULE_PAYLOAD, "name": "Rule 2"})
        resp = client.get("/api/v1/automation/rules")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_rule_by_id(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/automation/rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == rule_id

    def test_update_rule(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        patch_resp = client.patch(
            f"/api/v1/automation/rules/{rule_id}",
            json={"name": "Updated Name", "is_active": False},
        )
        assert patch_resp.status_code == 200
        updated = patch_resp.json()
        assert updated["name"] == "Updated Name"
        assert updated["is_active"] is False
        # Unchanged fields preserved
        assert updated["metric"] == "roas"

    def test_delete_rule(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/automation/rules/{rule_id}")
        assert del_resp.status_code == 204

        get_resp = client.get(f"/api/v1/automation/rules/{rule_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_returns_404(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.get(f"/api/v1/automation/rules/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_invalid_comparator_returns_422(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.post(
            "/api/v1/automation/rules",
            json={**_VALID_RULE_PAYLOAD, "comparator": "invalid_op"},
        )
        assert resp.status_code == 422

    def test_invalid_metric_returns_422(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.post(
            "/api/v1/automation/rules",
            json={**_VALID_RULE_PAYLOAD, "metric": "clicks"},
        )
        assert resp.status_code == 422

    def test_missing_threshold_for_pct_drop_returns_422(self, automation_client) -> None:
        client, *_ = automation_client
        payload = {**_VALID_RULE_PAYLOAD}
        payload.pop("threshold", None)
        payload["threshold"] = None
        resp = client.post("/api/v1/automation/rules", json=payload)
        assert resp.status_code == 422

    def test_anomaly_comparator_no_threshold_required(self, automation_client) -> None:
        client, *_ = automation_client
        payload = {
            "name": "Anomaly Rule",
            "metric": "roas",
            "comparator": "anomaly",
            "threshold": None,
            "window_days": 7,
            "action": "alert",
        }
        resp = client.post("/api/v1/automation/rules", json=payload)
        assert resp.status_code == 201

    def test_invalid_action_returns_422(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.post(
            "/api/v1/automation/rules",
            json={**_VALID_RULE_PAYLOAD, "action": "delete_campaign"},
        )
        assert resp.status_code == 422

    def test_tenant_isolation(
        self, automation_client, db_session: Session
    ) -> None:
        """Rule created for tenant A must not appear for tenant B."""
        client, tenant_a, _ = automation_client
        client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)

        tenant_b = _make_tenant(db_session, "TenantB_isolation")
        user_b = _make_user(db_session)
        membership_b = _make_membership(db_session, user_b, tenant_b)
        db_session.commit()

        def override_b():
            return membership_b

        _test_app.dependency_overrides[get_current_membership] = override_b
        try:
            resp = client.get("/api/v1/automation/rules")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            pass


class TestRunRuleEndpoint:
    """POST /api/v1/automation/rules/{id}/run"""

    def test_run_no_data_returns_not_triggered(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/automation/rules/{rule_id}/run",
            params={"as_of": "2024-04-14"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rule_id"] == rule_id
        assert body["triggered"] is False
        assert body["as_of_date"] == "2024-04-14"

    def test_run_404_on_wrong_rule(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.post(f"/api/v1/automation/rules/{uuid.uuid4()}/run")
        assert resp.status_code == 404

    def test_run_creates_automation_run_row(
        self, automation_client, db_session: Session
    ) -> None:
        client, tenant, _ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/automation/rules/{rule_id}/run",
            params={"as_of": "2024-04-14"},
        )
        assert resp.status_code == 200

        from sqlalchemy import select as sa_select
        runs = db_session.scalars(
            sa_select(AutomationRun).where(
                AutomationRun.rule_id == uuid.UUID(rule_id)
            )
        ).all()
        assert len(runs) == 1


class TestRunsEndpoint:
    """GET /api/v1/automation/rules/{id}/runs"""

    def test_runs_empty_initially(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        resp = client.get(f"/api/v1/automation/rules/{rule_id}/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_runs_appear_after_rule_run(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        client.post(
            f"/api/v1/automation/rules/{rule_id}/run",
            params={"as_of": "2024-04-14"},
        )

        resp = client.get(f"/api/v1/automation/rules/{rule_id}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["rule_id"] == rule_id

    def test_runs_404_on_wrong_rule(self, automation_client) -> None:
        client, *_ = automation_client
        resp = client.get(f"/api/v1/automation/rules/{uuid.uuid4()}/runs")
        assert resp.status_code == 404

    def test_runs_pagination_limit(self, automation_client) -> None:
        client, *_ = automation_client
        create_resp = client.post("/api/v1/automation/rules", json=_VALID_RULE_PAYLOAD)
        rule_id = create_resp.json()["id"]

        # Fire the rule 5 times
        for _ in range(5):
            client.post(
                f"/api/v1/automation/rules/{rule_id}/run",
                params={"as_of": "2024-04-14"},
            )

        resp = client.get(
            f"/api/v1/automation/rules/{rule_id}/runs",
            params={"limit": 3},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3
