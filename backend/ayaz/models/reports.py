"""Report Management models — M3+ Advanced Reporting.

Multi-tenancy
-------------
All tables carry ``tenant_id`` and must be filtered explicitly until Postgres RLS
policies are deployed (see oltp.py for the same pattern and the TODO comment).

Type/status columns
--------------------
All type and status fields use ``sa.String`` rather than Postgres ENUM types to
avoid the duplicate-type migration bug documented in 0001_initial_schema.py.
Allowed values are validated at the application/Pydantic layer.

Report flow
-----------
  ReportDefinition ──(schedules)──> ReportSchedule  (recurring delivery)
  ReportDefinition ──(shares)────> SharedReport      (public white-label links)

Public URL scheme
-----------------
  GET /api/v1/reports/public/{public_token}
  The public_token on SharedReport is a 32-byte urlsafe random string (no auth
  required — the token itself is the secret).  Users share this URL with clients
  as a white-label report page.

PDF note
--------
PDF export is out of scope for now.  The intended approach is to run a
headless-Chrome process over the HTML returned by ``render_report_html`` and
save the output as a PDF blob.  This will be wired in a later phase when the
infra team provisions a Chrome/Puppeteer sidecar.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from ayaz.models.base import GUID as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ayaz.models.base import Base, TimestampMixin, uuid_pk

try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover — should never happen on SA 2.x
    from sqlalchemy import Text as JSON  # type: ignore[assignment]


# ── ReportDefinition ──────────────────────────────────────────────────────────


class ReportDefinition(Base, TimestampMixin):
    """A saved, reusable report template owned by a tenant.

    config schema
    -------------
    The ``config`` JSON dict holds the full specification for the report::

        {
            "metrics": ["spend", "impressions", "clicks", "conversions",
                        "conversion_value", "ctr", "cpc", "cpa", "roas"],
            "channels": ["google_ads", "meta_ads"],   // null or [] = all channels
            "date_range_preset": "last_30_days",      // or null (use explicit dates)
            "sections": ["totals", "by_channel", "timeseries", "insights"],
            "brand_name": "Acme Marketing",
            "logo_url": "https://cdn.example.com/logo.png",
            "primary_color": "#1A73E8"
        }

    date_range_preset values
    ------------------------
    "last_7_days" | "last_30_days" | "last_90_days" | "this_month" |
    "last_month"  | null (caller provides explicit date_from/date_to)

    sections values
    ---------------
    "totals"      — aggregate KPI cards
    "by_channel"  — per-channel breakdown table
    "timeseries"  — daily spend line chart (as inline SVG or table)
    "insights"    — top anomaly/alert insights for the period
    """

    __tablename__ = "report_definitions"
    __table_args__ = (
        Index("ix_report_definitions_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Full report specification — see docstring for schema
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # UUID of the User who created this definition (informational)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Relationships
    schedules: Mapped[list["ReportSchedule"]] = relationship(
        back_populates="report_definition",
        cascade="all, delete-orphan",
    )
    shared_reports: Mapped[list["SharedReport"]] = relationship(
        back_populates="report_definition",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ReportDefinition id={self.id} name={self.name!r}"
            f" tenant={self.tenant_id}>"
        )


# ── ReportSchedule ────────────────────────────────────────────────────────────


class ReportSchedule(Base, TimestampMixin):
    """Recurring delivery schedule for a ReportDefinition.

    cadence values
    --------------
    "daily"   — delivered every day at ``hour`` UTC
    "weekly"  — delivered on ``weekday`` (0=Mon … 6=Sun) at ``hour`` UTC
    "monthly" — delivered on the 1st of each month at ``hour`` UTC

    delivery values
    ---------------
    "email" — the rendered HTML report is emailed to ``recipients``
    (Actual email sending is deferred until SMTP credentials are configured;
    the delivery mechanism currently stubs to logging.  Wire Celery beat
    against ``due_schedules`` + ``send_scheduled_report`` in services/reports.py.)

    weekday
    -------
    Only meaningful when cadence == "weekly".
    0 = Monday, 1 = Tuesday, …, 6 = Sunday.
    Nullable so daily/monthly rows don't carry a spurious value.
    """

    __tablename__ = "report_schedules"
    __table_args__ = (
        Index("ix_report_schedules_tenant_id", "tenant_id"),
        Index("ix_report_schedules_definition_id", "report_definition_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # "daily" | "weekly" | "monthly"
    cadence: Mapped[str] = mapped_column(String(20), nullable=False)
    # 0=Mon … 6=Sun — only used when cadence == "weekly"
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0-23 UTC hour for delivery
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    # "email"
    delivery: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    # JSON list of email addresses: ["cmo@example.com", "agency@example.com"]
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ISO-8601 timestamp of the last successful delivery (nullable until first run)
    last_sent_at: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC timestamp of the last successful delivery",
    )

    # Relationships
    report_definition: Mapped["ReportDefinition"] = relationship(
        back_populates="schedules"
    )

    def __repr__(self) -> str:
        return (
            f"<ReportSchedule id={self.id} cadence={self.cadence!r}"
            f" definition={self.report_definition_id}>"
        )


# ── SharedReport ──────────────────────────────────────────────────────────────


class SharedReport(Base, TimestampMixin):
    """A shareable, optionally expiring public link to a rendered report.

    public_token
    ------------
    32-byte urlsafe-base64 random token generated at creation time.
    Used in the public report URL; acts as the secret — no auth required.
    URL: GET /api/v1/reports/public/{public_token}

    expires_at
    ----------
    Optional expiry.  When set, the public endpoint returns 404 after this
    datetime.  When null the link is permanent (until revoked via is_active).

    view_count
    ----------
    Incremented atomically each time the public endpoint is accessed.
    Useful for simple client engagement tracking.
    """

    __tablename__ = "shared_reports"
    __table_args__ = (
        Index("ix_shared_reports_tenant_id", "tenant_id"),
        Index("ix_shared_reports_definition_id", "report_definition_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="RLS: filter by current_setting('app.tenant_id')",
    )
    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Unguessable random URL token — never log this value
    public_token: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    # Optional datetime after which the link no longer resolves (null = permanent)
    expires_at: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ISO-8601 UTC datetime after which the link is expired (null = no expiry)",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Hit counter — incremented on every public access
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    report_definition: Mapped["ReportDefinition"] = relationship(
        back_populates="shared_reports"
    )

    def __repr__(self) -> str:
        return (
            f"<SharedReport id={self.id} token={self.public_token[:8]}..."
            f" active={self.is_active}>"
        )
