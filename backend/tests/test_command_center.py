"""Self-contained tests for Komuta Merkezi (Command Center) — build_command_center.

Coverage
--------
1. build_command_center with empty tenant
   - zeros in KPIs
   - empty attention list
   - modules: all zeros / False / None

2. Seeded data: critical Insight
   - attention contains a "critical" item pointing to /insights
   - insights module counts correct

3. Seeded data: negative SocialMessage
   - attention contains a "warning" item for inbox
   - modules.inbox.negative == 1

4. Seeded data: pending_approval ContentPost
   - attention contains an "info" item for /content
   - modules.content.pending_approval == 1

5. Attention priority / ordering: critical before warning before info

6. API endpoint 200 happy path
7. API endpoint 401 without auth

Mirror structure of tests/test_executive.py (own SQLite engine, mini FastAPI app,
dependency overrides, fixture-based DB).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
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
import ayaz.models.recommendations  # noqa: F401

from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1 import command_center as command_center_module
from ayaz.models.base import Base
from ayaz.models.content import ContentPost
from ayaz.models.insights import Insight
from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
)
from ayaz.models.social_inbox import SocialMessage
from ayaz.services.auth import hash_password
from ayaz.services.command_center import build_command_center, _is_at_risk

# ── Mini test app ──────────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Command Center Test App")
_test_app.include_router(command_center_module.router, prefix="/api/v1")


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


# ── Client fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session: Session):
    """TestClient with DB + membership dependencies overridden."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="CC Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="cc_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="CC Test User",
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


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override — tests 401 behaviour."""

    def override_db():
        try:
            yield db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "CC Tenant") -> Tenant:
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


def _make_user(db: Session, email: str = "cc@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pw"),
        full_name="CC User",
    )
    db.add(u)
    db.flush()
    return u


def _seed_critical_insight(db: Session, tenant: Tenant) -> Insight:
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="roas_drop",
        severity="critical",
        title="Kritik ROAS düşüşü tespit edildi",
        body="ROAS geçen haftaya göre %30 geriledi.",
        metric="roas",
        channel="google_ads",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 28),
        status="new",
        score=0.95,
        data={},
    )
    db.add(ins)
    db.commit()
    return ins


def _seed_warning_insight(db: Session, tenant: Tenant) -> Insight:
    ins = Insight(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        category="spend_spike",
        severity="warning",
        title="Harcama anomalisi",
        body="Son 7 günde harcama normalin %40 üstüne çıktı.",
        metric="spend",
        channel="meta_ads",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 28),
        status="new",
        score=0.7,
        data={},
    )
    db.add(ins)
    db.commit()
    return ins


def _seed_negative_message(db: Session, tenant: Tenant) -> SocialMessage:
    msg = SocialMessage(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel="instagram",
        kind="comment",
        author_handle="@unhappy_user",
        text="Çok kötü bir deneyim yaşadım, hiç memnun olmadım!",
        sentiment="negative",
        status="open",
        tags=[],
        received_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(msg)
    db.commit()
    return msg


def _seed_open_message(db: Session, tenant: Tenant) -> SocialMessage:
    msg = SocialMessage(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel="facebook",
        kind="dm",
        author_handle="@curious_user",
        text="Ürününüz hakkında bilgi alabilir miyim?",
        sentiment="neutral",
        status="open",
        tags=[],
        received_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(msg)
    db.commit()
    return msg


def _seed_pending_approval_post(db: Session, tenant: Tenant) -> ContentPost:
    post = ContentPost(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Yaz Kampanyası Posteri",
        body="Bu yazın en iyi fırsatlarını kaçırmayın!",
        status="pending_approval",
        channels=["instagram", "facebook"],
    )
    db.add(post)
    db.commit()
    return post


def _seed_draft_post(db: Session, tenant: Tenant) -> ContentPost:
    post = ContentPost(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Taslak İçerik",
        body="Henüz tamamlanmadı.",
        status="draft",
        channels=["instagram"],
    )
    db.add(post)
    db.commit()
    return post


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure helper unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsAtRisk:
    def test_at_risk_when_status_unknown_and_below_100(self) -> None:
        assert _is_at_risk({"status": "behind", "pct_to_target": 50.0}) is True

    def test_not_at_risk_when_on_track(self) -> None:
        assert _is_at_risk({"status": "on_track", "pct_to_target": 70.0}) is False

    def test_not_at_risk_when_pct_100_or_more(self) -> None:
        assert _is_at_risk({"status": "behind", "pct_to_target": 100.0}) is False
        assert _is_at_risk({"status": "behind", "pct_to_target": 120.0}) is False

    def test_not_at_risk_when_ahead(self) -> None:
        assert _is_at_risk({"status": "ahead", "pct_to_target": 85.0}) is False

    def test_at_risk_when_status_empty_and_below_100(self) -> None:
        assert _is_at_risk({"status": "", "pct_to_target": 40.0}) is True

    def test_defensive_none_pct(self) -> None:
        # None pct_to_target defaults to 0 → at risk unless on_track
        assert _is_at_risk({"status": "unknown", "pct_to_target": None}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. build_command_center — empty tenant
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyTenant:
    def test_returns_200_shape(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty CC")
        result = build_command_center(db_session, tenant.id)
        assert set(result.keys()) == {"headline", "kpis", "attention", "modules"}

    def test_kpis_are_zero(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty KPI CC")
        result = build_command_center(db_session, tenant.id)
        kpis = result["kpis"]
        assert kpis["spend"] == 0.0
        assert kpis["revenue"] == 0.0
        assert kpis["roas"] == 0.0
        assert kpis["conversions"] == 0.0

    def test_attention_is_empty(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Attn CC")
        result = build_command_center(db_session, tenant.id)
        assert result["attention"] == []

    def test_modules_zeros(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Mod CC")
        result = build_command_center(db_session, tenant.id)
        modules = result["modules"]
        assert modules["inbox"]["total"] == 0
        assert modules["inbox"]["open"] == 0
        assert modules["inbox"]["negative"] == 0
        assert modules["content"]["draft"] == 0
        assert modules["content"]["pending_approval"] == 0
        assert modules["goals"]["total"] == 0
        assert modules["goals"]["at_risk"] == 0
        assert modules["insights"]["critical"] == 0
        assert modules["insights"]["warning"] == 0

    def test_budget_no_plan(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Empty Budget CC")
        result = build_command_center(db_session, tenant.id)
        budget = result["modules"]["budget"]
        assert budget["has_plan"] is False
        assert budget["period_month"] is None
        assert budget["pace_pct"] is None
        assert budget["pace_status"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Seeded data tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSeededData:
    def test_critical_insight_appears_in_attention(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Critical Tenant")
        _seed_critical_insight(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        attention = result["attention"]
        critical_items = [a for a in attention if a["severity"] == "critical"]
        assert len(critical_items) >= 1
        assert critical_items[0]["module"] == "insights"
        assert critical_items[0]["link"] == "/insights"

    def test_critical_insight_title_correct(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Critical Title Tenant")
        _seed_critical_insight(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        titles = [a["title"] for a in result["attention"] if a["severity"] == "critical"]
        assert any("Kritik" in t or "ROAS" in t or "kritik" in t.lower() for t in titles)

    def test_critical_insight_counted_in_modules(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Critical Count Tenant")
        _seed_critical_insight(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        assert result["modules"]["insights"]["critical"] == 1

    def test_negative_message_appears_as_warning(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Neg Msg Tenant")
        _seed_negative_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        inbox_warnings = [
            a for a in result["attention"]
            if a["severity"] == "warning" and a["module"] == "inbox"
        ]
        assert len(inbox_warnings) == 1

    def test_negative_message_title_mentions_count(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Neg Count Tenant")
        _seed_negative_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        inbox_warn = next(
            (a for a in result["attention"]
             if a["severity"] == "warning" and a["module"] == "inbox"),
            None,
        )
        assert inbox_warn is not None
        assert "1" in inbox_warn["title"]

    def test_negative_message_link_is_inbox(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Neg Link Tenant")
        _seed_negative_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        inbox_warn = next(
            (a for a in result["attention"]
             if a["severity"] == "warning" and a["module"] == "inbox"),
            None,
        )
        assert inbox_warn is not None
        assert inbox_warn["link"] == "/inbox"

    def test_negative_message_counted_in_modules(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Neg Module Tenant")
        _seed_negative_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        assert result["modules"]["inbox"]["negative"] == 1

    def test_pending_approval_post_appears_in_attention(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session, "Pending Tenant")
        _seed_pending_approval_post(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        content_items = [
            a for a in result["attention"] if a["module"] == "content"
        ]
        assert len(content_items) >= 1
        assert content_items[0]["link"] == "/content"

    def test_pending_approval_counted_in_modules(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Pending Count Tenant")
        _seed_pending_approval_post(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        assert result["modules"]["content"]["pending_approval"] == 1

    def test_draft_post_counted_in_content_module(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Draft Tenant")
        _seed_draft_post(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        assert result["modules"]["content"]["draft"] == 1
        # Draft posts should NOT generate an attention item
        draft_items = [
            a for a in result["attention"]
            if a.get("module") == "content"
        ]
        assert len(draft_items) == 0

    def test_open_message_without_negative_is_info(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Open Msg Tenant")
        _seed_open_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        inbox_items = [a for a in result["attention"] if a["module"] == "inbox"]
        assert len(inbox_items) == 1
        assert inbox_items[0]["severity"] == "info"
        assert inbox_items[0]["link"] == "/inbox"

    def test_warning_insight_appears_as_info_in_attention(
        self, db_session: Session
    ) -> None:
        tenant = _make_tenant(db_session, "Warning Tenant")
        _seed_warning_insight(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        insight_info_items = [
            a for a in result["attention"]
            if a["module"] == "insights" and a["severity"] == "info"
        ]
        assert len(insight_info_items) >= 1

    def test_warning_insight_counted_in_modules(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session, "Warning Count Tenant")
        _seed_warning_insight(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        assert result["modules"]["insights"]["warning"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Attention sorting and cap
# ═══════════════════════════════════════════════════════════════════════════════


class TestAttentionOrdering:
    def test_critical_before_warning_before_info(self, db_session: Session) -> None:
        """With critical insight + negative inbox, critical must come first."""
        tenant = _make_tenant(db_session, "Sort Tenant")
        _seed_critical_insight(db_session, tenant)
        _seed_negative_message(db_session, tenant)
        result = build_command_center(db_session, tenant.id)
        attention = result["attention"]
        assert len(attention) >= 2
        severities = [a["severity"] for a in attention]
        # All criticals before any warning; all warnings before any info
        order = {"critical": 0, "warning": 1, "info": 2}
        ordered_vals = [order[s] for s in severities]
        assert ordered_vals == sorted(ordered_vals)

    def test_attention_capped_at_8(self, db_session: Session) -> None:
        """Even with many signals the list must never exceed 8 items."""
        tenant = _make_tenant(db_session, "Cap Tenant")
        # Seed many insights
        for i in range(6):
            ins = Insight(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                category="roas_drop",
                severity="critical" if i < 3 else "warning",
                title=f"Uyarı {i}",
                body="Test",
                metric="roas",
                channel="google_ads",
                period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 28),
                status="new",
                score=0.9,
                data={},
            )
            db_session.add(ins)
        # Seed negative + open messages
        _seed_negative_message(db_session, tenant)
        _seed_open_message(db_session, tenant)
        _seed_pending_approval_post(db_session, tenant)
        db_session.commit()
        result = build_command_center(db_session, tenant.id)
        assert len(result["attention"]) <= 8


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandCenterEndpoint:
    def test_happy_path_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        assert resp.status_code == 200

    def test_response_shape_correct(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"headline", "kpis", "attention", "modules"}
        kpis = body["kpis"]
        assert set(kpis.keys()) >= {"spend", "revenue", "roas", "conversions", "deltas"}
        deltas = kpis["deltas"]
        assert set(deltas.keys()) >= {
            "spend_pct", "revenue_pct", "roas_pct", "conversions_pct"
        }
        assert isinstance(body["attention"], list)
        modules = body["modules"]
        assert set(modules.keys()) >= {
            "budget", "inbox", "content", "goals", "insights"
        }
        budget = modules["budget"]
        assert set(budget.keys()) >= {
            "has_plan", "period_month", "pace_pct", "pace_status"
        }
        inbox = modules["inbox"]
        assert set(inbox.keys()) >= {"total", "open", "pending", "negative"}
        content = modules["content"]
        assert set(content.keys()) >= {"draft", "pending_approval", "scheduled"}
        goals = modules["goals"]
        assert set(goals.keys()) >= {"total", "at_risk"}
        insights = modules["insights"]
        assert set(insights.keys()) >= {"critical", "warning"}

    def test_empty_tenant_returns_empty_attention(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["attention"] == []

    def test_unauthenticated_returns_401_or_403(
        self, unauth_client: TestClient
    ) -> None:
        resp = unauth_client.get("/api/v1/command-center/overview")
        assert resp.status_code in (401, 403)

    def test_headline_is_string(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        assert resp.status_code == 200
        assert isinstance(resp.json()["headline"], str)

    def test_modules_contains_new_keys(self, client: TestClient) -> None:
        """modules must expose recommendations, consent, funnel blocks."""
        resp = client.get("/api/v1/command-center/overview")
        assert resp.status_code == 200
        modules = resp.json()["modules"]
        assert "recommendations" in modules
        assert "consent" in modules
        assert "funnel" in modules

    def test_recommendations_block_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        rec = resp.json()["modules"]["recommendations"]
        assert set(rec.keys()) >= {"open", "high_impact_open", "total"}
        assert isinstance(rec["open"], int)
        assert isinstance(rec["high_impact_open"], int)
        assert isinstance(rec["total"], int)

    def test_consent_block_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        consent = resp.json()["modules"]["consent"]
        assert set(consent.keys()) >= {"score", "grade", "consent_rate_pct"}

    def test_funnel_block_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/command-center/overview")
        funnel = resp.json()["modules"]["funnel"]
        assert set(funnel.keys()) >= {"overall_conversion_pct", "biggest_dropoff_label"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Yeni modül blokları: Öneriler / KVKK Uyum / Dönüşüm Hunisi
# ═══════════════════════════════════════════════════════════════════════════════


class TestNewModuleBlocks:
    """Verify recommendations, consent, funnel blocks populate and degrade safely."""

    def test_recommendations_empty_tenant_defaults(
        self, db_session: Session
    ) -> None:
        """Empty tenant → recommendations block has correct types and
        open <= total, high_impact_open <= open.
        The recommendations service generates items from absence of data
        (e.g. no budget plan, no tracking sources) so non-zero counts are
        expected even for an empty tenant; we verify shape only here."""
        tenant = _make_tenant(db_session, "Rec Empty Tenant")
        result = build_command_center(db_session, tenant.id)
        rec = result["modules"]["recommendations"]
        assert isinstance(rec["open"], int) and rec["open"] >= 0
        assert isinstance(rec["high_impact_open"], int) and rec["high_impact_open"] >= 0
        assert isinstance(rec["total"], int) and rec["total"] >= 0
        assert rec["high_impact_open"] <= rec["open"]
        assert rec["open"] <= rec["total"]

    def test_consent_empty_tenant_defaults(self, db_session: Session) -> None:
        """Empty tenant → consent block has numeric score/grade and 0.0 rate.
        Score and grade are computed from compliance checks even with no events."""
        tenant = _make_tenant(db_session, "Consent Empty Tenant")
        result = build_command_center(db_session, tenant.id)
        consent = result["modules"]["consent"]
        assert "score" in consent
        assert "grade" in consent
        assert "consent_rate_pct" in consent
        # consent_rate_pct is 0.0 when there are no events
        assert consent["consent_rate_pct"] == 0.0
        # score is an integer 0–100 derived from compliance checks
        assert isinstance(consent["score"], int)
        assert 0 <= consent["score"] <= 100
        # grade is one of the three Turkish grade labels
        assert consent["grade"] in ("uyumlu", "kismi", "eksik")

    def test_funnel_empty_tenant_defaults(self, db_session: Session) -> None:
        """Empty tenant → funnel block has 0.0 conversion, no dropoff label."""
        tenant = _make_tenant(db_session, "Funnel Empty Tenant")
        result = build_command_center(db_session, tenant.id)
        funnel = result["modules"]["funnel"]
        assert funnel["overall_conversion_pct"] == 0.0
        assert funnel["biggest_dropoff_label"] is None

    def test_existing_module_keys_unchanged(self, db_session: Session) -> None:
        """Adding new blocks must not alter budget/inbox/content/goals/insights."""
        tenant = _make_tenant(db_session, "Compat Tenant")
        result = build_command_center(db_session, tenant.id)
        modules = result["modules"]
        # All original keys still present
        assert set(modules.keys()) >= {
            "budget", "inbox", "content", "goals", "insights",
            "recommendations", "consent", "funnel",
        }
        # Existing sub-key shapes intact
        assert set(modules["budget"].keys()) == {
            "has_plan", "period_month", "pace_pct", "pace_status"
        }
        assert set(modules["inbox"].keys()) == {"total", "open", "pending", "negative"}
        assert set(modules["content"].keys()) == {
            "draft", "pending_approval", "scheduled"
        }
        assert set(modules["goals"].keys()) == {"total", "at_risk"}
        assert set(modules["insights"].keys()) == {"critical", "warning"}

    def test_recommendations_service_failure_degrades_gracefully(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If build_recommendation_feed raises, modules[recommendations] is safe
        defaults and the rest of build_command_center still succeeds."""
        import ayaz.services.recommendations as rec_mod

        def _boom(*a, **kw):
            raise RuntimeError("simüle hata")

        monkeypatch.setattr(rec_mod, "build_recommendation_feed", _boom)

        tenant = _make_tenant(db_session, "Rec Fail Tenant")
        result = build_command_center(db_session, tenant.id)

        # Top-level keys still intact
        assert set(result.keys()) == {"headline", "kpis", "attention", "modules"}

        # Degraded recommendations block
        rec = result["modules"]["recommendations"]
        assert rec == {"open": 0, "high_impact_open": 0, "total": 0}

        # Other blocks still healthy
        assert "inbox" in result["modules"]
        assert "consent" in result["modules"]
        assert "funnel" in result["modules"]

    def test_consent_service_failure_degrades_gracefully(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If build_consent_center raises, modules[consent] is safe defaults."""
        import ayaz.services.consent_center as cc_mod

        def _boom(*a, **kw):
            raise RuntimeError("simüle hata")

        monkeypatch.setattr(cc_mod, "build_consent_center", _boom)

        tenant = _make_tenant(db_session, "Consent Fail Tenant")
        result = build_command_center(db_session, tenant.id)

        assert set(result.keys()) == {"headline", "kpis", "attention", "modules"}
        consent = result["modules"]["consent"]
        assert consent == {"score": None, "grade": None, "consent_rate_pct": None}
        assert "recommendations" in result["modules"]
        assert "funnel" in result["modules"]

    def test_funnel_service_failure_degrades_gracefully(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If build_funnel raises, modules[funnel] is safe defaults."""
        import ayaz.services.funnel as funnel_mod

        def _boom(*a, **kw):
            raise RuntimeError("simüle hata")

        monkeypatch.setattr(funnel_mod, "build_funnel", _boom)

        tenant = _make_tenant(db_session, "Funnel Fail Tenant")
        result = build_command_center(db_session, tenant.id)

        assert set(result.keys()) == {"headline", "kpis", "attention", "modules"}
        funnel = result["modules"]["funnel"]
        assert funnel == {
            "overall_conversion_pct": None,
            "biggest_dropoff_label": None,
        }
        assert "recommendations" in result["modules"]
        assert "consent" in result["modules"]

    def test_funnel_biggest_dropoff_label_formatted(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When build_funnel returns a biggest_dropoff, label is 'X → Y'."""
        import ayaz.services.funnel as funnel_mod

        fake_funnel = {
            "period": {"date_from": None, "date_to": None},
            "total_events": 200,
            "stages": [],
            "entry_count": 100,
            "final_count": 5,
            "overall_conversion_pct": 5.0,
            "biggest_dropoff": {
                "from_label": "Sepete Ekleme",
                "to_label": "Ödeme Başlatma",
                "dropoff_pct": 60.0,
            },
        }
        monkeypatch.setattr(
            funnel_mod,
            "build_funnel",
            lambda *a, **kw: fake_funnel,
        )

        tenant = _make_tenant(db_session, "Funnel Dropoff Tenant")
        result = build_command_center(db_session, tenant.id)

        funnel = result["modules"]["funnel"]
        assert funnel["overall_conversion_pct"] == 5.0
        assert funnel["biggest_dropoff_label"] == "Sepete Ekleme → Ödeme Başlatma"
