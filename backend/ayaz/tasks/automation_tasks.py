"""Automation & Rules engine Celery tasks — M9.

Tasks
-----
``evaluate_automation_rules()``
    Opens a DB session, calls ``run_all_active_rules`` for all tenants, returns
    a summary dict.  Designed to be called by the Celery beat on a nightly
    schedule (00:30 UTC by default).

Beat schedule
-------------
The recommended beat entry is exposed as ``BEAT_ENTRY`` at the bottom of this
module.  The team lead should register it in ``celery_app.conf.beat_schedule``
inside ``ayaz/tasks/celery_app.py`` by merging it:

    from ayaz.tasks.automation_tasks import BEAT_ENTRY
    celery_app.conf.beat_schedule.update(BEAT_ENTRY)

Alternatively, the task can be added to celery_app.py's include list and its
schedule added directly:

    celery_app.conf.beat_schedule["evaluate-automation-rules-nightly"] = {
        "task": "ayaz.tasks.automation_tasks.evaluate_automation_rules",
        "schedule": crontab(hour=0, minute=30),
        "options": {"queue": "beat"},
    }

Tests
-----
Tests call the service layer functions directly (``run_all_active_rules``) or
invoke the task function body directly without a broker.  No live Celery broker
or Redis connection is required in the test suite.
"""

from __future__ import annotations

import logging

from celery import shared_task
from celery.schedules import crontab

from ayaz.database import SessionLocal
from ayaz.services.automation import run_all_active_rules
from ayaz.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# ── Task ──────────────────────────────────────────────────────────────────────


@celery_app.task(
    name="ayaz.tasks.automation_tasks.evaluate_automation_rules",
    acks_late=True,
)
def evaluate_automation_rules() -> dict[str, object]:
    """Evaluate all active AutomationRules across all tenants.

    Opens its own DB session (not shared across Celery tasks / workers).
    Calls ``run_all_active_rules`` with ``tenant_id=None`` so every active
    tenant's rules are evaluated in one pass.

    Returns
    -------
    dict with keys ``evaluated``, ``triggered``, ``errors`` forwarded from
    ``run_all_active_rules``.

    Tests
    -----
    Tests should call the service function directly::

        from ayaz.services.automation import run_all_active_rules
        result = run_all_active_rules(db_session)

    Or call this task synchronously via Celery's eager mode by setting
    ``CELERY_TASK_ALWAYS_EAGER=True`` in the test environment.
    No live broker is required.
    """
    logger.info("[automation_tasks] evaluate_automation_rules starting")

    with SessionLocal() as db:
        result = run_all_active_rules(db, tenant_id=None)

    logger.info("[automation_tasks] evaluate_automation_rules done: %s", result)
    return result


# ── Beat schedule entry ───────────────────────────────────────────────────────

#: Recommended beat schedule entry for this task.
#: Team lead: merge this into celery_app.conf.beat_schedule, e.g.:
#:
#:     from ayaz.tasks.automation_tasks import BEAT_ENTRY
#:     celery_app.conf.beat_schedule.update(BEAT_ENTRY)
BEAT_ENTRY: dict = {
    "evaluate-automation-rules-nightly": {
        "task": "ayaz.tasks.automation_tasks.evaluate_automation_rules",
        "schedule": crontab(hour=0, minute=30),  # 00:30 UTC daily
        "options": {"queue": "beat"},
    },
}
