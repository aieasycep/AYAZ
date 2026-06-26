"""FastAPI dependency injection — auth, DB session, tenant context.

Every endpoint that needs a DB session should declare::

    db: Session = Depends(get_db)

Every endpoint that needs the current user should declare::

    current_user: User = Depends(get_current_user)

Tenant-scoped endpoints should additionally declare::

    membership: Membership = Depends(get_current_membership)

which resolves the active tenant from the JWT and validates the user's role.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.database import get_db
from ayaz.models.oltp import Membership, User
from ayaz.services.auth import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the JWT, return the matching User row.

    Raises HTTP 401 if the token is missing, invalid, or the user no longer
    exists.
    """
    _unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kimlik doğrulama gerekli.",  # "Authentication required."
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise _unauthorized

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise _unauthorized

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise _unauthorized

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise _unauthorized

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized

    return user


def get_current_membership(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Membership:
    """Resolve the active tenant from the JWT and return the Membership row.

    The ``tid`` claim in the JWT names the tenant the user is currently acting
    on behalf of.  This dependency validates that the membership actually exists
    (guards against a forged ``tid``).

    TODO (Faz 1 — RLS): After obtaining the membership, set Postgres
    ``current_setting('app.tenant_id')`` on the session so RLS policies fire::

        db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(membership.tenant_id)},
        )

    Until the RLS policies are deployed every query MUST explicitly filter
    ``WHERE tenant_id = :tenant_id``.  See individual service functions for
    the explicit filter pattern.
    """
    _forbidden = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Bu kiracıya erişim yetkiniz yok.",  # "No access to this tenant."
    )

    # Extract tenant_id from JWT payload
    if not credentials:
        raise _forbidden
    try:
        payload = decode_access_token(credentials.credentials)
        tenant_id = uuid.UUID(payload["tid"])
    except (JWTError, KeyError, ValueError):
        raise _forbidden

    # Verify membership exists
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == current_user.id,
            Membership.tenant_id == tenant_id,
        )
    )
    if membership is None:
        raise _forbidden

    return membership
