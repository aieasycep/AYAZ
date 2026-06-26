"""Natural-Language Report Builder API.

Endpoint
--------
POST /api/v1/reports/build
    Body: {prompt, date_from?, date_to?}
    Auth: Bearer JWT via get_current_membership (tenant-scoped)
    Returns: {spec: {...}, data: {totals, by_channel, timeseries}}

Router prefix
-------------
This router uses prefix="/reports" (matching the existing reports router) with
the single route "/build".  FastAPI merges routes by path — /reports/build does
not clash with any existing route in ayaz/api/v1/reports.py.

Wire-up (team lead adds one line to main.py)
--------------------------------------------
    from ayaz.api.v1 import report_builder as report_builder_router
    app.include_router(report_builder_router.router, prefix="/api/v1")
"""

from __future__ import annotations

from datetime import date, timedelta, timezone, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.report_builder import ReportSpec, build_report, parse_request

router = APIRouter(prefix="/reports", tags=["report-builder"])


# ── Request / response schemas ─────────────────────────────────────────────────


class BuildRequest(BaseModel):
    """Body for POST /reports/build."""

    prompt: str
    date_from: date | None = None
    date_to: date | None = None


class ReportSpecOut(BaseModel):
    """Serialisable projection of ReportSpec (dates as ISO strings)."""

    title: str
    metrics: list[str]
    channels: list[str]
    comparison: bool
    viz: str
    date_from: str
    date_to: str

    @classmethod
    def from_spec(cls, spec: ReportSpec) -> "ReportSpecOut":
        return cls(
            title=spec.title,
            metrics=spec.metrics,
            channels=spec.channels,
            comparison=spec.comparison,
            viz=spec.viz,
            date_from=spec.date_from.isoformat(),
            date_to=spec.date_to.isoformat(),
        )


class BuildResponse(BaseModel):
    """Full response from POST /reports/build."""

    spec: ReportSpecOut
    data: dict  # {totals, by_channel, timeseries} — shapes match dashboard API


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post(
    "/build",
    response_model=BuildResponse,
    summary="Parse a natural-language report prompt and execute it against unified data",
)
def build_report_endpoint(
    body: BuildRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> BuildResponse:
    """Convert a Turkish (or English) natural-language query into a report.

    The endpoint:
    1. Validates that prompt is non-empty (422 otherwise).
    2. Resolves default dates (last 30 days) if date_from/date_to are absent.
    3. Parses the prompt into a ReportSpec (Claude if API key is set, else stub).
    4. Executes the spec against the unified fact table, filtered by tenant_id.
    5. Returns the parsed spec alongside the aggregated data.

    All queries are explicitly scoped to ``membership.tenant_id``.

    Example request
    ---------------
    POST /api/v1/reports/build
    {"prompt": "Meta vs Google son 30 gun"}

    Example response (shape)
    ------------------------
    {
        "spec": {
            "title": "Meta Ads vs Google Ads Son 30 Gün Karşılaştırması",
            "metrics": ["spend", "roas", "conversions"],
            "channels": ["meta_ads", "google_ads"],
            "comparison": true,
            "viz": "mixed",
            "date_from": "2026-05-27",
            "date_to": "2026-06-25"
        },
        "data": {
            "totals": {spend, impressions, clicks, conversions,
                       conversion_value, ctr, cpc, cpa, roas},
            "by_channel": [{channel, spend, ...}, ...],
            "timeseries": [{date, value}, ...]
        }
    }
    """
    # 422 on empty prompt
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="prompt must not be empty",
        )

    # Resolve default date range: last 30 days
    today = datetime.now(timezone.utc).date()
    default_to = body.date_to or today
    default_from = body.date_from or (default_to - timedelta(days=29))

    # Parse prompt → ReportSpec
    spec = parse_request(
        body.prompt.strip(),
        default_from=default_from,
        default_to=default_to,
    )

    # Execute spec → data (tenant-scoped)
    data = build_report(db, membership.tenant_id, spec)

    return BuildResponse(
        spec=ReportSpecOut.from_spec(spec),
        data=data,
    )
