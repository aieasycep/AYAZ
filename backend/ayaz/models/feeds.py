"""Feed Management models — M5 (Channable-style).

Multi-tenancy
-------------
All tables carry ``tenant_id`` and must be filtered explicitly until Postgres RLS
policies are deployed (see oltp.py for the same pattern and the TODO comment).

Type/status columns
--------------------
All type and status fields use ``sa.String`` rather than Postgres ENUM types to
avoid the duplicate-type migration bug documented in 0001_initial_schema.py.
Allowed values are validated at the application/Pydantic layer.

Feed flow
---------
  FeedSource ──(products)──> FeedProduct
  FeedSource ──(channels)──> FeedChannel ──(rules)──> FeedRule

Public URL scheme
-----------------
  GET /api/v1/feeds/public/{public_token}
  The public_token on FeedChannel is a 32-byte urlsafe random string (no auth
  required — the token itself is the secret).  Users paste this URL into
  Google Merchant Center, Meta Catalog, TikTok Catalog, etc.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base, TimestampMixin, uuid_pk

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover — should never happen on SA 2.x
    from sqlalchemy import Text as JSON  # type: ignore[assignment]

# ── FeedSource ────────────────────────────────────────────────────────────────


class FeedSource(Base, TimestampMixin):
    """One product catalogue uploaded or fetched from a URL.

    source_type values
    ------------------
    "url_xml"       – XML feed polled from source_url
    "url_csv"       – CSV feed polled from source_url
    "upload"        – binary upload via the sync endpoint (raw_bytes path)
    "google_sheet"  – Google Sheets export URL (treated as CSV)

    status values
    -------------
    "pending"  – created, not yet ingested
    "syncing"  – ingest job in progress
    "ok"       – last sync succeeded
    "error"    – last sync failed
    """

    __tablename__ = "feed_sources"
    __table_args__ = (
        Index("ix_feed_sources_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # "url_xml" | "url_csv" | "upload" | "google_sheet"
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "pending" | "syncing" | "ok" | "error"
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_synced_at: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC timestamp of the last successful sync",
    )

    # Relationships
    products: Mapped[list["FeedProduct"]] = relationship(
        back_populates="feed_source",
        cascade="all, delete-orphan",
    )
    channels: Mapped[list["FeedChannel"]] = relationship(
        back_populates="feed_source",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<FeedSource id={self.id} name={self.name!r}"
            f" tenant={self.tenant_id} status={self.status!r}>"
        )


# ── FeedProduct ───────────────────────────────────────────────────────────────


class FeedProduct(Base, TimestampMixin):
    """One product (SKU) parsed from a FeedSource.

    ``data`` is a JSON dict of all raw attributes from the source feed.
    The unique constraint on (feed_source_id, external_id) makes upserts
    idempotent — re-ingesting the same feed won't duplicate rows.
    """

    __tablename__ = "feed_products"
    __table_args__ = (
        UniqueConstraint(
            "feed_source_id", "external_id", name="uq_feed_product_source_extid"
        ),
        Index("ix_feed_products_tenant_id", "tenant_id"),
        Index("ix_feed_products_feed_source_id", "feed_source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    # index created via __table_args__ above
    feed_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feed_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SKU / product ID from the source feed (string key from source)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    # Full attribute dict from the parsed feed row
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    feed_source: Mapped["FeedSource"] = relationship(back_populates="products")

    def __repr__(self) -> str:
        return (
            f"<FeedProduct id={self.id} external_id={self.external_id!r}"
            f" source={self.feed_source_id}>"
        )


# ── FeedChannel ───────────────────────────────────────────────────────────────


class FeedChannel(Base, TimestampMixin):
    """A channel-specific view of a FeedSource with its own transformation rules.

    channel_type values
    -------------------
    "google_shopping" – RSS 2.0 XML with g: namespace (Google Merchant Center)
    "meta_catalog"    – CSV (id,title,description,… required by Meta)
    "tiktok_catalog"  – CSV (id,title,price,… required by TikTok Shop)
    "custom"          – generic XML or CSV per output_format

    output_format values
    --------------------
    "xml" | "csv"

    public_token
    ------------
    32-byte urlsafe-base64 random token generated at creation time.
    Used in the public feed URL; acts as the secret — no auth required.
    URL: GET /api/v1/feeds/public/{public_token}
    """

    __tablename__ = "feed_channels"
    __table_args__ = (
        Index("ix_feed_channels_tenant_id", "tenant_id"),
        Index("ix_feed_channels_feed_source_id", "feed_source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    # index created via __table_args__ above
    feed_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feed_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # "google_shopping" | "meta_catalog" | "tiktok_catalog" | "custom"
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "xml" | "csv"
    output_format: Mapped[str] = mapped_column(
        String(10), nullable=False, default="xml"
    )
    # Unguessable random URL token — never log this
    public_token: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    feed_source: Mapped["FeedSource"] = relationship(back_populates="channels")
    rules: Mapped[list["FeedRule"]] = relationship(
        back_populates="feed_channel",
        cascade="all, delete-orphan",
        order_by="FeedRule.position",
    )

    def __repr__(self) -> str:
        return (
            f"<FeedChannel id={self.id} name={self.name!r}"
            f" channel_type={self.channel_type!r}>"
        )


# ── FeedRule ──────────────────────────────────────────────────────────────────


class FeedRule(Base, TimestampMixin):
    """One transformation step applied to every product in a FeedChannel.

    Rules are applied in ascending ``position`` order.

    rule_type values and their ``config`` schema
    --------------------------------------------
    "set_value"
        Force a field to a constant.
        config: {"field": "condition", "value": "new"}

    "rename_field"
        Copy the value of one field to a new key, optionally dropping the old.
        config: {"from_field": "product_type", "to_field": "google_product_category",
                 "drop_original": true}

    "find_replace"
        Replace a substring or regex pattern in a field's value.
        config: {"field": "title", "pattern": "  +", "replacement": " ",
                 "use_regex": true}

    "filter_include"
        Keep only products where condition_field matches condition_value.
        config: {"condition_field": "availability", "condition_op": "eq",
                 "condition_value": "in stock"}
        condition_op: "eq" | "neq" | "contains" | "not_contains" | "gt" | "lt"

    "filter_exclude"
        Drop products where condition_field matches condition_value.
        config: same shape as filter_include

    "calculated"
        Compute a new (or overwrite existing) field using a template string or
        simple arithmetic.  Template uses {field_name} placeholders.
        config: {"field": "custom_label_0",
                 "expression": "{title} - {brand} | {price}"}
        Arithmetic shortcut: {"field": "sale_price",
                               "expression": "{price} * 0.9"}
        If the expression contains arithmetic operators and all referenced
        fields are numeric, it is evaluated as arithmetic; otherwise it is
        treated as a string template.
    """

    __tablename__ = "feed_rules"
    __table_args__ = (
        Index("ix_feed_rules_feed_channel_id", "feed_channel_id"),
        Index("ix_feed_rules_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    # index created via __table_args__ above
    feed_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Ascending application order within the channel"
    )
    # "set_value" | "rename_field" | "find_replace" | "filter_include"
    # | "filter_exclude" | "calculated"
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Rule-specific config dict — schema depends on rule_type (see docstring)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    feed_channel: Mapped["FeedChannel"] = relationship(back_populates="rules")

    def __repr__(self) -> str:
        return (
            f"<FeedRule id={self.id} type={self.rule_type!r}"
            f" pos={self.position} channel={self.feed_channel_id}>"
        )
