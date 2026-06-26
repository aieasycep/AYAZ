"""Secret Vault abstraction layer.

Design
------
``SecretsVault`` is the interface every caller uses.  Two implementations ship:

1. ``EncryptedColumnVault`` (default, dev/staging):
   Serialises the secret dict to JSON, encrypts with Fernet (AES-128-CBC +
   HMAC-SHA256 envelope), and stores the resulting ciphertext blob in
   ``connected_accounts.vault_secret_ref`` keyed by the account UUID.
   The column already exists (Text, nullable=False, default="") — **no
   migration required**.

2. (Production) A ``HashiCorpVault`` subclass wires to the real KV v2 API
   using ``vault_addr`` / ``vault_token`` from settings.  Swap the dependency
   injection in ``get_vault()`` and nothing else changes.

Key derivation
--------------
``settings.vault_key`` is a URL-safe base64 string (32+ bytes of randomness).
We run it through PBKDF2-HMAC-SHA256 with a fixed salt to produce exactly 32
bytes, then base64-encode those bytes to satisfy Fernet's 32-byte-url-safe-b64
requirement.  Using PBKDF2 means a shorter/non-padded ``vault_key`` still
produces a valid Fernet key, and the derivation is deterministic so the same
key always decrypts the same ciphertext.

Production swap
---------------
Set the ``VAULT_KEY`` env-var to a cryptographically random 32-byte value
(generate with ``python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"``).
Never reuse the dev default in production.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.config import settings
from ayaz.models.oltp import ConnectedAccount


# ── Key derivation ────────────────────────────────────────────────────────────


def _derive_fernet_key(raw_key: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from the configured vault_key.

    Uses PBKDF2-HMAC-SHA256 with a fixed application salt so the derivation
    is deterministic and does not require storing a per-secret salt.

    Parameters
    ----------
    raw_key:
        The vault_key string from settings (URL-safe base64 or arbitrary ASCII).

    Returns
    -------
    bytes
        URL-safe base64-encoded 32-byte key ready for ``Fernet(key)``.
    """
    # Fixed salt — not secret, but domain-separates this derivation from others.
    _SALT = b"ayaz-vault-v1-fernet-key-derivation"
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode(),
        _SALT,
        iterations=100_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(derived)


# ── Interface ─────────────────────────────────────────────────────────────────


class SecretsVault(ABC):
    """Abstract interface for secret storage.

    All implementations MUST be safe to call from multiple threads
    (the Celery worker pool is multi-process; within a process httpx is
    synchronous so no additional locking is needed).
    """

    @abstractmethod
    def put(self, ref: str, secret: dict[str, Any]) -> None:
        """Encrypt and persist ``secret`` under the given ``ref``.

        Parameters
        ----------
        ref:
            Opaque identifier for the secret (typically the ConnectedAccount UUID
            as a string).
        secret:
            Arbitrary JSON-serialisable dict (OAuth tokens, API keys, etc.).
        """

    @abstractmethod
    def get(self, ref: str) -> dict[str, Any] | None:
        """Retrieve and decrypt the secret stored under ``ref``.

        Returns
        -------
        dict | None
            The decrypted secret dict, or ``None`` if ``ref`` is not found or
            the stored value is empty.
        """

    @abstractmethod
    def delete(self, ref: str) -> None:
        """Remove the secret stored under ``ref``.

        No-op if ``ref`` is not found.
        """


# ── Default implementation — encrypted column ─────────────────────────────────


class EncryptedColumnVault(SecretsVault):
    """Stores Fernet-encrypted secrets inside ``connected_accounts.vault_secret_ref``.

    The ``ref`` parameter is the ConnectedAccount primary key (UUID string).
    ``put()`` writes the encrypted blob into that row's ``vault_secret_ref``
    column; ``get()`` reads and decrypts it.

    This avoids any new tables or migrations.  The column already carries the
    semantic comment "Vault path to OAuth tokens" — here we repurpose it to
    store the encrypted payload directly (prefixed with ``enc:`` to distinguish
    from a path reference used by the future HashiCorp impl).

    Thread / process safety
    -----------------------
    Fernet encryption is stateless.  Each call creates its own SQLAlchemy
    Session via the provided ``session_factory`` callable so concurrent Celery
    workers do not share sessions.
    """

    _ENC_PREFIX = "enc:"

    def __init__(self, session_factory: Any, vault_key: str | None = None) -> None:
        """
        Parameters
        ----------
        session_factory:
            Callable returning a new ``sqlalchemy.orm.Session`` (e.g.
            ``SessionLocal`` from ``ayaz.database``).
        vault_key:
            Override the key from ``settings.vault_key`` — useful in tests.
        """
        key_source = vault_key if vault_key is not None else settings.vault_key
        self._fernet = Fernet(_derive_fernet_key(key_source))
        self._session_factory = session_factory

    # ── internal helpers ──────────────────────────────────────────────────

    def _encrypt(self, secret: dict[str, Any]) -> str:
        """Return a prefixed ciphertext string."""
        plaintext = json.dumps(secret, default=str).encode()
        ciphertext = self._fernet.encrypt(plaintext)
        return self._ENC_PREFIX + ciphertext.decode()

    def _decrypt(self, blob: str) -> dict[str, Any] | None:
        """Decrypt a prefixed ciphertext string.  Returns None on empty/invalid."""
        if not blob or not blob.startswith(self._ENC_PREFIX):
            return None
        raw = blob[len(self._ENC_PREFIX):]
        try:
            plaintext = self._fernet.decrypt(raw.encode())
        except InvalidToken:
            # Tampered or keyed differently — treat as missing rather than crash.
            return None
        return json.loads(plaintext.decode())

    def _load_account(self, session: Session, ref: str) -> ConnectedAccount | None:
        """Fetch the ConnectedAccount row whose id matches ``ref``."""
        try:
            account_id = uuid.UUID(ref)
        except ValueError:
            return None
        return session.get(ConnectedAccount, account_id)

    # ── SecretsVault interface ─────────────────────────────────────────────

    def put(self, ref: str, secret: dict[str, Any]) -> None:
        """Encrypt ``secret`` and write it to the account's vault_secret_ref column."""
        blob = self._encrypt(secret)
        with self._session_factory() as session:
            account = self._load_account(session, ref)
            if account is None:
                raise KeyError(
                    f"EncryptedColumnVault.put: no ConnectedAccount with id={ref!r}"
                )
            account.vault_secret_ref = blob
            session.commit()

    def get(self, ref: str) -> dict[str, Any] | None:
        """Read and decrypt the secret for the given ConnectedAccount id."""
        with self._session_factory() as session:
            account = self._load_account(session, ref)
            if account is None:
                return None
            return self._decrypt(account.vault_secret_ref or "")

    def delete(self, ref: str) -> None:
        """Clear the vault_secret_ref column for the given ConnectedAccount id."""
        with self._session_factory() as session:
            account = self._load_account(session, ref)
            if account is not None:
                account.vault_secret_ref = ""
                session.commit()


# ── In-memory implementation (tests only) ─────────────────────────────────────


class InMemoryVault(SecretsVault):
    """Non-persistent vault backed by a plain dict — for unit tests only.

    No encryption; stores secrets in plain text so tests can inspect them
    without decryption gymnastics.  Never use in production.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def put(self, ref: str, secret: dict[str, Any]) -> None:
        self._store[ref] = dict(secret)

    def get(self, ref: str) -> dict[str, Any] | None:
        return dict(self._store[ref]) if ref in self._store else None

    def delete(self, ref: str) -> None:
        self._store.pop(ref, None)
