"""Config tests — DATABASE_URL normalization + ALLOWED_ORIGINS parsing.

Both are deploy-critical:

* Managed Postgres providers (Neon, Supabase, Render, Railway) hand out
  ``postgres://`` / ``postgresql://`` connection strings. SQLAlchemy maps the
  bare ``postgresql://`` scheme to psycopg2 (not installed); the app uses
  psycopg3. The ``Settings._normalize_database_url`` validator rewrites these so
  a pasted provider URL works as-is.
* ``ALLOWED_ORIGINS`` is a comma-separated env string (e.g.
  ``https://a.app,https://b.app``). Because the field is a ``list[str]``,
  pydantic-settings would otherwise JSON-decode it at the source level and crash
  the boot. ``NoDecode`` keeps the raw string so ``_split_origins`` can split it.

These tests lock both behaviours.
"""

import pytest

from ayaz.config import Settings


def _url(database_url: str) -> str:
    return Settings(database_url=database_url).database_url


def test_bare_postgresql_scheme_gets_psycopg_driver():
    assert _url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"


def test_postgres_alias_scheme_gets_psycopg_driver():
    assert _url("postgres://u:p@host/db") == "postgresql+psycopg://u:p@host/db"


def test_neon_style_url_preserves_query_and_sslmode():
    src = "postgresql://u:p@ep-cool-1.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    out = _url(src)
    assert out.startswith("postgresql+psycopg://")
    assert out.endswith("?sslmode=require")
    assert "neon.tech/neondb" in out


def test_already_qualified_psycopg_url_unchanged():
    src = "postgresql+psycopg://u:p@host/db"
    assert _url(src) == src


def test_sqlite_url_unchanged():
    src = "sqlite:////tmp/demo.db"
    assert _url(src) == src


# ── ALLOWED_ORIGINS parsing (deploy-critical — Render boot crashed here) ───────


def test_allowed_origins_comma_string_from_env(monkeypatch):
    """A comma-separated ALLOWED_ORIGINS env var must parse into a list.

    This is the exact value shape set in the Render dashboard. Before the
    ``NoDecode`` fix, pydantic-settings tried to ``json.loads`` it and the app
    refused to boot with ``SettingsError``.
    """
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://ayaz-beryl.vercel.app,https://ayaz-git-foo-ayaz3.vercel.app",
    )
    assert Settings().allowed_origins == [
        "https://ayaz-beryl.vercel.app",
        "https://ayaz-git-foo-ayaz3.vercel.app",
    ]


def test_allowed_origins_single_value_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://ayaz.vercel.app")
    assert Settings().allowed_origins == ["https://ayaz.vercel.app"]


def test_allowed_origins_strips_whitespace_and_blanks(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://a.app , , https://b.app ")
    assert Settings().allowed_origins == ["https://a.app", "https://b.app"]


@pytest.mark.parametrize("raw", ["", "   "])
def test_allowed_origins_empty_env_yields_empty_list(monkeypatch, raw):
    monkeypatch.setenv("ALLOWED_ORIGINS", raw)
    assert Settings().allowed_origins == []


def test_allowed_origins_list_kwarg_unchanged():
    """Passing a list directly (the default path / tests) still works."""
    origins = ["http://localhost:3000", "http://localhost:3001"]
    assert Settings(allowed_origins=origins).allowed_origins == origins
