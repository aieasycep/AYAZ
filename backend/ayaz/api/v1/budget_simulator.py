"""Bütçe Senaryo Simülatörü API — M15.

Tenant'a özgü uç noktalar (JWT ile ``tid`` iddiası gerektirir):

    GET  /budget-simulator/baseline?lookback_days=
        Son N günün kanal metriklerini ve verimlilik katsayılarını döndürür.
        lookback_days: 7–90 arasında sıkıştırılır, varsayılan 30.

    POST /budget-simulator/simulate
        Verilen kanal→bütçe tahsislerine göre senaryo analizi yapar.
        Tarihsel verimlilikten doğrusal projeksiyon üretir.

Tüm tutarlar düz float olarak döndürülür.
Oran değerleri (cpc, cvr, roas vb.) 2–4 ondalık basamakla yuvarlanır.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.budget_simulator import get_baseline, simulate

router = APIRouter(prefix="/budget-simulator", tags=["budget-simulator"])

# ── lookback_days sınır değerleri ─────────────────────────────────────────────

_LOOKBACK_MIN = 7
_LOOKBACK_MAX = 90
_LOOKBACK_DEFAULT = 30


def _clamp_lookback(v: int) -> int:
    """lookback_days değerini 7–90 aralığına sıkıştırır."""
    return max(_LOOKBACK_MIN, min(_LOOKBACK_MAX, v))


# ── Pydantic şemaları ──────────────────────────────────────────────────────────


class SimulateRequest(BaseModel):
    """POST /budget-simulator/simulate istek gövdesi."""

    allocations: dict[str, float]
    lookback_days: int = _LOOKBACK_DEFAULT

    @field_validator("allocations")
    @classmethod
    def allocations_not_empty(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError(
                "allocations boş olamaz — en az bir kanal bütçesi gerekli."
            )
        for key, val in v.items():
            if val < 0:
                raise ValueError(
                    f"Negatif bütçe geçersizdir: {key!r} = {val}. "
                    "Tüm kanal bütçeleri 0 veya daha büyük olmalıdır."
                )
        return v

    @field_validator("lookback_days")
    @classmethod
    def clamp_lookback(cls, v: int) -> int:
        return _clamp_lookback(v)


# ── Uç noktalar ───────────────────────────────────────────────────────────────


@router.get(
    "/baseline",
    summary=(
        "Baz Çizgisi — son N günün kanal metriklerini ve verimlilik katsayılarını döndürür. "
        "lookback_days 7–90 arasında sıkıştırılır."
    ),
)
def get_baseline_endpoint(
    lookback_days: int = Query(
        default=_LOOKBACK_DEFAULT,
        ge=_LOOKBACK_MIN,
        le=_LOOKBACK_MAX,
        description=(
            "Geriye bakış penceresi (gün). "
            f"Minimum {_LOOKBACK_MIN}, maksimum {_LOOKBACK_MAX}. Varsayılan {_LOOKBACK_DEFAULT}."
        ),
    ),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Son ``lookback_days`` günün kanal bazlı verimlilik baz çizgisini döndürür.

    Her kanal için şunları içerir: harcama, gösterim, tıklama, dönüşüm,
    dönüşüm değeri, cpc, cpm, cvr, roas, aov, cpa ve harcama payı.

    Simülatör senaryo analizinin ön adımı olarak kullanılır.

    Hata kodları
    ------------
    401 — JWT eksik veya geçersiz.
    403 — Kiracı iddiası üyelikle eşleşmiyor.
    """
    clamped = _clamp_lookback(lookback_days)
    return get_baseline(db, membership.tenant_id, lookback_days=clamped)


@router.post(
    "/simulate",
    summary=(
        "Senaryo Simülasyonu — verilen kanal bütçe tahsislerine göre "
        "tıklama/gösterim/dönüşüm/gelir/ROAS projeksiyon hesaplar."
    ),
)
def simulate_endpoint(
    body: SimulateRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Kanal tahsislerine göre bütçe senaryo analizi yapar.

    Tarihsel verimlilik katsayıları (son ``lookback_days`` gün) baz alınarak
    her kanal için beklenen tıklama, gösterim, dönüşüm, gelir ve ROAS
    doğrusal olarak projekte edilir.

    Senaryo sonuçları şunları içerir:
    * Her kanal için projeksiyon değerleri ve baz çizgisinden fark.
    * Toplam projeksiyon ve baz totalleri.
    * KPI bazında delta yüzdeleri (projeksiyon vs gerçekleşen baz).
    * Türkçe varsayım listesi.

    Doğrusal projeksiyon varsayımı belgelerde belirtilir — büyük ölçek
    değişimlerinde gerçek sonuç azalan getiriler nedeniyle farklılaşabilir.

    Hata kodları
    ------------
    401 — JWT eksik veya geçersiz.
    403 — Kiracı iddiası üyelikle eşleşmiyor.
    422 — allocations boşsa veya herhangi bir bütçe değeri negatifse.
    """
    try:
        result = simulate(
            db,
            membership.tenant_id,
            body.allocations,
            lookback_days=body.lookback_days,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return result
