"""Unit tests for the OAuth Broker service.

Coverage
--------
- build_authorize_url: correct URL construction for all 5 platforms, unsupported platform.
- _sign_state / parse_state: round-trip, invalid token handling.
- exchange_code: mocked HTTP POST, token extraction, TikTok envelope unwrapping,
  missing access_token error, Meta's two-hop short-lived→long-lived token exchange
  (request shape verified via a recording mock transport, not just canned output).
- refresh: mocked HTTP POST, token extraction, TikTok refresh URL, missing token error,
  Meta's fb_exchange_token grant (NOT the generic refresh_token grant — Meta has none).
- store_tokens_for_account: delegates to vault.put.

No live network calls are made — all HTTP calls use an httpx mock transport.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


class _RecordingTransport(httpx.BaseTransport):
    """Mock transport that records every request it sees (method, URL, params)
    and answers with canned JSON bodies in call order — one entry of
    ``responses`` per expected HTTP call.  Used to assert on request SHAPE
    (method / grant_type / param names), not just the final parsed result —
    needed for Meta's two-hop token exchange where hop 1 vs hop 2 must use
    different grant types and HTTP methods.
    """

    def __init__(
        self,
        responses: list[dict],
        status_code: int = 200,
        statuses: list[int] | None = None,
    ) -> None:
        self.responses = responses
        # Per-call status code override (e.g. hop1=200, hop2=401). Falls back
        # to ``status_code`` for any call index not covered by ``statuses``.
        self.statuses = statuses or []
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        idx = len(self.requests) - 1
        body = json.dumps(self.responses[idx]).encode()
        status = self.statuses[idx] if idx < len(self.statuses) else self.status_code
        return httpx.Response(status, content=body)


def _recording_http_client(
    responses: list[dict],
    statuses: list[int] | None = None,
) -> tuple[httpx.Client, _RecordingTransport]:
    """Return (client, transport) — inspect ``transport.requests`` after the call.

    ``statuses`` (optional) sets a per-call HTTP status code, e.g.
    ``[200, 401]`` to make hop 1 succeed and hop 2 fail — needed to test
    Meta's two-hop exchange error paths.
    """
    transport = _RecordingTransport(responses, statuses=statuses)
    return httpx.Client(transport=transport), transport


def _request_params(request: httpx.Request) -> dict[str, str]:
    """Flatten a recorded request's params — query string for GET, form body for POST."""
    if request.method == "GET":
        return dict(httpx.QueryParams(request.url.query))
    return dict(httpx.QueryParams(request.content.decode()))


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


def test_exchange_code_meta_ads_hops_to_long_lived_token():
    """Meta's authorization_code grant only returns a SHORT-LIVED (~1-2h)
    token — exchange_code() must immediately hop to a second request
    (grant_type=fb_exchange_token) and return the LONG-LIVED (~60d) token,
    not the short-lived one from hop 1.
    """
    short_lived = {
        "access_token": "short_lived_token_abc",
        "token_type": "bearer",
        "expires_in": 5400,  # ~1.5h
    }
    long_lived = {
        "access_token": "long_lived_token_xyz",
        "token_type": "bearer",
        "expires_in": 5183944,  # ~60 days
    }
    client, transport = _recording_http_client([short_lived, long_lived])

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        result = exchange_code(
            platform="meta_ads",
            code="meta-code-abc",
            redirect_uri="https://example.com/callback",
            http_client=client,
        )

    # Final returned token must be the LONG-LIVED one, with its expires_in.
    assert result["access_token"] == "long_lived_token_xyz"
    assert result["expires_in"] == 5183944

    assert len(transport.requests) == 2
    hop1, hop2 = transport.requests

    # Hop 1: standard authorization_code grant (short-lived token).
    assert hop1.method == "POST"
    hop1_params = _request_params(hop1)
    assert hop1_params["grant_type"] == "authorization_code"
    assert hop1_params["code"] == "meta-code-abc"
    assert hop1_params["redirect_uri"] == "https://example.com/callback"
    assert hop1_params["client_id"] == "meta-id"
    assert hop1_params["client_secret"] == "meta-secret"

    # Hop 2: fb_exchange_token grant, feeding hop 1's token back in.
    assert hop2.method == "GET"
    hop2_params = _request_params(hop2)
    assert hop2_params["grant_type"] == "fb_exchange_token"
    assert hop2_params["fb_exchange_token"] == "short_lived_token_abc"
    assert hop2_params["client_id"] == "meta-id"
    assert hop2_params["client_secret"] == "meta-secret"

    # Both hops target the same Meta token endpoint (from _PLATFORM_CONFIGS).
    meta_token_url = _PLATFORM_CONFIGS["meta_ads"].token_url
    assert str(hop1.url).split("?")[0] == meta_token_url
    assert str(hop2.url).split("?")[0] == meta_token_url


def test_exchange_code_meta_ads_includes_absolute_token_expires_at():
    """The long-lived token dict returned by exchange_code() must carry an
    absolute ``token_expires_at`` (ISO-8601 UTC) computed from the LONG-LIVED
    hop's ``expires_in`` (~60 days) — not the short-lived hop's ~1-2h value.
    A relative ``expires_in`` alone is useless once persisted to the Vault
    (see sync.py's Meta rolling-refresh, which reads this field back)."""
    short_lived = {
        "access_token": "short_lived_token_abc",
        "token_type": "bearer",
        "expires_in": 5400,  # ~1.5h — must NOT be what token_expires_at is based on
    }
    long_lived = {
        "access_token": "long_lived_token_xyz",
        "token_type": "bearer",
        "expires_in": 5183944,  # ~60 days
    }
    client, _transport = _recording_http_client([short_lived, long_lived])

    before = datetime.now(timezone.utc)
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        result = exchange_code(
            platform="meta_ads",
            code="meta-code-abc",
            redirect_uri="https://example.com/callback",
            http_client=client,
        )
    after = datetime.now(timezone.utc)

    assert "token_expires_at" in result
    expires_at = datetime.fromisoformat(result["token_expires_at"])
    # Must be based on the LONG-LIVED hop's expires_in (~60 days), within a
    # generous tolerance for test execution time.
    assert before + timedelta(seconds=5183944) - timedelta(seconds=5) <= expires_at
    assert expires_at <= after + timedelta(seconds=5183944) + timedelta(seconds=5)


def test_exchange_code_meta_ads_hop2_http_error_propagates():
    """Hop 1 (authorization_code) succeeds, but hop 2 (fb_exchange_token)
    comes back non-2xx (e.g. Meta rejects the short-lived token) —
    ``raise_for_status()`` on hop 2 must propagate HTTPStatusError. The
    caller must NOT silently fall back to the short-lived hop-1 token.
    """
    short_lived = {
        "access_token": "short_lived_token_abc",
        "token_type": "bearer",
        "expires_in": 5400,
    }
    hop2_error_body = {
        "error": {"message": "Invalid OAuth access token", "code": 190}
    }
    client, transport = _recording_http_client(
        [short_lived, hop2_error_body],
        statuses=[200, 401],
    )

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        with pytest.raises(httpx.HTTPStatusError):
            exchange_code(
                platform="meta_ads",
                code="meta-code-abc",
                redirect_uri="https://example.com/callback",
                http_client=client,
            )

    # Hop 2 was attempted (not skipped) before the error surfaced.
    assert len(transport.requests) == 2
    assert transport.requests[1].method == "GET"


def test_exchange_code_meta_ads_hop2_missing_access_token_raises():
    """Hop 2 returns 200 but the body has no access_token (malformed/edge-case
    Meta response) — must raise the long-lived-specific ValueError, not
    silently return the short-lived hop-1 token.
    """
    short_lived = {
        "access_token": "short_lived_token_abc",
        "token_type": "bearer",
        "expires_in": 5400,
    }
    hop2_no_token_body = {"token_type": "bearer"}  # no access_token key
    client, transport = _recording_http_client([short_lived, hop2_no_token_body])

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "meta-id"
        mock_settings.meta_app_secret = "meta-secret"

        with pytest.raises(
            ValueError, match="Meta long-lived token exchange returned no access_token"
        ):
            exchange_code(
                platform="meta_ads",
                code="meta-code-abc",
                redirect_uri="https://example.com/callback",
                http_client=client,
            )

    assert len(transport.requests) == 2


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


def test_refresh_meta_uses_fb_exchange_token_grant_not_refresh_token():
    """Meta has NO ``refresh_token`` grant. refresh() must send
    grant_type=fb_exchange_token with the current long-lived token passed
    as ``fb_exchange_token`` — sending grant_type=refresh_token (the
    generic branch) is rejected by the Graph API.
    """
    response = {
        "access_token": "re_extended_long_lived_token",
        "token_type": "bearer",
        "expires_in": 5184000,
    }
    client, transport = _recording_http_client([response])

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "mid"
        mock_settings.meta_app_secret = "msecret"

        result = refresh(
            platform="meta_ads",
            refresh_token="current_long_lived_token",
            http_client=client,
        )

    assert result["access_token"] == "re_extended_long_lived_token"

    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.method == "GET"
    params = _request_params(req)
    assert params["grant_type"] == "fb_exchange_token"
    assert params["fb_exchange_token"] == "current_long_lived_token"
    assert params["client_id"] == "mid"
    assert params["client_secret"] == "msecret"
    # Must NOT use the generic refresh_token param name.
    assert "refresh_token" not in params


def test_refresh_meta_http_error_propagates():
    """The fb_exchange_token GET comes back non-2xx (e.g. the stored token
    was revoked/expired) — raise_for_status() must propagate
    HTTPStatusError, same as every other platform's refresh() error path.
    """
    client, transport = _recording_http_client(
        [{"error": {"message": "Error validating access token", "code": 190}}],
        statuses=[401],
    )

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "mid"
        mock_settings.meta_app_secret = "msecret"

        with pytest.raises(httpx.HTTPStatusError):
            refresh(
                platform="meta_ads",
                refresh_token="revoked_long_lived_token",
                http_client=client,
            )

    assert len(transport.requests) == 1
    assert transport.requests[0].method == "GET"


def test_refresh_meta_missing_access_token_raises():
    """The fb_exchange_token GET returns 200 but no access_token in the
    body — must raise ValueError like every other platform's refresh(),
    not silently return an incomplete token dict.
    """
    client, transport = _recording_http_client([{"token_type": "bearer"}])

    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "mid"
        mock_settings.meta_app_secret = "msecret"

        with pytest.raises(ValueError, match="no access_token"):
            refresh(
                platform="meta_ads",
                refresh_token="current_long_lived_token",
                http_client=client,
            )

    assert len(transport.requests) == 1


def test_refresh_meta_includes_absolute_token_expires_at():
    """refresh()'s Meta fb_exchange_token result must also carry an absolute
    ``token_expires_at`` — sync.py's rolling refresh persists this field back
    to the Vault so the NEXT sync can decide whether to renew again."""
    response = {
        "access_token": "re_extended_long_lived_token",
        "token_type": "bearer",
        "expires_in": 5184000,  # 60 days exactly
    }
    client, _transport = _recording_http_client([response])

    before = datetime.now(timezone.utc)
    with patch("ayaz.services.oauth_broker.settings") as mock_settings:
        mock_settings.meta_app_id = "mid"
        mock_settings.meta_app_secret = "msecret"

        result = refresh(
            platform="meta_ads",
            refresh_token="current_long_lived_token",
            http_client=client,
        )
    after = datetime.now(timezone.utc)

    assert "token_expires_at" in result
    expires_at = datetime.fromisoformat(result["token_expires_at"])
    assert before + timedelta(seconds=5184000) - timedelta(seconds=5) <= expires_at
    assert expires_at <= after + timedelta(seconds=5184000) + timedelta(seconds=5)


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
