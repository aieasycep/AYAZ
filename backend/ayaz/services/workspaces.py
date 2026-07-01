"""Workspace service — M8 Agency / Multi-Workspace + White-label.

Responsibilities
----------------
* ``list_workspaces``   — all tenants the user belongs to, with role and brand.
* ``create_workspace``  — create a new Tenant + owner Membership for the user.
* ``switch_workspace``  — verify membership, issue a new JWT scoped to target tenant.
* ``update_branding``   — set white-label brand fields on a Tenant.
* ``list_members``      — return all Membership rows for a tenant.
* ``invite_member``     — create a WorkspaceInvitation (email notification stubbed).
* ``accept_invitation`` — validate the token, create the Membership, mark accepted.
* ``remove_member``     — delete a Membership; guards the last-owner rule.
* ``change_role``       — change a member's role; guards the last-owner rule.

Tenant isolation
----------------
Every query that touches Membership or WorkspaceInvitation rows filters explicitly
on ``tenant_id`` — enforcing isolation until Postgres RLS policies are activated.

Security notes
--------------
* ``switch_workspace`` returns a fresh JWT; the caller must store it and use it for
  subsequent requests.  Old tokens scoped to the previous tenant remain valid until
  they expire (short-lived; TODO Faz 1: add Redis revocation list).
* Invitation tokens are 32-byte URL-safe random strings — not guessable.
* ``invited_by`` stores the user_id of the inviter for audit purposes.
* Stubbed email: ``_send_invitation_email`` logs to stdout only; wire a real mail
  service here in Faz 2 (SendGrid / Mailjet).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.oltp import (
    Membership,
    MembershipRole,
    Tenant,
    User,
    WorkspaceInvitation,
)
from ayaz.services.auth import create_access_token


# ── Internal helpers ──────────────────────────────────────────────────────────


def _role_from_str(role_str: str) -> MembershipRole:
    """Convert a string role to MembershipRole; raise 400 on invalid value."""
    try:
        return MembershipRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz rol: {role_str!r}. Geçerli değerler: admin, member.",
        )


def _count_owners(db: Session, tenant_id: uuid.UUID) -> int:
    """Return the number of owner-role memberships for the given tenant."""
    return db.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == MembershipRole.owner,
        )
        .with_only_columns(
            # We count via len of all() to keep SQLite compat simple; use func.count
            # for large datasets in production.
        )
    ) or 0  # type: ignore[arg-type]


def _owner_count(db: Session, tenant_id: uuid.UUID) -> int:
    """Return the count of owners in the tenant (SQLite-compatible)."""
    rows = db.scalars(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.role == MembershipRole.owner,
        )
    ).all()
    return len(rows)


def _get_membership_or_404(
    db: Session,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> Membership:
    """Fetch a Membership scoped to tenant_id; raise 404 if not found."""
    m = db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.tenant_id == tenant_id,
        )
    )
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Üyelik bulunamadı.",
        )
    return m


def _send_invitation_email(
    email: str,
    tenant_name: str,
    role: str,
    token: str,
) -> None:
    """Stub: log invitation details.  Wire SendGrid/Mailjet in Faz 2."""
    # TODO (Faz 2): send a real email with an accept link.
    print(
        f"[STUB] Invitation email → {email} | workspace={tenant_name!r}"
        f" | role={role} | token={token[:8]}…"
    )


# ── Workspace CRUD ────────────────────────────────────────────────────────────


def list_workspaces(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return all tenants the user is a member of, with their role and brand fields.

    Returns a list of dicts; each entry has:
        id, name, role, brand_name, logo_url, primary_color.
    """
    memberships = db.scalars(
        select(Membership)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at)
    ).all()

    result = []
    for m in memberships:
        tenant: Tenant = m.tenant
        result.append(
            {
                "id": tenant.id,
                "name": tenant.name,
                "role": m.role.value,
                "brand_name": tenant.brand_name,
                "logo_url": tenant.logo_url,
                "primary_color": tenant.primary_color,
            }
        )
    return result


def create_workspace(
    db: Session,
    user_id: uuid.UUID,
    name: str,
    country: str = "TR",
    base_currency: str = "TRY",
) -> Tenant:
    """Create a new Tenant and an owner Membership for the user.

    Mirrors the tenant-creation logic in ``api/v1/auth.py::signup``.

    Soft note: multi-workspace creation is intended for the agency plan but is
    not hard-blocked here — billing entitlement checks are the caller's concern.
    """
    tenant = Tenant(
        name=name,
        country=country,
        base_currency=base_currency,
    )
    db.add(tenant)
    db.flush()  # get tenant.id before FK reference

    membership = Membership(
        user_id=user_id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(membership)
    db.commit()
    db.refresh(tenant)
    return tenant


def switch_workspace(
    db: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> str:
    """Verify the user's membership in tenant_id and issue a new JWT for it.

    Returns the signed JWT string scoped to the target tenant.
    Raises HTTP 403 if the user is not a member of the target tenant.
    """
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu çalışma alanına erişim yetkiniz yok.",
        )

    return create_access_token(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
    )


def get_tenant_or_404(db: Session, tenant_id: uuid.UUID) -> Tenant:
    """Fetch a Tenant by id; raise 404 if not found."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Çalışma alanı bulunamadı.",
        )
    return tenant


def update_branding(
    db: Session,
    tenant_id: uuid.UUID,
    brand_name: str | None = None,
    logo_url: str | None = None,
    primary_color: str | None = None,
) -> Tenant:
    """Update the white-label branding fields for the given tenant.

    Only fields that are explicitly provided (not None sentinel) are updated.
    Pass an empty string to clear a field.
    """
    tenant = get_tenant_or_404(db, tenant_id)
    if brand_name is not None:
        tenant.brand_name = brand_name or None  # empty string → NULL
    if logo_url is not None:
        tenant.logo_url = logo_url or None
    if primary_color is not None:
        tenant.primary_color = primary_color or None
    db.commit()
    db.refresh(tenant)
    return tenant


# ── Member management ─────────────────────────────────────────────────────────


def list_members(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return all members of the tenant with their user info and role."""
    memberships = db.scalars(
        select(Membership)
        .where(Membership.tenant_id == tenant_id)
        .order_by(Membership.created_at)
    ).all()

    result = []
    for m in memberships:
        user: User = m.user
        result.append(
            {
                "membership_id": m.id,
                "user_id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": m.role.value,
                "joined_at": m.created_at.isoformat() if m.created_at else None,
            }
        )
    return result


def invite_member(
    db: Session,
    tenant_id: uuid.UUID,
    email: str,
    role: str,
    invited_by: uuid.UUID,
) -> WorkspaceInvitation:
    """Create a WorkspaceInvitation for the email address.

    If a pending invitation already exists for this email+tenant, it is revoked
    and a new one is created (re-invite flow).

    The role must be ``admin`` or ``member`` — owners cannot be invited directly;
    they must be promoted after accepting.
    """
    if role not in ("admin", "member"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Davet rolü 'admin' veya 'member' olabilir.",
        )

    # Check whether the email is already a member of this tenant
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user:
        existing_membership = db.scalar(
            select(Membership).where(
                Membership.user_id == existing_user.id,
                Membership.tenant_id == tenant_id,
            )
        )
        if existing_membership:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu e-posta adresi zaten bu çalışma alanının üyesi.",
            )

    # Revoke any pending invitation for the same email in this tenant
    pending = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.email == email,
            WorkspaceInvitation.status == "pending",
        )
    )
    if pending is not None:
        pending.status = "revoked"
        db.flush()

    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        tenant_id=tenant_id,
        email=email,
        role=role,
        token=token,
        status="pending",
        invited_by=invited_by,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    # Stub email notification
    tenant = get_tenant_or_404(db, tenant_id)
    _send_invitation_email(email, tenant.name, role, token)

    return invitation


def accept_invitation(
    db: Session,
    token: str,
    user_id: uuid.UUID,
) -> Membership:
    """Accept a workspace invitation by token.

    Creates a Membership with the invitation's role, marks the invitation as
    accepted, and returns the new Membership.

    Raises HTTP 404 if the token is not found or the invitation is not pending.
    Raises HTTP 409 if the user is already a member of that workspace.
    """
    invitation = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.token == token,
            WorkspaceInvitation.status == "pending",
        )
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geçerli bir davet bulunamadı.",
        )

    # Guard: already a member?
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == invitation.tenant_id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu çalışma alanının zaten üyesisiniz.",
        )

    role = _role_from_str(invitation.role)
    membership = Membership(
        user_id=user_id,
        tenant_id=invitation.tenant_id,
        role=role,
    )
    db.add(membership)

    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc).isoformat()

    db.commit()
    db.refresh(membership)
    return membership


def remove_member(
    db: Session,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> None:
    """Delete a Membership from the tenant.

    Guards the last-owner rule: if the membership being removed is an owner and
    it is the only owner, the removal is rejected with HTTP 422.
    """
    m = _get_membership_or_404(db, tenant_id, membership_id)

    if m.role == MembershipRole.owner and _owner_count(db, tenant_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Çalışma alanının son sahibi kaldırılamaz. "
                "Önce başka bir üyeyi sahip yapın."
            ),
        )

    db.delete(m)
    db.commit()


def change_role(
    db: Session,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    role: str,
) -> Membership:
    """Change a member's role within the tenant.

    Guards the last-owner rule: cannot demote the last owner away from 'owner'.
    """
    m = _get_membership_or_404(db, tenant_id, membership_id)
    new_role = _role_from_str(role)

    # Guard: demoting the last owner?
    if (
        m.role == MembershipRole.owner
        and new_role != MembershipRole.owner
        and _owner_count(db, tenant_id) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Çalışma alanının son sahibinin rolü değiştirilemez. "
                "Önce başka bir üyeyi sahip yapın."
            ),
        )

    m.role = new_role
    db.commit()
    db.refresh(m)
    return m
