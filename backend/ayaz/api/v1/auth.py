"""Auth endpoints: signup, login, me, logout.

POST /auth/signup  — create user + tenant + owner membership, return JWT
POST /auth/login   — email/password → JWT
GET  /auth/me      — return current user profile
POST /auth/logout  — revoke the current JWT (insert jti into deny-list)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_user, get_db
from ayaz.config import settings
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.security.rate_limit import rate_limit
from ayaz.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    revoke_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=False)


# ── Request / response schemas ────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    org_name: str  # name of the first tenant (org) created for this user

    @field_validator("password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalıdır.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str

    model_config = {"from_attributes": True}


class LogoutResponse(BaseModel):
    detail: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and organisation",
)
def signup(
    request: Request,
    body: SignupRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "auth:signup",
            limit=settings.rate_limit_signup_limit,
            window_seconds=settings.rate_limit_signup_window,
        )
    ),
) -> TokenResponse:
    """Create a new user, a new tenant (org), and an owner membership.

    Returns a JWT scoped to the new tenant so the client can proceed
    immediately without a separate login call.

    Rate limited: 5 requests/minute/IP (configurable via settings).
    """
    # Check for duplicate email
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu e-posta adresi zaten kullanımda.",
        )

    # Create user
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)

    # Create tenant (org)
    tenant = Tenant(name=body.org_name)
    db.add(tenant)

    # Flush to get IDs before creating the membership FK
    db.flush()

    # Create owner membership
    membership = Membership(
        user_id=user.id,
        tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db.add(membership)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kayıt sırasında bir çakışma oluştu. Lütfen tekrar deneyin.",
        )

    token = create_access_token(
        user_id=str(user.id),
        tenant_id=str(tenant.id),
    )
    return TokenResponse(access_token=token)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Obtain a JWT access token",
)
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "auth:login",
            limit=settings.rate_limit_login_limit,
            window_seconds=settings.rate_limit_login_window,
        )
    ),
) -> TokenResponse:
    """Authenticate with email + password, return a JWT.

    The JWT payload carries both ``sub`` (user_id) and ``tid`` (tenant_id).
    If the user belongs to multiple tenants, the first membership (by creation
    order) is used.  TODO (Faz 1): let the client specify the target tenant at
    login, or add a ``/auth/switch-tenant`` endpoint.

    Rate limited: 10 requests/minute/IP (configurable via settings).
    """
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı.",
        )

    # Pick the first membership (owner preferred, then admin, then member)
    membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
        .limit(1)
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız herhangi bir organizasyona bağlı değil.",
        )

    token = create_access_token(
        user_id=str(user.id),
        tenant_id=str(membership.tenant_id),
    )
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the current authenticated user",
)
def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the current user's profile.

    Requires a valid JWT in the ``Authorization: Bearer <token>`` header.
    """
    return current_user


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the current JWT (logout)",
)
def logout(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogoutResponse:
    """Revoke the current access token by inserting its ``jti`` into the deny-list.

    After this call the token is invalid even if it has not yet expired.
    The client should discard the token from local storage.

    Subsequent requests with the same token receive HTTP 401.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulama gerekli.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        # Token is already invalid — treat as successful logout
        return LogoutResponse(detail="Çıkış yapıldı.")

    revoke_token(db, payload)
    return LogoutResponse(detail="Çıkış yapıldı.")
