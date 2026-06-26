"""Golden-file tests for GA4Connector.

Follows the fixtures-based testing pattern from test_google_ads_connector.py.

Key design notes:
- GA4 is an analytics source: cost_raw is always Decimal("0").
- clicks is always 0 (sessions != clicks — see connector module docstring).
- GA4 dates are YYYYMMDD strings; normalize() must parse them to date objects.
- No live network calls; pure functions only.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayaz.connectors import ga4  # noqa: F401  — triggers self-registration
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.ga4 import GA4Connector

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ga4_run_report.json"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="tenant-test-003",
        connected_account_id="conn-ga4-001",
        external_account_id="987654321",
        platform_key="ga4",
        vault_secret_ref="",
        extra={
            "property_id": "987654321",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> GA4Connector:
    return GA4Connector(config=config)


@pytest.fixture()
def fixture_body() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_body) -> list[dict]:
    """Flat row dicts produced by _parse_run_report_response()."""
    return GA4Connector._parse_run_report_response(fixture_body)


# ── Registry ──────────────────────────────────────────────────────────────────


def test_ga4_connector_is_registered() -> None:
    """GA4Connector must auto-register under 'ga4'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "ga4" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("ga4")
    assert cls is GA4Connector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: GA4Connector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "ga4"
    assert "daily_channel_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 120


# ── _parse_run_report_response() — pure, no network ──────────────────────────


def test_parse_run_report_response_count(fixture_body) -> None:
    """Must parse all 4 rows from the fixture."""
    rows = GA4Connector._parse_run_report_response(fixture_body)
    assert len(rows) == 4


def test_parse_run_report_response_has_expected_keys(fixture_body) -> None:
    rows = GA4Connector._parse_run_report_response(fixture_body)
    for row in rows:
        assert "date" in row
        assert "sessionDefaultChannelGroup" in row
        assert "sessions" in row
        assert "conversions" in row
        assert "totalRevenue" in row


def test_parse_run_report_response_empty_body() -> None:
    rows = GA4Connector._parse_run_report_response({})
    assert rows == []


def test_parse_run_report_response_empty_rows() -> None:
    body = {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": [{"name": "sessions"}],
        "rows": [],
    }
    rows = GA4Connector._parse_run_report_response(body)
    assert rows == []


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: GA4Connector, fixture_rows) -> None:
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: GA4Connector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_organic_search_day1(
    connector: GA4Connector, fixture_rows
) -> None:
    """Golden-file: Organic Search channel on 2024-06-01 (sorts first alphabetically).

    Sort order by (date, channel): (20240601, Organic Search), (20240601, Paid Search),
    (20240602, Organic Search), (20240602, Paid Search).
    Index 0 is therefore Organic Search on 2024-06-01.
    """
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date"], r["sessionDefaultChannelGroup"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "987654321"
    assert first.platform == "ga4"
    # YYYYMMDD "20240601" → date(2024, 6, 1)
    assert first.date_key == date(2024, 6, 1)
    # channel group mapped to both campaign_id and campaign_name
    assert first.campaign_id == "Organic Search"
    assert first.campaign_name == "Organic Search"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: GA4Connector, fixture_rows
) -> None:
    """Golden-file: analytics-source cost=0, clicks=0, conversions and revenue mapped.

    Row 0 after sort: Organic Search on 2024-06-01.
    """
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date"], r["sessionDefaultChannelGroup"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # Analytics source: no ad spend
    assert first.cost_raw == Decimal("0")
    assert first.cost_ccy == "USD"
    # Sessions ≠ clicks; clicks always 0 for GA4
    assert first.clicks == 0
    # GA4 has no impression count at this query level
    assert first.impressions == 0
    # Organic Search 2024-06-01: conversions "87", totalRevenue "2109.75"
    assert first.conversions == Decimal("87")
    assert first.conversion_value_raw == Decimal("2109.75")
    assert first.conversion_value_ccy == "USD"


def test_normalize_golden_row2_paid_search_day1(
    connector: GA4Connector, fixture_rows
) -> None:
    """Golden-file: Paid Search channel on 2024-06-01 (index 1 after sort)."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date"], r["sessionDefaultChannelGroup"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "Paid Search"
    assert second.cost_raw == Decimal("0")
    assert second.conversions == Decimal("142")
    assert second.conversion_value_raw == Decimal("5684.30")


def test_normalize_golden_row3_organic_search_day2(
    connector: GA4Connector, fixture_rows
) -> None:
    """Golden-file: Organic Search channel on 2024-06-02 (index 2 after sort)."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["date"], r["sessionDefaultChannelGroup"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "Organic Search"
    assert third.cost_raw == Decimal("0")
    assert third.conversions == Decimal("79")
    assert third.conversion_value_raw == Decimal("1890.40")


def test_normalize_cost_is_always_zero(
    connector: GA4Connector, fixture_rows
) -> None:
    """GA4 is an analytics source — cost_raw must be Decimal('0') for every record."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw == Decimal("0"), (
            f"GA4 cost_raw must always be 0 (analytics source); got {r.cost_raw}"
        )


def test_normalize_clicks_is_always_zero(
    connector: GA4Connector, fixture_rows
) -> None:
    """clicks must be 0 for GA4 (sessions != clicks; see module docstring)."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.clicks == 0, (
            f"GA4 clicks must always be 0; got {r.clicks}. "
            "Sessions do not map to ad clicks."
        )


def test_normalize_impressions_is_always_zero(
    connector: GA4Connector, fixture_rows
) -> None:
    """impressions must be 0 for GA4 (no impression metric in this query)."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.impressions == 0


def test_normalize_date_parsed_from_yyyymmdd(
    connector: GA4Connector, fixture_rows
) -> None:
    """GA4 returns dates as YYYYMMDD strings; normalize() must produce date objects."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_monetary_values_are_decimal(
    connector: GA4Connector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_platform_field(
    connector: GA4Connector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "ga4"


def test_normalize_raw_source_preserved(
    connector: GA4Connector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "date" in r.raw_source
        assert "sessionDefaultChannelGroup" in r.raw_source


def test_normalize_zero_conversions_row(connector: GA4Connector) -> None:
    """Edge case: zero conversions and zero revenue must not raise."""
    row = {
        "date": "20240605",
        "sessionDefaultChannelGroup": "Direct",
        "sessions": "1200",
        "conversions": "0",
        "totalRevenue": "0",
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.date_key == date(2024, 6, 5)
    assert r.campaign_id == "Direct"
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_missing_channel_defaults_to_not_set(
    connector: GA4Connector,
) -> None:
    """If sessionDefaultChannelGroup is absent, default to '(not set)'."""
    row = {
        "date": "20240606",
        "sessions": "500",
        "conversions": "10",
        "totalRevenue": "200.00",
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.campaign_id == "(not set)"
    assert r.campaign_name == "(not set)"


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(connector: GA4Connector) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: GA4Connector) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() — no live call ────────────────────────────────────────────────


def test_discover_returns_configured_property(connector: GA4Connector) -> None:
    """discover() returns the configured property without a network call."""
    accounts = connector.discover()
    assert len(accounts) == 1
    acc = accounts[0]
    assert acc["id"] == "987654321"
    assert "currency" in acc


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_scope() -> None:
    url = GA4Connector.build_authorization_url(
        client_id="ga4-client-id",
        redirect_uri="https://example.com/callback",
        state="state-xyz",
    )
    assert "accounts.google.com" in url
    assert "analytics.readonly" in url
    assert "ga4-client-id" in url
    assert "state-xyz" in url
    assert "offline" in url
