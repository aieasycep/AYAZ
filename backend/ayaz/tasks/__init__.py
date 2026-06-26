"""Celery task package for AYAZ background jobs.

Import the Celery application from ``ayaz.tasks.celery_app`` and tasks from
``ayaz.tasks.sync_tasks``.  The package __init__ is intentionally minimal so
the Celery worker can be launched with::

    celery -A ayaz.tasks.celery_app worker --loglevel=info
    celery -A ayaz.tasks.celery_app beat --loglevel=info
"""
