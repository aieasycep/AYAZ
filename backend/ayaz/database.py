"""SQLAlchemy async-compatible session factory.

Using synchronous psycopg3 driver for simplicity in Faz 1.
TODO (Faz 2): switch to async engine (``create_async_engine``) when the
Celery workers are replaced by an async task runner (e.g. arq/taskiq).
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ayaz.config import settings

if settings.database_url.startswith("sqlite"):
    # Local/demo/dev convenience: run without Postgres. A single shared
    # connection (StaticPool + check_same_thread=False) keeps an in-memory or
    # file-based SQLite consistent across FastAPI's threadpool. The Postgres
    # production path below is unchanged.
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=settings.debug,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.debug,
    )

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
