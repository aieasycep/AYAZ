"""Connector SDK — abstract base class and canonical data types.

Every platform connector MUST subclass ``Connector`` and implement all abstract
methods.  The SDK provides cross-cutting infrastructure for free:

- Fixture-based golden-file testing pattern (see ``tests/test_sample_connector.py``)
- ``ConnectorRegistry`` auto-registration via ``platform_key`` class attribute
- ``UnifiedRecord`` — the single canonical schema that feeds ``fact_daily_metrics``
- ``ConnectorCapabilities`` — self-describing metadata so the scheduler and UI
  can adapt to each connector's features without if-chains

Adding a new connector
----------------------
1. Create ``ayaz/connectors/<platform>.py``.
2. Subclass ``Connector``, set ``platform_key = "<platform>"``.
3. Implement all abstract methods.
4. Add a ``tests/fixtures/<platform>_metrics.json`` sample response.
5. Add ``tests/test_<platform>_connector.py`` following the golden-file pattern.
6. Import the module in ``ayaz/connectors/__init__.py`` so it self-registers.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


# ── Canonical unified record ──────────────────────────────────────────────────


@dataclass
class UnifiedRecord:
    """One normalised row destined for ``fact_daily_metrics``.

    All monetary values are expressed as ``Decimal`` to avoid floating-point
    rounding errors.  Derived metrics (CTR / CPC / CPA / ROAS) are NOT included
    — they are computed by the Metric Layer.

    Timezone: ``date_key`` is always UTC calendar date.
    Currency:  ``cost_raw`` / ``conversion_value_raw`` are in the source
               platform currency (``cost_ccy``).  The ETL worker applies FX
               conversion to populate ``cost_base_ccy`` etc. before upsert.
    """

    # Grain identifiers (external platform IDs — resolved to dim surrogate keys
    # by the ETL worker before insert)
    external_account_id: str
    platform: str  # matches Platform enum key
    date_key: date  # UTC

    # Campaign hierarchy (use "(not set)" for sources without full hierarchy)
    campaign_id: str
    campaign_name: str
    adset_id: str
    adset_name: str
    ad_id: str
    ad_name: str

    # Raw metrics
    impressions: int = 0
    clicks: int = 0
    cost_raw: Decimal = field(default_factory=lambda: Decimal("0"))
    cost_ccy: str = "USD"
    conversions: Decimal = field(default_factory=lambda: Decimal("0"))
    conversion_value_raw: Decimal = field(default_factory=lambda: Decimal("0"))
    conversion_value_ccy: str = "USD"

    # Optional pass-through for debugging / lineage
    raw_source: dict[str, Any] | None = field(default=None, repr=False)


# ── Connector capabilities descriptor ────────────────────────────────────────


@dataclass
class ConnectorCapabilities:
    """Self-describing metadata about what a connector can do.

    The scheduler reads this to decide sync cadence, backfill depth, and
    whether write operations are available (Faz 5+).
    """

    platform_key: str
    supported_streams: list[str]
    """Named data streams this connector exposes (e.g. ``["campaigns", "ads"]``)."""
    supports_incremental: bool = True
    """True if the platform API supports ``since`` / watermark-based fetching."""
    supports_backfill: bool = True
    """True if historical data can be fetched beyond the incremental window."""
    supports_write: bool = False
    """True if the connector implements write operations (Faz 5+)."""
    min_granularity: str = "daily"
    """Finest time grain available: ``daily`` | ``hourly``."""
    max_backfill_days: int = 90
    """Maximum history the platform API allows."""
    rate_limit_rpm: int | None = None
    """Requests-per-minute cap (None = unknown / not enforced by connector)."""


# ── Connector configuration ───────────────────────────────────────────────────


@dataclass
class ConnectorConfig:
    """Runtime config passed to every connector instance.

    ``vault_secret_ref`` is the Vault path from which the connector should
    retrieve OAuth tokens / API keys at runtime.  Never pass raw tokens here.

    TODO (Faz 1): add VaultClient injection so connectors can self-refresh.
    """

    tenant_id: str
    connected_account_id: str
    external_account_id: str
    platform_key: str
    vault_secret_ref: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ── Abstract base class ───────────────────────────────────────────────────────


class Connector(abc.ABC):
    """Abstract base class for all platform connectors.

    Subclasses MUST:
    - Set ``platform_key`` as a class attribute (string, lowercase_underscore).
    - Implement every abstract method below.

    The ``ConnectorRegistry`` automatically registers subclasses that define
    ``platform_key`` via ``__init_subclass__``.
    """

    platform_key: str  # e.g. "google_ads" — set on the concrete subclass

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    # ── Registry hook ─────────────────────────────────────────────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register concrete connector classes in the ConnectorRegistry."""
        super().__init_subclass__(**kwargs)
        key = getattr(cls, "platform_key", None)
        if key:
            from ayaz.connectors.registry import ConnectorRegistry
            ConnectorRegistry.register(key, cls)

    # ── Abstract interface ─────────────────────────────────────────────────

    @abc.abstractmethod
    def authenticate(self) -> None:
        """Perform OAuth / API-key authentication.

        Should retrieve the token from Vault (via ``self.config.vault_secret_ref``),
        validate / refresh it, and store it on ``self`` for subsequent calls.

        Raises
        ------
        ConnectorAuthError
            If the credentials cannot be validated.
        """

    @abc.abstractmethod
    def refresh_token(self) -> None:
        """Refresh an expired OAuth access token and persist the new token to Vault.

        Called proactively by the OAuth Broker before expiry.
        TODO (Faz 1): wire up to VaultClient.write().
        """

    @abc.abstractmethod
    def discover(self) -> list[dict[str, Any]]:
        """List all accounts / entities accessible via the current credentials.

        Returns
        -------
        list[dict]
            Each dict describes one discoverable entity (account, property, …).
            Exact schema is connector-specific; keys SHOULD include ``id`` and
            ``name`` at minimum.
        """

    @abc.abstractmethod
    def fetch(
        self,
        stream: str,
        since: date,
        until: date,
    ) -> list[dict[str, Any]]:
        """Fetch raw platform data for the given stream and date range.

        Parameters
        ----------
        stream:
            Stream name from ``capabilities().supported_streams``.
        since:
            Inclusive start date (UTC).
        until:
            Inclusive end date (UTC).

        Returns
        -------
        list[dict]
            Raw platform-native records (connector-specific schema).
            These are passed directly to ``normalize()``.
        """

    @abc.abstractmethod
    def normalize(self, raw: list[dict[str, Any]]) -> list[UnifiedRecord]:
        """Map raw platform records to the canonical ``UnifiedRecord`` schema.

        This is where per-connector field mapping happens:
        - ``spend`` → ``cost_raw``
        - ``cost_micros / 1_000_000`` → ``cost_raw``
        - Platform timezone → UTC date
        - Platform currency code → ``cost_ccy``

        Parameters
        ----------
        raw:
            Output of ``fetch()``.

        Returns
        -------
        list[UnifiedRecord]
            Ready for upsert into ``fact_daily_metrics`` (after FX conversion
            is applied by the ETL worker).
        """

    @abc.abstractmethod
    def incremental_state(self) -> dict[str, Any]:
        """Return the current watermark / incremental-sync state.

        The scheduler persists this to ``connected_accounts.watermark`` after
        a successful sync so the next run can resume from where it left off.

        Returns
        -------
        dict
            Keys are stream names; values are watermark strings (ISO-8601 dates
            or platform-specific cursors).
        """

    @abc.abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        """Return the static capability descriptor for this connector."""

    # ── Helpers available to all subclasses ───────────────────────────────

    def _log_prefix(self) -> str:
        """Consistent log prefix: ``[<platform>/<account>]``."""
        return f"[{self.platform_key}/{self.config.external_account_id}]"
