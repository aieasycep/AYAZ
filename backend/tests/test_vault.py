"""Unit tests for the SecretsVault implementations.

Coverage
--------
- InMemoryVault: round-trip, overwrite, delete, missing-key.
- EncryptedColumnVault: encrypt/decrypt helpers, tamper detection, None handling.
- Key derivation: _derive_fernet_key produces a valid Fernet key.
- EncryptedColumnVault.put/get via a SQLite-backed in-memory DB (no Postgres needed).

All tests are hermetic — no live DB connections, no real vault server.
"""

from __future__ import annotations

import json
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import Session, sessionmaker
from contextlib import contextmanager

from ayaz.models.base import Base
from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus, Tenant
from ayaz.services.vault import (
    InMemoryVault,
    EncryptedColumnVault,
    _derive_fernet_key,
)


# ── SQLite test engine ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng, checkfirst=True)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def db_session(engine):
    """Yield a fresh Session that is always rolled back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def session_factory(engine):
    """Return a sessionmaker that opens sessions on the test engine."""
    factory = sessionmaker(bind=engine, class_=Session)

    @contextmanager
    def _factory():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    return _factory


@pytest.fixture()
def tenant_and_account(db_session):
    """Insert a Tenant + ConnectedAccount into the test DB; return the account."""
    tenant = Tenant(name="Test Tenant", country="TR", base_currency="TRY", kvkk_region="TR")
    db_session.add(tenant)
    db_session.flush()

    account = ConnectedAccount(
        tenant_id=tenant.id,
        platform=Platform.google_ads,
        external_account_id="123456",
        display_name="Test Account",
        vault_secret_ref="",
        sync_status=SyncStatus.idle,
    )
    db_session.add(account)
    db_session.commit()
    return tenant, account


# ── _derive_fernet_key ────────────────────────────────────────────────────────


def test_derive_fernet_key_produces_valid_fernet_key():
    """Derived key should be usable by the Fernet constructor without error."""
    key = _derive_fernet_key("test-vault-key-abc123")
    # Fernet() raises ValueError for invalid keys
    fernet = Fernet(key)
    assert fernet is not None


def test_derive_fernet_key_is_deterministic():
    """Same input always produces the same output."""
    k1 = _derive_fernet_key("my-key")
    k2 = _derive_fernet_key("my-key")
    assert k1 == k2


def test_derive_fernet_key_different_inputs_differ():
    """Different inputs must produce different keys."""
    k1 = _derive_fernet_key("key-a")
    k2 = _derive_fernet_key("key-b")
    assert k1 != k2


# ── InMemoryVault ─────────────────────────────────────────────────────────────


def test_in_memory_vault_round_trip():
    vault = InMemoryVault()
    secret = {"access_token": "tok_abc", "refresh_token": "ref_xyz", "expires_in": 3600}
    vault.put("account-1", secret)
    assert vault.get("account-1") == secret


def test_in_memory_vault_get_missing_returns_none():
    vault = InMemoryVault()
    assert vault.get("does-not-exist") is None


def test_in_memory_vault_overwrite():
    vault = InMemoryVault()
    vault.put("ref", {"token": "old"})
    vault.put("ref", {"token": "new"})
    assert vault.get("ref") == {"token": "new"}


def test_in_memory_vault_delete():
    vault = InMemoryVault()
    vault.put("ref", {"token": "tok"})
    vault.delete("ref")
    assert vault.get("ref") is None


def test_in_memory_vault_delete_nonexistent_is_noop():
    vault = InMemoryVault()
    vault.delete("never-existed")  # should not raise


def test_in_memory_vault_put_returns_copy():
    """Mutating the original dict after put() must not affect stored value."""
    vault = InMemoryVault()
    secret = {"access_token": "tok"}
    vault.put("ref", secret)
    secret["access_token"] = "mutated"
    assert vault.get("ref") == {"access_token": "tok"}


# ── EncryptedColumnVault internals ────────────────────────────────────────────


@pytest.fixture()
def ecv(session_factory):
    """Return an EncryptedColumnVault wired to the test session factory."""
    return EncryptedColumnVault(session_factory=session_factory, vault_key="test-key-123")


def test_ecv_encrypt_decrypt_round_trip(ecv):
    secret = {"access_token": "abc", "refresh_token": "xyz"}
    blob = ecv._encrypt(secret)
    assert blob.startswith("enc:")
    result = ecv._decrypt(blob)
    assert result == secret


def test_ecv_decrypt_empty_string_returns_none(ecv):
    assert ecv._decrypt("") is None


def test_ecv_decrypt_missing_prefix_returns_none(ecv):
    assert ecv._decrypt("not-a-valid-blob") is None


def test_ecv_decrypt_tampered_blob_returns_none(ecv):
    secret = {"key": "value"}
    blob = ecv._encrypt(secret)
    # Corrupt the ciphertext portion
    tampered = blob[:10] + "XXXX" + blob[14:]
    assert ecv._decrypt(tampered) is None


def test_ecv_decrypt_wrong_key_returns_none(session_factory):
    """Blob encrypted with one key cannot be decrypted with a different key."""
    ecv1 = EncryptedColumnVault(session_factory=session_factory, vault_key="key-one")
    ecv2 = EncryptedColumnVault(session_factory=session_factory, vault_key="key-two")
    blob = ecv1._encrypt({"secret": "data"})
    assert ecv2._decrypt(blob) is None


# ── EncryptedColumnVault.put / get against the DB ─────────────────────────────


def test_ecv_put_and_get_round_trip(ecv, tenant_and_account):
    _tenant, account = tenant_and_account
    ref = str(account.id)
    secret = {"access_token": "live_token", "refresh_token": "refresh_abc"}

    ecv.put(ref, secret)
    result = ecv.get(ref)

    assert result == secret


def test_ecv_get_nonexistent_account_returns_none(ecv):
    assert ecv.get(str(uuid.uuid4())) is None


def test_ecv_get_invalid_uuid_returns_none(ecv):
    assert ecv.get("not-a-uuid") is None


def test_ecv_put_nonexistent_account_raises(ecv):
    with pytest.raises(KeyError, match="no ConnectedAccount"):
        ecv.put(str(uuid.uuid4()), {"token": "x"})


def test_ecv_delete_clears_vault_ref(ecv, tenant_and_account):
    _tenant, account = tenant_and_account
    ref = str(account.id)

    ecv.put(ref, {"token": "to_be_deleted"})
    assert ecv.get(ref) is not None

    ecv.delete(ref)
    assert ecv.get(ref) is None


def test_ecv_delete_nonexistent_is_noop(ecv):
    ecv.delete(str(uuid.uuid4()))  # should not raise


def test_ecv_overwrite_secret(ecv, tenant_and_account):
    _tenant, account = tenant_and_account
    ref = str(account.id)

    ecv.put(ref, {"token": "first"})
    ecv.put(ref, {"token": "second"})
    assert ecv.get(ref) == {"token": "second"}


def test_ecv_get_empty_vault_ref_returns_none(ecv, tenant_and_account):
    """An account whose vault_secret_ref is empty should return None."""
    _tenant, account = tenant_and_account
    # account.vault_secret_ref starts as "" — get() should return None without error
    assert ecv.get(str(account.id)) is None
