"""Event Match Quality score on conversion events (Dalga 55).

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-28

What this migration adds
------------------------
``conversion_events.match_quality``  (JSON, nullable)

Stores the Event-Match-Quality (EMQ-style) score computed at ingest time from
the RAW user_data payload (before PII hashing), so AYAZ can show how well each
event will match on the ad platforms:

    {"score": int 0-100,
     "tier":  "weak" | "medium" | "good" | "excellent",
     "present": ["em", "ph", "fbc", ...]}   # canonical signal keys, weight desc

KVKK / privacy
--------------
Only the SET of present identity-signal keys is persisted — never the raw
values of IP address, user agent, name, etc.  This lets the dashboard report
match-quality coverage without retaining additional personal data.

Backward compatibility
----------------------
The column is ADDITIVE and NULLABLE (no enum, no default backfill).  Events
ingested before this migration keep ``match_quality = NULL`` and are simply
excluded from the match-quality aggregates (``scored_events``).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversion_events",
        sa.Column(
            "match_quality",
            sa.JSON(),
            nullable=True,
            comment=(
                "Event Match Quality score/tier/present-keys computed at ingest. "
                "Stores only which identity signals were present, never raw values. "
                "NULL for legacy events."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversion_events", "match_quality")
