"""Authentication service — password hashing and JWT issue/verify.

Security decisions
------------------
- bcrypt via passlib (work factor 12 — adjust upward as hardware improves).
- HS256 JWT with configurable expiry. For production, consider RS256 with a
  key pair so the public key can be published (JWKS endpoint).
  TODO (Faz 1 security hardening): switch to RS256 + JWKS.
- Token payload carries ``sub`` (user id) + ``tid`` (tenant id) so the API
  layer can enforce tenant context without an extra DB round-trip per request.
- Every token carries a ``jti`` (JWT ID, uuid4) so individual tokens can be
  revoked by inserting the jti into the ``revoked_tokens`` deny-list.
  Call ``revoke_token()`` from the logout endpoint to invalidate the token.
- Refresh tokens are NOT implemented in this skeleton.
  TODO (Faz 1): add refresh token rotation + Redis revocation list.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

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
        Signed JWT string.  The payload includes a ``jti`` (JWT ID) claim — a
        uuid4 string — that uniquely identifies this token for revocation.
    """
    delta = expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tid": tenant_id,  # tenant context — enforced by TenantContext dependency
        "jti": str(uuid.uuid4()),  # unique token id — used for revocation
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

    Note: this function does NOT check the revocation deny-list.  Revocation
    is enforced at the FastAPI dependency layer (``get_current_user``) because
    it requires a DB session.  This keeps the pure-crypto layer free of DB
    concerns and allows callers that do not have a DB session to call
    ``decode_access_token`` for basic structural validation.

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


# ── JWT revocation ────────────────────────────────────────────────────────────


def revoke_token(
    db: Session,
    payload: dict[str, str],
) -> None:
    """Add the token's ``jti`` to the deny-list (revoke it).

    This is the service-layer call made by ``POST /auth/logout``.  After this
    call, any subsequent request bearing the same token is rejected with
    HTTP 401 by ``get_current_user``.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    payload:
        The decoded JWT payload dict (as returned by ``decode_access_token``).
        Must contain a ``jti`` claim.
    """
    # Import here to avoid circular imports (models → config, services → models)
    from ayaz.models.auth import RevokedToken

    jti: str | None = payload.get("jti")
    if not jti:
        # Token predates jti support — nothing to revoke; not an error
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    # Derive expires_at from the exp claim (Unix timestamp) so the cleanup job
    # can prune this row once the token would have naturally expired anyway.
    expires_at: str | None = None
    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_dt = datetime.fromtimestamp(float(exp), tz=timezone.utc)
            expires_at = exp_dt.isoformat()
        except (TypeError, ValueError, OSError):
            pass

    # tenant_id may not parse if the token is malformed; store null in that case
    tenant_id: uuid.UUID | None = None
    tid_raw = payload.get("tid")
    if tid_raw:
        try:
            tenant_id = uuid.UUID(str(tid_raw))
        except ValueError:
            pass

    revoked = RevokedToken(
        jti=jti,
        tenant_id=tenant_id,
        revoked_at=now_iso,
        expires_at=expires_at,
    )
    # Merge so a duplicate logout is silently ignored (PK conflict → no-op)
    db.merge(revoked)
    db.commit()


def is_token_revoked(db: Session, jti: str) -> bool:
    """Return True if the given ``jti`` is in the revocation deny-list.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    jti:
        The ``jti`` claim from the decoded JWT payload.
    """
    from ayaz.models.auth import RevokedToken

    row = db.get(RevokedToken, jti)
    return row is not None


def cleanup_revoked_tokens(db: Session) -> int:
    """Delete deny-list rows whose token has already naturally expired.

    Safe to call from a background job (e.g. nightly Celery beat task or a
    startup hook).  Only removes rows where ``expires_at`` is in the past,
    so active revocations are never removed prematurely.

    Returns
    -------
    int
        Number of rows deleted.
    """
    from ayaz.models.auth import RevokedToken

    now_iso = datetime.now(timezone.utc).isoformat()
    # Select rows where expires_at is set and is earlier than now
    stale = db.scalars(
        select(RevokedToken).where(
            RevokedToken.expires_at.is_not(None),
            RevokedToken.expires_at < now_iso,
        )
    ).all()

    count = len(stale)
    for row in stale:
        db.delete(row)
    db.commit()
    return count
