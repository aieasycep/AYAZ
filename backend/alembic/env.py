"""Alembic environment — wires the SQLAlchemy models into the migration engine.

Run migrations::

    cd backend
    alembic upgrade head

Generate a new migration after model changes::

    alembic revision --autogenerate -m "describe the change"

Autogenerate is powered by importing all model modules (via ``ayaz.models``)
so every table registered on ``Base.metadata`` is picked up automatically.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ayaz.config import settings

# Import all models so they register on Base.metadata before autogenerate runs
import ayaz.models  # noqa: F401
from ayaz.models.base import Base

# Alembic Config object
config = context.config

# Override SQLAlchemy URL from our Settings (env / .env file)
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode (no DB connection required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
