"""Integration adapter base — unified OKUMA (read) + YAZMA (write) abstraction.

Design (§5, entegrasyon-aksiyon-merkezi-tasarim-2026-06.md)
------------------------------------------------------------
``Integration`` is the single adapter interface every integration must implement.
It unifies:
  - READ side  — ``as_connector()`` bridges to the existing Connector/sync engine
  - WRITE side — ``actions()`` + ``execute_action()`` power Copilot tool-calling
  - Metadata   — ``IntegrationMetadata`` drives the catalog UI, OAuth flows,
                  billing gates, and Copilot tool registration automatically.

Auto-registration
-----------------
Any subclass that sets a ``metadata`` class attribute is automatically registered
in ``IntegrationRegistry`` via ``__init_subclass__`` — identical pattern to the
existing ``Connector`` SDK.

This module is pure-abstract.  No concrete adapters here; those live in
``ayaz/integrations/<platform>.py`` and are imported by ``__init__.py``.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ayaz.connectors.base import Connector, ConnectorConfig
    from ayaz.services.vault import SecretsVault


# ── Enumerations ──────────────────────────────────────────────────────────────


class AuthType(str, Enum):
    """Authentication mechanism required to connect this integration."""

    oauth2 = "oauth2"
    """Standard per-product OAuth 2.0 Authorization Code flow."""

    oauth2_bundle = "oauth2_bundle"
    """Single grant shared by multiple product integrations (e.g. Google Workspace
    → Google Ads + GA4 + Search Console all share one token)."""

    api_key = "api_key"
    """Provider does not support OAuth; user supplies an API key/secret."""

    none = "none"
    """No credentials needed (e.g. public endpoints, webhooks only)."""


class Capability(str, Enum):
    """What an integration can do from AYAZ's perspective."""

    read = "read"
    """Data source — produces rows for ``fact_daily_metrics`` / feeds via the
    Connector sync engine."""

    action = "action"
    """Copilot write action — appears in the per-tenant tool pool and can be
    called by Claude after user confirmation (ADR-8)."""


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActionSpec:
    """Describes a single write action surfaced as a Copilot tool.

    The shape mirrors Claude's ``tool`` specification so
    ``IntegrationRegistry.action_specs_for()`` can emit ready-to-use tool dicts
    without further transformation.

    Attributes
    ----------
    name:
        Globally unique tool name, e.g. ``"slack_send_message"``.  Must be
        snake_case; no spaces.
    description_tr:
        Turkish-language description passed to Claude.  Should start with
        ``"[EYLEM]"`` prefix for write actions so the model knows to confirm
        before executing.
    input_schema:
        JSON Schema object (``{"type": "object", "properties": {...}, "required": [...]}``)
        describing the tool's input parameters.
    is_write:
        ``True`` for actions that mutate external state.  Triggers the
        two-phase confirm-before-execute flow (ADR-8).  Default ``True``.
    required_scopes:
        OAuth scopes that must be present in the ``IntegrationConnection.scopes``
        list for this action to be callable.  Checked at dispatch time.
    """

    name: str
    description_tr: str
    input_schema: dict[str, Any]
    is_write: bool = True
    required_scopes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IntegrationMetadata:
    """Static descriptor for an integration — the single source of truth.

    Every field here drives a downstream concern:
    - ``key`` / ``display_name`` / ``category`` / ``description_tr`` → catalog UI
    - ``auth_type`` / ``provider`` / ``oauth_scopes`` → OAuth/credential flows
    - ``capabilities`` → feature gating in UI and Copilot tool pool
    - ``min_plan`` → billing gate (checked against PLANS entitlements)
    - ``coming_soon`` → shows "Yakında" badge, disables connect button
    - ``aliases`` → full-text search in the integration catalog
    - ``setup_guide_url`` → "Nasıl alınır?" link shown in API-key modal

    Attributes
    ----------
    key:
        Unique integration identifier, lowercase_underscore.
        Examples: ``"slack"``, ``"google_ads"``, ``"trendyol"``.
    display_name:
        Human-readable name shown in the catalog.
    category:
        Catalog grouping: ``"ads"`` | ``"analytics"`` | ``"messaging"`` |
        ``"social"`` | ``"ecommerce"`` | ``"productivity"``.
    description_tr:
        One-sentence Turkish description shown on the integration card.
    auth_type:
        How credentials are obtained (see :class:`AuthType`).
    provider:
        OAuth provider key as used in ``oauth_broker._PLATFORM_CONFIGS``
        (e.g. ``"google_workspace"``, ``"meta"``, ``"slack"``).
        For ``api_key`` integrations this can be the same as ``key``.
    oauth_scopes:
        OAuth scopes this integration needs.  Subset of the full provider
        bundle for ``oauth2_bundle`` auth types.
    capabilities:
        Tuple of :class:`Capability` values.
    icon:
        Single letter, emoji, or asset key for the catalog card icon.
    icon_bg:
        CSS hex color for the icon background (brand color).
    aliases:
        Additional Turkish search terms (e.g. ``("analitik", "ölçüm")`` for GA4).
    setup_guide_url:
        URL of the "Nasıl alınır?" step-by-step guide (api_key integrations).
    coming_soon:
        When ``True`` the integration is shown with a "Yakında" badge and the
        connect button is disabled.
    min_plan:
        Minimum billing plan required: ``"free"`` | ``"starter"`` |
        ``"growth"`` | ``"agency"``.
    """

    key: str
    display_name: str
    category: str
    description_tr: str
    auth_type: AuthType
    provider: str
    oauth_scopes: tuple[str, ...] = field(default_factory=tuple)
    capabilities: tuple[Capability, ...] = field(
        default_factory=lambda: (Capability.read,)
    )
    icon: str = ""
    icon_bg: str = "#6b7280"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    setup_guide_url: str = ""
    coming_soon: bool = False
    min_plan: str = "free"


# ── Action execution context ──────────────────────────────────────────────────


@dataclass
class ActionContext:
    """Per-call context passed to ``Integration.execute_action()``.

    Bundles tenant isolation, Vault token retrieval, and audit logging so
    adapter implementations never touch security-sensitive plumbing directly.

    Attributes
    ----------
    tenant_id:
        UUID of the tenant making the request.  Every DB query inside
        ``execute_action`` MUST filter by this value.
    connection_id:
        UUID of the ``integration_connections`` row for this integration instance.
    user_id:
        UUID of the user who triggered the action (for audit log + RBAC).
    db:
        Active SQLAlchemy session (caller manages lifecycle / commit).
    vault:
        Injected ``SecretsVault`` implementation — use ``vault_get()`` rather
        than calling this directly.
    _vault_secret_ref:
        Internal: the ``vault_secret_ref`` string from the associated
        ``provider_grants`` row.  Populated by the caller (dispatcher).
    """

    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    user_id: uuid.UUID
    db: "Session"
    vault: "SecretsVault"
    _vault_secret_ref: str = ""

    def vault_get(self) -> dict[str, Any]:
        """Return the decrypted OAuth token dict for this connection.

        Raises
        ------
        KeyError
            If no secret is found for the configured vault ref.
        """
        secret = self.vault.get(self._vault_secret_ref)
        if secret is None:
            raise KeyError(
                f"No vault secret found for ref={self._vault_secret_ref!r} "
                f"(connection_id={self.connection_id})"
            )
        return secret

    def audit(
        self,
        action_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        status: str,
        *,
        was_auto: bool = False,
    ) -> None:
        """Write an audit log entry for this action (ADR-8).

        Records a row in ``action_audit_log`` with PII/secrets redacted from
        ``args``.  The ``db`` session is flushed (not committed) so the caller
        controls the transaction boundary.

        Parameters
        ----------
        action_name:
            The tool name, e.g. ``"slack_send_message"``.
        args:
            Action arguments — PII fields (``text``, ``message``, ``body``,
            ``email``, ``subject``, ``content``) and secret fields
            (``token``, ``password``, ``secret``, ``key``) are redacted to
            ``"[REDACTED]"`` before persistence.
        result:
            Action result dict (used to extract error message).
        status:
            ``"ok"`` | ``"error"`` | ``"denied"``.
        was_auto:
            ``True`` if the action was triggered by an automation rule rather
            than direct user request.
        """
        import logging

        _log = logging.getLogger(__name__)

        # ── PII / secret redaction ────────────────────────────────────────
        _PII_FIELDS = frozenset(
            {
                "text", "message", "body", "email", "subject", "content",
                "description", "note", "comment",
            }
        )
        _SECRET_FIELDS = frozenset(
            {
                "token", "access_token", "refresh_token", "password",
                "secret", "api_key", "api_secret", "client_secret", "key",
            }
        )
        redacted: dict[str, Any] = {}
        for k, v in (args or {}).items():
            k_lower = k.lower()
            if k_lower in _SECRET_FIELDS:
                redacted[k] = "[REDACTED:SECRET]"
            elif k_lower in _PII_FIELDS:
                # Keep short values (e.g. channel names) but redact long ones
                s = str(v) if v is not None else ""
                redacted[k] = s[:40] + "…" if len(s) > 40 else s
            else:
                redacted[k] = v

        # ── Resolve integration_key from action_name ──────────────────────
        # Attempt a lookup in the registry; fall back to the action name prefix.
        integration_key = action_name.split("_")[0] if "_" in action_name else action_name
        try:
            from ayaz.integrations.registry import IntegrationRegistry

            klass = IntegrationRegistry.find_by_action(action_name)
            if klass is not None:
                integration_key = klass.metadata.key
        except Exception:
            pass  # registry may not be fully loaded in edge cases

        # ── Error message ────────────────────────────────────────────────
        error_msg: str | None = None
        if status == "error":
            error_msg = str(result.get("error", "")) or None

        # ── Persist ──────────────────────────────────────────────────────
        try:
            from ayaz.models.integrations import ActionAuditLog

            log_row = ActionAuditLog(
                id=__import__("uuid").uuid4(),
                tenant_id=self.tenant_id,
                integration_key=integration_key,
                action_name=action_name,
                params_summary=redacted,
                status=status,
                error=error_msg,
                actor_user_id=self.user_id if not was_auto else None,
                was_auto=was_auto,
            )
            self.db.add(log_row)
            self.db.flush()
        except Exception as exc:
            # Audit failure must NEVER crash the action itself — log and continue
            _log.error(
                "audit write failed for action=%s tenant=%s: %s",
                action_name,
                self.tenant_id,
                exc,
                exc_info=True,
            )
            return

        _log.info(
            "audit action=%s tenant=%s connection=%s user=%s status=%s auto=%s",
            action_name,
            self.tenant_id,
            self.connection_id,
            self.user_id,
            status,
            was_auto,
        )


# ── Canonical integration status vocabulary ───────────────────────────────────


class IntegrationStatus(str, Enum):
    """Canonical lifecycle status for ``integration_connections.status``.

    This is the single vocabulary used by the new Integration layer.  The
    existing ``SyncStatus`` enum (``idle`` / ``syncing`` / ``success`` /
    ``error`` / ``paused``) is preserved for the ``connected_accounts`` table
    and the ad-sync engine — do NOT replace it.

    Mapping to legacy ``SyncStatus`` (for connectors-api.ts consumers):
        SyncStatus.idle     → IntegrationStatus.disconnected  (no sync yet)
        SyncStatus.syncing  → IntegrationStatus.syncing
        SyncStatus.success  → IntegrationStatus.connected
        SyncStatus.error    → IntegrationStatus.error
        SyncStatus.paused   → IntegrationStatus.disconnected

    Mapping to UI labels (replaces connectors-api.ts:74 clientside mask):
        connected        → "Bağlı"           (green badge)
        connecting       → "Bağlanıyor…"     (blue, animated)
        syncing          → "Senkronize ediliyor" (blue, animated)
        needs_reconnect  → "Yenileme gerekli"   (amber badge)
        error            → "Hata"              (red badge)
        disconnected     → "Bağlı değil"     (grey, connect button shown)
    """

    connected = "connected"
    """OAuth grant active; last health check passed."""

    connecting = "connecting"
    """OAuth flow initiated; awaiting callback / credential validation."""

    syncing = "syncing"
    """Data sync actively running."""

    needs_reconnect = "needs_reconnect"
    """Token expired or revoked; user must re-authorize (amber warning)."""

    error = "error"
    """Last sync or health check failed with a non-auth error."""

    disconnected = "disconnected"
    """Integration manually disconnected or never connected."""


# ── Abstract base class ───────────────────────────────────────────────────────


class Integration(abc.ABC):
    """Abstract base class for all AYAZ integrations.

    Concrete subclasses MUST set ``metadata`` as a class attribute.
    Setting ``metadata`` triggers automatic registration in
    ``IntegrationRegistry`` via ``__init_subclass__`` — no manual wiring.

    Implement only the methods relevant to the integration's capabilities:
    - READ  → override ``as_connector()``
    - WRITE → override ``actions()`` and ``execute_action()``
    - Both  → override all four methods

    See ``§5.3`` of the design doc for three canonical examples:
    - Slack (pure action / write-only)
    - Google Sheets (action + bundle)
    - Google Ads (read, wraps existing Connector)
    """

    # Subclasses set this as a class attribute; __init_subclass__ reads it.
    metadata: IntegrationMetadata

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register any subclass that declares ``metadata``."""
        super().__init_subclass__(**kwargs)
        meta = getattr(cls, "metadata", None)
        if meta is not None and isinstance(meta, IntegrationMetadata):
            # Lazy import avoids circular: base → registry → base
            from ayaz.integrations.registry import IntegrationRegistry

            IntegrationRegistry.register(meta.key, cls)

    # ── Credential validation (api_key integrations) ──────────────────────

    def validate_credentials(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Validate API-key credentials by making a live test call.

        Called by the ``POST /api/v1/integrations/{key}/credentials`` endpoint
        before persisting anything to Vault.

        Parameters
        ----------
        creds:
            Raw credential dict from the user (e.g. ``{"api_key": "...",
            "api_secret": "...", "seller_id": "..."}``)

        Returns
        -------
        dict
            Normalized credential dict to store in Vault.  May add derived
            fields (e.g. resolved account name).

        Raises
        ------
        ValueError
            If credentials are invalid (wrong key, network rejection, etc.).
            The message is forwarded to the user as ``"Anahtar reddedildi…"``.
        NotImplementedError
            For oauth2 integrations that should never call this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support API-key credentials. "
            f"auth_type={self.metadata.auth_type!r}"
        )

    # ── READ side ─────────────────────────────────────────────────────────

    def as_connector(self, cfg: "ConnectorConfig") -> "Connector | None":
        """Return a ``Connector`` instance backed by the existing sync engine.

        For integrations with ``Capability.read``, return the connector that
        feeds ``fact_daily_metrics``.  The default returns ``None``; override
        in read-capable integrations.

        Parameters
        ----------
        cfg:
            ``ConnectorConfig`` with the connected-account context.

        Returns
        -------
        Connector | None
            ``None`` if this integration has no read capability.
        """
        return None

    # ── WRITE side ────────────────────────────────────────────────────────

    def actions(self) -> list[ActionSpec]:
        """Return the list of write actions this integration exposes as Copilot tools.

        Override in integrations with ``Capability.action``.
        Return an empty list for read-only integrations.
        """
        return []

    def execute_action(
        self,
        name: str,
        args: dict[str, Any],
        *,
        ctx: ActionContext,
    ) -> dict[str, Any]:
        """Execute a named action with the given arguments.

        Parameters
        ----------
        name:
            Action name (must match one of the ``ActionSpec.name`` values
            returned by ``actions()``).
        args:
            Validated input dict matching the action's ``input_schema``.
        ctx:
            Execution context — use ``ctx.vault_get()`` for tokens,
            ``ctx.audit()`` to write the audit entry.

        Returns
        -------
        dict
            Action result.  For ``is_write=True`` actions the result is first
            returned as a preview (``requires_confirmation=True``); the caller
            re-invokes with ``confirmed=True`` to commit (two-phase, ADR-8).

        Raises
        ------
        NotImplementedError
            If the action name is unknown or the subclass has not implemented
            the write side.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.execute_action is not implemented "
            f"for action={name!r}"
        )

    # ── Discovery ─────────────────────────────────────────────────────────

    def discover(self, ctx: ActionContext) -> list[dict[str, Any]]:
        """List accessible accounts / entities after OAuth completes.

        Used by ``GET /api/v1/integrations/{key}/discover`` to let the user
        choose which account/channel/property to connect when a provider
        exposes multiple.

        Returns
        -------
        list[dict]
            Each dict SHOULD include at minimum ``{"id": "...", "name": "..."}``.
            Returns empty list if discovery is not applicable.
        """
        return []
