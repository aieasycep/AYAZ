"""Sektör Kıyaslama (Benchmark) API — TR E-ticaret sektör kıyaslaması.

Read-only endpoint that compares the tenant's last-N-day ad metrics against
reference ranges for the Turkish e-commerce vertical and reports each metric's
position (strong / average / weak) relative to those ranges.

    GET /benchmark/overview?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

Defaults: date_to = today (UTC), date_from = today - 29 days (last 30 days).
Returns 422 if date_from > date_to.

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All data is filtered
to the requesting tenant — no cross-tenant leakage is possible.

No new database tables are created or modified.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.benchmark import build_benchmark

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


# ── Response models ────────────────────────────────────────────────────────────


class BenchmarkPeriod(BaseModel):
    date_from: str
    date_to: str


class BenchmarkMetric(BaseModel):
    key: str
    label: str
    unit: str
    your_value: float
    ref_low: float
    ref_mid: float
    ref_high: float
    higher_is_better: bool
    position: Literal["strong", "average", "weak"]
    verdict: str


class BenchmarkChannel(BaseModel):
    channel: str
    label: str
    roas: float
    ctr: float
    roas_position: Literal["strong", "average", "weak"]
    ctr_position: Literal["strong", "average", "weak"]


class SummaryCounts(BaseModel):
    strong: int
    average: int
    weak: int


class BenchmarkOverviewResponse(BaseModel):
    period: BenchmarkPeriod
    vertical: str
    metrics: list[BenchmarkMetric]
    channels: list[BenchmarkChannel]
    headline: str
    summary_counts: SummaryCounts


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=BenchmarkOverviewResponse,
    summary=(
        "Sektör Kıyaslaması — reklamcılık metriklerinizi TR e-ticaret referans "
        "aralıklarıyla karşılaştırır.  Her metriğin konumunu (güçlü / ortalama / "
        "zayıf) ve Türkçe değerlendirmeyi döndürür."
    ),
)
def get_benchmark_overview(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    date_from: date | None = Query(
        default=None,
        description=(
            "Dönem başlangıç tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse bugünden 29 gün öncesi (son 30 gün)."
        ),
    ),
    date_to: date | None = Query(
        default=None,
        description=(
            "Dönem bitiş tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse bugün (UTC)."
        ),
    ),
) -> BenchmarkOverviewResponse:
    """Return a sector benchmark comparison for the tenant's ad performance.

    Aggregates the tenant's ad metrics over the requested period and compares
    them against reference ranges for the Turkish e-commerce vertical.

    Reference ranges are indicative benchmarks based on publicly available
    research.  They are NOT performance guarantees — actual results will vary
    by product category, seasonality, budget size, and audience targeting.

    Date range defaults
    -------------------
    * ``date_to`` defaults to today UTC if omitted.
    * ``date_from`` defaults to ``date_to - 29 days`` (last 30 days inclusive).

    Raises
    ------
    422 — if ``date_from > date_to``.
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim in the JWT does not match an active membership.
    """
    today = datetime.now(timezone.utc).date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=29)

    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from, date_to'dan sonra olamaz.",
        )

    result = build_benchmark(
        db=db,
        tenant_id=membership.tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    return BenchmarkOverviewResponse(
        period=BenchmarkPeriod(**result["period"]),
        vertical=result["vertical"],
        metrics=[BenchmarkMetric(**m) for m in result["metrics"]],
        channels=[BenchmarkChannel(**c) for c in result["channels"]],
        headline=result["headline"],
        summary_counts=SummaryCounts(**result["summary_counts"]),
    )
