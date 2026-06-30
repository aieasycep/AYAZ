"""GrantVault — Vault implementation backed by provider_grants.vault_secret_ref.

Wave 2 integrations use ``ProviderGrant`` rows (not ``ConnectedAccount`` rows)
to store OAuth tokens.  ``GrantVault`` provides the same ``SecretsVault``
interface as ``EncryptedColumnVault`` but writes to / reads from the
``provider_grants.vault_secret_ref`` column keyed by the grant UUID.

Design notes
------------
- Encryption: same Fernet key derivation as ``EncryptedColumnVault``
  (PBKDF2-HMAC-SHA256, fixed salt).
- The encrypted blob is prefixed with ``enc:`` to distinguish it from a future
  HashiCorp Vault path reference (same convention as the existing vault impl).
- ``put`` and ``delete`` call ``db.flush()`` (not ``commit()``) so the caller
  controls the transaction boundary — consistent with the request-level
  session-per-request pattern used in the router.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ayaz.config import settings
from ayaz.services.vault import SecretsVault, _derive_fernet_key


class GrantVault(SecretsVault):
    """Vault backed by ``provider_grants.vault_secret_ref`` column.

    Parameters
    ----------
    db:
        An active SQLAlchemy session.  The caller is responsible for committing.
    vault_key:
        Override the Fernet key source — used in tests to supply a deterministic
        key without relying on ``settings``.
    """

    _ENC_PREFIX = "enc:"

    def __init__(self, db: Session, vault_key: str | None = None) -> None:
        key_source = vault_key if vault_key is not None else settings.vault_key
        self._fernet = Fernet(_derive_fernet_key(key_source))
        self._db = db

    # ── internal helpers ──────────────────────────────────────────────────

    def _load_grant(self, ref: str):
        """Load a ProviderGrant by UUID string.  Returns None if not found."""
        from ayaz.models.integrations import ProviderGrant

        try:
            grant_id = uuid.UUID(ref)
        except ValueError:
            return None
        return self._db.get(ProviderGrant, grant_id)

    # ── SecretsVault interface ─────────────────────────────────────────────

    def put(self, ref: str, secret: dict[str, Any]) -> None:
        """Encrypt ``secret`` and write it to the grant's vault_secret_ref column.

        Raises
        ------
        KeyError
            If no ``ProviderGrant`` exists with the given ``ref`` UUID.
        """
        grant = self._load_grant(ref)
        if grant is None:
            raise KeyError(f"GrantVault.put: no ProviderGrant with id={ref!r}")
        plaintext = json.dumps(secret, default=str).encode()
        blob = self._ENC_PREFIX + self._fernet.encrypt(plaintext).decode()
        grant.vault_secret_ref = blob
        self._db.flush()

    def get(self, ref: str) -> dict[str, Any] | None:
        """Read and decrypt the secret for the given grant UUID.

        Returns ``None`` if the grant is not found or the column is empty/invalid.
        """
        grant = self._load_grant(ref)
        if grant is None:
            return None
        blob = grant.vault_secret_ref or ""
        if not blob.startswith(self._ENC_PREFIX):
            return None
        try:
            plaintext = self._fernet.decrypt(
                blob[len(self._ENC_PREFIX):].encode()
            )
            return json.loads(plaintext)
        except InvalidToken:
            return None

    def delete(self, ref: str) -> None:
        """Clear the vault_secret_ref column for the given grant UUID.

        No-op if the grant is not found.
        """
        grant = self._load_grant(ref)
        if grant is not None:
            grant.vault_secret_ref = ""
            self._db.flush()
