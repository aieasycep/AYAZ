"""KVKK Rıza Yönetim Merkezi (Consent Management Center) API.

Single read-only endpoint that synthesizes existing tracking and consent
infrastructure into a unified KVKK compliance dashboard.

    GET /consent/center
    GET /consent/center?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

Tenant-scoped: requires a valid JWT with ``tid`` claim. All data is filtered
to the requesting tenant — no cross-tenant leakage is possible.

Returns 422 if date_from > date_to.

Response shape
--------------
See ayaz.services.consent_center.build_consent_center for the full dict shape.
Key top-level keys: generated_at, period, summary, signals, destinations,
sources, compliance, audit_trail.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.consent_center import build_consent_center

router = APIRouter(prefix="/consent", tags=["consent"])


@router.get(
    "/center",
    summary=(
        "KVKK Rıza Yönetim Merkezi — rıza oranı, Consent Mode v2 sinyal dökümü, "
        "hedef uyum durumu, KVKK uyum puanı ve denetim izini tek ekranda sunar."
    ),
)
def get_consent_center(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: date | None = Query(
        default=None,
        description=(
            "Dönem başlangıç tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse tüm olaylar dahil edilir."
        ),
    ),
    date_to: date | None = Query(
        default=None,
        description=(
            "Dönem bitiş tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse tüm olaylar dahil edilir."
        ),
    ),
) -> Any:
    """KVKK Rıza Yönetim Merkezi — tek endpoint, eksiksiz rıza tablosu.

    Mevcut izleme altyapısından okuyarak şunları döndürür:
    - Rıza oranı özeti (toplam/rızalı olay sayısı, oran yüzdesi)
    - Consent Mode v2 granüler sinyal dökümü (4 kanonik sinyal)
    - Hedef başına rıza tutumu (Katı / Gevşek)
    - Kaynak başına yapılandırma durumu
    - KVKK uyum puanı (0-100), notu ve 7 maddelik kontrol listesi
    - Son 15 olaydan oluşan denetim izi (en yeni önce)

    Tarih aralığı
    -------------
    Her iki parametre de belirtilmezse kiracının tüm olayları dahil edilir;
    dönem, bulunan min/max event_time değerinden otomatik türetilir.
    Yalnızca biri belirtilirse; serbest uç filtresiz kalır.

    Döndürülen uyumluluk notu
    -------------------------
    score >= 85  →  uyumlu
    score >= 50  →  kismi
    else         →  eksik

    Raises
    ------
    422 — date_from, date_to'dan büyükse.
    401 — JWT eksik veya geçersiz.
    403 — JWT'deki kiracı aktif üyelikle eşleşmiyorsa.
    """
    # Validate date ordering
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from, date_to'dan sonra olamaz.",
        )

    result = build_consent_center(
        db=db,
        tenant_id=membership.tenant_id,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )

    return result
