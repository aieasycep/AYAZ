"""Pinterest Ads connector for AYAZ.

Connects to the Pinterest Ads analytics endpoint to pull daily campaign-level
metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``access_token``
    OAuth 2.0 access token obtained via Pinterest's authorization code flow.
    Passed as ``Authorization: Bearer <access_token>`` on every request.
``refresh_token``
    Refresh token used to obtain a new access token before the 1-hour expiry.
``client_id``
    OAuth 2.0 client ID from the Pinterest Developer application.
``client_secret``
    OAuth 2.0 client secret for the same application.
``ad_account_id``
    The Pinterest Ads account ID (numeric string), e.g. ``"549755885175"``.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"USD"``).  Defaults to ``"USD"``.

OAuth 2.0 flow
--------------
1. Redirect the advertiser to
   ``https://www.pinterest.com/oauth/``
   with scope ``ads:read`` and ``user_accounts:read``.
2. Exchange the authorization code at
   ``POST https://api.pinterest.com/v5/oauth/token``
   for ``access_token`` (expires in 1 hour) and ``refresh_token`` (30 days).
3. Store tokens in Vault.
4. Refresh via ``POST https://api.pinterest.com/v5/oauth/token`` with
   ``grant_type=refresh_token`` before the 1-hour expiry.

Analytics endpoint
------------------
``GET https://api.pinterest.com/v5/ad_accounts/{ad_account_id}/campaigns/analytics``

Query parameters:
- ``start_date``: YYYY-MM-DD (inclusive)
- ``end_date``: YYYY-MM-DD (inclusive)
- ``campaign_ids``: comma-separated list of campaign IDs (optional; omit for all)
- ``columns``: comma-separated metric columns (see below)
- ``granularity``: ``DAY``

Column selection
----------------
Pinterest supports both ``SPEND_IN_DOLLAR`` and ``SPEND_IN_MICRO_DOLLAR``
spend columns.  This connector requests ``SPEND_IN_DOLLAR`` (the higher-level
field) to avoid micro-dollar division.

Spend handling choice
----------------------
This connector uses ``SPEND_IN_DOLLAR`` — a direct float/string in the account
currency — rather than ``SPEND_IN_MICRO_DOLLAR`` (which would require dividing
by 1,000,000).  Rationale: ``SPEND_IN_DOLLAR`` is the canonical spend field
in the Pinterest Ads analytics response, it aligns with how Meta/LinkedIn/TikTok
return spend, and it avoids integer overflow edge cases at very high spend
levels.  If a future API version deprecates ``SPEND_IN_DOLLAR``,
the fallback is: ``Decimal(str(row["SPEND_IN_MICRO_DOLLAR"])) / 1_000_000``.

Columns requested:
    SPEND_IN_DOLLAR, IMPRESSION_1, PIN_CLICK, OUTBOUND_CLICK, TOTAL_CONVERSIONS

Field terminology:
- ``IMPRESSION_1`` → impressions (served impressions for the campaign)
- ``PIN_CLICK`` → clicks (clicks on the pin to expand or engage)
- ``TOTAL_CONVERSIONS`` → total attributed conversions (all conversion types)
- ``SPEND_IN_DOLLAR`` → spend (total billed cost in account currency)

Response structure
------------------
The API returns a JSON array of campaign analytics objects:
[
  {
    "CAMPAIGN_ID": "549755885175",
    "DATE": "2024-06-01",
    "SPEND_IN_DOLLAR": "145.72",
    "IMPRESSION_1": 98000,
    "PIN_CLICK": 2340,
    "TOTAL_CONVERSIONS": 52,
    "OUTBOUND_CLICK": 1980
  },
  ...
]

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 90 days (Pinterest analytics API limit is 90 days per request).
- Write support: no (read-only).

Rate limits
-----------
- Pinterest Ads API: 1,000 requests per hour per user.
- This connector uses 60 RPM as a conservative default.

API version
-----------
Targets ``v5`` of the Pinterest API.  Update ``_API_VERSION`` to upgrade.

Pinterest Ads API reference
----------------------------
https://developers.pinterest.com/docs/api/v5/ad_account-analytics/
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

_API_VERSION = "v5"
_OAUTH_AUTH_URL = "https://www.pinterest.com/oauth/"
_OAUTH_TOKEN_URL = f"https://api.pinterest.com/{_API_VERSION}/oauth/token"
_OAUTH_SCOPE = "ads:read user_accounts:read"

_ANALYTICS_URL = (
    "https://api.pinterest.com/{ver}/ad_accounts/{account_id}/campaigns/analytics"
)

# Spend column choice: SPEND_IN_DOLLAR (direct currency value, not micros).
# See module docstring for the rationale.
_SPEND_COLUMN = "SPEND_IN_DOLLAR"
_MICROS_DIVISOR = Decimal("1000000")

_COLUMNS = [
    _SPEND_COLUMN,
    "IMPRESSION_1",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
    "TOTAL_CONVERSIONS",
]


# ── Connector ─────────────────────────────────────────────────────────────────


class PinterestAdsConnector(Connector):
    """Pinterest Ads connector — daily campaign metrics via the Ads API.

    Uses OAuth 2.0 Bearer token authentication.  Credential lookup from
    ``ConnectorConfig.extra`` (Vault-injected in production).

    Expected ``config.extra`` keys:
        ``access_token``, ``refresh_token``, ``client_id``, ``client_secret``,
        ``ad_account_id``, ``currency`` (optional).

    Spend handling:
        Uses ``SPEND_IN_DOLLAR`` (direct currency string → Decimal).
        If the field is absent and ``SPEND_IN_MICRO_DOLLAR`` is present, the
        fallback divides by 1,000,000.  See module docstring for full rationale.
    """

    platform_key = "pinterest_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        """Read a credential from config.extra (Vault-injected at runtime)."""
        return str(self.config.extra.get(key, default))

    def _ad_account_id(self) -> str:
        return self._get_secret("ad_account_id") or self.config.external_account_id

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization header for every Pinterest API request."""
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _analytics_url(self) -> str:
        return _ANALYTICS_URL.format(
            ver=_API_VERSION,
            account_id=self._ad_account_id(),
        )

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the Pinterest OAuth2 consent URL for the ads:read scope.

        Pure helper — no network calls.

        Parameters
        ----------
        client_id:
            Pinterest application client ID.
        redirect_uri:
            URI Pinterest will redirect to after consent.
        state:
            CSRF protection token (opaque; round-tripped by Pinterest).
        """
        import urllib.parse

        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _OAUTH_SCOPE,
        }
        if state:
            params["state"] = state
        return f"{_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _do_refresh_token(self) -> str:
        """Exchange the stored refresh_token for a new access token.

        Returns the new ``access_token`` string.
        """
        import base64

        client_id = self._get_secret("client_id")
        client_secret = self._get_secret("client_secret")
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode()
        ).decode()

        resp = httpx.post(
            _OAUTH_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._get_secret("refresh_token"),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Token refresh returned no access_token. "
                f"Response: {data}"
            )
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Load or refresh the access token from ``config.extra``.

        If ``access_token`` is present in config.extra, it is used directly
        (Vault broker pre-injected a fresh token).  If absent, the
        ``refresh_token`` is used to obtain a new access token.

        Raises
        ------
        RuntimeError
            If neither ``access_token`` nor required refresh credentials are present.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        """
        direct_token = self._get_secret("access_token")
        if direct_token:
            self._access_token = direct_token
            logger.info(
                "%s Authenticated with pre-injected Pinterest access token.",
                self._log_prefix(),
            )
            return

        required = ("refresh_token", "client_id", "client_secret")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "Provide access_token or refresh_token+client_id+client_secret "
                "in config.extra (injected by Vault broker)."
            )
        self._access_token = self._do_refresh_token()
        logger.info(
            "%s Authenticated via Pinterest token refresh.", self._log_prefix()
        )

    def refresh_token(self) -> None:
        """Proactively refresh the access token before the 1-hour expiry.

        Called by the OAuth Broker ~5 minutes before expiry.
        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._do_refresh_token()
        logger.info(
            "%s Token refreshed proactively. TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return accessible ad accounts under the authenticated credentials.

        Calls ``GET /v5/ad_accounts`` to list accounts the token can access.

        Returns
        -------
        list[dict]
            Each entry has ``id``, ``name``, and ``currency``.
        """
        resp = httpx.get(
            f"https://api.pinterest.com/{_API_VERSION}/ad_accounts",
            headers=self._auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        accounts: list[dict[str, Any]] = []
        for item in body.get("items", []):
            accounts.append(
                {
                    "id": str(item.get("id", "")),
                    "name": str(item.get("name", "")),
                    "currency": str(item.get("currency", "USD")),
                }
            )
        return accounts

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch daily campaign analytics from the Pinterest Ads API.

        Issues a GET request to
        ``/v5/ad_accounts/{account_id}/campaigns/analytics`` with
        ``granularity=DAY`` and the full column set.  Pinterest returns all
        rows for the date range in a single response (no cursor pagination on
        this endpoint; max 90-day window per request).

        Parameters
        ----------
        stream:
            Must be ``"daily_campaign_metrics"``.
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            Raw analytics objects from the response array, each containing
            ``CAMPAIGN_ID``, ``DATE``, ``SPEND_IN_DOLLAR``, ``IMPRESSION_1``,
            ``PIN_CLICK``, ``TOTAL_CONVERSIONS``, etc.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        params: dict[str, Any] = {
            "start_date": since.isoformat(),
            "end_date": until.isoformat(),
            "columns": ",".join(_COLUMNS),
            "granularity": "DAY",
        }

        resp = httpx.get(
            self._analytics_url(),
            headers=self._auth_headers(),
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        body: Any = resp.json()

        # The endpoint returns a JSON array at the top level
        rows: list[dict[str, Any]] = body if isinstance(body, list) else body.get("items", [])

        if rows:
            latest = max(
                date.fromisoformat(r["DATE"]) for r in rows if "DATE" in r
            )
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
    def _extract_spend(row: dict[str, Any]) -> Decimal:
        """Extract spend from a Pinterest analytics row.

        Prefers ``SPEND_IN_DOLLAR`` (direct currency string → Decimal).
        Falls back to ``SPEND_IN_MICRO_DOLLAR`` divided by 1,000,000 if the
        dollar field is absent.

        Parameters
        ----------
        row:
            A single Pinterest analytics object.

        Returns
        -------
        Decimal
            Spend in account currency.
        """
        if "SPEND_IN_DOLLAR" in row and row["SPEND_IN_DOLLAR"] is not None:
            return Decimal(str(row["SPEND_IN_DOLLAR"]))
        if "SPEND_IN_MICRO_DOLLAR" in row and row["SPEND_IN_MICRO_DOLLAR"] is not None:
            return Decimal(str(row["SPEND_IN_MICRO_DOLLAR"])) / _MICROS_DIVISOR
        return Decimal("0")

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Pinterest analytics rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        Pinterest field          → UnifiedRecord field
        ``CAMPAIGN_ID``          → ``campaign_id``
        ``DATE``                 → ``date_key`` (YYYY-MM-DD → date)
        ``IMPRESSION_1`` (int)   → ``impressions``
        ``PIN_CLICK`` (int)      → ``clicks``
        ``SPEND_IN_DOLLAR`` (str)→ ``cost_raw`` (Decimal, account currency)
        ``TOTAL_CONVERSIONS``    → ``conversions`` (Decimal)
        account currency         → ``cost_ccy`` / ``conversion_value_ccy``

        Spend: Uses ``SPEND_IN_DOLLAR`` — a direct decimal string in the
        account currency.  If absent, falls back to
        ``SPEND_IN_MICRO_DOLLAR / 1_000_000``.  See ``_extract_spend()``.

        Campaign name: not returned in the analytics endpoint.  Set to
        ``"(not set)"`` per SDK convention.

        Ad-set and ad grain are not present at campaign-level analytics;
        set to ``"(not set)"``.

        Conversion value: Pinterest analytics does not expose an order revenue
        metric in the standard column set.  Set to Decimal("0").
        """
        records: list[UnifiedRecord] = []
        account_id = self._ad_account_id()
        currency = self._currency()

        for row in raw:
            date_key = date.fromisoformat(str(row.get("DATE", "1970-01-01")))

            campaign_id = str(row.get("CAMPAIGN_ID", "(not set)"))
            if not campaign_id:
                campaign_id = "(not set)"

            cost_raw = self._extract_spend(row)

            # IMPRESSION_1 and PIN_CLICK are integers in the API response
            impressions = int(row.get("IMPRESSION_1", 0))
            clicks = int(row.get("PIN_CLICK", 0))

            conversions = Decimal(str(row.get("TOTAL_CONVERSIONS", 0)))

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    campaign_id=campaign_id,
                    # Analytics endpoint does not include campaign names
                    campaign_name="(not set)",
                    adset_id="(not set)",
                    adset_name="(not set)",
                    ad_id="(not set)",
                    ad_name="(not set)",
                    impressions=impressions,
                    clicks=clicks,
                    cost_raw=cost_raw,
                    cost_ccy=currency,
                    conversions=conversions,
                    # Pinterest analytics does not expose purchase revenue value
                    conversion_value_raw=Decimal("0"),
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
            ``{"daily_campaign_metrics": "YYYY-MM-DD"}`` — latest date seen.
            Empty dict if no fetch has been completed in this instance's lifetime.
        """
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        """Return the capability descriptor for the Pinterest Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            # Pinterest analytics API: 90-day max window per request.
            # Scheduler must split longer backfills into 90-day chunks.
            max_backfill_days=90,
            # Pinterest Ads API: 1,000 requests per hour per user.
            # 60 RPM is a conservative safe default.
            rate_limit_rpm=60,
        )
