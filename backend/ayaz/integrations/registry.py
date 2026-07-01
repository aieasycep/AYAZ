"""Integration registry — maps integration keys to Integration classes.

Mirrors ``ayaz/connectors/registry.py`` in structure and auto-registration
pattern, extended with catalog queries and the dynamic per-tenant Copilot
tool-pool method (design §5.2, §6.1).

Auto-registration
-----------------
``Integration.__init_subclass__`` calls ``IntegrationRegistry.register()``
whenever a subclass with a ``metadata`` attribute is defined.  Importing
``ayaz.integrations`` (via ``__init__.py``) triggers all subclass definitions
and fully populates the registry.

Usage::

    from ayaz.integrations import IntegrationRegistry

    # Catalog (all registered integrations)
    catalog = IntegrationRegistry.catalog()

    # Lookup
    cls = IntegrationRegistry.get("slack")

    # Per-tenant dynamic Copilot tool pool
    tools = IntegrationRegistry.action_specs_for({"slack", "google_sheets"})
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ayaz.integrations.base import ActionSpec, Integration, IntegrationMetadata


class IntegrationRegistry:
    """Global registry of all available Integration classes.

    Thread safety: ``_registry`` is populated at import time (module load),
    before any request handling starts.  No locking is needed because Python's
    GIL protects dict operations and all writes happen during single-threaded
    startup.
    """

    _registry: dict[str, type["Integration"]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    @classmethod
    def register(cls, key: str, integration_cls: type["Integration"]) -> None:
        """Register an integration class under ``key``.

        Called automatically by ``Integration.__init_subclass__``.

        Re-registering the *same* class is idempotent (safe for module reloads
        in tests).  Registering a *different* class under an existing key raises
        ``ValueError`` to catch accidental key collisions.

        Parameters
        ----------
        key:
            Unique integration key (lowercase_underscore), e.g. ``"slack"``.
        integration_cls:
            Concrete ``Integration`` subclass to register.

        Raises
        ------
        ValueError
            If ``key`` is already registered by a different class.
        """
        existing = cls._registry.get(key)
        if existing is not None and existing is not integration_cls:
            raise ValueError(
                f"Integration key {key!r} is already registered by "
                f"{existing.__name__}. Each integration key must be unique."
            )
        cls._registry[key] = integration_cls

    # ── Lookup ────────────────────────────────────────────────────────────

    @classmethod
    def get(cls, key: str) -> type["Integration"]:
        """Return the Integration class for ``key``.

        Raises
        ------
        KeyError
            If no integration is registered for the given key.
        """
        try:
            return cls._registry[key]
        except KeyError:
            raise KeyError(
                f"No integration registered for key {key!r}. "
                f"Available: {sorted(cls._registry)}"
            ) from None

    @classmethod
    def list_keys(cls) -> list[str]:
        """Return a sorted list of all registered integration keys."""
        return sorted(cls._registry)

    # ── Catalog queries ───────────────────────────────────────────────────

    @classmethod
    def all(cls) -> list[type["Integration"]]:
        """Return all registered Integration classes (insertion order preserved)."""
        return list(cls._registry.values())

    @classmethod
    def catalog(cls) -> list["IntegrationMetadata"]:
        """Return ``IntegrationMetadata`` for every registered integration.

        Used by ``GET /api/v1/integrations`` to build the catalog response.
        """
        return [klass.metadata for klass in cls._registry.values()]

    @classmethod
    def filter_by_category(cls, category: str) -> list[type["Integration"]]:
        """Return integrations matching the given category string.

        Parameters
        ----------
        category:
            One of ``"ads"``, ``"analytics"``, ``"messaging"``, ``"social"``,
            ``"ecommerce"``, ``"productivity"``.
        """
        return [
            klass
            for klass in cls._registry.values()
            if klass.metadata.category == category
        ]

    @classmethod
    def filter_by_capability(
        cls, capability: "str | None"
    ) -> list[type["Integration"]]:
        """Return integrations that include the given capability.

        Parameters
        ----------
        capability:
            ``"read"`` or ``"action"`` (matches :class:`Capability` values).
            If ``None``, all integrations are returned.
        """
        if capability is None:
            return list(cls._registry.values())

        from ayaz.integrations.base import Capability

        try:
            cap = Capability(capability)
        except ValueError:
            return []

        return [
            klass
            for klass in cls._registry.values()
            if cap in klass.metadata.capabilities
        ]

    # ── Per-tenant Copilot tool pool (design §6.1) ────────────────────────

    @classmethod
    def action_specs_for(
        cls, connected_keys: "set[str] | list[str]"
    ) -> list[dict]:
        """Build the dynamic Claude tool-spec list for a tenant's connected integrations.

        Called by ``copilot.chat()`` to assemble the per-tenant tool pool.
        Only integrations that are (a) registered, (b) in ``connected_keys``,
        and (c) expose at least one ``ActionSpec`` contribute entries.

        The returned dicts are shaped as Claude tool specifications::

            {
                "name": "slack_send_message",
                "description": "[EYLEM] Belirtilen Slack kanalına mesaj gönderir…",
                "input_schema": {"type": "object", "properties": {...}, "required": [...]},
                "is_action": True,
            }

        Parameters
        ----------
        connected_keys:
            Integration keys the tenant has connected, e.g. ``{"slack", "ga4"}``.
            Unknown keys (not in registry) are silently skipped.

        Returns
        -------
        list[dict]
            Ready-to-use Claude tool spec dicts.  May be empty if none of the
            connected integrations expose actions.
        """
        specs: list[dict] = []
        for key in connected_keys:
            klass = cls._registry.get(key)
            if klass is None:
                continue
            try:
                instance = klass()
            except TypeError:
                # Concrete adapters may require __init__ args — skip gracefully.
                continue
            for action in instance.actions():
                specs.append(
                    {
                        "name": action.name,
                        "description": action.description_tr,
                        "input_schema": action.input_schema,
                        "is_action": action.is_write,
                    }
                )
        return specs

    @classmethod
    def find_by_action(cls, action_name: str) -> "type[Integration] | None":
        """Find the Integration class that owns a given action name.

        Used by ``copilot_tools.dispatch()`` to route unknown tool calls to
        the correct integration adapter (design §6.2).

        Parameters
        ----------
        action_name:
            The tool name as dispatched by Claude, e.g. ``"slack_send_message"``.

        Returns
        -------
        type[Integration] | None
            The owning Integration class, or ``None`` if no match.
        """
        for klass in cls._registry.values():
            try:
                instance = klass()
            except TypeError:
                continue
            for action in instance.actions():
                if action.name == action_name:
                    return klass
        return None

    # ── Test helpers ──────────────────────────────────────────────────────

    @classmethod
    def _reset(cls) -> None:
        """Clear the registry — for use in tests only."""
        cls._registry.clear()
