"""Marcom Kreatif Lensi (Marketing Creative Lens) API.

Endpoints
---------
GET /api/v1/marcom/creative-insights?date_from=&date_to=
    Plain-language marketing summary of which creatives drove engagement.
    Metrics use reach/clicks/CTR language — no ROAS jargon.

Auth
----
All endpoints require a valid JWT (Bearer token).  Tenant scope resolved via
``get_current_membership`` — every query explicitly filters on
``membership.tenant_id``.

CTR convention
--------------
All CTR values in responses are expressed as **percent** (0-100 scale, rounded
to 2 decimal places).  Example: raw ratio 0.031 → 3.10.

Wiring note for team lead
-------------------------
This module is NOT imported in main.py yet.  To activate:

    from ayaz.api.v1 import marcom as marcom_router
    app.include_router(marcom_router.router, prefix=_PREFIX)
"""

from __future__ import annotations

from datetime import date, timedelta, timezone, datetime as _dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.marcom import creative_insights

router = APIRouter(prefix="/marcom", tags=["marcom"])


# ── Response schemas ──────────────────────────────────────────────────────────


class MarcomPeriod(BaseModel):
    """Date range for the insights request."""

    date_from: date
    date_to: date


class MarcomTotals(BaseModel):
    """Aggregated totals across all creatives in the period."""

    impressions:     int
    clicks:          int
    ctr:             float   # PERCENT 0-100, rounded 2 dp
    conversions:     float
    creatives_count: int


class CreativeInsight(BaseModel):
    """Marketing-language summary for one ad creative."""

    ad_id:             str
    ad_name:           str
    campaign_name:     str
    channel:           str
    impressions:       int
    clicks:            int
    ctr:               float   # PERCENT 0-100, rounded 2 dp
    conversions:       float
    traffic_share_pct: float   # ad clicks / total clicks * 100, rounded 1 dp
    insight:           str     # Plain Turkish sentence


class CreativeInsightsResponse(BaseModel):
    """Full creative-lens response."""

    period:         MarcomPeriod
    totals:         MarcomTotals
    headline:       str           # Turkish one-liner summarising the period
    top_creatives:  list[CreativeInsight]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/creative-insights",
    response_model=CreativeInsightsResponse,
    summary=(
        "Hangi kreatifler etkileşimi/trafiği sürükledi? "
        "Erişim, tıklama, TO ve trafik payı cinsinden özet."
    ),
)
def get_creative_insights(
    date_from: Annotated[
        date | None,
        Query(description="Kapsayıcı başlangıç tarihi (YYYY-AA-GG). Varsayılan: bugün - 29 gün."),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Kapsayıcı bitiş tarihi (YYYY-AA-GG). Varsayılan: bugün."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=50, description="Döndürülecek maksimum kreatif sayısı (varsayılan 8)."),
    ] = 8,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> CreativeInsightsResponse:
    """Return plain-language marketing insights for the period's top creatives.

    Defaults: date_to = today UTC, date_from = today - 29 days (30-day window).
    Returns 422 when date_from > date_to.

    CTR is returned as **percent** (0-100), rounded to 2 decimal places.
    traffic_share_pct = ad clicks / total period clicks * 100, rounded 1 dp.
    All user-facing strings are in Turkish.
    """
    today = _dt.now(timezone.utc).date()

    effective_to:   date = date_to   if date_to   is not None else today
    effective_from: date = date_from if date_from is not None else (effective_to - timedelta(days=29))

    if effective_from > effective_to:
        raise HTTPException(
            status_code=422,
            detail="date_from, date_to'dan büyük olamaz.",
        )

    data = creative_insights(
        db,
        membership.tenant_id,
        effective_from,
        effective_to,
        limit=limit,
    )

    return CreativeInsightsResponse(
        period=MarcomPeriod(date_from=effective_from, date_to=effective_to),
        totals=MarcomTotals(**data["totals"]),
        headline=data["headline"],
        top_creatives=[CreativeInsight(**c) for c in data["top_creatives"]],
    )
