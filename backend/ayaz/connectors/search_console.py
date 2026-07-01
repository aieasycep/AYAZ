"""Google Search Console connector for AYAZ.

Connects to the Search Console Search Analytics API to pull daily organic
search performance metrics into the unified ``UnifiedRecord`` schema.

IMPORTANT — semantic gap
------------------------
Search Console is an **organic search analytics** source, not an ads source.
Key implications for the unified schema:

1. **No ad spend**: ``cost_raw`` is always ``Decimal("0")``.

2. **No conversions**: Search Console tracks impressions, clicks, CTR, and
   average position for organic search results.  There is no conversion signal.
   ``conversions`` and ``conversion_value_raw`` are always ``Decimal("0")``.

3. **clicks are organic clicks**: The ``clicks`` field maps naturally here —
   Search Console ``clicks`` counts how many times a user clicked a search
   result that led to the site.  This is structurally equivalent to the
   ``clicks`` field in the unified schema (count of link interactions).

4. **impressions** maps directly: how many times the site appeared in search
   results.

5. **campaign = "(not set)"**: Search Console has no campaign concept.  The
   channel is always ``"organic_search"``.  Both ``campaign_id`` and
   ``campaign_name`` are set to ``"(not set)"`` since there is no campaign
   structure.  The ``adset_id`` / ``ad_id`` hierarchy is likewise ``"(not set)"``.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``client_id``
    OAuth 2.0 client ID from a Google Cloud project with the Search Console
    API enabled.
``client_secret``
    OAuth 2.0 client secret.
``refresh_token``
    Long-lived refresh token (scope
    ``https://www.googleapis.com/auth/webmasters.readonly``).
``site_url``
    The site URL as registered in Search Console, e.g.
    ``"https://example.com/"`` or ``"sc-domain:example.com"``.
``currency``  (optional)
    Stored for schema compliance; always ``"USD"`` by default since there
    are no monetary values.

Sync strategy
-------------
- Stream: ``daily_search_metrics`` — one row per date.
- Granularity: daily.
- Incremental: yes.
- Max backfill: 16 months (Search Console keeps ~16 months of data; 480 days is
  a safe scheduler limit).
- Write support: no (read-only).

Rate limits
-----------
- Search Console API: 1,200 queries/minute per user, 10 queries/second.
- This connector uses a conservative 200 RPM cap.

API reference
-------------
https://developers.google.com/webmaster-tools/search-console-api-original/v3/searchanalytics/query
"""

from __future__ import annotations

import logging
import urllib.parse
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

_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# Query endpoint — {site_url} must be URL-encoded in the path segment
_QUERY_URL = (
    "https://www.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"
)

# Maximum rows per request (API maximum is 25,000)
_ROW_LIMIT = 25_000

# Channel label used for all Search Console records
_CHANNEL = "organic_search"


# ── Connector ─────────────────────────────────────────────────────────────────


class SearchConsoleConnector(Connector):
    """Search Console connector — daily organic search impressions and clicks.

    This is an analytics connector, not an ads connector.  ``cost_raw`` is
    always zero.  See module docstring for full semantic-gap documentation.

    Expected ``config.extra`` keys:
        ``client_id``, ``client_secret``, ``refresh_token``, ``site_url``,
        ``currency`` (optional).
    """

    platform_key = "search_console"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        return str(self.config.extra.get(key, default))

    def _site_url(self) -> str:
        return self._get_secret("site_url") or self.config.external_account_id

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

    def _query_url(self) -> str:
        # URL-encode the site_url so paths like "https://example.com/" are
        # safely embedded in the API path segment.
        encoded = urllib.parse.quote(self._site_url(), safe="")
        return _QUERY_URL.format(site_url=encoded)

    # ── OAuth helpers ──────────────────────────────────────────────────────

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Return the Google OAuth2 consent URL for the webmasters.readonly scope.

        Pure helper — no network calls.
        """
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

        Raises
        ------
        RuntimeError
            If any required credential is missing from config.extra.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        ValueError
            If the response does not contain an access_token.
        """
        required = ("client_id", "client_secret", "refresh_token", "site_url")
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
        """List all sites verified in Search Console under the authenticated user.

        Calls ``GET https://www.googleapis.com/webmasters/v3/sites`` and returns
        each verified site as a dict.

        Returns
        -------
        list[dict]
            Each entry has ``id`` (site URL), ``name`` (same), and
            ``permissionLevel``.
        """
        resp = httpx.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers=self._auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        sites: list[dict[str, Any]] = []
        for entry in body.get("siteEntry", []):
            site_url = str(entry.get("siteUrl", ""))
            sites.append(
                {
                    "id": site_url,
                    "name": site_url,
                    "permissionLevel": str(entry.get("permissionLevel", "")),
                }
            )
        return sites

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """POST a searchAnalytics query to the Search Console API.

        Requests ``dimensions=["date"]`` which yields one row per calendar day
        with aggregated clicks, impressions, CTR, and position across all queries
        and pages for that day.

        Parameters
        ----------
        stream:
            Must be ``"daily_search_metrics"``.
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            Each dict contains ``keys`` (list with the date string),
            ``clicks``, ``impressions``, ``ctr``, and ``position`` as returned
            by the API.  Passed directly to ``normalize()``.
        """
        if stream not in ("daily_search_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_search_metrics']"
            )

        payload: dict[str, Any] = {
            "startDate": since.isoformat(),
            "endDate": until.isoformat(),
            "dimensions": ["date"],
            "rowLimit": _ROW_LIMIT,
        }

        resp = httpx.post(
            self._query_url(),
            headers=self._auth_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        rows: list[dict[str, Any]] = body.get("rows", [])

        if rows:
            # The date is in keys[0] when dimension is ["date"]
            latest = max(date.fromisoformat(r["keys"][0]) for r in rows)
            self._watermark[stream] = latest.isoformat()
            logger.info(
                "%s Fetched %d rows for stream=%r, watermark=%s",
                self._log_prefix(),
                len(rows),
                stream,
                latest.isoformat(),
            )

        return rows

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Search Console rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        SC API field           → UnifiedRecord field
        ``keys[0]`` (date str) → ``date_key`` (date object, UTC)
        ``clicks`` (int)       → ``clicks``
        ``impressions`` (int)  → ``impressions``
        ``ctr`` (float)        → NOT MAPPED (derived; computed by Metric Layer)
        ``position`` (float)   → NOT MAPPED (no field in UnifiedRecord)
        n/a                    → ``cost_raw = Decimal("0")`` (analytics source)
        n/a                    → ``conversions = Decimal("0")`` (not available)
        n/a                    → ``conversion_value_raw = Decimal("0")``
        n/a                    → ``campaign_id/name = "(not set)"``
        ``"organic_search"``   → stored in ``raw_source`` for reference
        """
        records: list[UnifiedRecord] = []
        account_id = self._site_url()
        currency = self._currency()

        for row in raw:
            # keys[0] is the date dimension value when dimensions=["date"]
            date_str = row["keys"][0]
            date_key = date.fromisoformat(date_str)

            clicks = int(row.get("clicks", 0))
            impressions = int(row.get("impressions", 0))

            # Enrich raw_source with the derived channel label for lineage
            enriched = dict(row)
            enriched["_channel"] = _CHANNEL

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    # No campaign structure in Search Console
                    campaign_id="(not set)",
                    campaign_name="(not set)",
                    adset_id="(not set)",
                    adset_name="(not set)",
                    ad_id="(not set)",
                    ad_name="(not set)",
                    impressions=impressions,
                    clicks=clicks,
                    # Organic search: no ad spend
                    cost_raw=Decimal("0"),
                    cost_ccy=currency,
                    # No conversion signal in Search Console
                    conversions=Decimal("0"),
                    conversion_value_raw=Decimal("0"),
                    conversion_value_ccy=currency,
                    raw_source=enriched,
                )
            )

        return records

    def fetch_query_page(
        self,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch query+page-level rows from Search Console.

        Uses ``dimensions=["date", "query", "page"]`` to produce one row per
        (date, query, page) combination.  These rows are stored in
        ``seo_search_metrics`` by the sync pipeline.

        Each returned dict contains: ``date``, ``query``, ``page``,
        ``clicks``, ``impressions``, ``ctr``, ``position``.

        Parameters
        ----------
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            Flat dicts with date, query, page, and metric fields.
        """
        payload: dict[str, Any] = {
            "startDate": since.isoformat(),
            "endDate": until.isoformat(),
            "dimensions": ["date", "query", "page"],
            "rowLimit": _ROW_LIMIT,
        }

        resp = httpx.post(
            self._query_url(),
            headers=self._auth_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        raw_rows: list[dict[str, Any]] = body.get("rows", [])

        # Flatten: keys=[date, query, page]
        result: list[dict[str, Any]] = []
        for row in raw_rows:
            keys = row.get("keys", [])
            if len(keys) < 3:
                continue
            result.append({
                "date": keys[0],
                "query": keys[1],
                "page": keys[2],
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": float(row.get("ctr", 0.0)),
                "position": float(row.get("position", 0.0)),
            })

        logger.info(
            "%s fetch_query_page: %d rows between %s and %s",
            self._log_prefix(),
            len(result),
            since.isoformat(),
            until.isoformat(),
        )
        return result

    def incremental_state(self) -> dict[str, Any]:
        """Return the watermark cursor from the last ``fetch()`` call.

        Returns
        -------
        dict
            ``{"daily_search_metrics": "YYYY-MM-DD"}`` — latest date seen.
            Empty dict if no fetch has been completed in this instance's lifetime.
        """
        return dict(self._watermark)

    def capabilities(self) -> ConnectorCapabilities:
        """Return the capability descriptor for the Search Console connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_search_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=480,
            # Search Console API: 1,200 QPM per user; 200 RPM is a conservative cap.
            rate_limit_rpm=200,
        )
