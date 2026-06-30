"""Integration SDK package.

Usage
-----
Import ``IntegrationRegistry`` to look up an integration class by key::

    from ayaz.integrations import IntegrationRegistry
    cls = IntegrationRegistry.get("slack")

Or access the full catalog::

    from ayaz.integrations import IntegrationRegistry
    catalog = IntegrationRegistry.catalog()

Auto-registration
-----------------
Importing this package triggers the import of every concrete adapter module
below.  Each module defines an ``Integration`` subclass with a ``metadata``
class attribute; ``Integration.__init_subclass__`` calls
``IntegrationRegistry.register()`` automatically.  No manual wiring needed.
"""

from ayaz.integrations.base import (
    ActionContext,
    ActionSpec,
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
    IntegrationStatus,
)
from ayaz.integrations.registry import IntegrationRegistry

# ── Concrete adapters (self-register on import) ────────────────────────────
# Each import below triggers Integration.__init_subclass__ → registry.register()
# Add new adapters here as they are implemented.
#
# Wave 1 (foundation): no concrete adapters yet — they arrive in Wave 2+.
# The import block is intentionally left empty so this package is importable
# and testable without any concrete adapter implementations.
#
# Example (uncomment when adapters exist):
# import ayaz.integrations.slack          # noqa: F401  — registers "slack"
# import ayaz.integrations.google_ads     # noqa: F401  — registers "google_ads"

__all__ = [
    "ActionContext",
    "ActionSpec",
    "AuthType",
    "Capability",
    "Integration",
    "IntegrationMetadata",
    "IntegrationRegistry",
    "IntegrationStatus",
]
