"""Celery sync tasks — periodic data pull from all connected accounts.

Tasks
-----
``sync_account_task(account_id)``
    Load one ConnectedAccount, inject vault tokens into ConnectorConfig.extra,
    then call ``sync_connected_account`` for the last 2 days (today + yesterday
    as the default incremental window).  Marks the account as ``error`` if any
    exception escapes.

``sync_all_active_accounts()``
    Query all ConnectedAccounts whose ``sync_status`` is NOT ``error`` / ``paused``,
    then enqueue one ``sync_account_task`` per account.  The beat schedule calls
    this hourly.

Design notes
------------
- Both tasks open their own SQLAlchemy session (not shared across tasks/workers).
- Vault tokens are fetched once per task invocation and injected into
  ``ConnectorConfig.extra`` so the connector can authenticate without knowing
  about the Vault implementation.
- The date window defaults to ``[today - 1 day, today]`` (2-day incremental
  window).  The scheduler could pass a wider window for backfill jobs in future.
- ``sync_account_task`` is idempotent: running it twice for the same account
  and date range is safe (``sync_connected_account`` uses INSERT-or-UPDATE).
- No live network or broker required in unit tests — tests call the task
  function directly or use Celery's ``CELERY_TASK_ALWAYS_EAGER`` mode.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta, timezone, datetime

from celery import shared_task
from sqlalchemy import select

from ayaz.database import SessionLocal
from ayaz.models.oltp import ConnectedAccount, SyncStatus
from ayaz.services.sync import sync_connected_account
from ayaz.services.vault import EncryptedColumnVault
from ayaz.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Active statuses — accounts eligible for sync ──────────────────────────────

_SYNCABLE_STATUSES = {SyncStatus.idle, SyncStatus.success}


# ── Tasks ─────────────────────────────────────────────────────────────────────


@celery_app.task(
    name="ayaz.tasks.sync_tasks.sync_account_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 60 seconds between retries
    acks_late=True,
)
def sync_account_task(
    self,  # noqa: ANN001  (Celery bound task — type is celery.Task)
    account_id: str,
    since_iso: str | None = None,
    until_iso: str | None = None,
) -> dict[str, object]:
    """Sync one connected account.

    Parameters
    ----------
    account_id:
        UUID string of the ``ConnectedAccount`` to sync.
    since_iso:
        ISO-8601 date string for the sync window start (inclusive).
        Defaults to yesterday (UTC).
    until_iso:
        ISO-8601 date string for the sync window end (inclusive).
        Defaults to today (UTC).

    Returns
    -------
    dict
        ``{"inserted": int, "updated": int, "records_processed": int}``
        forwarded from ``sync_connected_account``.
    """
    today = date.today()
    since = date.fromisoformat(since_iso) if since_iso else today - timedelta(days=1)
    until = date.fromisoformat(until_iso) if until_iso else today

    logger.info(
        "[sync_account_task] account=%s since=%s until=%s",
        account_id,
        since,
        until,
    )

    vault = EncryptedColumnVault(session_factory=SessionLocal)

    with SessionLocal() as db:
        # Load account
        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError:
            logger.error("[sync_account_task] Invalid account_id=%r", account_id)
            return {"error": "invalid_account_id"}

        account = db.get(ConnectedAccount, acct_uuid)
        if account is None:
            logger.warning(
                "[sync_account_task] ConnectedAccount not found: %s", account_id
            )
            return {"error": "account_not_found"}

        if account.sync_status not in _SYNCABLE_STATUSES:
            logger.info(
                "[sync_account_task] Skipping account=%s status=%s",
                account_id,
                account.sync_status,
            )
            return {"skipped": True, "status": account.sync_status.value}

        try:
            result = sync_connected_account(
                db, account, since=since, until=until, vault=vault
            )
            logger.info(
                "[sync_account_task] Done: account=%s result=%s", account_id, result
            )
            return result
        except Exception as exc:
            logger.exception(
                "[sync_account_task] Failed: account=%s", account_id
            )
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                logger.error(
                    "[sync_account_task] Max retries exceeded: account=%s", account_id
                )
                return {"error": "max_retries_exceeded", "detail": str(exc)}


@celery_app.task(
    name="ayaz.tasks.sync_tasks.sync_all_active_accounts",
    acks_late=True,
)
def sync_all_active_accounts() -> dict[str, object]:
    """Discover all syncable accounts and enqueue one task per account.

    Called by the Celery beat schedule (hourly).  Returns a summary of how
    many tasks were enqueued.
    """
    logger.info("[sync_all_active_accounts] Starting fan-out.")

    with SessionLocal() as db:
        accounts = list(
            db.scalars(
                select(ConnectedAccount).where(
                    ConnectedAccount.sync_status.in_(_SYNCABLE_STATUSES)
                )
            )
        )

    enqueued = 0
    for account in accounts:
        sync_account_task.delay(str(account.id))
        enqueued += 1
        logger.debug(
            "[sync_all_active_accounts] Enqueued account=%s platform=%s",
            account.id,
            account.platform,
        )

    logger.info("[sync_all_active_accounts] Enqueued %d tasks.", enqueued)
    return {"enqueued": enqueued, "account_ids": [str(a.id) for a in accounts]}
