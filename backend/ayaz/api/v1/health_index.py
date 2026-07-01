"""Pazarlama Sağlık Endeksi API.

CMO / Yönetim personası için tek bir stratejik 0-100 skoru sunar;
mevcut 6 modülden (audit, benchmark, consent, funnel, goals, budget)
gelen alt skorları bütünleşik bir boyut listesinde raporlar.

    GET /health-index

Kimlik doğrulama gerektirir; kiracı JWT'deki ``tid`` claim'inden alınır.
Yanıt kiracıya özeldir — çapraz kiracı veri sızıntısı mümkün değildir.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.health_index import build_health_index

router = APIRouter(prefix="/health-index", tags=["health-index"])


# ── Yanıt modelleri ────────────────────────────────────────────────────────────


class HealthDimension(BaseModel):
    key: str
    label: str
    score: int | None
    grade: str | None
    status: str  # "ok" | "veri_yok"
    detail: str
    href: str
    weight: int


class HealthSummary(BaseModel):
    strong_count: int
    weak_count: int
    scored_count: int


class HealthIndexResponse(BaseModel):
    generated_at: str
    overall_score: int
    overall_grade: str
    dimensions: list[HealthDimension]
    summary: HealthSummary


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=HealthIndexResponse,
    summary=(
        "Pazarlama Sağlık Endeksi — 6 boyuttan oluşan 0-100 stratejik skor. "
        "CMO ve üst yönetim için hesap sağlığı, sektör konumu, KVKK uyumu, "
        "dönüşüm, hedef ilerleme ve bütçe disiplini boyutlarını tek bir endekste toplar."
    ),
)
def get_health_index(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> HealthIndexResponse:
    """Pazarlama Sağlık Endeksi'ni döndürür.

    Her boyut için 0-100 alt skor, Türkçe derece (mukemmel/iyi/orta/zayif)
    ve kısa bir Türkçe açıklama içerir.  Kaynak serviste veri yoksa boyut
    skoru None ve statüsü "veri_yok" olarak raporlanır; bu boyutlar genel
    ortalamanın dışında tutulur.
    """
    result = build_health_index(db, membership.tenant_id)
    return HealthIndexResponse(
        generated_at=result["generated_at"],
        overall_score=result["overall_score"],
        overall_grade=result["overall_grade"],
        dimensions=[HealthDimension(**d) for d in result["dimensions"]],
        summary=HealthSummary(**result["summary"]),
    )
