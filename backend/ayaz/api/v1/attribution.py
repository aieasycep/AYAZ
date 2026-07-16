"""Attribution (kaynak-mutabakatı) API.

GET /api/v1/attribution/summary?days=N
    Reklam platformlarının kendi-raporladığı dönüşüm/gelir ile GA4'ün
    ölçtüğü gerçek dönüşüm/geliri yan yana gösterir; ikisini asla kör
    toplamaz. ``inflation_factor`` platformların GA4'e göre ne kadar
    "şiştiğini" nicelleştirir.

Auth: mevcut ``get_current_membership`` deseni (JWT + tenant izolasyonu) —
diğer dashboard/executive endpoint'leriyle aynı.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.attribution import build_attribution_summary

router = APIRouter(prefix="/attribution", tags=["attribution"])


# ── Response schemas ──────────────────────────────────────────────────────────


class AttributionChannelRow(BaseModel):
    """Tek bir kanalın kendi (çapraz-kanal karışımı OLMAYAN) rakamları."""

    key: str
    label: str
    source_type: str  # "ad" | "analytics"
    spend: float
    conversions: float
    conversion_value: float
    roas: float


class AttributionDataQuality(BaseModel):
    """GA4 bağlantısı ve ücretli-kanal izlemesi hakkında veri-kalitesi bayrakları."""

    ga4_connected: bool
    ga4_paid_tracked: bool
    note: str | None


class AttributionSummaryResponse(BaseModel):
    """Reklam-platformu vs GA4 kaynak-mutabakatı özeti."""

    date_from: date
    date_to: date
    platform_claimed_conversions: float
    platform_claimed_revenue: float
    ga4_conversions: float
    ga4_revenue: float
    ga4_paid_conversions: float
    ga4_paid_revenue: float
    inflation_factor: float | None
    ad_spend: float
    blended_roas: float
    mer: float
    data_quality: AttributionDataQuality
    channels: list[AttributionChannelRow]


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=AttributionSummaryResponse,
    summary="Reklam-platformu vs GA4 kaynak-mutabakatı özeti",
)
def attribution_summary(
    days: Annotated[
        int,
        Query(description="Kaç günlük geriye dönük pencere (1-90)", ge=1, le=90),
    ] = 30,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AttributionSummaryResponse:
    """Seçilen dönemde reklam platformlarının kendi-iddia ettiği dönüşüm/gelir
    ile GA4'ün ölçtüğü gerçek dönüşüm/geliri yan yana döndürür.

    Neden gerekli
    -------------
    Google Ads / Meta Ads gibi platformlar kendi attribution modelleriyle
    (genelde son-tıklama, kendi penceresi) dönüşüm raporlar — bu sayılar
    genelde GA4'ün ölçtüğünden YÜKSEKTİR (platformlar kendi başarısını öne
    çıkarma eğilimindedir). Bu iki sayıyı KÖR TOPLAMAK (eski panel
    davranışı) manşet dönüşümü 2-3× şişirir. Bu endpoint ikisini ayrı ayrı
    gösterip ``inflation_factor`` ile farkı nicelleştirir.

    GA4'ün ``sessionDefaultChannelGroup`` boyutu organik/direkt/e-posta gibi
    ücretsiz kanalları da içerir — bu yüzden reklam platformuyla elma-elma
    karşılaştırma için GA4 TOPLAMI değil, GA4'ün YALNIZ ücretli kanal
    gruplarına (Paid Search/Paid Social/...) düşen dilimi (``ga4_paid_*``)
    kullanılır. ``ga4_conversions``/``ga4_revenue`` toplamı ayrı bir alan
    (``mer``) için saklanır.

    ``inflation_factor`` = ``platform_claimed_conversions / ga4_paid_conversions``.
    GA4 bağlı değilse veya bu dönemde ücretli-kanal GA4 dönüşümü sıfırsa
    ``None`` döner (karşılaştırma anlamsız — sıfıra bölme yok); bu durumda
    ``data_quality.note`` doldurulur.

    ``blended_roas`` ("Gerçek/Ücretli ROAS") = ücretli-GA4 geliri ÷ yalnız
    reklam harcaması. Ücretli-GA4 yoksa/sıfırsa 0 döner — bu endpoint'in
    amacı "gerçek" resmi göstermek olduğundan, dashboard ``/summary``
    endpoint'indeki geriye-uyumlu ad-only fallback burada UYGULANMAZ.

    ``mer`` (Media Efficiency Ratio) = TOPLAM GA4 geliri ÷ reklam harcaması —
    ``blended_roas`` ile karıştırılmamalı; tüm-işletme verimliliği sinyalidir.

    Tenant izolasyonu: tüm sorgular ``membership.tenant_id`` ile filtrelenir.
    """
    tenant_id = membership.tenant_id
    today = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=days - 1)
    date_to = today

    result = build_attribution_summary(db, tenant_id, date_from, date_to)

    return AttributionSummaryResponse(
        date_from=date.fromisoformat(result["date_from"]),
        date_to=date.fromisoformat(result["date_to"]),
        platform_claimed_conversions=result["platform_claimed_conversions"],
        platform_claimed_revenue=result["platform_claimed_revenue"],
        ga4_conversions=result["ga4_conversions"],
        ga4_revenue=result["ga4_revenue"],
        ga4_paid_conversions=result["ga4_paid_conversions"],
        ga4_paid_revenue=result["ga4_paid_revenue"],
        inflation_factor=result["inflation_factor"],
        ad_spend=result["ad_spend"],
        blended_roas=result["blended_roas"],
        mer=result["mer"],
        data_quality=AttributionDataQuality(**result["data_quality"]),
        channels=[AttributionChannelRow(**c) for c in result["channels"]],
    )
