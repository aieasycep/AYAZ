"""Tests for the Copilot content-planner tool + intent (Dalga 59).

Covers
------
1. get_content_status registered in _TOOLS and TOOL_SPECS.
2. _get_content_status aggregates counts by status + upcoming scheduled posts,
   tenant-isolated.
3. _stub_chat routes content-planner phrasings to the get_content_status tool.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.content import ContentPost
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.services.auth import hash_password

_SQLITE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.content  # noqa: F401
    import ayaz.models.copilot  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.goals  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.notifications  # noqa: F401
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.tracking  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_tenant(db: Session, name: str = "T") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name, base_currency="TRY", country="TR", kvkk_region="TR"
    )
    db.add(t)
    db.flush()
    return t


def _make_post(
    db: Session, tenant: Tenant, title: str, status: str, scheduled_at: str | None = None
) -> ContentPost:
    p = ContentPost(
        tenant_id=tenant.id,
        title=title,
        body="x",
        channels=["instagram"],
        scheduled_at=scheduled_at,
        status=status,
    )
    db.add(p)
    db.flush()
    return p


class TestRegistry:
    def test_tool_registered(self) -> None:
        from ayaz.services.copilot_tools import _TOOLS

        assert "get_content_status" in _TOOLS

    def test_in_tool_specs(self) -> None:
        from ayaz.services.copilot_tools import TOOL_SPECS

        assert any(s["name"] == "get_content_status" for s in TOOL_SPECS)


class TestGetContentStatus:
    def test_empty(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_content_status

        t = _make_tenant(db_session)
        result = _get_content_status(db=db_session, tenant_id=t.id)
        assert result["total"] == 0
        assert result["upcoming"] == []

    def test_counts_and_upcoming(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_content_status

        t = _make_tenant(db_session)
        _make_post(db_session, t, "Taslak 1", "draft")
        _make_post(db_session, t, "Onayda", "pending_approval")
        _make_post(db_session, t, "Geç", "scheduled", "2026-07-10T10:00:00+00:00")
        _make_post(db_session, t, "Erken", "scheduled", "2026-07-01T10:00:00+00:00")
        db_session.commit()

        result = _get_content_status(db=db_session, tenant_id=t.id)
        assert result["total"] == 4
        assert result["draft"] == 1
        assert result["pending_approval"] == 1
        assert result["scheduled"] == 2
        # upcoming sorted soonest-first
        assert result["upcoming"][0]["title"] == "Erken"

    def test_tenant_isolation(self, db_session: Session) -> None:
        from ayaz.services.copilot_tools import _get_content_status

        t1 = _make_tenant(db_session, "T1")
        t2 = _make_tenant(db_session, "T2")
        _make_post(db_session, t1, "T1 içerik", "draft")
        _make_post(db_session, t2, "T2 içerik", "draft")
        db_session.commit()

        result = _get_content_status(db=db_session, tenant_id=t1.id)
        assert result["total"] == 1


class TestContentIntentRouting:
    def test_stub_routes_content_query(self, db_session: Session) -> None:
        from ayaz.services.copilot import _stub_chat

        t = _make_tenant(db_session)
        _make_post(db_session, t, "Yaz kampanyası", "pending_approval")
        db_session.commit()

        reply = _stub_chat(db_session, t.id, "Kaç içerik onay bekliyor?")
        assert any(tu.name == "get_content_status" for tu in reply.tools_used)
        assert "içerik" in reply.text.lower()

    def test_stub_social_media_phrasing(self, db_session: Session) -> None:
        from ayaz.services.copilot import _stub_chat

        t = _make_tenant(db_session)
        db_session.commit()
        reply = _stub_chat(db_session, t.id, "Sosyal medya gönderilerim ne durumda?")
        assert any(tu.name == "get_content_status" for tu in reply.tools_used)
