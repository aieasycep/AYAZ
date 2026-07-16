"""Google Analytics 4 (GA4) connector for AYAZ.

Connects to the GA4 Data API (runReport endpoint) to pull daily session and
conversion metrics into the unified ``UnifiedRecord`` schema.

IMPORTANT — semantic gap
------------------------
GA4 is an **analytics** source, not an **ads** source.  Key implications:

1. **No ad spend**: ``cost_raw`` is always ``Decimal("0")``.  ``cost_ccy``
   defaults to ``"USD"`` (arbitrary; cost is zero so the currency is irrelevant,
   but a value is required by the schema).

2. **Sessions ≠ Clicks**: GA4 reports ``sessions`` (user sessions starting on
   the site/app), not ad clicks.  These are structurally incompatible with
   ``clicks`` (which counts ad-link clicks).  ``clicks`` is therefore set to
   ``0`` on every record.  Downstream metric-layer consumers should treat GA4
   ``clicks=0`` as "not applicable" rather than "zero clicks".

3. **Channel group ≠ Campaign**: GA4's ``sessionDefaultChannelGroup`` (e.g.
   ``"Paid Search"``, ``"Organic Search"``) is a channel grouping, not a
   campaign name.  It is mapped to both ``campaign_id`` and ``campaign_name``
   since GA4 has no campaign-level grain at this query.  The ETL worker can
   enrich this further if GA4 campaign dimensions are added to the report.

4. **Conversions are purchases, not all key events**: this connector requests
   the GA4 Data API's ecommerce-specific metrics — ``ecommercePurchases``
   (count of purchase events) and ``purchaseRevenue`` (revenue from those
   purchases) — rather than the generic ``conversions`` / ``totalRevenue``
   metrics. The generic ``conversions`` metric sums *every* configured
   key event (which can include ``page_view``, ``session_start``, etc.,
   depending on the property's key-event configuration) and ``totalRevenue``
   sums *all* site revenue regardless of channel — both wildly overcount vs.
   what ad platforms report as "conversions", producing nonsensical multi-
   million-conversion / triple-digit-ROAS numbers when blended with ad-
   platform data (see ``ayaz/services/attribution.py``). ``ecommercePurchases``
   / ``purchaseRevenue`` are standard GA4 Data API metrics available on every
   property (return ``0`` if the property has no ecommerce tracking
   configured) and map onto "conversions" the way ad platforms mean it:
   completed purchases.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``client_id``
    OAuth 2.0 client ID from a Google Cloud project with the GA4 Data API enabled.
``client_secret``
    OAuth 2.0 client secret.
``refresh_token``
    Long-lived refresh token (scope ``https://www.googleapis.com/auth/analytics.readonly``).
``property_id``
    GA4 property ID (numeric, without the ``properties/`` prefix), e.g. ``"123456789"``.
    NOT required by ``authenticate()`` (see chicken-and-egg note below) — only by
    ``fetch()``.  Discover candidate values via ``list_properties()``.
``currency``  (optional)
    ISO-4217 code for ``conversion_value_ccy``.  Defaults to ``"USD"``.

Property discovery
------------------
``authenticate()`` only requires ``client_id`` / ``client_secret`` /
``refresh_token`` — a user who just completed the OAuth consent dialog has a
refresh token but has not picked a GA4 property yet.  Call
``list_properties()`` (GA4 Admin API ``accountSummaries``) after
``authenticate()`` to list every property the credentials can access, then
persist the chosen ``id`` as ``property_id`` / ``connected_accounts.external_account_id``
before calling ``fetch()``.  ``discover()`` remains a zero-network-call helper
that echoes back the already-configured property.

Sync strategy
-------------
- Stream: ``daily_channel_metrics`` — one row per (date, channel group).
- Granularity: daily.
- Incremental: yes.
- Max backfill: 365 days (GA4 Data API does not enforce a hard limit, but very
  large ranges can time out; 365 days is a safe scheduler limit).
- Write support: no (read-only).

Rate limits
-----------
- GA4 Data API: 10 concurrent requests per property, 10 requests/second per
  project, and daily/hourly core token bucket limits.
- 120 RPM is a conservative per-property cap.

API version
-----------
Targets GA4 Data API v1beta.  Update ``_API_VERSION`` to upgrade.

GA4 Data API reference
-----------------------
https://developers.google.com/analytics/devguides/reporting/data/v1
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from ayaz.connectors.base import (
    Connector,
    ConnectorCapabilities,
    ConnectorConfig,
    UnifiedRecord,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_API_VERSION = "v1beta"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

# runReport endpoint — formatted with api_version and property_id
_RUN_REPORT_URL = (
    "https://analyticsdata.googleapis.com/{ver}/properties/{property_id}:runReport"
)

# GA4 Admin API accountSummaries endpoint — NOTE: separate host from the Data
# API above (analyticsadmin.googleapis.com, not analyticsdata.googleapis.com).
# Fixed at v1beta; not parameterized by _API_VERSION (Admin API versions its
# endpoints independently of the Data API).
_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"

# Dimensions and metrics requested from the Data API
_DIMENSIONS = ["date", "sessionDefaultChannelGroup"]
# ecommercePurchases / purchaseRevenue (NOT conversions / totalRevenue) — see
# module docstring point 4: the generic metrics overcount vs. ad-platform
# "conversions" semantics; the ecommerce-specific ones are apples-to-apples.
_METRICS = ["sessions", "ecommercePurchases", "purchaseRevenue"]


# ── Connector ─────────────────────────────────────────────────────────────────


class GA4Connector(Connector):
    """GA4 connector — daily channel-level session and conversion metrics.

    This is an analytics connector, not an ads connector.  ``cost_raw`` is
    always zero.  See module docstring for full semantic-gap documentation.

    Expected ``config.extra`` keys:
        ``client_id``, ``client_secret``, ``refresh_token``, ``property_id``,
        ``currency`` (optional).
    """

    platform_key = "ga4"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        return str(self.config.extra.get(key, default))

    def _property_id(self) -> str:
        return self._get_secret("property_id") or self.config.external_account_id

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _run_report_url(self) -> str:
        return _RUN_REPORT_URL.format(
            ver=_API_VERSION, property_id=self._property_id()
        )

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the Google OAuth2 consent URL for the analytics.readonly scope.

        Pure helper — no network calls.
        """
        import urllib.parse

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _OAUTH_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urllib.parse.urlencode(params)
        )

    def _exchange_refresh_token(self) -> str:
        """POST to Google token endpoint and return a new access token."""
        payload = {
            "client_id": self._get_secret("client_id"),
            "client_secret": self._get_secret("client_secret"),
            "refresh_token": self._get_secret("refresh_token"),
            "grant_type": "refresh_token",
        }
        resp = httpx.post(_OAUTH_TOKEN_URL, data=payload, timeout=30)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Token exchange returned no access_token. "
                f"Response: {data}"
            )
        logger.info("%s Access token refreshed successfully.", self._log_prefix())
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Exchange the stored refresh token for a live access token.

        ``property_id`` is intentionally NOT required here: a user who has
        just completed the OAuth dialog has a ``refresh_token`` but has not
        picked a GA4 property yet.  ``list_properties()`` (the property
        picker) needs to run with only the token — requiring ``property_id``
        up front creates a chicken-and-egg RuntimeError that blocks property
        selection entirely.  Mirrors ``MetaAdsConnector.authenticate()``,
        which does not require ``ad_account_id`` either.  ``_property_id()``
        / ``_run_report_url()`` still fall back to
        ``config.external_account_id`` once a property has been selected and
        persisted; ``fetch()`` still requires a resolved property_id to work.

        Raises
        ------
        RuntimeError
            If any required credential is missing from config.extra.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        ValueError
            If the response does not contain an access_token.
        """
        required = ("client_id", "client_secret", "refresh_token")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "These must be present in config.extra (injected by Vault broker)."
            )
        self._access_token = self._exchange_refresh_token()

    def refresh_token(self) -> None:
        """Proactively refresh the access token before expiry.

        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._exchange_refresh_token()
        logger.info(
            "%s Token refreshed proactively. "
            "TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return the configured GA4 property as a single-entry list.

        GA4 Data API does not expose a "list all properties" endpoint without
        the Admin API.  This connector returns only the configured property.

        Returns
        -------
        list[dict]
            Single entry with ``id`` (property ID) and ``name``.
        """
        return [
            {
                "id": self._property_id(),
                "name": f"GA4 Property {self._property_id()}",
                "currency": self._currency(),
            }
        ]

    def list_properties(self) -> list[dict[str, Any]]:
        """Return the GA4 properties accessible to the authenticated credentials.

        Calls the GA4 Admin API ``accountSummaries`` endpoint
        (``https://analyticsadmin.googleapis.com/v1beta/accountSummaries``), which
        the ``analytics.readonly`` scope covers, and flattens every
        ``propertySummary`` across all account summaries.

        Requires ``authenticate()`` first (needs an access token). Returns bare
        property IDs (``"123456789"``, stripped of the ``properties/`` prefix) with
        display names. Used by the ETL layer to auto-populate / offer a picker for
        ``connected_accounts.external_account_id`` when it is empty.

        Returns
        -------
        list[dict]
            One entry per property: ``{"id": "<bare property id>", "name":
            "<propertySummary.displayName>"}``. Empty list if no account summaries
            (or no property summaries within them) are returned.

        Raises
        ------
        RuntimeError
            If ``authenticate()`` has not been called yet (no access token) —
            raised by ``_auth_headers()``.
        httpx.HTTPStatusError
            If the endpoint returns a non-2xx response (invalid creds/scope).
        """
        headers = self._auth_headers()
        properties: list[dict[str, Any]] = []

        url: str | None = _ACCOUNT_SUMMARIES_URL
        params: dict[str, Any] | None = None
        while url:
            resp = httpx.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

            for summary in body.get("accountSummaries", []) or []:
                for prop in summary.get("propertySummaries", []) or []:
                    raw_id = str(prop.get("property", "")).removeprefix("properties/")
                    properties.append(
                        {
                            "id": raw_id,
                            "name": str(prop.get("displayName", "")),
                        }
                    )

            # Pagination: accountSummaries is normally a single page, but
            # follow nextPageToken if the caller has enough accounts to paginate.
            next_token = body.get("nextPageToken")
            url = _ACCOUNT_SUMMARIES_URL if next_token else None
            params = {"pageToken": next_token} if next_token else None

        logger.info(
            "%s list_properties() returned %d propert(y/ies).",
            self._log_prefix(),
            len(properties),
        )
        return properties

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """POST a runReport request to the GA4 Data API.

        Parameters
        ----------
        stream:
            Must be ``"daily_channel_metrics"``.
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            Flat list of row dicts, each containing ``date``,
            ``sessionDefaultChannelGroup``, ``sessions``, ``ecommercePurchases``,
            and ``purchaseRevenue`` keys.  Rows are produced by
            ``_parse_run_report_response()``.
        """
        if stream not in ("daily_channel_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_channel_metrics']"
            )

        payload: dict[str, Any] = {
            "dateRanges": [
                {
                    "startDate": since.isoformat(),
                    "endDate": until.isoformat(),
                }
            ],
            "dimensions": [{"name": d} for d in _DIMENSIONS],
            "metrics": [{"name": m} for m in _METRICS],
        }

        resp = httpx.post(
            self._run_report_url(),
            headers=self._auth_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()

        rows = self._parse_run_report_response(resp.json())

        if rows:
            latest = max(date.fromisoformat(r["date"]) for r in rows)
            self._watermark[stream] = latest.isoformat()
            logger.info(
                "%s Fetched %d rows for stream=%r, watermark=%s",
                self._log_prefix(),
                len(rows),
                stream,
                latest.isoformat(),
            )

        return rows

    @staticmethod
    def _parse_run_report_response(body: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert the GA4 runReport response into a flat list of row dicts.

        The runReport response uses a columnar format:
        ``dimensionHeaders``, ``metricHeaders``, and ``rows`` (each row has
        ``dimensionValues`` and ``metricValues`` lists).  This method pivots
        them into keyed dicts for easy consumption by ``normalize()``.

        Parameters
        ----------
        body:
            Parsed JSON body from the runReport POST response.

        Returns
        -------
        list[dict]
            Each dict has keys matching dimension and metric names.
        """
        dim_headers = [h["name"] for h in body.get("dimensionHeaders", [])]
        met_headers = [h["name"] for h in body.get("metricHeaders", [])]
        rows: list[dict[str, Any]] = []

        for row in body.get("rows", []):
            record: dict[str, Any] = {}
            for i, dv in enumerate(row.get("dimensionValues", [])):
                if i < len(dim_headers):
                    record[dim_headers[i]] = dv.get("value", "(not set)")
            for i, mv in enumerate(row.get("metricValues", [])):
                if i < len(met_headers):
                    record[met_headers[i]] = mv.get("value", "0")
            rows.append(record)

        return rows

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map GA4 runReport rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        GA4 field                      → UnifiedRecord field
        ``date`` (YYYYMMDD)            → ``date_key`` (date object, UTC)
        ``sessionDefaultChannelGroup`` → ``campaign_id`` and ``campaign_name``
        ``sessions`` (str)             → NOT MAPPED (no equivalent field in schema)
                                          ``clicks = 0`` (see module docstring)
        ``ecommercePurchases`` (str)   → ``conversions`` (Decimal) — purchase
                                          count, NOT the generic all-key-events
                                          ``conversions`` metric (see module
                                          docstring point 4).
        ``purchaseRevenue`` (str)      → ``conversion_value_raw`` (Decimal) —
                                          ecommerce purchase revenue, NOT
                                          ``totalRevenue`` (all site revenue).
        n/a                            → ``cost_raw = Decimal("0")`` (analytics source)

        Date format: GA4 returns dates as ``"YYYYMMDD"`` strings.
        """
        records: list[UnifiedRecord] = []
        account_id = self._property_id()
        currency = self._currency()

        for row in raw:
            # GA4 date format: YYYYMMDD → parse to date
            date_str = str(row.get("date", "19700101"))
            date_key = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))

            channel = str(row.get("sessionDefaultChannelGroup", "(not set)"))

            # sessions: present in raw but has no schema equivalent.
            # Documented as "not mapped"; clicks remains 0.
            # sessions_count = int(str(row.get("sessions", "0")))  # available if needed

            # ecommercePurchases / purchaseRevenue — NOT the generic
            # conversions / totalRevenue metrics (see module docstring point 4).
            conversions = Decimal(str(row.get("ecommercePurchases", "0")))
            conversion_value_raw = Decimal(str(row.get("purchaseRevenue", "0")))

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    # GA4 has no campaign grain at this query level;
                    # channel group is the most specific dimension available.
                    campaign_id=channel,
                    campaign_name=channel,
                    adset_id="(not set)",
                    adset_name="(not set)",
                    ad_id="(not set)",
                    ad_name="(not set)",
                    impressions=0,  # GA4 reports no impression count
                    clicks=0,       # sessions != clicks; see module docstring
                    # Analytics source: no ad spend
                    cost_raw=Decimal("0"),
                    cost_ccy=currency,
                    conversions=conversions,
                    conversion_value_raw=conversion_value_raw,
                    conversion_value_ccy=currency,
                    raw_source=row,
                )
            )

        return records

    def incremental_state(self) -> dict[str, Any]:
        """Return the watermark cursor from the last ``fetch()`` call.

        Returns
        -------
        dict
            ``{"daily_channel_metrics": "YYYY-MM-DD"}`` — latest date seen.
            Empty dict if no fetch has been completed in this instance's lifetime.
        """
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        """Return the capability descriptor for the GA4 connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_channel_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # GA4 Data API: 10 req/sec per project; 120 RPM is conservative.
            rate_limit_rpm=120,
        )
