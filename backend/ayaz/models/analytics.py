"""Unified analytics data model — star schema over ``fact_daily_metrics``.

Design notes
------------
* Single wide fact table + shared dims → trivial cross-channel blending.
  ``GROUP BY date_key, channel_id`` gives multi-platform totals with no ETL join.
* Derived metrics (CTR, CPC, CPA, ROAS) are NOT materialised here.
  They are computed by the Metric Layer (``ayaz/metrics/``) so the single
  definition is shared by every consumer (dashboard, alerts, LLM summaries).
* Currency: ``cost_raw`` / ``conversion_value_raw`` are in the source currency
  (``cost_ccy``); ``*_base_ccy`` columns hold the tenant's reporting currency
  after conversion via ``dim_currency_rate``.
* Timezone: all ``date_key`` values are in UTC. Display-layer converts.
* Postgres RLS: every row carries ``tenant_id``.
  RLS policies will be added in Faz 1 (infra task).
  Until then every query MUST filter explicitly on ``tenant_id``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base, TimestampMixin, uuid_pk


# ── Dimension tables ──────────────────────────────────────────────────────────


class DimChannel(Base):
    """Ad / analytics channel dimension (Google Ads, Meta, GA4, …)."""

    __tablename__ = "dim_channel"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    metrics: Mapped[list["FactDailyMetrics"]] = relationship(back_populates="channel")

    def __repr__(self) -> str:
        return f"<DimChannel key={self.key!r}>"


class DimCampaign(Base, TimestampMixin):
    """Campaign dimension.

    ``tenant_id`` is carried here to scope RLS.
    Sources without a campaign hierarchy (GA4 organic, Search Console) link to
    a sentinel row with ``external_id = '(not set)'``.
    """

    __tablename__ = "dim_campaign"
    __table_args__ = (
        Index("ix_dim_campaign_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_channel.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")

    ad_sets: Mapped[list["DimAdSet"]] = relationship(back_populates="campaign")
    metrics: Mapped[list["FactDailyMetrics"]] = relationship(back_populates="campaign")

    def __repr__(self) -> str:
        return f"<DimCampaign id={self.id} name={self.name!r}>"


class DimAdSet(Base, TimestampMixin):
    """Ad-set / ad-group dimension.

    ``tenant_id`` carried for RLS; null-dim row for sources without ad-set
    hierarchy.
    """

    __tablename__ = "dim_adset"
    __table_args__ = (
        Index("ix_dim_adset_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_campaign.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")

    campaign: Mapped["DimCampaign"] = relationship(back_populates="ad_sets")
    ads: Mapped[list["DimAd"]] = relationship(back_populates="ad_set")
    metrics: Mapped[list["FactDailyMetrics"]] = relationship(back_populates="ad_set")

    def __repr__(self) -> str:
        return f"<DimAdSet id={self.id} name={self.name!r}>"


class DimAd(Base, TimestampMixin):
    """Creative / ad dimension."""

    __tablename__ = "dim_ad"
    __table_args__ = (
        Index("ix_dim_ad_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    ad_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_adset.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")

    ad_set: Mapped["DimAdSet"] = relationship(back_populates="ads")
    metrics: Mapped[list["FactDailyMetrics"]] = relationship(back_populates="ad")

    def __repr__(self) -> str:
        return f"<DimAd id={self.id} name={self.name!r}>"


class DimDate(Base):
    """Date dimension (pre-populated by a one-off seed job).

    Stores calendar attributes (year, quarter, month, week, day-of-week, …)
    so dashboard queries can GROUP BY any calendar grain without date math.
    Seed script: TODO (Faz 1) — generate rows for 2020-01-01 → 2030-12-31.
    """

    __tablename__ = "dim_date"

    date_key: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    quarter: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    week: Mapped[int] = mapped_column(nullable=False)
    day_of_week: Mapped[int] = mapped_column(nullable=False, comment="0=Mon…6=Sun")
    is_weekend: Mapped[bool] = mapped_column(nullable=False, default=False)

    metrics: Mapped[list["FactDailyMetrics"]] = relationship(back_populates="date")

    def __repr__(self) -> str:
        return f"<DimDate {self.date_key}>"


class DimCurrencyRate(Base):
    """Daily FX rates relative to a base currency (e.g. USD or EUR).

    Populated by a daily ETL job pulling from TCMB / ECB.
    TODO (Faz 1): implement rate-fetch Celery task and backfill.
    """

    __tablename__ = "dim_currency_rate"
    __table_args__ = (
        UniqueConstraint("date_key", "from_ccy", "to_ccy", name="uq_rate_date_pair"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    date_key: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    from_ccy: Mapped[str] = mapped_column(String(3), nullable=False)
    to_ccy: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="tcmb",
        comment="Rate data source: tcmb | ecb | manual"
    )

    def __repr__(self) -> str:
        return (
            f"<DimCurrencyRate {self.date_key} {self.from_ccy}/{self.to_ccy}"
            f" rate={self.rate}>"
        )


# ── Fact table ────────────────────────────────────────────────────────────────


class FactDailyMetrics(Base):
    """Core fact table: one row per (tenant, account, campaign, adset, ad, date).

    Isolation note: ``tenant_id`` is on every row.
    Postgres RLS policies (TODO Faz 1) will enforce isolation at the DB level
    using ``current_setting('app.tenant_id')``.
    Until then the application layer MUST filter every query by ``tenant_id``.

    Derived metrics
    ---------------
    CTR, CPC, CPA, ROAS are NOT stored here — computed by the Metric Layer.
    This avoids double-counting and keeps the single source of truth clean.

    Currency
    --------
    ``cost_raw`` / ``conversion_value_raw`` = source platform currency.
    ``cost_base_ccy`` / ``conv_value_base_ccy`` = tenant's ``base_currency``
    after applying ``dim_currency_rate``.
    """

    __tablename__ = "fact_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connected_account_id",
            "channel_id",
            "campaign_id",
            "adset_id",
            "ad_id",
            "date_key",
            name="uq_fact_daily_grain",
        ),
        Index("ix_fact_tenant_date", "tenant_id", "date_key"),
        Index("ix_fact_tenant_channel_date", "tenant_id", "channel_id", "date_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    # ── Grain ──────────────────────────────────────────────────────────────
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    connected_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_channel.id"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_campaign.id"), nullable=False
    )
    adset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_adset.id"), nullable=False
    )
    ad_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dim_ad.id"), nullable=False
    )
    date_key: Mapped[date] = mapped_column(
        Date, ForeignKey("dim_date.date_key"), nullable=False
    )

    # ── Raw metrics ────────────────────────────────────────────────────────
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_raw: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0,
        comment="Spend in source currency (cost_ccy)"
    )
    cost_ccy: Mapped[str] = mapped_column(
        String(3), nullable=False, comment="ISO 4217 source currency"
    )
    conversions: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    conversion_value_raw: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0,
        comment="Conversion value in source currency"
    )
    conversion_value_ccy: Mapped[str] = mapped_column(
        String(3), nullable=False, comment="ISO 4217 source currency for conv value"
    )

    # ── Normalised (tenant base currency) ─────────────────────────────────
    cost_base_ccy: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0,
        comment="cost_raw converted to tenant base_currency"
    )
    conv_value_base_ccy: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0,
        comment="conversion_value_raw converted to tenant base_currency"
    )

    # ── Ingestion bookkeeping ──────────────────────────────────────────────
    ingested_at: Mapped[datetime] = mapped_column(
        nullable=False,
        comment="Wall-clock UTC time this row was written by the ETL worker",
    )

    # Relationships (for ORM joins in service layer)
    channel: Mapped["DimChannel"] = relationship(back_populates="metrics")
    campaign: Mapped["DimCampaign"] = relationship(back_populates="metrics")
    ad_set: Mapped["DimAdSet"] = relationship(back_populates="metrics")
    ad: Mapped["DimAd"] = relationship(back_populates="metrics")
    date: Mapped["DimDate"] = relationship(back_populates="metrics")

    def __repr__(self) -> str:
        return (
            f"<FactDailyMetrics tenant={self.tenant_id} date={self.date_key}"
            f" channel={self.channel_id}>"
        )
