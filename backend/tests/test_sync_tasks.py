"""Unit tests for Celery sync tasks.

Coverage
--------
- ``sync_account_task``: loads account from DB, calls sync_connected_account,
  handles missing/invalid account_id, handles non-syncable status, handles vault tokens.
- ``sync_all_active_accounts``: enqueues one task per syncable account,
  skips paused/error accounts.

No live Redis / Celery broker required.  Tests call the task function
directly (.apply() in eager mode, or direct function invocation) and mock
both the sync pipeline and the Vault.

SQLite is used as the in-process database.

Each test gets a completely fresh in-memory database (function-scoped engine)
to avoid cross-test contamination via the shared StaticPool connection.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ayaz.models.base import Base
from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus, Tenant


# ── Per-test SQLite setup ─────────────────────────────────────────────────────


def _make_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng, checkfirst=True)
    return eng


@contextmanager
def _make_session_factory(eng):
    """Return a context-manager session factory for a given engine."""
    Factory = sessionmaker(bind=eng, class_=Session)

    @contextmanager
    def _factory():
        session = Factory()
        try:
            yield session
        finally:
            session.close()

    yield _factory


def _insert_accounts(eng, statuses: list[SyncStatus]) -> list[ConnectedAccount]:
    """Insert a tenant and one account per status; return the account list."""
    with sessionmaker(bind=eng, class_=Session)() as session:
        tenant = Tenant(
            name="Sync Test Tenant",
            country="TR",
            base_currency="TRY",
            kvkk_region="TR",
        )
        session.add(tenant)
        session.flush()

        accounts = []
        for i, status in enumerate(statuses):
            acc = ConnectedAccount(
                tenant_id=tenant.id,
                platform=Platform.sample,
                external_account_id=f"sample-{i:03d}",
                display_name=f"Account {i}",
                vault_secret_ref="",
                sync_status=status,
            )
            session.add(acc)
            accounts.append(acc)

        session.commit()
        # Detach so IDs are accessible after session close
        return [
            ConnectedAccount(
                id=a.id,
                tenant_id=tenant.id,
                platform=a.platform,
                external_account_id=a.external_account_id,
                display_name=a.display_name,
                vault_secret_ref=a.vault_secret_ref,
                sync_status=a.sync_status,
            )
            for a in accounts
        ]


# ── sync_account_task ─────────────────────────────────────────────────────────


def test_sync_account_task_calls_sync():
    """Task should call sync_connected_account for a valid idle account."""
    eng = _make_engine()
    accounts = _insert_accounts(eng, [SyncStatus.idle])
    account_id = str(accounts[0].id)
    fake_result = {"inserted": 5, "updated": 2, "records_processed": 7}

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
            patch("ayaz.tasks.sync_tasks.sync_connected_account", return_value=fake_result) as mock_sync,
        ):
            mock_vault_instance = MagicMock()
            mock_vault_instance.get.return_value = None
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run(account_id)

    assert result == fake_result
    mock_sync.assert_called_once()


def test_sync_account_task_invalid_uuid_returns_error():
    """A non-UUID account_id should return an error dict without raising."""
    eng = _make_engine()
    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
        ):
            mock_vault_instance = MagicMock()
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run("not-a-uuid")

    assert result == {"error": "invalid_account_id"}


def test_sync_account_task_missing_account_returns_error():
    """Non-existent UUID should return account_not_found without raising."""
    eng = _make_engine()
    missing_id = str(uuid.uuid4())

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
        ):
            mock_vault_instance = MagicMock()
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run(missing_id)

    assert result == {"error": "account_not_found"}


def test_sync_account_task_paused_account_skipped():
    """Paused accounts should not trigger a sync call."""
    eng = _make_engine()
    accounts = _insert_accounts(eng, [SyncStatus.paused])
    account_id = str(accounts[0].id)

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
            patch("ayaz.tasks.sync_tasks.sync_connected_account") as mock_sync,
        ):
            mock_vault_instance = MagicMock()
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run(account_id)

    mock_sync.assert_not_called()
    assert result.get("skipped") is True


def test_sync_account_task_error_account_skipped():
    """Error accounts should not trigger a sync call."""
    eng = _make_engine()
    accounts = _insert_accounts(eng, [SyncStatus.error])
    account_id = str(accounts[0].id)

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
            patch("ayaz.tasks.sync_tasks.sync_connected_account") as mock_sync,
        ):
            mock_vault_instance = MagicMock()
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run(account_id)

    mock_sync.assert_not_called()
    assert result.get("skipped") is True


def test_sync_account_task_with_vault_tokens():
    """The task threads its EncryptedColumnVault instance through to
    ``sync_connected_account`` (which is the one that actually calls
    ``vault.get()``) rather than resolving tokens itself."""
    eng = _make_engine()
    accounts = _insert_accounts(eng, [SyncStatus.idle])
    account_id = str(accounts[0].id)
    tokens = {"access_token": "live_token", "refresh_token": "ref_token"}
    fake_result = {"inserted": 1, "updated": 0, "records_processed": 1}

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
            patch(
                "ayaz.tasks.sync_tasks.sync_connected_account", return_value=fake_result
            ) as mock_sync,
        ):
            mock_vault_instance = MagicMock()
            mock_vault_instance.get.return_value = tokens
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            result = sync_account_task.run(account_id)

    assert mock_sync.call_args.kwargs.get("vault") is mock_vault_instance
    assert result == fake_result


def test_sync_account_task_custom_date_range():
    """since_iso / until_iso parameters should be forwarded to sync."""
    eng = _make_engine()
    accounts = _insert_accounts(eng, [SyncStatus.idle])
    account_id = str(accounts[0].id)

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.EncryptedColumnVault") as MockVault,
            patch("ayaz.tasks.sync_tasks.sync_connected_account", return_value={}) as mock_sync,
        ):
            mock_vault_instance = MagicMock()
            mock_vault_instance.get.return_value = None
            MockVault.return_value = mock_vault_instance

            from ayaz.tasks.sync_tasks import sync_account_task

            sync_account_task.run(account_id, since_iso="2025-01-01", until_iso="2025-01-07")

    call_args = mock_sync.call_args
    # sync_connected_account(db, account, since=..., until=...)
    assert call_args[1].get("since") == date(2025, 1, 1) or call_args[0][2] == date(2025, 1, 1)
    assert call_args[1].get("until") == date(2025, 1, 7) or call_args[0][3] == date(2025, 1, 7)


# ── sync_all_active_accounts ──────────────────────────────────────────────────


def test_sync_all_enqueues_idle_and_success():
    """sync_all_active_accounts should enqueue idle + success, skip paused + error."""
    eng = _make_engine()
    accounts = _insert_accounts(
        eng,
        [SyncStatus.idle, SyncStatus.success, SyncStatus.paused, SyncStatus.error],
    )
    idle_acc, success_acc, paused_acc, error_acc = accounts
    enqueued_ids: list[str] = []

    def _mock_delay(account_id: str) -> None:
        enqueued_ids.append(account_id)

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.sync_account_task") as mock_task,
        ):
            mock_task.delay.side_effect = _mock_delay

            from ayaz.tasks.sync_tasks import sync_all_active_accounts

            result = sync_all_active_accounts.run()

    assert str(idle_acc.id) in enqueued_ids
    assert str(success_acc.id) in enqueued_ids
    assert str(paused_acc.id) not in enqueued_ids
    assert str(error_acc.id) not in enqueued_ids
    assert result["enqueued"] == 2


def test_sync_all_returns_enqueued_count():
    """Result should carry the count and account_ids list."""
    eng = _make_engine()
    _insert_accounts(eng, [SyncStatus.idle])

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.sync_account_task") as mock_task,
        ):
            mock_task.delay = MagicMock()

            from ayaz.tasks.sync_tasks import sync_all_active_accounts

            result = sync_all_active_accounts.run()

    assert "enqueued" in result
    assert "account_ids" in result
    assert isinstance(result["account_ids"], list)


def test_sync_all_empty_db_returns_zero():
    """With no accounts at all, enqueued count should be 0."""
    eng = _make_engine()

    with _make_session_factory(eng) as sf_ctx:
        with (
            patch("ayaz.tasks.sync_tasks.SessionLocal", sf_ctx),
            patch("ayaz.tasks.sync_tasks.sync_account_task") as mock_task,
        ):
            mock_task.delay = MagicMock()

            from ayaz.tasks.sync_tasks import sync_all_active_accounts

            result = sync_all_active_accounts.run()

    assert result["enqueued"] == 0
    assert result["account_ids"] == []
