"""Bildirim Merkezi API — Dalga 26.

Endpoint'ler
------------
GET  /api/v1/notifications
    Kiracının bildirimlerini listeler.  ``sync_from_insights`` ile gecikmeli
    üretim tetiklenir; her çağrıda feed güncel kalır.

GET  /api/v1/notifications/unread-count
    Okunmamış bildirim sayısını döndürür.  ``sync_from_insights`` tetiklenir.

POST /api/v1/notifications/{id}/read
    Tek bir bildirimi okundu olarak işaretler.  Yanlış kiracıda 404 döner.

POST /api/v1/notifications/read-all
    Kiracının tüm okunmamış bildirimlerini okundu olarak işaretler.

Auth
----
Tüm endpoint'ler geçerli JWT (Bearer token) gerektirir.  Kiracı bağlamı
``get_current_membership`` üzerinden çözümlenir; her sorgu açıkça
``membership.tenant_id`` ile filtrelenir.

NotificationOut
---------------
``read`` alanı ``read_at != None`` koşulundan türetilir; ORM nesnesinin
kendisinde saklanmaz.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services import notifications_center as nc

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── Response şeması ───────────────────────────────────────────────────────────


class NotificationOut(BaseModel):
    """Bir Notification satırının dış temsili."""

    id: str
    type: str
    severity: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: Any  # datetime — Pydantic tarafından ISO 8601 string olarak serileştirilir

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, notif: Any) -> "NotificationOut":
        """ORM nesnesinden NotificationOut oluşturur."""
        return cls(
            id=str(notif.id),
            type=notif.type,
            severity=notif.severity,
            title=notif.title,
            body=notif.body,
            link=notif.link,
            read=notif.read_at is not None,
            created_at=notif.created_at,
        )


# ── Endpoint'ler ──────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[NotificationOut],
    summary="Kiracının bildirimlerini listeler",
)
def list_notifications(
    unread_only: Annotated[
        bool,
        Query(description="True ise yalnızca okunmamış bildirimler döner"),
    ] = False,
    limit: Annotated[
        int,
        Query(description="Maksimum sonuç sayısı (1–200)", ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[NotificationOut]:
    """Kiracının bildirimlerini döndürür (en yeni önce).

    Her çağrıda ``sync_from_insights`` tetiklenerek feed güncel tutulur.
    Aynı kaynaktan yinelenen bildirim oluşturulmaz (``source_ref`` tekilleştirmesi).
    """
    tenant_id = membership.tenant_id
    nc.sync_from_insights(db, tenant_id)
    rows = nc.list_notifications(db, tenant_id, unread_only=unread_only, limit=limit)
    return [NotificationOut.from_orm_row(r) for r in rows]


@router.get(
    "/unread-count",
    summary="Okunmamış bildirim sayısı",
)
def get_unread_count(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, int]:
    """Kiracının okunmamış bildirim sayısını döndürür.

    ``sync_from_insights`` ile feed güncel tutulur.
    """
    tenant_id = membership.tenant_id
    nc.sync_from_insights(db, tenant_id)
    count = nc.unread_count(db, tenant_id)
    return {"count": count}


@router.post(
    "/{notification_id}/read",
    response_model=NotificationOut,
    summary="Tek bir bildirimi okundu olarak işaretle",
)
def mark_one_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> NotificationOut:
    """Belirtilen bildirimi okundu olarak işaretler ve güncel kaydı döndürür.

    Bildirim bulunamazsa veya farklı kiracıya aitse 404 döner.
    """
    try:
        notif = nc.mark_read(db, membership.tenant_id, notification_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bildirim bulunamadı.",
        )
    return NotificationOut.from_orm_row(notif)


@router.post(
    "/read-all",
    summary="Tüm okunmamış bildirimleri okundu olarak işaretle",
)
def mark_all_read(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, int]:
    """Kiracının tüm okunmamış bildirimlerini okundu olarak işaretler."""
    updated = nc.mark_all_read(db, membership.tenant_id)
    return {"updated": updated}
