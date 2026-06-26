"""Authentication service — password hashing and JWT issue/verify.

Security decisions
------------------
- bcrypt via passlib (work factor 12 — adjust upward as hardware improves).
- HS256 JWT with configurable expiry. For production, consider RS256 with a
  key pair so the public key can be published (JWKS endpoint).
  TODO (Faz 1 security hardening): switch to RS256 + JWKS.
- Token payload carries ``sub`` (user id) + ``tid`` (tenant id) so the API
  layer can enforce tenant context without an extra DB round-trip per request.
- Refresh tokens are NOT implemented in this skeleton.
  TODO (Faz 1): add refresh token rotation + Redis revocation list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from ayaz.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ──────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return the bcrypt hash of ``plain``."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the stored ``hashed`` password."""
    return _pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(
    user_id: str,
    tenant_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed JWT access token.

    Parameters
    ----------
    user_id:
        UUID of the authenticated user (``users.id``).
    tenant_id:
        UUID of the active tenant (``tenants.id``).
    expires_delta:
        Override default expiry (defaults to ``JWT_EXPIRE_MINUTES`` from config).

    Returns
    -------
    str
        Signed JWT string.
    """
    delta = expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tid": tenant_id,  # tenant context — enforced by TenantContext dependency
        "iat": now,
        "exp": now + delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, str]:
    """Decode and validate a JWT, returning its payload.

    Security
    --------
    ``algorithms`` is pinned to a single algorithm so an attacker cannot
    downgrade the token to ``alg=none`` or coerce an RS256/HS256 confusion
    attack.  ``require_exp`` rejects tokens that omit the expiry claim so a
    forged/malformed token without ``exp`` cannot be treated as non-expiring.

    Raises
    ------
    JWTError
        If the token is invalid, expired, missing ``exp``, or tampered with.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require_exp": True},
    )
