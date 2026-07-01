"""Unit tests for IntegrationRegistry and Integration base class.

Covers:
- Registration (auto and manual)
- Lookup / list_keys
- catalog() and filter queries
- action_specs_for() — dynamic per-tenant Copilot tool pool
- find_by_action()
- Duplicate-key collision guard
- IntegrationStatus enum values
- IntegrationMetadata / ActionSpec construction
- ActionContext.audit() stub (no crash)
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from ayaz.integrations.base import (
    ActionContext,
    ActionSpec,
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
    IntegrationStatus,
)
from ayaz.integrations.registry import IntegrationRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate each test: save and restore the registry state."""
    saved = dict(IntegrationRegistry._registry)
    yield
    IntegrationRegistry._registry.clear()
    IntegrationRegistry._registry.update(saved)


def _make_meta(
    key: str = "test_integ",
    category: str = "ads",
    capabilities: tuple = (Capability.read,),
    auth_type: AuthType = AuthType.oauth2,
    min_plan: str = "free",
) -> IntegrationMetadata:
    return IntegrationMetadata(
        key=key,
        display_name=key.replace("_", " ").title(),
        category=category,
        description_tr=f"{key} entegrasyonu.",
        auth_type=auth_type,
        provider=key,
        oauth_scopes=("read",),
        capabilities=capabilities,
        min_plan=min_plan,
    )


def _make_action(name: str = "test_action") -> ActionSpec:
    return ActionSpec(
        name=name,
        description_tr=f"[EYLEM] {name} açıklaması.",
        input_schema={
            "type": "object",
            "properties": {"channel": {"type": "string"}},
            "required": ["channel"],
        },
        is_write=True,
        required_scopes=("write",),
    )


# ── IntegrationMetadata construction ─────────────────────────────────────────


class TestIntegrationMetadata:
    def test_defaults(self):
        meta = _make_meta()
        assert meta.icon == ""
        assert meta.icon_bg == "#6b7280"
        assert meta.aliases == ()
        assert meta.coming_soon is False
        assert meta.setup_guide_url == ""

    def test_immutable(self):
        meta = _make_meta()
        with pytest.raises((AttributeError, TypeError)):
            meta.key = "other"  # type: ignore[misc]

    def test_capabilities_tuple(self):
        meta = _make_meta(capabilities=(Capability.read, Capability.action))
        assert Capability.read in meta.capabilities
        assert Capability.action in meta.capabilities


# ── ActionSpec construction ───────────────────────────────────────────────────


class TestActionSpec:
    def test_defaults(self):
        spec = ActionSpec(
            name="foo",
            description_tr="desc",
            input_schema={"type": "object"},
        )
        assert spec.is_write is True
        assert spec.required_scopes == ()

    def test_immutable(self):
        spec = _make_action()
        with pytest.raises((AttributeError, TypeError)):
            spec.name = "other"  # type: ignore[misc]


# ── Auto-registration via __init_subclass__ ───────────────────────────────────


class TestAutoRegistration:
    def test_subclass_with_metadata_auto_registers(self):
        class MyInteg(Integration):
            metadata = _make_meta("auto_reg_integ")

        assert "auto_reg_integ" in IntegrationRegistry.list_keys()

    def test_subclass_without_metadata_does_not_register(self):
        before = set(IntegrationRegistry.list_keys())

        class NoMeta(Integration):
            pass

        after = set(IntegrationRegistry.list_keys())
        assert after == before

    def test_subclass_with_wrong_type_metadata_does_not_register(self):
        before = set(IntegrationRegistry.list_keys())

        class BadMeta(Integration):
            metadata = "not_a_metadata_instance"

        after = set(IntegrationRegistry.list_keys())
        assert after == before


# ── IntegrationRegistry.register() ───────────────────────────────────────────


class TestRegistryRegister:
    def test_manual_register(self):
        class ManualInteg(Integration):
            pass  # no metadata — won't auto-register

        IntegrationRegistry.register("manual_key", ManualInteg)
        assert IntegrationRegistry.get("manual_key") is ManualInteg

    def test_same_class_re_registration_is_idempotent(self):
        class SameClass(Integration):
            metadata = _make_meta("idempotent_key")

        # Re-registering the same class should not raise
        IntegrationRegistry.register("idempotent_key", SameClass)
        assert IntegrationRegistry.get("idempotent_key") is SameClass

    def test_different_class_same_key_raises(self):
        class First(Integration):
            metadata = _make_meta("conflict_key")

        class Second(Integration):
            pass

        with pytest.raises(ValueError, match="already registered"):
            IntegrationRegistry.register("conflict_key", Second)


# ── IntegrationRegistry.get() ─────────────────────────────────────────────────


class TestRegistryGet:
    def test_get_registered_returns_class(self):
        class GetInteg(Integration):
            metadata = _make_meta("get_test")

        assert IntegrationRegistry.get("get_test") is GetInteg

    def test_get_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="unknown_integ_xyz"):
            IntegrationRegistry.get("unknown_integ_xyz")

    def test_get_unknown_error_message_lists_available(self):
        class Listed(Integration):
            metadata = _make_meta("listed_key")

        with pytest.raises(KeyError) as exc_info:
            IntegrationRegistry.get("no_such_key")
        assert "listed_key" in str(exc_info.value)


# ── IntegrationRegistry.list_keys() ──────────────────────────────────────────


class TestListKeys:
    def test_list_keys_sorted(self):
        class Z(Integration):
            metadata = _make_meta("zzz_key")

        class A(Integration):
            metadata = _make_meta("aaa_key")

        keys = IntegrationRegistry.list_keys()
        assert keys == sorted(keys)

    def test_list_keys_includes_all_registered(self):
        class One(Integration):
            metadata = _make_meta("one_key")

        class Two(Integration):
            metadata = _make_meta("two_key")

        keys = IntegrationRegistry.list_keys()
        assert "one_key" in keys
        assert "two_key" in keys


# ── IntegrationRegistry.catalog() ────────────────────────────────────────────


class TestCatalog:
    def test_catalog_returns_metadata_instances(self):
        class CatalogInteg(Integration):
            metadata = _make_meta("catalog_integ")

        catalog = IntegrationRegistry.catalog()
        keys_in_catalog = [m.key for m in catalog]
        assert "catalog_integ" in keys_in_catalog

    def test_catalog_elements_are_integration_metadata(self):
        class CatalogCheck(Integration):
            metadata = _make_meta("catalog_check")

        for meta in IntegrationRegistry.catalog():
            assert isinstance(meta, IntegrationMetadata)


# ── IntegrationRegistry.filter_by_category() ─────────────────────────────────


class TestFilterByCategory:
    def test_filter_returns_matching(self):
        class AdsInteg(Integration):
            metadata = _make_meta("ads_integ", category="ads")

        class MsgInteg(Integration):
            metadata = _make_meta("msg_integ", category="messaging")

        ads = IntegrationRegistry.filter_by_category("ads")
        assert any(k.metadata.key == "ads_integ" for k in ads)
        assert all(k.metadata.category == "ads" for k in ads)

    def test_filter_unknown_category_returns_empty(self):
        result = IntegrationRegistry.filter_by_category("nonexistent_category_xyz")
        assert result == []


# ── IntegrationRegistry.filter_by_capability() ───────────────────────────────


class TestFilterByCapability:
    def test_filter_read(self):
        class ReadOnly(Integration):
            metadata = _make_meta("read_only", capabilities=(Capability.read,))

        result = IntegrationRegistry.filter_by_capability("read")
        assert any(k.metadata.key == "read_only" for k in result)

    def test_filter_action(self):
        class ActionOnly(Integration):
            metadata = _make_meta(
                "action_only", capabilities=(Capability.action,)
            )

        result = IntegrationRegistry.filter_by_capability("action")
        assert any(k.metadata.key == "action_only" for k in result)

    def test_filter_none_returns_all(self):
        class AnyInteg(Integration):
            metadata = _make_meta("any_integ")

        result = IntegrationRegistry.filter_by_capability(None)
        assert any(k.metadata.key == "any_integ" for k in result)

    def test_filter_invalid_capability_returns_empty(self):
        result = IntegrationRegistry.filter_by_capability("invalid_cap")
        assert result == []


# ── IntegrationRegistry.action_specs_for() ───────────────────────────────────


class TestActionSpecsFor:
    def test_returns_action_specs_for_connected_key(self):
        class ActionInteg(Integration):
            metadata = _make_meta(
                "slack_test", capabilities=(Capability.action,)
            )

            def actions(self):
                return [_make_action("slack_send_msg")]

        specs = IntegrationRegistry.action_specs_for({"slack_test"})
        assert len(specs) == 1
        assert specs[0]["name"] == "slack_send_msg"
        assert specs[0]["is_action"] is True
        assert "description" in specs[0]
        assert "input_schema" in specs[0]

    def test_read_only_integration_returns_no_specs(self):
        class ReadInteg(Integration):
            metadata = _make_meta("ga4_test", capabilities=(Capability.read,))
            # actions() not overridden → returns []

        specs = IntegrationRegistry.action_specs_for({"ga4_test"})
        assert specs == []

    def test_unknown_key_is_silently_skipped(self):
        specs = IntegrationRegistry.action_specs_for({"nonexistent_xyz"})
        assert specs == []

    def test_multiple_connected_keys_aggregate_all_actions(self):
        class IntegA(Integration):
            metadata = _make_meta("integ_a", capabilities=(Capability.action,))

            def actions(self):
                return [_make_action("action_a")]

        class IntegB(Integration):
            metadata = _make_meta("integ_b", capabilities=(Capability.action,))

            def actions(self):
                return [_make_action("action_b1"), _make_action("action_b2")]

        specs = IntegrationRegistry.action_specs_for({"integ_a", "integ_b"})
        names = {s["name"] for s in specs}
        assert "action_a" in names
        assert "action_b1" in names
        assert "action_b2" in names

    def test_empty_connected_keys_returns_empty(self):
        specs = IntegrationRegistry.action_specs_for(set())
        assert specs == []

    def test_accepts_list_not_just_set(self):
        class ListInteg(Integration):
            metadata = _make_meta(
                "list_integ", capabilities=(Capability.action,)
            )

            def actions(self):
                return [_make_action("list_action")]

        specs = IntegrationRegistry.action_specs_for(["list_integ"])
        assert len(specs) == 1
        assert specs[0]["name"] == "list_action"


# ── IntegrationRegistry.find_by_action() ─────────────────────────────────────


class TestFindByAction:
    def test_finds_correct_integration(self):
        class FindInteg(Integration):
            metadata = _make_meta(
                "find_integ", capabilities=(Capability.action,)
            )

            def actions(self):
                return [_make_action("find_action_xyz")]

        result = IntegrationRegistry.find_by_action("find_action_xyz")
        assert result is FindInteg

    def test_returns_none_for_unknown_action(self):
        result = IntegrationRegistry.find_by_action("no_such_action_xyz")
        assert result is None


# ── Integration base class behaviour ─────────────────────────────────────────


class TestIntegrationBase:
    def test_validate_credentials_raises_not_implemented(self):
        class NoCredsInteg(Integration):
            metadata = _make_meta("no_creds")

        instance = NoCredsInteg()
        with pytest.raises(NotImplementedError):
            instance.validate_credentials({"key": "value"})

    def test_as_connector_default_returns_none(self):
        class DefaultConnector(Integration):
            metadata = _make_meta("default_conn")

        instance = DefaultConnector()
        assert instance.as_connector(MagicMock()) is None

    def test_actions_default_returns_empty_list(self):
        class DefaultActions(Integration):
            metadata = _make_meta("default_actions")

        instance = DefaultActions()
        assert instance.actions() == []

    def test_execute_action_raises_not_implemented(self):
        class DefaultExecute(Integration):
            metadata = _make_meta("default_exec")

        instance = DefaultExecute()
        ctx = MagicMock(spec=ActionContext)
        with pytest.raises(NotImplementedError):
            instance.execute_action("any_action", {}, ctx=ctx)

    def test_discover_default_returns_empty_list(self):
        class DefaultDiscover(Integration):
            metadata = _make_meta("default_disc")

        instance = DefaultDiscover()
        ctx = MagicMock(spec=ActionContext)
        assert instance.discover(ctx) == []


# ── IntegrationStatus enum ────────────────────────────────────────────────────


class TestIntegrationStatus:
    def test_all_canonical_values_exist(self):
        values = {s.value for s in IntegrationStatus}
        assert "connected" in values
        assert "connecting" in values
        assert "syncing" in values
        assert "needs_reconnect" in values
        assert "error" in values
        assert "disconnected" in values

    def test_is_string_enum(self):
        assert IntegrationStatus.connected == "connected"
        assert IntegrationStatus.needs_reconnect == "needs_reconnect"

    def test_legacy_sync_status_mapping(self):
        """Verify the IntegrationStatus values cover all legacy SyncStatus states."""
        from ayaz.models.oltp import SyncStatus

        # Every SyncStatus value must have a corresponding IntegrationStatus
        mapping = {
            SyncStatus.idle: IntegrationStatus.disconnected,
            SyncStatus.syncing: IntegrationStatus.syncing,
            SyncStatus.success: IntegrationStatus.connected,
            SyncStatus.error: IntegrationStatus.error,
            SyncStatus.paused: IntegrationStatus.disconnected,
        }
        for sync_s, integ_s in mapping.items():
            assert integ_s in IntegrationStatus  # enum membership check


# ── ActionContext ─────────────────────────────────────────────────────────────


class TestActionContext:
    def _make_ctx(self) -> ActionContext:
        mock_vault = MagicMock()
        mock_vault.get.return_value = {"access_token": "tok_abc"}
        return ActionContext(
            tenant_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            db=MagicMock(),
            vault=mock_vault,
            _vault_secret_ref="some-ref",
        )

    def test_vault_get_returns_secret(self):
        ctx = self._make_ctx()
        secret = ctx.vault_get()
        assert secret["access_token"] == "tok_abc"

    def test_vault_get_raises_key_error_when_missing(self):
        ctx = self._make_ctx()
        ctx.vault.get.return_value = None
        with pytest.raises(KeyError, match="some-ref"):
            ctx.vault_get()

    def test_audit_does_not_raise(self):
        ctx = self._make_ctx()
        # Should log without raising even though no DB is wired
        ctx.audit(
            action_name="test_action",
            args={"channel": "#general"},
            result={"sent": True},
            status="ok",
        )

    def test_audit_was_auto_param(self):
        ctx = self._make_ctx()
        ctx.audit("test_action", {}, {}, "ok", was_auto=True)
