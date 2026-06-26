"""Workspace API — M8 Agency / Multi-Workspace + White-label.

Endpoints
---------
GET    /workspaces                           — list workspaces the user belongs to
POST   /workspaces                           — create a new workspace
POST   /workspaces/switch                    — switch active tenant, returns new JWT
GET    /workspaces/current                   — branding of the active workspace
PATCH  /workspaces/current                   — update branding of the active workspace
GET    /workspaces/members                   — list members of the active workspace
POST   /workspaces/invitations               — invite a new member by email
POST   /workspaces/invitations/accept        — accept an invitation by token
DELETE /workspaces/members/{membership_id}   — remove a member
PATCH  /workspaces/members/{membership_id}   — change a member's role

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant-scoped endpoints resolve
the active tenant from the JWT ``tid`` claim via ``get_current_membership``.

Role enforcement
----------------
* GET /workspaces and POST /workspaces/switch: any authenticated user.
* POST /workspaces: any authenticated user (soft billing gate in service).
* GET /workspaces/current: any member (owner/admin/member).
* PATCH /workspaces/current: owner or admin only.
* GET /workspaces/members: any member.
* POST /workspaces/invitations: owner or admin only.
* POST /workspaces/invitations/accept: any authenticated user (just needs a token).
* DELETE /workspaces/members/{id}: owner or admin only.
* PATCH  /workspaces/members/{id}: owner or admin only.

Tenant isolation
----------------
All service calls pass the tenant_id from the JWT membership, never from the
request body (except ``POST /workspaces/switch`` which takes an explicit target).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_current_user, get_db
from ayaz.models.oltp import Membership, MembershipRole, User
from ayaz.services.workspaces import (
    accept_invitation,
    change_role,
    create_workspace,
    invite_member,
    list_members,
    list_workspaces,
    remove_member,
    switch_workspace,
    update_branding,
    get_tenant_or_404,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_ADMIN_ROLES = {MembershipRole.owner, MembershipRole.admin}


def _require_admin(membership: Membership) -> None:
    """Raise HTTP 403 if the membership role is not owner or admin."""
    if membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetici yetkisi gereklidir.",
        )


# ── Request / response schemas ────────────────────────────────────────────────


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    brand_name: str | None
    logo_url: str | None
    primary_color: str | None

    model_config = {"from_attributes": True}


class CreateWorkspaceRequest(BaseModel):
    name: str
    country: str = "TR"
    base_currency: str = "TRY"

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Çalışma alanı adı boş olamaz.")
        return v.strip()


class SwitchWorkspaceRequest(BaseModel):
    tenant_id: uuid.UUID


class SwitchWorkspaceResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID


class BrandingResponse(BaseModel):
    tenant_id: uuid.UUID
    name: str
    brand_name: str | None
    logo_url: str | None
    primary_color: str | None

    model_config = {"from_attributes": True}


class UpdateBrandingRequest(BaseModel):
    brand_name: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None


class MemberResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    joined_at: str | None

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ("admin", "member"):
            raise ValueError("Rol 'admin' veya 'member' olmalıdır.")
        return v


class InvitationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str
    status: str
    token: str  # returned to caller so tests can use it directly; hide in prod UI

    model_config = {"from_attributes": True}


class AcceptInvitationRequest(BaseModel):
    token: str


class MembershipResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str

    model_config = {"from_attributes": True}


class ChangeRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ("owner", "admin", "member"):
            raise ValueError("Rol 'owner', 'admin' veya 'member' olmalıdır.")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[WorkspaceResponse],
    summary="List all workspaces the current user belongs to",
)
def get_my_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return every tenant the authenticated user is a member of, with their role
    and white-label brand fields."""
    return list_workspaces(db, current_user.id)


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace",
)
def create_new_workspace(
    body: CreateWorkspaceRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new Tenant and owner Membership for the authenticated user.

    The calling user becomes the owner of the new workspace.  Intended for
    agency-plan accounts managing multiple client workspaces, but not hard-blocked
    by plan — the billing layer handles entitlement enforcement.
    """
    tenant = create_workspace(
        db,
        user_id=current_user.id,
        name=body.name,
        country=body.country,
        base_currency=body.base_currency,
    )
    return {
        "id": tenant.id,
        "name": tenant.name,
        "role": "owner",
        "brand_name": tenant.brand_name,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.post(
    "/switch",
    response_model=SwitchWorkspaceResponse,
    summary="Switch active workspace and receive a new JWT",
)
def switch_active_workspace(
    body: SwitchWorkspaceRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> SwitchWorkspaceResponse:
    """Verify the user's membership in the target tenant and return a new JWT.

    The returned ``access_token`` is scoped to ``tenant_id``; the client must
    store it and send it as ``Authorization: Bearer <token>`` on all subsequent
    requests that should run in the context of this workspace.
    """
    token = switch_workspace(db, current_user.id, body.tenant_id)
    return SwitchWorkspaceResponse(
        access_token=token,
        tenant_id=body.tenant_id,
    )


@router.get(
    "/current",
    response_model=BrandingResponse,
    summary="Get branding of the active workspace",
)
def get_current_workspace(
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the white-label branding fields for the JWT-scoped tenant."""
    tenant = get_tenant_or_404(db, membership.tenant_id)
    return {
        "tenant_id": tenant.id,
        "name": tenant.name,
        "brand_name": tenant.brand_name,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.patch(
    "/current",
    response_model=BrandingResponse,
    summary="Update branding of the active workspace",
)
def patch_current_workspace(
    body: UpdateBrandingRequest,
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update the white-label brand_name, logo_url, and/or primary_color.

    Only owner and admin roles may update branding.
    Only fields included in the request body are modified.
    """
    _require_admin(membership)
    tenant = update_branding(
        db,
        tenant_id=membership.tenant_id,
        brand_name=body.brand_name,
        logo_url=body.logo_url,
        primary_color=body.primary_color,
    )
    return {
        "tenant_id": tenant.id,
        "name": tenant.name,
        "brand_name": tenant.brand_name,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.get(
    "/members",
    response_model=list[MemberResponse],
    summary="List all members of the active workspace",
)
def get_workspace_members(
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return all current members of the JWT-scoped tenant."""
    return list_members(db, membership.tenant_id)


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new member to the active workspace",
)
def create_invitation(
    body: InviteMemberRequest,
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a WorkspaceInvitation for the given email address.

    Only owner and admin roles may invite.
    The token in the response is the accept link payload; in production this
    would only be included in an email, not returned to the caller.
    """
    _require_admin(membership)
    invitation = invite_member(
        db,
        tenant_id=membership.tenant_id,
        email=str(body.email),
        role=body.role,
        invited_by=membership.user_id,
    )
    return {
        "id": invitation.id,
        "tenant_id": invitation.tenant_id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "token": invitation.token,
    }


@router.post(
    "/invitations/accept",
    response_model=MembershipResponse,
    summary="Accept a workspace invitation",
)
def accept_workspace_invitation(
    body: AcceptInvitationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Accept an invitation token and join the workspace.

    The accept endpoint requires a valid JWT (the invitee must be a registered
    user) but does NOT require an existing tenant membership — the invitee may
    not yet belong to the tenant.
    """
    new_membership = accept_invitation(db, body.token, current_user.id)
    return {
        "membership_id": new_membership.id,
        "user_id": new_membership.user_id,
        "tenant_id": new_membership.tenant_id,
        "role": new_membership.role.value,
    }


@router.delete(
    "/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the active workspace",
)
def delete_member(
    membership_id: uuid.UUID,
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> None:
    """Remove a member from the JWT-scoped workspace.

    Only owner and admin roles may remove members.
    The last owner of a workspace cannot be removed.
    """
    _require_admin(membership)
    remove_member(db, membership.tenant_id, membership_id)


@router.patch(
    "/members/{membership_id}",
    response_model=MembershipResponse,
    summary="Change a member's role in the active workspace",
)
def update_member_role(
    membership_id: uuid.UUID,
    body: ChangeRoleRequest,
    membership: Annotated[Membership, Depends(get_current_membership)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Change the role of a member in the JWT-scoped workspace.

    Only owner and admin roles may change roles.
    The last owner cannot be demoted.
    """
    _require_admin(membership)
    updated = change_role(db, membership.tenant_id, membership_id, body.role)
    return {
        "membership_id": updated.id,
        "user_id": updated.user_id,
        "tenant_id": updated.tenant_id,
        "role": updated.role.value,
    }
