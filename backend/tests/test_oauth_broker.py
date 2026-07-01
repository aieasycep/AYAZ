"""Unit tests for the OAuth Broker service.

Coverage
--------
- build_authorize_url: correct URL construction for all 5 platforms, unsupported platform.
- _sign_state / parse_state: round-trip, invalid token handling.
- exchange_code: mocked HTTP POST, token extraction, TikTok envelope unwrapping,
  missing access_token error.
- refresh: mocked HTTP POST, token extraction, TikTok refresh URL, missing token error.
- store_tokens_for_account: delegates to vault.put.

No live network calls are made — all HTTP calls use an httpx mock transport.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from ayaz.services.oauth_broker import (
    build_authorize_url,
    exchange_code,
    parse_state,
    refresh,
    store_tokens_for_account,
    _sign_state,
    _PLATFORM_CONFIGS,
)
from ayaz.services.vault import InMemoryVault


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_http_client(response_data: dict, status_code: int = 200) -> httpx.Client:
    """Return an httpx.Client that always returns ``response_data`` as JSON."""
    body = json.dumps(response_data).encode()

    class _MockTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(status_code, content=body)

    return httpx.Client(transport=_MockTransport())


# ── State token ───────────────────────────────────────────────────────────────


def test_sign_state_parse_state_round_trip():
    account_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    tenant_id = "11111111-2222-3333-4444-555555555555"
    state = _sign_state(account_id, tenant_id)
    recovered_aid, recovered_tid = parse_state(state)
    assert recovered_aid == account_id
    assert recovered_tid == tenant_id


def test_parse_state_invalid_raises():
    with pytest.raises(ValueError, match="Invalid OAuth state"):
        parse_state("not-valid-base64!!!")


def test_parse_state_missing_keys_raises():
    import base64
    payload = base64.urlsafe_b64encode(b'{"foo": "bar"}').decode()
    with pytest.raises(ValueError):
        parse_state(payload)


# ── build_authorize_url ───────────────────────────────────────────────────────


@pytest.mark.parametrize("platform,expected_host", [
    ("google_ads", "accounts.google.com"),
    ("meta_ads", "facebook.com"),
    ("ga4", "accounts.google.com"),
    ("search_console", "accounts.google.com"),
    ("tiktok_ads", "business-api.tiktok.com"),
])
def test_build_authorize_url_contains_platform_host(platform, expected_host):
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "goog-client-id"
        mock_settings.google_client_secret = "goog-secret"
        mock_settings.meta_app_id = "meta-app-id"
        mock_settings.meta_app_secret = "meta-secret"
        mock_settings.tiktok_app_id = "tt-app-id"
        mock_settings.tiktok_app_secret = "tt-secret"

        url = build_authorize_url(
            platform=platform,
            tenant_id="tenant-123",
            redirect_uri="https://app.ayaz.com/callback",
            state="some-state",
        )

    assert expected_host in url


def test_build_authorize_url_includes_state():
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        url = build_authorize_url(
            platform="google_ads",
            tenant_id="tenant-1",
            redirect_uri="https://example.com/callback",
            state="csrf-token-xyz",
        )

    assert "csrf-token-xyz" in url


def test_build_authorize_url_includes_redirect_uri():
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        url = build_authorize_url(
            platform="meta_ads",
            tenant_id="t",
            redirect_uri="https://myapp.com/oauth/meta/callback",
            state="s",
        )

    assert "myapp.com" in url


def test_build_authorize_url_google_includes_scope():
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        url = build_authorize_url(
            platform="google_ads",
            tenant_id="t",
            redirect_uri="https://example.com",
            state="s",
        )

    assert "adwords" in url


def test_build_authorize_url_unsupported_platform_raises():
    with pytest.raises(ValueError, match="Unsupported platform"):
        build_authorize_url(
            platform="unknown_platform",
            tenant_id="t",
            redirect_uri="https://example.com",
            state="s",
        )


def test_build_authorize_url_tiktok_uses_app_id():
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.tiktok_app_id = "my-tiktok-app"
        mock_settings.tiktok_app_secret = "secret"

        url = build_authorize_url(
            platform="tiktok_ads",
            tenant_id="t",
            redirect_uri="https://example.com",
            state="s",
        )

    assert "my-tiktok-app" in url


# ── exchange_code ─────────────────────────────────────────────────────────────


def test_exchange_code_google_ads_returns_tokens():
    token_response = {
        "access_token": "ya29.live_access",
        "refresh_token": "1//refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    client = _mock_http_client(token_response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        result = exchange_code(
            platform="google_ads",
            code="4/0AY0e-g7code",
            redirect_uri="https://example.com/callback",
            http_client=client,
        )

    assert result["access_token"] == "ya29.live_access"
    assert result["refresh_token"] == "1//refresh-token"


def test_exchange_code_meta_ads_returns_tokens():
    token_response = {
        "access_token": "meta_access_token_abc",
        "token_type": "bearer",
        "expires_in": 5183944,
    }
    client = _mock_http_client(token_response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        result = exchange_code(
            platform="meta_ads",
            code="meta-code-abc",
            redirect_uri="https://example.com/callback",
            http_client=client,
        )

    assert result["access_token"] == "meta_access_token_abc"


def test_exchange_code_tiktok_unwraps_data_envelope():
    """TikTok wraps tokens in a ``data`` key — broker must unwrap."""
    token_response = {
        "code": 0,
        "message": "OK",
        "data": {
            "access_token": "tiktok_access_xyz",
            "refresh_token": "tiktok_refresh_xyz",
            "advertiser_ids": ["1234567890"],
        },
    }
    client = _mock_http_client(token_response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.tiktok_app_id = "tt-app"
        mock_settings.tiktok_app_secret = "tt-secret"

        result = exchange_code(
            platform="tiktok_ads",
            code="tt_code_abc",
            redirect_uri="https://example.com/callback",
            http_client=client,
        )

    assert result["access_token"] == "tiktok_access_xyz"
    assert result["refresh_token"] == "tiktok_refresh_xyz"


def test_exchange_code_missing_access_token_raises():
    """If the platform response has no access_token, raise ValueError."""
    bad_response = {"error": "invalid_grant", "error_description": "Code expired"}
    client = _mock_http_client(bad_response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        with pytest.raises(ValueError, match="no access_token"):
            exchange_code(
                platform="google_ads",
                code="bad-code",
                redirect_uri="https://example.com",
                http_client=client,
            )


def test_exchange_code_http_error_propagates():
    """Non-2xx HTTP response from the token endpoint raises HTTPStatusError."""
    class _ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(401, content=b'{"error":"unauthorized"}')

    client = httpx.Client(transport=_ErrorTransport())

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        with pytest.raises(httpx.HTTPStatusError):
            exchange_code(
                platform="google_ads",
                code="bad",
                redirect_uri="https://example.com",
                http_client=client,
            )


def test_exchange_code_unsupported_platform_raises():
    with pytest.raises(ValueError, match="Unsupported platform"):
        exchange_code(
            platform="unknown",
            code="c",
            redirect_uri="https://example.com",
        )


# ── refresh ───────────────────────────────────────────────────────────────────


def test_refresh_google_returns_new_access_token():
    response = {"access_token": "new_access_token", "expires_in": 3600}
    client = _mock_http_client(response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        result = refresh(
            platform="google_ads",
            refresh_token="old_refresh_token",
            http_client=client,
        )

    assert result["access_token"] == "new_access_token"


def test_refresh_meta_returns_new_access_token():
    response = {"access_token": "new_meta_token", "token_type": "bearer"}
    client = _mock_http_client(response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "mid"
        mock_settings.meta_app_secret = "msecret"

        result = refresh(
            platform="meta_ads",
            refresh_token="old_meta_refresh",
            http_client=client,
        )

    assert result["access_token"] == "new_meta_token"


def test_refresh_tiktok_unwraps_data_envelope():
    response = {
        "code": 0,
        "data": {"access_token": "new_tt_token", "refresh_token": "new_tt_refresh"},
    }
    client = _mock_http_client(response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.tiktok_app_id = "ttid"
        mock_settings.tiktok_app_secret = "ttsecret"

        result = refresh(
            platform="tiktok_ads",
            refresh_token="old_tt_refresh",
            http_client=client,
        )

    assert result["access_token"] == "new_tt_token"


def test_refresh_missing_access_token_raises():
    bad_response = {"error": "invalid_grant"}
    client = _mock_http_client(bad_response)

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        with pytest.raises(ValueError, match="no access_token"):
            refresh(
                platform="google_ads",
                refresh_token="bad_refresh",
                http_client=client,
            )


def test_refresh_http_error_propagates():
    class _ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(401, content=b'{"error":"token_revoked"}')

    client = httpx.Client(transport=_ErrorTransport())

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gsecret"

        with pytest.raises(httpx.HTTPStatusError):
            refresh(
                platform="google_ads",
                refresh_token="revoked",
                http_client=client,
            )


def test_refresh_unsupported_platform_raises():
    with pytest.raises(ValueError, match="Unsupported platform"):
        refresh(platform="unknown", refresh_token="tok")


# ── store_tokens_for_account ──────────────────────────────────────────────────


def test_store_tokens_for_account_calls_vault_put():
    vault = InMemoryVault()
    tokens = {"access_token": "at", "refresh_token": "rt"}
    store_tokens_for_account("account-uuid-123", tokens, vault)
    assert vault.get("account-uuid-123") == tokens


def test_store_tokens_for_account_overwrites_existing():
    vault = InMemoryVault()
    vault.put("acc-1", {"access_token": "old"})
    store_tokens_for_account("acc-1", {"access_token": "new"}, vault)
    assert vault.get("acc-1") == {"access_token": "new"}
