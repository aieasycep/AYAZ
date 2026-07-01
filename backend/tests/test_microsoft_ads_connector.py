"""Golden-file tests for MicrosoftAdsConnector.

Follows the fixtures-based testing pattern from test_meta_ads_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded Microsoft Advertising
  CampaignPerformanceReport response (row-based JSON format).
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only pure functions (normalize, _parse_csv_report, capabilities,
  incremental_state) are tested.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Importing the module triggers __init_subclass__ and auto-registers the connector.
from ayaz.connectors import microsoft_ads  # noqa: F401
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.microsoft_ads import MicrosoftAdsConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "microsoft_ads_report.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig with no live credentials."""
    return ConnectorConfig(
        tenant_id="tenant-test-005",
        connected_account_id="conn-msads-001",
        external_account_id="12345678",
        platform_key="microsoft_ads",
        vault_secret_ref="",
        extra={
            "account_id": "12345678",
            "customer_id": "87654321",
            "currency": "GBP",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> MicrosoftAdsConnector:
    return MicrosoftAdsConnector(config=config)


@pytest.fixture()
def fixture_data() -> dict:
    """Raw JSON loaded from the fixture file — mimics a parsed report response."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_data) -> list[dict]:
    """The ``rows`` list from the fixture — rows ready for normalize()."""
    return fixture_data["rows"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_microsoft_ads_connector_is_registered() -> None:
    """MicrosoftAdsConnector must auto-register under 'microsoft_ads'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "microsoft_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("microsoft_ads")
    assert cls is MicrosoftAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: MicrosoftAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "microsoft_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 60


# ── _parse_csv_report() — pure, no network ────────────────────────────────────


def test_parse_csv_report_basic() -> None:
    csv_text = (
        "TimePeriod,CampaignId,CampaignName,Impressions,Clicks,Spend,Conversions\r\n"
        "2024-06-01,720000001,Brand Search,85000,4200,310.75,93\r\n"
        "2024-06-01,720000002,Retargeting,210000,1850,128.40,31\r\n"
    )
    rows = MicrosoftAdsConnector._parse_csv_report(csv_text)
    assert len(rows) == 2
    assert rows[0]["CampaignId"] == "720000001"
    assert rows[0]["Spend"] == "310.75"
    assert rows[1]["CampaignName"] == "Retargeting"


def test_parse_csv_report_skips_empty_time_period() -> None:
    csv_text = (
        "TimePeriod,CampaignId,CampaignName,Impressions,Clicks,Spend,Conversions\r\n"
        "2024-06-01,720000001,Brand Search,85000,4200,310.75,93\r\n"
        ",Total,,370000,6050,439.15,124\r\n"
    )
    rows = MicrosoftAdsConnector._parse_csv_report(csv_text)
    # Summary/total row with blank TimePeriod must be skipped
    assert len(rows) == 1


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: MicrosoftAdsConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per row in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_brand_search_day1(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Golden-file: Brand Search UK on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["TimePeriod"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "12345678"
    assert first.platform == "microsoft_ads"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "720000001"
    assert first.campaign_name == "Brand Search UK"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Golden-file: spend string→Decimal, int impressions/clicks, Decimal conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["TimePeriod"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # Spend "310.75" → Decimal("310.75") in GBP (account currency)
    assert first.cost_raw == Decimal("310.75")
    assert first.cost_ccy == "GBP"
    assert first.impressions == 85000
    assert first.clicks == 4200
    assert first.conversions == Decimal("93")
    # CampaignPerformanceReport does not expose revenue value
    assert first.conversion_value_raw == Decimal("0")
    assert first.conversion_value_ccy == "GBP"


def test_normalize_golden_row2_retargeting_day1(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Golden-file: Retargeting Display on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["TimePeriod"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "720000002"
    assert second.campaign_name == "Retargeting Display"
    assert second.cost_raw == Decimal("128.40")
    assert second.impressions == 210000
    assert second.clicks == 1850
    assert second.conversions == Decimal("31")


def test_normalize_golden_row3_brand_search_day2(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Golden-file: Brand Search UK on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["TimePeriod"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "720000001"
    assert third.cost_raw == Decimal("298.90")
    assert third.impressions == 82400
    assert third.clicks == 4050
    assert third.conversions == Decimal("88")


def test_normalize_golden_row4_zero_conversions(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Golden-file: Retargeting Display on 2024-06-02 — zero conversions."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["TimePeriod"], r["CampaignId"]),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "720000002"
    assert fourth.cost_raw == Decimal("119.20")
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_is_decimal_not_micros(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    """Microsoft Ads Spend is a plain currency string, NOT micros."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw >= Decimal("0")
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks like it was divided by 1e6 — MS Ads Spend is not micros."
            )


def test_normalize_monetary_values_are_decimal(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "microsoft_ads"


def test_normalize_raw_source_preserved(
    connector: MicrosoftAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "TimePeriod" in r.raw_source
        assert "Spend" in r.raw_source


def test_normalize_zero_spend_row(connector: MicrosoftAdsConnector) -> None:
    """A row with Spend '0' must not raise and must yield Decimal('0')."""
    row = {
        "TimePeriod": "2024-06-05",
        "CampaignId": "720000099",
        "CampaignName": "Paused Campaign",
        "Impressions": "0",
        "Clicks": "0",
        "Spend": "0",
        "Conversions": "0",
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_commas_in_number_strings(connector: MicrosoftAdsConnector) -> None:
    """normalize() must strip commas from thousand-separated number strings."""
    row = {
        "TimePeriod": "2024-06-05",
        "CampaignId": "720000088",
        "CampaignName": "High Volume Campaign",
        "Impressions": "1,200,000",
        "Clicks": "45,000",
        "Spend": "12,345.67",
        "Conversions": "1,234",
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.impressions == 1_200_000
    assert r.clicks == 45_000
    assert r.cost_raw == Decimal("12345.67")
    assert r.conversions == Decimal("1234")


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: MicrosoftAdsConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(
    connector: MicrosoftAdsConnector,
) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_raises_without_token(connector: MicrosoftAdsConnector) -> None:
    """discover() requires a live network call — verify it raises without a token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_expected_parts() -> None:
    url = MicrosoftAdsConnector.build_authorization_url(
        client_id="azure-app-id-123",
        redirect_uri="https://example.com/callback",
        state="csrf-ms-456",
    )
    assert "login.microsoftonline.com" in url
    assert "azure-app-id-123" in url
    assert "csrf-ms-456" in url
    assert "msads.manage" in url
