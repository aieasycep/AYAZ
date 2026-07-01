"""Pazarlama Fırsat Takvimi (Marketing Opportunity Calendar) API — Dalga 80.

Türkiye'nin önemli ticari/sezonsal/resmi/dini tarihlerini ve her fırsat için
hazırlık durumunu (içerik planlandı mı? bütçe var mı?) döndüren salt okunur
endpoint.  TR pazarına özgü bir farklılaştırıcıdır.

    GET /marketing-calendar/opportunities?horizon_months=6

Kiracı kapsamlıdır: ``tid`` talibini içeren geçerli bir JWT gerektirir.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.marketing_calendar import build_opportunity_calendar

router = APIRouter(prefix="/marketing-calendar", tags=["marketing-calendar"])


# ── Response modelleri ────────────────────────────────────────────────────────


class CalendarReadiness(BaseModel):
    content_scheduled: int
    budget_planned: bool


class SuggestedAction(BaseModel):
    label: str
    href: str


class OpportunityItem(BaseModel):
    key: str
    date: str
    name: str
    category: str
    commerce_weight: str
    is_approximate: bool
    days_until: int
    lead_time_days: int
    status: str
    marketing_tip: str
    readiness: CalendarReadiness
    suggested_actions: list[SuggestedAction]


class CalendarSummary(BaseModel):
    total: int
    urgent: int
    this_month: int
    high_weight: int


class OpportunityCalendarResponse(BaseModel):
    as_of: str
    horizon_months: int
    summary: CalendarSummary
    opportunities: list[OpportunityItem]


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get(
    "/opportunities",
    response_model=OpportunityCalendarResponse,
    summary=(
        "Pazarlama Fırsat Takvimi — Türkiye'nin önemli ticari/sezonsal/resmi/dini "
        "tarihlerini ve her fırsat için hazırlık durumunu (içerik planlandı mı? "
        "bütçe var mı?) döndürür.  Fırsatlar tarihe göre artan sırada listelenir."
    ),
)
def get_opportunities(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    horizon_months: int = Query(
        default=6,
        ge=1,
        le=12,
        description=(
            "Kaç aylık ufuk sorgulanacak (1-12; varsayılan 6). "
            "Bugünden itibaren bu kadar ay içindeki fırsatlar listelenir."
        ),
    ),
) -> OpportunityCalendarResponse:
    """Kiracıya özel pazarlama fırsat takvimini döndür.

    Türkiye'nin önemli ticari, sezonsal, resmi ve dini tarihlerini derler;
    her fırsat için:
    - Tarihe kaç gün kaldığını (days_until)
    - Hazırlık durumunu (o tarihe yakın içerik var mı? o ayın bütçesi planlandı mı?)
    - Aciliyet statüsünü (urgent / upcoming)
    - Önerilen eylemleri (/content, /ad-studio, /planning linkleriyle)
    hesaplar.

    Fırsatlar tarihe göre artan sırada döner.

    Dini günler (Ramazan, Bayram) yaklaşık tarih içerebilir (is_approximate=True).

    Raises
    ------
    401 — JWT eksik veya geçersizse.
    403 — JWT'deki tenant_id geçerli bir üyeliğe karşılık gelmiyorsa.
    422 — horizon_months 1-12 aralığı dışındaysa.
    """
    as_of: date = datetime.now(timezone.utc).date()

    result = build_opportunity_calendar(
        db=db,
        tenant_id=membership.tenant_id,
        as_of=as_of,
        horizon_months=horizon_months,
    )

    return OpportunityCalendarResponse(
        as_of=result["as_of"],
        horizon_months=result["horizon_months"],
        summary=CalendarSummary(**result["summary"]),
        opportunities=[
            OpportunityItem(
                **{
                    **opp,
                    "readiness": CalendarReadiness(**opp["readiness"]),
                    "suggested_actions": [
                        SuggestedAction(**a) for a in opp["suggested_actions"]
                    ],
                }
            )
            for opp in result["opportunities"]
        ],
    )
