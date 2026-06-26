"""Connector SDK package.

Usage
-----
Import ``ConnectorRegistry`` to look up a connector class by platform key::

    from ayaz.connectors import ConnectorRegistry
    cls = ConnectorRegistry.get("google_ads")
    connector = cls(config=...)
"""

from ayaz.connectors.base import (
    Connector,
    ConnectorCapabilities,
    ConnectorConfig,
    UnifiedRecord,
)
from ayaz.connectors.registry import ConnectorRegistry

# Import connectors so they self-register on import
import ayaz.connectors.sample          # noqa: F401  — registers "sample"
import ayaz.connectors.google_ads      # noqa: F401  — registers "google_ads"
import ayaz.connectors.meta_ads        # noqa: F401  — registers "meta_ads"
import ayaz.connectors.ga4             # noqa: F401  — registers "ga4"
import ayaz.connectors.search_console  # noqa: F401  — registers "search_console"
import ayaz.connectors.tiktok_ads      # noqa: F401  — registers "tiktok_ads"
import ayaz.connectors.linkedin_ads    # noqa: F401  — registers "linkedin_ads"
import ayaz.connectors.microsoft_ads   # noqa: F401  — registers "microsoft_ads"
import ayaz.connectors.criteo          # noqa: F401  — registers "criteo"
import ayaz.connectors.pinterest_ads   # noqa: F401  — registers "pinterest_ads"

__all__ = [
    "Connector",
    "ConnectorCapabilities",
    "ConnectorConfig",
    "UnifiedRecord",
    "ConnectorRegistry",
]
