"""LinkedIn Ads connector for AYAZ.

Connects to the LinkedIn Marketing API ``adAnalytics`` endpoint to pull daily
campaign-level metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``access_token``
    OAuth 2.0 access token obtained via LinkedIn's authorization code flow.
    Passed as ``Authorization: Bearer <access_token>`` on every request.
``refresh_token``
    Long-lived refresh token used to obtain a new access token before expiry.
    LinkedIn access tokens last 60 days; refresh tokens last 365 days.
``client_id``
    OAuth 2.0 client ID from the LinkedIn Developer application.
``client_secret``
    OAuth 2.0 client secret for the same application.
``ad_account_id``
    The LinkedIn Ads account (sponsoredAccount) URN number, e.g. ``"503887890"``.
    The connector formats this as ``urn:li:sponsoredAccount:<id>`` in API calls.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"USD"``).  Defaults to ``"USD"``.

OAuth 2.0 flow
--------------
1. Redirect the advertiser to
   ``https://www.linkedin.com/oauth/v2/authorization``
   with scope ``r_ads_reporting`` (and ``r_ads`` for account discovery).
2. Exchange the authorization code at
   ``POST https://www.linkedin.com/oauth/v2/accessToken``
   for ``access_token`` and ``refresh_token``.
3. Store tokens in Vault.
4. Refresh via the same token endpoint with ``grant_type=refresh_token`` before
   the 60-day access token expiry.

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Endpoint: ``GET https://api.linkedin.com/v2/adAnalytics``
- Query params: ``q=analytics``, ``pivot=CAMPAIGN``, ``timeGranularity=DAILY``,
  ``dateRange.start.day/month/year``, ``dateRange.end.day/month/year``.
- Fields: ``costInLocalCurrency``, ``impressions``, ``clicks``,
  ``externalWebsiteConversions``.
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 365 days (LinkedIn keeps ~2 years; 365 is a conservative limit).
- Write support: no (read-only).

Spend handling
--------------
LinkedIn returns ``costInLocalCurrency`` as a decimal string already in the
account's local currency (e.g. ``"145.72"``).  No micro-conversion is needed.
We parse it directly with ``Decimal``.

Date representation
-------------------
LinkedIn returns dates inside a ``dateRange`` object with nested ``start`` and
``end`` sub-objects each containing ``day``, ``month``, ``year`` integer fields.
``date_key`` is constructed from the ``start`` sub-object (daily granularity
means start == end for each row).

Rate limits
-----------
- LinkedIn Marketing API: ~500 requests per day per application.
- No per-minute cap is documented; the connector uses 60 RPM as a safe default.
  The scheduler must monitor daily usage against the 500/day quota.

API version
-----------
Targets the LinkedIn v2 REST API.  The ``adAnalytics`` endpoint is stable
and does not use a versioned path segment.

LinkedIn Marketing API reference
---------------------------------
https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting
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

_OAUTH_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_OAUTH_SCOPE = "r_ads_reporting r_ads"

_ANALYTICS_URL = "https://api.linkedin.com/v2/adAnalytics"

# Fields to request from the adAnalytics endpoint
_FIELDS = (
    "costInLocalCurrency,"
    "impressions,"
    "clicks,"
    "externalWebsiteConversions,"
    "dateRange,"
    "pivotValues"
)


# ── Connector ─────────────────────────────────────────────────────────────────


class LinkedInAdsConnector(Connector):
    """LinkedIn Ads connector — daily campaign metrics via the Marketing API.

    Uses OAuth 2.0 Bearer token authentication.  Credential lookup from
    ``ConnectorConfig.extra`` (Vault-injected in production).

    Expected ``config.extra`` keys:
        ``access_token``, ``refresh_token``, ``client_id``, ``client_secret``,
        ``ad_account_id``, ``currency`` (optional).
    """

    platform_key = "linkedin_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        """Read a credential from config.extra (Vault-injected at runtime)."""
        return str(self.config.extra.get(key, default))

    def _ad_account_id(self) -> str:
        """Return the numeric portion of the LinkedIn sponsoredAccount ID."""
        return self._get_secret("ad_account_id") or self.config.external_account_id

    def _account_urn(self) -> str:
        """Return the full LinkedIn URN for the ad account."""
        return f"urn:li:sponsoredAccount:{self._ad_account_id()}"

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization header for every LinkedIn API request."""
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the LinkedIn OAuth2 consent URL for ads reporting scope.

        Pure helper — no network calls.

        Parameters
        ----------
        client_id:
            LinkedIn application client ID.
        redirect_uri:
            URI LinkedIn will redirect to after consent (must be registered
            in the LinkedIn Developer application).
        state:
            CSRF protection token (opaque; round-tripped by LinkedIn).
        """
        import urllib.parse

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": _OAUTH_SCOPE,
        }
        if state:
            params["state"] = state
        return f"{_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _do_refresh_token(self) -> str:
        """POST to LinkedIn's token endpoint to exchange refresh_token for access_token.

        Returns the new ``access_token`` string.
        Kept structural; separated so authenticate() and refresh_token() share logic.
        """
        resp = httpx.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._get_secret("refresh_token"),
                "client_id": self._get_secret("client_id"),
                "client_secret": self._get_secret("client_secret"),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Token exchange returned no access_token. "
                f"Response: {data}"
            )
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Load or refresh the access token from ``config.extra``.

        If ``access_token`` is present in config.extra it is used directly
        (Vault broker pre-injected a fresh token).  If absent, the ``refresh_token``
        is used to obtain a new access token via the LinkedIn token endpoint.

        Raises
        ------
        RuntimeError
            If neither ``access_token`` nor ``refresh_token`` is present.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        """
        direct_token = self._get_secret("access_token")
        if direct_token:
            self._access_token = direct_token
            logger.info(
                "%s Authenticated with pre-injected LinkedIn access token.",
                self._log_prefix(),
            )
            return

        # Fall back to refresh flow
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
            "%s Authenticated via LinkedIn token refresh.", self._log_prefix()
        )

    def refresh_token(self) -> None:
        """Proactively refresh the access token before the 60-day expiry.

        Called by the OAuth Broker ~5 days before expiry.
        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._do_refresh_token()
        logger.info(
            "%s Token refreshed proactively. TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return accessible ad accounts under the authenticated credentials.

        Calls ``GET /v2/adAccountsV2`` to list sponsored accounts accessible
        to the authenticated user.

        Returns
        -------
        list[dict]
            Each entry has ``id``, ``name``, ``currency``, and ``status``.
        """
        resp = httpx.get(
            "https://api.linkedin.com/v2/adAccountsV2",
            headers=self._auth_headers(),
            params={"q": "search", "search.type.values[0]": "BUSINESS"},
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        accounts: list[dict[str, Any]] = []
        for element in body.get("elements", []):
            acct_id = str(element.get("id", ""))
            accounts.append(
                {
                    "id": acct_id,
                    "name": str(element.get("name", "")),
                    "currency": str(element.get("currency", "USD")),
                    "status": str(element.get("status", "")),
                }
            )
        return accounts

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch raw campaign metrics from the LinkedIn adAnalytics endpoint.

        Issues a GET request with ``q=analytics``, ``pivot=CAMPAIGN``,
        ``timeGranularity=DAILY``.  LinkedIn does not paginate this endpoint
        with cursor tokens; it returns all rows for the date range in a single
        ``elements`` list (practical limit ~1000 rows per call; for large
        accounts split by shorter date ranges).

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
            Raw element dicts from the ``elements`` array, each containing
            ``dateRange``, ``pivotValues``, ``costInLocalCurrency``,
            ``impressions``, ``clicks``, ``externalWebsiteConversions``.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        params: dict[str, Any] = {
            "q": "analytics",
            "pivot": "CAMPAIGN",
            "timeGranularity": "DAILY",
            "accounts[0]": self._account_urn(),
            "dateRange.start.day": since.day,
            "dateRange.start.month": since.month,
            "dateRange.start.year": since.year,
            "dateRange.end.day": until.day,
            "dateRange.end.month": until.month,
            "dateRange.end.year": until.year,
            "fields": _FIELDS,
        }

        resp = httpx.get(
            _ANALYTICS_URL,
            headers=self._auth_headers(),
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        rows: list[dict[str, Any]] = body.get("elements", [])

        if rows:
            # Extract date from the dateRange.start sub-object
            latest = max(
                date(
                    r["dateRange"]["start"]["year"],
                    r["dateRange"]["start"]["month"],
                    r["dateRange"]["start"]["day"],
                )
                for r in rows
                if "dateRange" in r and "start" in r["dateRange"]
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
    def _parse_date_from_range(date_range: dict[str, Any]) -> date:
        """Extract a ``date`` from a LinkedIn ``dateRange.start`` sub-object.

        Parameters
        ----------
        date_range:
            The full ``dateRange`` object (containing a ``start`` sub-dict with
            ``day``, ``month``, ``year`` integer fields).

        Returns
        -------
        date
            UTC calendar date constructed from the ``start`` sub-object.
        """
        start = date_range.get("start", {})
        return date(
            int(start.get("year", 1970)),
            int(start.get("month", 1)),
            int(start.get("day", 1)),
        )

    @staticmethod
    def _extract_campaign_id(pivot_values: list[str]) -> str:
        """Extract the campaign ID from LinkedIn's pivotValues list.

        LinkedIn returns pivot values as a list of URN strings:
        ``["urn:li:sponsoredCampaign:123456789"]``.  We strip the URN prefix
        and return the numeric ID string.

        Parameters
        ----------
        pivot_values:
            The ``pivotValues`` list from an analytics element.

        Returns
        -------
        str
            Numeric campaign ID, or ``"(not set)"`` if absent/unparseable.
        """
        if not pivot_values:
            return "(not set)"
        urn = pivot_values[0]
        # URN format: "urn:li:sponsoredCampaign:<id>"
        parts = urn.split(":")
        return parts[-1] if parts else "(not set)"

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map LinkedIn adAnalytics elements to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        LinkedIn API field              → UnifiedRecord field
        ``pivotValues[0]`` (URN)        → ``campaign_id`` (numeric, stripped of URN)
        ``dateRange.start``             → ``date_key`` (UTC)
        ``impressions`` (int)           → ``impressions``
        ``clicks`` (int)                → ``clicks``
        ``costInLocalCurrency`` (str)   → ``cost_raw`` (Decimal, account currency)
        ``externalWebsiteConversions``  → ``conversions`` (Decimal)
        account currency (from config)  → ``cost_ccy`` / ``conversion_value_ccy``

        Spend: LinkedIn returns ``costInLocalCurrency`` as a decimal string already
        in the account's local currency (NOT micros).  Direct Decimal conversion.

        Campaign name: the adAnalytics endpoint does not return campaign names
        inline; the name requires a separate call to the campaigns endpoint.
        Set to ``"(not set)"`` per SDK convention.

        Ad-set and ad grain are not fetched at CAMPAIGN pivot level; set to
        ``"(not set)"``.

        Conversion value: LinkedIn does not return a purchase value metric in
        the adAnalytics endpoint for campaign-level queries.  Set to Decimal("0").
        """
        records: list[UnifiedRecord] = []
        account_id = self._ad_account_id()
        currency = self._currency()

        for row in raw:
            date_range = row.get("dateRange", {})
            date_key = self._parse_date_from_range(date_range)

            pivot_values = row.get("pivotValues", [])
            campaign_id = self._extract_campaign_id(pivot_values)

            # costInLocalCurrency is a decimal string; direct Decimal conversion
            cost_str = str(row.get("costInLocalCurrency", "0"))
            cost_raw = Decimal(cost_str)

            impressions = int(row.get("impressions", 0))
            clicks = int(row.get("clicks", 0))

            # externalWebsiteConversions is an int in the API; wrap in Decimal
            conversions = Decimal(str(row.get("externalWebsiteConversions", 0)))

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    campaign_id=campaign_id,
                    # adAnalytics does not return campaign names inline
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
                    # LinkedIn adAnalytics does not expose purchase value at
                    # campaign level; ETL worker enriches if needed.
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
        """Return the capability descriptor for the LinkedIn Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # LinkedIn Marketing API: ~500 requests/day per application.
            # 60 RPM is conservative; monitor daily quota separately.
            rate_limit_rpm=60,
        )
