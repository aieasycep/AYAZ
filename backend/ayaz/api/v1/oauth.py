"""OAuth 2.0 authorization and callback endpoints.

Wiring (team lead adds to main.py)
-----------------------------------
    from ayaz.api.v1.oauth import router as oauth_router
    app.include_router(oauth_router, prefix="/api/v1")

Flow
----
1. Frontend calls ``GET /oauth/{platform}/authorize`` (Bearer token required).
   Response: ``{"authorize_url": "https://accounts.google.com/..."}``
   A ``ConnectedAccount`` in ``pending`` status is created (or located) and its
   UUID is encoded into the OAuth ``state`` parameter so the callback can map
   the code back to the right account.

2. Browser is redirected to the platform consent screen.

3. Platform redirects to ``GET /oauth/{platform}/callback?code=&state=``.
   The endpoint decodes the state, exchanges the code for tokens, stores the
   tokens in the Vault, and marks the account as ``idle`` (ready to sync).
   Returns ``{"status": "connected", "account_id": "<uuid>"}`` (JSON).
   In a production SPA, redirect to the frontend success URL instead.

Tenant isolation
----------------
Every ``ConnectedAccount`` row is created with ``tenant_id`` from the JWT so
cross-tenant access is impossible by construction.  The callback verifies that
the decoded ``state.tid`` matches the row's ``tenant_id`` before proceeding.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.config import settings
from ayaz.database import SessionLocal
from ayaz.models.oltp import ConnectedAccount, Membership, Platform, SyncStatus
from ayaz.services import oauth_broker
from ayaz.services.oauth_broker import _sign_state, parse_state
from ayaz.services.vault import EncryptedColumnVault, SecretsVault

router = APIRouter(prefix="/oauth", tags=["oauth"])

logger = logging.getLogger(__name__)

# ── Dependency: vault instance ────────────────────────────────────────────────


def _get_vault() -> SecretsVault:
    """Return a Vault instance backed by the production session factory.

    Override this dependency in tests to inject an InMemoryVault.
    """
    return EncryptedColumnVault(session_factory=SessionLocal)


# ── Response schemas ──────────────────────────────────────────────────────────


class AuthorizeResponse(BaseModel):
    authorize_url: str
    account_id: str


class CallbackResponse(BaseModel):
    status: str
    account_id: str


# ── Default redirect URI ──────────────────────────────────────────────────────

# The redirect_uri must be registered in each platform's developer console.
# Override per-request via the ``redirect_uri`` query param; otherwise the base
# comes from ``settings.oauth_redirect_base`` (env: OAUTH_REDIRECT_BASE), which
# MUST be set to the deployed backend URL in production.
def _redirect_base() -> str:
    return settings.oauth_redirect_base


def _panel_redirect(platform: str, ok: bool) -> RedirectResponse | None:
    """Redirect the browser back to the panel after the OAuth callback.

    Returns a 302 to the Integration Center (Veri Kaynakları tab) with a
    ``connected`` / ``error`` query flag when ``FRONTEND_BASE_URL`` is set;
    returns ``None`` (caller falls back to JSON / raising) when it is not — so
    tests and pure-API/dev usage are unaffected.
    """
    base = (settings.frontend_base_url or "").rstrip("/")
    if not base:
        return None
    flag = "connected" if ok else "error"
    return RedirectResponse(
        url=f"{base}/integrations?tab=veri-kaynaklari&{flag}={platform}",
        status_code=status.HTTP_302_FOUND,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _platform_enum(platform: str) -> Platform:
    """Resolve a platform string to the Platform enum, raising 404 if unknown."""
    try:
        return Platform(platform)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform: {platform!r}",
        )


def _get_or_create_pending_account(
    db: Session,
    tenant_id: uuid.UUID,
    platform: Platform,
) -> ConnectedAccount:
    """Return an existing pending account for (tenant, platform) or create one.

    Only one pending account per (tenant, platform) is kept.  If the user
    restarts the OAuth flow we reuse the same account row so the account list
    stays clean.
    """
    existing = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.tenant_id == tenant_id,
            ConnectedAccount.platform == platform,
            ConnectedAccount.sync_status == SyncStatus.idle,
            # vault_secret_ref is empty for pending accounts
            ConnectedAccount.vault_secret_ref == "",
        )
    )
    if existing is not None:
        return existing

    account = ConnectedAccount(
        tenant_id=tenant_id,
        platform=platform,
        external_account_id="",  # populated after first sync / discover()
        display_name=f"{platform.value} (connecting…)",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/{platform}/authorize",
    response_model=AuthorizeResponse,
    summary="Start the OAuth2 authorization flow for a platform",
)
def authorize(
    platform: str,
    redirect_uri: str | None = Query(default=None),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AuthorizeResponse:
    """Return the platform consent URL to redirect the user to.

    Creates (or locates) a pending ConnectedAccount and embeds its ID in the
    ``state`` parameter so the callback can map the code back to this account.

    Query params
    ------------
    redirect_uri:
        Override the default redirect URI.  Must match what is registered in
        the platform developer console.
    """
    platform_enum = _platform_enum(platform)

    account = _get_or_create_pending_account(db, membership.tenant_id, platform_enum)

    effective_redirect_uri = redirect_uri or (
        f"{_redirect_base()}/oauth/{platform}/callback"
    )

    state = _sign_state(str(account.id), str(membership.tenant_id))

    try:
        url = oauth_broker.build_authorize_url(
            platform=platform,
            tenant_id=str(membership.tenant_id),
            redirect_uri=effective_redirect_uri,
            state=state,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return AuthorizeResponse(authorize_url=url, account_id=str(account.id))


@router.get(
    "/{platform}/callback",
    response_model=None,
    summary="OAuth2 callback — exchange code and store tokens",
)
def callback(
    platform: str,
    code: str = Query(..., description="Authorization code from the platform"),
    state: str = Query(..., description="CSRF state token"),
    redirect_uri: str | None = Query(default=None),
    db: Session = Depends(get_db),
    vault: SecretsVault = Depends(_get_vault),
) -> Any:
    """Exchange the authorization code for tokens and persist them in the Vault.

    This endpoint does NOT require the user's JWT because the platform calls
    it directly after consent.  Tenant isolation is enforced via the ``state``
    token (which encodes both the account id and the tenant id).

    Steps
    -----
    1. Decode ``state`` → (account_id, tenant_id).
    2. Load the ConnectedAccount and verify it belongs to the decoded tenant.
    3. Exchange the code for tokens via the broker.
    4. Store tokens in the Vault.
    5. Mark the account as ``idle`` (ready to sync).
    6. Return ``{"status": "connected", "account_id": "..."}``
    """
    # 1. Decode state
    try:
        account_id_str, tenant_id_str = parse_state(state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid state: {exc}",
        )

    try:
        account_id = uuid.UUID(account_id_str)
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed state token.",
        )

    # 2. Load account and verify tenant isolation
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            ConnectedAccount.tenant_id == tenant_id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or tenant mismatch.",
        )

    effective_redirect_uri = redirect_uri or (
        f"{_redirect_base()}/oauth/{platform}/callback"
    )

    # 3. Exchange code for tokens
    #    Never surface the raw exception to the client: provider error bodies can
    #    echo back the authorization code, client_secret, or token fragments.
    try:
        tokens = oauth_broker.exchange_code(
            platform=platform,
            code=code,
            redirect_uri=effective_redirect_uri,
        )
    except Exception:
        logger.exception(
            "OAuth token exchange failed: platform=%s account=%s",
            platform,
            account.id,
        )
        redir = _panel_redirect(platform, ok=False)
        if redir is not None:
            return redir
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Token exchange failed.",
        )

    # 4. Store tokens in vault (uses account.id as the ref)
    try:
        oauth_broker.store_tokens_for_account(
            account_id=str(account.id),
            tokens=tokens,
            vault=vault,
        )
    except Exception:
        logger.exception(
            "Failed to store OAuth tokens: account=%s", account.id
        )
        redir = _panel_redirect(platform, ok=False)
        if redir is not None:
            return redir
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store tokens.",
        )

    # 5. Mark the account as idle / connected and refresh the vault_secret_ref
    #    The EncryptedColumnVault already wrote the blob to vault_secret_ref;
    #    reload the account to pick up the updated column.
    db.refresh(account)
    account.sync_status = SyncStatus.idle
    db.commit()

    # 6. Redirect the browser back to the panel (customer flow), or return JSON
    #    confirmation when no frontend base URL is configured (dev / API / tests).
    redir = _panel_redirect(platform, ok=True)
    if redir is not None:
        return redir
    return CallbackResponse(status="connected", account_id=str(account.id))
