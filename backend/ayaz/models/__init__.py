"""SQLAlchemy ORM models for AYAZ.

Import order matters for Alembic autogenerate — import all model modules here
so they are registered on ``Base.metadata`` before migrations run.
"""

from ayaz.models.base import Base
from ayaz.models.oltp import (  # noqa: F401
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
    WorkspaceInvitation,
)
from ayaz.models.analytics import (  # noqa: F401
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimCurrencyRate,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.feeds import (  # noqa: F401
    FeedChannel,
    FeedProduct,
    FeedRule,
    FeedSource,
)
from ayaz.models.insights import (  # noqa: F401
    AlertRule,
    Insight,
)
from ayaz.models.reports import (  # noqa: F401
    ReportDefinition,
    ReportSchedule,
    SharedReport,
)
from ayaz.models.automation import (  # noqa: F401
    AutomationRule,
    AutomationRun,
)
from ayaz.models.tracking import (  # noqa: F401
    ConversionEvent,
    EventDestination,
    TrackingSource,
)
from ayaz.models.billing import (  # noqa: F401
    BillingEvent,
    Subscription,
)
from ayaz.models.copilot import (  # noqa: F401
    Conversation,
    Message,
)
from ayaz.models.goals import (  # noqa: F401
    Goal,
)
from ayaz.models.briefing import (  # noqa: F401
    Briefing,
)

__all__ = [
    "Base",
    "Tenant",
    "User",
    "Membership",
    "MembershipRole",
    "ConnectedAccount",
    "Platform",
    "SyncStatus",
    "DimChannel",
    "DimCampaign",
    "DimAdSet",
    "DimAd",
    "DimDate",
    "DimCurrencyRate",
    "FactDailyMetrics",
    "FeedSource",
    "FeedProduct",
    "FeedChannel",
    "FeedRule",
    "Insight",
    "AlertRule",
    "ReportDefinition",
    "ReportSchedule",
    "SharedReport",
    "AutomationRule",
    "AutomationRun",
    "TrackingSource",
    "EventDestination",
    "ConversionEvent",
    "Subscription",
    "BillingEvent",
    "WorkspaceInvitation",
    "Conversation",
    "Message",
    "Goal",
    "Briefing",
]
