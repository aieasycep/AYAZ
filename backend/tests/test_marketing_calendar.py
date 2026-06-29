"""Pazarlama Fırsat Takvimi (Marketing Opportunity Calendar) testleri — Dalga 80.

Kapsam
------
1. Saf birim testler (DB yok)
   - TR_KEY_DATES en az 18 giriş içerir
   - Her giriş zorunlu alanları taşır
   - _find_next_occurrence: fixed tarihler, horizon dışı, wrap

2. build_opportunity_calendar — servis düzeyinde testler (DB ile)
   - Fırsatlar gelecek tarihlere çözümlenir (as_of >= as_of)
   - Artan sıralama
   - Haziran'dan bakıldığında Sevgililer Günü → sonraki yıl Şubat'a wrap eder
   - days_until, as_of'a göre doğru hesaplanır
   - status: days_until <= lead_time → "urgent"
   - readiness.budget_planned: o ay için BudgetPlan varsa True
   - readiness.content_scheduled: tarihe ±7 gün içindeki ContentPost sayısı
   - summary sayımları: total/urgent/this_month/high_weight doğru
   - horizon_months parametresi daha uzun ufuk alır
   - Boş DB → çökmez, boş opportunities veya sıfır readiness
   - as_of ile dönüş "as_of" alanı eşleşir

3. HTTP endpoint testleri
   - GET /api/v1/marketing-calendar/opportunities → 200, doğru şekil
   - horizon_months varsayılan 6
   - horizon_months=1 → daha az fırsat
   - horizon_months < 1 → 422 (FastAPI clamp: ge=1)
   - horizon_months > 12 → 422 (FastAPI clamp: le=12)
   - Kimlik doğrulamasız → 401 veya 403
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Tüm modelleri kaydet (Base.metadata.create_all için) ──────────────────────
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

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
)
from ayaz.models.budget import BudgetPlan
from ayaz.models.content import ContentPost
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import marketing_calendar as marketing_calendar_module
from ayaz.services.auth import hash_password
from ayaz.services.marketing_calendar import (
    TR_KEY_DATES,
    _find_next_occurrence,
    build_opportunity_calendar,
)

# ── Minimal test uygulaması ───────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Marketing Calendar Test App")
_test_app.include_router(marketing_calendar_module.router, prefix="/api/v1")


# ── DB fixture ────────────────────────────────────────────────────────────────


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


# ── İstemci fixture'ları ──────────────────────────────────────────────────────


@pytest.fixture()
def tenant_and_membership(db_session: Session):
    """Ortak kiracı + üyelik; birden fazla fixture'da paylaşılır."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Takvim Test Kiracısı",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="takvim_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Takvim Test Kullanıcısı",
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
    return tenant, membership


@pytest.fixture()
def client(db_session: Session, tenant_and_membership):
    """DB + üyelik bağımlılıkları override edilmiş TestClient."""
    _tenant, membership = tenant_and_membership

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
    """Üyelik override'ı OLMAYAN TestClient — 401 testleri için."""
    def override_db():
        try:
            yield db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_db

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Yardımcı fabrika fonksiyonları ───────────────────────────────────────────


def _make_budget_plan(db: Session, tenant_id: uuid.UUID, period_month: str) -> BudgetPlan:
    """Belirtilen ay için bir BudgetPlan satırı oluştur ve commit et."""
    plan = BudgetPlan(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"{period_month} Planı",
        period_month=period_month,
        total_budget=50000,
        currency="TRY",
        objective="balanced",
        status="draft",
    )
    db.add(plan)
    db.commit()
    return plan


def _make_content_post(
    db: Session,
    tenant_id: uuid.UUID,
    scheduled_at: str,
) -> ContentPost:
    """Belirtilen scheduled_at ile bir ContentPost oluştur ve commit et."""
    post = ContentPost(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        title="Test İçerik",
        body="Test gövde metni",
        channels=["instagram"],
        scheduled_at=scheduled_at,
        status="scheduled",
    )
    db.add(post)
    db.commit()
    return post


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Saf birim testler (DB yok)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTRKeyDates:
    """TR_KEY_DATES sabit listesinin bütünlük testleri."""

    def test_at_least_18_entries(self) -> None:
        assert len(TR_KEY_DATES) >= 18

    def test_required_fields_present(self) -> None:
        required = {
            "key", "name", "category", "recurrence",
            "lead_time_days", "marketing_tip", "commerce_weight", "is_approximate",
        }
        for entry in TR_KEY_DATES:
            missing = required - set(entry.keys())
            assert not missing, f"{entry['key']} şu alanları eksik: {missing}"

    def test_fixed_entries_have_month_and_day(self) -> None:
        for entry in TR_KEY_DATES:
            if entry["recurrence"] == "fixed":
                assert "month" in entry, f"{entry['key']} month alanı eksik"
                assert "day" in entry, f"{entry['key']} day alanı eksik"
                assert 1 <= entry["month"] <= 12
                assert 1 <= entry["day"] <= 31

    def test_variable_entries_have_dates_by_year(self) -> None:
        for entry in TR_KEY_DATES:
            if entry["recurrence"] == "variable":
                assert "dates_by_year" in entry, f"{entry['key']} dates_by_year alanı eksik"
                assert len(entry["dates_by_year"]) >= 1

    def test_commerce_weight_valid(self) -> None:
        valid = {"yuksek", "orta", "dusuk"}
        for entry in TR_KEY_DATES:
            assert entry["commerce_weight"] in valid, (
                f"{entry['key']} geçersiz commerce_weight: {entry['commerce_weight']!r}"
            )

    def test_category_valid(self) -> None:
        valid = {"ticari", "resmi", "sezonsal", "dini"}
        for entry in TR_KEY_DATES:
            assert entry["category"] in valid, (
                f"{entry['key']} geçersiz category: {entry['category']!r}"
            )

    def test_known_keys_present(self) -> None:
        keys = {e["key"] for e in TR_KEY_DATES}
        expected_keys = {
            "yilbasi", "sevgililer_gunu", "dunya_kadinlar_gunu",
            "ramazan_baslangici", "ramazan_bayrami", "23_nisan", "1_mayis",
            "anneler_gunu", "19_mayis", "babalar_gunu", "kurban_bayrami",
            "30_agustos", "okula_donus", "cumhuriyet_bayrami", "singles_day",
            "efsane_cuma", "cyber_monday", "yilbasi_alisverisi",
        }
        missing = expected_keys - keys
        assert not missing, f"Eksik key'ler: {missing}"

    def test_yilbasi_is_jan_1(self) -> None:
        entry = next(e for e in TR_KEY_DATES if e["key"] == "yilbasi")
        assert entry["recurrence"] == "fixed"
        assert entry["month"] == 1
        assert entry["day"] == 1
        assert entry["commerce_weight"] == "yuksek"

    def test_sevgililer_gunu_is_feb_14(self) -> None:
        entry = next(e for e in TR_KEY_DATES if e["key"] == "sevgililer_gunu")
        assert entry["month"] == 2
        assert entry["day"] == 14
        assert entry["commerce_weight"] == "yuksek"

    def test_dini_gunler_are_approximate(self) -> None:
        """Ramazan ve Bayram girişleri is_approximate=True olmalı."""
        dini_variable = [
            e for e in TR_KEY_DATES
            if e["category"] == "dini" and e["recurrence"] == "variable"
        ]
        for entry in dini_variable:
            assert entry["is_approximate"] is True, (
                f"{entry['key']} is_approximate=True olmalı"
            )

    def test_efsane_cuma_2026_is_nov_27(self) -> None:
        entry = next(e for e in TR_KEY_DATES if e["key"] == "efsane_cuma")
        assert entry["dates_by_year"][2026] == date(2026, 11, 27)

    def test_anneler_gunu_2026_is_may_10(self) -> None:
        entry = next(e for e in TR_KEY_DATES if e["key"] == "anneler_gunu")
        assert entry["dates_by_year"][2026] == date(2026, 5, 10)

    def test_babalar_gunu_2026_is_june_21(self) -> None:
        entry = next(e for e in TR_KEY_DATES if e["key"] == "babalar_gunu")
        assert entry["dates_by_year"][2026] == date(2026, 6, 21)


class TestFindNextOccurrence:
    """_find_next_occurrence fonksiyonunun testleri."""

    _yilbasi = next(e for e in TR_KEY_DATES if e["key"] == "yilbasi")
    _sevgililer = next(e for e in TR_KEY_DATES if e["key"] == "sevgililer_gunu")
    _efsane = next(e for e in TR_KEY_DATES if e["key"] == "efsane_cuma")

    def test_fixed_same_year(self) -> None:
        # Ekim'den bakınca Yılbaşı 1 Ocak 2027'ye wrap eder
        as_of = date(2026, 10, 1)
        horizon_end = date(2027, 4, 1)
        result = _find_next_occurrence(self._yilbasi, as_of, horizon_end)
        assert result == date(2027, 1, 1)

    def test_fixed_horizon_excludes_past(self) -> None:
        # Şubat'tan bakınca Yılbaşı horizon içinde değilse None
        as_of = date(2026, 2, 1)
        horizon_end = date(2026, 3, 1)
        result = _find_next_occurrence(self._yilbasi, as_of, horizon_end)
        assert result is None

    def test_fixed_as_of_date_itself_included(self) -> None:
        # as_of tam Yılbaşı ise dahil edilmeli
        as_of = date(2027, 1, 1)
        horizon_end = date(2027, 6, 1)
        result = _find_next_occurrence(self._yilbasi, as_of, horizon_end)
        assert result == date(2027, 1, 1)

    def test_variable_year_lookup(self) -> None:
        as_of = date(2026, 10, 1)
        horizon_end = date(2027, 4, 1)
        result = _find_next_occurrence(self._efsane, as_of, horizon_end)
        assert result == date(2026, 11, 27)

    def test_none_when_outside_all_years(self) -> None:
        # Sevgililer Günü ufuk bitişi Ocak olursa Şubat yakalanamaz
        as_of = date(2026, 7, 1)
        horizon_end = date(2026, 12, 31)
        result = _find_next_occurrence(self._sevgililer, as_of, horizon_end)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. build_opportunity_calendar — servis düzeyinde testler (DB ile)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildOpportunityCalendar:
    """build_opportunity_calendar fonksiyonunun DB tabanlı testleri."""

    _as_of = date(2026, 6, 29)  # Sabit referans tarihi — deterministik testler

    def test_all_opportunities_are_future(self, db_session: Session, tenant_and_membership) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            opp_date = date.fromisoformat(opp["date"])
            assert opp_date >= self._as_of, (
                f"{opp['key']} tarih {opp['date']} as_of'dan önce olamaz"
            )

    def test_opportunities_sorted_ascending(self, db_session: Session, tenant_and_membership) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        dates = [opp["date"] for opp in result["opportunities"]]
        assert dates == sorted(dates), "Fırsatlar artan tarih sırasında olmalı"

    def test_sevgililer_gunu_wraps_to_next_year_from_june(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Haziran'dan bakıldığında Sevgililer Günü sonraki yılın Şubat'ına çözümlenmeli."""
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=8
        )
        # 6 aylık ufukta Sevgililer Günü (Şubat) dahil olmalı → 2027-02-14
        sev = next(
            (o for o in result["opportunities"] if o["key"] == "sevgililer_gunu"), None
        )
        assert sev is not None, "Sevgililer Günü 8 aylık ufukta bulunmalı"
        assert sev["date"] == "2027-02-14"

    def test_yilbasi_wraps_to_next_jan_from_june(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Haziran'dan bakıldığında Yılbaşı 2027-01-01'e çözümlenmeli."""
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=7
        )
        yb = next(
            (o for o in result["opportunities"] if o["key"] == "yilbasi"), None
        )
        assert yb is not None, "Yılbaşı 7 aylık ufukta bulunmalı"
        assert yb["date"] == "2027-01-01"

    def test_days_until_computed_correctly(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            opp_date = date.fromisoformat(opp["date"])
            expected_days = (opp_date - self._as_of).days
            assert opp["days_until"] == expected_days, (
                f"{opp['key']}: days_until {opp['days_until']} != {expected_days}"
            )

    def test_status_urgent_when_days_until_lte_lead_time(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            if opp["days_until"] <= opp["lead_time_days"]:
                assert opp["status"] == "urgent", (
                    f"{opp['key']}: days_until={opp['days_until']} <= "
                    f"lead_time={opp['lead_time_days']} iken status 'urgent' olmalı"
                )
            else:
                assert opp["status"] == "upcoming", (
                    f"{opp['key']}: days_until={opp['days_until']} > "
                    f"lead_time={opp['lead_time_days']} iken status 'upcoming' olmalı"
                )

    def test_budget_planned_true_when_plan_exists(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Efsane Cuma ayı (Kasım 2026) için BudgetPlan ekleyince budget_planned True olmalı."""
        tenant, _mem = tenant_and_membership
        _make_budget_plan(db_session, tenant.id, "2026-11")

        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        efsane = next(
            (o for o in result["opportunities"] if o["key"] == "efsane_cuma"), None
        )
        assert efsane is not None, "Efsane Cuma 6 aylık ufukta bulunmalı"
        assert efsane["readiness"]["budget_planned"] is True

    def test_budget_planned_false_when_no_plan(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """BudgetPlan olmadan budget_planned False olmalı."""
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            assert opp["readiness"]["budget_planned"] is False, (
                f"{opp['key']}: plan olmadan budget_planned False olmalı"
            )

    def test_budget_planned_only_for_matching_month(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Sadece eşleşen ay için budget_planned True, diğerleri False."""
        tenant, _mem = tenant_and_membership
        # Yalnızca Kasım 2026 için plan ekle
        _make_budget_plan(db_session, tenant.id, "2026-11")

        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            opp_date = date.fromisoformat(opp["date"])
            expected = (opp_date.year == 2026 and opp_date.month == 11)
            assert opp["readiness"]["budget_planned"] == expected, (
                f"{opp['key']} ({opp['date']}): budget_planned={opp['readiness']['budget_planned']}, "
                f"beklenen={expected}"
            )

    def test_content_scheduled_counts_posts_near_date(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Efsane Cuma'ya ±7 gün içinde ContentPost eklince content_scheduled=1 olmalı."""
        tenant, _mem = tenant_and_membership
        # Efsane Cuma 2026-11-27; ±7 gün içinde bir post ekle (2026-11-25)
        _make_content_post(db_session, tenant.id, "2026-11-25T09:00:00")

        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        efsane = next(
            (o for o in result["opportunities"] if o["key"] == "efsane_cuma"), None
        )
        assert efsane is not None
        assert efsane["readiness"]["content_scheduled"] >= 1

    def test_content_scheduled_zero_when_no_posts(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """İçerik yoksa content_scheduled=0 olmalı."""
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            assert opp["readiness"]["content_scheduled"] == 0

    def test_content_scheduled_ignores_other_tenant_posts(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """Başka kiracıya ait postlar sayılmamalı."""
        tenant, _mem = tenant_and_membership
        other_tenant_id = uuid.uuid4()
        _make_content_post(db_session, other_tenant_id, "2026-11-25T09:00:00")

        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            assert opp["readiness"]["content_scheduled"] == 0

    def test_summary_total_matches_opportunities_count(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        assert result["summary"]["total"] == len(result["opportunities"])

    def test_summary_urgent_count(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        expected_urgent = sum(
            1 for o in result["opportunities"] if o["status"] == "urgent"
        )
        assert result["summary"]["urgent"] == expected_urgent

    def test_summary_this_month_count(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        month_prefix = f"{self._as_of.year}-{self._as_of.month:02d}"
        expected = sum(
            1 for o in result["opportunities"] if o["date"].startswith(month_prefix)
        )
        assert result["summary"]["this_month"] == expected

    def test_summary_high_weight_count(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        expected = sum(
            1 for o in result["opportunities"] if o["commerce_weight"] == "yuksek"
        )
        assert result["summary"]["high_weight"] == expected

    def test_larger_horizon_includes_more_opportunities(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result_6 = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        result_12 = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=12
        )
        assert result_12["summary"]["total"] >= result_6["summary"]["total"]

    def test_as_of_in_response_matches_input(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        assert result["as_of"] == self._as_of.isoformat()

    def test_horizon_months_in_response(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=3
        )
        assert result["horizon_months"] == 3

    def test_empty_db_does_not_crash(self, db_session: Session) -> None:
        """Hiç veri olmayan bir kiracı ID'si → servis çökmemeli."""
        result = build_opportunity_calendar(
            db_session, uuid.uuid4(), as_of=self._as_of, horizon_months=6
        )
        assert isinstance(result["opportunities"], list)
        for opp in result["opportunities"]:
            assert opp["readiness"]["budget_planned"] is False
            assert opp["readiness"]["content_scheduled"] == 0

    def test_all_opportunities_have_required_fields(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        required = {
            "key", "date", "name", "category", "commerce_weight",
            "is_approximate", "days_until", "lead_time_days", "status",
            "marketing_tip", "readiness", "suggested_actions",
        }
        for opp in result["opportunities"]:
            missing = required - set(opp.keys())
            assert not missing, f"{opp.get('key', '?')} şu alanları eksik: {missing}"

    def test_suggested_actions_non_empty(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            assert len(opp["suggested_actions"]) >= 1, (
                f"{opp['key']}: suggested_actions boş olamaz"
            )

    def test_suggested_actions_have_label_and_href(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=6
        )
        for opp in result["opportunities"]:
            for action in opp["suggested_actions"]:
                assert "label" in action and action["label"]
                assert "href" in action and action["href"].startswith("/")

    def test_babalar_gunu_in_june_horizon_if_june_21_in_range(
        self, db_session: Session, tenant_and_membership
    ) -> None:
        """as_of=2026-06-29'dan bakınca Babalar Günü (21 Haziran 2026) geçmişte kalır → 12 aylık ufukta 2027'si gelir."""
        tenant, _mem = tenant_and_membership
        result = build_opportunity_calendar(
            db_session, tenant.id, as_of=self._as_of, horizon_months=12
        )
        baba = next(
            (o for o in result["opportunities"] if o["key"] == "babalar_gunu"), None
        )
        assert baba is not None, "Babalar Günü 12 aylık ufukta bulunmalı"
        # 2026-06-21 geçti; 2027-06-20 gelecek
        assert baba["date"] == "2027-06-20"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HTTP endpoint testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarketingCalendarEndpoint:
    """GET /api/v1/marketing-calendar/opportunities endpoint testleri."""

    def test_happy_path_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200

    def test_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"as_of", "horizon_months", "summary", "opportunities"}
        assert isinstance(body["as_of"], str)
        assert isinstance(body["horizon_months"], int)
        assert set(body["summary"].keys()) >= {"total", "urgent", "this_month", "high_weight"}
        assert isinstance(body["opportunities"], list)

    def test_default_horizon_is_6(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        assert resp.json()["horizon_months"] == 6

    def test_custom_horizon_months(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 3},
        )
        assert resp.status_code == 200
        assert resp.json()["horizon_months"] == 3

    def test_horizon_months_too_small_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 0},
        )
        assert resp.status_code == 422

    def test_horizon_months_too_large_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 13},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code in (401, 403)

    def test_opportunities_sorted_in_response(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        dates = [o["date"] for o in resp.json()["opportunities"]]
        assert dates == sorted(dates)

    def test_opportunity_item_shape(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        for opp in resp.json()["opportunities"]:
            assert set(opp.keys()) >= {
                "key", "date", "name", "category", "commerce_weight",
                "is_approximate", "days_until", "lead_time_days", "status",
                "marketing_tip", "readiness", "suggested_actions",
            }
            assert set(opp["readiness"].keys()) >= {"content_scheduled", "budget_planned"}
            assert isinstance(opp["suggested_actions"], list)

    def test_horizon_1_returns_fewer_than_horizon_12(self, client: TestClient) -> None:
        resp_1 = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 1},
        )
        resp_12 = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 12},
        )
        assert resp_1.status_code == 200
        assert resp_12.status_code == 200
        total_1 = resp_1.json()["summary"]["total"]
        total_12 = resp_12.json()["summary"]["total"]
        assert total_12 >= total_1

    def test_as_of_is_today(self, client: TestClient) -> None:
        """API as_of alanı bugünün tarihini döndürmeli."""
        today = datetime.now(timezone.utc).date().isoformat()
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        assert resp.json()["as_of"] == today

    def test_all_statuses_are_valid(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/marketing-calendar/opportunities",
            params={"horizon_months": 12},
        )
        assert resp.status_code == 200
        valid_statuses = {"urgent", "upcoming"}
        for opp in resp.json()["opportunities"]:
            assert opp["status"] in valid_statuses

    def test_commerce_weight_values_valid(self, client: TestClient) -> None:
        resp = client.get("/api/v1/marketing-calendar/opportunities")
        assert resp.status_code == 200
        valid_weights = {"yuksek", "orta", "dusuk"}
        for opp in resp.json()["opportunities"]:
            assert opp["commerce_weight"] in valid_weights
