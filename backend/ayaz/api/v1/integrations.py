"""Integration catalog, connect/disconnect, and OAuth callback endpoints.

Wave 2 — Entegrasyon & Aksiyon Merkezi

Endpoints
---------
GET  /integrations/catalog                 — full catalog with per-tenant status
GET  /integrations/connections             — tenant's active connections
POST /integrations/{key}/connect           — initiate connect flow
GET  /integrations/oauth/callback          — OAuth callback (popup close)
DELETE /integrations/{key}/connections/{id} — disconnect
POST /integrations/requests               — record coming-soon demand
POST /integrations/{key}/connect/api-key  — submit API-key credentials

Tenant isolation
----------------
Every DB query MUST filter by ``membership.tenant_id``.  No exceptions.

Billing gates
-------------
- ``min_plan`` on ``IntegrationMetadata`` is checked against the tenant's
  current plan via ``billing.entitlements()``.
- Free plan → may not connect growth-only integrations (HTTP 402).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.integrations import IntegrationRegistry
from ayaz.integrations.base import AuthType, IntegrationStatus
from ayaz.models.integrations import (
    IntegrationConnection,
    IntegrationRequest,
    ProviderGrant,
)
from ayaz.models.oltp import Membership
from ayaz.services import billing, oauth_broker
from ayaz.services.grant_vault import GrantVault
from ayaz.services.oauth_broker import _has_credentials, _sign_state, parse_state

router = APIRouter(prefix="/integrations", tags=["integrations"])
_log = logging.getLogger(__name__)

# ── Plan ordering — used for min_plan gate ─────────────────────────────────────

_PLAN_ORDER = {"free": 0, "starter": 1, "growth": 2, "agency": 3}

_DEFAULT_REDIRECT_BASE = "http://localhost:8000/api/v1"

# Keys in the google_workspace bundle that get auto-connections on callback
_GOOGLE_BUNDLE_KEYS = [
    "google_ads",
    "ga4",
    "search_console",
    "google_sheets",
    "gmail",
]


# ── Billing gate helper ────────────────────────────────────────────────────────


def _check_plan_gate(db: Session, tenant_id: uuid.UUID, min_plan: str) -> None:
    """Raise HTTP 402 if the tenant's plan is below ``min_plan``."""
    if min_plan == "free":
        return
    ents = billing.entitlements(db, tenant_id)
    current_plan = ents.get("plan_code", "free")
    current_rank = _PLAN_ORDER.get(current_plan, 0)
    required_rank = _PLAN_ORDER.get(min_plan, 0)
    if current_rank < required_rank:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Bu entegrasyon en az '{min_plan}' planı gerektirir. "
                f"Mevcut planınız: '{current_plan}'. Lütfen yükseltin."
            ),
        )


# ── Response schemas ──────────────────────────────────────────────────────────


class CatalogCard(BaseModel):
    key: str
    display_name: str
    category: str
    description_tr: str
    auth_type: str
    provider: str
    oauth_scopes: list[str]
    capabilities: list[str]
    icon: str
    icon_bg: str
    aliases: list[str]
    setup_guide_url: str
    coming_soon: bool
    min_plan: str
    status: str  # "connected" | "available" | "coming_soon"


class ConnectionOut(BaseModel):
    id: str
    integration_key: str
    display_name: str
    status: str
    capabilities: list[str]
    scopes: list[str]
    created_at: str
    last_synced_at: str | None


class ConnectResponse(BaseModel):
    mode: str  # "popup" | "api_key" | "operator_setup_required"
    authorize_url: str | None = None
    grant_id: str | None = None
    fields: list[dict] | None = None
    message: str | None = None


class RequestOut(BaseModel):
    id: str
    integration_key: str
    tenant_id: str


# ── Dependency: GrantVault ────────────────────────────────────────────────────


def _get_grant_vault(db: Session = Depends(get_db)) -> GrantVault:
    return GrantVault(db)


# ── Helper: connected keys for a tenant ───────────────────────────────────────


def _connected_keys(db: Session, tenant_id: uuid.UUID) -> set[str]:
    rows = db.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.status == IntegrationStatus.connected.value,
        )
    ).all()
    return {r.integration_key for r in rows}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/catalog",
    response_model=list[CatalogCard],
    summary="Integration catalog with per-tenant status",
)
def get_catalog(
    category: str | None = Query(default=None, description="Filter by category"),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[CatalogCard]:
    """Return all registered integrations with their status for the current tenant.

    Status values:
    - ``connected``   — tenant has an active connection
    - ``available``   — tenant can connect this integration
    - ``coming_soon`` — not yet implemented; shows "Yakında" badge
    """
    connected = _connected_keys(db, membership.tenant_id)

    if category:
        klasses = IntegrationRegistry.filter_by_category(category)
    else:
        klasses = IntegrationRegistry.all()

    cards: list[CatalogCard] = []
    for klass in klasses:
        m = klass.metadata
        if m.coming_soon:
            tenant_status = "coming_soon"
        elif m.key in connected:
            tenant_status = "connected"
        else:
            tenant_status = "available"

        cards.append(
            CatalogCard(
                key=m.key,
                display_name=m.display_name,
                category=m.category,
                description_tr=m.description_tr,
                auth_type=m.auth_type.value,
                provider=m.provider,
                oauth_scopes=list(m.oauth_scopes),
                capabilities=[c.value for c in m.capabilities],
                icon=m.icon,
                icon_bg=m.icon_bg,
                aliases=list(m.aliases),
                setup_guide_url=m.setup_guide_url,
                coming_soon=m.coming_soon,
                min_plan=m.min_plan,
                status=tenant_status,
            )
        )
    return cards


@router.get(
    "/connections",
    response_model=list[ConnectionOut],
    summary="Tenant's active integration connections",
)
def get_connections(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[ConnectionOut]:
    """Return all ``IntegrationConnection`` rows for the current tenant."""
    rows = db.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == membership.tenant_id,
        )
    ).all()

    return [
        ConnectionOut(
            id=str(row.id),
            integration_key=row.integration_key,
            display_name=row.display_name,
            status=row.status,
            capabilities=row.capabilities or [],
            scopes=row.scopes or [],
            created_at=row.created_at.isoformat() if row.created_at else "",
            last_synced_at=(
                row.last_synced_at.isoformat() if row.last_synced_at else None
            ),
        )
        for row in rows
    ]


@router.post(
    "/{key}/connect",
    response_model=ConnectResponse,
    summary="Initiate the connect flow for an integration",
)
def connect_integration(
    key: str,
    redirect_uri: str | None = Query(default=None),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ConnectResponse:
    """Initiate the OAuth or API-key connect flow for an integration.

    - For ``oauth2`` / ``oauth2_bundle``: if operator credentials are configured,
      creates a ``ProviderGrant`` in ``connecting`` state, signs an HMAC state
      token, and returns ``{"mode": "popup", "authorize_url": "..."}`` for the
      frontend to open in a popup window.
    - If operator credentials are absent, returns
      ``{"mode": "operator_setup_required", ...}`` — HTTP 200, no 500.
    - For ``api_key``: returns ``{"mode": "api_key", "fields": [...]}`` with the
      credential fields the user must supply.

    Billing gate: raises 402 if the tenant's plan is below ``min_plan``.
    """
    # Look up integration
    try:
        klass = IntegrationRegistry.get(key)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration not found: {key!r}",
        )

    meta = klass.metadata

    # Billing gate
    _check_plan_gate(db, membership.tenant_id, meta.min_plan)

    # API-key integrations
    if meta.auth_type == AuthType.api_key:
        return ConnectResponse(
            mode="api_key",
            fields=[
                {"name": "api_key", "label": "API Anahtarı", "type": "password"}
            ],
        )

    # OAuth2 / OAuth2-bundle integrations
    provider = meta.provider

    if not _has_credentials(provider):
        return ConnectResponse(
            mode="operator_setup_required",
            message=(
                f"'{meta.display_name}' entegrasyonu için operatör kimlik bilgileri "
                f"henüz yapılandırılmamış. Lütfen sistem yöneticinizle iletişime geçin."
            ),
        )

    # Create a ProviderGrant in "connecting" state
    grant = ProviderGrant(
        tenant_id=membership.tenant_id,
        provider=provider,
        status="connecting",
        scopes=list(meta.oauth_scopes),
        connected_by_user_id=membership.user_id,
    )
    db.add(grant)
    db.flush()  # get grant.id assigned

    # Sign HMAC state — encode grant.id as "aid", tenant_id as "tid"
    state = _sign_state(str(grant.id), str(membership.tenant_id))

    effective_redirect_uri = redirect_uri or (
        f"{_DEFAULT_REDIRECT_BASE}/integrations/oauth/callback"
    )

    try:
        authorize_url = oauth_broker.build_authorize_url(
            platform=provider,
            tenant_id=str(membership.tenant_id),
            redirect_uri=effective_redirect_uri,
            state=state,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    db.commit()

    return ConnectResponse(
        mode="popup",
        authorize_url=authorize_url,
        grant_id=str(grant.id),
    )


@router.get(
    "/oauth/callback",
    response_class=HTMLResponse,
    summary="OAuth callback for integrations (popup close)",
    include_in_schema=False,  # internal — not documented in Swagger
)
def oauth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="HMAC-signed state token"),
    redirect_uri: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Exchange the OAuth code, store tokens, create connections, close popup.

    This endpoint does NOT require the user's JWT — the platform calls it
    directly.  Tenant isolation is enforced via the HMAC-signed state token.

    Steps
    -----
    1. Verify HMAC state → grant_id, tenant_id.
    2. Load the ProviderGrant and verify tenant isolation.
    3. Exchange the code for tokens via the broker.
    4. Encrypt and store tokens in ``grant.vault_secret_ref`` via GrantVault.
    5. Mark the grant as ``active``.
    6. Create ``IntegrationConnection`` rows for all sub-integrations of the
       bundle (or for the single integration if not a bundle).
    7. Return a tiny HTML page that postMessages to the opener and closes itself.
    """
    # 1. Verify state
    try:
        grant_id_str, tenant_id_str = parse_state(state)
    except ValueError as exc:
        return _error_html(f"Invalid state: {exc}")

    try:
        grant_id = uuid.UUID(grant_id_str)
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError:
        return _error_html("Malformed state token.")

    # 2. Load grant with tenant isolation
    grant = db.scalar(
        select(ProviderGrant).where(
            ProviderGrant.id == grant_id,
            ProviderGrant.tenant_id == tenant_id,
        )
    )
    if grant is None:
        return _error_html("Grant not found or tenant mismatch.")

    provider = grant.provider

    effective_redirect_uri = redirect_uri or (
        f"{_DEFAULT_REDIRECT_BASE}/integrations/oauth/callback"
    )

    # 3. Exchange code for tokens
    try:
        tokens = oauth_broker.exchange_code(
            platform=provider,
            code=code,
            redirect_uri=effective_redirect_uri,
        )
    except Exception:
        _log.exception(
            "OAuth token exchange failed: provider=%s grant=%s", provider, grant_id
        )
        return _error_html("Token exchange failed. Please try again.")

    # 4. Store tokens in GrantVault
    vault = GrantVault(db)
    try:
        vault.put(str(grant.id), tokens)
    except Exception:
        _log.exception("Failed to store tokens for grant=%s", grant_id)
        return _error_html("Failed to store tokens. Please try again.")

    # 5. Mark grant as active
    grant.status = "active"
    grant.scopes = list(grant.scopes or [])

    # 6. Create IntegrationConnection rows
    if provider == "google_workspace":
        keys_to_connect = _GOOGLE_BUNDLE_KEYS
    else:
        # For non-bundle providers: connect the single integration matching this provider
        keys_to_connect = [
            k
            for k, klass in IntegrationRegistry._registry.items()
            if klass.metadata.provider == provider
        ]

    _create_connections(db, tenant_id, grant, keys_to_connect)

    db.commit()

    return _success_html(str(grant.id), provider)


@router.delete(
    "/{key}/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an integration",
)
def disconnect_integration(
    key: str,
    connection_id: str,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Disconnect an integration by deleting its ``IntegrationConnection`` row.

    Steps
    -----
    1. Load the connection (tenant-scoped).
    2. Best-effort token revocation via ``oauth_broker.revoke()``.
    3. Clear the vault secret from the grant if no other connections remain.
    4. Delete the connection row.
    5. If the ``ProviderGrant`` has no remaining connections, delete it too.
    """
    try:
        conn_id = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid connection ID.",
        )

    # Load connection with tenant isolation
    conn = db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == conn_id,
            IntegrationConnection.tenant_id == membership.tenant_id,
            IntegrationConnection.integration_key == key,
        )
    )
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found.",
        )

    grant = conn.provider_grant
    grant_id = conn.provider_grant_id

    # Best-effort revocation
    if grant is not None:
        vault = GrantVault(db)
        tokens = vault.get(str(grant.id))
        if tokens:
            access_token = tokens.get("access_token", "")
            if access_token:
                try:
                    oauth_broker.revoke(grant.provider, access_token)
                except Exception:
                    _log.warning(
                        "Revocation failed for grant=%s (continuing)", grant.id
                    )

    # Delete the connection
    db.delete(conn)
    db.flush()

    # If the grant has no remaining connections, clean it up
    if grant_id is not None:
        remaining = db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.provider_grant_id == grant_id,
            )
        )
        if remaining is None and grant is not None:
            vault = GrantVault(db)
            vault.delete(str(grant.id))
            db.delete(grant)
            db.flush()

    db.commit()


@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    response_model=RequestOut,
    summary="Record a coming-soon integration request",
)
def create_integration_request(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> RequestOut:
    """Record a demand signal for a coming-soon integration.

    Body: ``{"integration_key": "trendyol"}``
    """
    integration_key = payload.get("integration_key", "")
    if not integration_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="integration_key is required.",
        )

    req = IntegrationRequest(
        tenant_id=membership.tenant_id,
        integration_key=integration_key,
        requested_by=membership.user_id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return RequestOut(
        id=str(req.id),
        integration_key=req.integration_key,
        tenant_id=str(req.tenant_id),
    )


@router.post(
    "/{key}/connect/api-key",
    response_model=dict,
    summary="Submit API-key credentials for an api_key integration",
)
def connect_api_key(
    key: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    vault: GrantVault = Depends(_get_grant_vault),
) -> dict:
    """Validate API-key credentials and create an IntegrationConnection.

    Body: ``{"api_key": "...", ...}`` — schema depends on the integration.
    """
    try:
        klass = IntegrationRegistry.get(key)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration not found: {key!r}",
        )

    meta = klass.metadata
    if meta.auth_type != AuthType.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Integration {key!r} does not use API-key auth.",
        )

    _check_plan_gate(db, membership.tenant_id, meta.min_plan)

    instance = klass()
    try:
        normalized = instance.validate_credentials(payload)
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Anahtar reddedildi: {exc}",
        )

    # Store in a ProviderGrant (no OAuth, but same table for consistency)
    grant = ProviderGrant(
        tenant_id=membership.tenant_id,
        provider=meta.provider,
        status="active",
        scopes=[],
        connected_by_user_id=membership.user_id,
    )
    db.add(grant)
    db.flush()

    vault.put(str(grant.id), normalized)

    conn = IntegrationConnection(
        tenant_id=membership.tenant_id,
        integration_key=key,
        provider_grant_id=grant.id,
        status=IntegrationStatus.connected.value,
        capabilities=[c.value for c in meta.capabilities],
        scopes=[],
    )
    db.add(conn)
    db.commit()

    return {"ok": True, "connection_id": str(conn.id)}


# ── Private helpers ───────────────────────────────────────────────────────────


def _create_connections(
    db: Session,
    tenant_id: uuid.UUID,
    grant: ProviderGrant,
    integration_keys: list[str],
) -> None:
    """Create IntegrationConnection rows for each key in ``integration_keys``.

    Skips keys that are not registered in the IntegrationRegistry.
    Uses upsert-by-unique-constraint logic: if a connection already exists for
    (tenant_id, integration_key, external_entity_id="") we update its status
    rather than creating a duplicate (the unique constraint would reject it).
    """
    for ikey in integration_keys:
        try:
            klass = IntegrationRegistry.get(ikey)
        except KeyError:
            continue

        meta = klass.metadata

        # Check for existing connection (upsert semantics)
        existing = db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.integration_key == ikey,
                IntegrationConnection.external_entity_id == "",
            )
        )
        if existing is not None:
            existing.status = IntegrationStatus.connected.value
            existing.provider_grant_id = grant.id
            existing.capabilities = [c.value for c in meta.capabilities]
            existing.scopes = list(meta.oauth_scopes)
        else:
            conn = IntegrationConnection(
                tenant_id=tenant_id,
                integration_key=ikey,
                provider_grant_id=grant.id,
                status=IntegrationStatus.connected.value,
                capabilities=[c.value for c in meta.capabilities],
                scopes=list(meta.oauth_scopes),
                display_name=meta.display_name,
            )
            db.add(conn)

    db.flush()


def _success_html(grant_id: str, provider: str) -> HTMLResponse:
    """Return a tiny HTML page that postMessages success to the opener."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Bağlantı tamamlandı</title></head>
<body>
<p>Bağlantı başarılı. Bu pencere kapanıyor...</p>
<script>
  try {{
    window.opener && window.opener.postMessage(
      {{type: 'ayaz:oauth:done', grant_id: {grant_id!r}, provider: {provider!r}}},
      '*'
    );
  }} catch(e) {{}}
  window.close();
</script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


def _error_html(message: str) -> HTMLResponse:
    """Return a tiny HTML page that postMessages an error to the opener."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Bağlantı hatası</title></head>
<body>
<p>Hata: {message}</p>
<script>
  try {{
    window.opener && window.opener.postMessage(
      {{type: 'ayaz:oauth:error', error: {message!r}}},
      '*'
    );
  }} catch(e) {{}}
  window.close();
</script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)
