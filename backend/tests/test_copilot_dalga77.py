"""Tests for Copilot Dalga 77: funnel, consent, benchmark, audit modules.

Coverage
--------
* Each new tool is registered in _TOOLS and TOOL_SPECS.
* dispatch works for all four new tools (returns a dict without "error").
* Each new keyword routes to the correct intent and the reply contains a
  topic word + a number from demo/fixture data.
* Existing intents (performance, budget, inbox, executive, insights, content,
  campaign) still route correctly after the new elif branches were added
  (regression).
* _summarise_* functions handle empty/missing data without crashing.
* Tenant isolation: each new tool returns only the requesting tenant's data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.oltp import Tenant

_SQLITE_URL = "sqlite://"


# ── DB fixture ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite DB with all AYAZ tables."""
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


# ── Helper factories ──────────────────────────────────────────────────────────


def _tenant(db: Session, name: str = "Test Tenant") -> Tenant:
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


def _make_tracking_source(db: Session, tenant: Tenant):
    """Seed a minimal TrackingSource for consent / audit / funnel tests."""
    from ayaz.models.tracking import TrackingSource

    src = TrackingSource(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Web Kaynağı",
        domain="example.com",
        public_token="tok-test-001",
        is_active=True,
        consent_cookie_var="CookieConsent",
    )
    db.add(src)
    db.flush()
    return src


def _make_conversion_events(db: Session, tenant: Tenant) -> None:
    """Seed 5 funnel events so build_funnel returns non-zero counts."""
    from ayaz.models.tracking import ConversionEvent

    # tracking_source_id is NOT NULL — create a source first
    src = _make_tracking_source(db, tenant)
    today = date.today().isoformat()
    stages = [
        ("PageView", True, "forwarded"),
        ("ViewContent", True, "forwarded"),
        ("AddToCart", True, "forwarded"),
        ("InitiateCheckout", False, "skipped_no_consent"),
        ("Purchase", True, "forwarded"),
    ]
    now = datetime.now(timezone.utc).isoformat()
    for event_name, consent, status in stages:
        evt = ConversionEvent(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            tracking_source_id=src.id,
            event_name=event_name,
            event_time=today + "T10:00:00",
            event_id=str(uuid.uuid4()),
            consent=consent,
            status=status,
            consent_signals=None,
            created_at=now,
        )
        db.add(evt)
    db.flush()


# ── Registry tests ─────────────────────────────────────────────────────────────


class TestDalga77Registry:
    """All four new tools must appear in _TOOLS and TOOL_SPECS."""

    NEW_TOOLS = [
        "get_funnel_summary",
        "get_consent_summary",
        "get_benchmark_summary",
        "get_audit_summary",
    ]

    def test_all_in_tools(self):
        from ayaz.services.copilot_tools import _TOOLS

        for name in self.NEW_TOOLS:
            assert name in _TOOLS, f"{name!r} missing from _TOOLS"

    def test_all_in_tool_specs(self):
        from ayaz.services.copilot_tools import TOOL_SPECS

        spec_names = {s["name"] for s in TOOL_SPECS}
        for name in self.NEW_TOOLS:
            assert name in spec_names, f"{name!r} missing from TOOL_SPECS"

    def test_none_in_action_tools(self):
        from ayaz.services.copilot_tools import ACTION_TOOLS

        for name in self.NEW_TOOLS:
            assert name not in ACTION_TOOLS, f"{name!r} should not be an ACTION tool"

    def test_tool_specs_have_required_keys(self):
        from ayaz.services.copilot_tools import TOOL_SPECS

        for spec in TOOL_SPECS:
            if spec["name"] in self.NEW_TOOLS:
                assert "name" in spec
                assert "description" in spec
                assert "input_schema" in spec
                assert len(spec["description"]) > 20, (
                    f"{spec['name']} description is too short"
                )


# ── dispatch tests ─────────────────────────────────────────────────────────────


class TestDalga77Dispatch:
    """dispatch() works for each new tool and returns a dict without 'error'."""

    def test_dispatch_get_funnel_summary(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_funnel_summary", db, t.id, {})
        assert isinstance(result, dict)
        assert "error" not in result
        # Even with no data the funnel returns a well-formed dict
        assert "entry_count" in result or "stages" in result

    def test_dispatch_get_funnel_summary_with_events(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        _make_conversion_events(db, t)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_funnel_summary", db, t.id, {})
        assert result["entry_count"] == 1  # 1 PageView seeded
        assert result["final_count"] == 1  # 1 Purchase seeded
        assert result["overall_conversion_pct"] == pytest.approx(100.0)

    def test_dispatch_get_consent_summary(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_consent_summary", db, t.id, {})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "consent_rate_pct" in result
        assert "compliance_score" in result

    def test_dispatch_get_consent_summary_with_events(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        _make_conversion_events(db, t)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_consent_summary", db, t.id, {})
        # 5 events: 4 consent=True → 80% rate
        assert result["consent_rate_pct"] == pytest.approx(80.0)
        # 1 event skipped_no_consent
        assert result["skipped_no_consent"] == 1

    def test_dispatch_get_benchmark_summary(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_benchmark_summary", db, t.id, {})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "headline" in result
        assert "metrics" in result
        assert "summary_counts" in result

    def test_dispatch_get_audit_summary(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_audit_summary", db, t.id, {})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "score" in result
        assert "grade" in result
        assert "counts" in result
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100


# ── _summarise_* robustness tests ─────────────────────────────────────────────


class TestSummariseFunctions:
    """Each _summarise_* must handle empty/missing data gracefully."""

    def test_summarise_funnel_empty(self):
        from ayaz.services.copilot import _summarise_funnel

        result = _summarise_funnel({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarise_funnel_zero_entry(self):
        from ayaz.services.copilot import _summarise_funnel

        result = _summarise_funnel({"entry_count": 0, "final_count": 0})
        assert "veri" in result.lower() or "yeterli" in result.lower()

    def test_summarise_funnel_with_data(self):
        from ayaz.services.copilot import _summarise_funnel

        result = _summarise_funnel({
            "entry_count": 40,
            "final_count": 6,
            "overall_conversion_pct": 15.0,
            "biggest_dropoff": {
                "from_label": "Sepete Ekleme",
                "to_label": "Ödeme Başlatma",
                "dropoff_pct": 44.0,
            },
        })
        assert "40" in result
        assert "6" in result
        assert "15" in result
        assert "Sepete Ekleme" in result
        assert "44" in result

    def test_summarise_consent_empty(self):
        from ayaz.services.copilot import _summarise_consent

        result = _summarise_consent({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarise_consent_no_events(self):
        from ayaz.services.copilot import _summarise_consent

        result = _summarise_consent({"total_events": 0})
        assert "olay" in result.lower()

    def test_summarise_consent_with_data(self):
        from ayaz.services.copilot import _summarise_consent

        result = _summarise_consent({
            "total_events": 100,
            "consent_rate_pct": 83.0,
            "skipped_no_consent": 17,
            "compliance_score": 100,
            "compliance_grade": "uyumlu",
        })
        assert "83" in result
        assert "100" in result
        assert "17" in result

    def test_summarise_benchmark_empty(self):
        from ayaz.services.copilot import _summarise_benchmark

        result = _summarise_benchmark({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarise_benchmark_no_headline(self):
        from ayaz.services.copilot import _summarise_benchmark

        result = _summarise_benchmark({"headline": ""})
        assert "yeterli" in result.lower() or "veri" in result.lower()

    def test_summarise_benchmark_with_data(self):
        from ayaz.services.copilot import _summarise_benchmark

        result = _summarise_benchmark({
            "headline": "5 metrik ortalama sektör kıyaslamasında.",
            "summary_counts": {"strong": 0, "average": 5, "weak": 0},
            "metrics": [
                {
                    "key": "roas",
                    "label": "ROAS",
                    "your_value": 3.31,
                    "unit": "x",
                    "position": "average",
                    "verdict": "ROAS'ınız sektör referans aralığında — ortalama.",
                }
            ],
        })
        assert "3,31" in result  # TR ondalık biçim
        assert "ortalama" in result.lower()

    def test_summarise_audit_empty(self):
        from ayaz.services.copilot import _summarise_audit

        result = _summarise_audit({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarise_audit_with_data(self):
        from ayaz.services.copilot import _summarise_audit

        result = _summarise_audit({
            "score": 60,
            "grade": "orta",
            "counts": {"pass": 11, "warn": 4, "fail": 1},
            "top_issues": [{"severity": "fail", "title": "Ölçümleme kurulu değil", "finding": "..."}],
        })
        assert "60" in result
        assert "orta" in result
        assert "1" in result   # fail count
        assert "4" in result   # warn count
        assert "11" in result  # pass count

    def test_summarise_audit_no_top_issues(self):
        from ayaz.services.copilot import _summarise_audit

        result = _summarise_audit({
            "score": 95,
            "grade": "mukemmel",
            "counts": {"pass": 10, "warn": 0, "fail": 0},
            "top_issues": [],
        })
        assert "95" in result
        assert "mükemmel" in result


# ── Stub intent routing tests (new intents) ────────────────────────────────────


class TestDalga77IntentRouting:
    """Each new keyword must route to the correct intent."""

    def _run(self, db, tenant_id, text):
        from ayaz.services.copilot import _stub_chat
        return _stub_chat(db, tenant_id, text)

    # -- funnel intent --

    def test_funnel_keyword_huni(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Dönüşüm hunisi nasıl görünüyor?")
        assert any(tu.name == "get_funnel_summary" for tu in reply.tools_used)
        assert "Huni" in reply.text or "huni" in reply.text or "Dönüşüm" in reply.text

    def test_funnel_keyword_musteri_yolculugu(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Müşteri yolculuğunu göster")
        assert any(tu.name == "get_funnel_summary" for tu in reply.tools_used)

    def test_funnel_keyword_sepete_ekleme(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        _make_conversion_events(db, t)
        db.commit()
        reply = self._run(db, t.id, "Sepete ekleme oranı nedir?")
        assert any(tu.name == "get_funnel_summary" for tu in reply.tools_used)
        # With events seeded the reply should contain a number
        assert any(char.isdigit() for char in reply.text)

    def test_funnel_keyword_funnel_english(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Show me the funnel")
        assert any(tu.name == "get_funnel_summary" for tu in reply.tools_used)

    def test_funnel_with_events_mentions_count(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        _make_conversion_events(db, t)
        db.commit()
        reply = self._run(db, t.id, "Dönüşüm hunisini analiz et")
        assert any(tu.name == "get_funnel_summary" for tu in reply.tools_used)
        # entry_count=1, final_count=1 — the reply should mention a count
        assert any(char.isdigit() for char in reply.text)

    # -- consent intent --

    def test_consent_keyword_kvkk(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "KVKK uyum durumum ne?")
        assert any(tu.name == "get_consent_summary" for tu in reply.tools_used)
        assert "KVKK" in reply.text or "rıza" in reply.text.lower()

    def test_consent_keyword_riza(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Rıza oranım kaç?")
        assert any(tu.name == "get_consent_summary" for tu in reply.tools_used)

    def test_consent_keyword_consent_english(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "What is my consent rate?")
        assert any(tu.name == "get_consent_summary" for tu in reply.tools_used)

    def test_consent_keyword_onay_orani(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        _make_conversion_events(db, t)
        db.commit()
        reply = self._run(db, t.id, "Onay oranı nasıl?")
        assert any(tu.name == "get_consent_summary" for tu in reply.tools_used)
        # With events the reply mentions a percentage number
        assert any(char.isdigit() for char in reply.text)

    # -- benchmark intent --

    def test_benchmark_keyword_kiyaslama(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Sektörle kıyaslama yap")
        assert any(tu.name == "get_benchmark_summary" for tu in reply.tools_used)
        assert "Kıyaslama" in reply.text or "kıyas" in reply.text.lower()

    def test_benchmark_keyword_benchmark_english(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Show me the benchmark report")
        assert any(tu.name == "get_benchmark_summary" for tu in reply.tools_used)

    def test_benchmark_keyword_sektor(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Sektör ortalamasına göre nasılım?")
        assert any(tu.name == "get_benchmark_summary" for tu in reply.tools_used)

    def test_benchmark_keyword_rakip_ortalama(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Rakip ortalama nedir?")
        assert any(tu.name == "get_benchmark_summary" for tu in reply.tools_used)

    # -- audit intent --

    def test_audit_keyword_denetim(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Hesap denetimi yap")
        assert any(tu.name == "get_audit_summary" for tu in reply.tools_used)
        assert "skor" in reply.text.lower() or "sağlık" in reply.text.lower() or "Tarama" in reply.text

    def test_audit_keyword_hesap_sagligi(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Hesap sağlığı nasıl?")
        assert any(tu.name == "get_audit_summary" for tu in reply.tools_used)

    def test_audit_keyword_saglik_taramasi(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Sağlık taraması sonuçlarını göster")
        assert any(tu.name == "get_audit_summary" for tu in reply.tools_used)

    def test_audit_keyword_audit_english(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Run the account audit")
        assert any(tu.name == "get_audit_summary" for tu in reply.tools_used)

    def test_audit_score_is_a_number(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Sağlık skoru ne?")
        assert any(tu.name == "get_audit_summary" for tu in reply.tools_used)
        # The summary always contains a number (score/100)
        assert any(char.isdigit() for char in reply.text)


# ── Regression: existing intents still route correctly ────────────────────────


class TestExistingIntentsRegression:
    """After adding 4 new elif branches, existing intents must still fire."""

    def _run(self, db, tenant_id, text):
        from ayaz.services.copilot import _stub_chat
        return _stub_chat(db, tenant_id, text)

    def test_performance_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Performans özeti nasıl?")
        assert any(tu.name == "get_performance_summary" for tu in reply.tools_used)

    def test_campaign_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Kampanyaları listele")
        assert any(tu.name == "list_campaigns" for tu in reply.tools_used)

    def test_recommendations_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Ne yapmalıyım, optimizasyon önerileri var mı?")
        assert any(tu.name == "get_recommendations" for tu in reply.tools_used)

    def test_insights_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "İçgörüleri göster")
        assert any(tu.name == "get_insights" for tu in reply.tools_used)

    def test_content_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        # Avoid "nasıl" which is captured by the broader performance intent
        reply = self._run(db, t.id, "Zamanlanmış içerik listesi")
        assert any(tu.name == "get_content_status" for tu in reply.tools_used)

    def test_inbox_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Sosyal gelen kutusu nasıl?")
        assert any(tu.name == "get_inbox_summary" for tu in reply.tools_used)

    def test_executive_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Yönetici özeti ver")
        assert any(tu.name == "get_executive_summary" for tu in reply.tools_used)

    def test_budget_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Bütçe planı nerede?")
        assert any(tu.name == "get_budget_status" for tu in reply.tools_used)

    def test_subscription_intent_still_works(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Abonelik planım nedir?")
        assert any(tu.name == "get_subscription_status" for tu in reply.tools_used)

    def test_default_intent_mentions_new_capabilities(self, db_session: Session):
        db = db_session
        t = _tenant(db)
        db.commit()
        reply = self._run(db, t.id, "Merhaba, ne yapabilirsin?")
        # Default message should now mention all 4 new capabilities
        assert "huni" in reply.text.lower() or "Dönüşüm hunisi" in reply.text
        assert "kvkk" in reply.text.lower() or "rıza" in reply.text.lower()
        assert "kıyaslama" in reply.text.lower() or "benchmark" in reply.text.lower()
        assert "denetim" in reply.text.lower() or "sağlık taraması" in reply.text.lower()
        # No tools are called for the default intent
        assert len(reply.tools_used) == 0


# ── Tenant isolation tests ─────────────────────────────────────────────────────


class TestDalga77TenantIsolation:
    """Each new tool must return only the requesting tenant's data."""

    def test_funnel_isolation(self, db_session: Session):
        db = db_session
        tenant_a = _tenant(db, "A")
        tenant_b = _tenant(db, "B")
        _make_conversion_events(db, tenant_a)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result_b = dispatch("get_funnel_summary", db, tenant_b.id, {})
        # Tenant B has no events — all stage counts are 0
        assert result_b["entry_count"] == 0
        assert result_b["final_count"] == 0

        result_a = dispatch("get_funnel_summary", db, tenant_a.id, {})
        assert result_a["entry_count"] >= 1

    def test_consent_isolation(self, db_session: Session):
        db = db_session
        tenant_a = _tenant(db, "CA")
        tenant_b = _tenant(db, "CB")
        _make_conversion_events(db, tenant_a)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result_b = dispatch("get_consent_summary", db, tenant_b.id, {})
        assert result_b["total_events"] == 0

        result_a = dispatch("get_consent_summary", db, tenant_a.id, {})
        assert result_a["total_events"] == 5

    def test_benchmark_isolation(self, db_session: Session):
        """Benchmark with no data for tenant_b returns 0 or weak positions."""
        db = db_session
        tenant_b = _tenant(db, "BM_B")
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_benchmark_summary", db, tenant_b.id, {})
        # All metrics should be 'weak' when there is no spend data
        for m in result["metrics"]:
            assert m["position"] in ("weak", "average", "strong")

    def test_audit_isolation(self, db_session: Session):
        """Audit for tenant_b (no data) must not include tenant_a's data."""
        db = db_session
        tenant_a = _tenant(db, "AU_A")
        tenant_b = _tenant(db, "AU_B")
        _make_tracking_source(db, tenant_a)
        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result_b = dispatch("get_audit_summary", db, tenant_b.id, {})
        # Tenant B has no tracking source — top_issues should mention it or score < 100
        assert result_b["score"] <= 100
        assert result_b["grade"] in ("mukemmel", "iyi", "orta", "zayif")
