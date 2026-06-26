"""Unit tests for the auth service layer (no DB required)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from jose import JWTError

from ayaz.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────


def test_hash_password_produces_bcrypt_string() -> None:
    h = hash_password("hunter2")
    assert h.startswith("$2b$")


def test_verify_password_correct() -> None:
    h = hash_password("correct-horse")
    assert verify_password("correct-horse", h) is True


def test_verify_password_wrong() -> None:
    h = hash_password("correct-horse")
    assert verify_password("wrong-password", h) is False


def test_hash_is_not_plaintext() -> None:
    plain = "my-secret-password"
    h = hash_password(plain)
    assert h != plain


# ── JWT ───────────────────────────────────────────────────────────────────────


def test_create_and_decode_token() -> None:
    token = create_access_token(user_id="user-1", tenant_id="tenant-1")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-1"
    assert payload["tid"] == "tenant-1"


def test_expired_token_raises() -> None:
    token = create_access_token(
        user_id="user-1",
        tenant_id="tenant-1",
        expires_delta=timedelta(seconds=-1),  # already expired
    )
    with pytest.raises(JWTError):
        decode_access_token(token)


def test_tampered_token_raises() -> None:
    token = create_access_token(user_id="user-1", tenant_id="tenant-1")
    # Corrupt the signature
    tampered = token[:-4] + "xxxx"
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_token_contains_required_claims() -> None:
    token = create_access_token(user_id="abc", tenant_id="xyz")
    payload = decode_access_token(token)
    for claim in ("sub", "tid", "iat", "exp"):
        assert claim in payload, f"Missing claim: {claim}"
