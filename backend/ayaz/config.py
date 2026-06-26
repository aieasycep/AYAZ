"""Application configuration — all values sourced from environment variables.

Load order: environment → .env file (if present) → defaults.
Never import secrets into module-level variables; always use the ``settings``
singleton so the values stay in one place and are easy to mock in tests.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    jwt_secret: str = "changeme"
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
    vault_token: str = "root"
    # vault_key: 32-byte URL-safe base64 string used to derive a Fernet key.
    # In production set this via the VAULT_KEY environment variable — never commit
    # a real key.  The dev default is a deterministic test-only value.
    vault_key: str = "ZEVBWUFaX0RFVl9WQVVMVF9LRVlfMzJCWVRFU18h"

    # ── OAuth Broker ─────────────────────────────────────────────────────────
    # Per-platform OAuth2 client credentials (injected via env in production).
    google_client_id: str = ""
    google_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    tiktok_app_id: str = ""
    tiktok_app_secret: str = ""

    # ── Billing ───────────────────────────────────────────────────────────────
    # TODO (Faz 1): iyzico + Stripe integration
    iyzico_api_key: str = ""
    iyzico_secret_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string or a list."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()


# Convenient module-level alias
settings = get_settings()
