"""Golden-file tests for TikTokAdsConnector.

Follows the fixtures-based testing pattern from test_google_ads_connector.py.

Key design notes:
- TikTok spend is a float-string in account currency (NOT micros) — Decimal directly.
- stat_time_day is "YYYY-MM-DD HH:MM:SS"; normalize() slices [:10] for the date.
- campaign_name is "(not set)" — not returned in integrated report metrics.
- No live network calls; pure functions only.
- TikTok uses Access-Token header, not Authorization: Bearer.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayaz.connectors import tiktok_ads  # noqa: F401 — triggers self-registration
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.connectors.tiktok_ads import TikTokAdsConnector

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tiktok_ads_report.json"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="tenant-test-005",
        connected_account_id="conn-tiktok-001",
        external_account_id="6934259910082387968",
        platform_key="tiktok_ads",
        vault_secret_ref="",
        extra={
            "access_token": "test-access-token-placeholder",
            "advertiser_id": "6934259910082387968",
            "currency": "USD",
        },
    )


@pytest.fixture()
def connector(config: ConnectorConfig) -> TikTokAdsConnector:
    conn = TikTokAdsConnector(config=config)
    # Inject the token so _access_token_header() works if called by tests
    conn._access_token = "test-access-token-placeholder"
    return conn


@pytest.fixture()
def fixture_body() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def fixture_rows(fixture_body) -> list[dict]:
    """The ``data.list`` from the fixture — rows ready for normalize()."""
    return fixture_body["data"]["list"]


# ── Registry ──────────────────────────────────────────────────────────────────


def test_tiktok_ads_connector_is_registered() -> None:
    """TikTokAdsConnector must auto-register under 'tiktok_ads'."""
    from ayaz.connectors.registry import ConnectorRegistry

    assert "tiktok_ads" in ConnectorRegistry.list_keys()
    cls = ConnectorRegistry.get("tiktok_ads")
    assert cls is TikTokAdsConnector


# ── Capabilities ──────────────────────────────────────────────────────────────


def test_capabilities(connector: TikTokAdsConnector) -> None:
    caps = connector.capabilities()
    assert caps.platform_key == "tiktok_ads"
    assert "daily_campaign_metrics" in caps.supported_streams
    assert caps.supports_incremental is True
    assert caps.supports_backfill is True
    assert caps.supports_write is False
    assert caps.min_granularity == "daily"
    assert caps.max_backfill_days == 365
    assert caps.rate_limit_rpm == 120


# ── normalize() golden-file tests ─────────────────────────────────────────────


def test_normalize_count(connector: TikTokAdsConnector, fixture_rows) -> None:
    records = connector.normalize(fixture_rows)
    assert len(records) == 4


def test_normalize_returns_unified_records(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r, UnifiedRecord)


def test_normalize_golden_row1_campaign1_day1(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """Golden-file: campaign 1780012345678901 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dimensions"]["stat_time_day"][:10],
            r["dimensions"]["campaign_id"],
        ),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    assert first.external_account_id == "6934259910082387968"
    assert first.platform == "tiktok_ads"
    # "2024-06-01 00:00:00"[:10] → date(2024, 6, 1)
    assert first.date_key == date(2024, 6, 1)
    assert first.campaign_id == "1780012345678901"
    # campaign_name not in integrated report; must be "(not set)"
    assert first.campaign_name == "(not set)"
    assert first.adset_id == "(not set)"
    assert first.adset_name == "(not set)"
    assert first.ad_id == "(not set)"
    assert first.ad_name == "(not set)"


def test_normalize_golden_metrics_row1(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """Golden-file: spend string→Decimal (NOT micros), all metrics correct."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dimensions"]["stat_time_day"][:10],
            r["dimensions"]["campaign_id"],
        ),
    )
    records = connector.normalize(rows_sorted)

    first = records[0]
    # spend "112.35" → Decimal("112.35") — no micro conversion
    assert first.cost_raw == Decimal("112.35")
    assert first.cost_ccy == "USD"
    assert first.impressions == 204_500
    assert first.clicks == 5_120
    assert first.conversions == Decimal("94")
    assert first.conversion_value_raw == Decimal("3760.00")
    assert first.conversion_value_ccy == "USD"


def test_normalize_golden_row2_campaign2_day1(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """Golden-file: campaign 1780012345678902 on 2024-06-01."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dimensions"]["stat_time_day"][:10],
            r["dimensions"]["campaign_id"],
        ),
    )
    records = connector.normalize(rows_sorted)

    second = records[1]
    assert second.date_key == date(2024, 6, 1)
    assert second.campaign_id == "1780012345678902"
    assert second.cost_raw == Decimal("45.80")
    assert second.impressions == 98_700
    assert second.clicks == 2_340
    assert second.conversions == Decimal("31")
    assert second.conversion_value_raw == Decimal("1240.00")


def test_normalize_golden_row3_campaign1_day2(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """Golden-file: campaign 1780012345678901 on 2024-06-02."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dimensions"]["stat_time_day"][:10],
            r["dimensions"]["campaign_id"],
        ),
    )
    records = connector.normalize(rows_sorted)

    third = records[2]
    assert third.date_key == date(2024, 6, 2)
    assert third.campaign_id == "1780012345678901"
    assert third.cost_raw == Decimal("119.60")
    assert third.impressions == 218_000
    assert third.clicks == 5_480
    assert third.conversions == Decimal("102")
    assert third.conversion_value_raw == Decimal("4080.00")


def test_normalize_golden_row4_zero_metrics(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """Golden-file: campaign 2 on 2024-06-02 — all zero metrics."""
    rows_sorted = sorted(
        fixture_rows,
        key=lambda r: (
            r["dimensions"]["stat_time_day"][:10],
            r["dimensions"]["campaign_id"],
        ),
    )
    records = connector.normalize(rows_sorted)

    fourth = records[3]
    assert fourth.date_key == date(2024, 6, 2)
    assert fourth.campaign_id == "1780012345678902"
    assert fourth.cost_raw == Decimal("0")
    assert fourth.impressions == 0
    assert fourth.clicks == 0
    assert fourth.conversions == Decimal("0")
    assert fourth.conversion_value_raw == Decimal("0")


def test_normalize_spend_is_not_micros(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """TikTok spend is plain currency, NOT micros — must not divide by 1e6."""
    records = connector.normalize(fixture_rows)
    for r in records:
        # If micros division were applied, spend "112.35" → ~0.000112, not 112.35
        if r.cost_raw > Decimal("0"):
            assert r.cost_raw > Decimal("1"), (
                "Spend looks like it was divided by 1e6 — TikTok spend is not micros."
            )


def test_normalize_stat_time_day_with_timestamp_suffix(
    connector: TikTokAdsConnector,
) -> None:
    """stat_time_day includes a time component — must slice to YYYY-MM-DD."""
    row = {
        "dimensions": {
            "campaign_id": "111",
            "stat_time_day": "2024-06-15 00:00:00",
        },
        "metrics": {
            "spend": "50.00",
            "impressions": "1000",
            "clicks": "100",
            "conversions": "5",
            "total_purchase_value": "200.00",
        },
    }
    records = connector.normalize([row])
    assert len(records) == 1
    assert records[0].date_key == date(2024, 6, 15)


def test_normalize_monetary_values_are_decimal(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.cost_raw, Decimal)
        assert isinstance(r.conversions, Decimal)
        assert isinstance(r.conversion_value_raw, Decimal)


def test_normalize_date_is_date_object(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert isinstance(r.date_key, date)


def test_normalize_platform_field(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.platform == "tiktok_ads"


def test_normalize_raw_source_preserved(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.raw_source is not None
        assert "dimensions" in r.raw_source
        assert "metrics" in r.raw_source


def test_normalize_campaign_name_is_not_set(
    connector: TikTokAdsConnector, fixture_rows
) -> None:
    """campaign_name must be '(not set)' — not returned in integrated report."""
    records = connector.normalize(fixture_rows)
    for r in records:
        assert r.campaign_name == "(not set)", (
            "TikTok integrated report does not include campaign_name; "
            "must default to '(not set)'."
        )


# ── incremental_state() ───────────────────────────────────────────────────────


def test_incremental_state_empty_before_fetch(
    connector: TikTokAdsConnector,
) -> None:
    assert connector.incremental_state() == {}


def test_incremental_state_returns_dict(connector: TikTokAdsConnector) -> None:
    assert isinstance(connector.incremental_state(), dict)


# ── authenticate() — pure path ─────────────────────────────────────────────────


def test_authenticate_sets_access_token(config: ConnectorConfig) -> None:
    """authenticate() must load the access_token from config.extra."""
    conn = TikTokAdsConnector(config=config)
    assert conn._access_token is None
    conn.authenticate()
    assert conn._access_token == "test-access-token-placeholder"


def test_authenticate_raises_without_required_keys() -> None:
    """authenticate() must raise RuntimeError if required keys are missing."""
    cfg = ConnectorConfig(
        tenant_id="t", connected_account_id="c", external_account_id="e",
        platform_key="tiktok_ads", extra={},
    )
    conn = TikTokAdsConnector(config=cfg)
    with pytest.raises(RuntimeError, match="Missing required credentials"):
        conn.authenticate()


# ── build_authorization_url() ─────────────────────────────────────────────────


def test_build_authorization_url_contains_expected_parts() -> None:
    url = TikTokAdsConnector.build_authorization_url(
        app_id="tt-app-123",
        redirect_uri="https://example.com/callback",
        state="csrf-tok",
    )
    assert "business-api.tiktok.com/portal/auth" in url
    assert "tt-app-123" in url
    assert "csrf-tok" in url
