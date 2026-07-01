"""Bildirim Merkezi veri modeli — Dalga 26.

Multi-tenancy
-------------
Tüm tablolar ``tenant_id`` filtresi içerir; Postgres RLS politikaları
devreye alınana dek her sorgu açıkça ``tenant_id`` ile filtrelenir.

Type/status columns
-------------------
Tüm tip ve durum alanları ``sa.String`` (Mapped[str] aracılığıyla) kullanır.
İzin verilen değerler Pydantic / servis katmanında zorunlu kılınır.

Notification
------------
Bir kiracı için oluşturulan tek bir bildirim kaydı.  ``source_ref`` alanı
aynı kaynaktan birden fazla bildirim oluşturulmasını engellemek için
kullanılan tekilleştirme anahtarıdır.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import GUID as UUID, Base, TimestampMixin, uuid_pk


class Notification(Base, TimestampMixin):
    """Bir kiracı için oluşturulan tek bir bildirim kaydı.

    type değerleri
    --------------
    "insight"    – AI / kural tabanlı tespit motorundan
    "automation" – Otomasyon motoru tetiklemesi
    "system"     – Platform geneli sistem duyurusu

    severity değerleri
    ------------------
    "info"     – dikkat çekici ama acil değil
    "warning"  – bugün ilgilenilmesi önerilir
    "critical" – hemen aksiyon alınmalı

    source_ref
    ----------
    Tekilleştirme anahtarı; örn. ``"insight:<uuid>"``.  Aynı kaynak için
    bir kiracıda yalnızca bir bildirim oluşturulmasını garantiler.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_tenant_id", "tenant_id"),
        Index("ix_notifications_source_ref", "source_ref"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    # "insight" | "automation" | "system"
    type: Mapped[str] = mapped_column(String(32), nullable=False)

    # "info" | "warning" | "critical"
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info"
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Kısa Türkçe başlık",
    )

    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Türkçe açıklama metni",
    )

    # Uygulama içi rota; örn. "/insights"
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Tekilleştirme anahtarı; örn. "insight:<uuid>"
    source_ref: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Dedup key — aynı kaynak için tekrar bildirim üretilmez",
    )

    # Okunma zamanı; None ise bildirim okunmamış demektir
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} type={self.type!r}"
            f" severity={self.severity!r} tenant={self.tenant_id}>"
        )
