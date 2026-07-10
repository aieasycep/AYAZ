"""Google Ads connector for AYAZ.

Connects to the Google Ads REST API (searchStream endpoint) to pull daily
campaign-level metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``client_id``
    OAuth 2.0 client ID from a Google Cloud project with the Google Ads API enabled.
``client_secret``
    OAuth 2.0 client secret for the same project.
``developer_token``
    Google Ads developer token issued to your manager account.  Required in every
    API request header (``developer-token``).
``refresh_token``
    Long-lived refresh token obtained once via the OAuth 2.0 consent flow
    (scope ``https://www.googleapis.com/auth/adwords``).  Use the OAuth2 Playground
    or a one-time CLI script to generate and store this token in Vault.
``login_customer_id``
    Manager (MCC) account ID that owns the target customer account.  Omit if the
    authenticated account IS the customer account (no manager hierarchy).
``customer_id``
    The 10-digit Google Ads customer ID whose data is to be synced.
    Must be accessible by the credentials above.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"USD"``).  Defaults to ``"USD"``.
    Obtain from the account's currency_code field in the API if not supplied.

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Granularity: daily (``segments.date``).
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 365 days (Google Ads keeps ~3 years; 365 is a safe scheduler limit).
- Write support: no (read-only).

Rate limits
-----------
- Google Ads API uses an Operations-Per-Day quota tied to the developer token level.
  Basic access: ~15,000 operations/day.  Standard access: no hard daily cap but
  subject to per-minute burst limits.
- ``searchStream`` counts as one operation per request, regardless of row count.
- This connector does NOT implement per-request throttling — the scheduler must
  space calls appropriately when handling many customer IDs.

API version
-----------
Targets ``v18`` of the Google Ads REST API.  Update ``_API_VERSION`` to upgrade.

Google Ads API reference
-----------
https://developers.google.com/google-ads/api/rest/reference/rest
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

_API_VERSION = "v18"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/adwords"

# Base URL for the Google Ads REST searchStream endpoint.
# Formatted with: _SEARCH_STREAM_URL.format(ver=_API_VERSION, customer_id=...)
_SEARCH_STREAM_URL = (
    "https://googleads.googleapis.com/{ver}/customers/{customer_id}"
    "/googleAds:searchStream"
)

# GAQL query used by fetch().  Selects daily campaign-level metrics.
# Caller injects the date range via the WHERE clause before sending.
_GAQL_TEMPLATE = (
    "SELECT "
    "  segments.date, "
    "  campaign.id, "
    "  campaign.name, "
    "  campaign.status, "
    "  metrics.impressions, "
    "  metrics.clicks, "
    "  metrics.cost_micros, "
    "  metrics.conversions, "
    "  metrics.conversions_value "
    "FROM campaign "
    "WHERE segments.date BETWEEN '{since}' AND '{until}' "
    "  AND campaign.status != 'REMOVED'"
)

_MICROS_DIVISOR = Decimal("1000000")


# ── Connector ─────────────────────────────────────────────────────────────────


class GoogleAdsConnector(Connector):
    """Google Ads connector — daily campaign metrics via the REST searchStream API.

    No gRPC / google-ads library required; uses ``httpx`` against the REST
    endpoint so the dependency footprint stays minimal.

    Credential lookup
    -----------------
    All secrets are read from ``ConnectorConfig.extra`` at runtime.  In
    production these values are injected by the Vault broker — never hard-coded.

    Expected ``config.extra`` keys:
        ``client_id``, ``client_secret``, ``developer_token``, ``refresh_token``,
        ``customer_id``, ``login_customer_id`` (optional), ``currency`` (optional).
    """

    platform_key = "google_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        # Access token populated by authenticate() / refresh_token()
        self._access_token: str | None = None
        # Watermark updated by fetch()
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        """Read a credential from config.extra (Vault-injected at runtime)."""
        return str(self.config.extra.get(key, default))

    def _customer_id(self) -> str:
        return self._get_secret("customer_id") or self.config.external_account_id

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        """Build request headers that every Google Ads API call requires."""
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._access_token}",
            "developer-token": self._get_secret("developer_token"),
            "Content-Type": "application/json",
        }
        login_cid = self._get_secret("login_customer_id")
        if login_cid:
            headers["login-customer-id"] = login_cid
        return headers

    # ── OAuth helpers (structural; no live calls in tests) ─────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the Google OAuth2 consent URL for the adwords scope.

        This is a pure helper used by the AYAZ OAuth broker to redirect the
        user through Google's consent screen.  It makes NO network calls.

        Parameters
        ----------
        client_id:
            OAuth 2.0 client ID from the Google Cloud project.
        redirect_uri:
            URI Google will redirect to after consent (must be registered in
            the Cloud Console for the client_id).
        state:
            CSRF protection token (opaque; round-tripped by Google).
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
        return f"{_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _exchange_refresh_token(self) -> str:
        """POST to Google's token endpoint and return a new access token.

        Uses the long-lived refresh_token stored in Vault (via config.extra).
        Separated from authenticate() so it can be called standalone by
        refresh_token() without duplicating the HTTP logic.
        """
        payload = {
            "client_id": self._get_secret("client_id"),
            "client_secret": self._get_secret("client_secret"),
            "refresh_token": self._get_secret("refresh_token"),
            "grant_type": "refresh_token",
        }
        resp = httpx.post(_OAUTH_TOKEN_URL, data=payload, timeout=30)
        resp.raise_for_status()
        token_data: dict[str, Any] = resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ValueError(
                f"{self._log_prefix()} Token exchange returned no access_token. "
                f"Response: {token_data}"
            )
        logger.info("%s Access token refreshed successfully.", self._log_prefix())
        return access_token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Exchange the stored refresh token for a live access token.

        Reads ``client_id``, ``client_secret``, and ``refresh_token`` from
        ``config.extra`` (injected by the Vault broker in production).

        Raises
        ------
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response (invalid creds).
        ValueError
            If the response does not contain an access_token.
        RuntimeError
            If any required credential is missing from config.extra.
        """
        required = ("client_id", "client_secret", "refresh_token", "developer_token")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "These must be present in config.extra (injected by Vault broker)."
            )
        self._access_token = self._exchange_refresh_token()

    def refresh_token(self) -> None:
        """Proactively refresh the access token before expiry.

        Called by the OAuth Broker ~5 minutes before the token expires.
        Delegates to _exchange_refresh_token() and updates self._access_token.

        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._exchange_refresh_token()
        logger.info(
            "%s Token refreshed proactively. "
            "TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """List accessible customer accounts under the authenticated credentials.

        In a manager-account (MCC) setup this queries
        ``customers/{login_customer_id}/googleAds:search`` for all accessible
        leaf customers.  For a standalone account it returns just that account.

        Returns
        -------
        list[dict]
            Each entry contains at minimum ``id``, ``name``, and ``currency``.
            In production the ETL worker stores these to ``connected_accounts``.

        Notes
        -----
        The live call uses GAQL:
            SELECT customer_client.id, customer_client.descriptive_name,
                   customer_client.currency_code
            FROM customer_client
            WHERE customer_client.manager = false

        No live call is made here; the method is structured so tests can call
        it with a mocked ``httpx`` client.
        """
        login_cid = self._get_secret("login_customer_id")
        if not login_cid:
            # Standalone account — return a single-entry list without a network call
            return [
                {
                    "id": self._customer_id(),
                    "name": f"Google Ads Account {self._customer_id()}",
                    "currency": self._currency(),
                }
            ]

        # Manager account: query the customer_client resource
        gaql = (
            "SELECT customer_client.id, customer_client.descriptive_name, "
            "customer_client.currency_code "
            "FROM customer_client "
            "WHERE customer_client.manager = false"
        )
        url = (
            f"https://googleads.googleapis.com/{_API_VERSION}"
            f"/customers/{login_cid}/googleAds:search"
        )
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            json={"query": gaql},
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        accounts: list[dict[str, Any]] = []
        for result in body.get("results", []):
            cc = result.get("customerClient", {})
            accounts.append(
                {
                    "id": str(cc.get("id", "")),
                    "name": str(cc.get("descriptiveName", "")),
                    "currency": str(cc.get("currencyCode", "USD")),
                }
            )
        return accounts

    def list_child_customers(self, manager_id: str) -> list[dict[str, Any]]:
        """Return the non-manager (leaf) advertising accounts under a customer.

        Runs the customer_client GAQL query (WHERE customer_client.manager = false)
        against ``customers/{manager_id}/googleAds:search`` with the ``login-customer-id``
        header explicitly set to ``manager_id``. For a manager (MCC) account this returns
        its leaf child ad accounts; for a STANDALONE (non-manager) account the
        customer_client resource returns a single self-row (the account itself).

        Requires ``authenticate()`` to have run first (needs an access token).

        Parameters
        ----------
        manager_id:
            The Google Ads customer ID (MCC or standalone) to query as the
            ``login-customer-id``. Overrides any ``login_customer_id`` configured
            in ``config.extra`` — this call always addresses ``manager_id`` directly.

        Returns
        -------
        list[dict]
            One entry per leaf: ``{"id": "<bare 10-digit>", "name": "<descriptive_name>",
            "currency": "<currency_code>"}``. Empty list if the response has no results.

        Raises
        ------
        RuntimeError
            If ``authenticate()`` has not been called yet (no access token) —
            raised by ``_auth_headers()``.
        httpx.HTTPStatusError
            If the endpoint returns a non-2xx response (invalid creds/scope).
        """
        gaql = (
            "SELECT customer_client.id, customer_client.descriptive_name, "
            "customer_client.currency_code "
            "FROM customer_client "
            "WHERE customer_client.manager = false"
        )
        url = (
            f"https://googleads.googleapis.com/{_API_VERSION}"
            f"/customers/{manager_id}/googleAds:search"
        )
        headers = self._auth_headers()
        headers["login-customer-id"] = str(manager_id)

        resp = httpx.post(url, headers=headers, json={"query": gaql}, timeout=30)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()

        leaves: list[dict[str, Any]] = []
        for result in body.get("results", []):
            cc = result.get("customerClient", {})
            raw_id = str(cc.get("id", "")).removeprefix("customers/")
            leaves.append(
                {
                    "id": raw_id,
                    "name": str(cc.get("descriptiveName", "")),
                    "currency": str(cc.get("currencyCode", "")),
                }
            )
        logger.info(
            "%s list_child_customers(manager_id=%s) returned %d leaf account(s).",
            self._log_prefix(),
            manager_id,
            len(leaves),
        )
        return leaves

    def list_accessible_customers(self) -> list[str]:
        """Return the 10-digit customer IDs accessible to the authenticated creds.

        Calls the Google Ads REST ``customers:listAccessibleCustomers`` endpoint,
        which requires only the OAuth access token + developer-token header (no
        login-customer-id, no GAQL). Used by the ETL layer to auto-populate
        ``connected_accounts.external_account_id`` when it is empty.

        Requires ``authenticate()`` to have been called (needs an access token).
        Returns bare customer IDs (``"1234567890"``), stripped of the
        ``"customers/"`` resource-name prefix. Empty list if none accessible.

        Returns
        -------
        list[str]
            Bare customer IDs, e.g. ``["1234567890", "9876543210"]``.

        Raises
        ------
        RuntimeError
            If ``authenticate()`` has not been called yet (no access token) —
            raised by ``_auth_headers()``.
        httpx.HTTPStatusError
            If the endpoint returns a non-2xx response (invalid creds/scope).
        """
        url = (
            f"https://googleads.googleapis.com/{_API_VERSION}"
            "/customers:listAccessibleCustomers"
        )
        resp = httpx.get(url, headers=self._auth_headers(), timeout=30)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        resource_names = body.get("resourceNames") or []
        customer_ids = [name.removeprefix("customers/") for name in resource_names]
        logger.info(
            "%s listAccessibleCustomers returned %d customer id(s).",
            self._log_prefix(),
            len(customer_ids),
        )
        return customer_ids

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch raw campaign metrics from the Google Ads searchStream endpoint.

        POSTs a GAQL query to the REST searchStream endpoint and collects all
        result batches into a flat list of raw row dicts.

        Parameters
        ----------
        stream:
            Must be ``"daily_campaign_metrics"`` (the only supported stream).
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            One dict per row, each containing ``campaign``, ``metrics``, and
            ``segments`` sub-dicts matching the Google Ads REST response shape.
            These are passed directly to ``normalize()``.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        gaql = _GAQL_TEMPLATE.format(
            since=since.isoformat(),
            until=until.isoformat(),
        )
        url = _SEARCH_STREAM_URL.format(
            ver=_API_VERSION,
            customer_id=self._customer_id(),
        )

        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            json={"query": gaql},
            timeout=60,
        )
        resp.raise_for_status()

        # searchStream returns a JSON array of batch objects, each with a
        # "results" list.  Flatten all batches into a single list of row dicts.
        raw_rows = self._parse_stream_response(resp.json())

        # Update watermark to latest date seen
        if raw_rows:
            latest = max(
                date.fromisoformat(r["segments"]["date"]) for r in raw_rows
            )
            self._watermark[stream] = latest.isoformat()
            logger.info(
                "%s Fetched %d rows for stream=%r, watermark=%s",
                self._log_prefix(),
                len(raw_rows),
                stream,
                latest.isoformat(),
            )

        return raw_rows

    @staticmethod
    def _parse_stream_response(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten a searchStream response (list of batches) into row dicts.

        The searchStream endpoint returns a JSON array of batch objects:
        ``[{"results": [{...row...}, ...]}, ...]``

        This method is static and pure so it can be exercised independently
        of any network call.

        Parameters
        ----------
        body:
            Parsed JSON body from the searchStream POST response.

        Returns
        -------
        list[dict]
            Flat list of individual row dicts, each containing ``campaign``,
            ``metrics``, and ``segments`` keys.
        """
        rows: list[dict[str, Any]] = []
        for batch in body:
            for row in batch.get("results", []):
                rows.append(row)
        return rows

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Google Ads searchStream rows to ``UnifiedRecord``s.

        This is a PURE function — it takes the flat list produced by
        ``_parse_stream_response()`` and performs no I/O.

        Field mapping
        -------------
        Google Ads field                 → UnifiedRecord field
        ``campaign.id``                  → ``campaign_id``
        ``campaign.name``                → ``campaign_name``
        ``segments.date``                → ``date_key`` (UTC)
        ``metrics.impressions`` (str)    → ``impressions`` (int)
        ``metrics.clicks`` (str)         → ``clicks`` (int)
        ``metrics.cost_micros`` (str)    → ``cost_raw`` (Decimal, /1_000_000)
        ``metrics.conversions`` (float)  → ``conversions`` (Decimal)
        ``metrics.conversions_value``    → ``conversion_value_raw`` (Decimal)
        account currency (from config)   → ``cost_ccy`` / ``conversion_value_ccy``

        Google Ads does not expose ad-set or ad granularity via this GAQL query;
        those levels are set to ``"(not set)"`` as the SDK convention requires.

        Example (before → after)
        -------------------------
        Input row::

            {
              "campaign": {"id": "111000001", "name": "Summer Promo 2024", ...},
              "metrics": {"impressions": "82000", "clicks": "1540",
                          "costMicros": "25000000", "conversions": 18.0,
                          "conversionsValue": 540.0},
              "segments": {"date": "2024-06-01"}
            }

        Output UnifiedRecord::

            UnifiedRecord(
                external_account_id="1234567890",
                platform="google_ads",
                date_key=date(2024, 6, 1),
                campaign_id="111000001",
                campaign_name="Summer Promo 2024",
                adset_id="(not set)", adset_name="(not set)",
                ad_id="(not set)",    ad_name="(not set)",
                impressions=82000,
                clicks=1540,
                cost_raw=Decimal("25"),      # 25_000_000 / 1_000_000
                cost_ccy="USD",
                conversions=Decimal("18"),
                conversion_value_raw=Decimal("540"),
                conversion_value_ccy="USD",
            )
        """
        records: list[UnifiedRecord] = []
        account_id = self._customer_id()
        currency = self._currency()

        for row in raw:
            campaign = row.get("campaign", {})
            metrics = row.get("metrics", {})
            segments = row.get("segments", {})

            # Monetary: costMicros is returned as a string; divide by 1_000_000
            cost_micros_raw = str(metrics.get("costMicros", "0"))
            cost_raw = Decimal(cost_micros_raw) / _MICROS_DIVISOR

            # Impressions and clicks arrive as strings in the REST API
            impressions = int(str(metrics.get("impressions", "0")))
            clicks = int(str(metrics.get("clicks", "0")))

            # Conversions and conversionsValue arrive as floats; use str() to
            # avoid floating-point repr issues when constructing Decimal
            conversions = Decimal(str(metrics.get("conversions", "0")))
            conversion_value_raw = Decimal(
                str(metrics.get("conversionsValue", "0"))
            )

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date.fromisoformat(segments["date"]),
                    campaign_id=str(campaign.get("id", "(not set)")),
                    campaign_name=str(campaign.get("name", "(not set)")),
                    # Google Ads campaign-level GAQL has no ad-set/ad grain
                    adset_id="(not set)",
                    adset_name="(not set)",
                    ad_id="(not set)",
                    ad_name="(not set)",
                    impressions=impressions,
                    clicks=clicks,
                    cost_raw=cost_raw,
                    cost_ccy=currency,
                    conversions=conversions,
                    conversion_value_raw=conversion_value_raw,
                    conversion_value_ccy=currency,
                    raw_source=row,
                )
            )

        return records

    def incremental_state(self) -> dict[str, Any]:
        """Return the watermark cursor populated by the last ``fetch()`` call.

        The scheduler persists this to ``connected_accounts.watermark`` after a
        successful sync.  The next run passes ``watermark + 1 day`` as ``since``.

        Returns
        -------
        dict
            ``{"daily_campaign_metrics": "YYYY-MM-DD"}`` where the date is the
            latest date seen in the most recent fetch.  Empty dict if no fetch
            has been completed in this connector instance's lifetime.
        """
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        """Return the capability descriptor for the Google Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # Google Ads API: Basic access ~15k ops/day.  No per-minute limit is
            # documented for searchStream; 60 RPM is a conservative safe default.
            rate_limit_rpm=60,
        )
