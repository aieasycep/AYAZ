"""Criteo connector for AYAZ.

Connects to the Criteo Marketing Solutions API statistics endpoint to pull daily
campaign-level metrics into the unified ``UnifiedRecord`` schema.

Required credentials (store in Vault; reference via ConnectorConfig.vault_secret_ref)
-------------------------------------------------------------------------------------
``client_id``
    OAuth 2.0 client ID for the Criteo API application (client credentials flow).
    Created in the Criteo Developer Portal under your application settings.
``client_secret``
    OAuth 2.0 client secret for the same application.
``advertiser_id``
    The Criteo advertiser account ID (numeric string), e.g. ``"78901234"``.
``currency``  (optional)
    ISO-4217 currency code for the account (e.g. ``"EUR"``).  Defaults to ``"USD"``.
    Criteo returns ``AdvertiserCost`` in the account's billing currency.

OAuth 2.0 flow (client credentials)
-------------------------------------
Criteo uses the OAuth 2.0 client credentials grant — no user consent redirect is
required.  The connector authenticates entirely server-to-server:

1. POST ``https://api.criteo.com/oauth2/token`` with:
   ``grant_type=client_credentials``, ``client_id``, ``client_secret``.
2. Response contains ``access_token`` (expires in ~15 minutes).
3. Store client_id / client_secret in Vault (NOT the short-lived token).
4. The connector re-authenticates before each sync to obtain a fresh token.
   ``refresh_token()`` re-runs the client-credentials grant (no separate
   refresh token concept in this flow).

Statistics endpoint
-------------------
``POST https://api.criteo.com/2023-01/statistics/report``

Request body (JSON):
    {
      "dimensions": ["AdvertiserId", "CampaignId", "Day"],
      "metrics": ["Displays", "Clicks", "AdvertiserCost", "Conversions"],
      "currency": "<account_currency>",
      "startDate": "YYYY-MM-DD",
      "endDate": "YYYY-MM-DD",
      "format": "json"
    }

Response body (JSON):
    {
      "rows": [
        {
          "AdvertiserId": "78901234",
          "CampaignId": "456789",
          "Day": "2024-06-01",
          "Displays": 95000,
          "Clicks": 2100,
          "AdvertiserCost": "312.50",
          "Conversions": 45
        },
        ...
      ]
    }

Field terminology:
- ``Displays`` → impressions (Criteo uses "displays" for ad impressions)
- ``AdvertiserCost`` → spend (total cost billed to the advertiser)
- ``Conversions`` → total attributed conversions

Sync strategy
-------------
- Stream: ``daily_campaign_metrics`` — one row per (date, campaign).
- Incremental: yes — caller supplies ``since`` / ``until`` date range.
- Max backfill: 365 days (Criteo supports up to 13 months; 365 is conservative).
- Write support: no (read-only).

Spend handling
--------------
Criteo returns ``AdvertiserCost`` as a decimal string in the account's billing
currency (e.g. ``"312.50"``).  No micro-conversion is needed.  Direct Decimal
conversion.

Rate limits
-----------
- Criteo Marketing Solutions API: 60 requests per minute per token.
- This connector uses 60 RPM as the documented cap.

API version
-----------
Targets the ``2023-01`` version of the Criteo API.  Update ``_API_VERSION`` to
upgrade.

Criteo Marketing Solutions API reference
------------------------------------------
https://developers.criteo.com/marketing-solutions/docs/getting-started
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

_API_VERSION = "2023-01"
_TOKEN_URL = "https://api.criteo.com/oauth2/token"
_STATS_URL = f"https://api.criteo.com/{_API_VERSION}/statistics/report"


# ── Connector ─────────────────────────────────────────────────────────────────


class CriteoConnector(Connector):
    """Criteo connector — daily campaign metrics via the Marketing Solutions API.

    Uses OAuth 2.0 client credentials flow (server-to-server; no user redirect).
    Credential lookup from ``ConnectorConfig.extra`` (Vault-injected in production).

    Expected ``config.extra`` keys:
        ``client_id``, ``client_secret``, ``advertiser_id``,
        ``currency`` (optional).
    """

    platform_key = "criteo"

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._watermark: dict[str, str] = {}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_secret(self, key: str, default: str = "") -> str:
        """Read a credential from config.extra (Vault-injected at runtime)."""
        return str(self.config.extra.get(key, default))

    def _advertiser_id(self) -> str:
        return self._get_secret("advertiser_id") or self.config.external_account_id

    def _currency(self) -> str:
        return self._get_secret("currency", "USD")

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization header for every Criteo API request."""
        if not self._access_token:
            raise RuntimeError(
                f"{self._log_prefix()} No access token — call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── OAuth helpers (client credentials — no redirect) ───────────────────

    def _do_client_credentials_grant(self) -> str:
        """POST to Criteo's token endpoint using client credentials grant.

        Returns the new ``access_token`` string.  Criteo access tokens expire
        in ~15 minutes; this method is called from both authenticate() and
        refresh_token() since there is no separate refresh token concept in the
        client credentials flow.
        """
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._get_secret("client_id"),
                "client_secret": self._get_secret("client_secret"),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError(
                f"{self._log_prefix()} Client credentials grant returned no "
                f"access_token. Response: {data}"
            )
        return token

    # ── Abstract interface ─────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Obtain an access token via the OAuth 2.0 client credentials grant.

        Criteo's client credentials flow requires ``client_id`` and
        ``client_secret`` from Vault (``config.extra``).  No user redirect is
        needed.  The short-lived access token (~15 min) is stored on
        ``self._access_token`` for subsequent API calls.

        Raises
        ------
        RuntimeError
            If ``client_id`` or ``client_secret`` are absent from config.extra.
        httpx.HTTPStatusError
            If the token endpoint returns a non-2xx response.
        ValueError
            If the response does not contain an access_token.
        """
        required = ("client_id", "client_secret")
        missing = [k for k in required if not self._get_secret(k)]
        if missing:
            raise RuntimeError(
                f"{self._log_prefix()} Missing required credentials: {missing}. "
                "These must be present in config.extra (injected by Vault broker)."
            )
        self._access_token = self._do_client_credentials_grant()
        logger.info(
            "%s Authenticated via Criteo client credentials grant.",
            self._log_prefix(),
        )

    def refresh_token(self) -> None:
        """Re-obtain an access token via the client credentials grant.

        Criteo client credentials flow has no separate refresh token; this
        method simply re-runs the grant to get a fresh access token.
        Called proactively by the OAuth Broker before the ~15-minute expiry.

        TODO (Faz 1): persist the new token back to Vault via VaultClient.write().
        """
        self._access_token = self._do_client_credentials_grant()
        logger.info(
            "%s Token refreshed (client credentials re-grant). "
            "TODO: persist to Vault (Faz 1).",
            self._log_prefix(),
        )

    def discover(self) -> list[dict[str, Any]]:
        """Return accessible advertisers under the authenticated credentials.

        Calls ``GET /2023-01/advertisers`` to list advertisers the token can
        access.

        Returns
        -------
        list[dict]
            Each entry has ``id``, ``name``, and ``currency``.
        """
        resp = httpx.get(
            f"https://api.criteo.com/{_API_VERSION}/advertisers",
            headers=self._auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        advertisers: list[dict[str, Any]] = []
        for adv in body.get("data", []):
            attrs = adv.get("attributes", {})
            advertisers.append(
                {
                    "id": str(adv.get("id", "")),
                    "name": str(attrs.get("name", "")),
                    "currency": str(attrs.get("currency", "USD")),
                }
            )
        return advertisers

    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch daily campaign stats from the Criteo statistics report endpoint.

        POSTs to ``POST /statistics/report`` with dimensions ``["AdvertiserId",
        "CampaignId", "Day"]`` and metrics ``["Displays", "Clicks",
        "AdvertiserCost", "Conversions"]``.

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
            Flat list of row dicts from the ``rows`` array in the response.
            Each dict contains: ``AdvertiserId``, ``CampaignId``, ``Day``,
            ``Displays``, ``Clicks``, ``AdvertiserCost``, ``Conversions``.
        """
        if stream not in ("daily_campaign_metrics",):
            raise ValueError(
                f"{self._log_prefix()} Unknown stream {stream!r}. "
                "Supported: ['daily_campaign_metrics']"
            )

        payload: dict[str, Any] = {
            "dimensions": ["AdvertiserId", "CampaignId", "Day"],
            "metrics": ["Displays", "Clicks", "AdvertiserCost", "Conversions"],
            "currency": self._currency(),
            "startDate": since.isoformat(),
            "endDate": until.isoformat(),
            "format": "json",
            "advertiserId": self._advertiser_id(),
        }

        resp = httpx.post(
            _STATS_URL,
            headers=self._auth_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        rows: list[dict[str, Any]] = body.get("rows", [])

        if rows:
            latest = max(
                date.fromisoformat(r["Day"]) for r in rows if "Day" in r
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

    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map Criteo statistics report rows to ``UnifiedRecord``s.

        This is a PURE function — no I/O.

        Field mapping
        -------------
        Criteo field             → UnifiedRecord field
        ``CampaignId``           → ``campaign_id``
        ``Day``                  → ``date_key`` (YYYY-MM-DD → date)
        ``Displays`` (int)       → ``impressions``
        ``Clicks`` (int)         → ``clicks``
        ``AdvertiserCost`` (str) → ``cost_raw`` (Decimal, account currency)
        ``Conversions`` (int)    → ``conversions`` (Decimal)
        account currency         → ``cost_ccy`` / ``conversion_value_ccy``

        Spend: Criteo returns ``AdvertiserCost`` as a decimal string in the
        account's billing currency (NOT micros).  Direct Decimal conversion.

        Campaign name: not returned in the statistics report endpoint.  Set to
        ``"(not set)"`` per SDK convention.

        Ad-set and ad grain are not present at campaign-level; set to ``"(not set)"``.

        Conversion value: Criteo statistics does not expose revenue / order value
        in the default metric set.  Set to Decimal("0").
        """
        records: list[UnifiedRecord] = []
        account_id = self._advertiser_id()
        currency = self._currency()

        for row in raw:
            date_key = date.fromisoformat(str(row.get("Day", "1970-01-01")))

            campaign_id = str(row.get("CampaignId", "(not set)"))
            if not campaign_id:
                campaign_id = "(not set)"

            # AdvertiserCost is a decimal string; direct Decimal conversion
            cost_str = str(row.get("AdvertiserCost", "0"))
            cost_raw = Decimal(cost_str)

            # Displays and Clicks are integers in the API response
            impressions = int(row.get("Displays", 0))
            clicks = int(row.get("Clicks", 0))

            conversions = Decimal(str(row.get("Conversions", 0)))

            records.append(
                UnifiedRecord(
                    external_account_id=account_id,
                    platform=self.platform_key,
                    date_key=date_key,
                    campaign_id=campaign_id,
                    # Statistics report does not include campaign names inline
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
                    # Revenue/order value not in default stats metric set
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
        """Return the capability descriptor for the Criteo connector."""
        return ConnectorCapabilities(
            platform_key=self.platform_key,
            supported_streams=["daily_campaign_metrics"],
            supports_incremental=True,
            supports_backfill=True,
            supports_write=False,
            min_granularity="daily",
            max_backfill_days=365,
            # Criteo Marketing Solutions API: 60 requests per minute per token.
            rate_limit_rpm=60,
        )
