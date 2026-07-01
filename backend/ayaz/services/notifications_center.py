"""Bildirim Merkezi servis katmanı — Dalga 26.

Bu dosya, varolan ``ayaz/services/notifications.py`` (e-posta/Slack stub)
ile çakışmamak için farklı bir isim almıştır.

Mimari
------
Bildirimler *gecikmeli üretim* (lazy generation) modeliyle çalışır:
kullanıcı liste endpoint'ini her çağırdığında ``sync_from_insights`` tetiklenir
ve mevcut Insight'lardan henüz bildirim oluşturulmamış olanlar için
kayıt üretilir.  ``source_ref`` alanı tekilleştirme anahtarı olarak kullanılır;
aynı kaynak için birden fazla bildirim oluşturulmaz.

Kiracı izolasyonu
-----------------
Her sorgu ``tenant_id`` filtresi içerir.  Başka kiracı verisi asla sızdırılmaz.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.insights import Insight
from ayaz.models.notifications import Notification


# ── İçsel yardımcı ────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """UTC şimdiki zamanı döndür (timezone-aware)."""
    return datetime.now(timezone.utc)


# ── Ana servis fonksiyonları ──────────────────────────────────────────────────


def sync_from_insights(
    db: Session,
    tenant_id: Any,
    limit: int = 100,
) -> int:
    """Son Insight'lardan henüz bildirimi olmayan kayıtlar için Notification oluşturur.

    Her ``Insight`` için ``source_ref = "insight:<insight.id>"`` kullanılarak
    tekilleştirme yapılır; varolan bir bildirim ikinci kez oluşturulmaz.

    Parameters
    ----------
    db:
        SQLAlchemy Session (yazma yetkisi gerekli).
    tenant_id:
        Kiracı UUID — tüm sorgular bu değerle kısıtlanır.
    limit:
        İşlenecek en fazla Insight sayısı (en yeni kayıtlar alınır).

    Returns
    -------
    Oluşturulan yeni bildirim sayısı.
    """
    # Son `limit` Insight'ı al (en yeni önce)
    recent_insights = db.scalars(
        select(Insight)
        .where(Insight.tenant_id == tenant_id)
        .order_by(Insight.created_at.desc())
        .limit(limit)
    ).all()

    if not recent_insights:
        return 0

    # Mevcut source_ref'leri tek sorguda al (N+1 önlemi)
    insight_refs = [f"insight:{ins.id}" for ins in recent_insights]
    existing_refs = set(
        db.scalars(
            select(Notification.source_ref).where(
                Notification.tenant_id == tenant_id,
                Notification.source_ref.in_(insight_refs),
            )
        ).all()
    )

    created = 0
    for ins in recent_insights:
        ref = f"insight:{ins.id}"
        if ref in existing_refs:
            continue

        notif = Notification(
            tenant_id=tenant_id,
            type="insight",
            severity=ins.severity,
            title=ins.title,
            body=ins.body,
            link="/insights",
            source_ref=ref,
        )
        db.add(notif)
        created += 1

    if created:
        db.commit()

    return created


def list_notifications(
    db: Session,
    tenant_id: Any,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    """Kiracıya ait bildirimleri döndürür.

    Parameters
    ----------
    db:
        SQLAlchemy Session (salt okunur sorgu).
    tenant_id:
        Kiracı UUID — her sorgu bu değerle kısıtlanır.
    unread_only:
        True ise yalnızca ``read_at IS NULL`` kayıtlar döner.
    limit:
        Döndürülecek maksimum kayıt sayısı.

    Returns
    -------
    Notification ORM nesnelerinin listesi (en yeni önce sıralı).
    """
    stmt = (
        select(Notification)
        .where(Notification.tenant_id == tenant_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    return list(db.scalars(stmt).all())


def unread_count(db: Session, tenant_id: Any) -> int:
    """Kiracının okunmamış bildirim sayısını döndürür."""
    from sqlalchemy import func

    result = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == tenant_id,
            Notification.read_at.is_(None),
        )
    )
    return result or 0


def mark_read(
    db: Session,
    tenant_id: Any,
    notification_id: uuid.UUID,
) -> Notification:
    """Bir bildirimi okundu olarak işaretler.

    Parameters
    ----------
    db:
        SQLAlchemy Session (yazma yetkisi gerekli).
    tenant_id:
        Kiracı UUID — yanlış kiracı erişimini engeller.
    notification_id:
        Okundu olarak işaretlenecek bildirim ID'si.

    Returns
    -------
    Güncellenmiş Notification nesnesi.

    Raises
    ------
    KeyError
        Bildirim bulunamadığında veya farklı kiracıya aitse.
    """
    notif = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
        )
    )
    if notif is None:
        raise KeyError(notification_id)

    if notif.read_at is None:
        notif.read_at = _utcnow()
        db.flush()
        db.refresh(notif)
        db.commit()

    return notif


def mark_all_read(db: Session, tenant_id: Any) -> int:
    """Kiracının tüm okunmamış bildirimlerini okundu olarak işaretler.

    Parameters
    ----------
    db:
        SQLAlchemy Session (yazma yetkisi gerekli).
    tenant_id:
        Kiracı UUID — yalnızca bu kiracının bildirimleri güncellenir.

    Returns
    -------
    Güncellenen bildirim sayısı.
    """
    unread_notifs = db.scalars(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.read_at.is_(None),
        )
    ).all()

    now = _utcnow()
    for notif in unread_notifs:
        notif.read_at = now

    count = len(unread_notifs)
    if count:
        db.flush()
        db.commit()

    return count
