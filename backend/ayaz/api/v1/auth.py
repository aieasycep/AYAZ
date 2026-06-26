"""Auth endpoints: signup, login, me, logout, profile update, change password, preferences.

POST  /auth/signup           — create user + tenant + owner membership, return JWT
POST  /auth/login            — email/password → JWT
GET   /auth/me               — return current user profile
PATCH /auth/me               — update profile (full_name / email)
POST  /auth/logout           — revoke the current JWT (insert jti into deny-list)
POST  /auth/change-password  — change the current user's password
GET   /auth/preferences      — return current user preferences
PATCH /auth/preferences      — update current user preferences
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
    created_at: str | None = None  # ISO-8601; optional for backward compat

    model_config = {"from_attributes": False}

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        """Build a UserResponse from a User ORM object."""
        created_at_val = None
        if user.created_at is not None:
            created_at_val = user.created_at.isoformat()
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=created_at_val,
        )


class LogoutResponse(BaseModel):
    detail: str


class UpdateProfileRequest(BaseModel):
    """Request body for PATCH /auth/me."""

    full_name: str | None = None
    email: EmailStr | None = None

    def has_any_field(self) -> bool:
        return self.full_name is not None or self.email is not None


class ChangePasswordRequest(BaseModel):
    """Request body for POST /auth/change-password."""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalıdır.")
        return v


class MessageResponse(BaseModel):
    """Generic single-detail message response."""

    detail: str


class PreferencesResponse(BaseModel):
    """Response for GET/PATCH /auth/preferences."""

    locale: str
    timezone: str
    email_alerts: bool
    email_briefing: bool

    model_config = {"from_attributes": False}

    @classmethod
    def from_user(cls, user: "User") -> "PreferencesResponse":
        return cls(
            locale=user.locale,
            timezone=user.timezone,
            email_alerts=user.email_alerts,
            email_briefing=user.email_briefing,
        )


class UpdatePreferencesRequest(BaseModel):
    """Request body for PATCH /auth/preferences (all fields optional)."""

    locale: str | None = None
    timezone: str | None = None
    email_alerts: bool | None = None
    email_briefing: bool | None = None

    VALID_LOCALES: set[str] = {"tr", "en"}

    @field_validator("locale")
    @classmethod
    def _validate_locale(cls, v: str | None) -> str | None:
        if v is not None and v not in {"tr", "en"}:
            raise ValueError("Geçersiz dil seçeneği. 'tr' veya 'en' olmalıdır.")
        return v


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
) -> UserResponse:
    """Return the current user's profile.

    Requires a valid JWT in the ``Authorization: Bearer <token>`` header.
    """
    return UserResponse.from_user(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the current user's profile",
)
def update_profile(
    body: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> UserResponse:
    """Update the authenticated user's ``full_name`` and/or ``email``.

    At least one field must be provided — an empty body returns HTTP 400.
    If the requested ``email`` is already used by another account, HTTP 409 is
    raised with a Turkish detail message.

    Returns the updated user profile.

    Requires a valid JWT in the ``Authorization: Bearer <token>`` header.
    """
    if not body.has_any_field():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="En az bir alan (full_name veya email) sağlanmalıdır.",
        )

    if body.email is not None and body.email != current_user.email:
        # Check uniqueness against all OTHER users
        conflict = db.scalar(
            select(User).where(
                User.email == body.email,
                User.id != current_user.id,
            )
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu e-posta adresi zaten kullanımda.",
            )
        current_user.email = body.email

    if body.full_name is not None:
        current_user.full_name = body.full_name

    try:
        db.commit()
        db.refresh(current_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu e-posta adresi zaten kullanımda.",
        )

    return UserResponse.from_user(current_user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change the current user's password",
)
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "auth:change-password",
            limit=settings.rate_limit_change_password_limit,
            window_seconds=settings.rate_limit_change_password_window,
        )
    ),
) -> MessageResponse:
    """Change the authenticated user's password.

    Verifies the ``current_password`` against the stored bcrypt hash, rejects
    trivial same-password changes, then persists the new bcrypt hash.

    Plain-text passwords are NEVER logged.

    Rate limited: 5 requests/minute/IP (configurable via settings).
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mevcut şifre hatalı.",
        )

    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yeni şifre mevcut şifre ile aynı olamaz.",
        )

    current_user.hashed_password = hash_password(body.new_password)
    db.commit()

    return MessageResponse(detail="Şifre güncellendi.")


@router.get(
    "/preferences",
    response_model=PreferencesResponse,
    summary="Return the current user's preferences",
)
def get_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
) -> PreferencesResponse:
    """Return the authenticated user's notification and locale preferences.

    Requires a valid JWT in the ``Authorization: Bearer <token>`` header.
    """
    return PreferencesResponse.from_user(current_user)


@router.patch(
    "/preferences",
    response_model=PreferencesResponse,
    summary="Update the current user's preferences",
)
def update_preferences(
    body: UpdatePreferencesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> PreferencesResponse:
    """Partially update the authenticated user's preferences.

    All fields are optional; only provided fields are changed.
    Validates ``locale`` against the allowed values ``'tr'`` and ``'en'``
    (returns HTTP 400 on invalid input — Pydantic raises HTTP 422 for
    non-string values).

    Requires a valid JWT in the ``Authorization: Bearer <token>`` header.
    """
    if body.locale is not None:
        current_user.locale = body.locale
    if body.timezone is not None:
        current_user.timezone = body.timezone
    if body.email_alerts is not None:
        current_user.email_alerts = body.email_alerts
    if body.email_briefing is not None:
        current_user.email_briefing = body.email_briefing

    db.commit()
    db.refresh(current_user)

    return PreferencesResponse.from_user(current_user)


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
