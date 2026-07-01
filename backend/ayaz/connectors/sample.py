"""Sample connector — demonstrates the Connector SDK with zero network calls.

This connector reads from a recorded fixture JSON file (representing a generic
ad platform's daily metrics export format) and normalises it to ``UnifiedRecord``s.

Purpose
-------
1. Proves the end-to-end connector pattern before any real connector is built.
2. Provides the golden-file testing template all future connectors will follow.
3. Acts as a development / CI fixture source for dashboard and ETL testing.

The fixture format (``tests/fixtures/sample_metrics.json``) mirrors the kind of
flat-file export many ad platforms offer: one row per (account, date, campaign,
adset, ad) with spend in the account currency.

Field mapping
-------------
Platform field   → UnifiedRecord field
``account_id``   → ``external_account_id``
``date``         → ``date_key`` (parsed as UTC date; no TZ shift needed)
``campaign_id``  → ``campaign_id``
``adset_id``     → ``adset_id``
``ad_id``        → ``ad_id``
``impressions``  → ``impressions``
``clicks``       → ``clicks``
``spend``        → ``cost_raw`` (Decimal)
``currency``     → ``cost_ccy``
``conversions``  → ``conversions`` (Decimal)
``conversion_value`` → ``conversion_value_raw`` (Decimal; same ccy as spend)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ayaz.connectors.base import (
    Connector,
    ConnectorCapabilities,
    ConnectorConfig,
    UnifiedRecord,
)

# Default fixture path — tests override via ConnectorConfig.extra["fixture_path"]
_DEFAULT_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "tests"
    / "fixtures"
    / "sample_metrics.json"
)


class SampleConnector(Connector):
    """Fixture-backed connector used for testing and local development.

    No network calls are made.  Credentials / Vault references are ignored.
    """

    platform_key = "sample"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._fixture_path: Path = Path(
            config.extra.get("fixture_path", _DEFAULT_FIXTURE)
        )
        self._watermark: dict[str, str] = {}

    # ── Connector interface ────────────────────────────────────────────────

    def authenticate(self) -> None:
        """No-op: sample connector needs no credentials."""

    def refresh_token(self) -> None:
        """No-op: sample connector has no OAuth tokens."""

    def discover(self) -> list[dict[str, Any]]:
        """Return a single fake account entry."""
        return [
            {
                "id": self.config.external_account_id or "ACC-001",
                "name": "Sample Ad Account",
                "currency": "USD",
            }
        ]

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Load records from the fixture file and filter by date range.

        ``stream`` is accepted but ignored — the fixture has a single stream.
        """
        with self._fixture_path.open(encoding="utf-8") as fh:
            rows: list[dict[str, Any]] = json.load(fh)

        # Filter to the requested date window (inclusive)
        result = []
        for row in rows:
            row_date = date.fromisoformat(row["date"])
            if since <= row_date <= until:
                result.append(row)

        # Update watermark to the latest date seen
        if result:
            latest = max(date.fromisoformat(r["date"]) for r in result)
            self._watermark[stream] = latest.isoformat()

        return result

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map sample fixture rows to ``UnifiedRecord``s.

        Currency / timezone handling
        ----------------------------
        - Dates in the fixture are already calendar dates (no TZ conversion needed
          for this mock).  Real connectors MUST convert from platform-local timezone
          to UTC before setting ``date_key``.
        - Monetary values are converted to ``Decimal`` from strings to preserve
          precision.  Real connectors receiving ``cost_micros`` should divide by
          ``1_000_000``.
        """
        records: list[UnifiedRecord] = []
        for row in raw:
            records.append(
                UnifiedRecord(
                    external_account_id=str(row["account_id"]),
                    platform=self.platform_key,
                    date_key=date.fromisoformat(row["date"]),
                    campaign_id=str(row["campaign_id"]),
                    campaign_name=str(row.get("campaign_name", "")),
                    adset_id=str(row["adset_id"]),
                    adset_name=str(row.get("adset_name", "")),
                    ad_id=str(row["ad_id"]),
                    ad_name=str(row.get("ad_name", "")),
                    impressions=int(row.get("impressions", 0)),
                    clicks=int(row.get("clicks", 0)),
                    cost_raw=Decimal(str(row.get("spend", "0"))),
                    cost_ccy=str(row.get("currency", "USD")),
                    conversions=Decimal(str(row.get("conversions", "0"))),
                    conversion_value_raw=Decimal(
                        str(row.get("conversion_value", "0"))
                    ),
                    conversion_value_ccy=str(row.get("currency", "USD")),
                    raw_source=row,
                )
            )
        return records

    def incremental_state(self) -> dict[str, Any]:
        """Return the watermark populated by the last ``fetch()`` call."""
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            rate_limit_rpm=None,
        )
