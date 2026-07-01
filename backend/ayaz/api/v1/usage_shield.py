"""Kullanım Kalkanı (Usage Shield) API — sürpriz fatura önleme paneli.

Endpoint
--------
GET /usage-shield      — kiracının kullanım durumu, limitler, atıl konektörler
                         ve aktif uyarıları döndürür.

Auth
----
JWT gerekli (``get_current_membership`` bağımlılığı ile).

Kiracı izolasyonu
-----------------
Tüm sorgular ``membership.tenant_id`` ile kısıtlanır; istek gövdesinden
veya sorgu parametresinden gelen hiçbir tenant_id kabul edilmez.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.usage_shield import IDLE_THRESHOLD_DAYS, compute_shield, check_and_notify

router = APIRouter(prefix="/usage-shield", tags=["usage-shield"])


# ── Pydantic şemaları ─────────────────────────────────────────────────────────


class ConnectorInfoOut(BaseModel):
    """Atıl konektör özeti."""

    account_id: uuid.UUID
    platform: str
    display_name: str
    sync_status: str
    last_synced_at: str | None
    reason: str  # "idle" | "error"


class ShieldReportOut(BaseModel):
    """Kullanım kalkanı paneli yanıtı."""

    tenant_id: uuid.UUID

    # Plan bilgisi
    plan_code: str
    plan_name: str

    # Veri kaynağı kullanımı
    data_sources_used: int
    data_sources_max: Any          # int veya "unlimited"
    data_sources_pct: float | None  # None if unlimited

    # Durum bayrakları
    approaching_limit: bool
    at_limit: bool

    # Atıl konektörler
    idle_connectors: list[ConnectorInfoOut]

    # Aktif uyarılar
    active_warnings: list[str]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=ShieldReportOut,
    summary="Kullanım kalkanı paneli — limitler, atıl konektörler, uyarılar",
)
def get_shield(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ShieldReportOut:
    """Kiracının güncel kullanım durumunu ve kalkan uyarılarını döndürür.

    * Plan limitleri ve mevcut kullanım yüzdesi
    * ``approaching_limit`` (≥ %80) ve ``at_limit`` bayrakları
    * Atıl ya da hata durumundaki konektörlerin listesi
    * Aktif uyarı anahtarlarının listesi

    Bu endpoint aynı zamanda eksik bildirimleri Bildirim Merkezine yazar
    (``check_and_notify`` aracılığıyla — idempotent).
    """
    tenant_id = membership.tenant_id

    # Hesapla + bildirim yaz (idempotent)
    result = check_and_notify(db, tenant_id)
    report = result["report"]

    return ShieldReportOut(
        tenant_id=report.tenant_id,
        plan_code=report.plan_code,
        plan_name=report.plan_name,
        data_sources_used=report.data_sources_used,
        data_sources_max=report.data_sources_max,
        data_sources_pct=report.data_sources_pct,
        approaching_limit=report.approaching_limit,
        at_limit=report.at_limit,
        idle_connectors=[
            ConnectorInfoOut(
                account_id=c.account_id,
                platform=c.platform,
                display_name=c.display_name,
                sync_status=c.sync_status,
                last_synced_at=c.last_synced_at,
                reason=c.reason,
            )
            for c in report.idle_connectors
        ],
        active_warnings=report.active_warnings,
    )
