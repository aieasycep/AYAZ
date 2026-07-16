"""Proaktif Öneri Merkezi + AI Haftalık Strateji API — M14.

Endpoints
---------
    GET  /recommendations/feed
        Synthesised, prioritised recommendation feed for the tenant.
        Reads signals from audit, budget, benchmark, goals, inbox and content.

    GET  /recommendations/weekly-strategy
        AI (or template) Turkish weekly strategy narrative.

    POST /recommendations/{recommendation_key}/action
        Persist an accept / snooze / dismiss / reopen action on a recommendation.
        Returns the updated state dict.  422 on invalid action or key format.

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All data is filtered
to the requesting tenant — no cross-tenant leakage is possible.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.models.recommendations import VALID_ACTIONS
from ayaz.services.recommendations import (
    apply_recommendation_action,
    build_recommendation_feed,
    generate_weekly_strategy,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


# ── Request / response models ─────────────────────────────────────────────────


class RecommendationMetric(BaseModel):
    label: str
    value: str
    comparison: str | None = None


class RecommendationItem(BaseModel):
    key: str
    category: str
    category_label: str
    title: str
    rationale: str
    impact: Literal["high", "medium", "low"]
    impact_label: str
    effort: Literal["low", "medium", "high"]
    effort_label: str
    metric: RecommendationMetric | None = None
    action_label: str
    action_href: str
    status: str
    snoozed_until: str | None = None


class FeedSummary(BaseModel):
    open: int
    accepted: int
    snoozed: int
    dismissed: int
    total: int
    high_impact_open: int


class RecommendationFeedResponse(BaseModel):
    generated_at: str
    summary: FeedSummary
    recommendations: list[RecommendationItem]


class FocusArea(BaseModel):
    title: str
    detail: str


class WeeklyStrategyResponse(BaseModel):
    week_label: str
    headline: str
    narrative: str
    focus_areas: list[FocusArea]
    top_recommendations: list[RecommendationItem]
    source: Literal["template", "ai"]


class ActionRequest(BaseModel):
    action: str = Field(
        ...,
        description=(
            "İşlem türü. Geçerli değerler: "
            "``accept`` (onayla), ``snooze`` (ertele), "
            "``dismiss`` (reddet), ``reopen`` (yeniden aç)."
        ),
    )
    note: str | None = Field(
        default=None,
        description="Kullanıcının isteğe bağlı notu.",
    )
    snooze_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description=(
            "Erteleme süresi (gün).  Yalnızca ``action=snooze`` için geçerlidir. "
            "Belirtilmezse varsayılan 7 gün kullanılır."
        ),
    )

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in VALID_ACTIONS:
            raise ValueError(
                f"Geçersiz işlem: {v!r}. "
                f"Geçerli değerler: {sorted(VALID_ACTIONS)}"
            )
        return v


class ActionResponse(BaseModel):
    key: str
    status: str
    snoozed_until: str | None = None
    note: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/feed",
    response_model=RecommendationFeedResponse,
    summary=(
        "Öneri Akışı — tüm AYAZ sinyallerini birleştirerek önceliklendirilmiş, "
        "eyleme geçirilebilir öneri listesi döndürür.  Her öneri için durum "
        "(açık / onaylandı / ertelendi / reddedildi) ve etki/çaba puanı içerir."
    ),
)
def get_recommendation_feed(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    as_of: date | None = Query(
        default=None,
        description=(
            "Hesaplama referans tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse bugün (UTC)."
        ),
    ),
) -> RecommendationFeedResponse:
    """Return the tenant's prioritised recommendation feed.

    Synthesises signals from the account health audit, budget planner,
    sector benchmarks, goal tracker, social inbox, and content planner.
    Each recommendation carries a stable key, impact / effort rating,
    and the current workflow status (open / accepted / snoozed / dismissed).

    Raises
    ------
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim does not match an active membership.
    """
    result = build_recommendation_feed(
        db,
        membership.tenant_id,
        as_of=as_of,
    )
    return RecommendationFeedResponse(**result)


@router.get(
    "/weekly-strategy",
    response_model=WeeklyStrategyResponse,
    summary=(
        "Haftalık Strateji — o haftanın öneri sinyallerine dayalı AI (veya "
        "şablon) Türkçe strateji anlatısı.  Odak alanları ve üst önerilerle "
        "birlikte döndürülür."
    ),
)
def get_weekly_strategy(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    as_of: date | None = Query(
        default=None,
        description=(
            "Hesaplama referans tarihi (YYYY-MM-DD, dahil). "
            "Belirtilmezse bugün (UTC)."
        ),
    ),
) -> WeeklyStrategyResponse:
    """Return a Turkish weekly strategy narrative for the tenant.

    When an Anthropic API key is configured and the claude_narrator_model is
    set, the narrative is generated by Claude.  Otherwise a fully deterministic
    template is used so the endpoint never fails due to missing credentials.

    ``source`` in the response indicates which path was taken:
    ``"ai"`` — Claude-generated, ``"template"`` — deterministic fallback.

    Raises
    ------
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim does not match an active membership.
    """
    result = generate_weekly_strategy(
        db,
        membership.tenant_id,
        as_of=as_of,
    )
    return WeeklyStrategyResponse(**result)


@router.post(
    "/{recommendation_key}/action",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary=(
        "Öneri İşlemi — bir öneriyi onayla, ertele, reddet veya yeniden aç. "
        "Snooze için snooze_days belirtin (varsayılan: 7 gün)."
    ),
)
def post_recommendation_action(
    recommendation_key: str,
    body: ActionRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ActionResponse:
    """Persist an action on a recommendation for the tenant.

    Actions
    -------
    * ``accept``  — marks the recommendation as accepted.
    * ``snooze``  — defers the recommendation for ``snooze_days`` days
                    (default 7; valid range 1–365).
    * ``dismiss`` — permanently dismisses the recommendation.
    * ``reopen``  — reverts any accepted/snoozed/dismissed recommendation
                    back to open.

    The recommendation_key in the path must be a non-empty string.  The
    ``(tenant_id, recommendation_key)`` pair is unique — calling this endpoint
    twice with the same key and action is idempotent (the row is upserted).

    Raises
    ------
    400 — if ``action`` is not one of the four valid values (also caught at
          Pydantic validation time → 422).
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim does not match an active membership.
    422 — if the request body fails validation (e.g. invalid action string or
          snooze_days out of range).
    """
    if not recommendation_key or not recommendation_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="recommendation_key boş olamaz.",
        )

    try:
        result = apply_recommendation_action(
            db,
            membership.tenant_id,
            recommendation_key,
            body.action,
            note=body.note,
            snooze_days=body.snooze_days if body.snooze_days is not None else 7,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ActionResponse(**result)
