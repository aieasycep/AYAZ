"""Connector management endpoints (skeleton).

GET  /connectors/                  — list registered connector platforms
GET  /connectors/accounts          — list tenant's connected accounts
POST /connectors/accounts          — link a new connected account (TODO: OAuth flow)
GET  /connectors/accounts/{id}     — get one connected account
DELETE /connectors/accounts/{id}   — unlink a connected account

TODO (Faz 1 — Integrations): implement real OAuth broker flows.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.connectors import ConnectorRegistry
from ayaz.connectors.base import ConnectorConfig
from ayaz.database import SessionLocal
from ayaz.models.oltp import ConnectedAccount, Membership, Platform, SyncStatus
from ayaz.services.vault import EncryptedColumnVault, SecretsVault

logger = logging.getLogger(__name__)


def _get_vault() -> SecretsVault:
    """Return a Vault backed by the production session factory.

    Overridden in tests to inject an InMemoryVault.
    """
    return EncryptedColumnVault(session_factory=SessionLocal)

# M10 Billing: plan-gating dependency
# This import is intentionally deferred to a local import-style reference inside
# the endpoint signature so that circular imports are avoided.  The dependency is
# declared as a default parameter so FastAPI resolves it lazily at request time.
from ayaz.services.billing import require_within_data_source_limit

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ── Response schemas ──────────────────────────────────────────────────────────


class PlatformInfo(BaseModel):
    key: str


class ConnectedAccountResponse(BaseModel):
    id: uuid.UUID
    platform: str
    external_account_id: str
    display_name: str
    sync_status: str
    watermark: str | None

    model_config = {"from_attributes": True}


class CreateAccountRequest(BaseModel):
    platform: Platform
    external_account_id: str
    display_name: str = ""
    vault_secret_ref: str = ""  # provided by OAuth Broker after auth flow


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[PlatformInfo],
    summary="List all registered connector platforms",
)
def list_platforms() -> list[PlatformInfo]:
    """Return the platform keys of all connectors registered in the SDK."""
    return [PlatformInfo(key=k) for k in ConnectorRegistry.list_keys()]


@router.get(
    "/accounts",
    response_model=list[ConnectedAccountResponse],
    summary="List this tenant's connected accounts",
)
def list_accounts(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[ConnectedAccount]:
    """Return all connected accounts belonging to the current tenant.

    TODO (Faz 1 — RLS): Once Postgres RLS is active this explicit WHERE clause
    can be replaced by the RLS policy; keep it here until then.
    """
    return list(
        db.scalars(
            select(ConnectedAccount).where(
                ConnectedAccount.tenant_id == membership.tenant_id
            )
        )
    )


@router.post(
    "/accounts",
    response_model=ConnectedAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a new connected account to this tenant",
)
def create_account(
    body: CreateAccountRequest,
    db: Session = Depends(get_db),
    membership: Annotated[Membership, Depends(get_current_membership)] = ...,
    # M10 Billing: enforce the plan's max_data_sources limit before creating.
    # Returns 402 Payment Required with a Turkish message when the limit is reached.
    # Agency plan is "unlimited" and always passes.
    _plan_gate: None = Depends(require_within_data_source_limit),
    allow_duplicate: bool = False,
) -> ConnectedAccount:
    """Create a ConnectedAccount row after the OAuth flow completes.

    In production this endpoint is called by the OAuth Broker callback after
    it has exchanged the auth code for tokens and stored them in Vault.
    The ``vault_secret_ref`` is the Vault path returned by the Broker.

    Duplicate-link guard
    --------------------
    If an account with the same (platform, external_account_id) already exists
    for this tenant, the endpoint returns HTTP 409 Conflict with a Turkish error
    message and the list of existing accounts.  This prevents silent double-
    counting in every SUM/ROAS aggregation.

    To bypass the guard and link the account anyway (e.g. for migrations or
    debugging), pass ``?allow_duplicate=true``.  The endpoint will proceed but
    log a warning.

    TODO (Faz 1): add role check — only owner/admin may link new accounts.
    """
    if not allow_duplicate:
        from ayaz.services.data_quality import check_duplicate_before_link
        dupe_check = check_duplicate_before_link(
            db,
            membership.tenant_id,
            body.platform,
            body.external_account_id,
        )
        if dupe_check["is_duplicate"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "duplicate_account",
                    "message": dupe_check["warning"],
                    "existing_accounts": dupe_check["existing_accounts"],
                },
            )

    account = ConnectedAccount(
        tenant_id=membership.tenant_id,
        platform=body.platform,
        external_account_id=body.external_account_id,
        display_name=body.display_name,
        vault_secret_ref=body.vault_secret_ref,
        sync_status=SyncStatus.idle,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get(
    "/accounts/{account_id}",
    response_model=ConnectedAccountResponse,
    summary="Get one connected account",
)
def get_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ConnectedAccount:
    """Fetch a single connected account, scoped to the current tenant."""
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            # Explicit tenant_id filter — enforces isolation until RLS is active
            ConnectedAccount.tenant_id == membership.tenant_id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hesap bulunamadı.",
        )
    return account


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a connected account",
)
def delete_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Remove a connected account from this tenant.

    TODO (Faz 1): also revoke the OAuth token via Vault before deleting.
    TODO (Faz 1): add role check — only owner/admin may delete accounts.
    """
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            ConnectedAccount.tenant_id == membership.tenant_id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hesap bulunamadı.",
        )
    db.delete(account)
    db.commit()


class SyncResultResponse(BaseModel):
    status: str
    account_id: str
    inserted: int = 0
    updated: int = 0
    records_processed: int = 0


@router.post(
    "/accounts/{account_id}/sync",
    response_model=SyncResultResponse,
    summary="Trigger a synchronous data sync for one connected account",
)
def sync_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    vault: SecretsVault = Depends(_get_vault),
    days: int = 30,
) -> SyncResultResponse:
    """Pull recent data for a connected account and upsert into the warehouse.

    Runs the sync **synchronously** (there is no background worker on the
    current deployment), scoped to the requesting tenant.  The stored OAuth
    credentials are loaded from the Vault and injected into the connector.

    ``days`` bounds the backfill window (clamped to 1..90; default 30).

    Errors
    ------
    404 — account not found / tenant mismatch.
    502 — the connector/sync failed (credentials, permissions, or platform API).
          The account's ``sync_status`` is left as ``error``.
    """
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            ConnectedAccount.tenant_id == membership.tenant_id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hesap bulunamadı.",
        )

    window = max(1, min(days, 90))
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=window - 1)

    # Local import avoids any import-time coupling between the API and the
    # sync service (which pulls in the connector SDK).
    from ayaz.services.sync import sync_connected_account

    try:
        result = sync_connected_account(db, account, since, until, vault=vault)
    except Exception:
        # sync_connected_account already set sync_status=error and committed.
        logger.exception("Manual sync failed: account=%s", account_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Senkronizasyon başarısız oldu. Bağlantıyı ve platform izinlerini kontrol edin.",
        )

    return SyncResultResponse(
        status="success",
        account_id=str(account.id),
        inserted=int(result.get("inserted", 0)),
        updated=int(result.get("updated", 0)),
        records_processed=int(result.get("records_processed", 0)),
    )


class UpdateAccountRequest(BaseModel):
    external_account_id: str | None = None
    display_name: str | None = None


@router.patch(
    "/accounts/{account_id}",
    response_model=ConnectedAccountResponse,
    summary="Update a connected account (e.g. set the ad account id after OAuth)",
)
def update_account(
    account_id: uuid.UUID,
    body: UpdateAccountRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ConnectedAccount:
    """Patch mutable fields of a connected account, scoped to the tenant.

    The primary use is setting ``external_account_id`` — the platform ad-account
    id (e.g. a Meta ad account) — which the OAuth flow leaves empty and which the
    connector needs before it can fetch data.  For Meta, a leading ``act_``
    prefix is stripped (the connector adds it back).
    """
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            ConnectedAccount.tenant_id == membership.tenant_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hesap bulunamadı.")

    if body.external_account_id is not None:
        ext = body.external_account_id.strip()
        if account.platform == Platform.meta_ads and ext.lower().startswith("act_"):
            ext = ext[4:]
        account.external_account_id = ext
    if body.display_name is not None:
        account.display_name = body.display_name.strip()

    db.commit()
    db.refresh(account)
    return account


class DiscoveredAccount(BaseModel):
    id: str
    name: str = ""
    currency: str = ""


@router.post(
    "/accounts/{account_id}/discover",
    response_model=list[DiscoveredAccount],
    summary="List ad accounts reachable with this connection's stored credentials",
)
def discover_accounts(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    vault: SecretsVault = Depends(_get_vault),
) -> list[DiscoveredAccount]:
    """Use the stored OAuth token to list the ad accounts the user can access.

    Lets the user pick which ad account to attach (set via PATCH) before the
    first sync.  Requires the account to have been connected (token in Vault).

    Errors
    ------
    404 — account not found / tenant mismatch.
    400 — no stored credentials (connect via OAuth first).
    502 — the platform discovery call failed.
    """
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.id == account_id,
            ConnectedAccount.tenant_id == membership.tenant_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hesap bulunamadı.")

    try:
        secrets = vault.get(str(account.id)) or {}
    except Exception:
        secrets = {}
    if not secrets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu hesap için saklı kimlik yok — önce OAuth ile bağlanın.",
        )

    # Inject operator-level (global) platform credentials — same rationale as
    # sync_connected_account: the Vault only holds the tenant's own OAuth
    # refresh_token, never the shared client_id/client_secret/developer_token.
    # Without this, Google Ads discovery always 502s (authenticate() raises on
    # missing developer_token).
    from ayaz.services.sync import inject_operator_credentials, resolve_google_ads_targets

    inject_operator_credentials(account.platform.value, secrets)

    connector_cls = ConnectorRegistry.get(account.platform.value)
    config = ConnectorConfig(
        tenant_id=str(account.tenant_id),
        connected_account_id=str(account.id),
        external_account_id=account.external_account_id,
        platform_key=account.platform.value,
        vault_secret_ref=account.vault_secret_ref or "",
        extra=secrets,
    )
    connector = connector_cls(config=config)
    try:
        connector.authenticate()
        if account.platform.value == "google_ads":
            # Route through the same leaf-resolving logic used by sync so the
            # user picks from real syncable ad accounts (MCC children), not
            # the raw (possibly manager-only) accessible-customers list.
            targets = resolve_google_ads_targets(connector)
            found = [
                {
                    "id": t["customer_id"],
                    "name": t["name"],
                    "currency": t["currency"],
                }
                for t in targets
            ]
        else:
            found = connector.discover()
    except Exception:
        logger.exception("Discover failed: account=%s", account_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reklam hesabı listesi alınamadı. İzinleri kontrol edin.",
        )

    return [
        DiscoveredAccount(
            id=str(a.get("id", "")),
            name=str(a.get("name", "")),
            currency=str(a.get("currency", "")),
        )
        for a in (found or [])
    ]
