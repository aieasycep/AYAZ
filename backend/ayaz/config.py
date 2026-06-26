"""Application configuration — all values sourced from environment variables.

Load order: environment → .env file (if present) → defaults.
Never import secrets into module-level variables; always use the ``settings``
singleton so the values stay in one place and are easy to mock in tests.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Insecure development defaults that MUST be overridden before a production
# deploy.  The production startup guard (see ``_reject_insecure_production``)
# refuses to boot if any of these are still in place when
# ``environment == "production"``.
_INSECURE_JWT_SECRET = "changeme"
_INSECURE_VAULT_KEY = "ZEVBWUFaX0RFVl9WQVVMVF9LRVlfMzJCWVRFU18h"
_INSECURE_VAULT_TOKEN = "root"


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg://ayaz:ayaz@localhost:5432/ayaz"
    )

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret: str = _INSECURE_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── App ───────────────────────────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:3000"]

    # ── Vault ─────────────────────────────────────────────────────────────────
    # TODO (Faz 1): replace with real HashiCorp Vault client
    vault_addr: str = "http://localhost:8200"
    vault_token: str = _INSECURE_VAULT_TOKEN
    # vault_key: 32-byte URL-safe base64 string used to derive a Fernet key.
    # In production set this via the VAULT_KEY environment variable — never commit
    # a real key.  The dev default is a deterministic test-only value.
    vault_key: str = _INSECURE_VAULT_KEY

    # ── OAuth Broker ─────────────────────────────────────────────────────────
    # Per-platform OAuth2 client credentials (injected via env in production).
    google_client_id: str = ""
    google_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    tiktok_app_id: str = ""
    tiktok_app_secret: str = ""

    # ── AI / Insights ─────────────────────────────────────────────────────────
    # Anthropic API key for ClaudeNarrator (M4 AI insights).
    # Leave empty (default) to use TemplateNarrator (no network, fully offline).
    anthropic_api_key: str = ""
    # Model ID used by ClaudeNarrator when anthropic_api_key is set.
    claude_narrator_model: str = "claude-opus-4-8"

    # ── Billing ───────────────────────────────────────────────────────────────
    # Provider selection: "none" (stub/free), "iyzico" (TR), "stripe" (global).
    # Leave as "none" in development; set via BILLING_PROVIDER env var in production.
    billing_provider: str = "none"
    # iyzico credentials (TR market).  Leave empty in development / stub mode.
    iyzico_api_key: str = ""
    iyzico_secret_key: str = ""
    # Stripe credentials (global market).  Leave empty in development / stub mode.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string or a list."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _reject_insecure_production(self) -> "Settings":
        """Fail fast if the app is started in production with insecure defaults.

        The dev/test defaults for ``jwt_secret`` and ``vault_key`` are known,
        committed values — if they reach production an attacker can forge JWTs
        (full account takeover, cross-tenant access) and decrypt every stored
        OAuth token / API key (the crown jewels).  This guard only fires when
        ``environment == "production"`` so development and the test-suite, which
        rely on the defaults, are unaffected.
        """
        if self.environment != "production":
            return self

        problems: list[str] = []
        if self.jwt_secret == _INSECURE_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET is the insecure default or shorter than 32 chars"
            )
        if self.vault_key == _INSECURE_VAULT_KEY:
            problems.append("VAULT_KEY is the insecure committed default")
        if self.vault_token == _INSECURE_VAULT_TOKEN:
            problems.append("VAULT_TOKEN is the insecure default ('root')")
        if self.debug:
            problems.append("DEBUG must be False in production")

        if problems:
            raise ValueError(
                "Refusing to start in production with insecure configuration: "
                + "; ".join(problems)
                + ". Set strong values via environment variables."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()


# Convenient module-level alias
settings = get_settings()
