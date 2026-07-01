"""Golden-file tests for LinkedInAdsConnector.

Follows the fixtures-based testing pattern from test_meta_ads_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded LinkedIn adAnalytics response.
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only pure functions (normalize, _parse_date_from_range, _extract_campaign_id,
  capabilities, incremental_state) are tested.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Importing the module triggers __init_subclass__ and auto-registers the connector.
from ayaz.connectors import linkedin_ads  # noqa: F401
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.linkedin_ads import LinkedInAdsConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "linkedin_ads_analytics.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig with no live credentials."""
    return ConnectorConfig(
        tenant_id="tenant-test-004",
        connected_account_id="conn-li-001",
        external_account_id="503887890",
        platform_key="linkedin_ads",
        vault_secret_ref="",
        extra={
            "ad_account_id": "503887890",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> LinkedInAdsConnector:
    return LinkedInAdsConnector(config=config)


@pytest.fixture()
def fixture_data() -> dict:
    """Raw JSON loaded from the fixture file — mimics a real adAnalytics response."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_data) -> list[dict]:
    """The ``elements`` list from the fixture — rows ready for normalize()."""
    return fixture_data["elements"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_linkedin_ads_connector_is_registered() -> None:
    """LinkedInAdsConnector must auto-register under 'linkedin_ads'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "linkedin_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("linkedin_ads")
    assert cls is LinkedInAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: LinkedInAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "linkedin_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 60


# ── _parse_date_from_range() — pure, no network ───────────────────────────────


def test_parse_date_from_range_basic() -> None:
    date_range = {"start": {"year": 2024, "month": 6, "day": 1}}
    result = LinkedInAdsConnector._parse_date_from_range(date_range)
    assert result == date(2024, 6, 1)


def test_parse_date_from_range_missing_start_returns_epoch() -> None:
    result = LinkedInAdsConnector._parse_date_from_range({})
    assert result == date(1970, 1, 1)


# ── _extract_campaign_id() — pure, no network ─────────────────────────────────


def test_extract_campaign_id_strips_urn_prefix() -> None:
    pivot = ["urn:li:sponsoredCampaign:310000001"]
    assert LinkedInAdsConnector._extract_campaign_id(pivot) == "310000001"


def test_extract_campaign_id_empty_returns_not_set() -> None:
    assert LinkedInAdsConnector._extract_campaign_id([]) == "(not set)"


def test_extract_campaign_id_malformed_urn_returns_last_segment() -> None:
    pivot = ["urn:li:sponsoredCampaign:999888777"]
    assert LinkedInAdsConnector._extract_campaign_id(pivot) == "999888777"


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: LinkedInAdsConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per element in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_campaign1_day1(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 310000001 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dateRange"]["start"]["year"],
            r["dateRange"]["start"]["month"],
            r["dateRange"]["start"]["day"],
            r["pivotValues"][0],
        ),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "503887890"
    assert first.platform == "linkedin_ads"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "310000001"
    # Campaign name not returned by adAnalytics; must be "(not set)"
    assert first.campaign_name == "(not set)"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """Golden-file: spend string→Decimal, impressions, clicks, conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dateRange"]["start"]["year"],
            r["dateRange"]["start"]["month"],
            r["dateRange"]["start"]["day"],
            r["pivotValues"][0],
        ),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # costInLocalCurrency "245.80" → Decimal("245.80"), already in USD
    assert first.cost_raw == Decimal("245.80")
    assert first.cost_ccy == "USD"
    assert first.impressions == 112400
    assert first.clicks == 3870
    assert first.conversions == Decimal("74")
    # LinkedIn adAnalytics has no purchase value metric
    assert first.conversion_value_raw == Decimal("0")
    assert first.conversion_value_ccy == "USD"


def test_normalize_golden_row2_campaign2_day1(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 310000002 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dateRange"]["start"]["year"],
            r["dateRange"]["start"]["month"],
            r["dateRange"]["start"]["day"],
            r["pivotValues"][0],
        ),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "310000002"
    assert second.cost_raw == Decimal("89.15")
    assert second.impressions == 43200
    assert second.clicks == 980
    assert second.conversions == Decimal("18")


def test_normalize_golden_row3_campaign1_day2(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 310000001 on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dateRange"]["start"]["year"],
            r["dateRange"]["start"]["month"],
            r["dateRange"]["start"]["day"],
            r["pivotValues"][0],
        ),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "310000001"
    assert third.cost_raw == Decimal("231.50")
    assert third.impressions == 108900
    assert third.clicks == 3710
    assert third.conversions == Decimal("69")


def test_normalize_golden_row4_zero_conversions(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """Golden-file: Campaign 310000002 on 2024-06-02 — zero conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dateRange"]["start"]["year"],
            r["dateRange"]["start"]["month"],
            r["dateRange"]["start"]["day"],
            r["pivotValues"][0],
        ),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "310000002"
    assert fourth.cost_raw == Decimal("82.40")
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_is_decimal_not_micros(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    """LinkedIn spend is a plain currency string, NOT micros — must not divide by 1e6."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw >= Decimal("0")
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks like it was divided by 1e6 — LinkedIn spend is not micros."
            )


def test_normalize_monetary_values_are_decimal(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "linkedin_ads"


def test_normalize_raw_source_preserved(
    connector: LinkedInAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "dateRange" in r.raw_source
        assert "costInLocalCurrency" in r.raw_source


def test_normalize_zero_spend_row(connector: LinkedInAdsConnector) -> None:
    """A row with costInLocalCurrency '0.00' must not raise and yield Decimal('0')."""
    row = {
        "dateRange": {"start": {"year": 2024, "month": 6, "day": 5}},
        "pivotValues": ["urn:li:sponsoredCampaign:999"],
        "costInLocalCurrency": "0.00",
        "impressions": 0,
        "clicks": 0,
        "externalWebsiteConversions": 0,
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_missing_pivot_values(connector: LinkedInAdsConnector) -> None:
    """A row with empty pivotValues must yield campaign_id='(not set)'."""
    row = {
        "dateRange": {"start": {"year": 2024, "month": 6, "day": 5}},
        "pivotValues": [],
        "costInLocalCurrency": "10.00",
        "impressions": 100,
        "clicks": 5,
        "externalWebsiteConversions": 1,
    }
    records = connector.normalize([row])
    assert records[0].campaign_id == "(not set)"


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: LinkedInAdsConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(
    connector: LinkedInAdsConnector,
) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_raises_without_token(connector: LinkedInAdsConnector) -> None:
    """discover() requires a live network call — verify it raises without a token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_expected_parts() -> None:
    url = LinkedInAdsConnector.build_authorization_url(
        client_id="test-client-id",
        redirect_uri="https://example.com/callback",
        state="csrf-xyz",
    )
    assert "linkedin.com/oauth/v2/authorization" in url
    assert "test-client-id" in url
    assert "csrf-xyz" in url
    assert "r_ads_reporting" in url
