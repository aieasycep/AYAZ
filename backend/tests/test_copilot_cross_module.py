"""Tests for Copilot awareness of budget / inbox / executive modules (Dalga 64)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.budget import BudgetPlan
from ayaz.models.social_inbox import SocialMessage
from ayaz.models.oltp import Tenant

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        _SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.budget  # noqa: F401
    import ayaz.models.content  # noqa: F401
    import ayaz.models.copilot  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.goals  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.notifications  # noqa: F401
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.social_inbox  # noqa: F401
    import ayaz.models.tracking  # noqa: F401

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)


def _tenant(db: Session) -> Tenant:
    t = Tenant(id=uuid.uuid4(), name="T", base_currency="TRY", country="TR", kvkk_region="TR")
    db.add(t)
    db.flush()
    return t


class TestRegistry:
    def test_tools_registered(self) -> None:
        from ayaz.services.copilot_tools import _TOOLS

        assert "get_budget_status" in _TOOLS
        assert "get_inbox_summary" in _TOOLS
        assert "get_executive_summary" in _TOOLS

    def test_tool_specs(self) -> None:
        from ayaz.services.copilot_tools import TOOL_SPECS

        names = {s["name"] for s in TOOL_SPECS}
        assert {"get_budget_status", "get_inbox_summary", "get_executive_summary"} <= names


class TestBudgetStatus:
    def test_no_plan(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_budget_status

        t = _tenant(db_session)
        assert _get_budget_status(db=db_session, tenant_id=t.id)["has_plan"] is False

    def test_with_plan(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_budget_status

        t = _tenant(db_session)
        db_session.add(BudgetPlan(
            tenant_id=t.id, name="Temmuz", period_month="2026-07",
            total_budget=100000, currency="TRY", objective="balanced",
            lookback_days=90,
            allocations={"platforms": [{"label": "Meta Ads", "recommended_budget": 60000,
                                        "recommended_share": 60.0}],
                         "projection": {"expected_revenue": 300000, "expected_roas": 3.0}},
            status="active",
        ))
        db_session.commit()
        r = _get_budget_status(db=db_session, tenant_id=t.id)
        assert r["has_plan"] is True
        assert r["total_budget"] == 100000
        assert r["top_platforms"][0]["label"] == "Meta Ads"


class TestInboxSummary:
    def test_summary(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_inbox_summary

        t = _tenant(db_session)
        for st in ("open", "open", "resolved"):
            db_session.add(SocialMessage(
                tenant_id=t.id, channel="instagram", kind="dm",
                author_handle="@u", text="x", sentiment="neutral", status=st,
                tags=[], received_at="2026-06-25T10:00:00+00:00",
            ))
        db_session.commit()
        r = _get_inbox_summary(db=db_session, tenant_id=t.id)
        assert r["total"] == 3
        assert r["open"] == 2
        assert r["resolved"] == 1


class TestExecutiveSummary:
    def test_summary_empty(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_executive_summary

        t = _tenant(db_session)
        r = _get_executive_summary(db=db_session, tenant_id=t.id)
        assert "kpis" in r and "headline" in r


class TestIntentRouting:
    def test_budget_intent(self, db_session: Session) -> None:
        from ayaz.services.copilot import _stub_chat

        t = _tenant(db_session)
        db_session.commit()
        reply = _stub_chat(db_session, t.id, "Bütçe planım ne durumda?")
        assert any(tu.name == "get_budget_status" for tu in reply.tools_used)

    def test_inbox_intent(self, db_session: Session) -> None:
        from ayaz.services.copilot import _stub_chat

        t = _tenant(db_session)
        db_session.commit()
        reply = _stub_chat(db_session, t.id, "Gelen kutusunda kaç açık mesaj var?")
        assert any(tu.name == "get_inbox_summary" for tu in reply.tools_used)

    def test_executive_intent(self, db_session: Session) -> None:
        from ayaz.services.copilot import _stub_chat

        t = _tenant(db_session)
        db_session.commit()
        reply = _stub_chat(db_session, t.id, "Yönetici özeti ver, genel durum nasıl?")
        assert any(tu.name == "get_executive_summary" for tu in reply.tools_used)

    def test_performance_still_routes(self, db_session: Session) -> None:
        # Ensure the new intents did not steal plain performance queries
        from ayaz.services.copilot import _stub_chat

        t = _tenant(db_session)
        db_session.commit()
        reply = _stub_chat(db_session, t.id, "Performans özeti ver")
        assert any(tu.name == "get_performance_summary" for tu in reply.tools_used)
