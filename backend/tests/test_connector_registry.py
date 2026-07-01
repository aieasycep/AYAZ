"""Tests for the ConnectorRegistry."""

from __future__ import annotations

import pytest

from ayaz.connectors.base import Connector, ConnectorCapabilities, ConnectorConfig
from ayaz.connectors.registry import ConnectorRegistry
from ayaz.connectors.sample import SampleConnector


def test_registry_has_sample() -> None:
    assert "sample" in ConnectorRegistry.list_keys()


def test_registry_get_returns_class() -> None:
    cls = ConnectorRegistry.get("sample")
    assert issubclass(cls, Connector)


def test_registry_get_unknown_raises() -> None:
    with pytest.raises(KeyError, match="unknown_platform"):
        ConnectorRegistry.get("unknown_platform")


def test_registry_list_keys_sorted() -> None:
    keys = ConnectorRegistry.list_keys()
    assert keys == sorted(keys)


def test_duplicate_registration_same_class_is_idempotent() -> None:
    """Re-registering the same class under the same key is safe (no error)."""
    ConnectorRegistry.register("sample", SampleConnector)  # should not raise


def test_duplicate_registration_different_class_raises() -> None:
    """Registering a *different* class under an existing key must raise."""

    class AnotherSample(Connector):
        # Do NOT set platform_key here — we want to call register() directly
        # to avoid auto-registration side-effects in __init_subclass__.
        def authenticate(self) -> None: ...
        def refresh_token(self) -> None: ...
        def discover(self): return []
        def fetch(self, stream, since, until): return []
        def normalize(self, raw): return []
        def incremental_state(self): return {}
        def capabilities(self): ...

    with pytest.raises(ValueError, match="already registered"):
        ConnectorRegistry.register("sample", AnotherSample)  # type: ignore[arg-type]
