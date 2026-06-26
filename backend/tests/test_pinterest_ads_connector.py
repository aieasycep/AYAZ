"""Golden-file tests for PinterestAdsConnector.

Follows the fixtures-based testing pattern from test_meta_ads_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded Pinterest campaign analytics response.
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only pure functions (normalize, _extract_spend, capabilities, incremental_state)
  are tested.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Importing the module triggers __init_subclass__ and auto-registers the connector.
from ayaz.connectors import pinterest_ads  # noqa: F401
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.pinterest_ads import PinterestAdsConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "pinterest_ads_analytics.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig with no live credentials."""
    return ConnectorConfig(
        tenant_id="tenant-test-007",
        connected_account_id="conn-pinterest-001",
        external_account_id="549755885175",
        platform_key="pinterest_ads",
        vault_secret_ref="",
        extra={
            "ad_account_id": "549755885175",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> PinterestAdsConnector:
    return PinterestAdsConnector(config=config)


@pytest.fixture()
def fixture_rows() -> list[dict]:
    """Raw JSON loaded from the fixture file — mimics a Pinterest analytics response."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Registry ──────────────────────────────────────────────────────────────────


def test_pinterest_ads_connector_is_registered() -> None:
    """PinterestAdsConnector must auto-register under 'pinterest_ads'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "pinterest_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("pinterest_ads")
    assert cls is PinterestAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: PinterestAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "pinterest_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    # Pinterest analytics API: 90-day max window per request
    assert caps.max_backfill_days == 90
    assert caps.rate_limit_rpm == 60


# ── _extract_spend() — pure, no network ──────────────────────────────────────


def test_extract_spend_from_dollar_field() -> None:
    """SPEND_IN_DOLLAR is preferred over SPEND_IN_MICRO_DOLLAR."""
    row = {"SPEND_IN_DOLLAR": "145.72", "SPEND_IN_MICRO_DOLLAR": 145720000}
    result = PinterestAdsConnector._extract_spend(row)
    assert result == Decimal("145.72")


def test_extract_spend_fallback_to_micro_dollar() -> None:
    """If SPEND_IN_DOLLAR is absent, fall back to SPEND_IN_MICRO_DOLLAR / 1e6."""
    row = {"SPEND_IN_MICRO_DOLLAR": 145720000}
    result = PinterestAdsConnector._extract_spend(row)
    assert result == Decimal("145.72")


def test_extract_spend_micro_dollar_division_exact() -> None:
    """Micro-dollar fallback must divide by exactly 1,000,000 (no float rounding)."""
    row = {"SPEND_IN_MICRO_DOLLAR": 1000000}
    result = PinterestAdsConnector._extract_spend(row)
    assert result == Decimal("1")


def test_extract_spend_missing_both_fields_returns_zero() -> None:
    result = PinterestAdsConnector._extract_spend({})
    assert result == Decimal("0")


def test_extract_spend_dollar_none_falls_back_to_micro() -> None:
    """SPEND_IN_DOLLAR=None must fall back to SPEND_IN_MICRO_DOLLAR."""
    row = {"SPEND_IN_DOLLAR": None, "SPEND_IN_MICRO_DOLLAR": 63180000}
    result = PinterestAdsConnector._extract_spend(row)
    assert result == Decimal("63.18")


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: PinterestAdsConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per row in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_campaign1_day1(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 549755885175 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["DATE"], r["CAMPAIGN_ID"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "549755885175"
    assert first.platform == "pinterest_ads"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "549755885175"
    # Analytics endpoint does not include campaign names
    assert first.campaign_name == "(not set)"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Golden-file: SPEND_IN_DOLLAR string→Decimal, IMPRESSION_1, PIN_CLICK."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["DATE"], r["CAMPAIGN_ID"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # SPEND_IN_DOLLAR "145.72" → Decimal("145.72"), already in USD
    assert first.cost_raw == Decimal("145.72")
    assert first.cost_ccy == "USD"
    # IMPRESSION_1 maps to impressions
    assert first.impressions == 98000
    # PIN_CLICK maps to clicks
    assert first.clicks == 2340
    assert first.conversions == Decimal("52")
    # Pinterest analytics does not expose purchase revenue value
    assert first.conversion_value_raw == Decimal("0")
    assert first.conversion_value_ccy == "USD"


def test_normalize_golden_row2_campaign2_day1(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 549755885176 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["DATE"], r["CAMPAIGN_ID"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "549755885176"
    assert second.cost_raw == Decimal("63.18")
    assert second.impressions == 41500
    assert second.clicks == 890
    assert second.conversions == Decimal("14")


def test_normalize_golden_row3_campaign1_day2(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 549755885175 on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["DATE"], r["CAMPAIGN_ID"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "549755885175"
    assert third.cost_raw == Decimal("138.44")
    assert third.impressions == 94200
    assert third.clicks == 2190
    assert third.conversions == Decimal("48")


def test_normalize_golden_row4_zero_conversions(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 549755885176 on 2024-06-02 — zero conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["DATE"], r["CAMPAIGN_ID"]),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "549755885176"
    assert fourth.cost_raw == Decimal("59.90")
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_uses_dollar_not_micros(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    """Connector uses SPEND_IN_DOLLAR — values must not look like micro-divided amounts."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw >= Decimal("0")
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks unexpectedly small — check that SPEND_IN_DOLLAR "
                "is used rather than SPEND_IN_MICRO_DOLLAR / 1e6."
            )


def test_normalize_monetary_values_are_decimal(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "pinterest_ads"


def test_normalize_raw_source_preserved(
    connector: PinterestAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "DATE" in r.raw_source
        assert "SPEND_IN_DOLLAR" in r.raw_source


def test_normalize_micro_dollar_fallback(connector: PinterestAdsConnector) -> None:
    """If SPEND_IN_DOLLAR absent, connector must use SPEND_IN_MICRO_DOLLAR / 1e6."""
    row = {
        "CAMPAIGN_ID": "111111",
        "DATE": "2024-06-05",
        "SPEND_IN_MICRO_DOLLAR": 75500000,
        "IMPRESSION_1": 50000,
        "PIN_CLICK": 1200,
        "OUTBOUND_CLICK": 1000,
        "TOTAL_CONVERSIONS": 20,
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    # 75_500_000 / 1_000_000 = 75.5
    assert r.cost_raw == Decimal("75.5")


def test_normalize_zero_spend_row(connector: PinterestAdsConnector) -> None:
    """A row with SPEND_IN_DOLLAR '0.00' must not raise and yield Decimal('0')."""
    row = {
        "CAMPAIGN_ID": "000000",
        "DATE": "2024-06-05",
        "SPEND_IN_DOLLAR": "0.00",
        "IMPRESSION_1": 0,
        "PIN_CLICK": 0,
        "OUTBOUND_CLICK": 0,
        "TOTAL_CONVERSIONS": 0,
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_impression_1_maps_to_impressions(
    connector: PinterestAdsConnector,
) -> None:
    """IMPRESSION_1 column must map to the 'impressions' field."""
    row = {
        "CAMPAIGN_ID": "222222",
        "DATE": "2024-06-06",
        "SPEND_IN_DOLLAR": "50.00",
        "IMPRESSION_1": 75000,
        "PIN_CLICK": 1500,
        "OUTBOUND_CLICK": 1200,
        "TOTAL_CONVERSIONS": 30,
    }
    records = connector.normalize([row])
    assert records[0].impressions == 75000


def test_normalize_pin_click_maps_to_clicks(
    connector: PinterestAdsConnector,
) -> None:
    """PIN_CLICK column must map to the 'clicks' field."""
    row = {
        "CAMPAIGN_ID": "333333",
        "DATE": "2024-06-06",
        "SPEND_IN_DOLLAR": "25.00",
        "IMPRESSION_1": 20000,
        "PIN_CLICK": 850,
        "OUTBOUND_CLICK": 700,
        "TOTAL_CONVERSIONS": 12,
    }
    records = connector.normalize([row])
    assert records[0].clicks == 850


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: PinterestAdsConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(
    connector: PinterestAdsConnector,
) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_raises_without_token(connector: PinterestAdsConnector) -> None:
    """discover() requires a live network call — verify it raises without a token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_expected_parts() -> None:
    url = PinterestAdsConnector.build_authorization_url(
        client_id="pinterest-app-id",
        redirect_uri="https://example.com/callback",
        state="csrf-pin-789",
    )
    assert "pinterest.com/oauth/" in url
    assert "pinterest-app-id" in url
    assert "csrf-pin-789" in url
    assert "ads%3Aread" in url or "ads:read" in url
