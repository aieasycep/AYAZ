"""Creative / Ad-level Performance Analysis API.

Endpoints
---------
GET /api/v1/creatives/performance?date_from=&date_to=&sort=
    Ad-level aggregated metrics with top/bottom creative analysis and Turkish
    commentary grounded in real numbers.

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant scope is resolved via
``get_current_membership`` — every query explicitly filters on
``membership.tenant_id`` to enforce isolation until Postgres RLS is active.

Wiring note for team lead
-------------------------
This module is NOT imported in main.py yet.  To activate:

    from ayaz.api.v1 import creatives as creatives_router
    app.include_router(creatives_router.router, prefix=_PREFIX)
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.creatives import ad_performance

router = APIRouter(prefix="/creatives", tags=["creatives"])


# ── Response schemas ──────────────────────────────────────────────────────────


class AdMetrics(BaseModel):
    """Aggregated metrics for one ad creative over the requested date range."""

    ad_id: str
    ad_name: str
    campaign_id: str
    campaign_name: str
    channel: str
    spend: float
    impressions: float
    clicks: float
    conversions: float
    conversion_value: float
    roas: float
    ctr: float
    cpc: float
    cpa: float


class AdPerformanceResponse(BaseModel):
    """Creative performance response: full ad list, top/bottom picks, commentary."""

    ads: list[AdMetrics]
    top: list[AdMetrics]       # Up to 3 best ROAS
    bottom: list[AdMetrics]    # Up to 3 worst ROAS among spenders
    commentary: str            # Deterministic Turkish narrative


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/performance",
    response_model=AdPerformanceResponse,
    summary="Ad-level creative performance with top/bottom analysis (Turkish commentary)",
)
def get_ad_performance(
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    sort: Annotated[
        str | None,
        Query(
            description=(
                "Sort column for the ads list. One of: spend | roas | impressions | "
                "clicks | conversions | conversion_value | ctr | cpc | cpa | "
                "ad_name | campaign_name | channel. Default: spend (descending)."
            )
        ),
    ] = None,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AdPerformanceResponse:
    """Return aggregated metrics per ad creative for the requested date range.

    Excludes sentinel '(not set)' ad rows (campaign-level data without an actual
    creative).  Results include:

    - ``ads``: full list sorted by ``sort`` descending.
    - ``top``: 3 best-ROAS ads (among ads with spend > 0).
    - ``bottom``: 3 worst-ROAS ads among spenders — highlights budget waste.
    - ``commentary``: Turkish narrative naming the best and worst performers
      grounded in the actual numbers.  No fabrication.

    Returns 422 when date_from > date_to.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from, date_to'dan büyük olamaz.",
        )

    result = ad_performance(
        db,
        membership.tenant_id,
        date_from,
        date_to,
        sort=sort or "spend",
    )

    return AdPerformanceResponse(
        ads=[AdMetrics(**a) for a in result["ads"]],
        top=[AdMetrics(**a) for a in result["top"]],
        bottom=[AdMetrics(**a) for a in result["bottom"]],
        commentary=result["commentary"],
    )


# ── CSV export ────────────────────────────────────────────────────────────────

# Turkish column headers for ad-level creative CSV.
_CREATIVE_CSV_HEADERS = [
    "Reklam ID",
    "Reklam Adı",
    "Kampanya ID",
    "Kampanya Adı",
    "Kanal",
    "Harcama",
    "Gösterim",
    "Tıklama",
    "Dönüşüm",
    "Dönüşüm Değeri",
    "ROAS",
    "CTR",
    "CPC",
    "CPA",
]


def _ad_to_csv_row(a: dict) -> list:
    return [
        a["ad_id"],
        a["ad_name"],
        a["campaign_id"],
        a["campaign_name"],
        a["channel"],
        round(a["spend"], 4),
        round(a["impressions"], 4),
        round(a["clicks"], 4),
        round(a["conversions"], 4),
        round(a["conversion_value"], 4),
        round(a["roas"], 4),
        round(a["ctr"], 4),
        round(a["cpc"], 4),
        round(a["cpa"], 4),
    ]


@router.get(
    "/export",
    summary="Export ad-level creative performance as CSV (Turkish headers, UTF-8 BOM)",
    response_class=StreamingResponse,
)
def export_creatives(
    date_from: Annotated[
        date, Query(description="Inclusive start date (YYYY-MM-DD)")
    ],
    date_to: Annotated[
        date, Query(description="Inclusive end date (YYYY-MM-DD)")
    ],
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> StreamingResponse:
    """Return a UTF-8 BOM CSV of all ad creatives for the date range.

    Mirrors the columns from GET /api/v1/creatives/performance.
    Content-Disposition filename: ``ayaz-creatives-<from>_<to>.csv``.
    The BOM (\\ufeff) ensures Excel correctly decodes Turkish characters.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from, date_to'dan büyük olamaz.",
        )

    result = ad_performance(
        db,
        membership.tenant_id,
        date_from,
        date_to,
        sort="spend",
    )

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(_CREATIVE_CSV_HEADERS)
    for a in result["ads"]:
        writer.writerow(_ad_to_csv_row(a))

    filename = f"ayaz-creatives-{date_from}_{date_to}.csv"
    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
