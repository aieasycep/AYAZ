"""Consent Mode v2 / granular KVKK consent (Dalga 54).

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-28

What this migration adds
------------------------
All changes are ADDITIVE and NULLABLE (no enums, no breaking schema changes):

1. ``conversion_events.consent_signals``  (JSON, nullable)
   Stores the four Consent Mode v2 signal keys after normalization:
   {"ad_storage": bool, "ad_user_data": bool,
    "ad_personalization": bool, "analytics_storage": bool}
   NULL for events ingested before this column exists — treated as all-denied
   at forward time (preserves existing skipped_no_consent behaviour).

2. ``event_destinations.required_consent``  (JSON, nullable)
   List of signal key strings ALL of which must be granted for the event to
   be forwarded to this destination.
   NULL / empty → platform-specific code default:
     meta_capi      → ["ad_user_data"]
     tiktok_events  → ["ad_user_data"]
     ga4_mp         → ["analytics_storage"]
   Ignored entirely when ``consent_required`` is False.

3. ``tracking_sources.consent_cookie_var``  (String 200, nullable)
   JS variable/cookie name the generated snippet reads to auto-populate
   the consent field.  NULL → snippet sends ``consent: false`` (current
   behaviour unchanged).

Backward compatibility
----------------------
* A plain ``consent: true/false`` collect call behaves exactly as before.
* Existing rows with NULL consent_signals are treated as all-False signals;
  existing destinations with NULL required_consent use platform defaults.
* The overall ``consent`` bool on ConversionEvent is preserved and updated
  using the rule: consent = (ad_user_data OR analytics_storage) which matches
  the intent of the pre-existing boolean for GDPR/KVKK purposes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Granular consent signals on each event
    op.add_column(
        "conversion_events",
        sa.Column(
            "consent_signals",
            sa.JSON(),
            nullable=True,
            comment=(
                "Consent Mode v2 granular signals: "
                '{"ad_storage": bool, "ad_user_data": bool, '
                '"ad_personalization": bool, "analytics_storage": bool}. '
                "NULL for legacy events (treated as all-denied)."
            ),
        ),
    )

    # 2. Per-destination required consent signal keys
    op.add_column(
        "event_destinations",
        sa.Column(
            "required_consent",
            sa.JSON(),
            nullable=True,
            comment=(
                "List of Consent Mode v2 signal keys ALL required for forwarding. "
                "NULL/[] → platform default. Ignored when consent_required=False."
            ),
        ),
    )

    # 3. JS consent cookie/variable name on the source
    op.add_column(
        "tracking_sources",
        sa.Column(
            "consent_cookie_var",
            sa.String(200),
            nullable=True,
            comment=(
                "JS variable / cookie name the snippet reads for consent signals. "
                "NULL → snippet sends consent: false (existing behaviour)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("tracking_sources", "consent_cookie_var")
    op.drop_column("event_destinations", "required_consent")
    op.drop_column("conversion_events", "consent_signals")
