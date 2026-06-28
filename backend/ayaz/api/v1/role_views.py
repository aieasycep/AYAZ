"""Rol Görünümü (Role-based views) API — Dalga 75.

Her pazarlama ekibine kendi önceliklerine göre özelleştirilmiş bir kokpit sunar.
Tüm veriler mevcut servislerden okunur; yeni model veya migration yoktur.

Endpoints
---------
    GET /role-views/roles
        Tanımlı 5 rolün kısa listesini döndürür.

    GET /role-views/{role}
        Verilen rol için tam kokpit görünümünü döndürür.
        Bilinmeyen rol → 404.

Tenant-scoped: geçerli JWT + ``tid`` claim gerektirir.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.role_views import get_role_view, list_roles

router = APIRouter(prefix="/role-views", tags=["role-views"])


# ── Yanıt modelleri ───────────────────────────────────────────────────────────


class RoleListItem(BaseModel):
    key: str
    label: str
    description: str
    icon_key: str


class RoleMetric(BaseModel):
    label: str
    value: str
    hint: str


class RoleAttentionItem(BaseModel):
    title: str
    detail: str
    severity: str  # "high" | "medium" | "low"
    href: str


class RolePriorityScreen(BaseModel):
    href: str
    label: str
    why: str


class RoleQuickAction(BaseModel):
    label: str
    href: str


class RoleViewResponse(BaseModel):
    role: str
    label: str
    description: str
    icon_key: str
    generated_at: str
    metrics: list[RoleMetric]
    attention: list[RoleAttentionItem]
    priority_screens: list[RolePriorityScreen]
    quick_actions: list[RoleQuickAction]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/roles",
    response_model=list[RoleListItem],
    summary=(
        "Rol Listesi — tanımlı 5 pazarlama rolünü sıralarıyla döndürür. "
        "Her öğe rol anahtarı, Türkçe etiket, açıklama ve ikon anahtarı içerir."
    ),
)
def get_roles(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[RoleListItem]:
    """Tanımlı pazarlama rollerinin kısa listesini döndürür.

    Performans, Marcom, Müşteri Hizmetleri, Planlama ve Yönetim rollerini
    tanımlandıkları sırayla listeler.

    Raises
    ------
    401 — JWT eksik veya geçersiz.
    403 — Tenant claim aktif bir membership ile eşleşmiyor.
    """
    roles = list_roles()
    return [RoleListItem(**r) for r in roles]


@router.get(
    "/{role}",
    response_model=RoleViewResponse,
    summary=(
        "Rol Görünümü — verilen role özel KPI, dikkat öğeleri, öncelikli ekranlar "
        "ve hızlı aksiyonlardan oluşan tam kokpit görünümü."
    ),
)
def get_role_view_endpoint(
    role: str,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> RoleViewResponse:
    """Belirtilen rol için özelleştirilmiş kokpit görünümü döndürür.

    ``role`` parametresi geçerli anahtarlardan biri olmalıdır:
    ``performans``, ``marcom``, ``musteri_hizmetleri``, ``planlama``, ``yonetim``.

    Veriler mevcut AYAZ servislerinden okunur ve tenant_id ile izole edilir;
    hiçbir zaman başka bir kiracının verisi döndürülmez.

    Raises
    ------
    404 — bilinmeyen rol anahtarı.
    401 — JWT eksik veya geçersiz.
    403 — Tenant claim aktif bir membership ile eşleşmiyor.
    """
    try:
        result = get_role_view(db, membership.tenant_id, role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return RoleViewResponse(**result)
