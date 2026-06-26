"""Microsoft Advertising (Bing Ads) connector for AYAZ.

Connects to the Microsoft Advertising Reporting API to pull daily campaign-level
metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``client_id``
    OAuth 2.0 client ID from the Microsoft Azure AD application registered for
    the Microsoft Advertising API.
``client_secret``
    OAuth 2.0 client secret for the same application.
``refresh_token``
    Long-lived refresh token obtained via the OAuth 2.0 authorization code flow.
    Microsoft Advertising refresh tokens do not expire if used at least once
    every 90 days.
``developer_token``
    Microsoft Advertising developer token issued to your manager account.
    Required in every API request header (``DeveloperToken``).
``customer_id``
    The Microsoft Advertising customer (manager) ID that owns the target account.
``account_id``
    The Microsoft Advertising account ID (``AccountId``) whose data is synced.
    Numeric string, e.g. ``"12345678"``.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"USD"``).  Defaults to ``"USD"``.

OAuth 2.0 flow
--------------
1. Redirect the advertiser to the Microsoft identity platform consent URL:
   ``https://login.microsoftonline.com/common/oauth2/v2.0/authorize``
   with scope ``https://ads.microsoft.com/msads.manage offline_access``.
2. Exchange the authorization code at
   ``POST https://login.microsoftonline.com/common/oauth2/v2.0/token``.
3. Store ``access_token`` (expires in ~1 hour) and ``refresh_token`` in Vault.
4. Refresh via the same token endpoint with ``grant_type=refresh_token``.

Reporting model (Microsoft Advertising)
---------------------------------------
Microsoft Advertising uses an asynchronous three-step reporting model in its
SOAP/REST API, but this connector uses a simplified synchronous row-based JSON
approach suitable for the AYAZ integration layer:

1. The ``fetch()`` method posts a report request (ReportRequest SOAP envelope or
   REST equivalent) specifying ``CampaignPerformanceReport``,
   ``ReportAggregation=Daily``, and the column set: ``TimePeriod``,
   ``CampaignId``, ``CampaignName``, ``Impressions``, ``Clicks``, ``Spend``,
   ``Conversions``.
2. For normalize() and testing purposes this connector assumes the report has
   already been downloaded and parsed into a row-based JSON list where each
   element is a dict mapping column names to values (strings, as Microsoft
   Advertising CSV exports are string-typed).

In production the fetch() method would:
  a. Submit the report request (POST) → receive a ``reportRequestId``.
  b. Poll ``GET /v13/Reporting/operations/{reportRequestId}`` until status
     is ``Success``.
  c. Download the report CSV from the ``reportDownloadUrl``.
  d. Parse the CSV into the row-based dict format normalized here.

This three-step model is intentionally abstracted behind ``fetch()``; normalize()
is kept pure and tested against the JSON fixture.

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Report: ``CampaignPerformanceReportRequest`` (Daily aggregation).
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 365 days.
- Write support: no (read-only).

Spend handling
--------------
Microsoft Advertising returns ``Spend`` as a decimal string in the account
currency (e.g. ``"123.45"``).  No micro-conversion is needed.  Direct Decimal
conversion.

Rate limits
-----------
- Microsoft Advertising: 10 concurrent report requests per customer, up to
  1,000 queued requests per day.
- This connector uses 60 RPM as a conservative default.

API version
-----------
Targets v13 of the Microsoft Advertising Reporting API.

Microsoft Advertising Reporting API reference
----------------------------------------------
https://learn.microsoft.com/en-us/advertising/reporting-service/reportingservice
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

_OAUTH_AUTH_URL = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
)
_OAUTH_TOKEN_URL = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/token"
)
_OAUTH_SCOPE = "https://ads.microsoft.com/msads.manage offline_access"

_API_VERSION = "v13"
_REPORTING_URL = (
    f"https://reporting.api.bingads.microsoft.com/Reporting/{_API_VERSION}/"
    "operations"
)


# ── Connector ─────────────────────────────────────────────────────────────────


class MicrosoftAdsConnector(Connector):
    """Microsoft Advertising (Bing Ads) connector — daily campaign metrics.

    Uses OAuth 2.0 Bearer token + developer token header authentication.
    Credential lookup from ``ConnectorConfig.extra`` (Vault-injected in production).

    Expected ``config.extra`` keys:
        ``access_token`` (optional; if absent, obtained via refresh),
        ``refresh_token``, ``client_id``, ``client_secret``,
        ``developer_token``, ``customer_id``, ``account_id``,
        ``currency`` (optional).
    """

    platform_key = "microsoft_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        """Read a credential from config.extra (Vault-injected at runtime)."""
        return str(self.config.extra.get(key, default))

    def _account_id(self) -> str:
        return self._get_secret("account_id") or self.config.external_account_id

    def _customer_id(self) -> str:
        return self._get_secret("customer_id")

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        """Build the request headers required by every Microsoft Advertising call.

        Microsoft Advertising requires both a Bearer token and a DeveloperToken
        header on every authenticated API request.
        """
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "DeveloperToken": self._get_secret("developer_token"),
            "CustomerId": self._customer_id(),
            "CustomerAccountId": self._account_id(),
            "Content-Type": "application/json",
        }

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the Microsoft identity platform consent URL.

        Pure helper — no network calls.

        Parameters
        ----------
        client_id:
            Azure AD application (client) ID.
        redirect_uri:
            URI Microsoft will redirect to after consent.
        state:
            CSRF protection token (opaque; round-tripped by Microsoft).
        """
        import urllib.parse

        params: dict[str, str] = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": _OAUTH_SCOPE,
        }
        if state:
            params["state"] = state
        return f"{_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _do_refresh_token(self) -> str:
        """Exchange the stored refresh_token for a new access token.

        Returns the new ``access_token`` string.
        """
        resp = httpx.post(
            _OAUTH_TOKEN_URL,
            data={
                "client_id": self._get_secret("client_id"),
                "client_secret": self._get_secret("client_secret"),
                "grant_type": "refresh_token",
                "refresh_token": self._get_secret("refresh_token"),
                "scope": _OAUTH_SCOPE,
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

        If ``access_token`` is present in config.extra, it is used directly.
        Otherwise the ``refresh_token`` is used to obtain a fresh one.

        Raises
        ------
        RuntimeError
            If required credentials are absent from config.extra.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        """
        direct_token = self._get_secret("access_token")
        if direct_token:
            self._access_token = direct_token
            logger.info(
                "%s Authenticated with pre-injected Microsoft Ads access token.",
                self._log_prefix(),
            )
            return

        required = ("refresh_token", "client_id", "client_secret", "developer_token")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "Provide access_token or refresh_token+client_id+client_secret "
                "+developer_token in config.extra (injected by Vault broker)."
            )
        self._access_token = self._do_refresh_token()
        logger.info(
            "%s Authenticated via Microsoft Ads token refresh.", self._log_prefix()
        )

    def refresh_token(self) -> None:
        """Proactively refresh the access token (Microsoft tokens expire in ~1 hour).

        Called by the OAuth Broker before expiry.
        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._do_refresh_token()
        logger.info(
            "%s Token refreshed proactively. TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return accessible ad accounts under the authenticated credentials.

        Calls the Microsoft Advertising Customer Management API to list
        accounts accessible to the authenticated user.

        Returns
        -------
        list[dict]
            Each entry has ``id``, ``name``, and ``currency``.
        """
        resp = httpx.get(
            "https://clientcenter.api.bingads.microsoft.com/CustomerManagement"
            f"/{_API_VERSION}/Accounts",
            headers=self._auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        accounts: list[dict[str, Any]] = []
        for acct in body.get("Accounts", []):
            accounts.append(
                {
                    "id": str(acct.get("Id", "")),
                    "name": str(acct.get("Name", "")),
                    "currency": str(acct.get("CurrencyCode", "USD")),
                }
            )
        return accounts

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch daily campaign performance rows from Microsoft Advertising.

        In production this submits a ``CampaignPerformanceReportRequest`` to the
        Reporting API, polls for completion, downloads the CSV, and parses it
        into the row-based JSON format consumed by ``normalize()``.

        Each row dict uses the Microsoft Advertising column name as the key and
        a string value.  Required keys per row: ``TimePeriod``, ``CampaignId``,
        ``CampaignName``, ``Spend``, ``Impressions``, ``Clicks``, ``Conversions``.

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
            Row-based dicts, each mapping column names to string values.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        # Step 1: Submit report request
        report_request: dict[str, Any] = {
            "ReportRequest": {
                "ExcludeColumnHeaders": False,
                "ExcludeReportFooter": True,
                "ExcludeReportHeader": True,
                "Format": "Csv",
                "ReportName": "AYAZ_DailyCampaign",
                "ReturnOnlyCompleteData": False,
                "Type": "CampaignPerformanceReportRequest",
                "Aggregation": "Daily",
                "Columns": [
                    "TimePeriod", "CampaignId", "CampaignName",
                    "Impressions", "Clicks", "Spend", "Conversions",
                ],
                "Scope": {
                    "AccountIds": [int(self._account_id())],
                },
                "Time": {
                    "CustomDateRangeStart": {
                        "Day": since.day, "Month": since.month, "Year": since.year,
                    },
                    "CustomDateRangeEnd": {
                        "Day": until.day, "Month": until.month, "Year": until.year,
                    },
                },
            }
        }

        submit_resp = httpx.post(
            _REPORTING_URL,
            headers=self._auth_headers(),
            json=report_request,
            timeout=60,
        )
        submit_resp.raise_for_status()
        operation: dict[str, Any] = submit_resp.json()
        report_request_id: str = operation.get("reportRequestId", "")

        # Step 2: Poll for completion (simplified; real implementation uses retry loop)
        poll_url = f"{_REPORTING_URL}/{report_request_id}"
        status_resp = httpx.get(poll_url, headers=self._auth_headers(), timeout=60)
        status_resp.raise_for_status()
        status_body: dict[str, Any] = status_resp.json()

        download_url: str = status_body.get("reportDownloadUrl", "")
        if not download_url:
            raise RuntimeError(
                f"{self._log_prefix()} Report not ready or no download URL. "
                f"Status: {status_body}"
            )

        # Step 3: Download and parse CSV into row-based dicts
        download_resp = httpx.get(download_url, timeout=120)
        download_resp.raise_for_status()
        rows = self._parse_csv_report(download_resp.text)

        if rows:
            latest = max(
                date.fromisoformat(r["TimePeriod"]) for r in rows
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
    def _parse_csv_report(csv_text: str) -> list[dict[str, str]]:
        """Parse a Microsoft Advertising report CSV into row dicts.

        The CSV has a header row followed by data rows.  Each data row is
        mapped to a dict keyed by the column headers.  Empty lines and the
        final summary row (if present) are skipped.

        Parameters
        ----------
        csv_text:
            Raw CSV text from the report download endpoint.

        Returns
        -------
        list[dict[str, str]]
            One dict per data row.
        """
        import csv
        import io

        reader = csv.DictReader(io.StringIO(csv_text))
        rows: list[dict[str, str]] = []
        for row in reader:
            # Skip summary / total rows that Microsoft Advertising appends
            if not row.get("TimePeriod", "").strip():
                continue
            rows.append(dict(row))
        return rows

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Microsoft Advertising row dicts to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        MS Ads column        → UnifiedRecord field
        ``CampaignId``       → ``campaign_id``
        ``CampaignName``     → ``campaign_name``
        ``TimePeriod``       → ``date_key`` (YYYY-MM-DD string → date)
        ``Impressions`` (str)→ ``impressions`` (int)
        ``Clicks`` (str)     → ``clicks`` (int)
        ``Spend`` (str)      → ``cost_raw`` (Decimal, account currency)
        ``Conversions`` (str)→ ``conversions`` (Decimal)
        account currency     → ``cost_ccy`` / ``conversion_value_ccy``

        Spend: Microsoft Advertising reports ``Spend`` as a decimal string in
        the account currency (NOT micros).  Direct Decimal conversion.

        Ad-set and ad grain are not present at campaign-level report scope;
        set to ``"(not set)"``.

        Conversion value: not included in the default CampaignPerformanceReport
        column set; set to Decimal("0").
        """
        records: list[UnifiedRecord] = []
        account_id = self._account_id()
        currency = self._currency()

        for row in raw:
            date_str = str(row.get("TimePeriod", "1970-01-01")).strip()
            date_key = date.fromisoformat(date_str)

            campaign_id = str(row.get("CampaignId", "(not set)")).strip()
            if not campaign_id:
                campaign_id = "(not set)"
            campaign_name = str(row.get("CampaignName", "(not set)")).strip()
            if not campaign_name:
                campaign_name = "(not set)"

            # Spend is a decimal string; strip any currency symbols / commas
            spend_str = str(row.get("Spend", "0")).replace(",", "").strip()
            cost_raw = Decimal(spend_str) if spend_str else Decimal("0")

            impressions_str = str(row.get("Impressions", "0")).replace(",", "").strip()
            impressions = int(impressions_str) if impressions_str else 0

            clicks_str = str(row.get("Clicks", "0")).replace(",", "").strip()
            clicks = int(clicks_str) if clicks_str else 0

            conversions_str = str(row.get("Conversions", "0")).replace(",", "").strip()
            conversions = Decimal(conversions_str) if conversions_str else Decimal("0")

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    adset_id="(not set)",
                    adset_name="(not set)",
                    ad_id="(not set)",
                    ad_name="(not set)",
                    impressions=impressions,
                    clicks=clicks,
                    cost_raw=cost_raw,
                    cost_ccy=currency,
                    conversions=conversions,
                    # CampaignPerformanceReport does not expose revenue value
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
        """Return the capability descriptor for the Microsoft Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # Microsoft Advertising: 10 concurrent report requests per customer;
            # 60 RPM is a conservative default.
            rate_limit_rpm=60,
        )
