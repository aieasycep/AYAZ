"""AI Reklam Metni Stüdyosu (Ad Copy Studio) API — M15 Dalga 73.

Endpoints
---------
    POST /ad-studio/generate
        Generate platform-specific Turkish ad copy from a brief.
        Body: {platform, product, value_prop?, tone?, keywords?, audience?, n_variants?}
        Returns the generate_ad_copy response dict (200).
        422 on missing/unknown platform or missing product.

    POST /ad-studio/drafts
        Save a generated draft to the library.
        Body: {platform, title, brief, variants, source?}
        Returns the saved draft dict (201).

    GET /ad-studio/drafts?status=
        List drafts for the tenant, newest first.
        Optional ?status=saved|archived filter.

    PATCH /ad-studio/drafts/{draft_id}
        Update the status of a draft.
        Body: {status}
        Returns the updated draft dict (200).
        422 on invalid status, 404 on missing draft.

    DELETE /ad-studio/drafts/{draft_id}
        Hard-delete a draft (204).
        404 on missing draft.

Tenant-scoped: requires a valid JWT with ``tid`` claim.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.ad_studio import (
    PLATFORM_SPECS,
    delete_draft,
    generate_ad_copy,
    list_drafts,
    save_draft,
    update_draft_status,
)

router = APIRouter(prefix="/ad-studio", tags=["ad-studio"])


# ── Request / response models ─────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    platform: str = Field(
        ...,
        description=(
            "Reklam platformu. Geçerli değerler: "
            "``google_ads``, ``meta_ads``, ``tiktok_ads``."
        ),
    )
    product: str = Field(
        ...,
        min_length=1,
        description="Ürün veya hizmet adı (zorunlu).",
    )
    value_prop: str | None = Field(
        default=None,
        description="Benzersiz değer önerisi.",
    )
    tone: str | None = Field(
        default=None,
        description=(
            "Metin tonu. Geçerli değerler: "
            "``profesyonel``, ``samimi``, ``heyecanli``, ``bilgilendirici``."
        ),
    )
    keywords: list[str] | None = Field(
        default=None,
        description="Hedef anahtar kelimeler listesi.",
    )
    audience: str | None = Field(
        default=None,
        description="Hedef kitle açıklaması.",
    )
    n_variants: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Üretilecek varyant sayısı (varsayılan: 3).",
    )

    @field_validator("platform")
    @classmethod
    def _validate_platform(cls, v: str) -> str:
        v = v.strip()
        if v not in PLATFORM_SPECS:
            raise ValueError(
                f"Bilinmeyen platform: {v!r}. "
                f"Geçerli değerler: {sorted(PLATFORM_SPECS)}"
            )
        return v

    @field_validator("product")
    @classmethod
    def _validate_product(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'product' alanı boş olamaz.")
        return v


class SaveDraftRequest(BaseModel):
    platform: str = Field(..., description="Reklam platformu.")
    title: str = Field(..., min_length=1, description="Taslak başlığı.")
    brief: dict[str, Any] = Field(..., description="Kullanılan brief verisi.")
    variants: list[dict[str, Any]] = Field(..., description="Üretilen varyantlar.")
    source: str | None = Field(
        default=None,
        description="Üretim kaynağı: ``template`` veya ``ai``.",
    )


class UpdateDraftRequest(BaseModel):
    status: str = Field(
        ...,
        description="Yeni durum: ``saved`` veya ``archived``.",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/generate",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary=(
        "Reklam Metni Üret — verilen brief'e göre platforma özgü Türkçe reklam metni "
        "varyantları üretir.  Her alan için karakter sayısı ve sınır bilgisi içerir."
    ),
)
def post_generate(
    body: GenerateRequest,
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Generate Turkish ad copy for the given platform and brief.

    The response contains ``n_variants`` distinct variants, each with a
    uniform ``fields`` list (key / label / value / char_count / max_len /
    within_limit) ready for generic frontend rendering.

    ``source`` is ``"template"`` when the deterministic generator ran, ``"ai"``
    when Claude was used successfully.

    Raises
    ------
    401 — missing / invalid JWT.
    403 — tenant mismatch.
    422 — unknown platform or empty product.
    """
    brief = body.model_dump(exclude_none=True)
    brief.pop("n_variants", None)

    n_variants = body.n_variants if body.n_variants is not None else 3

    try:
        result = generate_ad_copy(brief, n_variants=n_variants)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return result


@router.post(
    "/drafts",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Taslak Kaydet — üretilen reklam metni varyantlarını taslak kütüphanesine "
        "kaydeder."
    ),
)
def post_save_draft(
    body: SaveDraftRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Save a draft to the library and return its serialized form.

    Raises
    ------
    401 — missing / invalid JWT.
    403 — tenant mismatch.
    """
    src = body.source or "template"
    return save_draft(
        db,
        membership.tenant_id,
        platform=body.platform,
        title=body.title,
        brief=body.brief,
        variants=body.variants,
        source=src,
    )


@router.get(
    "/drafts",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary=(
        "Taslak Listesi — kiracının reklam metni taslak kütüphanesini döndürür.  "
        "İsteğe bağlı ?status= filtresi desteklenir."
    ),
)
def get_drafts(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Durum filtresi: ``saved`` veya ``archived``.",
    ),
) -> list[dict[str, Any]]:
    """Return the tenant's draft library, newest first.

    Raises
    ------
    401 — missing / invalid JWT.
    403 — tenant mismatch.
    """
    return list_drafts(db, membership.tenant_id, status=status_filter)


@router.patch(
    "/drafts/{draft_id}",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary=(
        "Taslak Güncelle — bir taslağın durumunu ``saved`` veya ``archived`` "
        "olarak günceller."
    ),
)
def patch_draft(
    draft_id: str,
    body: UpdateDraftRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> dict[str, Any]:
    """Update a draft's status.

    Raises
    ------
    401 — missing / invalid JWT.
    403 — tenant mismatch.
    404 — draft not found or belongs to a different tenant.
    422 — invalid status value.
    """
    try:
        return update_draft_status(
            db, membership.tenant_id, draft_id, body.status
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Taslak Sil — bir taslağı kalıcı olarak siler.",
)
def delete_draft_endpoint(
    draft_id: str,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    """Hard-delete a draft.

    Raises
    ------
    401 — missing / invalid JWT.
    403 — tenant mismatch.
    404 — draft not found or belongs to a different tenant.
    """
    try:
        delete_draft(db, membership.tenant_id, draft_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
