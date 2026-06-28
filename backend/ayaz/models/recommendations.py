"""Öneri Durumu (Recommendation State) data model — M14 Proaktif Öneri Merkezi.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as other model modules).

Type/status columns
-------------------
All type and status columns use ``String`` to avoid the duplicate-type migration
bug documented in 0001_initial_schema.py.  Allowed values are enforced at the
Pydantic/service layer.

RecommendationState
-------------------
Persists the accept/snooze/dismiss/reopen workflow state for a recommendation.
The ``recommendation_key`` is a stable, deterministic string produced by the
synthesis engine (e.g. "budget:overspend", "benchmark:weak_roas:tiktok").  The
unique constraint on (tenant_id, recommendation_key) means one state row per
recommendation per tenant.

Status values
-------------
"open"      – default; no action taken
"accepted"  – user acknowledged / accepted the recommendation
"snoozed"   – temporarily deferred; snoozed_until is set
"dismissed" – permanently dismissed
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import Base, TimestampMixin, uuid_pk


VALID_STATUSES: frozenset[str] = frozenset(
    {"open", "accepted", "snoozed", "dismissed"}
)
VALID_ACTIONS: frozenset[str] = frozenset(
    {"accept", "snooze", "dismiss", "reopen"}
)


class RecommendationState(Base, TimestampMixin):
    """Persisted workflow state for a single recommendation.

    recommendation_key
    ------------------
    Stable, deterministic key emitted by the synthesis engine.
    Form: "<category>:<subtype>" or "<category>:<subtype>:<channel>".
    Examples: "budget:overspend", "benchmark:weak_roas:tiktok".

    status
    ------
    "open" | "accepted" | "snoozed" | "dismissed"

    snoozed_until
    -------------
    Non-null only when status == "snoozed".  ISO-8601 UTC datetime stored as
    DateTime(timezone=True) for portable comparison queries.

    note
    ----
    Optional user-supplied note attached to the action.
    """

    __tablename__ = "recommendation_states"
    __table_args__ = (
        Index("ix_recommendation_states_tenant_id", "tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "recommendation_key",
            name="uq_recommendation_states_tenant_key",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    recommendation_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Stable deterministic key: <category>:<subtype>[:<channel>]",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="'open'",
        comment="open | accepted | snoozed | dismissed",
    )

    snoozed_until: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC datetime when the snooze expires; null unless snoozed",
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional user-supplied note attached to the action",
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationState id={self.id} key={self.recommendation_key!r}"
            f" status={self.status!r} tenant={self.tenant_id}>"
        )
