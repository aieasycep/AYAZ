"""Config tests — DATABASE_URL normalization (deploy-critical).

Managed Postgres providers (Neon, Supabase, Render, Railway) hand out
``postgres://`` / ``postgresql://`` connection strings. SQLAlchemy maps the
bare ``postgresql://`` scheme to psycopg2 (not installed); the app uses
psycopg3. The ``Settings._normalize_database_url`` validator rewrites these so
a pasted provider URL works as-is. These tests lock that behaviour.
"""

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
