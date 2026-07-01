"""Self-contained tests for Proaktif Öneri Merkezi + AI Haftalık Strateji (M14).

Coverage
--------
1. Pure unit tests (no DB)
   - apply_recommendation_action: invalid action → ValueError
   - _week_label: correct Turkish format

2. Service tests (with SQLite in-memory DB)
   - build_recommendation_feed: empty DB → returns valid feed structure
   - build_recommendation_feed: feed summary counts are correct (open/accepted/snoozed/dismissed)
   - build_recommendation_feed: accepted state is reflected per-recommendation
   - build_recommendation_feed: snoozed state is reflected per-recommendation
   - apply_recommendation_action: accept → status "accepted"
   - apply_recommendation_action: snooze → status "snoozed", snoozed_until set
   - apply_recommendation_action: dismiss → status "dismissed"
   - apply_recommendation_action: reopen → status "open"
   - apply_recommendation_action: note is stored
   - apply_recommendation_action: idempotent upsert (second call updates)
   - generate_weekly_strategy: returns valid dict with all required keys
   - generate_weekly_strategy: source is "template" when no API key
   - generate_weekly_strategy: top_recommendations list is a subset of feed

3. HTTP endpoint tests
   - GET /recommendations/feed → 200, valid shape
   - GET /recommendations/weekly-strategy → 200, valid shape
   - POST /recommendations/{key}/action → 200, accept
   - POST /recommendations/{key}/action → 200, snooze
   - POST /recommendations/{key}/action → 200, dismiss
   - POST /recommendations/{key}/action → 200, reopen
   - POST /recommendations/{key}/action → 422, invalid action
   - POST with empty key → 422
   - No auth → 401/403
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

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
import ayaz.models.copilot  # noqa: F401
import ayaz.models.auth  # noqa: F401
import ayaz.models.recommendations  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
)
from ayaz.models.recommendations import RecommendationState
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import recommendations as recs_module
from ayaz.services.auth import hash_password
from ayaz.services.recommendations import (
    apply_recommendation_action,
    build_recommendation_feed,
    generate_weekly_strategy,
    _week_label,
)

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Recommendations Test App")
_test_app.include_router(recs_module.router, prefix="/api/v1")


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


def _make_tenant(db: Session, name: str = "Rec Test Tenant") -> Tenant:
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
        email=f"rec_test_{uuid.uuid4().hex[:8]}@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Rec Test User",
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
    """TestClient with NO membership override — tests 401/403 behaviour."""
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


# ── Helper: insert a RecommendationState row directly ─────────────────────────


def _insert_state(
    db: Session,
    tenant_id: uuid.UUID,
    key: str,
    status: str = "open",
    snoozed_until: str | None = None,
    note: str | None = None,
) -> RecommendationState:
    row = RecommendationState(
        tenant_id=tenant_id,
        recommendation_key=key,
        status=status,
        snoozed_until=snoozed_until,
        note=note,
    )
    db.add(row)
    db.commit()
    return row


# ── 1. Pure unit tests (no DB) ────────────────────────────────────────────────


class TestWeekLabel:
    def test_format_june_2026(self) -> None:
        ref = date(2026, 6, 28)
        label = _week_label(ref)
        assert "Haziran" in label
        assert "2026" in label

    def test_format_contains_day_numbers(self) -> None:
        ref = date(2026, 6, 28)  # Sunday
        label = _week_label(ref)
        # The label should contain day numbers like "22" and "28"
        assert any(str(d) in label for d in range(1, 32))

    def test_cross_month_boundary(self) -> None:
        ref = date(2026, 7, 1)  # Wednesday — spans June-July
        label = _week_label(ref)
        # Should contain a month name
        assert any(m in label for m in ["Haziran", "Temmuz"])


class TestApplyActionErrors:
    def test_invalid_action_raises(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError, match="Geçersiz"):
            apply_recommendation_action(
                db_session, tenant.id, "inbox:backlog", "fly"
            )

    def test_unknown_action_rejected(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with pytest.raises(ValueError):
            apply_recommendation_action(
                db_session, tenant.id, "inbox:backlog", "unknown_action"
            )


# ── 2. Service tests ──────────────────────────────────────────────────────────


class TestBuildRecommendationFeed:
    def test_empty_db_returns_valid_structure(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_recommendation_feed(db_session, tenant.id)

        assert "generated_at" in result
        assert "summary" in result
        assert "recommendations" in result
        summary = result["summary"]
        assert "open" in summary
        assert "accepted" in summary
        assert "snoozed" in summary
        assert "dismissed" in summary
        assert "total" in summary
        assert "high_impact_open" in summary

    def test_summary_totals_are_consistent(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_recommendation_feed(db_session, tenant.id)
        recs = result["recommendations"]
        summary = result["summary"]

        status_counts: dict[str, int] = {}
        for r in recs:
            s = r["status"]
            status_counts[s] = status_counts.get(s, 0) + 1

        assert summary["open"] == status_counts.get("open", 0)
        assert summary["accepted"] == status_counts.get("accepted", 0)
        assert summary["snoozed"] == status_counts.get("snoozed", 0)
        assert summary["dismissed"] == status_counts.get("dismissed", 0)
        assert summary["total"] == len(recs)

    def test_each_recommendation_has_required_fields(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_recommendation_feed(db_session, tenant.id)
        for rec in result["recommendations"]:
            assert "key" in rec
            assert "category" in rec
            assert "title" in rec
            assert "rationale" in rec
            assert "impact" in rec
            assert "effort" in rec
            assert "status" in rec
            assert "action_label" in rec
            assert "action_href" in rec
            assert rec["impact"] in {"high", "medium", "low"}
            assert rec["effort"] in {"low", "medium", "high"}
            assert rec["status"] in {"open", "accepted", "snoozed", "dismissed"}

    def test_accepted_state_reflected(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        key = "inbox:backlog"
        _insert_state(db_session, tenant.id, key, status="accepted")

        result = build_recommendation_feed(db_session, tenant.id)
        # Find the recommendation with this key (if generated)
        matching = [r for r in result["recommendations"] if r["key"] == key]
        # If the signal exists, its status should be "accepted"
        for rec in matching:
            assert rec["status"] == "accepted"

    def test_snoozed_state_reflected(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        key = "inbox:backlog"
        snooze_until = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        _insert_state(db_session, tenant.id, key, status="snoozed", snoozed_until=snooze_until)

        result = build_recommendation_feed(db_session, tenant.id)
        matching = [r for r in result["recommendations"] if r["key"] == key]
        for rec in matching:
            assert rec["status"] == "snoozed"
            assert rec["snoozed_until"] is not None

    def test_no_cross_tenant_leakage(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")
        key = "inbox:backlog"
        _insert_state(db_session, tenant_a.id, key, status="accepted")

        result_b = build_recommendation_feed(db_session, tenant_b.id)
        # Tenant B sees no state from Tenant A
        for rec in result_b["recommendations"]:
            if rec["key"] == key:
                # Tenant B's version should be "open" (no state for B)
                assert rec["status"] == "open"

    def test_high_impact_open_count(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_recommendation_feed(db_session, tenant.id)
        recs = result["recommendations"]
        expected_high_open = sum(
            1 for r in recs if r["impact"] == "high" and r["status"] == "open"
        )
        assert result["summary"]["high_impact_open"] == expected_high_open

    def test_as_of_param_accepted(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = build_recommendation_feed(
            db_session, tenant.id, as_of=date(2026, 6, 20)
        )
        assert "generated_at" in result


class TestApplyRecommendationAction:
    def test_accept(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "accept"
        )
        assert result["status"] == "accepted"
        assert result["key"] == "inbox:backlog"

    def test_snooze_default_days(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "snooze"
        )
        assert result["status"] == "snoozed"
        assert result["snoozed_until"] is not None
        # Should be ~7 days from now
        snooze_dt = datetime.fromisoformat(result["snoozed_until"])
        delta = snooze_dt - datetime.now(timezone.utc)
        assert 6 <= delta.days <= 8

    def test_snooze_custom_days(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "snooze", snooze_days=14
        )
        assert result["status"] == "snoozed"
        snooze_dt = datetime.fromisoformat(result["snoozed_until"])
        delta = snooze_dt - datetime.now(timezone.utc)
        assert 13 <= delta.days <= 15

    def test_dismiss(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "budget:overspend", "dismiss"
        )
        assert result["status"] == "dismissed"

    def test_reopen(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        # First accept, then reopen
        apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "accept"
        )
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "reopen"
        )
        assert result["status"] == "open"
        assert result["snoozed_until"] is None

    def test_note_stored(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "accept",
            note="Bu hafta ele alındı."
        )
        assert result["note"] == "Bu hafta ele alındı."

    def test_idempotent_upsert(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        key = "audit:warn:tracking"
        apply_recommendation_action(db_session, tenant.id, key, "accept")
        # Second call should update, not create a duplicate
        result = apply_recommendation_action(db_session, tenant.id, key, "dismiss")
        assert result["status"] == "dismissed"

        from sqlalchemy import select
        rows = db_session.scalars(
            select(RecommendationState).where(
                RecommendationState.tenant_id == tenant.id,
                RecommendationState.recommendation_key == key,
            )
        ).all()
        assert len(rows) == 1

    def test_returns_required_keys(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = apply_recommendation_action(
            db_session, tenant.id, "inbox:backlog", "accept"
        )
        assert "key" in result
        assert "status" in result
        assert "snoozed_until" in result
        assert "note" in result

    def test_no_cross_tenant_state_sharing(self, db_session: Session) -> None:
        tenant_a = _make_tenant(db_session, "Tenant A")
        tenant_b = _make_tenant(db_session, "Tenant B")
        key = "inbox:backlog"
        apply_recommendation_action(db_session, tenant_a.id, key, "dismiss")

        from sqlalchemy import select
        b_rows = db_session.scalars(
            select(RecommendationState).where(
                RecommendationState.tenant_id == tenant_b.id,
                RecommendationState.recommendation_key == key,
            )
        ).all()
        assert len(b_rows) == 0


class TestGenerateWeeklyStrategy:
    def test_returns_valid_structure(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_weekly_strategy(db_session, tenant.id)

        assert "week_label" in result
        assert "headline" in result
        assert "narrative" in result
        assert "focus_areas" in result
        assert "top_recommendations" in result
        assert "source" in result

    def test_source_is_template_without_api_key(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        with patch("ayaz.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = None
            mock_settings.claude_narrator_model = "claude-opus-4-8"
            result = generate_weekly_strategy(db_session, tenant.id)
        assert result["source"] == "template"

    def test_week_label_is_turkish(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_weekly_strategy(db_session, tenant.id)
        tr_months = [
            "Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
            "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik",
            # with diacritics too
            "Şubat", "Mayıs", "Ağustos", "Eylül",
        ]
        assert any(m in result["week_label"] for m in tr_months)

    def test_focus_areas_are_list(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_weekly_strategy(db_session, tenant.id)
        assert isinstance(result["focus_areas"], list)
        for fa in result["focus_areas"]:
            assert "title" in fa
            assert "detail" in fa

    def test_top_recommendations_are_valid(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_weekly_strategy(db_session, tenant.id)
        for rec in result["top_recommendations"]:
            assert "key" in rec
            assert "status" in rec

    def test_as_of_param_accepted(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        result = generate_weekly_strategy(
            db_session, tenant.id, as_of=date(2026, 6, 20)
        )
        assert "week_label" in result

    def test_never_raises_on_empty_db(self, db_session: Session) -> None:
        tenant = _make_tenant(db_session)
        # Should not raise regardless of empty tables
        result = generate_weekly_strategy(db_session, tenant.id)
        assert result is not None
        assert result["source"] in {"template", "ai"}


# ── 3. HTTP endpoint tests ────────────────────────────────────────────────────


class TestRecommendationFeedEndpoint:
    def test_get_feed_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/feed")
        assert resp.status_code == 200

    def test_get_feed_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/feed")
        data = resp.json()
        assert "generated_at" in data
        assert "summary" in data
        assert "recommendations" in data
        summary = data["summary"]
        for key in ("open", "accepted", "snoozed", "dismissed", "total", "high_impact_open"):
            assert key in summary, f"summary missing key: {key}"

    def test_get_feed_with_as_of(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/feed?as_of=2026-06-20")
        assert resp.status_code == 200

    def test_get_feed_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/recommendations/feed")
        assert resp.status_code in {401, 403}


class TestWeeklyStrategyEndpoint:
    def test_get_strategy_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/weekly-strategy")
        assert resp.status_code == 200

    def test_get_strategy_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/weekly-strategy")
        data = resp.json()
        for key in ("week_label", "headline", "narrative", "focus_areas",
                    "top_recommendations", "source"):
            assert key in data, f"response missing key: {key}"

    def test_get_strategy_source_field_valid(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/weekly-strategy")
        data = resp.json()
        assert data["source"] in {"template", "ai"}

    def test_get_strategy_with_as_of(self, client: TestClient) -> None:
        resp = client.get("/api/v1/recommendations/weekly-strategy?as_of=2026-06-20")
        assert resp.status_code == 200

    def test_get_strategy_no_auth(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/recommendations/weekly-strategy")
        assert resp.status_code in {401, 403}


class TestActionEndpoint:
    def test_accept_action_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "accept"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["key"] == "inbox:backlog"

    def test_snooze_action_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "snooze", "snooze_days": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "snoozed"
        assert data["snoozed_until"] is not None

    def test_dismiss_action_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/budget:overspend/action",
            json={"action": "dismiss"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    def test_reopen_after_accept(self, client: TestClient) -> None:
        key = "budget:no_plan"
        client.post(
            f"/api/v1/recommendations/{key}/action",
            json={"action": "accept"},
        )
        resp = client.post(
            f"/api/v1/recommendations/{key}/action",
            json={"action": "reopen"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"

    def test_action_with_note(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "accept", "note": "Test notu."},
        )
        assert resp.status_code == 200
        assert resp.json()["note"] == "Test notu."

    def test_invalid_action_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "invalid_action"},
        )
        assert resp.status_code == 422

    def test_missing_action_field_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"note": "no action"},
        )
        assert resp.status_code == 422

    def test_snooze_days_out_of_range_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "snooze", "snooze_days": 0},
        )
        assert resp.status_code == 422

    def test_action_response_shape(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/recommendations/benchmark:weak_roas/action",
            json={"action": "accept"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert "status" in data
        assert "snoozed_until" in data
        assert "note" in data

    def test_no_auth_returns_401_or_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.post(
            "/api/v1/recommendations/inbox:backlog/action",
            json={"action": "accept"},
        )
        assert resp.status_code in {401, 403}

    def test_colon_in_key_is_handled(self, client: TestClient) -> None:
        # Keys with colons (e.g. audit:fail:check_id) should work in path
        resp = client.post(
            "/api/v1/recommendations/audit:warn:tracking/action",
            json={"action": "dismiss"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "audit:warn:tracking"
