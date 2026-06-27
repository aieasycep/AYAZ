"""AYAZ FastAPI application entry point.

Startup
-------
    cd backend
    uvicorn ayaz.main:app --reload

The app is versioned under ``/api/v1/``.  The root ``/health`` endpoint is
intentionally unversioned for load-balancer / Kubernetes liveness probes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ayaz.api.v1 import auth as auth_router
from ayaz.api.v1 import connectors as connectors_router
from ayaz.api.v1 import dashboard as dashboard_router
from ayaz.api.v1 import ads as ads_router
from ayaz.api.v1 import automation as automation_router
from ayaz.api.v1 import billing as billing_router
from ayaz.api.v1 import briefing as briefing_router
from ayaz.api.v1 import copilot as copilot_router
from ayaz.api.v1 import notifications as notifications_router
from ayaz.api.v1 import creatives as creatives_router
from ayaz.api.v1 import goals as goals_router
from ayaz.api.v1 import optimizer as optimizer_router
from ayaz.api.v1 import feeds as feeds_router
from ayaz.api.v1 import insights as insights_router
from ayaz.api.v1 import oauth as oauth_router
from ayaz.api.v1 import report_builder as report_builder_router
from ayaz.api.v1 import reports as reports_router
from ayaz.api.v1 import tracking as tracking_router
from ayaz.api.v1 import workspaces as workspaces_router
from ayaz.config import settings

app = FastAPI(
    title="AYAZ API",
    description=(
        "AYAZ — unified digital-marketing platform API. "
        "All endpoints are under /api/v1/ except /health."
    ),
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
_PREFIX = "/api/v1"

app.include_router(auth_router.router, prefix=_PREFIX)
app.include_router(connectors_router.router, prefix=_PREFIX)
app.include_router(dashboard_router.router, prefix=_PREFIX)
app.include_router(feeds_router.router, prefix=_PREFIX)
app.include_router(oauth_router.router, prefix=_PREFIX)
app.include_router(insights_router.router, prefix=_PREFIX)
app.include_router(ads_router.router, prefix=_PREFIX)
app.include_router(reports_router.router, prefix=_PREFIX)
app.include_router(automation_router.router, prefix=_PREFIX)
app.include_router(tracking_router.router, prefix=_PREFIX)
app.include_router(billing_router.router, prefix=_PREFIX)
app.include_router(workspaces_router.router, prefix=_PREFIX)
app.include_router(copilot_router.router, prefix=_PREFIX)
app.include_router(optimizer_router.router, prefix=_PREFIX)
app.include_router(goals_router.router, prefix=_PREFIX)
app.include_router(report_builder_router.router, prefix=_PREFIX)
app.include_router(creatives_router.router, prefix=_PREFIX)
app.include_router(briefing_router.router, prefix=_PREFIX)
app.include_router(notifications_router.router, prefix=_PREFIX)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["infra"], summary="Liveness probe")
def health() -> dict[str, str]:
    """Return 200 OK — used by load balancers and Kubernetes liveness probes."""
    return {"status": "ok", "version": app.version}
