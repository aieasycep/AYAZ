"""Celery application factory for AYAZ.

The broker and result backend both default to Redis (``settings.redis_url``).
Configure via the ``REDIS_URL`` environment variable in production.

Worker launch::

    celery -A ayaz.tasks.celery_app worker --loglevel=info --concurrency=4

Beat (scheduler) launch::

    celery -A ayaz.tasks.celery_app beat --loglevel=info

Combined (development only)::

    celery -A ayaz.tasks.celery_app worker --beat --loglevel=info

Dependencies (add to pyproject.toml)::

    celery[redis]>=5.3,<6
    redis>=5.0,<6
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from ayaz.config import settings

# ── Application ───────────────────────────────────────────────────────────────

celery_app = Celery(
    "ayaz",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["ayaz.tasks.sync_tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reliability
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Result expiry: 24 hours
    result_expires=86_400,
)

# ── Beat schedule ─────────────────────────────────────────────────────────────

celery_app.conf.beat_schedule = {
    # Fan-out: enqueue one sync_account_task per active connected account.
    # Runs every hour at minute 0.
    "sync-all-active-accounts-hourly": {
        "task": "ayaz.tasks.sync_tasks.sync_all_active_accounts",
        "schedule": crontab(minute=0),  # top of every hour
        "options": {"queue": "beat"},
    },
}

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_queues = {
    "default": {},
    "beat": {},
}
