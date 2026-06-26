"""Golden-file tests for GoogleAdsConnector.

Follows the fixtures-based testing pattern established in test_sample_connector.py.

- All assertions use explicit golden values — no dynamic computation.
- No live network calls; the fixture is a recorded searchStream response.
- authenticate() / refresh_token() / fetch() network paths are not exercised;
  only the pure functions (normalize, _parse_stream_response, capabilities,
  incremental_state, discover) are tested here.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.google_ads import GoogleAdsConnector

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_ads_search_stream.json"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    """ConnectorConfig for a standalone (non-MCC) account with no live creds."""
    return ConnectorConfig(
        tenant_id="tenant-test-001",
        connected_account_id="conn-account-001",
        external_account_id="1234567890",
        platform_key="google_ads",
        vault_secret_ref="",
        extra={
            # No live secrets; tests never call authenticate() or fetch()
            "customer_id": "1234567890",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> GoogleAdsConnector:
    return GoogleAdsConnector(config=config)


@pytest.fixture()
def fixture_batches() -> list[dict]:
    """Raw JSON loaded from the fixture file — mimics a real searchStream body."""
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_batches) -> list[dict]:
    """Flat list of row dicts, as produced by _parse_stream_response()."""
    return GoogleAdsConnector._parse_stream_response(fixture_batches)


# ── Registry ──────────────────────────────────────────────────────────────────


def test_google_ads_connector_is_registered() -> None:
    """GoogleAdsConnector must auto-register under 'google_ads' via __init_subclass__."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "google_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("google_ads")
    assert cls is GoogleAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: GoogleAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "google_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 60


# ── _parse_stream_response() — pure, no network ───────────────────────────────


def test_parse_stream_response_flattens_batches(fixture_batches) -> None:
    """_parse_stream_response() must flatten all batches into one flat list."""
    rows = GoogleAdsConnector._parse_stream_response(fixture_batches)
    # Fixture has 2 batches: first with 2 rows, second with 1 row → 3 total
    assert len(rows) == 3


def test_parse_stream_response_row_has_required_keys(fixture_batches) -> None:
    rows = GoogleAdsConnector._parse_stream_response(fixture_batches)
    for row in rows:
        assert "campaign" in row
        assert "metrics" in row
        assert "segments" in row


def test_parse_stream_response_empty_body() -> None:
    """An empty batch list must return an empty row list without raising."""
    rows = GoogleAdsConnector._parse_stream_response([])
    assert rows == []


def test_parse_stream_response_batch_with_no_results() -> None:
    rows = GoogleAdsConnector._parse_stream_response([{"results": []}])
    assert rows == []


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: GoogleAdsConnector, fixture_rows) -> None:
    """normalize() must return one UnifiedRecord per row in the fixture."""
    records = connector.normalize(fixture_rows)
    assert len(records) == 3


def test_normalize_returns_unified_records(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """Golden-file: first row — Summer Promo 2024 on 2024-06-01."""
    # Sort by (date, campaign_id) for stable ordering
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["segments"]["date"], r["campaign"]["id"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "1234567890"
    assert first.platform == "google_ads"
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "111000001"
    assert first.campaign_name == "Summer Promo 2024"
    # Campaign-level query; ad-set/ad grain is not available
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """Golden-file: cost_micros→cost_raw conversion and metric types for row 1."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["segments"]["date"], r["campaign"]["id"]),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # 25_000_000 micros → Decimal("25")
    assert first.cost_raw == Decimal("25")
    assert first.cost_ccy == "USD"
    assert first.impressions == 82_000
    assert first.clicks == 1_540
    assert first.conversions == Decimal("18")
    assert first.conversion_value_raw == Decimal("540.0")
    assert first.conversion_value_ccy == "USD"


def test_normalize_golden_row2(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """Golden-file: second row sorted by (date, campaign_id) — Brand Awareness Q2 on 2024-06-01.

    Sort order: (2024-06-01, 111000001), (2024-06-01, 111000002), (2024-06-02, 111000001).
    Index 1 is therefore Brand Awareness Q2 on 2024-06-01.
    """
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["segments"]["date"], r["campaign"]["id"]),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "111000002"
    assert second.campaign_name == "Brand Awareness Q2"
    # 8_750_000 / 1_000_000 = 8.75
    assert second.cost_raw == Decimal("8.75")
    assert second.impressions == 310_000
    assert second.clicks == 2_100
    assert second.conversions == Decimal("0")
    assert second.conversion_value_raw == Decimal("0.0")


def test_normalize_golden_row3_summer_promo_day2(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """Golden-file: third row sorted by (date, campaign_id) — Summer Promo 2024 on 2024-06-02.

    Sort order: (2024-06-01, 111000001), (2024-06-01, 111000002), (2024-06-02, 111000001).
    Index 2 is therefore Summer Promo 2024 on 2024-06-02.
    """
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (r["segments"]["date"], r["campaign"]["id"]),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "111000001"
    assert third.campaign_name == "Summer Promo 2024"
    # 31_500_000 / 1_000_000 = 31.5
    assert third.cost_raw == Decimal("31.5")
    assert third.impressions == 91_000
    assert third.clicks == 1_780
    assert third.conversions == Decimal("24")
    assert third.conversion_value_raw == Decimal("720.0")


def test_normalize_zero_cost_row(connector: GoogleAdsConnector) -> None:
    """Edge case: a row with zero costMicros must not raise and must yield Decimal('0')."""
    zero_row = {
        "campaign": {"id": "999", "name": "Zero Cost Campaign", "status": "ENABLED"},
        "metrics": {
            "impressions": "5000",
            "clicks": "100",
            "costMicros": "0",
            "conversions": 0.0,
            "conversionsValue": 0.0,
        },
        "segments": {"date": "2024-06-03"},
    }
    records = connector.normalize([zero_row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("0")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_missing_optional_metrics(connector: GoogleAdsConnector) -> None:
    """Edge case: missing conversions / conversionsValue keys default to zero gracefully."""
    sparse_row = {
        "campaign": {"id": "888", "name": "Sparse Campaign", "status": "ENABLED"},
        "metrics": {
            "impressions": "1000",
            "clicks": "50",
            "costMicros": "5000000",
            # conversions and conversionsValue omitted
        },
        "segments": {"date": "2024-06-04"},
    }
    records = connector.normalize([sparse_row])
    assert len(records) == 1
    r = records[0]
    assert r.cost_raw == Decimal("5")
    assert r.conversions == Decimal("0")
    assert r.conversion_value_raw == Decimal("0")


def test_normalize_monetary_values_are_decimal(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """All monetary fields must be Decimal, never float."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal), "cost_raw must be Decimal"
        assert isinstance(r.conversions, Decimal), "conversions must be Decimal"
        assert isinstance(r.conversion_value_raw, Decimal), (
            "conversion_value_raw must be Decimal"
        )


def test_normalize_date_is_date_object(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """date_key must be a datetime.date instance, not a string or datetime."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date), "date_key must be datetime.date"


def test_normalize_raw_source_preserved(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """normalize() must attach the original row dict as raw_source for lineage."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "campaign" in r.raw_source
        assert "metrics" in r.raw_source
        assert "segments" in r.raw_source


def test_normalize_platform_field(
    connector: GoogleAdsConnector, fixture_rows
) -> None:
    """platform field must equal 'google_ads' on every record."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "google_ads"


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: GoogleAdsConnector,
) -> None:
    """incremental_state() returns empty dict before any fetch."""
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: GoogleAdsConnector) -> None:
    """incremental_state() always returns a dict."""
    state = connector.incremental_state()
    assert isinstance(state, dict)


# ── discover() — standalone account (no live call) ────────────────────────────


def test_discover_standalone_account(connector: GoogleAdsConnector) -> None:
    """discover() with no login_customer_id returns a single local entry, no network."""
    accounts = connector.discover()
    assert len(accounts) == 1
    account = accounts[0]
    assert "id" in account
    assert "name" in account
    assert "currency" in account
    assert account["id"] == "1234567890"
    assert account["currency"] == "USD"


# ── build_authorization_url() — pure, no network ─────────────────────────────


def test_build_authorization_url_contains_scope() -> None:
    """build_authorization_url() is a pure helper; must embed the adwords scope."""
    url = GoogleAdsConnector.build_authorization_url(
        client_id="test-client-id",
        redirect_uri="https://example.com/callback",
        state="csrf-token",
    )
    assert "accounts.google.com" in url
    assert "adwords" in url
    assert "test-client-id" in url
    assert "csrf-token" in url
    assert "offline" in url
