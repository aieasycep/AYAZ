"""Meta Ads connector for AYAZ.

Connects to the Meta Marketing API (Graph API) Insights endpoint to pull daily
campaign-level metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``access_token``
    Long-lived user access token or system user access token obtained via the
    Meta OAuth 2.0 flow or the Business Manager system user setup.  System user
    tokens are preferred for server-side integrations (no expiry by default).
``ad_account_id``
    The Meta ad account ID without the ``act_`` prefix (e.g. ``"123456789"``).
    The connector prepends ``act_`` when forming API URLs.
``api_version``  (optional)
    Graph API version string, e.g. ``"v25.0"``.  Defaults to ``_API_VERSION``.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"USD"``).  Defaults to ``"USD"``.
    The ``spend`` field in the API is always in the account's currency.

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Granularity: daily (``time_increment=1``).
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 37 months (Meta keeps up to 37 months of data; 730 days is a
  conservative scheduler limit that avoids API timeout issues on large accounts).
- Write support: no (read-only).

Spend handling
--------------
Meta returns ``spend`` as a decimal string already in the account currency
(e.g. ``"12.34"``).  No micro-conversion is needed.  We pass it directly to
``Decimal`` for exact representation.

Conversions & conversion value
-------------------------------
Meta returns ``actions`` and ``action_values`` as lists of
``{"action_type": str, "value": str}`` objects.  This connector extracts the
``offsite_conversion.fb_pixel_purchase`` action type as the conversion event,
which represents standard purchase conversions tracked by the Meta Pixel or
Conversions API.  Rationale: purchase is the most commercially meaningful
action type for e-commerce and performance advertisers; it is the action type
recommended by Meta for ROAS calculation.

If the account uses a different primary conversion action (e.g. ``lead``,
``complete_registration``), configure the ``conversion_action_type`` key in
``config.extra`` to override the default.

Rate limits
-----------
- Meta Business API uses a percentage-based rate limit measured per app per
  ad account.  Limit information is returned in the ``X-Business-Use-Case-Usage``
  response header.
- This connector does NOT parse or enforce that header — the scheduler must
  monitor it and back off when usage approaches 100 %.
- Conservative default: 200 RPM across all ad accounts served by the app.

API version
-----------
Targets ``v25.0`` of the Graph API (latest GA, Feb 2026).  Update ``_API_VERSION``
to upgrade.  Unlike Google Ads (which hard-404s a sunset version), Meta keeps old
versions ~2 years and only warns — but bump periodically to stay well inside window.

Meta Marketing API reference
-----------------------------
https://developers.facebook.com/docs/marketing-api/insights
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
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

_API_VERSION = "v25.0"

# Insights endpoint — formatted with api_version and act_{ad_account_id}
_INSIGHTS_URL = "https://graph.facebook.com/{ver}/{account}/insights"

# Fields requested from the Insights API
_FIELDS = (
    "date_start,"
    "campaign_id,"
    "campaign_name,"
    "impressions,"
    "clicks,"
    "spend,"
    "actions,"
    "action_values"
)

# Default conversion action type used to extract conversions from the
# ``actions`` / ``action_values`` lists.  Corresponds to a Meta Pixel purchase
# event or Conversions API purchase event.  Override via config.extra key
# ``conversion_action_type``.
_DEFAULT_CONVERSION_ACTION = "offsite_conversion.fb_pixel_purchase"

# Pagination: maximum rows per page (Meta default is 25; we raise to 500 to
# minimise round-trips on large accounts).
_PAGE_LIMIT = 500

# Meta's Insights endpoint returns HTTP 500 / times out on large *synchronous*
# pulls (a wide date range × ``time_increment=1`` × many campaigns explodes the
# response — unlike Google Ads' searchStream, which handles a full year in one
# call). fetch() therefore splits the requested window into chunks of at most
# this many days and pages through each independently, concatenating results.
_INSIGHTS_CHUNK_DAYS = 30


# ── Connector ─────────────────────────────────────────────────────────────────


class MetaAdsConnector(Connector):
    """Meta Ads connector — daily campaign metrics via the Marketing API Insights.

    Credential lookup
    -----------------
    All secrets are read from ``ConnectorConfig.extra`` at runtime.  In
    production these values are injected by the Vault broker — never hard-coded.

    Expected ``config.extra`` keys:
        ``access_token``, ``ad_account_id``,
        ``api_version`` (optional), ``currency`` (optional),
        ``conversion_action_type`` (optional).
    """

    platform_key = "meta_ads"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        # Access token may be injected directly or refreshed at runtime
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        return str(self.config.extra.get(key, default))

    def _ad_account_id(self) -> str:
        """Return the raw account ID (without ``act_`` prefix)."""
        return self._get_secret("ad_account_id") or self.config.external_account_id

    def _api_version(self) -> str:
        return self._get_secret("api_version", _API_VERSION)

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _conversion_action_type(self) -> str:
        return self._get_secret("conversion_action_type", _DEFAULT_CONVERSION_ACTION)

    def _token(self) -> str:
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return self._access_token

    def _insights_url(self) -> str:
        account = f"act_{self._ad_account_id()}"
        return _INSIGHTS_URL.format(ver=self._api_version(), account=account)

    # ── OAuth / auth helpers ───────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
        scopes: tuple[str, ...] = ("ads_read", "business_management"),
    ) -> str:
        """Return the Meta OAuth2 dialog URL for the required ad scopes.

        This is a pure helper; it makes NO network calls.

        Parameters
        ----------
        client_id:
            Meta app ID.
        redirect_uri:
            URI Meta will redirect to after authorization (must be registered
            in the Meta app settings).
        state:
            CSRF protection token (opaque; round-tripped by Meta).
        scopes:
            OAuth permission scopes to request.
        """
        import urllib.parse

        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
        }
        if state:
            params["state"] = state
        return (
            f"https://www.facebook.com/dialog/oauth?{urllib.parse.urlencode(params)}"
        )

    def _exchange_code_for_token(self, code: str, redirect_uri: str) -> str:
        """Exchange an authorization code for a short-lived user access token.

        The caller should then exchange this for a long-lived token via
        ``GET /oauth/access_token?grant_type=fb_exchange_token`` before
        storing in Vault.  Kept structural; not exercised in fixture tests.
        """
        resp = httpx.get(
            "https://graph.facebook.com/oauth/access_token",
            params={
                "client_id": self._get_secret("client_id"),
                "client_secret": self._get_secret("client_secret"),
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Token exchange returned no access_token."
            )
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Load the long-lived access token from ``config.extra``.

        Meta long-lived user tokens last ~60 days; system user tokens from
        Business Manager do not expire.  The Vault broker injects the token
        via ``config.extra['access_token']``; no live exchange is performed
        here at authenticate() time (the token is already long-lived).

        For regular user tokens the OAuth Broker must call ``refresh_token()``
        before the 60-day window expires.

        ``ad_account_id`` is intentionally NOT required here: a user who has
        just completed the OAuth dialog has an ``access_token`` but has not
        picked an ad account yet.  ``discover()`` (the account picker) needs
        to run with only the token — requiring ``ad_account_id`` up front
        creates a chicken-and-egg RuntimeError that blocks account selection
        entirely.  Mirrors ``GoogleAdsConnector.authenticate()``, which does
        not require ``customer_id`` either.  ``_ad_account_id()`` /
        ``_insights_url()`` still fall back to ``config.external_account_id``
        once an account has been selected and persisted.

        Raises
        ------
        RuntimeError
            If ``access_token`` is absent from config.extra.
        """
        required = ("access_token",)
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "These must be present in config.extra (injected by Vault broker)."
            )
        self._access_token = self._get_secret("access_token")
        logger.info("%s Authenticated with Meta access token.", self._log_prefix())

    def refresh_token(self) -> None:
        """Exchange the current long-lived token for a fresh one.

        Calls ``GET /oauth/access_token?grant_type=fb_exchange_token`` which
        extends user token validity by another 60 days.  For system user tokens
        this is a no-op (they do not expire).

        TODO (Faz 1): persist the refreshed token back to Vault via VaultClient.write().
        """
        current = self._get_secret("access_token")
        if not current:
            raise RuntimeError(
                f"{self._log_prefix()} Cannot refresh: no access_token in config.extra."
            )
        resp = httpx.get(
            f"https://graph.facebook.com/{self._api_version()}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._get_secret("client_id"),
                "client_secret": self._get_secret("client_secret"),
                "fb_exchange_token": current,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        new_token = data.get("access_token", "")
        if not new_token:
            raise ValueError(
                f"{self._log_prefix()} Token refresh returned no access_token."
            )
        self._access_token = new_token
        logger.info(
            "%s Token refreshed. TODO: persist to Vault (Faz 1).", self._log_prefix()
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return accessible ad accounts under the authenticated token.

        Queries ``GET /me/adaccounts`` with fields ``account_id,name,currency``.

        Returns
        -------
        list[dict]
            Each entry has ``id`` (without ``act_`` prefix), ``name``, and
            ``currency``.
        """
        resp = httpx.get(
            f"https://graph.facebook.com/{self._api_version()}/me/adaccounts",
            params={
                "fields": "account_id,name,currency",
                "access_token": self._token(),
            },
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        accounts: list[dict[str, Any]] = []
        for item in body.get("data", []):
            accounts.append(
                {
                    "id": str(
                        item.get("account_id", item.get("id", ""))
                    ).removeprefix("act_"),
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
        """Fetch raw campaign insights from the Meta Marketing API.

        Issues a GET request to the Insights endpoint with ``time_increment=1``
        (daily breakdown) and ``level=campaign``.  Follows pagination via the
        ``paging.next`` cursor until all pages are exhausted.

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
            Raw Insights API data objects, each containing at minimum
            ``date_start``, ``campaign_id``, ``campaign_name``, ``impressions``,
            ``clicks``, ``spend``, ``actions``, ``action_values``.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        rows: list[dict[str, Any]] = []
        insights_url = self._insights_url()

        # Split [since, until] into <= _INSIGHTS_CHUNK_DAYS windows so each
        # synchronous Insights call stays small enough for Meta to serve (a
        # full-year daily pull on a busy account otherwise 500s). Each chunk is
        # paginated independently; all rows are concatenated.
        chunk_start = since
        while chunk_start <= until:
            chunk_end = min(
                chunk_start + timedelta(days=_INSIGHTS_CHUNK_DAYS - 1), until
            )
            url: str | None = insights_url
            params: dict[str, Any] | None = {
                "access_token": self._token(),
                "fields": _FIELDS,
                "time_increment": "1",
                "level": "campaign",
                "time_range": (
                    f'{{"since":"{chunk_start.isoformat()}",'
                    f'"until":"{chunk_end.isoformat()}"}}'
                ),
                "limit": str(_PAGE_LIMIT),
            }
            while url:
                resp = httpx.get(url, params=params, timeout=60)
                resp.raise_for_status()
                body: dict[str, Any] = resp.json()
                rows.extend(body.get("data", []))
                # Pagination: follow cursor if present
                url = body.get("paging", {}).get("next")
                params = None  # ``next`` URL already contains all query params
            chunk_start = chunk_end + timedelta(days=1)

        if rows:
            latest = max(date.fromisoformat(r["date_start"]) for r in rows)
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
    def _extract_action_value(
        action_list: list[dict[str, Any]], action_type: str
    ) -> Decimal:
        """Extract the value for a specific action type from an actions list.

        Parameters
        ----------
        action_list:
            List of ``{"action_type": str, "value": str}`` dicts from the API.
        action_type:
            The ``action_type`` key to look up.

        Returns
        -------
        Decimal
            The value for that action type, or ``Decimal("0")`` if not found.
        """
        for item in action_list:
            if item.get("action_type") == action_type:
                return Decimal(str(item.get("value", "0")))
        return Decimal("0")

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Meta Insights API rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        Meta API field        → UnifiedRecord field
        ``campaign_id``       → ``campaign_id``
        ``campaign_name``     → ``campaign_name``
        ``date_start``        → ``date_key`` (already UTC calendar date)
        ``impressions`` (str) → ``impressions`` (int)
        ``clicks`` (str)      → ``clicks`` (int)
        ``spend`` (str)       → ``cost_raw`` (Decimal, already in account ccy)
        ``actions``           → ``conversions`` (filtered by conversion_action_type)
        ``action_values``     → ``conversion_value_raw`` (same filter)
        account currency      → ``cost_ccy`` / ``conversion_value_ccy``

        Ad-set and ad grain are not fetched at ``level=campaign``; those
        hierarchy levels are set to ``"(not set)"``.

        Spend: Meta returns ``spend`` as a string decimal already in the account
        currency (NOT micros).  We parse it directly with ``Decimal``.
        """
        records: list[UnifiedRecord] = []
        account_id = self._ad_account_id()
        currency = self._currency()
        conversion_type = self._conversion_action_type()

        for row in raw:
            spend_str = str(row.get("spend", "0"))
            cost_raw = Decimal(spend_str)

            impressions = int(str(row.get("impressions", "0")))
            clicks = int(str(row.get("clicks", "0")))

            actions = row.get("actions") or []
            action_values = row.get("action_values") or []

            conversions = self._extract_action_value(actions, conversion_type)
            conversion_value_raw = self._extract_action_value(
                action_values, conversion_type
            )

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date.fromisoformat(row["date_start"]),
                    campaign_id=str(row.get("campaign_id", "(not set)")),
                    campaign_name=str(row.get("campaign_name", "(not set)")),
                    # campaign-level query; no ad-set / ad grain
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
        """Return the capability descriptor for the Meta Ads connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=730,
            # Meta uses percentage-based rate limits per app per ad account.
            # 200 RPM is a conservative app-level cap across all accounts.
            rate_limit_rpm=200,
        )
