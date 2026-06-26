"""Ad Management API — M6, phase 1 (READ-ONLY).

Endpoints
---------
GET /api/v1/ads/campaigns
    Campaign list with aggregated metrics.  Supports date range, channel/status
    filtering, and sort.

GET /api/v1/ads/campaigns/{campaign_id}
    Detail view: campaign totals + daily timeseries for the given date range.

GET /api/v1/ads/recommendations
    Per-campaign actionable recommendations (Turkish) produced by reusing the
    insights detectors at campaign granularity.  READ-ONLY — suggestions only.

POST /api/v1/ads/campaigns/{campaign_id}/actions  (501 stub)
    Intentionally not implemented in M6 phase 1.  Returns 501 with a Turkish
    message so the frontend can show the affordance.  Write/execute paths are
    planned for M6 phase 2.

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant scope is resolved via
``get_current_membership`` — every query explicitly filters on
``membership.tenant_id`` to enforce isolation until Postgres RLS is active.

Wiring note for team lead
-------------------------
This module is NOT imported in main.py yet.  To activate:

    from ayaz.api.v1 import ads as ads_router
    app.include_router(ads_router.router, prefix=_PREFIX)
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.ads import (
    campaign_detail,
    campaign_recommendations,
    list_campaigns,
)

router = APIRouter(prefix="/ads", tags=["ads"])


# ── Response schemas ──────────────────────────────────────────────────────────


class CampaignMetrics(BaseModel):
    """Aggregated metrics for one campaign over the requested date range."""

    campaign_id: str
    campaign_name: str
    channel: str
    status: str  # "active" | "paused"  — derived from spend > 0
    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class DailyMetricsPoint(BaseModel):
    """One row in the daily timeseries for a campaign."""

    date: str
    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class CampaignTotals(BaseModel):
    """Period totals for the campaign detail view."""

    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class CampaignDetailResponse(BaseModel):
    """Full detail for a single campaign: totals + daily timeseries."""

    campaign_id: str
    campaign_name: str
    channel: str
    status: str
    totals: CampaignTotals
    timeseries: list[DailyMetricsPoint]


class CampaignRecommendation(BaseModel):
    """A single actionable recommendation for a campaign (READ-ONLY)."""

    campaign_id: str
    campaign_name: str
    channel: str
    category: str
    severity: str      # "info" | "warning" | "critical"
    score: float
    metric: str
    message: str       # Turkish narrative
    suggested_action: str   # Turkish action label — M6 phase 2 will execute this
    period_start: str
    period_end: str
    data: dict[str, Any]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/campaigns",
    response_model=list[CampaignMetrics],
    summary="Cross-channel campaign list with aggregated metrics",
)
def get_campaigns(
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    channel: Annotated[
        str | None,
        Query(description="Filter by channel key (e.g. 'google_ads', 'meta_ads')"),
    ] = None,
    campaign_status: Annotated[
        str | None,
        Query(alias="status", description="Filter by derived status: 'active' | 'paused'"),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            description=(
                "Sort column. One of: spend | roas | impressions | clicks | "
                "conversions | conversion_value | ctr | cpc | cpa | "
                "campaign_name | channel. Default: spend (descending)."
            )
        ),
    ] = None,
    sort_asc: Annotated[
        bool,
        Query(description="Set true for ascending sort (default false = descending)"),
    ] = False,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[CampaignMetrics]:
    """Return aggregated metrics per campaign for the requested date range.

    Campaigns with no data in the range are excluded.  The ``status`` field is
    derived: a campaign is "active" when it had spend > 0 in the range, else
    "paused".  This is an approximation until a platform status sync is
    implemented (M6 phase 2).
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    rows = list_campaigns(
        db,
        membership.tenant_id,
        date_from,
        date_to,
        channel=channel,
        status=campaign_status,
        sort=sort,
        sort_desc=not sort_asc,
    )
    return [CampaignMetrics(**r) for r in rows]


# ── Campaign CSV export (declared BEFORE /{campaign_id} to avoid path conflict) ──

# Turkish column headers for campaign CSV.
_CAMPAIGN_CSV_HEADERS = [
    "Kampanya ID",
    "Kampanya Adı",
    "Kanal",
    "Durum",
    "Harcama",
    "Gösterim",
    "Tıklama",
    "Dönüşüm",
    "Dönüşüm Değeri",
    "CTR",
    "CPC",
    "CPA",
    "ROAS",
]


def _campaign_to_csv_row(c: dict) -> list:
    return [
        c["campaign_id"],
        c["campaign_name"],
        c["channel"],
        c["status"],
        round(c["spend"], 4),
        round(c["impressions"], 4),
        round(c["clicks"], 4),
        round(c["conversions"], 4),
        round(c["conversion_value"], 4),
        round(c["ctr"], 4),
        round(c["cpc"], 4),
        round(c["cpa"], 4),
        round(c["roas"], 4),
    ]


@router.get(
    "/campaigns/export",
    summary="Export campaign list as CSV (Turkish headers, UTF-8 BOM)",
    response_class=StreamingResponse,
)
def export_campaigns(
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    channel: Annotated[
        str | None,
        Query(description="Filter by channel key (e.g. 'google_ads', 'meta_ads')"),
    ] = None,
    campaign_status: Annotated[
        str | None,
        Query(alias="status", description="Filter by derived status: 'active' | 'paused'"),
    ] = None,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> StreamingResponse:
    """Return a UTF-8 BOM CSV of all campaigns matching the filters.

    Mirrors the columns from GET /api/v1/ads/campaigns.
    Content-Disposition filename: ``ayaz-campaigns-<from>_<to>.csv``.
    The BOM (\\ufeff) ensures Excel correctly decodes Turkish characters.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    rows = list_campaigns(
        db,
        membership.tenant_id,
        date_from,
        date_to,
        channel=channel,
        status=campaign_status,
        sort="spend",
        sort_desc=True,
    )

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(_CAMPAIGN_CSV_HEADERS)
    for r in rows:
        writer.writerow(_campaign_to_csv_row(r))

    filename = f"ayaz-campaigns-{date_from}_{date_to}.csv"
    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignDetailResponse,
    summary="Campaign detail: totals + daily timeseries",
)
def get_campaign_detail(
    campaign_id: uuid.UUID,
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> CampaignDetailResponse:
    """Return period totals and a daily timeseries for a single campaign.

    Returns 404 when the campaign does not exist in the tenant's scope.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    detail = campaign_detail(
        db,
        membership.tenant_id,
        campaign_id,
        date_from,
        date_to,
    )
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="Kampanya bulunamadı.",  # "Campaign not found."
        )

    return CampaignDetailResponse(
        campaign_id=detail["campaign_id"],
        campaign_name=detail["campaign_name"],
        channel=detail["channel"],
        status=detail["status"],
        totals=CampaignTotals(**detail["totals"]),
        timeseries=[DailyMetricsPoint(**p) for p in detail["timeseries"]],
    )


@router.get(
    "/recommendations",
    response_model=list[CampaignRecommendation],
    summary="Per-campaign actionable recommendations (read-only, Turkish)",
)
def get_recommendations(
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    lookback_days: Annotated[
        int,
        Query(
            ge=7,
            le=90,
            description=(
                "Calendar days of history to analyse (default 30). "
                "A larger window makes anomaly detection more reliable."
            ),
        ),
    ] = 30,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[CampaignRecommendation]:
    """Run the insights detectors at campaign granularity and return suggestions.

    Recommendations are READ-ONLY.  The ``suggested_action`` field names what
    the user could do; the write/execute path is M6 phase 2.

    Results are sorted by score descending (most urgent first).
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    recs = campaign_recommendations(
        db,
        membership.tenant_id,
        date_from,
        date_to,
        lookback_days=lookback_days,
    )
    return [CampaignRecommendation(**r) for r in recs]


# ── M6 phase 2 stub ───────────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/actions",
    status_code=501,
    summary="[Stub] Execute a campaign action — M6 phase 2",
    tags=["ads"],
)
def campaign_action_stub(
    campaign_id: uuid.UUID,
    _membership: Membership = Depends(get_current_membership),
) -> dict[str, str]:
    """Placeholder for write/execute actions (pause, budget change, etc.).

    This endpoint intentionally returns 501 Not Implemented.
    Write/execute functionality is planned for M6 phase 2.
    The endpoint is stubbed so the frontend can show the affordance today.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Bu özellik henüz hazır değil — M6 faz 2'de eklenecek.  "  # "Not implemented — M6 phase 2."
            "Kampanya aksiyonları (duraklat, bütçe değiştir) yakında kullanılabilir."
        ),
    )
