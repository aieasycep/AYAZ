"""SEO module API — owned analytics (GSC) + site audit + DataForSEO gateway.

Endpoints
---------
GET  /api/v1/seo/overview       — aggregated GSC metrics + trends for the period
GET  /api/v1/seo/opportunities  — structured improvement opportunities (striking-distance, low-CTR, …)
POST /api/v1/seo/audit          — PageSpeed Insights audit for a URL
GET  /api/v1/seo/backlinks      — DataForSEO backlinks summary (requires connected integration)
GET  /api/v1/seo/keywords       — DataForSEO keyword ideas (requires connected integration)

Auth
----
All endpoints require a valid JWT Bearer token. Tenant context is resolved via
``get_current_membership``. Every query explicitly filters by tenant_id.

DataForSEO gating
-----------------
``/seo/backlinks`` and ``/seo/keywords`` return HTTP 200 with a
``{"status": "connect_required", ...}`` body when the dataforseo integration
is not connected — never 500.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.integrations import IntegrationConnection
from ayaz.models.oltp import Membership
from ayaz.services import seo as seo_service
from ayaz.services import pagespeed as pagespeed_service

router = APIRouter(prefix="/seo", tags=["seo"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_dataforseo_connection(
    db: Session,
    tenant_id: uuid.UUID,
) -> "IntegrationConnection | None":
    """Return the tenant's active DataForSEO connection row, or None."""
    return db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.integration_key == "dataforseo",
            IntegrationConnection.status == "connected",
        )
    )


# ── Request / Response schemas ────────────────────────────────────────────────


class AuditRequest(BaseModel):
    url: str = Field(..., description="URL to audit, e.g. https://example.com/")
    strategy: str = Field("mobile", description="'mobile' or 'desktop'")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/overview", summary="GSC search analytics overview + trends")
def get_overview(
    period_days: Annotated[int, Query(ge=7, le=180, description="Lookback window in days")] = 30,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Return aggregated GSC metrics (clicks, impressions, CTR, position) with
    period-over-period trends and top-10 queries / pages.

    Data is drawn exclusively from ``seo_search_metrics`` (tenant-scoped).
    """
    return seo_service.get_overview(db, membership.tenant_id, period_days=period_days)


@router.get("/opportunities", summary="SEO improvement opportunities")
def get_opportunities(
    period_days: Annotated[int, Query(ge=7, le=90)] = 30,
    emit_insights: Annotated[bool, Query(description="Also write results to the Insights table")] = False,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Compute structured SEO opportunities from GSC data:

    - **striking_distance**: queries ranked 8–20 with meaningful impressions
    - **low_ctr**: queries with high impressions but low click-through rate
    - **cannibalization**: multiple pages ranking for the same query
    - **top_movers**: queries with significant position delta vs prior period

    Pass ``?emit_insights=true`` to also write findings to the Insights / Öneriler feed.
    """
    opps = seo_service.get_opportunities(db, membership.tenant_id, period_days=period_days)

    emitted: dict[str, int] | None = None
    if emit_insights:
        emitted = seo_service.emit_seo_insights(
            db, membership.tenant_id, period_days=period_days
        )
        db.commit()

    return {"opportunities": opps, "count": len(opps), "emitted": emitted}


@router.post("/audit", summary="PageSpeed Insights site audit")
def run_audit(
    body: AuditRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Run a Google PageSpeed Insights audit for the given URL.

    Returns Core Web Vitals + Lighthouse scores (performance, SEO,
    accessibility, best-practices) and the top 10 failing audits.

    Never returns HTTP 500 — on API failure or offline mode returns a
    degraded result with ``"status": "error"`` or ``"status": "kimlik_bekliyor"``.
    """
    from ayaz.config import settings

    api_key = getattr(settings, "pagespeed_api_key", None) or getattr(settings, "google_api_key", "") or ""
    result = pagespeed_service.run_audit(body.url, api_key=api_key, strategy=body.strategy)
    return result


@router.get("/backlinks", summary="DataForSEO backlinks summary")
def get_backlinks(
    domain: Annotated[str, Query(description="Domain to analyse, e.g. example.com")] = "",
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Return backlinks summary for a domain via DataForSEO.

    Returns ``{"status": "connect_required", ...}`` (HTTP 200) when DataForSEO
    is not connected — never 500.
    """
    conn = _get_dataforseo_connection(db, membership.tenant_id)
    if conn is None:
        return {
            "status": "connect_required",
            "message": (
                "DataForSEO entegrasyonu bağlı değil. "
                "Entegrasyon Merkezi'nden 'SEO' kategorisinde DataForSEO'yu bağlayın."
            ),
            "integration_key": "dataforseo",
        }

    if not domain:
        return {"status": "error", "message": "domain parametresi gereklidir."}

    from ayaz.integrations.dataforseo import DataForSEOIntegration
    from ayaz.integrations.base import ActionContext
    from ayaz.services.vault import InMemoryVault
    from ayaz.services.grant_vault import GrantVault

    # Build a minimal ActionContext to call execute_action
    ctx = _build_action_ctx(db, membership.tenant_id, conn)
    adapter = DataForSEOIntegration()
    return adapter.execute_action(
        "dataforseo_backlinks_summary",
        {"domain": domain},
        ctx=ctx,
    )


@router.get("/keywords", summary="DataForSEO keyword ideas")
def get_keywords(
    seed: Annotated[str, Query(description="Seed keyword")] = "",
    language_code: Annotated[str, Query()] = "tr",
    location_code: Annotated[int, Query()] = 2792,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Return keyword ideas (volume, difficulty) for a seed keyword via DataForSEO.

    Returns ``{"status": "connect_required", ...}`` (HTTP 200) when DataForSEO
    is not connected — never 500.
    """
    conn = _get_dataforseo_connection(db, membership.tenant_id)
    if conn is None:
        return {
            "status": "connect_required",
            "message": (
                "DataForSEO entegrasyonu bağlı değil. "
                "Entegrasyon Merkezi'nden 'SEO' kategorisinde DataForSEO'yu bağlayın."
            ),
            "integration_key": "dataforseo",
        }

    if not seed:
        return {"status": "error", "message": "seed parametresi gereklidir."}

    from ayaz.integrations.dataforseo import DataForSEOIntegration

    ctx = _build_action_ctx(db, membership.tenant_id, conn)
    adapter = DataForSEOIntegration()
    return adapter.execute_action(
        "dataforseo_keyword_ideas",
        {"seed": seed, "language_code": language_code, "location_code": location_code},
        ctx=ctx,
    )


# ── Private helpers ────────────────────────────────────────────────────────────


def _build_action_ctx(
    db: Session,
    tenant_id: uuid.UUID,
    conn: "IntegrationConnection",
) -> "Any":
    """Build a minimal ActionContext for DataForSEO adapter calls."""
    from ayaz.integrations.base import ActionContext
    from ayaz.services.grant_vault import GrantVault
    from ayaz.config import settings
    from ayaz.services.vault import EncryptedColumnVault

    vault = EncryptedColumnVault(settings.vault_key)
    gv = GrantVault(vault)

    # Resolve vault_secret_ref from the provider grant
    from sqlalchemy import select as sa_select
    from ayaz.models.integrations import ProviderGrant

    grant_ref = ""
    if conn.provider_grant_id:
        pg = db.get(ProviderGrant, conn.provider_grant_id)
        if pg:
            grant_ref = pg.vault_secret_ref or ""

    return ActionContext(
        tenant_id=tenant_id,
        connection_id=conn.id,
        user_id=tenant_id,  # system context
        db=db,
        vault=gv,
        _vault_secret_ref=grant_ref,
    )
