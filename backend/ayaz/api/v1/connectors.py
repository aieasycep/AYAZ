"""Connector management endpoints (skeleton).

GET  /connectors/                  — list registered connector platforms
GET  /connectors/accounts          — list tenant's connected accounts
POST /connectors/accounts          — link a new connected account (TODO: OAuth flow)
GET  /connectors/accounts/{id}     — get one connected account
DELETE /connectors/accounts/{id}   — unlink a connected account

TODO (Faz 1 — Integrations): implement real OAuth broker flows.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.connectors import ConnectorRegistry
from ayaz.models.oltp import ConnectedAccount, Membership, Platform, SyncStatus

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
