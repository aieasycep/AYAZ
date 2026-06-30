"""Tests for the SEO module.

Coverage
--------
1. seo_service.get_overview — aggregation, trends, top queries/pages
2. seo_service.get_opportunities — striking_distance, low_ctr, cannibalization, top_movers
3. seo_service.emit_seo_insights — writes Insight rows, deduplication
4. seo_service.store_gsc_rows — upsert into seo_search_metrics
5. pagespeed.run_audit — mocked PSI response + offline degraded path
6. DataForSEOIntegration — actions, not-connected state, mocked HTTP
7. SEO router endpoints — tenant isolation, gated backlinks/keywords
8. Seed produces SEO rows
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# ── ORM models (trigger table creation) ──────────────────────────────────────
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401
import ayaz.models.billing  # noqa: F401
import ayaz.models.integrations  # noqa: F401
import ayaz.models.insights  # noqa: F401
import ayaz.models.seo  # noqa: F401

from ayaz.models.base import Base
from ayaz.models.insights import Insight
from ayaz.models.integrations import IntegrationConnection, ProviderGrant
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.seo import SeoSearchMetric
from ayaz.api.deps import get_current_membership, get_db
from ayaz.api.v1.seo import router as seo_router
from ayaz.services.auth import hash_password


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def tenant(db_session: Session) -> Tenant:
    t = Tenant(id=uuid.uuid4(), name="SEO Test Tenant", base_currency="TRY")
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture()
def user(db_session: Session, tenant: Tenant) -> User:
    u = User(
        id=uuid.uuid4(),
        email="seo-test@example.com",
        hashed_password=hash_password("testpass"),
    )
    db_session.add(u)
    db_session.flush()
    mem = Membership(
        id=uuid.uuid4(),
        user_id=u.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db_session.add(mem)
    db_session.flush()
    return u


@pytest.fixture()
def membership(db_session: Session, user: User, tenant: Tenant) -> Membership:
    return db_session.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant.id,
        )
    )


def _make_seo_row(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    query: str = "test sorgu",
    page: str = "https://example.com/",
    clicks: int = 10,
    impressions: int = 100,
    ctr: float = 0.1,
    position: float = 5.0,
    d: date | None = None,
    device: str | None = None,
    country: str | None = None,
) -> SeoSearchMetric:
    if d is None:
        d = date.today() - timedelta(days=1)
    row = SeoSearchMetric(
        tenant_id=tenant_id,
        date=d,
        query=query,
        page=page,
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
        device=device,
        country=country,
        extra={},
    )
    db.add(row)
    db.flush()
    return row


# ═══════════════════════════════════════════════════════════════════════════════
# 1. store_gsc_rows
# ═══════════════════════════════════════════════════════════════════════════════


class TestStoreGscRows:
    def test_inserts_new_rows(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import store_gsc_rows

        rows = [
            {
                "date": "2026-06-01",
                "query": "ayakkabı",
                "page": "https://example.com/",
                "clicks": 50,
                "impressions": 500,
                "ctr": 0.10,
                "position": 3.5,
            },
            {
                "date": "2026-06-02",
                "query": "koşu",
                "page": "https://example.com/kosu",
                "clicks": 20,
                "impressions": 200,
                "ctr": 0.10,
                "position": 7.0,
            },
        ]
        count = store_gsc_rows(db_session, tenant.id, rows)
        assert count == 2
        stored = db_session.scalars(
            select(SeoSearchMetric).where(SeoSearchMetric.tenant_id == tenant.id)
        ).all()
        assert len(stored) == 2

    def test_upserts_existing_rows(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import store_gsc_rows

        rows = [{"date": "2026-06-01", "query": "spor", "page": "https://x.com/", "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 8.0}]
        store_gsc_rows(db_session, tenant.id, rows)
        # Update same key
        rows[0]["clicks"] = 99
        store_gsc_rows(db_session, tenant.id, rows)
        all_rows = db_session.scalars(
            select(SeoSearchMetric).where(SeoSearchMetric.tenant_id == tenant.id)
        ).all()
        assert len(all_rows) == 1
        assert all_rows[0].clicks == 99

    def test_tenant_isolation(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import store_gsc_rows

        other_tenant_id = uuid.uuid4()
        rows = [{"date": "2026-06-01", "query": "test", "page": "https://x.com/", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0}]
        store_gsc_rows(db_session, tenant.id, rows)
        # Other tenant has no rows
        count = db_session.scalar(
            select(SeoSearchMetric).where(SeoSearchMetric.tenant_id == other_tenant_id)
        )
        assert count is None

    def test_caps_oversized_query_and_page(self, db_session: Session, tenant: Tenant) -> None:
        """Adversarially long query/page must be capped before insert so they can
        never breach VARCHAR(2048) or the Postgres btree index-tuple limit
        (which would otherwise abort the ingest/sync transaction)."""
        from ayaz.services.seo import store_gsc_rows, _MAX_QUERY_LEN, _MAX_PAGE_LEN

        rows = [{
            "date": "2026-06-01",
            "query": "q" * 5000,
            "page": "https://example.com/" + "p" * 5000,
            "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0,
        }]
        count = store_gsc_rows(db_session, tenant.id, rows)
        assert count == 1
        stored = db_session.scalars(
            select(SeoSearchMetric).where(SeoSearchMetric.tenant_id == tenant.id)
        ).all()
        assert len(stored) == 1
        assert len(stored[0].query) == _MAX_QUERY_LEN
        assert len(stored[0].page) == _MAX_PAGE_LEN
        # Re-ingesting the same oversized row upserts (no duplicate, no crash).
        store_gsc_rows(db_session, tenant.id, rows)
        again = db_session.scalars(
            select(SeoSearchMetric).where(SeoSearchMetric.tenant_id == tenant.id)
        ).all()
        assert len(again) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_overview
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetOverview:
    def _seed_rows(self, db: Session, tenant_id: uuid.UUID, period_days: int = 30) -> None:
        """Seed rows across current + prior period."""
        today = date.today()
        for i in range(period_days * 2):
            d = today - timedelta(days=i)
            _make_seo_row(
                db,
                tenant_id,
                query=f"sorgu-{i % 5}",
                page=f"https://example.com/page-{i % 3}",
                clicks=10 + i % 5,
                impressions=100 + i * 2,
                ctr=0.1,
                position=5.0 + i % 3,
                d=d,
            )

    def test_overview_returns_expected_shape(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_overview

        self._seed_rows(db_session, tenant.id, 30)
        result = get_overview(db_session, tenant.id, period_days=30)

        assert "current" in result
        assert "prior" in result
        assert "trends" in result
        assert "top_queries" in result
        assert "top_pages" in result
        assert isinstance(result["top_queries"], list)
        assert isinstance(result["top_pages"], list)
        assert result["period_days"] == 30

    def test_overview_current_has_nonzero_metrics(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_overview

        self._seed_rows(db_session, tenant.id, 30)
        result = get_overview(db_session, tenant.id, period_days=30)
        assert result["current"]["clicks"] > 0
        assert result["current"]["impressions"] > 0

    def test_overview_empty_returns_zeros(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_overview

        result = get_overview(db_session, tenant.id, period_days=30)
        assert result["current"]["clicks"] == 0
        assert result["current"]["impressions"] == 0
        assert result["top_queries"] == []

    def test_top_queries_sorted_by_clicks(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_overview

        today = date.today() - timedelta(days=1)
        _make_seo_row(db_session, tenant.id, query="a", page="https://x.com/a", clicks=100, impressions=1000, d=today)
        _make_seo_row(db_session, tenant.id, query="b", page="https://x.com/b", clicks=50, impressions=500, d=today)
        _make_seo_row(db_session, tenant.id, query="c", page="https://x.com/c", clicks=1, impressions=10, d=today)

        result = get_overview(db_session, tenant.id, period_days=30)
        queries = result["top_queries"]
        assert len(queries) >= 3
        assert queries[0]["query"] == "a"
        assert queries[1]["query"] == "b"

    def test_trends_clicks_delta(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_overview

        today = date.today()
        # Current period: high clicks
        for i in range(15):
            d = today - timedelta(days=i)
            _make_seo_row(db_session, tenant.id, query="q", page="https://x.com/", clicks=100, impressions=1000, d=d)
        # Prior period: low clicks
        for i in range(15, 30):
            d = today - timedelta(days=i)
            _make_seo_row(db_session, tenant.id, query="q", page="https://x.com/", clicks=50, impressions=500, d=d)

        result = get_overview(db_session, tenant.id, period_days=15)
        # Current 100 clicks vs prior 50 → +100% delta
        delta = result["trends"]["clicks_delta_pct"]
        assert delta is not None
        assert delta > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. get_opportunities — striking_distance
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpportunitiesStrikingDistance:
    def test_striking_distance_detected(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Position 12, 200 impressions — should be striking_distance
        _make_seo_row(db_session, tenant.id, query="ucuz ayakkabı", page="https://x.com/", clicks=5, impressions=200, ctr=0.025, position=12.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        types = [o["type"] for o in opps]
        assert "striking_distance" in types
        sd = next(o for o in opps if o["type"] == "striking_distance")
        assert sd["data"]["query"] == "ucuz ayakkabı"
        assert sd["severity"] == "warning"

    def test_striking_distance_requires_min_impressions(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Only 50 impressions — below threshold of 100
        _make_seo_row(db_session, tenant.id, query="low imp", page="https://x.com/", clicks=5, impressions=50, position=12.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        sd = [o for o in opps if o["type"] == "striking_distance"]
        # Should NOT include this query (only 50 impressions < 100 threshold)
        assert not any(o["data"]["query"] == "low imp" for o in sd)

    def test_striking_distance_excludes_top_positions(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Position 3 — not striking distance (< 8)
        _make_seo_row(db_session, tenant.id, query="top ranker", page="https://x.com/", clicks=50, impressions=500, position=3.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        sd = [o for o in opps if o["type"] == "striking_distance"]
        assert not any(o["data"]["query"] == "top ranker" for o in sd)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. get_opportunities — low_ctr
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpportunitiesLowCtr:
    def test_low_ctr_detected(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # 500 impressions, position 5, 3 clicks → CTR = 0.006 < 2%
        _make_seo_row(db_session, tenant.id, query="spor mağaza", page="https://x.com/", clicks=3, impressions=500, ctr=0.006, position=5.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        lc = [o for o in opps if o["type"] == "low_ctr"]
        assert len(lc) >= 1
        assert lc[0]["severity"] == "warning"
        assert lc[0]["data"]["query"] == "spor mağaza"

    def test_low_ctr_requires_high_impressions(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Only 100 impressions — below 200 threshold
        _make_seo_row(db_session, tenant.id, query="small vol", page="https://x.com/", clicks=1, impressions=100, ctr=0.01, position=5.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        lc = [o for o in opps if o["type"] == "low_ctr" and o["data"]["query"] == "small vol"]
        assert len(lc) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_opportunities — cannibalization
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpportunitiesCannibalization:
    def test_cannibalization_detected(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Same query, two different pages, both >= 50 impressions
        _make_seo_row(db_session, tenant.id, query="koşu bandı", page="https://x.com/page1", clicks=10, impressions=150, position=3.0, d=today)
        _make_seo_row(db_session, tenant.id, query="koşu bandı", page="https://x.com/page2", clicks=5, impressions=80, position=7.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        cann = [o for o in opps if o["type"] == "cannibalization"]
        assert len(cann) >= 1
        assert cann[0]["data"]["page_count"] == 2
        assert cann[0]["data"]["query"] == "koşu bandı"

    def test_cannibalization_not_fired_single_page(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today() - timedelta(days=1)
        # Same query, only one page
        _make_seo_row(db_session, tenant.id, query="single page query", page="https://x.com/only", clicks=15, impressions=200, position=3.0, d=today)

        opps = get_opportunities(db_session, tenant.id)
        cann = [o for o in opps if o["type"] == "cannibalization" and o["data"]["query"] == "single page query"]
        assert len(cann) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. get_opportunities — top_movers
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpportunitiesTopMovers:
    def test_position_improvement_detected(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today()
        # Recent half (last 15 days): position ~3 (improved)
        for i in range(15):
            d = today - timedelta(days=i + 1)
            _make_seo_row(db_session, tenant.id, query="gelişen sorgu", page="https://x.com/", clicks=20, impressions=200, position=3.0, d=d)
        # Prior half (days 16-30): position ~10 (worse)
        for i in range(15, 30):
            d = today - timedelta(days=i + 1)
            _make_seo_row(db_session, tenant.id, query="gelişen sorgu", page="https://x.com/", clicks=5, impressions=200, position=10.0, d=d)

        opps = get_opportunities(db_session, tenant.id, period_days=30)
        movers = [o for o in opps if o["type"] == "top_movers"]
        improved = [o for o in movers if o["data"].get("delta", 0) > 0]
        assert len(improved) >= 1
        assert improved[0]["severity"] == "info"

    def test_position_drop_detected(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import get_opportunities

        today = date.today()
        # Recent half: position ~12 (worse)
        for i in range(15):
            d = today - timedelta(days=i + 1)
            _make_seo_row(db_session, tenant.id, query="düşen sorgu", page="https://x.com/", clicks=10, impressions=200, position=12.0, d=d)
        # Prior half: position ~5 (better)
        for i in range(15, 30):
            d = today - timedelta(days=i + 1)
            _make_seo_row(db_session, tenant.id, query="düşen sorgu", page="https://x.com/", clicks=25, impressions=200, position=5.0, d=d)

        opps = get_opportunities(db_session, tenant.id, period_days=30)
        movers = [o for o in opps if o["type"] == "top_movers"]
        drops = [o for o in movers if o["data"].get("delta", 0) < 0 or o["severity"] == "warning"]
        assert len(drops) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. emit_seo_insights
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmitSeoInsights:
    def test_writes_insight_rows(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import emit_seo_insights

        today = date.today() - timedelta(days=1)
        # Create a striking_distance opportunity
        _make_seo_row(db_session, tenant.id, query="fırsatlık sorgu", page="https://x.com/", clicks=5, impressions=200, position=10.0, d=today)

        counts = emit_seo_insights(db_session, tenant.id)
        assert isinstance(counts, dict)
        assert "new_info" in counts
        assert "new_warning" in counts
        assert "skipped" in counts

        # Insight rows should have been created
        total_new = counts["new_info"] + counts["new_warning"] + counts["new_critical"]
        if total_new > 0:
            insight = db_session.scalar(
                select(Insight).where(
                    Insight.tenant_id == tenant.id,
                    Insight.channel == "organic_search",
                )
            )
            assert insight is not None
            assert insight.category.startswith("seo_")

    def test_deduplication_skips_existing(self, db_session: Session, tenant: Tenant) -> None:
        from ayaz.services.seo import emit_seo_insights

        today = date.today() - timedelta(days=1)
        _make_seo_row(db_session, tenant.id, query="dupe check", page="https://x.com/", clicks=5, impressions=200, position=10.0, d=today)

        counts1 = emit_seo_insights(db_session, tenant.id)
        counts2 = emit_seo_insights(db_session, tenant.id)
        # Second call should skip already-existing insights
        assert counts2["skipped"] >= counts1["new_info"] + counts1["new_warning"] + counts1["new_critical"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. PageSpeed audit service
# ═══════════════════════════════════════════════════════════════════════════════


class TestPagespeedAudit:
    def _mock_psi_response(self) -> dict:
        """Minimal valid PSI v5 response."""
        return {
            "lighthouseResult": {
                "categories": {
                    "performance": {"score": 0.72},
                    "seo": {"score": 0.95},
                    "accessibility": {"score": 0.88},
                    "best-practices": {"score": 0.83},
                },
                "audits": {
                    "largest-contentful-paint": {
                        "score": 0.6,
                        "numericValue": 3200.0,
                        "displayValue": "3.2 s",
                    },
                    "cumulative-layout-shift": {
                        "score": 0.9,
                        "numericValue": 0.05,
                        "displayValue": "0.05",
                    },
                    "first-contentful-paint": {
                        "score": 0.8,
                        "numericValue": 1500.0,
                        "displayValue": "1.5 s",
                    },
                    "server-response-time": {
                        "score": 0.95,
                        "numericValue": 200.0,
                        "displayValue": "200 ms",
                    },
                    "max-potential-fid": {
                        "score": 0.7,
                        "numericValue": 120.0,
                        "displayValue": "120 ms",
                    },
                    "render-blocking-resources": {
                        "score": 0.2,
                        "title": "Render-blocking resources",
                        "description": "Resources block first paint",
                        "scoreDisplayMode": "numeric",
                    },
                },
            }
        }

    def test_successful_audit_returns_scores(self) -> None:
        from ayaz.services.pagespeed import run_audit
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = self._mock_psi_response()

        with patch("httpx.get", return_value=mock_resp):
            result = run_audit("https://example.com/")

        assert result["status"] == "ok"
        assert result["scores"]["performance"] == 72.0
        assert result["scores"]["seo"] == 95.0
        assert "core_web_vitals" in result
        assert "lcp" in result["core_web_vitals"]
        assert result["core_web_vitals"]["lcp"]["value"] == 3200.0

    def test_offline_degrades_gracefully(self) -> None:
        from ayaz.services.pagespeed import run_audit
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("Connection refused")):
            result = run_audit("https://example.com/")

        assert result["status"] == "error"
        assert "message" in result
        assert result["scores"]["performance"] is None
        # Must never raise — status is "error" not an exception

    def test_timeout_degrades_gracefully(self) -> None:
        from ayaz.services.pagespeed import run_audit
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout")):
            result = run_audit("https://example.com/")

        assert result["status"] == "error"
        assert result["scores"]["performance"] is None

    def test_403_returns_kimlik_bekliyor(self) -> None:
        from ayaz.services.pagespeed import run_audit

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.is_success = False

        with patch("httpx.get", return_value=mock_resp):
            result = run_audit("https://example.com/")

        assert result["status"] == "kimlik_bekliyor"
        assert "message" in result

    def test_issues_extracted_and_sorted(self) -> None:
        from ayaz.services.pagespeed import run_audit

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = self._mock_psi_response()

        with patch("httpx.get", return_value=mock_resp):
            result = run_audit("https://example.com/")

        assert isinstance(result["issues"], list)
        # The render-blocking-resources audit has score 0.2 → should be in issues
        issue_ids = [i["id"] for i in result["issues"]]
        assert "render-blocking-resources" in issue_ids


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DataForSEO adapter
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataForSEOIntegration:
    def test_actions_returns_three_specs(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration

        adapter = DataForSEOIntegration()
        actions = adapter.actions()
        names = [a.name for a in actions]
        assert "dataforseo_backlinks_summary" in names
        assert "dataforseo_keyword_ideas" in names
        assert "dataforseo_rank_check" in names

    def test_metadata_category_is_seo(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration

        assert DataForSEOIntegration.metadata.category == "seo"
        assert DataForSEOIntegration.metadata.auth_type.value == "api_key"
        assert DataForSEOIntegration.metadata.min_plan == "growth"

    def test_not_connected_returns_kimlik_bekliyor(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration
        from ayaz.integrations.base import ActionContext

        adapter = DataForSEOIntegration()

        ctx = MagicMock(spec=ActionContext)
        ctx.vault_get.side_effect = KeyError("no vault secret")

        result = adapter.execute_action(
            "dataforseo_backlinks_summary",
            {"domain": "example.com"},
            ctx=ctx,
        )
        assert result["status"] == "kimlik_bekliyor"
        assert "message" in result

    def test_empty_credentials_returns_kimlik_bekliyor(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration
        from ayaz.integrations.base import ActionContext

        adapter = DataForSEOIntegration()
        ctx = MagicMock(spec=ActionContext)
        ctx.vault_get.return_value = {"api_login": "", "api_password": ""}

        result = adapter.execute_action(
            "dataforseo_keyword_ideas",
            {"seed": "spor"},
            ctx=ctx,
        )
        assert result["status"] == "kimlik_bekliyor"

    def test_backlinks_summary_mocked_http(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration
        from ayaz.integrations.base import ActionContext
        import httpx

        adapter = DataForSEOIntegration()
        ctx = MagicMock(spec=ActionContext)
        ctx.vault_get.return_value = {"api_login": "user", "api_password": "pass"}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "tasks": [{"result": [{"backlinks": 1234, "referring_domains": 56, "rank": 78}]}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = adapter.execute_action(
                "dataforseo_backlinks_summary",
                {"domain": "example.com"},
                ctx=ctx,
            )

        assert result["domain"] == "example.com"
        assert result["backlinks"] == 1234
        assert result["referring_domains"] == 56

    def test_keyword_ideas_mocked_http(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration
        from ayaz.integrations.base import ActionContext

        adapter = DataForSEOIntegration()
        ctx = MagicMock(spec=ActionContext)
        ctx.vault_get.return_value = {"api_login": "u", "api_password": "p"}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "tasks": [{"result": [{"items": [
                {"keyword": "spor ayakkabı", "keyword_info": {"search_volume": 5000, "competition": 0.6, "cpc": 1.5}},
            ]}]}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = adapter.execute_action(
                "dataforseo_keyword_ideas",
                {"seed": "spor"},
                ctx=ctx,
            )

        assert result["seed"] == "spor"
        assert len(result["keywords"]) >= 1
        assert result["keywords"][0]["keyword"] == "spor ayakkabı"
        assert result["keywords"][0]["search_volume"] == 5000

    def test_http_error_returns_hata_not_500(self) -> None:
        from ayaz.integrations.dataforseo import DataForSEOIntegration
        from ayaz.integrations.base import ActionContext
        import httpx

        adapter = DataForSEOIntegration()
        ctx = MagicMock(spec=ActionContext)
        ctx.vault_get.return_value = {"api_login": "u", "api_password": "p"}

        with patch("httpx.post", side_effect=httpx.ConnectError("Network error")):
            result = adapter.execute_action(
                "dataforseo_rank_check",
                {"keyword": "spor", "domain": "example.com"},
                ctx=ctx,
            )

        assert result["status"] == "hata"
        # Must not raise

    def test_registered_in_catalog(self) -> None:
        import ayaz.integrations  # noqa: F401 — triggers registration
        from ayaz.integrations.registry import IntegrationRegistry

        catalog = IntegrationRegistry.catalog()
        keys = [m.key for m in catalog]
        assert "dataforseo" in keys


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SEO router endpoints
# ═══════════════════════════════════════════════════════════════════════════════


def _make_test_app(db_session: Session, membership: Membership) -> TestClient:
    """Build a test FastAPI app with SEO router and overridden deps."""
    test_app = FastAPI()
    test_app.include_router(seo_router, prefix="/api/v1")

    def _override_db():
        yield db_session

    def _override_membership():
        return membership

    test_app.dependency_overrides[get_db] = _override_db
    test_app.dependency_overrides[get_current_membership] = _override_membership

    return TestClient(test_app)


class TestSeoRouter:
    def test_overview_empty_returns_200(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        client = _make_test_app(db_session, membership)
        resp = client.get("/api/v1/seo/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "top_queries" in data

    def test_overview_with_data(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        today = date.today() - timedelta(days=1)
        _make_seo_row(db_session, tenant.id, query="router test", page="https://x.com/", clicks=50, impressions=500, d=today)

        client = _make_test_app(db_session, membership)
        resp = client.get("/api/v1/seo/overview?period_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"]["clicks"] > 0

    def test_opportunities_returns_200(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        client = _make_test_app(db_session, membership)
        resp = client.get("/api/v1/seo/opportunities")
        assert resp.status_code == 200
        data = resp.json()
        assert "opportunities" in data
        assert "count" in data

    def test_audit_mocked_psi(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "lighthouseResult": {
                "categories": {"performance": {"score": 0.80}, "seo": {"score": 0.90}, "accessibility": {"score": 0.85}, "best-practices": {"score": 0.75}},
                "audits": {
                    "largest-contentful-paint": {"score": 0.7, "numericValue": 2500.0, "displayValue": "2.5 s"},
                    "cumulative-layout-shift": {"score": 0.95, "numericValue": 0.03, "displayValue": "0.03"},
                    "first-contentful-paint": {"score": 0.85, "numericValue": 1200.0, "displayValue": "1.2 s"},
                    "server-response-time": {"score": 0.99, "numericValue": 100.0, "displayValue": "100 ms"},
                    "max-potential-fid": {"score": 0.8, "numericValue": 80.0, "displayValue": "80 ms"},
                },
            }
        }

        client = _make_test_app(db_session, membership)
        with patch("httpx.get", return_value=mock_resp):
            resp = client.post("/api/v1/seo/audit", json={"url": "https://example.com/"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["scores"]["performance"] == 80.0

    def test_audit_offline_returns_degraded_not_500(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        import httpx

        client = _make_test_app(db_session, membership)
        with patch("httpx.get", side_effect=httpx.ConnectError("offline")):
            resp = client.post("/api/v1/seo/audit", json={"url": "https://example.com/"})
        # Must be 200 with status=error, NOT 500
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_backlinks_not_connected_returns_connect_required(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        client = _make_test_app(db_session, membership)
        resp = client.get("/api/v1/seo/backlinks?domain=example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connect_required"
        assert data["integration_key"] == "dataforseo"

    def test_keywords_not_connected_returns_connect_required(self, db_session: Session, user: User, tenant: Tenant, membership: Membership) -> None:
        client = _make_test_app(db_session, membership)
        resp = client.get("/api/v1/seo/keywords?seed=spor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connect_required"

    def test_tenant_isolation_overview(self, db_session: Session, tenant: Tenant) -> None:
        """Tenant A's data is not visible to Tenant B."""
        tenant_b = Tenant(id=uuid.uuid4(), name="Tenant B", base_currency="TRY")
        db_session.add(tenant_b)
        db_session.flush()
        user_b = User(id=uuid.uuid4(), email="b@test.com", hashed_password=hash_password("x"))
        db_session.add(user_b)
        db_session.flush()
        mem_b = Membership(id=uuid.uuid4(), user_id=user_b.id, tenant_id=tenant_b.id, role=MembershipRole.owner)
        db_session.add(mem_b)
        db_session.flush()

        # Add data for tenant A only
        today = date.today() - timedelta(days=1)
        _make_seo_row(db_session, tenant.id, query="tenant a query", page="https://a.com/", clicks=999, impressions=9999, d=today)

        # Client for tenant B
        client_b = _make_test_app(db_session, mem_b)
        resp = client_b.get("/api/v1/seo/overview")
        assert resp.status_code == 200
        data = resp.json()
        # Tenant B should see 0 clicks (tenant A's data is invisible)
        assert data["current"]["clicks"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Seed smoke test
# ═══════════════════════════════════════════════════════════════════════════════


class TestSeoSeed:
    def test_seed_seo_rows(self, db_session: Session, tenant: Tenant) -> None:
        """_seed_seo_metrics writes rows into seo_search_metrics."""
        from scripts.seed_demo import _seed_seo_metrics, _SEO_QUERIES

        count = _seed_seo_metrics(db_session, tenant)
        assert count > 0
        # 18 queries × 45 days = 810 rows
        expected = len(_SEO_QUERIES) * 45
        assert count == expected

    def test_seed_idempotent(self, db_session: Session, tenant: Tenant) -> None:
        """Running _seed_seo_metrics twice returns same count (no duplicates)."""
        from scripts.seed_demo import _seed_seo_metrics

        count1 = _seed_seo_metrics(db_session, tenant)
        count2 = _seed_seo_metrics(db_session, tenant)

        from sqlalchemy import func as _func, select as _select
        total_in_db = db_session.scalar(
            _select(_func.count()).select_from(SeoSearchMetric)
            .where(SeoSearchMetric.tenant_id == tenant.id)
        )
        assert total_in_db == count1
        assert count2 == count1
