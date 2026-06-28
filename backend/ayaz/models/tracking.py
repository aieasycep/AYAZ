"""Server-side Tracking / Conversions API data model — M7.

Multi-tenancy
-------------
All tables carry ``tenant_id`` for explicit filtering until Postgres RLS
policies are deployed (same pattern as other model modules).

Type/status columns
-------------------
All type and status columns use ``String`` to avoid the duplicate-type migration
bug documented in 0001_initial_schema.py.  Allowed values are enforced at the
Pydantic/service layer.

TrackingSource
--------------
A named first-party data source that emits conversion events.  Identified by a
``public_token`` (URL-safe random string, 32 bytes) that acts as the write key
in the collect URL.  One source can fan out to many EventDestinations.

EventDestination
----------------
A platform-specific forwarding target for events.  The access token / pixel
secret lives in Vault (``vault_secret_ref``); only non-secret config (pixel_id,
dataset_id, measurement_id) is stored in the ``config`` JSON column.

ConversionEvent
---------------
Immutable event record.  PII has already been hashed by the time a row is
written — ``user_data`` contains only SHA-256 hashed identifiers.  The
``status`` column tracks the event through its lifecycle.

Status values
-------------
"received"            – ingested and persisted; forwarding not yet attempted
"forwarded"           – successfully forwarded to all active destinations
"failed"              – one or more destination forwards failed (see ``error``)
"skipped_no_consent"  – consent was required by at least one destination but
                        the event payload did not include consent=true
"duplicate"           – event_id already exists for this tracking_source_id;
                        the pre-existing event is returned without re-forwarding
"disabled"            – the event_name is in the source's disabled_events list;
                        the event is recorded but NOT forwarded to any destination

Platform values (EventDestination.platform)
-------------------------------------------
"meta_capi"       – Meta Conversions API (Graph API v21.0)
"tiktok_events"   – TikTok Events API (Business API v1.3)
"ga4_mp"          – Google Analytics 4 Measurement Protocol
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

from ayaz.models.base import Base, TimestampMixin, uuid_pk


# ── TrackingSource ────────────────────────────────────────────────────────────


class TrackingSource(Base, TimestampMixin):
    """A named first-party data source.

    The ``public_token`` is a URL-safe random string (32 bytes) that acts as
    the write key in the collect URL::

        POST /api/v1/tracking/collect/{public_token}

    This token is the sole secret protecting the public ingest endpoint.
    Rotate it to invalidate existing embedded snippets.

    domain
    ------
    Optional site domain (e.g. ``"shop.example.com"``) for informational
    display and future CORS allowlisting.  Not enforced by the service layer.
    """

    __tablename__ = "tracking_sources"
    __table_args__ = (
        Index("ix_tracking_sources_tenant_id", "tenant_id"),
        UniqueConstraint("public_token", name="uq_tracking_sources_public_token"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Human-readable label for this data source",
    )

    domain: Mapped[str | None] = mapped_column(
        String(253),
        nullable=True,
        comment="Site domain (optional; informational)",
    )

    # URL-safe random token used as the write key — never store as a hash here
    # because it must be returned in plain text for snippet generation.
    public_token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="Write key in the collect URL; rotate to revoke access",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive sources reject inbound events with 404",
    )

    # Per-event enable/disable: list of event_name strings whose forwarding is
    # suppressed.  An empty list (the default) means all events are enabled.
    # Stored as a JSON array; no Postgres ENUM is used.
    disabled_events: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="'[]'",
        comment="Event names whose forwarding is disabled (recorded but not forwarded)",
    )

    # Consent Mode v2 / KVKK: optional JS variable name (cookie or dataLayer key)
    # that the generated snippet reads to auto-populate the consent signals.
    # When None, the snippet sends consent: false (existing behaviour unchanged).
    consent_cookie_var: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment=(
            "JS variable / cookie name the snippet reads for consent signals. "
            "When set, the snippet reads window[consent_cookie_var] and passes "
            "it as the consent field (bool or granular object)."
        ),
    )

    # Relationships
    destinations: Mapped[list["EventDestination"]] = relationship(
        back_populates="tracking_source", cascade="all, delete-orphan"
    )
    events: Mapped[list["ConversionEvent"]] = relationship(
        back_populates="tracking_source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<TrackingSource id={self.id} name={self.name!r}"
            f" tenant={self.tenant_id}>"
        )


# ── EventDestination ──────────────────────────────────────────────────────────


class EventDestination(Base, TimestampMixin):
    """A platform-specific forwarding target for conversion events.

    platform values
    ---------------
    "meta_capi"       – Meta Conversions API
    "tiktok_events"   – TikTok Events API
    "ga4_mp"          – Google Analytics 4 Measurement Protocol

    config (JSON)
    -------------
    Non-secret platform configuration.  Secrets (access tokens, API secrets)
    are stored in Vault and referenced via ``vault_secret_ref``.

    meta_capi example:
        {"pixel_id": "123456789", "action_source": "website"}

    tiktok_events example:
        {"pixel_id": "ABCDE12345", "event_source": "web"}

    ga4_mp example:
        {"measurement_id": "G-XXXXXXXXXX"}

    vault_secret_ref
    ----------------
    Vault path or EncryptedColumnVault ref under which the access token lives.
    The service layer calls ``vault.get(vault_secret_ref)`` at forward time;
    the secret is NEVER written to this table.

    consent_required
    ----------------
    When True, events arriving without ``consent=true`` are silently skipped
    for this destination (status becomes "skipped_no_consent" if ALL active
    destinations require consent and the event has no consent).
    """

    __tablename__ = "event_destinations"
    __table_args__ = (
        Index("ix_event_destinations_tenant_id", "tenant_id"),
        Index("ix_event_destinations_tracking_source_id", "tracking_source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    tracking_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_sources.id", ondelete="CASCADE"),
        nullable=False,
    )

    # "meta_capi" | "tiktok_events" | "ga4_mp"
    platform: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="meta_capi | tiktok_events | ga4_mp",
    )

    # Non-secret platform config (pixel_id / measurement_id / dataset_id)
    config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Non-secret platform config; access token lives in Vault",
    )

    # Vault ref for the access token / API secret
    vault_secret_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Vault path — actual token never stored in this column",
    )

    consent_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Skip forwarding events without consent when True",
    )

    # Consent Mode v2 granular signals required for this destination.
    # JSON list of signal keys: any subset of
    #   ["ad_storage", "ad_user_data", "ad_personalization", "analytics_storage"]
    # ALL listed keys must be granted (True) in the event's consent_signals for
    # the event to be forwarded to this destination.
    # When NULL or empty, platform-specific defaults are applied at runtime:
    #   meta_capi      → ["ad_user_data"]
    #   tiktok_events  → ["ad_user_data"]
    #   ga4_mp         → ["analytics_storage"]
    # If consent_required is False, satisfaction is always True regardless.
    required_consent: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "Consent Mode v2 signal keys ALL required to forward. "
            "NULL/[] → platform default. Ignored when consent_required=False."
        ),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Relationships
    tracking_source: Mapped["TrackingSource"] = relationship(
        back_populates="destinations"
    )

    def __repr__(self) -> str:
        return (
            f"<EventDestination id={self.id} platform={self.platform!r}"
            f" source={self.tracking_source_id} tenant={self.tenant_id}>"
        )


# ── ConversionEvent ───────────────────────────────────────────────────────────


class ConversionEvent(Base):
    """An immutable server-side conversion event record.

    PII policy
    ----------
    ``user_data`` MUST contain only SHA-256 hashed identifiers when written to
    the database.  The service layer hashes raw PII via ``hash_identity()``
    before calling this model's constructor.  Raw email / phone is NEVER
    persisted or logged.

    Deduplication
    -------------
    ``event_id`` + ``tracking_source_id`` form a soft-unique key.  The service
    layer checks for an existing row before inserting; if found it returns the
    existing event with status "duplicate" without forwarding again.

    A database-level UniqueConstraint is intentionally NOT added because:
    1. We want to handle the race at the application layer with a clear status.
    2. Partial uniqueness (active vs. duplicate) is application logic, not DB.

    status values
    -------------
    "received"           – ingested; forwarding not yet attempted
    "forwarded"          – forwarded to all active destinations successfully
    "failed"             – forward attempted but at least one destination errored
    "skipped_no_consent" – no consent when at least one destination requires it
    "duplicate"          – event_id already seen for this source
    "disabled"           – event_name is in source.disabled_events; recorded but not forwarded

    forwarded_count
    ---------------
    Number of destinations to which the event was successfully forwarded.
    """

    __tablename__ = "conversion_events"
    __table_args__ = (
        Index("ix_conversion_events_tenant_id", "tenant_id"),
        Index("ix_conversion_events_tracking_source_id", "tracking_source_id"),
        Index(
            "ix_conversion_events_source_event_id",
            "tracking_source_id",
            "event_id",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )

    tracking_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_sources.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Platform-agnostic event name (e.g. Purchase, AddToCart)",
    )

    # ISO-8601 UTC datetime string — stored as Text to avoid timezone complexity
    # in SQLite and to keep the value exactly as the client sent it.
    event_time: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ISO-8601 UTC event time as supplied by the client",
    )

    # Caller-supplied dedup key (e.g. order_id, session-event UUID)
    event_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Caller-supplied dedup key; unique per tracking_source",
    )

    # Pre-hashed user identifiers (email_hash, phone_hash, etc.)
    # Raw PII MUST NOT be written to this column.
    user_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="SHA-256 hashed user identifiers only — no raw PII",
    )

    # Event-specific payload (value, currency, contents, etc.)
    custom_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Non-PII event payload (value, currency, product data, etc.)",
    )

    # KVKK/GDPR consent flag from the payload.
    # "overall" consent: True when ad_user_data OR analytics_storage is granted
    # (or when a plain boolean True is sent).  Kept for backward compatibility —
    # all existing code that gates on this bool continues to work unchanged.
    consent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment=(
            "Overall consent flag (backward compat). True when ad_user_data OR "
            "analytics_storage is granted, or when a plain consent:true bool is sent."
        ),
    )

    # Consent Mode v2 granular signals stored verbatim after normalization.
    # Shape: {"ad_storage": bool, "ad_user_data": bool,
    #         "ad_personalization": bool, "analytics_storage": bool}
    # NULL for events ingested before this column was added (treated as all-False
    # at forwarding time — i.e. existing behaviour is preserved).
    consent_signals: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "Consent Mode v2 granular signals dict. "
            "NULL for legacy events (treated as all-denied at forward time)."
        ),
    )

    # Match quality (Event Match Quality / EMQ-style) computed at ingest from the
    # RAW user_data payload — BEFORE hashing — so it can see which identity signals
    # were supplied (email/phone/fbc/fbp/external_id/IP/UA/name/geo).
    # Shape: {"score": int 0-100, "tier": "weak|medium|good|excellent",
    #         "present": [canonical signal keys ordered by weight desc]}
    # KVKK note: only the SET of present field keys is stored here — never the raw
    # values of IP / user agent / etc.  NULL for events ingested before this column.
    match_quality: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "Event Match Quality score/tier/present-keys computed at ingest. "
            "Stores only which identity signals were present, never raw values. "
            "NULL for legacy events."
        ),
    )

    # "received" | "forwarded" | "failed" | "skipped_no_consent" | "duplicate" | "disabled"
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="received",
        comment="received | forwarded | failed | skipped_no_consent | duplicate | disabled",
    )

    # Number of destinations to which the event was successfully forwarded
    forwarded_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Last error message from a failed forward attempt (nullable)
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error detail from a failed platform forward attempt",
    )

    created_at: Mapped[datetime] = mapped_column(
        # Use Text for SQLite compatibility (same as other models' nullable Text dates)
        Text,
        nullable=False,
        comment="ISO-8601 UTC datetime of ingest",
    )

    # Relationships
    tracking_source: Mapped["TrackingSource"] = relationship(
        back_populates="events"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversionEvent id={self.id} name={self.event_name!r}"
            f" status={self.status!r} tenant={self.tenant_id}>"
        )
