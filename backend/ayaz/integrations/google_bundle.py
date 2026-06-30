"""Google Workspace bundle integration adapters.

Provides four Integration subclasses that all share a single OAuth grant
via the ``google_workspace`` provider:

- ``GoogleWorkspaceBundleIntegration`` — meta-entry for the connect flow
- ``GoogleAdsIntegration``             — read, wraps existing GA connector
- ``GA4Integration``                   — read, wraps existing GA4 connector
- ``SearchConsoleIntegration``          — read, wraps existing SC connector
"""

from __future__ import annotations

from ayaz.integrations.base import (
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
)


class GoogleWorkspaceBundleIntegration(Integration):
    """Meta-entry for the bundled Google Workspace OAuth connect flow.

    A single OAuth consent from this integration grants access to Google Ads,
    GA4, Search Console, Google Sheets, and Gmail — all pointing at the same
    ``ProviderGrant`` row.
    """

    metadata = IntegrationMetadata(
        key="google_workspace",
        display_name="Google Workspace",
        category="productivity",
        description_tr="Google Ads, GA4 ve Search Console'u tek izinle bağlayın.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=(
            "https://www.googleapis.com/auth/adwords",
            "https://www.googleapis.com/auth/analytics.readonly",
            "https://www.googleapis.com/auth/webmasters.readonly",
        ),
        capabilities=(Capability.read,),
        icon="G",
        icon_bg="#4285F4",
        aliases=("google bundle", "google workspace", "google paket"),
        min_plan="free",
    )


class GoogleAdsIntegration(Integration):
    """Google Ads integration — read-only, wraps the existing connector."""

    metadata = IntegrationMetadata(
        key="google_ads",
        display_name="Google Ads",
        category="ads",
        description_tr="Arama ve görüntülü reklam kampanya performansını çekin.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/adwords",),
        capabilities=(Capability.read,),
        icon="G",
        icon_bg="#4285F4",
        aliases=("google reklam", "arama reklamı", "sem", "adwords"),
        min_plan="free",
    )

    def as_connector(self, cfg):  # type: ignore[override]
        from ayaz.connectors.registry import ConnectorRegistry

        return ConnectorRegistry.get("google_ads")(cfg)


class GA4Integration(Integration):
    """Google Analytics 4 integration — read-only, wraps the existing GA4 connector."""

    metadata = IntegrationMetadata(
        key="ga4",
        display_name="Google Analytics 4",
        category="analytics",
        description_tr="Web sitesi ve uygulama oturum metriklerini çekin.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/analytics.readonly",),
        capabilities=(Capability.read,),
        icon="G",
        icon_bg="#F4B400",
        aliases=("analitik", "ölçüm", "ga4", "google analytics"),
        min_plan="free",
    )

    def as_connector(self, cfg):  # type: ignore[override]
        from ayaz.connectors.registry import ConnectorRegistry

        return ConnectorRegistry.get("ga4")(cfg)


class SearchConsoleIntegration(Integration):
    """Google Search Console integration — read-only."""

    metadata = IntegrationMetadata(
        key="search_console",
        display_name="Google Search Console",
        category="analytics",
        description_tr="Organik arama performansını (tıklama, gösterim, CTR) çekin.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/webmasters.readonly",),
        capabilities=(Capability.read,),
        icon="G",
        icon_bg="#34A853",
        aliases=("arama konsolu", "seo", "organik arama", "search console"),
        min_plan="free",
    )

    def as_connector(self, cfg):  # type: ignore[override]
        from ayaz.connectors.registry import ConnectorRegistry

        return ConnectorRegistry.get("search_console")(cfg)
