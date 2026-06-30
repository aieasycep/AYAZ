"""Kullanım Kalkanı Celery görevleri — periyodik limit ve atıl konektör kontrolü.

Görevler
--------
``check_shield_for_tenant(tenant_id)``
    Tek bir kiracı için kullanım kalkanını çalıştırır, gerekli bildirimleri
    Bildirim Merkezine yazar.  İdempotent: spam koruma penceresi (24 saat)
    nedeniyle aynı bildirim tekrar yazılmaz.

``check_shield_all_tenants()``
    Tüm kiracılar için ``check_shield_for_tenant`` görevlerini fan-out eder.
    Beat schedule'ı tarafından günde bir kez çağrılır.

Tasarım
-------
- Her görev kendi SQLAlchemy oturumunu açar.
- Bir kiracıda oluşan hata diğer kiracıların işlenmesini durdurmaz.
- Celery broker gerekmez (testlerde doğrudan çağrılabilir).
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from sqlalchemy import select

from ayaz.database import SessionLocal
from ayaz.models.oltp import Tenant
from ayaz.services.usage_shield import check_and_notify
from ayaz.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="ayaz.tasks.shield_tasks.check_shield_for_tenant",
    acks_late=True,
    max_retries=2,
    default_retry_delay=30,
)
def check_shield_for_tenant(tenant_id: str) -> dict:
    """Tek bir kiracı için kullanım kalkanını çalıştırır.

    Parameters
    ----------
    tenant_id:
        UUID string.

    Returns
    -------
    dict
        ``{"tenant_id": str, "notifications_created": int}``
    """
    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        logger.error("[shield] Geçersiz tenant_id: %r", tenant_id)
        return {"error": "invalid_tenant_id"}

    logger.info("[shield] Kiracı kontrolü: %s", tenant_id)

    with SessionLocal() as db:
        try:
            result = check_and_notify(db, tid)
            n = result["notifications_created"]
            if n:
                logger.info("[shield] %s → %d bildirim oluşturuldu.", tenant_id, n)
            return {"tenant_id": tenant_id, "notifications_created": n}
        except Exception as exc:
            logger.exception("[shield] Hata: tenant=%s", tenant_id)
            return {"tenant_id": tenant_id, "error": str(exc)}


@celery_app.task(
    name="ayaz.tasks.shield_tasks.check_shield_all_tenants",
    acks_late=True,
)
def check_shield_all_tenants() -> dict:
    """Tüm kiracılar için shield kontrolünü fan-out eder.

    Beat schedule tarafından günde bir kez çağrılır (00:15 UTC).
    Bir kiracıdaki hata diğerlerini etkilemez.

    Returns
    -------
    dict
        ``{"enqueued": int, "tenant_ids": list[str]}``
    """
    logger.info("[shield] Tüm kiracılar için fan-out başlıyor.")

    with SessionLocal() as db:
        tenants = list(db.scalars(select(Tenant)))

    enqueued = 0
    ids = []
    for tenant in tenants:
        tid_str = str(tenant.id)
        check_shield_for_tenant.delay(tid_str)
        enqueued += 1
        ids.append(tid_str)
        logger.debug("[shield] Kuyruğa eklendi: tenant=%s", tid_str)

    logger.info("[shield] %d kiracı kuyruğa eklendi.", enqueued)
    return {"enqueued": enqueued, "tenant_ids": ids}
