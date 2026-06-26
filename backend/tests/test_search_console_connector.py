"""Golden-file tests for SearchConsoleConnector.

Follows the fixtures-based testing pattern from test_google_ads_connector.py.

Key design notes:
- Search Console is an organic analytics source: cost_raw is always Decimal("0").
- conversions and conversion_value_raw are always Decimal("0").
- clicks and impressions map directly (organic clicks and organic impressions).
- campaign_id / campaign_name are always "(not set)" — no campaign structure.
- No live network calls; pure functions only.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayaz.connectors import search_console  # noqa: F401 — triggers self-registration
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.search_console import SearchConsoleConnector

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "search_console_search_analytics.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="tenant-test-004",
        connected_account_id="conn-sc-001",
        external_account_id="https://example.com/",
        platform_key="search_console",
        vault_secret_ref="",
        extra={
            "site_url": "https://example.com/",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> SearchConsoleConnector:
    return SearchConsoleConnector(config=config)


@pytest.fixture()
def fixture_body() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_body) -> list[dict]:
    """The ``rows`` list from the fixture — ready for normalize()."""
    return fixture_body["rows"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_search_console_connector_is_registered() -> None:
    """SearchConsoleConnector must auto-register under 'search_console'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "search_console" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("search_console")
    assert cls is SearchConsoleConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: SearchConsoleConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "search_console"
    assert "daily_search_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 480
    assert caps.rate_limit_rpm == 200


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: SearchConsoleConnector, fixture_rows) -> None:
    records = connector.normalize(fixture_rows)
    assert len(records) == 3


def test_normalize_returns_unified_records(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_day1(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Golden-file: 2024-06-01 organic search metrics."""
    # Fixture rows are already in date order
    records = connector.normalize(fixture_rows)

    first = records[0]
    assert first.external_account_id == "https://example.com/"
    assert first.platform == "search_console"
    assert first.date_key == date(2024, 6, 1)
    # No campaign structure in Search Console
    assert first.campaign_id == "(not set)"
    assert first.campaign_name == "(not set)"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_clicks_and_impressions_row1(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Golden-file: clicks and impressions map directly from the API."""
    records = connector.normalize(fixture_rows)

    first = records[0]
    assert first.clicks == 3_210
    assert first.impressions == 84_500


def test_normalize_golden_row2_day2(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Golden-file: 2024-06-02."""
    records = connector.normalize(fixture_rows)

    second = records[1]
    assert second.date_key == date(2024, 6, 2)
    assert second.clicks == 3_580
    assert second.impressions == 89_200


def test_normalize_golden_row3_day3(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Golden-file: 2024-06-03."""
    records = connector.normalize(fixture_rows)

    third = records[2]
    assert third.date_key == date(2024, 6, 3)
    assert third.clicks == 2_940
    assert third.impressions == 76_800


def test_normalize_cost_is_always_zero(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Search Console is an organic source — cost_raw must be Decimal('0') always."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.cost_raw == Decimal("0"), (
            f"SC cost_raw must always be 0; got {r.cost_raw}"
        )


def test_normalize_conversions_always_zero(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """Search Console has no conversion signal — both conversion fields must be 0."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.conversions == Decimal("0")
        assert r.conversion_value_raw == Decimal("0")


def test_normalize_monetary_values_are_decimal(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "search_console"


def test_normalize_raw_source_preserved_with_channel(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """raw_source must be non-None and include the injected _channel label."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "keys" in r.raw_source
        assert r.raw_source.get("_channel") == "organic_search"


def test_normalize_zero_clicks_and_impressions_row(
    connector: SearchConsoleConnector,
) -> None:
    """Edge case: zero clicks and impressions must not raise."""
    row = {
        "keys": ["2024-06-10"],
        "clicks": 0,
        "impressions": 0,
        "ctr": 0.0,
        "position": 0.0,
    }
    records = connector.normalize([row])
    assert len(records) == 1
    r = records[0]
    assert r.date_key == date(2024, 6, 10)
    assert r.clicks == 0
    assert r.impressions == 0
    assert r.cost_raw == Decimal("0")


def test_normalize_ctr_and_position_not_mapped(
    connector: SearchConsoleConnector, fixture_rows
) -> None:
    """CTR and position are not mapped to UnifiedRecord — they stay in raw_source."""
    records = connector.normalize(fixture_rows)
    for r in records:
        # CTR and position are derived / non-schema; they exist in raw_source only
        assert "ctr" in r.raw_source
        assert "position" in r.raw_source


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: SearchConsoleConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: SearchConsoleConnector) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── discover() — requires live call ──────────────────────────────────────────


def test_discover_raises_without_token(connector: SearchConsoleConnector) -> None:
    """discover() issues a live call — must raise without an access token."""
    with pytest.raises(RuntimeError, match="No access token"):
        connector.discover()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_scope() -> None:
    url = SearchConsoleConnector.build_authorization_url(
        client_id="sc-client-id",
        redirect_uri="https://example.com/callback",
        state="state-123",
    )
    assert "accounts.google.com" in url
    assert "webmasters.readonly" in url
    assert "sc-client-id" in url
    assert "state-123" in url
    assert "offline" in url
