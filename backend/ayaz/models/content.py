"""İçerik Planlayıcı (Content Planner) ORM model — M8.

Multi-tenancy
-------------
All rows carry ``tenant_id`` for explicit per-query filtering until Postgres RLS
policies are enabled (same pattern as other model modules).

Type / status columns
---------------------
All status values are stored as ``String`` to avoid the duplicate-type migration
bug documented in 0001_initial_schema.py.  Allowed values are enforced at the
Pydantic / service layer.

ContentPost
-----------
A planned or published social-media post.  Live publishing is intentionally
credential-gated: the ``publish`` action always raises 501 until OAuth tokens
for each channel are connected via the Integrations connector layer.

Status lifecycle
----------------
  draft            – initial state (default)
  pending_approval – submitted for review
  approved         – approved, not yet scheduled
  scheduled        – approved and a publish time is set
  published        – pushed live (requires channel OAuth — not available in v1)
  archived         – withdrawn / no longer relevant

VALID_CHANNELS
--------------
{"instagram", "facebook", "x", "linkedin", "tiktok", "youtube"}
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import GUID as UUID
from ayaz.models.base import Base, TimestampMixin, uuid_pk

# ── Allowed values (also re-exported for use by the service + API layers) ──────

VALID_CHANNELS: set[str] = {
    "instagram",
    "facebook",
    "x",
    "linkedin",
    "tiktok",
    "youtube",
}

VALID_STATUSES: set[str] = {
    "draft",
    "pending_approval",
    "approved",
    "scheduled",
    "published",
    "archived",
}


# ── ContentPost ────────────────────────────────────────────────────────────────


class ContentPost(Base, TimestampMixin):
    """A planned social-media content post.

    channels (JSON list of strings)
    --------------------------------
    Each entry is a member of VALID_CHANNELS.  Stored as a JSON array so no
    Postgres ARRAY or ENUM type is needed, keeping the schema portable to SQLite
    for tests.

    scheduled_at (Text, nullable)
    ------------------------------
    ISO-8601 datetime string (e.g. "2026-07-01T09:00:00+03:00").  Stored as
    Text to avoid timezone-conversion complexity across dialects.  Validated by
    the API layer when set.

    ai_assisted (Boolean)
    ----------------------
    True when the caption / body was generated (at least partially) via the
    Claude AI path in ``ayaz.services.content.generate_caption``.

    Live-publish gate
    -----------------
    The ``publish`` API action (POST /content/posts/{id}/publish) intentionally
    returns HTTP 501 in this version.  Credential-based live publishing requires
    per-channel OAuth tokens managed by the Integrations connector layer, which
    is not yet wired for social channels.  The status field and workflow
    (draft → pending_approval → approved → scheduled) are fully functional.
    """

    __tablename__ = "content_posts"
    __table_args__ = (
        Index("ix_content_posts_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Short label for the post (shown in the calendar grid)",
    )

    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="''",
        comment="Caption / post body text",
    )

    # JSON list of channel key strings, e.g. ["instagram", "facebook"]
    channels: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="'[]'",
        comment="Target channels; members of VALID_CHANNELS",
    )

    # ISO-8601 string; nullable until the post is scheduled
    scheduled_at: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 datetime string for when the post is to be published",
    )

    # "draft" | "pending_approval" | "approved" | "scheduled" | "published" | "archived"
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        server_default="'draft'",
        comment=(
            "draft | pending_approval | approved | scheduled | published | archived"
        ),
    )

    approval_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reviewer note (populated on reject)",
    )

    media_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="URL of an attached image or video asset",
    )

    ai_assisted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="'0'",
        comment="True when the caption was generated via the Claude AI path",
    )

    def __repr__(self) -> str:
        return (
            f"<ContentPost id={self.id} title={self.title!r}"
            f" status={self.status!r} tenant={self.tenant_id}>"
        )
