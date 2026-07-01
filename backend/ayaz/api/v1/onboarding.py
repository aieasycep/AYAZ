"""Kurulum Sihirbazı (Onboarding Wizard) API — guided first-run setup.

Single read-only endpoint that reports which of the five required setup steps a
tenant has already completed, inferred from existing data (no dedicated
onboarding table required).

    GET /onboarding/status

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All step detection
queries are filtered to the requesting tenant — no cross-tenant leakage is
possible.

No query parameters.  The service layer detects completion state from existing
model data in real time.

Response shape
--------------
{
    "total_steps": 5,
    "completed_steps": int,
    "percent": int,           // 0-100, rounded
    "all_done": bool,
    "steps": [
        {
            "key": str,
            "title": str,
            "description": str,
            "done": bool,
            "cta_label": str,
            "cta_link": str
        },
        ...                   // always 5 items, in canonical order
    ]
}
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.onboarding import build_onboarding_status

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ── Response models ────────────────────────────────────────────────────────────


class OnboardingStep(BaseModel):
    key: str
    title: str
    description: str
    done: bool
    cta_label: str
    cta_link: str


class OnboardingStatusResponse(BaseModel):
    total_steps: int
    completed_steps: int
    percent: int
    all_done: bool
    steps: List[OnboardingStep]


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=OnboardingStatusResponse,
    summary=(
        "Kurulum Sihirbazı durumu — hangi adımlar tamamlandı? "
        "Mevcut verilerden kurulum ilerleme durumunu döndürür. "
        "Yeni kurumsal müşterilerin hızlıca üretken hale gelmesini sağlar."
    ),
)
def get_onboarding_status(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> OnboardingStatusResponse:
    """Return the onboarding wizard completion status for the current tenant.

    Detects which of the five setup steps have been completed by inspecting
    existing data (connected accounts, goals, tracking sources, budget plans,
    content posts).  No onboarding-specific table or state is required.

    Steps are always returned in canonical order:
    1. connect_accounts
    2. set_goal
    3. tracking
    4. budget_plan
    5. first_content

    Each step is marked ``done: true`` once at least one corresponding row
    exists for the tenant.  The response also includes convenience aggregates
    (``completed_steps``, ``percent``, ``all_done``) for progress indicators.

    Raises
    ------
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim in the JWT does not match an active membership.
    """
    data = build_onboarding_status(db=db, tenant_id=membership.tenant_id)

    return OnboardingStatusResponse(
        total_steps=data["total_steps"],
        completed_steps=data["completed_steps"],
        percent=data["percent"],
        all_done=data["all_done"],
        steps=[OnboardingStep(**step) for step in data["steps"]],
    )
