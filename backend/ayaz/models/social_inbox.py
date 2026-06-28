"""Sosyal Gelen Kutusu (Social Inbox) data model — M13.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as other model modules).

Type/status columns
-------------------
All type and status columns use ``String`` to avoid the duplicate-type migration
bug documented in 0001_initial_schema.py.  Allowed values are enforced at the
Pydantic/service layer.

SocialMessage
-------------
An inbound social-media message (DM, comment, or mention) that arrives in the
unified Social Inbox.  Messages are normally populated by the platform sync job
(connector layer).  The ``external_id`` field holds the platform's own identifier
and is used for deduplication when live sync is active.

Live sync + reply delivery are intentionally credential-gated: a reply is stored
with ``delivered=False`` and never pushed to the platform unless the connector has
valid OAuth tokens.

SocialReply
-----------
An outbound reply authored by a team agent (or AI-assisted).  ``delivered=False``
is the default — live delivery to the social platform requires credentials managed
by the connector layer.

Status values (SocialMessage.status)
--------------------------------------
"open"      – new / unread; nobody is working on it yet
"pending"   – agent has started working on it
"resolved"  – conversation closed
"snoozed"   – temporarily deferred

Sentiment values (SocialMessage.sentiment)
-------------------------------------------
"positive"  – detected or manually set positive sentiment
"neutral"   – neutral (default)
"negative"  – detected or manually set negative sentiment

Channel values (SocialMessage.channel)
---------------------------------------
"instagram" | "facebook" | "x" | "linkedin" | "tiktok" | "youtube"

Kind values (SocialMessage.kind)
---------------------------------
"dm" | "comment" | "mention"
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import Base, TimestampMixin, uuid_pk

# ── Allowed value sets (imported by API/service layers) ───────────────────────

VALID_CHANNELS: frozenset[str] = frozenset(
    {"instagram", "facebook", "x", "linkedin", "tiktok", "youtube"}
)
VALID_KINDS: frozenset[str] = frozenset({"dm", "comment", "mention"})
VALID_STATUSES: frozenset[str] = frozenset({"open", "pending", "resolved", "snoozed"})
VALID_SENTIMENTS: frozenset[str] = frozenset({"positive", "neutral", "negative"})


# ── SocialMessage ─────────────────────────────────────────────────────────────


class SocialMessage(Base, TimestampMixin):
    """An inbound social-media message (DM / comment / mention).

    Normally populated by the platform sync job.  Exposed via POST for seeding,
    manual testing, and demo data injection.

    external_id
    -----------
    The platform's own message/comment identifier.  Used for deduplication when
    live sync is active.  NULL is allowed when the message is created manually
    (e.g. seed data).

    received_at
    -----------
    ISO-8601 string representing when the message was received on the platform.
    Stored as Text for SQLite portability (same as ConversionEvent.created_at).

    tags
    ----
    Agent-applied labels (JSON string array).  Replaced wholesale on every
    update; no individual tag add/remove endpoint is provided.
    """

    __tablename__ = "social_messages"
    __table_args__ = (
        Index("ix_social_messages_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    # Channel and message kind
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="instagram | facebook | x | linkedin | tiktok | youtube",
    )
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="dm | comment | mention",
    )

    # Platform dedup key — nullable for manually-created / seed messages
    external_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Platform-native message/comment identifier; used for dedup on live sync",
    )

    # Author info
    author_handle: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="Platform @handle of the message author",
    )
    author_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Display name of the message author (optional)",
    )

    # Message body
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full text of the inbound message",
    )

    # Link to the original post/thread on the platform
    permalink: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="URL of the original post/comment/thread on the platform",
    )

    # Sentiment — auto-classified at ingest; can be overridden by an agent
    sentiment: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="neutral",
        server_default="'neutral'",
        comment="positive | neutral | negative",
    )

    # Workflow status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="'open'",
        comment="open | pending | resolved | snoozed",
    )

    # Agent assignment (display name or email of the responsible agent)
    assignee: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Display name/email of the agent assigned to this message",
    )

    # Agent-applied labels
    tags: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="'[]'",
        comment="Agent-applied label list (JSON string array)",
    )

    # When the message was received on the platform (ISO-8601)
    received_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ISO-8601 UTC datetime when the message was received on the platform",
    )

    # Relationships
    replies: Mapped[list["SocialReply"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="SocialReply.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<SocialMessage id={self.id} channel={self.channel!r}"
            f" kind={self.kind!r} status={self.status!r} tenant={self.tenant_id}>"
        )


# ── SocialReply ───────────────────────────────────────────────────────────────


class SocialReply(Base):
    """An outbound reply authored by a team agent (or AI-assisted).

    delivered
    ---------
    Always False until live delivery via the connector layer is activated.
    Live delivery requires per-channel OAuth tokens managed by the Integrations
    connector layer.  Recording the reply in AYAZ with ``delivered=False`` is
    the default — the reply is stored for audit and never silently lost.

    ai_assisted
    -----------
    True when the reply body was generated (or seeded) via the AI suggest-reply
    endpoint.  Set to False when the agent typed the reply manually.
    """

    __tablename__ = "social_replies"
    __table_args__ = (
        Index("ix_social_replies_tenant_id", "tenant_id"),
        Index("ix_social_replies_message_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_messages.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent SocialMessage that this reply addresses",
    )

    # Reply body
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Text body of the outbound reply",
    )

    # Who wrote the reply (agent display name / email)
    author: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Display name/email of the agent who wrote the reply",
    )

    # Delivery status — always False until connector layer delivers it live
    delivered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="'0'",
        comment=(
            "False until live delivery via the connector layer. "
            "Live delivery requires per-channel OAuth tokens."
        ),
    )

    # Whether this reply was AI-generated via suggest-reply
    ai_assisted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="'0'",
        comment="True when the reply body came from the AI suggest-reply path",
    )

    # Creation timestamp stored as ISO-8601 Text for SQLite portability
    created_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ISO-8601 UTC datetime when the reply was recorded in AYAZ",
    )

    # Relationships
    message: Mapped["SocialMessage"] = relationship(back_populates="replies")

    def __repr__(self) -> str:
        return (
            f"<SocialReply id={self.id} message={self.message_id}"
            f" delivered={self.delivered} tenant={self.tenant_id}>"
        )
