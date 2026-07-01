"""Celery periodic task — proactive OAuth token refresh.

Design (§4.3, entegrasyon-aksiyon-merkezi-tasarim-2026-06.md)
------------------------------------------------------------
``refresh_due_grants`` runs every 15 minutes (registered in celery_app.py).
It finds ``ProviderGrant`` rows whose ``access_expires_at`` is within the
refresh window (default: 10 minutes from now) *or* already expired, and
refreshes them via ``oauth_broker.refresh_token()``.

On success:
    - Updates ``vault_secret_ref`` via ``GrantVault.put()``
    - Updates ``access_expires_at`` on the grant row
    - Leaves ``status = "active"``

On failure (network error, HTTP 401, invalid_grant, etc.):
    - Sets ``grant.status = "reauth_required"``
    - Sets all ``IntegrationConnection.status = "needs_reconnect"`` for that grant
    - Does NOT raise — one failing grant must not abort the batch

Idempotency
-----------
The task re-queries fresh state at each run.  Grants refreshed within the
current window are skipped via the ``access_expires_at`` filter.  Grants
without an ``access_expires_at`` (non-expiring tokens, api_key) are skipped.
Already-revoked grants are skipped.

Usage
-----
The task is imported and scheduled by ``celery_app.py``::

    include=["ayaz.tasks.token_refresh", ...]
    beat_schedule={"refresh-due-grants": {"task": "...", "schedule": crontab(...)}}
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# Refresh grants expiring within this many minutes from now.
_REFRESH_WINDOW_MINUTES = 10


def _get_db() -> Session:
    """Return a fresh SQLAlchemy session using the application database URL."""
    from ayaz.database import SessionLocal

    return SessionLocal()


def _refresh_one_grant(db: Session, grant_id: uuid.UUID) -> bool:
    """Attempt to refresh a single ProviderGrant.

    Returns True on success, False on failure.
    Marks grant + connected connections on failure.
    """
    from ayaz.models.integrations import IntegrationConnection, ProviderGrant
    from ayaz.services import oauth_broker
    from ayaz.services.grant_vault import GrantVault

    grant = db.get(ProviderGrant, grant_id)
    if grant is None:
        _log.warning("refresh_one_grant: grant %s not found (deleted?)", grant_id)
        return False

    if grant.status == "revoked":
        _log.debug("refresh_one_grant: grant %s already revoked — skip", grant_id)
        return True  # nothing to do

    # Decrypt current token to get the refresh_token
    vault = GrantVault(db)
    token_data = vault.get(str(grant_id))
    if token_data is None:
        _log.warning(
            "refresh_one_grant: no vault secret for grant %s — marking needs_reconnect",
            grant_id,
        )
        _mark_grant_failed(db, grant, grant_id)
        return False

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        _log.warning(
            "refresh_one_grant: grant %s has no refresh_token — cannot refresh",
            grant_id,
        )
        # Non-expiring or api_key grant — leave as-is
        return True

    provider = grant.provider

    try:
        new_tokens = oauth_broker.refresh(provider, refresh_token)
    except Exception as exc:
        _log.error(
            "refresh_one_grant: refresh failed for grant %s provider=%s: %s",
            grant_id,
            provider,
            exc,
        )
        _mark_grant_failed(db, grant, grant_id)
        return False

    # ── Update vault ─────────────────────────────────────────────────────────
    try:
        # Preserve refresh_token if provider doesn't return a new one
        if "refresh_token" not in new_tokens or not new_tokens["refresh_token"]:
            new_tokens["refresh_token"] = refresh_token
        vault.put(str(grant_id), new_tokens)
    except Exception as exc:
        _log.error(
            "refresh_one_grant: vault.put failed for grant %s: %s", grant_id, exc
        )
        _mark_grant_failed(db, grant, grant_id)
        return False

    # ── Update access_expires_at ─────────────────────────────────────────────
    expires_in = new_tokens.get("expires_in")
    if expires_in is not None:
        try:
            grant.access_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(expires_in)
            )
        except (TypeError, ValueError):
            pass

    grant.status = "active"
    db.flush()

    _log.info(
        "refresh_one_grant: successfully refreshed grant %s provider=%s",
        grant_id,
        provider,
    )
    return True


def _mark_grant_failed(db: Session, grant: Any, grant_id: uuid.UUID) -> None:
    """Mark a grant and all its connections as needing reconnection."""
    from ayaz.models.integrations import IntegrationConnection

    grant.status = "reauth_required"

    connections = db.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.provider_grant_id == grant_id
        )
    ).all()

    for conn in connections:
        conn.status = "needs_reconnect"
        _log.info(
            "refresh_one_grant: marked connection %s (key=%s tenant=%s) needs_reconnect",
            conn.id,
            conn.integration_key,
            conn.tenant_id,
        )

    db.flush()


@shared_task(
    name="ayaz.tasks.token_refresh.refresh_due_grants",
    bind=True,
    max_retries=0,  # Retry is per-grant inside the loop; task itself does not retry
    ignore_result=True,
    soft_time_limit=300,  # 5 minutes max; beat runs every 15 minutes
    time_limit=360,
)
def refresh_due_grants(self) -> dict:  # type: ignore[misc]
    """Refresh all ProviderGrant tokens that are due for renewal.

    A grant is "due" when its ``access_expires_at`` is within
    ``_REFRESH_WINDOW_MINUTES`` minutes from now, or is already in the past.

    Grants without ``access_expires_at`` (non-expiring, api_key) are skipped.
    Revoked grants are skipped.

    Returns a summary dict with counts: refreshed, failed, skipped.
    This value is only useful for testing; the task uses ``ignore_result=True``
    in production.
    """
    from ayaz.models.integrations import ProviderGrant

    db = _get_db()
    refreshed = 0
    failed = 0

    try:
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=_REFRESH_WINDOW_MINUTES)

        # Find all grants with an access_expires_at within the refresh window
        # (already expired OR expiring soon) and not already revoked.
        due_grant_ids: list[uuid.UUID] = list(
            db.scalars(
                select(ProviderGrant.id).where(
                    ProviderGrant.access_expires_at.isnot(None),
                    ProviderGrant.access_expires_at <= cutoff,
                    ProviderGrant.status != "revoked",
                )
            ).all()
        )

        _log.info(
            "refresh_due_grants: found %d grant(s) due for refresh", len(due_grant_ids)
        )

        for grant_id in due_grant_ids:
            success = _refresh_one_grant(db, grant_id)
            if success:
                refreshed += 1
            else:
                failed += 1

        db.commit()

    except Exception as exc:
        _log.error("refresh_due_grants: unexpected error: %s", exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()

    result = {
        "refreshed": refreshed,
        "failed": failed,
        "total_due": len(due_grant_ids) if "due_grant_ids" in dir() else 0,
    }
    _log.info("refresh_due_grants: done — %s", result)
    return result
