"""Müşteri Yolculuğu / Dönüşüm Hunisi API — 5 aşamalı e-ticaret hunisi.

Kiracının ConversionEvent verilerini beş standart e-ticaret aşamasına
(Sayfa Görüntüleme → Ürün Görüntüleme → Sepete Ekleme → Ödeme Başlatma →
Satın Alma) göre gruplar; her aşamada adet, önceki aşamaya göre dönüşüm
oranı ve düşüş miktarı döner.

    GET /funnel/overview?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

Tarih parametreleri isteğe bağlıdır; verilmezse tüm kayıtlar dahil edilir.
date_from > date_to ise 422 döner.

Kiracı kapsamı: geçerli JWT'deki ``tid`` talebini gerektirir.
Tüm veriler yalnızca isteği yapan kiracıyla sınırlıdır.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.funnel import build_funnel

router = APIRouter(prefix="/funnel", tags=["funnel"])


# ── Yanıt modelleri ───────────────────────────────────────────────────────────


class FunnelPeriod(BaseModel):
    date_from: str | None
    date_to: str | None


class FunnelStage(BaseModel):
    key: str
    label: str
    count: int
    conversion_from_prev_pct: float | None
    dropoff_count: int
    dropoff_pct: float | None
    share_of_entry_pct: float | None


class BiggestDropoff(BaseModel):
    from_label: str
    to_label: str
    dropoff_pct: float


class FunnelOverviewResponse(BaseModel):
    period: FunnelPeriod
    total_events: int
    stages: list[FunnelStage]
    entry_count: int
    final_count: int
    overall_conversion_pct: float
    biggest_dropoff: BiggestDropoff | None


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=FunnelOverviewResponse,
    summary=(
        "Dönüşüm Hunisi — kiracının ConversionEvent verilerini 5 e-ticaret "
        "aşamasına göre gruplar ve her aşamada düşüş oranını döndürür."
    ),
)
def get_funnel_overview(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: str | None = Query(
        default=None,
        description="Dönem başlangıç tarihi (YYYY-MM-DD, dahil). Belirtilmezse tüm kayıtlar.",
    ),
    date_to: str | None = Query(
        default=None,
        description="Dönem bitiş tarihi (YYYY-MM-DD, dahil). Belirtilmezse tüm kayıtlar.",
    ),
) -> FunnelOverviewResponse:
    """Kiracı için Dönüşüm Hunisi özetini döndürür.

    Her aşamada:
    - ``count``: o aşamadaki toplam olay sayısı
    - ``conversion_from_prev_pct``: önceki aşamadan bu aşamaya geçiş yüzdesi
      (ilk aşama için null)
    - ``dropoff_count``: önceki aşamadan düşen olay sayısı
    - ``dropoff_pct``: düşüş yüzdesi (100 - conversion_from_prev_pct)
    - ``share_of_entry_pct``: giriş aşaması sayısına göre bu aşamanın payı

    İstisna fırlatır
    ----------------
    422 — date_from > date_to ise.
    401 — JWT eksik veya geçersizse.
    403 — JWT'deki kiracı talebi aktif bir üyelikle eşleşmiyorsa.
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from, date_to'dan sonra olamaz.",
        )

    result = build_funnel(
        db=db,
        tenant_id=membership.tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    biggest = result["biggest_dropoff"]

    return FunnelOverviewResponse(
        period=FunnelPeriod(**result["period"]),
        total_events=result["total_events"],
        stages=[FunnelStage(**s) for s in result["stages"]],
        entry_count=result["entry_count"],
        final_count=result["final_count"],
        overall_conversion_pct=result["overall_conversion_pct"],
        biggest_dropoff=BiggestDropoff(**biggest) if biggest is not None else None,
    )
