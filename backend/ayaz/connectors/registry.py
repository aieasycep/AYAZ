"""Connector registry — maps platform keys to connector classes.

Connectors self-register via ``Connector.__init_subclass__`` so the registry
stays consistent without manual wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ayaz.connectors.base import Connector


class ConnectorRegistry:
    """Global registry of all available connector classes.

    Usage::

        ConnectorRegistry.get("google_ads")  # raises KeyError if not registered
        ConnectorRegistry.list_keys()         # ["google_ads", "meta_ads", …]
    """

    _registry: dict[str, type["Connector"]] = {}

    @classmethod
    def register(cls, key: str, connector_cls: type["Connector"]) -> None:
        """Register a connector class under ``key``.

        Called automatically by ``Connector.__init_subclass__``.
        Raises ``ValueError`` on duplicate registration to catch accidental
        key collisions during development.
        """
        if key in cls._registry and cls._registry[key] is not connector_cls:
            raise ValueError(
                f"Connector key {key!r} is already registered by "
                f"{cls._registry[key].__name__}. "
                "Each platform key must be unique."
            )
        cls._registry[key] = connector_cls

    @classmethod
    def get(cls, key: str) -> type["Connector"]:
        """Return the connector class for ``key``.

        Raises
        ------
        KeyError
            If no connector is registered for the given key.
        """
        try:
            return cls._registry[key]
        except KeyError:
            raise KeyError(
                f"No connector registered for platform key {key!r}. "
                f"Available: {sorted(cls._registry)}"
            ) from None

    @classmethod
    def list_keys(cls) -> list[str]:
        """Return a sorted list of all registered platform keys."""
        return sorted(cls._registry)

    @classmethod
    def _reset(cls) -> None:
        """Clear the registry — for use in tests only."""
        cls._registry.clear()
