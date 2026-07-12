"""AYAZ FastAPI application entry point.

Startup
-------
    cd backend
    uvicorn ayaz.main:app --reload

The app is versioned under ``/api/v1/``.  The root ``/health`` endpoint is
intentionally unversioned for load-balancer / Kubernetes liveness probes.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from ayaz.api.v1 import content as content_router
from ayaz.api.v1 import budget as budget_router
from ayaz.api.v1 import inbox as inbox_router
from ayaz.api.v1 import executive as executive_router
from ayaz.api.v1 import attribution as attribution_router
from ayaz.api.v1 import marcom as marcom_router
from ayaz.api.v1 import command_center as command_center_router
from ayaz.api.v1 import benchmark as benchmark_router
from ayaz.api.v1 import segments as segments_router
from ayaz.api.v1 import audit as audit_router
from ayaz.api.v1 import onboarding as onboarding_router
from ayaz.api.v1 import recommendations as recommendations_router
from ayaz.api.v1 import consent_center as consent_center_router
from ayaz.api.v1 import ad_studio as ad_studio_router
from ayaz.api.v1 import budget_simulator as budget_simulator_router
from ayaz.api.v1 import role_views as role_views_router
from ayaz.api.v1 import funnel as funnel_router
from ayaz.api.v1 import marketing_calendar as marketing_calendar_router
from ayaz.api.v1 import health_index as health_index_router
from ayaz.api.v1 import integrations as integrations_router
from ayaz.api.v1 import data_quality as data_quality_router
from ayaz.api.v1 import usage_shield as usage_shield_router
from ayaz.api.v1 import seo as seo_router
from ayaz.config import settings
from ayaz.observability import (
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    configure_logging,
)

# Configure logging once at import time — idempotent, safe under hot-reload.
configure_logging(level=logging.DEBUG if settings.debug else logging.INFO)

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

# ── Observability middleware ───────────────────────────────────────────────────
# Starlette executes middleware in *reverse* registration order on ingress.
# We want: RequestID → RequestLogging → CORS → route handler.
# So we register in the order: CORS last (added first below is outermost last),
# but to be explicit we add them in this exact sequence:
#   1. RequestLoggingMiddleware  (registered second → runs second on ingress)
#   2. RequestIDMiddleware       (registered third  → runs first on ingress,
#                                  sets request_id before logging reads it)
# CORS is added last here so it remains the very first ASGI layer (handles
# preflight OPTIONS before any of our middleware fires).

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Türkçe request-validation hataları ──────────────────────────────────────────
# FastAPI'nin otomatik gövde/parametre doğrulaması İngilizce Pydantic mesajları
# üretir ("Field required", "Input should be a valid integer"). Türk kullanıcıya
# bunlar gösterilmemeli; frontend parseApiError detail[0].msg'i ekrana basıyor.
# Bu işleyici SADECE otomatik doğrulama hatalarını (RequestValidationError)
# çevirir; kod içinde elle atılan Türkçe HTTPException(422, detail=[...]) çağrıları
# ayrı yoldan geçtiği için etkilenmez.
from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.requests import Request  # noqa: E402

_TR_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "Bu alan zorunludur.",
    "string_too_short": "Çok kısa bir değer girdiniz.",
    "string_too_long": "Çok uzun bir değer girdiniz.",
    "string_type": "Metin değeri bekleniyor.",
    "int_parsing": "Geçerli bir tam sayı girin.",
    "int_type": "Sayısal bir değer bekleniyor.",
    "float_parsing": "Geçerli bir sayı girin.",
    "bool_parsing": "Geçerli bir evet/hayır değeri bekleniyor.",
    "greater_than": "Değer çok küçük.",
    "greater_than_equal": "Değer izin verilenin altında.",
    "less_than": "Değer çok büyük.",
    "less_than_equal": "Değer izin verilenin üstünde.",
    "value_error": "Geçersiz değer.",
    "enum": "Geçersiz seçenek.",
    "date_parsing": "Geçerli bir tarih girin.",
    "date_from_datetime_parsing": "Geçerli bir tarih girin.",
    "datetime_parsing": "Geçerli bir tarih/saat girin.",
    "json_invalid": "Gönderilen veri okunamadı.",
    "uuid_parsing": "Geçersiz kimlik değeri.",
}
_TR_VALIDATION_FALLBACK = "Gönderilen bilgilerde bir sorun var. Lütfen alanları kontrol edin."


def _tr_validation_msg(err: dict) -> str:
    """Turkish message for one Pydantic error.

    ``value_error`` / ``assertion_error`` carry a CUSTOM message a validator
    raised (usually already Turkish and specific, e.g. "Geçersiz saat
    dilimi") — pass it through, stripping Pydantic's "Value error, " prefix.
    All other types are Pydantic's built-in English messages → translate.
    """
    etype = err.get("type", "")
    if etype in ("value_error", "assertion_error"):
        raw = str(err.get("msg", "")).strip()
        for prefix in ("Value error, ", "Assertion failed, "):
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
        return raw or _TR_VALIDATION_MESSAGES.get(etype, _TR_VALIDATION_FALLBACK)
    return _TR_VALIDATION_MESSAGES.get(etype, _TR_VALIDATION_FALLBACK)


@app.exception_handler(RequestValidationError)
async def _tr_validation_handler(request: Request, exc: RequestValidationError):
    tr_errors = [
        {"loc": e.get("loc"), "msg": _tr_validation_msg(e), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": tr_errors})


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
app.include_router(content_router.router, prefix=_PREFIX)
app.include_router(budget_router.router, prefix=_PREFIX)
app.include_router(inbox_router.router, prefix=_PREFIX)
app.include_router(executive_router.router, prefix=_PREFIX)
app.include_router(attribution_router.router, prefix=_PREFIX)
app.include_router(marcom_router.router, prefix=_PREFIX)
app.include_router(command_center_router.router, prefix=_PREFIX)
app.include_router(benchmark_router.router, prefix=_PREFIX)
app.include_router(segments_router.router, prefix=_PREFIX)
app.include_router(audit_router.router, prefix=_PREFIX)
app.include_router(onboarding_router.router, prefix=_PREFIX)
app.include_router(recommendations_router.router, prefix=_PREFIX)
app.include_router(consent_center_router.router, prefix=_PREFIX)
app.include_router(ad_studio_router.router, prefix=_PREFIX)
app.include_router(budget_simulator_router.router, prefix=_PREFIX)
app.include_router(role_views_router.router, prefix=_PREFIX)
app.include_router(funnel_router.router, prefix=_PREFIX)
app.include_router(marketing_calendar_router.router, prefix=_PREFIX)
app.include_router(health_index_router.router, prefix=_PREFIX)
app.include_router(integrations_router.router, prefix=_PREFIX)
app.include_router(data_quality_router.router, prefix=_PREFIX)
app.include_router(usage_shield_router.router, prefix=_PREFIX)
app.include_router(seo_router.router, prefix=_PREFIX)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["infra"], summary="Liveness probe")
def health() -> dict[str, str]:
    """Return 200 OK — used by load balancers and Kubernetes liveness probes."""
    return {"status": "ok", "version": app.version}


@app.get("/health/ready", tags=["infra"], summary="Readiness probe")
def health_ready() -> JSONResponse:
    """Check DB connectivity and return 200 when the service is ready to serve traffic.

    Executes a lightweight ``SELECT 1`` against the configured database.
    Returns 503 Service Unavailable (body ``{"status": "not_ready"}``) if the
    database is unreachable — without leaking any exception detail.
    Used by Kubernetes readiness probes and load-balancer health checks.
    """
    from sqlalchemy import text

    from ayaz.database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger("ayaz.health").warning(
            "Readiness probe: DB connectivity check failed"
        )
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    return JSONResponse(status_code=200, content={"status": "ready"})
