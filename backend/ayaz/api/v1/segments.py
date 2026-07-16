"""Ürün / SKU Segment API — segment derinliği (Dalga 3).

Read-only endpoint that returns per-SKU and per-category performance with gross
and return-adjusted (net) ROAS for the tenant.

    GET /segments/products?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

Defaults: date_to = today (UTC), date_from = today - 29 days (last 30 days).
Returns 422 if date_from > date_to.

Tenant-scoped: requires a valid JWT with ``tid`` claim. All data is filtered to
the requesting tenant — no cross-tenant leakage is possible.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.product_segments import build_product_segments

router = APIRouter(prefix="/segments", tags=["segments"])


# ── Response models ────────────────────────────────────────────────────────────


class SegmentPeriod(BaseModel):
    date_from: str
    date_to: str


class SegmentMetrics(BaseModel):
    units_sold: int
    returned_units: int
    gross_revenue: float
    returned_revenue: float
    net_revenue: float
    ad_spend: float
    gross_roas: float
    net_roas: float
    return_rate_pct: float


class ProductRow(SegmentMetrics):
    product_id: str
    sku: str
    name: str
    category: str
    price: float


class CategoryRow(SegmentMetrics):
    category: str
    product_count: int


class TotalsRow(SegmentMetrics):
    product_count: int


class ProductSegmentsResponse(BaseModel):
    period: SegmentPeriod
    currency: str
    totals: TotalsRow
    categories: list[CategoryRow]
    products: list[ProductRow]


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/products",
    response_model=ProductSegmentsResponse,
    summary=(
        "Ürün/SKU segment analizi — SKU ve kategori bazında brüt vs "
        "iade-düzeltilmiş (net) ROAS, iade oranı."
    ),
)
def get_product_segments(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: date | None = Query(
        default=None,
        description="Dönem başlangıcı (YYYY-MM-DD, dahil). Boşsa son 30 gün.",
    ),
    date_to: date | None = Query(
        default=None,
        description="Dönem bitişi (YYYY-MM-DD, dahil). Boşsa bugün (UTC).",
    ),
) -> ProductSegmentsResponse:
    """Return SKU + category performance for the tenant's product sales.

    Date range defaults
    -------------------
    * ``date_to`` defaults to today UTC if omitted.
    * ``date_from`` defaults to ``date_to - 29 days`` (last 30 days inclusive).

    Raises
    ------
    422 — if ``date_from > date_to``.
    401/403 — on missing/invalid auth or tenant mismatch.
    """
    today = datetime.now(timezone.utc).date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=29)

    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from, date_to'dan sonra olamaz.",
        )

    result = build_product_segments(
        db=db,
        tenant_id=membership.tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    return ProductSegmentsResponse(
        period=SegmentPeriod(**result["period"]),
        currency=result["currency"],
        totals=TotalsRow(**result["totals"]),
        categories=[CategoryRow(**c) for c in result["categories"]],
        products=[ProductRow(**p) for p in result["products"]],
    )
