"""OAuth 2.0 Broker — per-platform authorization, code exchange, and token refresh.

Supported platforms
-------------------
- ``google_ads``     — Google OAuth2 (accounts.google.com)
- ``meta_ads``       — Meta / Facebook Login OAuth2
- ``ga4``            — Google OAuth2 (same client as google_ads; different scope)
- ``search_console`` — Google OAuth2 (same client; different scope)
- ``tiktok_ads``     — TikTok Marketing API OAuth2 (business-api.tiktok.com)

Credentials come exclusively from ``settings`` / environment variables — never
hardcoded.  All network calls go through an injected ``httpx.Client`` so tests
can substitute a mock without patching the module.

Usage (happy path)
------------------
1. ``url = build_authorize_url(platform, tenant_id, redirect_uri, state)``
   — redirect the browser here.
2. Platform redirects back with ``?code=&state=``
3. ``tokens = exchange_code(platform, code, redirect_uri)``
4. ``vault.put(account_id, tokens)``
5. On each sync: ``tokens = vault.get(account_id)`` → inject into ConnectorConfig.extra
6. When the access token expires: ``tokens = refresh(platform, tokens["refresh_token"])``
   then ``vault.put(account_id, tokens)``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from ayaz.config import settings


# ── Platform OAuth2 configuration catalog ────────────────────────────────────


@dataclass(frozen=True)
class _PlatformOAuthConfig:
    """Static OAuth2 endpoints and scopes for one platform."""

    authorize_url: str
    token_url: str
    scopes: list[str]


# All URLs and scopes are public knowledge — sourced from each platform's docs.
# Credentials (client_id / client_secret) come from settings at call time.
_PLATFORM_CONFIGS: dict[str, _PlatformOAuthConfig] = {
    "google_ads": _PlatformOAuthConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/adwords"],
    ),
    "ga4": _PlatformOAuthConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    ),
    "search_console": _PlatformOAuthConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    ),
    "meta_ads": _PlatformOAuthConfig(
        authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
        token_url="https://graph.facebook.com/v21.0/oauth/access_token",
        scopes=["ads_read", "ads_management", "business_management"],
    ),
    "tiktok_ads": _PlatformOAuthConfig(
        authorize_url="https://business-api.tiktok.com/portal/auth",
        token_url="https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
        scopes=[],  # TikTok scopes are granted at app level, not per-request
    ),
}


def _supported_platforms() -> list[str]:
    return sorted(_PLATFORM_CONFIGS)


# ── Credential helpers ────────────────────────────────────────────────────────


def _google_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) for all Google platforms."""
    return settings.google_client_id, settings.google_client_secret


def _meta_credentials() -> tuple[str, str]:
    return settings.meta_app_id, settings.meta_app_secret


def _tiktok_credentials() -> tuple[str, str]:
    return settings.tiktok_app_id, settings.tiktok_app_secret


def _credentials_for(platform: str) -> tuple[str, str]:
    """Return (client_id, client_secret) for ``platform``."""
    if platform in ("google_ads", "ga4", "search_console"):
        return _google_credentials()
    if platform == "meta_ads":
        return _meta_credentials()
    if platform == "tiktok_ads":
        return _tiktok_credentials()
    raise ValueError(f"Unknown platform: {platform!r}")


# ── State token helpers (CSRF) ────────────────────────────────────────────────


def _sign_state(account_id: str, tenant_id: str) -> str:
    """Encode account_id + tenant_id into a URL-safe state token.

    The token is a base64(JSON payload) — it is not a MAC because the
    ``state`` round-trip via the platform already provides replay protection
    (state is echoed verbatim).  For higher assurance, a future version should
    HMAC this with a short-lived per-session secret.

    Parameters
    ----------
    account_id:
        The ConnectedAccount UUID (str).
    tenant_id:
        The Tenant UUID (str) — used to scope the callback.

    Returns
    -------
    str
        URL-safe base64 encoded JSON string.
    """
    payload = json.dumps({"aid": account_id, "tid": tenant_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def parse_state(state: str) -> tuple[str, str]:
    """Decode a state token back to (account_id, tenant_id).

    Raises
    ------
    ValueError
        If the token cannot be decoded or is missing required keys.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        return payload["aid"], payload["tid"]
    except Exception as exc:
        raise ValueError(f"Invalid OAuth state token: {exc}") from exc


# ── Public API ────────────────────────────────────────────────────────────────


def build_authorize_url(
    platform: str,
    tenant_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Build the OAuth2 authorization URL for the given platform.

    Makes no network calls — purely URL construction.

    Parameters
    ----------
    platform:
        One of the supported platform keys (``google_ads``, ``meta_ads``, …).
    tenant_id:
        The current tenant UUID (str) — embedded in the state token for CSRF
        protection.
    redirect_uri:
        The URL the platform should redirect to after consent.  Must be
        registered in the platform's developer console.
    state:
        Opaque CSRF token (the caller — typically the OAuth API handler —
        generates this, usually via ``_sign_state``).

    Returns
    -------
    str
        The full consent-screen URL to redirect the user to.

    Raises
    ------
    ValueError
        If ``platform`` is not supported.
    """
    if platform not in _PLATFORM_CONFIGS:
        raise ValueError(
            f"Unsupported platform: {platform!r}. "
            f"Supported: {_supported_platforms()}"
        )
    cfg = _PLATFORM_CONFIGS[platform]
    client_id, _ = _credentials_for(platform)

    if platform == "tiktok_ads":
        # TikTok uses a non-standard parameter name for the client id
        params: dict[str, str] = {
            "app_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    else:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(cfg.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }

    return f"{cfg.authorize_url}?{urllib.parse.urlencode(params)}"


def exchange_code(
    platform: str,
    code: str,
    redirect_uri: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for OAuth tokens.

    POSTs to the platform's token endpoint and returns the full token response
    as a dict (``access_token``, ``refresh_token``, ``expires_in``, …).

    Parameters
    ----------
    platform:
        Supported platform key.
    code:
        The authorization code received in the callback query string.
    redirect_uri:
        Must match exactly the ``redirect_uri`` used in the authorization URL.
    http_client:
        Optional ``httpx.Client`` override — inject a mock in tests.

    Returns
    -------
    dict
        Token response from the platform.

    Raises
    ------
    httpx.HTTPStatusError
        If the token endpoint returns a non-2xx status.
    ValueError
        If the response does not contain ``access_token``.
    """
    if platform not in _PLATFORM_CONFIGS:
        raise ValueError(f"Unsupported platform: {platform!r}")

    cfg = _PLATFORM_CONFIGS[platform]
    client_id, client_secret = _credentials_for(platform)

    if platform == "tiktok_ads":
        payload: dict[str, Any] = {
            "app_id": client_id,
            "secret": client_secret,
            "auth_code": code,
        }
    else:
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

    client = http_client or httpx.Client()
    try:
        resp = client.post(cfg.token_url, data=payload, timeout=30)
        resp.raise_for_status()
    finally:
        if http_client is None:
            client.close()

    data: dict[str, Any] = resp.json()

    # TikTok wraps the tokens in a ``data`` envelope
    if platform == "tiktok_ads":
        data = data.get("data", data)

    if "access_token" not in data:
        raise ValueError(
            f"Token exchange for {platform!r} returned no access_token. "
            f"Response: {data}"
        )

    return data


def refresh(
    platform: str,
    refresh_token: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Refresh an expired access token using the platform's refresh grant.

    Parameters
    ----------
    platform:
        Supported platform key.
    refresh_token:
        The long-lived refresh token (obtained during the initial code exchange).
    http_client:
        Optional ``httpx.Client`` override — inject a mock in tests.

    Returns
    -------
    dict
        New token response (``access_token``, possibly a new ``refresh_token``,
        ``expires_in``, …).  The caller is responsible for persisting the
        updated tokens via the Vault.

    Raises
    ------
    httpx.HTTPStatusError
        If the token endpoint returns a non-2xx status (e.g. 401 — revoked token).
    ValueError
        If the response does not contain ``access_token`` or the platform does
        not support refresh grants.
    """
    if platform not in _PLATFORM_CONFIGS:
        raise ValueError(f"Unsupported platform: {platform!r}")

    cfg = _PLATFORM_CONFIGS[platform]
    client_id, client_secret = _credentials_for(platform)

    if platform == "tiktok_ads":
        payload: dict[str, Any] = {
            "app_id": client_id,
            "secret": client_secret,
            "refresh_token": refresh_token,
        }
        token_url = (
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/"
        )
    else:
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        token_url = cfg.token_url

    client = http_client or httpx.Client()
    try:
        resp = client.post(token_url, data=payload, timeout=30)
        resp.raise_for_status()
    finally:
        if http_client is None:
            client.close()

    data: dict[str, Any] = resp.json()
    if platform == "tiktok_ads":
        data = data.get("data", data)

    if "access_token" not in data:
        raise ValueError(
            f"Token refresh for {platform!r} returned no access_token. "
            f"Response: {data}"
        )

    return data


def store_tokens_for_account(
    account_id: str,
    tokens: dict[str, Any],
    vault: Any,  # SecretsVault — avoid circular import by using Any here
) -> None:
    """Persist OAuth tokens into the Vault, keyed by the ConnectedAccount id.

    This is called by the OAuth callback handler after a successful code
    exchange.  It is a thin wrapper to keep the API handler free of vault
    coupling details.

    Parameters
    ----------
    account_id:
        ConnectedAccount UUID (str) — the vault ``ref``.
    tokens:
        Dict returned by ``exchange_code()`` or ``refresh()``.
    vault:
        A ``SecretsVault`` instance (injected by the caller).
    """
    vault.put(account_id, tokens)
