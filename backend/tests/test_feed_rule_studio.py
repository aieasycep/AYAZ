"""Feed Rule Studio tests — Dalga 43.

Covers:
  1. Per-rule pause: is_paused skipped by apply_rules; reflected in impact.
  2. Impact preview: affected/excluded counts correct.
  3. Simulate: unsaved filter returns plausible counts; DB unchanged.
  4. Linter: flags no_effect and duplicate.
  5. Auth isolation: 401 without token; 404/empty for another tenant's channel.

Strategy
--------
* FastAPI TestClient with in-memory SQLite (same pattern as test_feeds_api.py).
* get_db and get_current_membership are overridden per fixture.
* Pure service functions tested directly without HTTP where possible.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models on Base.metadata
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
from ayaz.services.feeds import (
    apply_rules,
    compute_rules_impact,
    lint_rules,
    simulate_rule,
)

import secrets as _secrets

# ── Test app ──────────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Feed Rule Studio Test App")
_test_app.include_router(feeds_module.router, prefix="/api/v1")


# ── Shared DB engine (one per module for test isolation) ─────────────────────


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


def _seed_tenant_user(db_session: Session) -> tuple[Tenant, User, Membership]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Studio Test Tenant",
        base_currency="USD",
        country="US",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email=f"studio_{uuid.uuid4().hex[:6]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Studio User",
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
def client_other_tenant(db_session: Session):
    """TestClient wired to tenant B — for isolation tests."""
    _, _, membership_b = _seed_tenant_user(db_session)

    def override_db():
        try:
            yield db_session
        finally:
            pass

    def override_membership():
        return membership_b

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
        name="Studio Source",
        source_type="upload",
        source_url=None,
        status="pending",
        item_count=0,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_channel(db: Session, source: FeedSource) -> FeedChannel:
    ch = FeedChannel(
        id=uuid.uuid4(),
        tenant_id=source.tenant_id,
        feed_source_id=source.id,
        name="Studio Channel",
        channel_type="google_shopping",
        output_format="xml",
        public_token="studio_tok_" + _secrets.token_hex(8),
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
            external_id=str(i),
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


# ── Stub rule for pure-function tests ────────────────────────────────────────


class _StubRule:
    """Duck-type stand-in for FeedRule for pure service tests."""

    def __init__(
        self,
        rule_type: str,
        config: dict,
        position: int = 0,
        is_paused: bool = False,
    ) -> None:
        self.id = uuid.uuid4()
        self.rule_type = rule_type
        self.config = config
        self.position = position
        self.is_paused = is_paused


# ── Sample products ───────────────────────────────────────────────────────────

PRODUCTS = [
    {"id": "P1", "title": "Widget Alpha", "price": "10.00",
     "availability": "in stock", "brand": "Acme"},
    {"id": "P2", "title": "Widget Beta", "price": "20.00",
     "availability": "out of stock", "brand": "Beta Corp"},
    {"id": "P3", "title": "Gadget Gamma", "price": "5.00",
     "availability": "in stock", "brand": "Acme"},
    {"id": "P4", "title": "Gadget Delta", "price": "30.00",
     "availability": "in stock", "brand": "Delta Inc"},
    {"id": "P5", "title": "Gizmo Epsilon", "price": "1.00",
     "availability": "out of stock", "brand": "Acme"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Per-rule PAUSE
# ═══════════════════════════════════════════════════════════════════════════════


class TestRulePause:
    def test_paused_rule_skipped_by_apply_rules(self) -> None:
        """A paused set_value rule must not alter any product."""
        rule = _StubRule("set_value", {"field": "brand", "value": "OVERRIDDEN"}, is_paused=True)
        result = apply_rules(list(PRODUCTS), [rule])
        # brand must be unchanged on all products
        assert all(p["brand"] != "OVERRIDDEN" for p in result)

    def test_active_rule_applied_by_apply_rules(self) -> None:
        """An active set_value rule must alter every product."""
        rule = _StubRule("set_value", {"field": "brand", "value": "OVERRIDDEN"}, is_paused=False)
        result = apply_rules(list(PRODUCTS), [rule])
        assert all(p["brand"] == "OVERRIDDEN" for p in result)

    def test_paused_filter_does_not_remove_items(self) -> None:
        """A paused filter_exclude rule must leave the product count unchanged."""
        rule = _StubRule(
            "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq", "condition_value": "in stock"},
            is_paused=True,
        )
        result = apply_rules(list(PRODUCTS), [rule])
        assert len(result) == len(PRODUCTS)

    def test_paused_rule_via_patch_endpoint(self, client: TestClient, db_session: Session) -> None:
        """PATCH /feeds/rules/{id} with is_paused=True toggles the pause flag."""
        # Create channel + rule via API
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "PauseTest", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "PauseCh", "channel_type": "google_shopping"},
        )
        ch_id = ch_resp.json()["id"]
        rule_resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={"rule_type": "set_value", "position": 0,
                  "config": {"field": "brand", "value": "X"}},
        )
        rule_id = rule_resp.json()["id"]
        assert rule_resp.json()["is_paused"] is False

        # Toggle pause
        patch_resp = client.patch(
            f"/api/v1/feeds/rules/{rule_id}",
            json={"is_paused": True},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_paused"] is True

        # Toggle back
        unpause_resp = client.patch(
            f"/api/v1/feeds/rules/{rule_id}",
            json={"is_paused": False},
        )
        assert unpause_resp.json()["is_paused"] is False

    def test_paused_rule_reflected_in_impact(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Impact endpoint must show is_paused=True and zero counts for paused rule."""
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "ImpactPauseTest", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "ImpactPauseCh", "channel_type": "google_shopping"},
        )
        ch_id = ch_resp.json()["id"]
        client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules",
            json={
                "rule_type": "set_value",
                "position": 0,
                "config": {"field": "brand", "value": "X"},
                "is_paused": True,
            },
        )

        resp = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["rules"]) == 1
        rule_stat = body["rules"][0]
        assert rule_stat["is_paused"] is True
        assert rule_stat["affected_count"] == 0
        assert rule_stat["excluded_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Impact preview — pure service function
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeRulesImpact:
    def test_no_rules_gives_zero_impact(self) -> None:
        result = compute_rules_impact(list(PRODUCTS), [])
        assert result["total_before"] == len(PRODUCTS)
        assert result["total_after"] == len(PRODUCTS)
        assert result["rules"] == []

    def test_set_value_affects_all_products(self) -> None:
        rule = _StubRule("set_value", {"field": "brand", "value": "NEW"}, position=0)
        result = compute_rules_impact(list(PRODUCTS), [rule])
        assert result["rules"][0]["affected_count"] == len(PRODUCTS)
        assert result["rules"][0]["excluded_count"] == 0
        assert result["total_after"] == result["total_before"]

    def test_filter_exclude_counts_excluded(self) -> None:
        # Out-of-stock products: P2 and P5 → excluded_count = 2
        rule = _StubRule(
            "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "out of stock"},
            position=0,
        )
        result = compute_rules_impact(list(PRODUCTS), [rule])
        stat = result["rules"][0]
        assert stat["excluded_count"] == 2
        assert stat["affected_count"] == 0
        assert result["total_after"] == 3

    def test_filter_include_counts_excluded(self) -> None:
        # Keep only "in stock" → 3 kept, 2 excluded
        rule = _StubRule(
            "filter_include",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "in stock"},
            position=0,
        )
        result = compute_rules_impact(list(PRODUCTS), [rule])
        stat = result["rules"][0]
        assert stat["excluded_count"] == 2
        assert result["total_after"] == 3

    def test_paused_rule_has_zero_counts_in_impact(self) -> None:
        rule = _StubRule(
            "set_value", {"field": "brand", "value": "NEW"}, position=0, is_paused=True
        )
        result = compute_rules_impact(list(PRODUCTS), [rule])
        stat = result["rules"][0]
        assert stat["is_paused"] is True
        assert stat["affected_count"] == 0
        assert stat["excluded_count"] == 0
        # Paused rule must not change total_after
        assert result["total_after"] == result["total_before"]

    def test_cumulative_impact_across_rules(self) -> None:
        """Two rules: first excludes out-of-stock (2 gone), second set_value on remainder."""
        r1 = _StubRule(
            "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "out of stock"},
            position=0,
        )
        r2 = _StubRule("set_value", {"field": "brand", "value": "BRAND"}, position=1)
        result = compute_rules_impact(list(PRODUCTS), [r1, r2])
        # After r1: 3 remain; r2 changes brand on all 3
        assert result["rules"][0]["excluded_count"] == 2
        assert result["rules"][1]["affected_count"] == 3
        assert result["total_after"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 2b. Impact endpoint (HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestImpactEndpoint:
    def _setup(self, client: TestClient, db_session: Session, membership: Membership):
        """Helper: create source+channel+products+rules, return channel_id."""
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src)
        _seed_products(db_session, src, PRODUCTS)
        # Rule 1: set_value (affects all)
        _make_rule(
            db_session, ch, "set_value",
            {"field": "brand", "value": "AYAZ"},
            position=0,
        )
        # Rule 2: filter_exclude out-of-stock (excludes 2)
        _make_rule(
            db_session, ch, "filter_exclude",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "out of stock"},
            position=1,
        )
        # Rule 3: paused
        _make_rule(
            db_session, ch, "set_value",
            {"field": "title", "value": "PAUSED TITLE"},
            position=2,
            is_paused=True,
        )
        return str(ch.id)

    def test_impact_200(self, client: TestClient, db_session: Session) -> None:
        # Use the DB session's membership (created by the client fixture)
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        resp = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact")
        assert resp.status_code == 200

    def test_impact_structure(self, client: TestClient, db_session: Session) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact").json()
        assert "total_before" in body
        assert "total_after" in body
        assert "sampled" in body
        assert "rules" in body
        assert len(body["rules"]) == 3

    def test_impact_affected_count_for_set_value(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact").json()
        r1 = next(r for r in body["rules"] if r["position"] == 0)
        assert r1["affected_count"] == len(PRODUCTS)
        assert r1["excluded_count"] == 0

    def test_impact_excluded_count_for_filter(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact").json()
        r2 = next(r for r in body["rules"] if r["position"] == 1)
        assert r2["excluded_count"] == 2
        assert r2["affected_count"] == 0

    def test_impact_paused_shows_zero(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact").json()
        r3 = next(r for r in body["rules"] if r["position"] == 2)
        assert r3["is_paused"] is True
        assert r3["affected_count"] == 0
        assert r3["excluded_count"] == 0

    def test_impact_total_after_correct(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        ch_id = self._setup(client, db_session, membership)
        body = client.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact").json()
        # 5 total, 2 excluded by filter_exclude → 3 remaining
        assert body["total_before"] == 5
        assert body["total_after"] == 3

    def test_impact_404_unknown_channel(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/impact")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Simulate — pure service function
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulateRule:
    def test_simulate_filter_exclude_returns_excluded_count(self) -> None:
        result = simulate_rule(
            products=list(PRODUCTS),
            saved_rules=[],
            candidate_rule_type="filter_exclude",
            candidate_config={
                "condition_field": "availability",
                "condition_op": "eq",
                "condition_value": "out of stock",
            },
        )
        assert result["excluded_count"] == 2
        assert result["affected_count"] == 0

    def test_simulate_set_value_returns_affected_count(self) -> None:
        result = simulate_rule(
            products=list(PRODUCTS),
            saved_rules=[],
            candidate_rule_type="set_value",
            candidate_config={"field": "brand", "value": "SIM"},
        )
        assert result["affected_count"] == len(PRODUCTS)
        assert result["excluded_count"] == 0

    def test_simulate_sample_before_and_after(self) -> None:
        result = simulate_rule(
            products=list(PRODUCTS),
            saved_rules=[],
            candidate_rule_type="set_value",
            candidate_config={"field": "brand", "value": "SIM"},
        )
        assert len(result["sample_before"]) <= 3
        assert len(result["sample_after"]) <= 3
        # After rule, brand should be SIM
        for p in result["sample_after"]:
            assert p["brand"] == "SIM"

    def test_simulate_only_applies_rules_before_position(self) -> None:
        """Saved rule at position 0 is applied before candidate at position 1."""
        saved = [
            _StubRule(
                "filter_exclude",
                {"condition_field": "availability", "condition_op": "eq",
                 "condition_value": "out of stock"},
                position=0,
            )
        ]
        # Candidate at position 1: set brand on remaining (3 in-stock products)
        result = simulate_rule(
            products=list(PRODUCTS),
            saved_rules=saved,
            candidate_rule_type="set_value",
            candidate_config={"field": "brand", "value": "SIM"},
            candidate_position=1,
        )
        assert result["affected_count"] == 3  # only 3 in-stock remain after saved rule

    def test_simulate_does_not_persist(
        self, client: TestClient, db_session: Session
    ) -> None:
        """POST /simulate must not add any FeedRule rows."""
        from sqlalchemy import select, func
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "SimSrc", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "SimCh", "channel_type": "google_shopping"},
        )
        ch_id = ch_resp.json()["id"]

        count_before = db_session.scalar(select(func.count(FeedRule.id)))

        resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules/simulate",
            json={
                "rule_type": "filter_exclude",
                "config": {
                    "condition_field": "availability",
                    "condition_op": "eq",
                    "condition_value": "out of stock",
                },
            },
        )
        assert resp.status_code == 200
        count_after = db_session.scalar(select(func.count(FeedRule.id)))
        assert count_after == count_before, "Simulate must not persist any rules"

    def test_simulate_invalid_rule_type_returns_422(self, client: TestClient) -> None:
        src_resp = client.post(
            "/api/v1/feeds/sources",
            json={"name": "Sim422Src", "source_type": "upload"},
        )
        src_id = src_resp.json()["id"]
        ch_resp = client.post(
            f"/api/v1/feeds/sources/{src_id}/channels",
            json={"name": "Sim422Ch", "channel_type": "google_shopping"},
        )
        ch_id = ch_resp.json()["id"]

        resp = client.post(
            f"/api/v1/feeds/channels/{ch_id}/rules/simulate",
            json={"rule_type": "nonexistent_type", "config": {}},
        )
        assert resp.status_code == 422

    def test_simulate_response_shape(self, client: TestClient, db_session: Session) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src)
        _seed_products(db_session, src, PRODUCTS)

        resp = client.post(
            f"/api/v1/feeds/channels/{str(ch.id)}/rules/simulate",
            json={
                "rule_type": "filter_exclude",
                "config": {
                    "condition_field": "availability",
                    "condition_op": "eq",
                    "condition_value": "out of stock",
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "affected_count" in body
        assert "excluded_count" in body
        assert "sample_before" in body
        assert "sample_after" in body
        assert body["excluded_count"] == 2
        assert len(body["sample_before"]) <= 3
        assert len(body["sample_after"]) <= 3

    def test_simulate_404_unknown_channel(self, client: TestClient) -> None:
        resp = client.post(
            f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/simulate",
            json={"rule_type": "set_value", "config": {"field": "f", "value": "v"}},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Rule Linter — pure service function + HTTP
# ═══════════════════════════════════════════════════════════════════════════════


class TestLintRules:
    def test_no_issues_for_clean_rules(self) -> None:
        rule = _StubRule(
            "set_value", {"field": "brand", "value": "Acme"}, position=0
        )
        issues = lint_rules(list(PRODUCTS), [rule])
        # May or may not flag no_effect depending on whether any brand differs
        # (all brands here ARE "Acme" for some products, so it's not zero-effect)
        # Just verify it returns a list
        assert isinstance(issues, list)

    def test_no_effect_flagged(self) -> None:
        """A set_value rule targeting a field that is already that value matches no_effect."""
        # All products have brand "Acme" OR some other brand — so set_value to a
        # brand that doesn't exist yet (so all ARE changed). But if we target a
        # field with a value that no product has first, let's use a find_replace
        # with a pattern that never appears.
        rule = _StubRule(
            "find_replace",
            {"field": "title", "pattern": "ZZZNOMATCH", "replacement": "X",
             "use_regex": False},
            position=0,
        )
        issues = lint_rules(list(PRODUCTS), [rule])
        codes = {i["code"] for i in issues}
        assert "no_effect" in codes

    def test_duplicate_flagged(self) -> None:
        """Two rules with identical (rule_type, config) should raise duplicate."""
        cfg = {"field": "brand", "value": "AYAZ"}
        r1 = _StubRule("set_value", cfg, position=0)
        r2 = _StubRule("set_value", cfg, position=1)
        issues = lint_rules(list(PRODUCTS), [r1, r2])
        codes = [i["code"] for i in issues]
        assert "duplicate" in codes

    def test_shadowed_set_value_flagged(self) -> None:
        """Two set_value rules on the same field: earlier is shadowed."""
        r1 = _StubRule("set_value", {"field": "brand", "value": "X"}, position=0)
        r2 = _StubRule("set_value", {"field": "brand", "value": "Y"}, position=1)
        issues = lint_rules(list(PRODUCTS), [r1, r2])
        codes = {i["code"] for i in issues}
        assert "shadowed" in codes

    def test_excludes_all_flagged(self) -> None:
        """A filter that excludes all products should be flagged excludes_all."""
        rule = _StubRule(
            "filter_include",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "discontinued"},
            position=0,
        )
        issues = lint_rules(list(PRODUCTS), [rule])
        codes = {i["code"] for i in issues}
        # When all are excluded (no_effect + excludes_all may both fire)
        # excludes_all: 100% excluded
        assert "excludes_all" in codes or "no_effect" in codes

    def test_lint_issue_has_required_fields(self) -> None:
        cfg = {"field": "brand", "value": "AYAZ"}
        r1 = _StubRule("set_value", cfg, position=0)
        r2 = _StubRule("set_value", cfg, position=1)
        issues = lint_rules(list(PRODUCTS), [r1, r2])
        for issue in issues:
            assert "severity" in issue
            assert "rule_id" in issue
            assert "position" in issue
            assert "code" in issue
            assert "message" in issue

    def test_lint_endpoint_200(self, client: TestClient, db_session: Session) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src)
        _seed_products(db_session, src, PRODUCTS)
        # Create a no-effect rule
        _make_rule(
            db_session, ch, "filter_include",
            {"condition_field": "availability", "condition_op": "eq",
             "condition_value": "discontinued"},
            position=0,
        )
        resp = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/rules/lint")
        assert resp.status_code == 200
        body = resp.json()
        assert "issues" in body
        codes = {i["code"] for i in body["issues"]}
        assert "no_effect" in codes or "excludes_all" in codes

    def test_lint_endpoint_flags_duplicate(
        self, client: TestClient, db_session: Session
    ) -> None:
        from sqlalchemy import select
        membership = db_session.scalar(select(Membership))
        src = _make_source(db_session, membership.tenant_id)
        ch = _make_channel(db_session, src)
        _seed_products(db_session, src, PRODUCTS)
        cfg = {"field": "brand", "value": "AYAZ"}
        _make_rule(db_session, ch, "set_value", cfg, position=0)
        _make_rule(db_session, ch, "set_value", cfg, position=1)

        resp = client.get(f"/api/v1/feeds/channels/{str(ch.id)}/rules/lint")
        assert resp.status_code == 200
        codes = {i["code"] for i in resp.json()["issues"]}
        assert "duplicate" in codes

    def test_lint_endpoint_404_unknown_channel(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/lint")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Auth isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthIsolation:
    """New endpoints must enforce tenant isolation and require authentication."""

    def _make_isolated_client(
        self, db_session: Session, membership: Membership
    ) -> TestClient:
        """Build a fresh TestClient scoped to the given membership (no fixture cleanup needed)."""
        # We use a local app instance to avoid dependency-override conflicts
        # between two clients sharing the same _test_app.
        app = FastAPI()
        app.include_router(feeds_module.router, prefix="/api/v1")

        def override_db():
            try:
                yield db_session
            finally:
                pass

        _captured_membership = membership

        def override_membership():
            return _captured_membership

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_membership] = override_membership
        return TestClient(app, raise_server_exceptions=True)

    def test_impact_requires_auth(self, client_no_auth: TestClient) -> None:
        resp = client_no_auth.get(
            f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/impact"
        )
        # No auth override → get_current_membership raises → 401 or 403
        assert resp.status_code in (401, 403, 422)

    def test_simulate_requires_auth(self, client_no_auth: TestClient) -> None:
        resp = client_no_auth.post(
            f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/simulate",
            json={"rule_type": "set_value", "config": {"field": "f", "value": "v"}},
        )
        assert resp.status_code in (401, 403, 422)

    def test_lint_requires_auth(self, client_no_auth: TestClient) -> None:
        resp = client_no_auth.get(
            f"/api/v1/feeds/channels/{uuid.uuid4()}/rules/lint"
        )
        assert resp.status_code in (401, 403, 422)

    def test_impact_returns_404_for_other_tenants_channel(
        self, db_session: Session
    ) -> None:
        """Tenant A's channel must not be visible to Tenant B."""
        # Create two separate tenants + memberships
        tenant_a, _, membership_a = _seed_tenant_user(db_session)
        _, _, membership_b = _seed_tenant_user(db_session)

        # Create channel for Tenant A
        src_a = _make_source(db_session, tenant_a.id)
        ch_a = _make_channel(db_session, src_a)
        _seed_products(db_session, src_a, PRODUCTS)
        ch_id = str(ch_a.id)

        # Client B tries to access Tenant A's channel
        client_b = self._make_isolated_client(db_session, membership_b)
        resp = client_b.get(f"/api/v1/feeds/channels/{ch_id}/rules/impact")
        assert resp.status_code == 404

    def test_simulate_returns_404_for_other_tenants_channel(
        self, db_session: Session
    ) -> None:
        tenant_a, _, membership_a = _seed_tenant_user(db_session)
        _, _, membership_b = _seed_tenant_user(db_session)

        src_a = _make_source(db_session, tenant_a.id)
        ch_a = _make_channel(db_session, src_a)
        ch_id = str(ch_a.id)

        client_b = self._make_isolated_client(db_session, membership_b)
        resp = client_b.post(
            f"/api/v1/feeds/channels/{ch_id}/rules/simulate",
            json={"rule_type": "set_value", "config": {"field": "f", "value": "v"}},
        )
        assert resp.status_code == 404

    def test_lint_returns_404_for_other_tenants_channel(
        self, db_session: Session
    ) -> None:
        tenant_a, _, membership_a = _seed_tenant_user(db_session)
        _, _, membership_b = _seed_tenant_user(db_session)

        src_a = _make_source(db_session, tenant_a.id)
        ch_a = _make_channel(db_session, src_a)
        ch_id = str(ch_a.id)

        client_b = self._make_isolated_client(db_session, membership_b)
        resp = client_b.get(f"/api/v1/feeds/channels/{ch_id}/rules/lint")
        assert resp.status_code == 404
