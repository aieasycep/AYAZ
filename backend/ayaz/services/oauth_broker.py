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
import logging
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ayaz.config import settings

_log = logging.getLogger(__name__)


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
        authorize_url="https://www.facebook.com/v25.0/dialog/oauth",
        token_url="https://graph.facebook.com/v25.0/oauth/access_token",
        # Least privilege: AYAZ is read-only for Meta (see
        # MetaAdsConnector.capabilities().supports_write=False). "ads_management"
        # (write) is deliberately excluded to narrow the App Review scope —
        # "ads_read" + "business_management" is sufficient for /me/adaccounts
        # and Insights. Keep in sync with
        # MetaAdsConnector.build_authorization_url()'s default scopes.
        scopes=["ads_read", "business_management"],
    ),
    "tiktok_ads": _PlatformOAuthConfig(
        authorize_url="https://business-api.tiktok.com/portal/auth",
        token_url="https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
        scopes=[],  # TikTok scopes are granted at app level, not per-request
    ),
    "google_workspace": _PlatformOAuthConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/adwords",
            "https://www.googleapis.com/auth/analytics.readonly",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://mail.google.com/",
        ],
    ),
    "slack": _PlatformOAuthConfig(
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=["chat:write", "channels:read"],
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


def _slack_credentials() -> tuple[str, str]:
    return settings.slack_client_id, settings.slack_client_secret


def _credentials_for(platform: str) -> tuple[str, str]:
    """Return (client_id, client_secret) for ``platform``.

    For platforms with missing/empty credentials, returns ``("", "")``
    rather than raising so callers can gracefully degrade.
    """
    if platform in ("google_ads", "ga4", "search_console", "google_workspace"):
        return _google_credentials()
    if platform == "meta_ads":
        return _meta_credentials()
    if platform == "tiktok_ads":
        return _tiktok_credentials()
    if platform == "slack":
        return _slack_credentials()
    # Unknown platform — return empty rather than raising so callers can check
    return ("", "")


def _has_credentials(platform: str) -> bool:
    """Return True only if both client_id and client_secret are non-empty."""
    client_id, client_secret = _credentials_for(platform)
    return bool(client_id) and bool(client_secret)


# ── PKCE helpers ─────────────────────────────────────────────────────────────


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Challenge = S256.

    The code_verifier is a URL-safe base64 string (no padding).
    The code_challenge is BASE64URL(SHA256(verifier)) with no padding.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


# ── State token helpers (CSRF) — HMAC-signed, expiring ───────────────────────

_STATE_TTL_SECONDS = 1800  # 30 minutes — OAuth akışı 2FA/SMS doğrulaması + soğuk
# başlatma (Render free) ile 10 dk'yı aşabiliyordu; state'in erken bitip callback'i
# reddetmesini önlemek için 30 dk. CSRF için hâlâ güvenli (kısa, HMAC imzalı, nonce'lu).


def _sign_state(account_id: str, tenant_id: str) -> str:
    """Encode account_id + tenant_id into a URL-safe HMAC-signed state token.

    The token has a 30-minute expiry and is signed with HMAC-SHA256 using
    ``settings.jwt_secret`` as the key.

    Parameters
    ----------
    account_id:
        The ConnectedAccount or ProviderGrant UUID (str).
    tenant_id:
        The Tenant UUID (str) — used to scope the callback.

    Returns
    -------
    str
        ``<base64url(payload)>.<base64url(mac)>`` — dot-separated.
    """
    nonce = str(uuid.uuid4())
    exp = int(time.time()) + _STATE_TTL_SECONDS
    payload_dict = {"aid": account_id, "tid": tenant_id, "nonce": nonce, "exp": exp}
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")

    mac = hmac.new(
        settings.jwt_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    mac_b64 = base64.urlsafe_b64encode(mac).decode().rstrip("=")

    return f"{payload_b64}.{mac_b64}"


def parse_state(state: str) -> tuple[str, str]:
    """Decode and verify a state token, returning (account_id, tenant_id).

    Raises
    ------
    ValueError
        If the token cannot be decoded, the HMAC is invalid, or the token
        has expired.
    """
    try:
        payload_b64, mac_b64 = state.rsplit(".", 1)
    except ValueError:
        raise ValueError("Invalid OAuth state token: missing MAC separator") from None

    # Verify HMAC
    expected_mac = hmac.new(
        settings.jwt_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()

    try:
        provided_mac = base64.urlsafe_b64decode(mac_b64 + "==")
    except Exception as exc:
        raise ValueError(f"Invalid OAuth state token: bad MAC encoding: {exc}") from exc

    if not hmac.compare_digest(expected_mac, provided_mac):
        raise ValueError("Invalid OAuth state token: MAC verification failed")

    # Decode payload
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes.decode())
    except Exception as exc:
        raise ValueError(f"Invalid OAuth state token: {exc}") from exc

    # Check expiry
    exp = payload.get("exp", 0)
    if int(time.time()) > exp:
        raise ValueError("OAuth state token has expired")

    try:
        return payload["aid"], payload["tid"]
    except KeyError as exc:
        raise ValueError(f"Invalid OAuth state token: missing key {exc}") from exc


# ── Token expiry helper ───────────────────────────────────────────────────────


def _with_absolute_expiry(data: dict[str, Any]) -> dict[str, Any]:
    """Add an absolute ``token_expires_at`` (ISO-8601 UTC) to ``data`` in place,
    computed from its ``expires_in`` (relative seconds), if present.

    Every platform token endpoint returns a *relative* ``expires_in`` — that
    number is only meaningful at the instant the HTTP response was received.
    Once the token dict is persisted to the Vault and read back later (e.g. by
    a sync task hours or days afterward), a relative value can no longer say
    whether the token is still alive. Converting to an absolute timestamp here
    — right where "now" is well-defined — lets any later caller (see
    ``sync.py``'s Meta rolling-refresh) compare against ``datetime.now(UTC)``
    directly.

    Silently leaves ``data`` untouched if ``expires_in`` is absent or not a
    valid number — defensive, since not every platform response guarantees
    the field (e.g. system-user tokens, or a malformed response we'd rather
    not crash the whole exchange over).
    """
    expires_in = data.get("expires_in")
    if expires_in is None:
        return data
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return data
    data["token_expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat()
    return data


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
        data: dict[str, Any] = resp.json()

        # TikTok wraps the tokens in a ``data`` envelope
        if platform == "tiktok_ads":
            data = data.get("data", data)

        if "access_token" not in data:
            raise ValueError(
                f"Token exchange for {platform!r} returned no access_token. "
                f"Response: {data}"
            )

        if platform == "meta_ads":
            # Meta's ``authorization_code`` grant only ever returns a
            # SHORT-LIVED user access token (~1-2h). Unlike Google, Meta's
            # authenticate() does not refresh on every sync — a short-lived
            # token left unattended would die within hours and nothing
            # would repair it. Immediately hop to the long-lived exchange
            # (same token endpoint, GET, grant_type=fb_exchange_token) so
            # the token handed back to the caller/Vault is the ~60-day
            # long-lived one. Reuses the same ``client`` (and same
            # test-injected transport) as the first hop — mirrors how the
            # TikTok branch above gets special per-platform treatment
            # inline rather than as a second public function.
            data = _meta_exchange_long_lived_token(
                client, cfg.token_url, client_id, client_secret, data
            )
    finally:
        if http_client is None:
            client.close()

    return _with_absolute_expiry(data)


def _meta_exchange_long_lived_token(
    client: httpx.Client,
    token_url: str,
    client_id: str,
    client_secret: str,
    short_lived_data: dict[str, Any],
) -> dict[str, Any]:
    """Hop a short-lived Meta user access token to a long-lived (~60d) one.

    ``GET {token_url}?grant_type=fb_exchange_token&client_id=...&client_secret=...
    &fb_exchange_token=<short_lived_token>`` — per Meta's "Long-Lived Access
    Tokens" doc. Meta has no ``refresh_token`` concept; this exchange (and
    ``refresh()`` below, which repeats it) is the only way to keep a user
    token alive beyond the first couple of hours.

    Returns the short-lived response dict with ``access_token`` /
    ``expires_in`` (and any other keys the long-lived response includes,
    e.g. ``token_type``) overwritten by the long-lived response. Any keys
    present only in the short-lived response are preserved.
    """
    short_lived_token = short_lived_data.get("access_token", "")
    resp = client.get(
        token_url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    long_lived_data: dict[str, Any] = resp.json()

    if "access_token" not in long_lived_data:
        raise ValueError(
            "Meta long-lived token exchange returned no access_token. "
            f"Response: {long_lived_data}"
        )

    return {**short_lived_data, **long_lived_data}


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

    client = http_client or httpx.Client()
    try:
        if platform == "tiktok_ads":
            payload: dict[str, Any] = {
                "app_id": client_id,
                "secret": client_secret,
                "refresh_token": refresh_token,
            }
            token_url = (
                "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/"
            )
            resp = client.post(token_url, data=payload, timeout=30)
        elif platform == "meta_ads":
            # Meta has NO ``refresh_token`` grant — sending
            # grant_type=refresh_token (the generic branch below) is
            # rejected by Graph API. The only way to extend a Meta user
            # token is the SAME fb_exchange_token hop used in
            # exchange_code() (see _meta_exchange_long_lived_token above
            # and MetaAdsConnector.refresh_token(), which already does
            # this at the connector layer). The caller passes the current
            # long-lived access token in as ``refresh_token`` (Meta has no
            # separate refresh-token artifact; the Vault stores the
            # long-lived access token under that key by convention).
            resp = client.get(
                cfg.token_url,
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "fb_exchange_token": refresh_token,
                },
                timeout=30,
            )
        else:
            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            resp = client.post(cfg.token_url, data=payload, timeout=30)

        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if platform == "tiktok_ads":
            data = data.get("data", data)

        if "access_token" not in data:
            raise ValueError(
                f"Token refresh for {platform!r} returned no access_token. "
                f"Response: {data}"
            )
    finally:
        if http_client is None:
            client.close()

    return _with_absolute_expiry(data)


def revoke(
    platform: str,
    token: str,
    *,
    http_client: httpx.Client | None = None,
) -> None:
    """Best-effort revocation of an OAuth token for the given platform.

    Network errors are swallowed and logged — callers should proceed with
    local cleanup regardless of whether the platform revocation succeeded.

    Parameters
    ----------
    platform:
        The platform key (e.g. ``"google_workspace"``, ``"slack"``).
    token:
        The access token to revoke.
    http_client:
        Optional ``httpx.Client`` override — inject a mock in tests.
    """
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10)
    try:
        if platform in ("google_ads", "ga4", "search_console", "google_workspace"):
            client.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
            )
        elif platform == "slack":
            client.post(
                "https://slack.com/api/auth.revoke",
                headers={"Authorization": f"Bearer {token}"},
            )
        elif platform == "meta_ads":
            # Meta does not have a simple programmatic revoke endpoint;
            # log intent and rely on token TTL / user revocation via UI.
            _log.info("revoke: Meta token revocation not supported programmatically")
        elif platform == "tiktok_ads":
            # TikTok has no standard revoke endpoint.
            _log.info("revoke: TikTok token revocation not supported")
        else:
            _log.warning("revoke: unknown platform %r — skipping", platform)
    except Exception:
        _log.warning(
            "revoke: best-effort revocation failed for platform=%r (continuing)",
            platform,
            exc_info=True,
        )
    finally:
        if own_client:
            client.close()


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
