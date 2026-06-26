"""Declarative base and shared column helpers."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CHAR, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent UUID column type.

    Uses PostgreSQL's native ``UUID`` type in production and falls back to a
    deterministic ``CHAR(32)`` hex representation everywhere else (e.g. the
    in-memory SQLite engine used by the test-suite).

    Why a custom type instead of ``postgresql.UUID(as_uuid=True)`` directly:
    the dialect-specific type leans on SQLAlchemy's generic UUID bind/result
    processors on non-PostgreSQL backends, which — combined with the compiled
    statement cache — proved fragile across SQLAlchemy point releases (a
    cached result processor could receive a value of the wrong Python type and
    raise ``'float' object has no attribute 'replace'`` deep inside
    ``uuid.UUID``). This decorator owns its bind/result processing explicitly
    and always round-trips through ``uuid.UUID`` objects, so behaviour is
    identical and stable on both PostgreSQL and SQLite.

    ``as_uuid`` is accepted for drop-in compatibility with the previous
    ``postgresql.UUID(as_uuid=True)`` call sites; values are always returned as
    ``uuid.UUID`` instances regardless.
    """

    impl = CHAR
    cache_ok = True

    def __init__(self, as_uuid: bool = True, **kwargs) -> None:  # noqa: ARG002
        self.as_uuid = as_uuid
        super().__init__(**kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            # native UUID type handles uuid.UUID objects directly
            return value
        # store as a plain 32-char hex string on non-native backends
        return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# Backwards-compatible alias: existing models import ``UUID`` from the
# postgresql dialect; they now import this portable type under the same name.
UUID = GUID


class Base(DeclarativeBase):
    """Shared declarative base for all AYAZ ORM models."""


def utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """Convenience factory for a UUID primary key column."""
    return mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
