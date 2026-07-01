"""Golden-file tests for SampleConnector.

This module establishes the fixtures-based testing pattern that ALL future
connector implementations must follow:

1. A ``fixtures/<platform>_metrics.json`` file records a realistic sample of
   the platform's raw API response.
2. ``normalize()`` maps that raw response to ``UnifiedRecord``s.
3. This test asserts the mapping is correct — acting as a regression guard
   against accidental field-mapping breakage.

When adding a new connector:
- Copy the structure of these tests.
- Update the fixture file alongside any mapping changes.
- Keep the golden values explicit (no dynamic computation in assertions).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.sample import SampleConnector

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_metrics.json"

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def connector() -> SampleConnector:
    """Return a SampleConnector pointed at the test fixture file."""
    config = ConnectorConfig(
        tenant_id="tenant-test-001",
        connected_account_id="account-test-001",
        external_account_id="ACC-001",
        platform_key="sample",
        extra={"fixture_path": str(FIXTURE_PATH)},
    )
    return SampleConnector(config=config)


# ── Registry tests ────────────────────────────────────────────────────────────


def test_sample_connector_is_registered() -> None:
    """SampleConnector must auto-register itself via __init_subclass__."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "sample" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("sample")
    assert cls is SampleConnector


# ── Capabilities tests ────────────────────────────────────────────────────────


def test_capabilities(connector: SampleConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "sample"
    assert "daily_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"


# ── fetch() tests ─────────────────────────────────────────────────────────────


def test_fetch_full_range(connector: SampleConnector) -> None:
    """fetch() with a wide range returns all fixture rows."""
    rows = connector.fetch(
        stream="daily_metrics",
        since=date(2024, 1, 1),
        until=date(2024, 12, 31),
    )
    assert len(rows) == 3  # fixture has 3 rows


def test_fetch_narrow_range(connector: SampleConnector) -> None:
    """fetch() filters rows outside the requested date range."""
    rows = connector.fetch(
        stream="daily_metrics",
        since=date(2024, 3, 16),
        until=date(2024, 3, 16),
    )
    # Only one row has date 2024-03-16
    assert len(rows) == 1
    assert rows[0]["date"] == "2024-03-16"


def test_fetch_empty_range(connector: SampleConnector) -> None:
    """fetch() returns empty list when no rows fall in the date window."""
    rows = connector.fetch(
        stream="daily_metrics",
        since=date(2025, 1, 1),
        until=date(2025, 1, 31),
    )
    assert rows == []


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: SampleConnector) -> None:
    """normalize() produces one UnifiedRecord per raw row."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    records = connector.normalize(raw)
    assert len(records) == 3


def test_normalize_returns_unified_records(connector: SampleConnector) -> None:
    """normalize() returns a list of UnifiedRecord instances."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    records = connector.normalize(raw)
    for record in records:
        assert isinstance(record, UnifiedRecord)


def test_normalize_first_row_golden(connector: SampleConnector) -> None:
    """Golden-file: assert exact field values for the first fixture row.

    This is the primary regression guard — if the field mapping changes,
    this test fails and forces explicit sign-off on the change.
    """
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    # Sort by (date, campaign_id) to ensure stable ordering
    raw_sorted = sorted(raw, key=lambda r: (r["date"], r["campaign_id"]))
    records = connector.normalize(raw_sorted)

    first = records[0]
    assert first.external_account_id == "ACC-001"
    assert first.platform == "sample"
    assert first.date_key == date(2024, 3, 15)
    assert first.campaign_id == "CAMP-100"
    assert first.campaign_name == "Spring Sale 2024"
    assert first.adset_id == "ADSET-200"
    assert first.adset_name == "Remarketing 25-44"
    assert first.ad_id == "AD-300"
    assert first.ad_name == "Banner v2"


def test_normalize_metrics_golden(connector: SampleConnector) -> None:
    """Golden-file: numeric metric values are mapped and typed correctly."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    raw_sorted = sorted(raw, key=lambda r: (r["date"], r["campaign_id"]))
    records = connector.normalize(raw_sorted)

    first = records[0]
    assert first.impressions == 150_000
    assert first.clicks == 3_200
    assert first.cost_raw == Decimal("1280.50")
    assert first.cost_ccy == "USD"
    assert first.conversions == Decimal("48.0")
    assert first.conversion_value_raw == Decimal("9600.00")
    assert first.conversion_value_ccy == "USD"


def test_normalize_second_row_golden(connector: SampleConnector) -> None:
    """Golden-file: second row (2024-03-16) maps correctly."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    raw_sorted = sorted(raw, key=lambda r: (r["date"], r["campaign_id"]))
    records = connector.normalize(raw_sorted)

    second = records[1]  # CAMP-101 on 2024-03-15
    assert second.campaign_id == "CAMP-101"
    assert second.campaign_name == "Brand Awareness"
    assert second.impressions == 500_000
    assert second.clicks == 1_800
    assert second.cost_raw == Decimal("750.00")
    assert second.conversions == Decimal("0.0")
    assert second.conversion_value_raw == Decimal("0.00")


def test_normalize_monetary_values_are_decimal(connector: SampleConnector) -> None:
    """All monetary fields must be Decimal, never float, to avoid rounding errors."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    records = connector.normalize(raw)
    for r in records:
        assert isinstance(r.cost_raw, Decimal), "cost_raw must be Decimal"
        assert isinstance(r.conversions, Decimal), "conversions must be Decimal"
        assert isinstance(r.conversion_value_raw, Decimal), (
            "conversion_value_raw must be Decimal"
        )


def test_normalize_date_is_date_object(connector: SampleConnector) -> None:
    """date_key must be a ``datetime.date`` — not a string or datetime."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    records = connector.normalize(raw)
    for r in records:
        assert isinstance(r.date_key, date), "date_key must be datetime.date"


def test_normalize_raw_source_preserved(connector: SampleConnector) -> None:
    """normalize() attaches raw_source for lineage / debugging."""
    raw = connector.fetch("daily_metrics", date(2024, 1, 1), date(2024, 12, 31))
    records = connector.normalize(raw)
    for r in records:
        assert r.raw_source is not None
        assert "account_id" in r.raw_source


# ── incremental_state() tests ─────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(connector: SampleConnector) -> None:
    """incremental_state() returns empty dict before any fetch."""
    assert connector.incremental_state() == {}


def test_incremental_state_after_fetch(connector: SampleConnector) -> None:
    """incremental_state() returns the latest date seen after a fetch."""
    connector.fetch("daily_metrics", date(2024, 3, 15), date(2024, 3, 16))
    state = connector.incremental_state()
    assert "daily_metrics" in state
    # Latest date in the fetched window is 2024-03-16
    assert state["daily_metrics"] == "2024-03-16"


# ── discover() test ───────────────────────────────────────────────────────────


def test_discover(connector: SampleConnector) -> None:
    """discover() returns at least one account entry with id and name."""
    accounts = connector.discover()
    assert len(accounts) >= 1
    account = accounts[0]
    assert "id" in account
    assert "name" in account


# ── authenticate / refresh_token (no-op smoke tests) ─────────────────────────


def test_authenticate_noop(connector: SampleConnector) -> None:
    """authenticate() must not raise for the sample connector."""
    connector.authenticate()  # should not raise


def test_refresh_token_noop(connector: SampleConnector) -> None:
    """refresh_token() must not raise for the sample connector."""
    connector.refresh_token()  # should not raise
