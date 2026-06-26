"""Briefing ORM model — daily AI-generated Turkish digest.

Design notes
------------
* All enum-like and date columns use ``sa.String`` — no Postgres ENUM, keeping
  SQLite compatibility for tests.
* ``briefing_date`` is stored as String(10) ISO-8601 text (YYYY-MM-DD) to match
  the ``period_start`` / ``period_end`` convention used in goals.py and elsewhere.
* ``body`` is JSON (dict): structured sections for the digest.  Not JSONB so
  SQLite in tests works without dialect magic.
* Idempotency key is (tenant_id, briefing_date) — enforced via a unique index
  and service-layer upsert logic.

Body shape
----------
{
  "performance_delta": {
    "yesterday":    {"spend": float, "conversions": float, "roas": float},
    "prior_day":    {"spend": float, "conversions": float, "roas": float},
    "delta":        {"spend_pct": float, "conversions_pct": float, "roas_pct": float}
  },
  "top_insights": [
    {"id": str, "category": str, "severity": str, "title": str, "score": float}
    // up to 3 items
  ],
  "top_recommendation": {
    "campaign_id": str, "campaign_name": str, "channel": str,
    "category": str, "message": str, "suggested_action": str, "score": float
  } | null,
  "goals_status": [
    {"goal_id": str, "name": str, "metric": str,
     "status": str, "pct_to_target": float, "recommendation": str}
  ]
}
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ayaz.models.base import Base, TimestampMixin, uuid_pk


class Briefing(Base, TimestampMixin):
    """A tenant-scoped daily AI digest in Turkish.

    Attributes
    ----------
    id:
        UUID primary key.
    tenant_id:
        Tenant this briefing belongs to (isolation filter on every query).
    briefing_date:
        The calendar date the briefing covers, as ISO-8601 text (YYYY-MM-DD).
        Together with ``tenant_id`` this forms the idempotency key.
    headline:
        A single Turkish sentence summarising the most important signal of the
        day.  Either Claude-generated (when API key present) or deterministic
        template.
    body:
        JSON dict with structured sections:
        ``performance_delta``, ``top_insights``, ``top_recommendation``,
        ``goals_status``.  See module docstring for the exact shape.
    created_at / updated_at:
        Supplied by ``TimestampMixin``.
    """

    __tablename__ = "briefings"
    __table_args__ = (
        Index("ix_briefings_tenant_date", "tenant_id", "briefing_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Tenant that owns this briefing (RLS: filter on every query)",
    )

    briefing_date: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="ISO-8601 date (YYYY-MM-DD) of the day this briefing covers",
    )

    headline: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Turkish one-liner headline — Claude-generated or template",
    )

    body: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment=(
            "Structured sections: performance_delta, top_insights, "
            "top_recommendation, goals_status"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Briefing id={self.id} tenant={self.tenant_id}"
            f" date={self.briefing_date}>"
        )
