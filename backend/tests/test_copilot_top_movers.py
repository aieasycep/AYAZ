"""Tests for the get_top_movers Copilot tool — added in M11 extension.

Coverage
--------
* Tool is registered in _TOOLS and TOOL_SPECS.
* Tool is NOT in ACTION_TOOLS (read-only).
* Calling the tool returns ranked movers for seeded data with correct deltas.
* Default dates work (no date_from/date_to needed).
* Dimension=campaign works.
* Tenant isolation: a second tenant's data never leaks.
* TOOL_SPECS schema entry has the correct name, Turkish description, and enum values.

Fixture strategy
----------------
We use the same in-memory SQLite pattern as test_copilot.py.  Two periods of
data are seeded under a fixed date range so delta assertions are deterministic:

    google_ads:
        previous period (prev_date): spend=2000
        current period  (curr_date): spend=1200   → delta = -800 (down)

    meta_ads:
        previous period (prev_date): spend=1000
        current period  (curr_date): spend=1500   → delta = +500 (up)

Absolute delta ranking: google_ads (800) > meta_ads (500).

The conftest autouse fixture clears app.dependency_overrides around every test.
Our tests set their own overrides on the tool-layer directly (not via the HTTP
client), so we never touch app.dependency_overrides here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.base import Base
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

# ── Fixed test dates — deterministic delta assertions ─────────────────────────

_CURR_DATE = date(2024, 5, 8)   # current period: 2024-05-08 → 2024-05-14
_PREV_DATE = date(2024, 5, 1)   # previous period: 2024-05-01 → 2024-05-07

_DATE_FROM = "2024-05-08"
_DATE_TO = "2024-05-14"


# ── In-memory DB fixture ─────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Isolated in-memory SQLite DB with all AYAZ tables."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import ayaz.models.oltp  # noqa: F401
    import ayaz.models.analytics  # noqa: F401
    import ayaz.models.feeds  # noqa: F401
    import ayaz.models.insights  # noqa: F401
    import ayaz.models.reports  # noqa: F401
    import ayaz.models.automation  # noqa: F401
    import ayaz.models.tracking  # noqa: F401
    import ayaz.models.billing  # noqa: F401
    import ayaz.models.copilot  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── DB helpers ────────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
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


def _make_user(db: Session, email: str = "test@ayaz.app") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("pass1234"),
        full_name="Test User",
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


def _make_connected_account(db: Session, tenant: Tenant) -> ConnectedAccount:
    return ConnectedAccount(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        platform=Platform.google_ads,
        external_account_id=f"ext-{uuid.uuid4()}",
        display_name="Test Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.replace("_", " ").title())
    db.add(ch)
    db.flush()
    return ch


def _make_dim_date(db: Session, d: date) -> DimDate:
    existing = db.get(DimDate, d)
    if existing:
        return existing
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
    return dim


def _make_campaign(
    db: Session, tenant: Tenant, channel: DimChannel, name: str
) -> DimCampaign:
    c = DimCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        external_id=f"ext-{uuid.uuid4()}",
        name=name,
    )
    db.add(c)
    db.flush()
    return c


def _make_fact(
    db: Session,
    tenant: Tenant,
    channel: DimChannel,
    campaign: DimCampaign,
    d: date,
    spend: float,
    impressions: float = 10000.0,
    clicks: float = 100.0,
    conversions: float = 10.0,
    conv_value: float = 500.0,
) -> FactDailyMetrics:
    acct = _make_connected_account(db, tenant)
    db.add(acct)
    db.flush()

    adset = DimAdSet(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        external_id=f"adset-{uuid.uuid4()}",
        name="adset",
    )
    db.add(adset)
    db.flush()

    ad = DimAd(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        ad_set_id=adset.id,
        external_id=f"ad-{uuid.uuid4()}",
        name="ad",
    )
    db.add(ad)
    db.flush()

    _make_dim_date(db, d)

    f = FactDailyMetrics(
        tenant_id=tenant.id,
        connected_account_id=acct.id,
        channel_id=channel.id,
        campaign_id=campaign.id,
        adset_id=adset.id,
        ad_id=ad.id,
        date_key=d,
        impressions=impressions,
        clicks=clicks,
        cost_raw=Decimal(str(spend)),
        cost_ccy="TRY",
        cost_base_ccy=Decimal(str(spend)),
        conversions=Decimal(str(conversions)),
        conversion_value_raw=Decimal(str(conv_value)),
        conversion_value_ccy="TRY",
        conv_value_base_ccy=Decimal(str(conv_value)),
        ingested_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.flush()
    return f


@pytest.fixture()
def seeded(db_session: Session):
    """Seed two channels across two periods with known spend deltas.

    google_ads: prev=2000 → curr=1200  (delta=-800, down)
    meta_ads:   prev=1000 → curr=1500  (delta=+500, up)
    """
    db = db_session
    tenant = _make_tenant(db)
    user = _make_user(db)
    membership = _make_membership(db, user, tenant)

    ch_google = _make_channel(db, "google_ads")
    ch_meta = _make_channel(db, "meta_ads")

    camp_google = _make_campaign(db, tenant, ch_google, "Google Kampanya")
    camp_meta = _make_campaign(db, tenant, ch_meta, "Meta Kampanya")

    # Previous period facts
    _make_fact(db, tenant, ch_google, camp_google, _PREV_DATE, spend=2000.0)
    _make_fact(db, tenant, ch_meta, camp_meta, _PREV_DATE, spend=1000.0)

    # Current period facts
    _make_fact(db, tenant, ch_google, camp_google, _CURR_DATE, spend=1200.0)
    _make_fact(db, tenant, ch_meta, camp_meta, _CURR_DATE, spend=1500.0)

    db.commit()
    return db, tenant, user, membership, ch_google, ch_meta, camp_google, camp_meta


# ── Registration tests ────────────────────────────────────────────────────────


class TestGetTopMoversRegistration:
    """Verify the tool is correctly registered in all expected collections."""

    def test_registered_in_tools_dict(self):
        from ayaz.services.copilot_tools import _TOOLS
        assert "get_top_movers" in _TOOLS

    def test_registered_in_tool_specs(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        assert any(t["name"] == "get_top_movers" for t in TOOL_SPECS)

    def test_not_in_action_tools(self):
        from ayaz.services.copilot_tools import ACTION_TOOLS
        assert "get_top_movers" not in ACTION_TOOLS

    def test_tool_spec_has_turkish_description(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        spec = next(t for t in TOOL_SPECS if t["name"] == "get_top_movers")
        desc = spec["description"]
        # Must contain Turkish key phrase from the spec
        assert "dönem" in desc.lower() or "değişen" in desc.lower()

    def test_tool_spec_has_dimension_enum(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        spec = next(t for t in TOOL_SPECS if t["name"] == "get_top_movers")
        props = spec["input_schema"]["properties"]
        assert "dimension" in props
        assert set(props["dimension"]["enum"]) == {"channel", "campaign"}

    def test_tool_spec_has_metric_enum(self):
        from ayaz.services.copilot_tools import TOOL_SPECS
        spec = next(t for t in TOOL_SPECS if t["name"] == "get_top_movers")
        props = spec["input_schema"]["properties"]
        assert "metric" in props
        assert "spend" in props["metric"]["enum"]
        assert "roas" in props["metric"]["enum"]

    def test_tool_spec_has_no_required_params(self):
        """All parameters should be optional — defaults must work."""
        from ayaz.services.copilot_tools import TOOL_SPECS
        spec = next(t for t in TOOL_SPECS if t["name"] == "get_top_movers")
        assert spec["input_schema"].get("required", []) == []


# ── Dispatch / return value tests ─────────────────────────────────────────────


class TestGetTopMoversDispatch:
    """Test the tool returns correct ranked movers for seeded data."""

    def test_returns_dict_with_expected_keys(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        for key in ("dimension", "metric", "period", "previous_period", "movers"):
            assert key in result, f"Missing key: {key}"

    def test_movers_list_has_expected_item_keys(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        for item in result["movers"]:
            for field in ("label", "current", "previous", "delta", "delta_pct", "direction"):
                assert field in item, f"Missing field in mover item: {field}"

    def test_google_ads_ranked_first_by_absolute_delta(self, seeded):
        """google_ads delta=-800, meta_ads delta=+500 → google comes first."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
            "limit": 5,
        })
        labels = [m["label"] for m in result["movers"]]
        google_idx = next(i for i, lbl in enumerate(labels) if "google" in lbl.lower())
        meta_idx = next(i for i, lbl in enumerate(labels) if "meta" in lbl.lower())
        assert google_idx < meta_idx, (
            f"google_ads (|delta|=800) should rank before meta_ads (|delta|=500); "
            f"labels: {labels}"
        )

    def test_google_ads_delta_correct(self, seeded):
        """google_ads: curr=1200, prev=2000 → delta=-800."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        google = next(m for m in result["movers"] if "google" in m["label"].lower())
        assert google["delta"] == pytest.approx(-800.0, abs=0.01)
        assert google["direction"] == "down"

    def test_meta_ads_delta_correct(self, seeded):
        """meta_ads: curr=1500, prev=1000 → delta=+500."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        meta = next(m for m in result["movers"] if "meta" in m["label"].lower())
        assert meta["delta"] == pytest.approx(500.0, abs=0.01)
        assert meta["direction"] == "up"

    def test_delta_pct_google_ads(self, seeded):
        """google_ads: (1200-2000)/2000 = -0.4."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        google = next(m for m in result["movers"] if "google" in m["label"].lower())
        assert google["delta_pct"] == pytest.approx(-0.4, abs=1e-4)

    def test_delta_pct_meta_ads(self, seeded):
        """meta_ads: (1500-1000)/1000 = 0.5."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        meta = next(m for m in result["movers"] if "meta" in m["label"].lower())
        assert meta["delta_pct"] == pytest.approx(0.5, abs=1e-4)

    def test_sorted_by_absolute_delta_descending(self, seeded):
        """Movers list must always be sorted by |delta| descending."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        abs_deltas = [abs(m["delta"]) for m in result["movers"]]
        assert abs_deltas == sorted(abs_deltas, reverse=True)

    def test_limit_parameter_respected(self, seeded):
        """limit=1 should return exactly 1 mover."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
            "limit": 1,
        })
        assert len(result["movers"]) == 1

    def test_dimension_campaign_returns_campaign_labels(self, seeded):
        """dimension=campaign should return campaign names as labels."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
            "dimension": "campaign",
        })
        assert result["dimension"] == "campaign"
        labels = {m["label"] for m in result["movers"]}
        assert any("Kampanya" in lbl for lbl in labels)

    def test_default_metric_is_spend(self, seeded):
        """When metric is not specified the result should be for spend."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        assert result["metric"] == "spend"

    def test_default_dimension_is_channel(self, seeded):
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
        })
        assert result["dimension"] == "channel"


# ── Default dates ─────────────────────────────────────────────────────────────


class TestGetTopMoversDefaultDates:
    """Calling the tool without dates should use the last 30 days."""

    def test_no_dates_returns_result_not_error(self, seeded):
        """Tool must not raise when dates are omitted."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        # Seed a fact for today so the 30-day window picks up data.
        today = date.today()
        _, _, _, _, ch_google, _, camp_google, _ = seeded
        _make_fact(db, tenant, ch_google, camp_google, today, spend=999.0)
        db.commit()

        result = dispatch("get_top_movers", db, tenant.id, {})
        assert "movers" in result
        assert "error" not in result

    def test_no_dates_period_string_contains_today(self, seeded):
        """period field in the result must reflect today as the end date."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        today = date.today().isoformat()
        result = dispatch("get_top_movers", db, tenant.id, {})
        assert today in result["period"]

    def test_empty_string_dates_treated_as_defaults(self, seeded):
        """Passing empty-string dates should not crash — treated as omitted."""
        db, tenant, *_ = seeded
        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant.id, {
            "date_from": "",
            "date_to": "",
        })
        assert "movers" in result
        assert "error" not in result


# ── Tenant isolation ──────────────────────────────────────────────────────────


class TestGetTopMoversTenantIsolation:
    """A second tenant's data must never appear in the first tenant's results."""

    def test_tenant_b_spend_not_visible_to_tenant_a(self, db_session: Session):
        db = db_session

        # Tenant A — seeded with normal spend
        tenant_a = _make_tenant(db, "Tenant A")
        ch_a = _make_channel(db, "google_ads_a")
        camp_a = _make_campaign(db, tenant_a, ch_a, "A Campaign")
        _make_fact(db, tenant_a, ch_a, camp_a, _CURR_DATE, spend=500.0)
        _make_fact(db, tenant_a, ch_a, camp_a, _PREV_DATE, spend=300.0)

        # Tenant B — seeded with a very distinct spend value
        tenant_b = _make_tenant(db, "Tenant B")
        ch_b = _make_channel(db, "google_ads_b")
        camp_b = _make_campaign(db, tenant_b, ch_b, "B Campaign")
        _make_fact(db, tenant_b, ch_b, camp_b, _CURR_DATE, spend=999999.0)

        db.commit()

        from ayaz.services.copilot_tools import dispatch

        result = dispatch("get_top_movers", db, tenant_a.id, {
            "date_from": _DATE_FROM,
            "date_to": _DATE_TO,
            "limit": 20,
        })

        for mover in result["movers"]:
            assert mover["current"] != pytest.approx(999999.0, rel=1e-2), (
                "Tenant B spend leaked into Tenant A result"
            )

        keys = [m["label"] for m in result["movers"]]
        assert not any("B Campaign" in k for k in keys)
