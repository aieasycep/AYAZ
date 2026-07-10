"""Golden-file tests for MetaAdsConnector.

Follows the fixtures-based testing pattern from test_google_ads_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded Meta Insights API response.
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only pure functions (normalize, _extract_action_value, capabilities,
  incremental_state, discover) are tested.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Importing the module triggers __init_subclass__ and auto-registers the connector.
from ayaz.connectors import meta_ads  # noqa: F401
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.meta_ads import MetaAdsConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "meta_ads_insights.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig with no live credentials."""
    return ConnectorConfig(
        tenant_id="tenant-test-002",
        connected_account_id="conn-meta-001",
        external_account_id="123456789",
        platform_key="meta_ads",
        vault_secret_ref="",
        extra={
            "ad_account_id": "123456789",
            "currency": "EUR",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> MetaAdsConnector:
    return MetaAdsConnector(config=config)


@pytest.fixture()
def fixture_data() -> dict:
    """Raw JSON loaded from the fixture file — mimics a real Insights API body."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_data) -> list[dict]:
    """The ``data`` list from the fixture — rows ready for normalize()."""
    return fixture_data["data"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_meta_ads_connector_is_registered() -> None:
    """MetaAdsConnector must auto-register under 'meta_ads'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "meta_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("meta_ads")
    assert cls is MetaAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: MetaAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "meta_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 730
    assert caps.rate_limit_rpm == 200


# ── _extract_action_value() — pure, no network ────────────────────────────────


def test_extract_action_value_found() -> None:
    actions = [
        {"action_type": "link_click", "value": "500"},
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "42"},
    ]
    result = MetaAdsConnector._extract_action_value(
        actions, "offsite_conversion.fb_pixel_purchase"
    )
    assert result == Decimal("42")


def test_extract_action_value_not_found_returns_zero() -> None:
    actions = [{"action_type": "link_click", "value": "500"}]
    result = MetaAdsConnector._extract_action_value(
        actions, "offsite_conversion.fb_pixel_purchase"
    )
    assert result == Decimal("0")


def test_extract_action_value_empty_list_returns_zero() -> None:
    result = MetaAdsConnector._extract_action_value(
        [], "offsite_conversion.fb_pixel_purchase"
    )
    assert result == Decimal("0")


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: MetaAdsConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per row in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_summer_sale_day1(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Golden-file: Summer Sale EMEA on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date_start"], r["campaign_id"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "123456789"
    assert first.platform == "meta_ads"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "23855001001780001"
    assert first.campaign_name == "Summer Sale EMEA"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Golden-file: spend string→Decimal, conversions from actions list."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date_start"], r["campaign_id"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # spend "87.43" → Decimal("87.43"), already in EUR (account currency)
    assert first.cost_raw == Decimal("87.43")
    assert first.cost_ccy == "EUR"
    assert first.impressions == 145_200
    assert first.clicks == 3_840
    # offsite_conversion.fb_pixel_purchase value "62"
    assert first.conversions == Decimal("62")
    assert first.conversion_value_raw == Decimal("1984.50")
    assert first.conversion_value_ccy == "EUR"


def test_normalize_golden_row2_brand_retargeting_day1(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Golden-file: Brand Retargeting EU on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date_start"], r["campaign_id"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "23855001001780002"
    assert second.campaign_name == "Brand Retargeting EU"
    assert second.cost_raw == Decimal("21.10")
    assert second.impressions == 52_000
    assert second.clicks == 890
    assert second.conversions == Decimal("8")
    assert second.conversion_value_raw == Decimal("240.00")


def test_normalize_golden_row3_summer_sale_day2(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Golden-file: Summer Sale EMEA on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date_start"], r["campaign_id"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "23855001001780001"
    assert third.cost_raw == Decimal("83.75")
    assert third.impressions == 138_900
    assert third.clicks == 3_610
    assert third.conversions == Decimal("58")
    assert third.conversion_value_raw == Decimal("1856.00")


def test_normalize_golden_row4_empty_actions(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Golden-file: Brand Retargeting EU on 2024-06-02 — empty actions lists."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date_start"], r["campaign_id"]),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "23855001001780002"
    assert fourth.cost_raw == Decimal("19.90")
    # empty actions → conversions and value must be zero
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_is_decimal_not_micros(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    """Meta spend is a plain currency string, NOT micros — must not divide by 1e6."""
    records = connector.normalize(fixture_rows)
    # If micros division were applied, spend "87.43" would → ~0.000087 not 87.43
    for r in records:
        assert r.cost_raw >= Decimal("0")
        # Sanity: none of the fixture spends are < 0.01 (they are all dollars)
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks like it was divided by 1e6 — Meta spend is not micros."
            )


def test_normalize_monetary_values_are_decimal(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "meta_ads"


def test_normalize_raw_source_preserved(
    connector: MetaAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "date_start" in r.raw_source
        assert "spend" in r.raw_source


def test_normalize_custom_conversion_action_type(config: ConnectorConfig) -> None:
    """Override conversion_action_type via config.extra — connector must respect it."""
    config.extra["conversion_action_type"] = "lead"
    connector = MetaAdsConnector(config=config)
    row = {
        "date_start": "2024-06-01",
        "campaign_id": "999",
        "campaign_name": "Lead Gen",
        "impressions": "10000",
        "clicks": "500",
        "spend": "30.00",
        "actions": [
            {"action_type": "lead", "value": "15"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
        ],
        "action_values": [
            {"action_type": "lead", "value": "0"},
        ],
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    # Must use "lead" action type, not purchase
    assert r.conversions == Decimal("15")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_zero_spend_row(connector: MetaAdsConnector) -> None:
    """A row with spend '0.00' must not raise and must yield Decimal('0')."""
    row = {
        "date_start": "2024-06-05",
        "campaign_id": "777",
        "campaign_name": "Paused Campaign",
        "impressions": "0",
        "clicks": "0",
        "spend": "0.00",
        "actions": [],
        "action_values": [],
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(connector: MetaAdsConnector) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: MetaAdsConnector) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_raises_without_token(connector: MetaAdsConnector) -> None:
    """discover() requires a live network call — verify it raises without a token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── authenticate() — ad_account_id must NOT be required (chicken-and-egg) ─────


def test_authenticate_succeeds_with_access_token_only() -> None:
    """A user fresh out of the OAuth dialog has an access_token but has not
    picked an ad account yet. authenticate() must succeed on access_token
    alone so discover() (the account picker) can run — mirrors
    GoogleAdsConnector.authenticate(), which does not require customer_id.
    """
    config = ConnectorConfig(
        tenant_id="tenant-test-003",
        connected_account_id="conn-meta-002",
        external_account_id="",
        platform_key="meta_ads",
        vault_secret_ref="",
        extra={"access_token": "EAABbbb...longlived"},
    )
    connector = MetaAdsConnector(config=config)
    connector.authenticate()  # must not raise
    assert connector._token() == "EAABbbb...longlived"


def test_authenticate_raises_without_access_token() -> None:
    """access_token is the one credential authenticate() still requires."""
    config = ConnectorConfig(
        tenant_id="tenant-test-004",
        connected_account_id="conn-meta-003",
        external_account_id="",
        platform_key="meta_ads",
        vault_secret_ref="",
        extra={"ad_account_id": "123456789"},  # access_token missing on purpose
    )
    connector = MetaAdsConnector(config=config)
    with pytest.raises(RuntimeError, match="Missing required credentials"):
        connector.authenticate()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_expected_parts() -> None:
    url = MetaAdsConnector.build_authorization_url(
        client_id="test-app-id",
        redirect_uri="https://example.com/callback",
        state="csrf-abc",
    )
    assert "facebook.com/dialog/oauth" in url
    assert "test-app-id" in url
    assert "csrf-abc" in url
    assert "ads_read" in url
