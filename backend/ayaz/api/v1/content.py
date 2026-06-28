"""İçerik Planlayıcı (Content Planner) API — M8.

All endpoints are tenant-scoped via the ``get_current_membership`` dependency.
Tenant isolation is enforced on every query via ``membership.tenant_id``.

Endpoints
---------
    GET    /content/posts                — list posts (filterable)
    POST   /content/posts                — create a post
    GET    /content/posts/{id}           — get a single post
    PATCH  /content/posts/{id}           — update a post
    DELETE /content/posts/{id}           — delete a post
    POST   /content/posts/{id}/submit    — → status="pending_approval"
    POST   /content/posts/{id}/approve   — → status="approved"
    POST   /content/posts/{id}/reject    — → status="draft" + approval_note
    POST   /content/posts/{id}/schedule  — → status="scheduled" + scheduled_at
    POST   /content/posts/{id}/publish   — ALWAYS 501 (credential gate)
    POST   /content/ai-caption           — generate caption (no DB write)

Live-publish credential gate
-----------------------------
``POST /content/posts/{id}/publish`` intentionally returns HTTP 501.
Live publishing requires per-channel OAuth tokens (Instagram Graph API, Facebook
Page API, Twitter/X v2, LinkedIn API, TikTok for Business, YouTube Data API)
managed by the Integrations connector layer.  These credentials are NOT
available in this release.  Content planning, drafting, the approval workflow,
and scheduled queue are fully functional.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.content import VALID_CHANNELS, VALID_STATUSES, ContentPost
from ayaz.models.oltp import Membership
from ayaz.services.content import generate_caption

router = APIRouter(prefix="/content", tags=["content"])


# ── Ownership helper ──────────────────────────────────────────────────────────


def _require_post(
    post_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> ContentPost:
    """Return the post or raise 404 if not found / other tenant."""
    post = db.scalar(
        select(ContentPost).where(
            ContentPost.id == post_id,
            ContentPost.tenant_id == tenant_id,
        )
    )
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İçerik gönderisi bulunamadı.",
        )
    return post


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class ContentPostCreate(BaseModel):
    title: str
    body: str = ""
    channels: list[str] = []
    scheduled_at: str | None = None
    media_url: str | None = None
    ai_assisted: bool = False

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_CHANNELS
        if invalid:
            raise ValueError(
                f"Geçersiz kanal(lar): {sorted(invalid)}. "
                f"Geçerli kanallar: {sorted(VALID_CHANNELS)}."
            )
        return v


class ContentPostPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    channels: list[str] | None = None
    scheduled_at: str | None = None
    media_url: str | None = None
    status: str | None = None
    ai_assisted: bool | None = None

    model_config = {"from_attributes": True}

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalid = set(v) - VALID_CHANNELS
        if invalid:
            raise ValueError(
                f"Geçersiz kanal(lar): {sorted(invalid)}. "
                f"Geçerli kanallar: {sorted(VALID_CHANNELS)}."
            )
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in VALID_STATUSES:
            raise ValueError(
                f"Geçersiz durum: {v!r}. "
                f"Geçerli durumlar: {sorted(VALID_STATUSES)}."
            )
        return v


class ContentPostResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    body: str
    channels: list[str]
    scheduled_at: str | None
    status: str
    approval_note: str | None
    media_url: str | None
    ai_assisted: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: ContentPost) -> "ContentPostResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            title=obj.title,
            body=obj.body,
            channels=obj.channels if isinstance(obj.channels, list) else [],
            scheduled_at=obj.scheduled_at,
            status=obj.status,
            approval_note=obj.approval_note,
            media_url=obj.media_url,
            ai_assisted=obj.ai_assisted,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class RejectBody(BaseModel):
    note: str | None = None


class ScheduleBody(BaseModel):
    scheduled_at: str


class AICaptionRequest(BaseModel):
    brief: str
    channel: str | None = None
    tone: str = "profesyonel"


class AICaptionResponse(BaseModel):
    caption: str
    hashtags: list[str]
    ai_assisted: bool


# ── List posts ────────────────────────────────────────────────────────────────


@router.get(
    "/posts",
    response_model=list[ContentPostResponse],
    summary="Tüm içerik gönderilerini listele (filtrelenebilir)",
)
def list_posts(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Duruma göre filtrele (ör: draft, pending_approval, approved)",
    ),
    channel: str | None = Query(
        default=None,
        description="Kanala göre filtrele (kanal listesinde üyelik kontrolü yapılır)",
    ),
    date_from: str | None = Query(
        default=None,
        description="Başlangıç tarihi (YYYY-MM-DD) — scheduled_at üzerinden filtreler",
    ),
    date_to: str | None = Query(
        default=None,
        description="Bitiş tarihi (YYYY-MM-DD) — scheduled_at üzerinden filtreler",
    ),
) -> list[ContentPostResponse]:
    q = (
        select(ContentPost)
        .where(ContentPost.tenant_id == membership.tenant_id)
        .order_by(ContentPost.created_at.desc())
    )
    if status_filter is not None:
        q = q.where(ContentPost.status == status_filter)

    rows = list(db.scalars(q))

    # Channel filtering: keep posts whose channels list contains the requested channel.
    # Done in Python because JSON array membership queries are not portable across
    # SQLite (test) and PostgreSQL (production).
    if channel is not None:
        rows = [r for r in rows if channel in (r.channels or [])]

    # Date filtering: when BOTH date_from and date_to are provided, include only
    # posts whose scheduled_at date falls within [date_from, date_to].
    # Posts with scheduled_at=None are excluded in this case.
    if date_from is not None and date_to is not None:
        def _in_range(post: ContentPost) -> bool:
            if post.scheduled_at is None:
                return False
            # scheduled_at is an ISO-8601 string; the date prefix is the first 10 chars
            post_date = post.scheduled_at[:10]
            return date_from <= post_date <= date_to

        rows = [r for r in rows if _in_range(r)]

    return [ContentPostResponse.from_orm_obj(r) for r in rows]


# ── Create post ───────────────────────────────────────────────────────────────


@router.post(
    "/posts",
    response_model=ContentPostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni bir içerik gönderisi oluştur",
)
def create_post(
    body: ContentPostCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = ContentPost(
        tenant_id=membership.tenant_id,
        title=body.title,
        body=body.body,
        channels=body.channels,
        scheduled_at=body.scheduled_at,
        media_url=body.media_url,
        ai_assisted=body.ai_assisted,
        status="draft",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


# ── Get single post ───────────────────────────────────────────────────────────


@router.get(
    "/posts/{post_id}",
    response_model=ContentPostResponse,
    summary="Tek bir içerik gönderisini getir",
)
def get_post(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)
    return ContentPostResponse.from_orm_obj(post)


# ── Patch post ────────────────────────────────────────────────────────────────


@router.patch(
    "/posts/{post_id}",
    response_model=ContentPostResponse,
    summary="İçerik gönderisini güncelle (kısmi)",
)
def patch_post(
    post_id: uuid.UUID,
    body: ContentPostPatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)

    if body.title is not None:
        post.title = body.title
    if body.body is not None:
        post.body = body.body
    if body.channels is not None:
        post.channels = body.channels
    if body.ai_assisted is not None:
        post.ai_assisted = body.ai_assisted
    if body.status is not None:
        post.status = body.status

    # Use model_fields_set so explicit None clears nullable fields
    if "scheduled_at" in body.model_fields_set:
        post.scheduled_at = body.scheduled_at
    if "media_url" in body.model_fields_set:
        post.media_url = body.media_url

    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


# ── Delete post ───────────────────────────────────────────────────────────────


@router.delete(
    "/posts/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="İçerik gönderisini sil",
)
def delete_post(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    post = _require_post(post_id, membership.tenant_id, db)
    db.delete(post)
    db.commit()


# ── Workflow transitions ──────────────────────────────────────────────────────


@router.post(
    "/posts/{post_id}/submit",
    response_model=ContentPostResponse,
    summary="Gönderiyi onay için sun (draft → pending_approval)",
)
def submit_post(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)
    post.status = "pending_approval"
    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


@router.post(
    "/posts/{post_id}/approve",
    response_model=ContentPostResponse,
    summary="Gönderiyi onayla (pending_approval → approved)",
)
def approve_post(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)
    post.status = "approved"
    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


@router.post(
    "/posts/{post_id}/reject",
    response_model=ContentPostResponse,
    summary="Gönderiyi reddet (→ draft) ve not ekle",
)
def reject_post(
    post_id: uuid.UUID,
    body: RejectBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)
    post.status = "draft"
    post.approval_note = body.note
    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


@router.post(
    "/posts/{post_id}/schedule",
    response_model=ContentPostResponse,
    summary="Gönderiyi planla (→ scheduled) ve yayın zamanı ata",
)
def schedule_post(
    post_id: uuid.UUID,
    body: ScheduleBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> ContentPostResponse:
    post = _require_post(post_id, membership.tenant_id, db)
    post.status = "scheduled"
    post.scheduled_at = body.scheduled_at
    db.add(post)
    db.commit()
    db.refresh(post)
    return ContentPostResponse.from_orm_obj(post)


@router.post(
    "/posts/{post_id}/publish",
    summary="Canlı yayına al — kimlik doğrulama gerektirir (şu anda kullanılamaz)",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
def publish_post(
    post_id: uuid.UUID,  # noqa: ARG001 — parameter kept for clean URL routing
    db: Session = Depends(get_db),  # noqa: ARG001
    membership: Membership = Depends(get_current_membership),  # noqa: ARG001
) -> None:
    """Canlı yayın için kanal kimlik doğrulaması (OAuth) gerekli.

    Bu endpoint her zaman HTTP 501 döner.

    Canlı yayın (publish) işlevi, her sosyal medya kanalı için OAuth erişim
    tokenlarını gerektirmektedir (Instagram Graph API, Facebook Page API,
    Twitter/X v2, LinkedIn API, TikTok for Business, YouTube Data API).
    Bu kimlik bilgileri, Entegrasyonlar bağlayıcı katmanı tarafından yönetilmekte
    olup bu sürümde henüz sosyal kanallar için yapılandırılmamıştır.

    Kullanılabilir işlevler
    -----------------------
    - İçerik planlama ve taslak oluşturma
    - Onay akışı (draft → pending_approval → approved → scheduled)
    - Yapay zeka destekli altyazı üretimi (/content/ai-caption)
    - Takvim görünümü (scheduled_at ile)

    Bu durum bir hata DEĞİLDİR — kimlik doğrulama kasıtlı olarak geçit
    görevi görmektedir.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Canlı yayın için kanal kimlik doğrulaması (OAuth) gerekli. "
            "Bu sürümde içerik planlama, taslak ve onay akışı kullanılabilir."
        ),
    )


# ── AI caption ────────────────────────────────────────────────────────────────


@router.post(
    "/ai-caption",
    response_model=AICaptionResponse,
    summary="Yapay zeka destekli sosyal medya altyazısı oluştur (DB yazımı yok)",
)
def ai_caption(
    body: AICaptionRequest,
    membership: Membership = Depends(get_current_membership),  # noqa: ARG001 — auth gate
) -> AICaptionResponse:
    """Verilen brief için Türkçe bir sosyal medya altyazısı üretir.

    API anahtarı yapılandırılmamışsa şablon tabanlı (deterministik) yol
    kullanılır.  Hiçbir zaman HTTP hatası fırlatılmaz.  DB'ye herhangi bir
    kayıt yapılmaz.

    Parametreler
    ------------
    brief   — İçerik özeti (zorunlu)
    channel — Hedef kanal (isteğe bağlı; ör: "instagram")
    tone    — Ton (varsayılan: "profesyonel")

    Yanıt
    -----
    caption     — Oluşturulan gönderi metni
    hashtags    — 3-5 küçük harfli hashtag listesi
    ai_assisted — Claude API yolu kullanıldıysa True, şablon kullanıldıysa False
    """
    result = generate_caption(
        brief=body.brief,
        channel=body.channel,
        tone=body.tone,
    )
    return AICaptionResponse(**result)
