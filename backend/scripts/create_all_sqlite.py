"""Bootstrap script: create all SQLAlchemy tables using Base.metadata.create_all.

This is the CI/SQLite alternative to Alembic migrations.  Alembic's migration
scripts contain Postgres-specific constructs (server_default expressions, native
UUID type, etc.) that fail on SQLite.  ``create_all`` derives the DDL from the
current ORM models, so it works on any SQLAlchemy-supported backend.

Usage
-----
From the ``backend/`` directory:

    python -m scripts.create_all_sqlite
    python scripts/create_all_sqlite.py

The script is safe to run against a pre-existing database: SQLAlchemy's
``create_all`` skips tables that already exist (``checkfirst=True`` by default).

Environment
-----------
DATABASE_URL  — SQLAlchemy URL, e.g.:
                  sqlite:////abs/path/to/dev.db
                  sqlite:///:memory:
                  postgresql+psycopg://ayaz:ayaz@localhost/ayaz
                Defaults to the value in ayaz.config (which itself reads the
                DATABASE_URL env var or falls back to the Postgres default).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python scripts/create_all_sqlite.py`` (run as plain script from any CWD)
# as well as ``python -m scripts.create_all_sqlite`` (run as module from backend/).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# Import every model module so their tables are registered on Base.metadata
# before we call create_all.  The canonical list lives in ayaz/models/__init__.py;
# we import it wholesale here so this script never drifts out of sync.
# ---------------------------------------------------------------------------

import ayaz.models  # noqa: F401 — side-effect import; registers all ORM classes

# Also import the Notification model which is not yet in ayaz/models/__init__.py
# (added in Dalga 26; keep this import until the package __init__ is updated).
try:
    from ayaz.models.notifications import Notification  # noqa: F401
except ImportError:
    pass  # forward-compat: safe to skip if not yet present

from ayaz.models.base import Base
from ayaz.database import engine


def create_all() -> None:
    """Create all tables for the configured database, skipping existing ones."""
    url = engine.url
    print(f"Creating tables on: {url}")
    Base.metadata.create_all(engine)
    table_names = sorted(Base.metadata.tables.keys())
    print(f"Done — {len(table_names)} tables registered:")
    for t in table_names:
        print(f"  {t}")


if __name__ == "__main__":
    create_all()
