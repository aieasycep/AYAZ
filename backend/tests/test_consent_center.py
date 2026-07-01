"""Self-contained tests for KVKK Rıza Yönetim Merkezi (Consent Management Center).

Coverage
--------
1. Summary counts + consent_rate math
   - correct total/consented/skipped counts
   - consent_rate = round(consented/total*100, 1)
   - total == 0 → consent_rate_pct == 0.0, no divide-by-zero

2. Signals (Consent Mode v2 granular)
   - exactly 4 entries in canonical _CONSENT_SIGNAL_KEYS order
   - granted + denied count per signal
   - grant_rate_pct math
   - legacy fallback: event with consent=True but consent_signals=None counts all 4 granted
   - granular_supported true/false

3. Destinations
   - posture_label reflects consent_required (Katı / Gevşek)
   - per-destination forwarded / skipped_no_consent counts

4. Compliance
   - score / grade / counts correct
   - acik_riza_mekanizmasi: fail when no source has consent_cookie_var
   - acik_riza_mekanizmasi: pass when source has consent_cookie_var
   - riza_olmadan_aktarim_engelleme: warn when no destination consent_required
   - consent_mode_v2_granular: warn when no granular signals
   - riza_orani_saglikli: pass >= 70%, warn >= 40%, fail < 40%
   - riza_denetim_izi: warn when total_events == 0, pass when > 0
   - riza_zorlama_calisiyor: warn when no skipped and no required-consent dest

5. Audit trail
   - at most 15 entries
   - ordered newest first (by event_time)
   - status_label mapping correct
   - signals_summary format correct

6. Date filter
   - date_from > date_to via API → 422
   - date window narrows events returned
   - omitted dates → all events; period derived from actual min/max event_time

7. API
   - GET /consent/center → 200 with all required top-level keys
   - missing auth → 401 or 403
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Register all models so Base.metadata.create_all works ─────────────────────
import ayaz.models.oltp           # noqa: F401
import ayaz.models.analytics      # noqa: F401
import ayaz.models.feeds          # noqa: F401
import ayaz.models.insights       # noqa: F401
import ayaz.models.reports        # noqa: F401
import ayaz.models.automation     # noqa: F401
import ayaz.models.tracking       # noqa: F401
import ayaz.models.goals          # noqa: F401
import ayaz.models.billing        # noqa: F401
import ayaz.models.briefing       # noqa: F401
import ayaz.models.budget         # noqa: F401
import ayaz.models.content        # noqa: F401
import ayaz.models.notifications  # noqa: F401
import ayaz.models.social_inbox   # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import consent_center as consent_center_module
from ayaz.services.auth import hash_password
from ayaz.services.consent_center import build_consent_center
from ayaz.services.tracking import _CONSENT_SIGNAL_KEYS

# ── Minimal test app ──────────────────────────────────────────────────────────

_test_app = FastAPI(title="AYAZ Consent Center Test App")
_test_app.include_router(consent_center_module.router, prefix="/api/v1")


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
def tenant_and_membership(db_session: Session):
    """Create a tenant + user + membership; return (tenant, membership)."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Consent Test Tenant",
        base_currency="TRY",
        country="TR",
        kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(),
        email="consent_test@ayaz.app",
        hashed_password=hash_password("test1234"),
        full_name="Consent Test User",
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
    """TestClient with DB + membership dependencies overridden."""
    _tenant, membership = tenant_and_membership

    def _override_db():
        yield db_session

    def _override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_membership] = _override_membership

    with TestClient(_test_app) as c:
        yield c

    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    """TestClient with NO membership override — tests 401/403 behaviour."""
    def _override_db():
        yield db_session

    _test_app.dependency_overrides[get_db] = _override_db
    # get_current_membership NOT overridden → real impl → raises 401/403

    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c

    _test_app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_source(
    db: Session,
    tenant: Tenant,
    *,
    consent_cookie_var: str | None = None,
    is_active: bool = True,
) -> TrackingSource:
    src = TrackingSource(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=f"Source-{secrets.token_hex(4)}",
        domain="example.com",
        public_token=secrets.token_urlsafe(32),
        is_active=is_active,
        disabled_events=[],
        consent_cookie_var=consent_cookie_var,
    )
    db.add(src)
    db.flush()
    return src


def _make_destination(
    db: Session,
    tenant: Tenant,
    source: TrackingSource,
    *,
    platform: str = "meta_capi",
    consent_required: bool = True,
    required_consent: list | None = None,
) -> EventDestination:
    dest = EventDestination(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tracking_source_id=source.id,
        platform=platform,
        config={"pixel_id": "TEST123"},
        vault_secret_ref="vault/test",
        consent_required=consent_required,
        required_consent=required_consent,
        is_active=True,
    )
    db.add(dest)
    db.flush()
    return dest


def _make_event(
    db: Session,
    tenant: Tenant,
    source: TrackingSource,
    *,
    consent: bool = True,
    consent_signals: dict | None = None,
    status: str = "forwarded",
    event_time: str = "2026-01-15T10:00:00+00:00",
    event_name: str = "Purchase",
    forwarded_count: int = 1,
) -> ConversionEvent:
    evt = ConversionEvent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tracking_source_id=source.id,
        event_name=event_name,
        event_time=event_time,
        event_id=secrets.token_hex(8),
        user_data={},
        custom_data={},
        consent=consent,
        consent_signals=consent_signals,
        status=status,
        forwarded_count=forwarded_count,
        created_at=event_time,
    )
    db.add(evt)
    db.flush()
    return evt


# ── 1. Summary counts + consent_rate math ────────────────────────────────────


def test_summary_counts_basic(db_session: Session):
    """Basic summary: total, consented, skipped, consent_rate."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 3 consented, 1 skipped_no_consent (consent=False)
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-10T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-11T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True, status="failed",
                event_time="2026-01-12T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=False,
                status="skipped_no_consent",
                event_time="2026-01-13T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    s = result["summary"]

    assert s["total_events"] == 4
    assert s["consented_events"] == 3
    assert s["skipped_no_consent"] == 1
    assert s["consent_rate_pct"] == 75.0  # 3/4 * 100


def test_summary_no_events(db_session: Session):
    """Empty tenant → zeros, no divide-by-zero."""
    tenant = _make_tenant(db_session)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    s = result["summary"]

    assert s["total_events"] == 0
    assert s["consented_events"] == 0
    assert s["skipped_no_consent"] == 0
    assert s["consent_rate_pct"] == 0.0


def test_consent_rate_rounding(db_session: Session):
    """consent_rate_pct is rounded to 1 decimal place."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 1 consented out of 3 → 33.3%
    for i in range(3):
        _make_event(
            db_session, tenant, src,
            consent=(i == 0),
            status="forwarded" if i == 0 else "skipped_no_consent",
            event_time=f"2026-01-{10 + i:02d}T10:00:00+00:00",
        )
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["summary"]["consent_rate_pct"] == 33.3


# ── 2. Signals ────────────────────────────────────────────────────────────────


def test_signals_canonical_order(db_session: Session):
    """4 signal entries returned in _CONSENT_SIGNAL_KEYS canonical order."""
    tenant = _make_tenant(db_session)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    signal_keys = [s["key"] for s in result["signals"]]
    assert signal_keys == list(_CONSENT_SIGNAL_KEYS)


def test_signals_count_all_consented(db_session: Session):
    """All 4 signals granted when event consent=True with full consent_signals."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    signals = {k: True for k in _CONSENT_SIGNAL_KEYS}
    _make_event(db_session, tenant, src, consent=True, consent_signals=signals,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    for sig in result["signals"]:
        assert sig["granted"] == 1, f"{sig['key']}: expected granted=1"
        assert sig["denied"] == 0, f"{sig['key']}: expected denied=0"
        assert sig["grant_rate_pct"] == 100.0


def test_signals_partial_consent(db_session: Session):
    """Partial consent_signals: ad_personalization denied, rest granted."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    signals = {
        "ad_storage": True,
        "ad_user_data": True,
        "analytics_storage": True,
        "ad_personalization": False,
    }
    _make_event(db_session, tenant, src, consent=True, consent_signals=signals,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    sig_by_key = {s["key"]: s for s in result["signals"]}

    assert sig_by_key["ad_storage"]["granted"] == 1
    assert sig_by_key["analytics_storage"]["granted"] == 1
    assert sig_by_key["ad_user_data"]["granted"] == 1
    assert sig_by_key["ad_personalization"]["granted"] == 0
    assert sig_by_key["ad_personalization"]["denied"] == 1
    assert sig_by_key["ad_personalization"]["grant_rate_pct"] == 0.0


def test_signals_legacy_fallback_true(db_session: Session):
    """Legacy event with consent=True but consent_signals=None counts all 4 granted."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, consent_signals=None,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    for sig in result["signals"]:
        assert sig["granted"] == 1, f"{sig['key']}: legacy fallback should give granted=1"
        assert sig["denied"] == 0


def test_signals_legacy_fallback_false(db_session: Session):
    """Legacy event with consent=False and consent_signals=None counts all 4 denied."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=False, consent_signals=None,
                status="skipped_no_consent",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    for sig in result["signals"]:
        assert sig["granted"] == 0, f"{sig['key']}: legacy fallback should give granted=0"
        assert sig["denied"] == 1


def test_granular_supported_false_when_no_signals(db_session: Session):
    """granular_supported is False when no events have consent_signals."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, consent_signals=None,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["summary"]["granular_supported"] is False


def test_granular_supported_true_when_signals_present(db_session: Session):
    """granular_supported is True when at least one event has consent_signals."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    signals = {k: True for k in _CONSENT_SIGNAL_KEYS}
    _make_event(db_session, tenant, src, consent=True, consent_signals=signals,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["summary"]["granular_supported"] is True


def test_signals_grant_rate_math(db_session: Session):
    """grant_rate_pct = granted / (granted+denied) * 100, rounded to 1 decimal."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 2 events: one with all granted, one with all denied
    _make_event(db_session, tenant, src, consent=True,
                consent_signals={k: True for k in _CONSENT_SIGNAL_KEYS},
                event_time="2026-01-10T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=False,
                consent_signals={k: False for k in _CONSENT_SIGNAL_KEYS},
                status="skipped_no_consent",
                event_time="2026-01-11T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    for sig in result["signals"]:
        assert sig["granted"] == 1
        assert sig["denied"] == 1
        assert sig["grant_rate_pct"] == 50.0


# ── 3. Destinations ───────────────────────────────────────────────────────────


def test_destinations_posture_label_strict(db_session: Session):
    """consent_required=True → posture_label contains 'Katı'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, consent_required=True)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert len(result["destinations"]) == 1
    assert "Katı" in result["destinations"][0]["posture_label"]


def test_destinations_posture_label_relaxed(db_session: Session):
    """consent_required=False → posture_label contains 'Gevşek'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, consent_required=False)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert "Gevşek" in result["destinations"][0]["posture_label"]


def test_destinations_forwarded_skipped_counts(db_session: Session):
    """Per-destination counts use source-level event status as proxy."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, platform="meta_capi", consent_required=True)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-10T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-11T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=False, status="skipped_no_consent",
                event_time="2026-01-12T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    dest = result["destinations"][0]
    assert dest["forwarded"] == 2
    assert dest["skipped_no_consent"] == 1


def test_destinations_no_destinations(db_session: Session):
    """Empty destinations list when no EventDestination exists."""
    tenant = _make_tenant(db_session)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["destinations"] == []


# ── 4. Compliance ─────────────────────────────────────────────────────────────


def test_compliance_acik_riza_fail_when_no_cookie_var(db_session: Session):
    """acik_riza_mekanizmasi fails when no active source has consent_cookie_var."""
    tenant = _make_tenant(db_session)
    _make_source(db_session, tenant, consent_cookie_var=None)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["acik_riza_mekanizmasi"]["status"] == "fail"


def test_compliance_acik_riza_pass_when_cookie_var_set(db_session: Session):
    """acik_riza_mekanizmasi passes when source has consent_cookie_var."""
    tenant = _make_tenant(db_session)
    _make_source(db_session, tenant, consent_cookie_var="ayaz_consent")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["acik_riza_mekanizmasi"]["status"] == "pass"


def test_compliance_riza_olmadan_warn_when_no_consent_required(db_session: Session):
    """riza_olmadan_aktarim_engelleme warns when no destination requires consent."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, consent_required=False)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_olmadan_aktarim_engelleme"]["status"] == "warn"


def test_compliance_riza_olmadan_pass_when_consent_required(db_session: Session):
    """riza_olmadan_aktarim_engelleme passes when a destination requires consent."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, consent_required=True)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_olmadan_aktarim_engelleme"]["status"] == "pass"


def test_compliance_consent_mode_v2_granular_warn_when_no_signals(db_session: Session):
    """consent_mode_v2_granular warns when no granular signals in events."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, consent_signals=None,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["consent_mode_v2_granular"]["status"] == "warn"


def test_compliance_consent_mode_v2_granular_pass_when_signals_present(db_session: Session):
    """consent_mode_v2_granular passes when at least one event has signals."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                consent_signals={k: True for k in _CONSENT_SIGNAL_KEYS},
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["consent_mode_v2_granular"]["status"] == "pass"


def test_compliance_riza_orani_fail_low_rate(db_session: Session):
    """riza_orani_saglikli fails when consent rate < 40%."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 1 consented out of 10 → 10%
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-10T10:00:00+00:00")
    for i in range(9):
        _make_event(db_session, tenant, src, consent=False,
                    status="skipped_no_consent",
                    event_time=f"2026-01-{11 + i:02d}T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_orani_saglikli"]["status"] == "fail"


def test_compliance_riza_orani_warn_mid_rate(db_session: Session):
    """riza_orani_saglikli warns when consent rate is 40%-69%."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 5 consented out of 10 → 50%
    for i in range(5):
        _make_event(db_session, tenant, src, consent=True, status="forwarded",
                    event_time=f"2026-01-{10 + i:02d}T10:00:00+00:00")
    for i in range(5):
        _make_event(db_session, tenant, src, consent=False,
                    status="skipped_no_consent",
                    event_time=f"2026-01-{15 + i:02d}T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_orani_saglikli"]["status"] == "warn"


def test_compliance_riza_orani_pass_high_rate(db_session: Session):
    """riza_orani_saglikli passes when consent rate >= 70%."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # 8 consented out of 10 → 80%
    for i in range(8):
        _make_event(db_session, tenant, src, consent=True, status="forwarded",
                    event_time=f"2026-01-{10 + i:02d}T10:00:00+00:00")
    for i in range(2):
        _make_event(db_session, tenant, src, consent=False,
                    status="skipped_no_consent",
                    event_time=f"2026-01-{18 + i:02d}T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_orani_saglikli"]["status"] == "pass"


def test_compliance_riza_denetim_izi_warn_no_events(db_session: Session):
    """riza_denetim_izi warns when no events exist."""
    tenant = _make_tenant(db_session)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_denetim_izi"]["status"] == "warn"


def test_compliance_riza_denetim_izi_pass_with_events(db_session: Session):
    """riza_denetim_izi passes when at least one event exists."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_denetim_izi"]["status"] == "pass"


def test_compliance_riza_zorlama_warn_no_enforcement(db_session: Session):
    """riza_zorlama_calisiyor warns when no skipped events and no required-consent dest."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    _make_destination(db_session, tenant, src, consent_required=False)
    db_session.commit()

    # Only forwarded events; no skipped_no_consent
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_zorlama_calisiyor"]["status"] == "warn"


def test_compliance_riza_zorlama_pass_with_skipped_events(db_session: Session):
    """riza_zorlama_calisiyor passes when skipped_no_consent events exist."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=False,
                status="skipped_no_consent",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    checks = {c["id"]: c for c in result["compliance"]["checks"]}
    assert checks["riza_zorlama_calisiyor"]["status"] == "pass"


def test_compliance_score_and_grade_all_pass(db_session: Session):
    """Score = 100 and grade = 'uyumlu' when all checks pass."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant, consent_cookie_var="ayaz_consent")
    _make_destination(db_session, tenant, src, consent_required=True)
    db_session.commit()

    # 9 consented, 1 skipped → 90% rate, skipped>0 → enforcement active
    for i in range(9):
        _make_event(db_session, tenant, src, consent=True,
                    consent_signals={k: True for k in _CONSENT_SIGNAL_KEYS},
                    event_time=f"2026-01-{10 + i:02d}T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=False,
                consent_signals={k: False for k in _CONSENT_SIGNAL_KEYS},
                status="skipped_no_consent",
                event_time="2026-01-20T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    compliance = result["compliance"]
    # All 7 checks should be pass
    for check in compliance["checks"]:
        assert check["status"] == "pass", f"Expected pass for {check['id']}: {check['status']}"
    assert compliance["score"] == 100
    assert compliance["grade"] == "uyumlu"
    assert compliance["counts"]["fail"] == 0
    assert compliance["counts"]["warn"] == 0


def test_compliance_score_formula(db_session: Session):
    """Score = max(0, 100 - 16*fail - 7*warn)."""
    tenant = _make_tenant(db_session)
    # No sources, no destinations → acik_riza fail + riza_olmadan warn + no_events warn + zorlama warn
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    compliance = result["compliance"]
    fail_c = compliance["counts"]["fail"]
    warn_c = compliance["counts"]["warn"]
    expected_score = max(0, 100 - 16 * fail_c - 7 * warn_c)
    assert compliance["score"] == expected_score


def test_compliance_counts_match_checks(db_session: Session):
    """counts.pass + counts.warn + counts.fail == len(checks)."""
    tenant = _make_tenant(db_session)
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    compliance = result["compliance"]
    counts = compliance["counts"]
    checks = compliance["checks"]
    assert counts["pass"] + counts["warn"] + counts["fail"] == len(checks)


def test_compliance_grade_eksik(db_session: Session):
    """Grade 'eksik' when score < 50.

    Scenario: no consent_cookie_var → acik_riza fail; no consent_required → riza_olmadan warn;
    no granular signals → v2_granular warn; low consent rate (10%) → riza_orani fail;
    skipped > 0 → zorlama pass; events > 0 → denetim pass; veri_minimizasyonu pass.
    Result: fail=2, warn=2 → score = 100-32-14 = 54.
    To push below 50 we need fail=3: add second source with no cookie_var would not add
    another fail check. Instead achieve fail=3 by constructing a scenario where
    riza_zorlama is also warn: no skipped events AND no required-consent destinations.
    Then: fail=2 (acik_riza + riza_orani), warn=3 (riza_olmadan + v2_granular + zorlama)
    → score = 100 - 32 - 21 = 47 < 50.
    """
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant, consent_cookie_var=None)
    # consent_required=False → riza_olmadan warn; zorlama will warn too
    _make_destination(db_session, tenant, src, consent_required=False)
    db_session.commit()

    # 1 consented out of 10 → 10% → riza_orani fail
    # No skipped_no_consent events (status=forwarded for all) AND no required-consent dest
    # → zorlama warn
    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                consent_signals=None,   # no granular → v2_granular warn
                event_time="2026-01-10T10:00:00+00:00")
    for i in range(9):
        _make_event(db_session, tenant, src, consent=False, status="failed",
                    consent_signals=None,
                    event_time=f"2026-01-{11 + i:02d}T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    compliance = result["compliance"]
    # acik_riza=fail, riza_orani=fail → 2 fails
    # riza_olmadan=warn, v2_granular=warn, zorlama=warn → 3 warns
    # score = 100 - 32 - 21 = 47
    assert compliance["counts"]["fail"] >= 2
    assert compliance["score"] < 50
    assert compliance["grade"] == "eksik"


# ── 5. Audit trail ────────────────────────────────────────────────────────────


def test_audit_trail_at_most_15(db_session: Session):
    """Audit trail contains at most 15 entries even with more events."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    # Create 20 events
    for i in range(20):
        _make_event(db_session, tenant, src, consent=True,
                    event_time=f"2026-01-{10 + i // 2:02d}T{i % 24:02d}:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert len(result["audit_trail"]) <= 15


def test_audit_trail_newest_first(db_session: Session):
    """Audit trail is ordered newest-first by event_time."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-10T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-15T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-12T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    times = [e["event_time"] for e in result["audit_trail"]]
    assert times == sorted(times, reverse=True)


def test_audit_trail_status_label_forwarded(db_session: Session):
    """status_label for 'forwarded' is 'İletildi'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, status="forwarded",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["status_label"] == "İletildi"


def test_audit_trail_status_label_skipped(db_session: Session):
    """status_label for 'skipped_no_consent' is 'Rıza yok — atlandı'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=False, status="skipped_no_consent",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["status_label"] == "Rıza yok — atlandı"


def test_audit_trail_status_label_failed(db_session: Session):
    """status_label for 'failed' is 'Başarısız'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, status="failed",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["status_label"] == "Başarısız"


def test_audit_trail_signals_summary_all_granted(db_session: Session):
    """signals_summary shows '4/4 onaylı' when all 4 signals granted."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                consent_signals={k: True for k in _CONSENT_SIGNAL_KEYS},
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["signals_summary"] == "4/4 onaylı"


def test_audit_trail_signals_summary_none_granted(db_session: Session):
    """signals_summary shows '0/4 onaylı' when no signals granted."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=False,
                consent_signals={k: False for k in _CONSENT_SIGNAL_KEYS},
                status="skipped_no_consent",
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["signals_summary"] == "0/4 onaylı"


def test_audit_trail_signals_summary_legacy_true(db_session: Session):
    """Legacy event with consent=True, consent_signals=None → '4/4 onaylı'."""
    tenant = _make_tenant(db_session)
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True, consent_signals=None,
                event_time="2026-01-10T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["audit_trail"][0]["signals_summary"] == "4/4 onaylı"


# ── 6. Date filter ────────────────────────────────────────────────────────────


def test_date_filter_from_gt_to_via_api_returns_422(client):
    """API returns 422 when date_from > date_to."""
    resp = client.get(
        "/api/v1/consent/center",
        params={"date_from": "2026-06-30", "date_to": "2026-06-01"},
    )
    assert resp.status_code == 422


def test_date_filter_narrows_events(db_session: Session, tenant_and_membership):
    """Date window narrows the events returned in the result."""
    tenant, _membership = tenant_and_membership
    src = _make_source(db_session, tenant)
    db_session.commit()

    # Event inside window
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-15T10:00:00+00:00")
    # Event outside window (too early)
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-01T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(
        db_session, tenant.id,
        date_from="2026-01-10", date_to="2026-01-20"
    )
    assert result["summary"]["total_events"] == 1


def test_date_filter_omitted_includes_all_events(db_session: Session, tenant_and_membership):
    """Omitted dates → all events; period derived from actual event_time."""
    tenant, _membership = tenant_and_membership
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                event_time="2025-06-01T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-06-01T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["summary"]["total_events"] == 2
    # Period derived from actual data
    assert result["period"]["date_from"] is not None
    assert result["period"]["date_to"] is not None
    assert result["period"]["date_from"] <= result["period"]["date_to"]


def test_date_filter_period_from_actual_data(db_session: Session, tenant_and_membership):
    """Period reflects actual min/max event_time when dates are omitted."""
    tenant, _membership = tenant_and_membership
    src = _make_source(db_session, tenant)
    db_session.commit()

    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-05T10:00:00+00:00")
    _make_event(db_session, tenant, src, consent=True,
                event_time="2026-01-20T10:00:00+00:00")
    db_session.commit()

    result = build_consent_center(db_session, tenant.id)
    assert result["period"]["date_from"].startswith("2026-01-05")
    assert result["period"]["date_to"].startswith("2026-01-20")


# ── 7. API ────────────────────────────────────────────────────────────────────


def test_api_get_consent_center_200(client):
    """GET /consent/center returns 200 with all required top-level keys."""
    resp = client.get("/api/v1/consent/center")
    assert resp.status_code == 200
    data = resp.json()
    required_keys = {
        "generated_at", "period", "summary", "signals",
        "destinations", "sources", "compliance", "audit_trail",
    }
    assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"


def test_api_summary_keys_present(client):
    """summary block contains all expected keys."""
    resp = client.get("/api/v1/consent/center")
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    for key in ("total_events", "consented_events", "consent_rate_pct",
                "skipped_no_consent", "granular_supported"):
        assert key in summary, f"Missing summary key: {key}"


def test_api_signals_structure(client):
    """signals list has 4 entries, each with required keys."""
    resp = client.get("/api/v1/consent/center")
    assert resp.status_code == 200
    signals = resp.json()["signals"]
    assert len(signals) == 4
    for sig in signals:
        for key in ("key", "label", "granted", "denied", "grant_rate_pct", "description"):
            assert key in sig, f"Missing signal key: {key}"


def test_api_compliance_structure(client):
    """compliance block has score, grade, counts, checks."""
    resp = client.get("/api/v1/consent/center")
    assert resp.status_code == 200
    compliance = resp.json()["compliance"]
    assert "score" in compliance
    assert "grade" in compliance
    assert "counts" in compliance
    assert "checks" in compliance
    assert compliance["grade"] in ("uyumlu", "kismi", "eksik")


def test_api_date_params_accepted(client):
    """date_from and date_to query params are accepted."""
    resp = client.get(
        "/api/v1/consent/center",
        params={"date_from": "2026-01-01", "date_to": "2026-06-30"},
    )
    assert resp.status_code == 200


def test_api_missing_auth_returns_401_or_403(unauth_client):
    """Missing auth → 401 or 403."""
    resp = unauth_client.get("/api/v1/consent/center")
    assert resp.status_code in (401, 403)
