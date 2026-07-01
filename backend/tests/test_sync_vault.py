"""Sync → Vault credential injection (real-data path).

Verifies that ``sync_connected_account`` loads stored OAuth tokens from the
Vault and injects them into ``ConnectorConfig.extra``, and calls
``authenticate()`` — the wiring that makes real (non-fixture) connector syncs
work.  Also verifies the credential-free fixture path is untouched when no vault
is supplied.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401

from ayaz.connectors.base import ConnectorCapabilities
from ayaz.models.base import Base
from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus, Tenant
from ayaz.services.sync import sync_connected_account
from ayaz.services.vault import InMemoryVault


# ── Spy connector that records the config it was built with ───────────────────

_spy_state: dict = {}


class _SpyConnector:
    def __init__(self, config):
        self.config = config
        _spy_state["extra"] = dict(config.extra)
        _spy_state["authed"] = False

    def authenticate(self) -> None:
        _spy_state["authed"] = True

    def capabilities(self) -> ConnectorCapabilities:
        # No streams → fetch loop is skipped; we only assert on config wiring.
        return ConnectorCapabilities(platform_key="sample", supported_streams=[])

    def fetch(self, stream, since, until):  # pragma: no cover - not reached
        return []

    def normalize(self, raw):  # pragma: no cover - not reached
        return []


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_account(db: Session) -> ConnectedAccount:
    tenant = Tenant(
        id=uuid.uuid4(), name="Sync Vault T",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(tenant)
    db.flush()
    acct = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.sample,
        external_account_id="act_123", display_name="Real Acct",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db.add(acct)
    db.commit()
    return acct


_SINCE = date(2026, 1, 1)
_UNTIL = date(2026, 1, 3)


def test_vault_secrets_injected_and_authenticate_called(db_session: Session) -> None:
    _spy_state.clear()
    acct = _make_account(db_session)
    vault = InMemoryVault()
    vault.put(str(acct.id), {"access_token": "TOKEN-XYZ", "ad_account_id": "act_123"})

    with patch("ayaz.services.sync.ConnectorRegistry.get", return_value=_SpyConnector):
        sync_connected_account(db_session, acct, _SINCE, _UNTIL, vault=vault)

    assert _spy_state["extra"].get("access_token") == "TOKEN-XYZ"
    assert _spy_state["extra"].get("ad_account_id") == "act_123"
    assert _spy_state["authed"] is True


def test_no_vault_keeps_fixture_path(db_session: Session) -> None:
    _spy_state.clear()
    acct = _make_account(db_session)

    with patch("ayaz.services.sync.ConnectorRegistry.get", return_value=_SpyConnector):
        sync_connected_account(db_session, acct, _SINCE, _UNTIL)  # no vault

    assert _spy_state["extra"] == {}
    assert _spy_state["authed"] is False


def test_vault_returning_none_is_safe(db_session: Session) -> None:
    _spy_state.clear()
    acct = _make_account(db_session)
    vault = InMemoryVault()  # empty — get() returns None

    with patch("ayaz.services.sync.ConnectorRegistry.get", return_value=_SpyConnector):
        sync_connected_account(db_session, acct, _SINCE, _UNTIL, vault=vault)

    assert _spy_state["extra"] == {}
    assert _spy_state["authed"] is False
