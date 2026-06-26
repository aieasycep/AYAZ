"""Daily Briefing Celery task — Proactive AI Turkish Digest.

Tasks
-----
``generate_daily_briefings()``
    Iterates all tenants that have fact data for yesterday, generates a briefing
    for each, delivers it via the notifier stubs, and commits.  Designed to run
    at 07:00 UTC daily via Celery Beat.

Beat schedule
-------------
The recommended beat entry is exposed as ``BEAT_ENTRY`` at the bottom of this
module.  The team lead should register it in ``celery_app.conf.beat_schedule``
inside ``ayaz/tasks/celery_app.py`` by merging it:

    from ayaz.tasks.briefing_tasks import BEAT_ENTRY
    celery_app.conf.beat_schedule.update(BEAT_ENTRY)

Or add directly:

    celery_app.conf.beat_schedule["generate-daily-briefings"] = {
        "task": "ayaz.tasks.briefing_tasks.generate_daily_briefings",
        "schedule": crontab(hour=7, minute=0),
        "options": {"queue": "beat"},
    }

And add "ayaz.tasks.briefing_tasks" to the ``include`` list in celery_app.py.

Tests
-----
Tests call the service layer directly (``generate_briefing``) or invoke this
task function body directly without a broker.  No live Celery broker or Redis
connection is required in the test suite.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from celery.schedules import crontab

from ayaz.database import SessionLocal
from ayaz.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tenants_with_data(db, as_of_date: date):
    """Return distinct tenant UUIDs that have FactDailyMetrics for yesterday.

    This gates briefing generation so we only process tenants with actual data.
    """
    from sqlalchemy import select

    from ayaz.models.analytics import FactDailyMetrics

    yesterday = as_of_date - timedelta(days=1)
    rows = db.execute(
        select(FactDailyMetrics.tenant_id)
        .where(FactDailyMetrics.date_key == yesterday)
        .distinct()
    ).scalars().all()
    return list(rows)


# ── Task ──────────────────────────────────────────────────────────────────────


@celery_app.task(
    name="ayaz.tasks.briefing_tasks.generate_daily_briefings",
    acks_late=True,
)
def generate_daily_briefings() -> dict[str, object]:
    """Generate and deliver the daily Turkish briefing for all active tenants.

    Opens its own DB session (not shared across workers).  For each tenant that
    has fact data for yesterday, calls ``generate_briefing`` (idempotent) then
    ``deliver_briefing`` via the notification stubs.

    Returns
    -------
    dict with keys:
        ``generated`` — number of briefings successfully written.
        ``delivered`` — number of delivery attempts made.
        ``errors``    — number of per-tenant failures.

    Schedule
    --------
    Intended to run at 07:00 UTC daily.  See ``BEAT_ENTRY`` below.
    """
    from ayaz.services.briefing import deliver_briefing, generate_briefing

    today = date.today()
    logger.info("[briefing_tasks] generate_daily_briefings starting for as_of=%s", today)

    generated = 0
    delivered = 0
    errors = 0

    with SessionLocal() as db:
        tenant_ids = _tenants_with_data(db, today)
        logger.info("[briefing_tasks] Found %d tenants with data", len(tenant_ids))

        for tenant_id in tenant_ids:
            try:
                briefing = generate_briefing(db, tenant_id, as_of_date=today)
                db.commit()
                generated += 1

                try:
                    deliver_briefing(db, briefing)
                    delivered += 1
                except Exception as exc:
                    logger.warning(
                        "[briefing_tasks] deliver_briefing failed for tenant=%s: %s",
                        tenant_id,
                        exc,
                    )
                    # Delivery failure is non-fatal — briefing was written.

            except Exception as exc:
                logger.exception(
                    "[briefing_tasks] generate_briefing failed for tenant=%s: %s",
                    tenant_id,
                    exc,
                )
                db.rollback()
                errors += 1

    result = {"generated": generated, "delivered": delivered, "errors": errors}
    logger.info("[briefing_tasks] Done: %s", result)
    return result


# ── Beat schedule entry ───────────────────────────────────────────────────────

#: Recommended beat schedule entry.
#: Team lead: merge this into celery_app.conf.beat_schedule, e.g.:
#:
#:     from ayaz.tasks.briefing_tasks import BEAT_ENTRY
#:     celery_app.conf.beat_schedule.update(BEAT_ENTRY)
#:
#: Also add "ayaz.tasks.briefing_tasks" to the ``include`` list in celery_app.py.
BEAT_ENTRY: dict = {
    "generate-daily-briefings": {
        "task": "ayaz.tasks.briefing_tasks.generate_daily_briefings",
        "schedule": crontab(hour=7, minute=0),  # 07:00 UTC daily
        "options": {"queue": "beat"},
    },
}
