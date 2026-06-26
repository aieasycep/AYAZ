"""TikTok Ads connector for AYAZ.

Connects to the TikTok Marketing API integrated reporting endpoint to pull
daily campaign-level metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``access_token``
    OAuth 2.0 access token obtained via TikTok's authorization code flow.
    Passed in the ``Access-Token`` request header (TikTok's non-standard header
    name — NOT a ``Bearer`` Authorization header).
``advertiser_id``
    TikTok advertiser account ID (numeric string), e.g. ``"6934259910082387968"``.
``api_version``  (optional)
    API version string, e.g. ``"v1.3"``.  Defaults to ``_API_VERSION``.
``currency``  (optional)
    ISO-4217 currency code for the account.  Defaults to ``"USD"``.
    TikTok returns ``spend`` in the advertiser's account currency.

OAuth 2.0 flow
--------------
1. Redirect the advertiser to
   ``https://business-api.tiktok.com/portal/auth?app_id=<APP_ID>&state=<STATE>&redirect_uri=<URI>``
2. Exchange the authorization code at
   ``POST https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/``
   for ``access_token`` and ``refresh_token`` (both in the ``data`` envelope).
3. Store tokens in Vault.
4. Refresh via ``POST /open_api/v1.3/oauth2/refresh_token/`` before the
   24-hour access token expiry.  TikTok access tokens expire after 24 hours;
   refresh tokens last 365 days.

Auth header
-----------
TikTok does NOT use the standard ``Authorization: Bearer <token>`` pattern.
Every API request must include:
    ``Access-Token: <access_token>``
as a custom request header.

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Endpoint: ``GET /open_api/v{VER}/report/integrated/get/``
- Dimensions: ``["campaign_id", "stat_time_day"]``
- Metrics: ``["spend", "impressions", "clicks", "conversions", "total_purchase_value"]``
- Granularity: daily.
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 365 days (TikTok keeps up to 397 days; 365 is a safe limit).
- Write support: no (read-only).

Spend handling
--------------
TikTok returns ``spend`` as a float-string already in the advertiser's account
currency (NOT micros).  We parse it directly with ``Decimal(str(...))``.

Conversion value
----------------
``total_purchase_value`` is the sum of purchase amounts attributed to the
campaign for the day.  This is the closest equivalent to Google's
``conversions_value`` for e-commerce and is mapped to ``conversion_value_raw``.
``conversions`` maps to the TikTok ``conversions`` metric (count of all
attributed conversion events, not just purchases).

Rate limits
-----------
- TikTok Marketing API: ~10 QPS per app per advertiser.
- This connector uses a conservative 120 RPM cap.

API version
-----------
Targets ``v1.3`` of the TikTok Marketing API.  Update ``_API_VERSION`` to upgrade.

TikTok Marketing API reference
-------------------------------
https://business-api.tiktok.com/portal/docs?id=1740302848100353
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

_API_VERSION = "v1.3"

# Integrated reporting endpoint
_REPORT_URL = (
    "https://business-api.tiktok.com/open_api/{ver}/report/integrated/get/"
)

# OAuth token exchange endpoints
_TOKEN_URL = "https://business-api.tiktok.com/open_api/{ver}/oauth2/access_token/"
_REFRESH_URL = (
    "https://business-api.tiktok.com/open_api/{ver}/oauth2/refresh_token/"
)

# Authorization portal URL (for AYAZ OAuth broker to redirect to)
_AUTH_PORTAL_URL = "https://business-api.tiktok.com/portal/auth"

# Dimensions requested
_DIMENSIONS = ["campaign_id", "stat_time_day"]

# Metrics requested
_METRICS = [
    "spend",
    "impressions",
    "clicks",
    "conversions",
    "total_purchase_value",
]

# Maximum rows per page (TikTok maximum is 1,000)
_PAGE_SIZE = 1_000


# ── Connector ─────────────────────────────────────────────────────────────────


class TikTokAdsConnector(Connector):
    """TikTok Ads connector — daily campaign metrics via Marketing API reporting.

    Uses the non-standard ``Access-Token`` header (not ``Authorization: Bearer``).
    See module docstring for full OAuth and field-mapping documentation.

    Expected ``config.extra`` keys:
        ``access_token``, ``advertiser_id``,
        ``api_version`` (optional), ``currency`` (optional),
        ``app_id`` (optional, used in token refresh), ``app_secret`` (optional).
    """

    platform_key = "tiktok_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        return str(self.config.extra.get(key, default))

    def _advertiser_id(self) -> str:
        return self._get_secret("advertiser_id") or self.config.external_account_id

    def _api_version(self) -> str:
        return self._get_secret("api_version", _API_VERSION)

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _access_token_header(self) -> dict[str, str]:
        """Build request headers with TikTok's custom Access-Token header."""
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Access-Token": self._access_token,
            "Content-Type": "application/json",
        }

    def _report_url(self) -> str:
        return _REPORT_URL.format(ver=self._api_version())

    def _token_url(self) -> str:
        return _TOKEN_URL.format(ver=self._api_version())

    def _refresh_url(self) -> str:
        return _REFRESH_URL.format(ver=self._api_version())

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        app_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the TikTok Business API authorization portal URL.

        Pure helper — no network calls.

        Parameters
        ----------
        app_id:
            TikTok app ID from the Developer Portal.
        redirect_uri:
            URI TikTok will redirect to after authorization.
        state:
            CSRF protection token.
        """
        import urllib.parse

        params: dict[str, str] = {
            "app_id": app_id,
            "redirect_uri": redirect_uri,
        }
        if state:
            params["state"] = state
        return f"{_AUTH_PORTAL_URL}?{urllib.parse.urlencode(params)}"

    def _do_exchange_token(self, auth_code: str) -> dict[str, Any]:
        """Exchange an authorization code for access and refresh tokens.

        Returns the ``data`` envelope from the TikTok token response.
        Kept structural; not exercised in fixture tests.
        """
        resp = httpx.post(
            self._token_url(),
            json={
                "app_id": self._get_secret("app_id"),
                "secret": self._get_secret("app_secret"),
                "auth_code": auth_code,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        if body.get("code") != 0:
            raise ValueError(
                f"{self._log_prefix()} TikTok token exchange failed: {body}"
            )
        return body.get("data", {})

    def _do_refresh_token(self) -> str:
        """Exchange the stored refresh token for a new access token.

        Returns the new ``access_token`` string.
        """
        resp = httpx.post(
            self._refresh_url(),
            json={
                "app_id": self._get_secret("app_id"),
                "secret": self._get_secret("app_secret"),
                "refresh_token": self._get_secret("refresh_token"),
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        if body.get("code") != 0:
            raise ValueError(
                f"{self._log_prefix()} TikTok token refresh failed: {body}"
            )
        token = body.get("data", {}).get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Token refresh returned no access_token."
            )
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Load the access token from ``config.extra``.

        TikTok access tokens expire after 24 hours.  The Vault broker injects
        a fresh token via ``config.extra['access_token']`` before each sync.
        The OAuth Broker must call ``refresh_token()`` proactively to rotate
        the token before it expires.

        Raises
        ------
        RuntimeError
            If ``access_token`` or ``advertiser_id`` are absent from config.extra.
        """
        required = ("access_token", "advertiser_id")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "These must be present in config.extra (injected by Vault broker)."
            )
        self._access_token = self._get_secret("access_token")
        logger.info("%s Authenticated with TikTok access token.", self._log_prefix())

    def refresh_token(self) -> None:
        """Refresh the access token using the stored refresh token.

        TikTok access tokens last 24 hours; refresh tokens last 365 days.
        Called proactively by the OAuth Broker before the 24-hour window closes.

        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        new_token = self._do_refresh_token()
        self._access_token = new_token
        logger.info(
            "%s Token refreshed. TODO: persist to Vault (Faz 1).", self._log_prefix()
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return advertiser accounts accessible via the current access token.

        Calls ``GET /open_api/v{VER}/oauth2/advertiser/get/`` which lists the
        advertiser IDs authorized for the app.

        Returns
        -------
        list[dict]
            Each entry has ``id``, ``name``, ``currency``, and ``timezone``.
        """
        resp = httpx.get(
            f"https://business-api.tiktok.com/open_api/{self._api_version()}"
            "/oauth2/advertiser/get/",
            headers=self._access_token_header(),
            params={
                "app_id": self._get_secret("app_id"),
                "secret": self._get_secret("app_secret"),
            },
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        advertisers: list[dict[str, Any]] = []
        for adv in body.get("data", {}).get("list", []):
            advertisers.append(
                {
                    "id": str(adv.get("advertiser_id", "")),
                    "name": str(adv.get("advertiser_name", "")),
                    "currency": str(adv.get("currency", "USD")),
                    "timezone": str(adv.get("timezone", "")),
                }
            )
        return advertisers

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch raw campaign metrics from the TikTok integrated reporting endpoint.

        Uses the ``GET /open_api/v{VER}/report/integrated/get/`` endpoint with
        daily granularity (``data_level=AUCTION_CAMPAIGN``) and paginates
        via ``page`` + ``page_size`` until all pages are exhausted.

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
            Flat list of row dicts.  Each dict contains:
            ``dimensions`` (sub-dict with ``campaign_id`` and ``stat_time_day``)
            and ``metrics`` (sub-dict with ``spend``, ``impressions``, ``clicks``,
            ``conversions``, ``total_purchase_value``).
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        base_params: dict[str, Any] = {
            "advertiser_id": self._advertiser_id(),
            "report_type": "BASIC",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": '["campaign_id","stat_time_day"]',
            "metrics": (
                '["spend","impressions","clicks","conversions","total_purchase_value"]'
            ),
            "start_date": since.isoformat(),
            "end_date": until.isoformat(),
            "page_size": str(_PAGE_SIZE),
        }

        rows: list[dict[str, Any]] = []
        page = 1

        while True:
            params = {**base_params, "page": str(page)}
            resp = httpx.get(
                self._report_url(),
                headers=self._access_token_header(),
                params=params,
                timeout=60,
            )
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

            if body.get("code") != 0:
                raise ValueError(
                    f"{self._log_prefix()} TikTok API error: {body}"
                )

            data = body.get("data", {})
            page_rows = data.get("list", [])
            rows.extend(page_rows)

            page_info = data.get("page_info", {})
            total_page = int(page_info.get("total_page", 1))
            if page >= total_page:
                break
            page += 1

        if rows:
            latest = max(
                date.fromisoformat(r["dimensions"]["stat_time_day"][:10])
                for r in rows
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
    def _parse_campaign_name(row: dict[str, Any]) -> str:
        """Extract campaign_name from a row dict.

        TikTok's integrated report does not return campaign_name in the default
        metric set.  The dimension ``campaign_id`` is available; name can be
        fetched separately via the campaign endpoint if needed.  We fall back to
        ``"(not set)"`` as the SDK convention requires.

        Override by including ``campaign_name`` in the dimensions or by joining
        with the campaign list endpoint in a post-processing step.
        """
        return str(row.get("dimensions", {}).get("campaign_name", "(not set)"))

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map TikTok integrated report rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        TikTok field                         → UnifiedRecord field
        ``dimensions.campaign_id``           → ``campaign_id``
        ``dimensions.stat_time_day``[:10]    → ``date_key`` (UTC date)
        ``metrics.impressions`` (str)        → ``impressions`` (int)
        ``metrics.clicks`` (str)             → ``clicks`` (int)
        ``metrics.spend`` (str)              → ``cost_raw`` (Decimal, account ccy)
        ``metrics.conversions`` (str)        → ``conversions`` (Decimal)
        ``metrics.total_purchase_value`` (str)→ ``conversion_value_raw`` (Decimal)
        account currency (from config)       → ``cost_ccy`` / ``conversion_value_ccy``

        Spend: TikTok returns ``spend`` as a float-string already in the account
        currency (NOT micros).  We wrap in ``str()`` before ``Decimal()`` to
        avoid float-repr issues.

        Campaign name: not returned in the integrated report metric set.  Set to
        ``"(not set)"`` per SDK convention.  Callers needing the name must join
        against the campaign list endpoint separately.

        Ad-set and ad grain are not fetched at campaign level; set to ``"(not set)"``.
        """
        records: list[UnifiedRecord] = []
        account_id = self._advertiser_id()
        currency = self._currency()

        for row in raw:
            dims = row.get("dimensions", {})
            metrics = row.get("metrics", {})

            campaign_id = str(dims.get("campaign_id", "(not set)"))
            # stat_time_day is returned as "YYYY-MM-DD HH:MM:SS"; take first 10 chars
            date_str = str(dims.get("stat_time_day", "1970-01-01"))[:10]
            date_key = date.fromisoformat(date_str)

            impressions = int(str(metrics.get("impressions", "0")))
            clicks = int(str(metrics.get("clicks", "0")))

            # spend is a float-string; use Decimal(str()) to avoid repr issues
            spend_str = str(metrics.get("spend", "0"))
            cost_raw = Decimal(spend_str)

            conversions = Decimal(str(metrics.get("conversions", "0")))
            conversion_value_raw = Decimal(
                str(metrics.get("total_purchase_value", "0"))
            )

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    campaign_id=campaign_id,
                    # Campaign name not in integrated report; use "(not set)"
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
            ``{"daily_campaign_metrics": "YYYY-MM-DD"}`` — latest date seen.
            Empty dict if no fetch has been completed in this instance's lifetime.
        """
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        """Return the capability descriptor for the TikTok Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # TikTok Marketing API: ~10 QPS per app per advertiser; 120 RPM is safe.
            rate_limit_rpm=120,
        )
