"""Golden-file tests for CriteoConnector.

Follows the fixtures-based testing pattern from test_meta_ads_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded Criteo statistics report response.
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only pure functions (normalize, capabilities, incremental_state) are tested.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Importing the module triggers __init_subclass__ and auto-registers the connector.
from ayaz.connectors import criteo  # noqa: F401
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.criteo import CriteoConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "criteo_stats_report.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig with no live credentials."""
    return ConnectorConfig(
        tenant_id="tenant-test-006",
        connected_account_id="conn-criteo-001",
        external_account_id="78901234",
        platform_key="criteo",
        vault_secret_ref="",
        extra={
            "advertiser_id": "78901234",
            "currency": "EUR",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> CriteoConnector:
    return CriteoConnector(config=config)


@pytest.fixture()
def fixture_data() -> dict:
    """Raw JSON loaded from the fixture file — mimics a Criteo statistics response."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_data) -> list[dict]:
    """The ``rows`` list from the fixture — rows ready for normalize()."""
    return fixture_data["rows"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_criteo_connector_is_registered() -> None:
    """CriteoConnector must auto-register under 'criteo'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "criteo" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("criteo")
    assert cls is CriteoConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: CriteoConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "criteo"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 60


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: CriteoConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per row in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: CriteoConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_campaign1_day1(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 456789001 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["Day"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "78901234"
    assert first.platform == "criteo"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "456789001"
    # Statistics report does not include campaign names inline
    assert first.campaign_name == "(not set)"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Golden-file: AdvertiserCost string→Decimal, Displays→impressions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["Day"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # AdvertiserCost "312.50" → Decimal("312.50") in EUR (account currency)
    assert first.cost_raw == Decimal("312.50")
    assert first.cost_ccy == "EUR"
    # Displays maps to impressions
    assert first.impressions == 95000
    assert first.clicks == 2100
    assert first.conversions == Decimal("45")
    # Revenue not in default stats metric set
    assert first.conversion_value_raw == Decimal("0")
    assert first.conversion_value_ccy == "EUR"


def test_normalize_golden_row2_campaign2_day1(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 456789002 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["Day"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "456789002"
    assert second.cost_raw == Decimal("98.75")
    assert second.impressions == 34000
    assert second.clicks == 780
    assert second.conversions == Decimal("12")


def test_normalize_golden_row3_campaign1_day2(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 456789001 on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["Day"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "456789001"
    assert third.cost_raw == Decimal("301.20")
    assert third.impressions == 91500
    assert third.clicks == 2050
    assert third.conversions == Decimal("41")


def test_normalize_golden_row4_zero_conversions(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 456789002 on 2024-06-02 — zero conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["Day"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "456789002"
    assert fourth.cost_raw == Decimal("91.00")
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_is_decimal_not_micros(
    connector: CriteoConnector, fixture_rows
) -> None:
    """Criteo AdvertiserCost is a plain currency string, NOT micros."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw >= Decimal("0")
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks like it was divided by 1e6 — "
                "Criteo AdvertiserCost is not micros."
            )


def test_normalize_monetary_values_are_decimal(
    connector: CriteoConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: CriteoConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: CriteoConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "criteo"


def test_normalize_raw_source_preserved(
    connector: CriteoConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "Day" in r.raw_source
        assert "AdvertiserCost" in r.raw_source


def test_normalize_displays_maps_to_impressions(
    connector: CriteoConnector,
) -> None:
    """Criteo 'Displays' must map to 'impressions' in UnifiedRecord."""
    row = {
        "AdvertiserId": "78901234",
        "CampaignId": "999000",
        "Day": "2024-06-05",
        "Displays": 50000,
        "Clicks": 1500,
        "AdvertiserCost": "200.00",
        "Conversions": 30,
    }
    records = connector.normalize([row])
    assert records[0].impressions == 50000


def test_normalize_zero_spend_row(connector: CriteoConnector) -> None:
    """A row with AdvertiserCost '0' must not raise and yield Decimal('0')."""
    row = {
        "AdvertiserId": "78901234",
        "CampaignId": "000001",
        "Day": "2024-06-05",
        "Displays": 0,
        "Clicks": 0,
        "AdvertiserCost": "0",
        "Conversions": 0,
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: CriteoConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: CriteoConnector) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_raises_without_token(connector: CriteoConnector) -> None:
    """discover() requires a live network call — verify it raises without a token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── authenticate() — credential validation ────────────────────────────────────


def test_authenticate_raises_with_missing_credentials(
    connector: CriteoConnector,
) -> None:
    """authenticate() must raise RuntimeError when client_id/secret are absent."""
    with pytest.raises(RuntimeError, match="Missing required credentials"):
        connector.authenticate()
