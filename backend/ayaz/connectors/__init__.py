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
import ayaz.connectors.sample  # noqa: F401  — registers "sample" connector

__all__ = [
    "Connector",
    "ConnectorCapabilities",
    "ConnectorConfig",
    "UnifiedRecord",
    "ConnectorRegistry",
]
