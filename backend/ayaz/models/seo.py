"""SEO data model — seo_search_metrics table."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ayaz.models.base import GUID as UUID, Base, uuid_pk


class SeoSearchMetric(Base):
    """One row of Search Console performance data for a (tenant, date, query, page) key."""

    __tablename__ = "seo_search_metrics"
    __table_args__ = (
        Index("ix_seo_search_metrics_tenant_id", "tenant_id"),
        Index("ix_seo_search_metrics_tenant_date", "tenant_id", "date"),
        UniqueConstraint(
            "tenant_id", "date", "query", "page", "device", "country",
            name="uq_seo_search_metrics",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    query: Mapped[str] = mapped_column(String(2048), nullable=False)

    page: Mapped[str] = mapped_column(String(2048), nullable=False)

    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ctr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    position: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    device: Mapped[str | None] = mapped_column(String(50), nullable=True)

    country: Mapped[str | None] = mapped_column(String(10), nullable=True)

    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
