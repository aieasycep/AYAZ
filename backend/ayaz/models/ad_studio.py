"""AI Reklam Metni Stüdyosu (Ad Copy Studio) data model — M15 Dalga 73.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as other model modules).

Type/status columns
-------------------
All type and status columns use ``String`` to avoid the duplicate-type migration
bug documented in 0001_initial_schema.py.  Allowed values are enforced at the
Pydantic/service layer.

AdCopyDraft
-----------
Persists a generated ad copy draft for a given tenant.  The ``brief`` column
stores the input brief dict as JSON; the ``variants`` column stores the
generated variants list as JSON (same shape as the generate_ad_copy response).

Status values
-------------
"saved"    – default; draft is saved and visible in the library
"archived" – user has archived the draft; hidden from default list view
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Index,
    JSON,
    String,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import Base, TimestampMixin, uuid_pk


VALID_PLATFORMS: frozenset[str] = frozenset(
    {"google_ads", "meta_ads", "tiktok_ads"}
)
VALID_STATUSES: frozenset[str] = frozenset({"saved", "archived"})
VALID_SOURCES: frozenset[str] = frozenset({"template", "ai"})


class AdCopyDraft(Base, TimestampMixin):
    """Persisted ad copy draft for a single tenant.

    platform
    --------
    "google_ads" | "meta_ads" | "tiktok_ads"

    title
    -----
    Short label supplied by the user, e.g. the product name.

    brief
    -----
    The input brief dict (platform, product, value_prop, tone, keywords,
    audience) as submitted to generate_ad_copy.

    variants
    --------
    The generated variants list as returned by generate_ad_copy (list of
    dicts with index + fields list).

    source
    ------
    "template" (deterministic) | "ai" (Claude-generated).

    status
    ------
    "saved" | "archived"
    """

    __tablename__ = "ad_copy_drafts"
    __table_args__ = (
        Index("ix_ad_copy_drafts_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="google_ads | meta_ads | tiktok_ads",
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Short user-supplied label, e.g. product name",
    )

    brief: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Input brief dict (platform, product, value_prop, tone, keywords, audience)",
    )

    variants: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        comment="Generated variants list — same shape as generate_ad_copy response",
    )

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="template",
        server_default="'template'",
        comment="template | ai",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="saved",
        server_default="'saved'",
        comment="saved | archived",
    )

    def __repr__(self) -> str:
        return (
            f"<AdCopyDraft id={self.id} platform={self.platform!r}"
            f" title={self.title!r} status={self.status!r} tenant={self.tenant_id}>"
        )
