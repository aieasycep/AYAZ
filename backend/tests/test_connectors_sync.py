"""Manual sync endpoint — POST /connectors/accounts/{id}/sync.

Uses the credential-free ``sample`` connector so the whole trigger→fetch→upsert
path runs end-to-end and actually writes fact rows, without real OAuth.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker

import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401

from ayaz.database import get_db
from ayaz.models.analytics import FactDailyMetrics
from ayaz.models.base import Base
from ayaz.models.oltp import (
    ConnectedAccount, Membership, MembershipRole, Platform, SyncStatus, Tenant, User,
)
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import connectors as connectors_module
from ayaz.services.auth import hash_password
from ayaz.services.vault import InMemoryVault

_test_app = FastAPI(title="AYAZ Connectors Sync Test App")
_test_app.include_router(connectors_module.router, prefix="/api/v1")


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def ctx(db_session: Session):
    tenant = Tenant(
        id=uuid.uuid4(), name="Sync Ep Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(), email="syncep@ayaz.app",
        hashed_password=hash_password("test1234"), full_name="Sync Ep",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()
    membership = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    account = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.sample,
        external_account_id="ACC-SAMPLE-1", display_name="Sample",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add(membership)
    db_session.add(account)
    db_session.commit()

    def override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    _test_app.dependency_overrides[connectors_module._get_vault] = lambda: InMemoryVault()

    with TestClient(_test_app) as c:
        yield c, db_session, tenant, account

    _test_app.dependency_overrides.clear()


def test_sync_populates_facts(ctx, tmp_path) -> None:
    """Full trigger→fetch→upsert path writes facts.

    The sample connector filters its fixture to the endpoint's date window (last
    30 days). We inject — via the Vault (which the endpoint loads into
    ConnectorConfig.extra) — a fixture_path pointing at a row dated *today*, so
    the window always overlaps and a fact is written deterministically.
    """
    client, db, tenant, account = ctx
    today = datetime.now(timezone.utc).date().isoformat()
    fixture = tmp_path / "recent.json"
    fixture.write_text(json.dumps([
        {
            "date": today,
            "account_id": account.external_account_id,
            "campaign_id": "C1", "campaign_name": "Test Camp",
            "adset_id": "AS1", "adset_name": "Test AdSet",
            "ad_id": "AD1", "ad_name": "Test Ad",
            "impressions": 1000, "clicks": 50, "spend": "100.00",
            "conversions": "5", "conversion_value": "500.00", "currency": "TRY",
        }
    ]), encoding="utf-8")

    # Vault returns the fixture_path secret → injected into connector extra.
    vault = InMemoryVault()
    vault.put(str(account.id), {"fixture_path": str(fixture)})
    _test_app.dependency_overrides[connectors_module._get_vault] = lambda: vault

    resp = client.post(f"/api/v1/connectors/accounts/{account.id}/sync")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["records_processed"] > 0
    assert body["inserted"] > 0

    count = db.scalar(
        select(func.count()).select_from(FactDailyMetrics).where(
            FactDailyMetrics.tenant_id == tenant.id
        )
    )
    assert count > 0

    db.refresh(account)
    assert account.sync_status == SyncStatus.success


def test_sync_unknown_account_404(ctx) -> None:
    client, _db, _tenant, _account = ctx
    resp = client.post(f"/api/v1/connectors/accounts/{uuid.uuid4()}/sync")
    assert resp.status_code == 404


def test_sync_respects_days_window(ctx) -> None:
    client, _db, _tenant, account = ctx
    resp = client.post(
        f"/api/v1/connectors/accounts/{account.id}/sync", params={"days": 7}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_patch_sets_external_account_id(ctx) -> None:
    client, db, _tenant, account = ctx
    resp = client.patch(
        f"/api/v1/connectors/accounts/{account.id}",
        json={"external_account_id": "123456", "display_name": "Benim Hesabım"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["external_account_id"] == "123456"
    assert body["display_name"] == "Benim Hesabım"


def test_patch_strips_act_prefix_for_meta(ctx) -> None:
    client, db, tenant, _account = ctx
    meta = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.meta_ads,
        external_account_id="", display_name="Meta",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db.add(meta)
    db.commit()
    resp = client.patch(
        f"/api/v1/connectors/accounts/{meta.id}",
        json={"external_account_id": "act_987654"},
    )
    assert resp.status_code == 200
    assert resp.json()["external_account_id"] == "987654"


def test_discover_without_creds_400(ctx) -> None:
    # ctx's default vault is empty → get() returns None → 400.
    client, _db, _tenant, account = ctx
    resp = client.post(f"/api/v1/connectors/accounts/{account.id}/discover")
    assert resp.status_code == 400


def _make_google_ads_tenant_account(
    db_session, external_account_id: str = ""
) -> tuple[Tenant, ConnectedAccount]:
    """Create+commit a bare tenant and a google_ads ConnectedAccount for it."""
    tenant = Tenant(
        id=uuid.uuid4(), name="GAds Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    account = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.google_ads,
        external_account_id=external_account_id,
        display_name="Google Ads (connecting…)",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add(tenant)
    db_session.add(account)
    db_session.commit()
    return tenant, account


def _fake_capabilities(self):
    from ayaz.connectors.base import ConnectorCapabilities
    return ConnectorCapabilities(platform_key="google_ads", supported_streams=[])


def test_sync_injects_global_google_ads_creds_and_resolves_customer_id(
    db_session, monkeypatch
) -> None:
    """``sync_connected_account`` must inject the operator-level Google Ads
    credentials (client_id/client_secret/developer_token) from Settings on top
    of the tenant's vault-stored refresh_token — without ever overwriting the
    vault value — and, when the account has no external_account_id yet, must
    auto-resolve it via the ``list_accessible_customers`` + ``list_child_customers``
    resolver. A standalone (non-MCC) accessible customer's ``list_child_customers``
    call returns a single self-row (same id) — the resolver must treat that as
    "standalone", not descend further, and set no login_customer_id.
    """
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)

    vault = InMemoryVault()
    # Only the tenant-specific secret is in the vault — the other 3 Google Ads
    # credentials are operator-global and must come from Settings.
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    captured: dict[str, object] = {}

    def fake_authenticate(self) -> None:
        captured["connector"] = self
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["9998887777"]

    def fake_list_child_customers(self, manager_id):
        captured.setdefault("list_child_customers_calls", []).append(manager_id)
        # Standalone account: customer_client resolves to a single self-row.
        return [{"id": manager_id, "name": "Standalone Acct", "currency": "TRY"}]

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "capabilities", _fake_capabilities)

    result = sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    assert result["records_processed"] == 0

    connector = captured["connector"]
    assert connector.config.extra["client_id"] == "GLOBAL_CID"
    assert connector.config.extra["client_secret"] == "GLOBAL_SECRET"
    assert connector.config.extra["developer_token"] == "GLOBAL_DEV_TOKEN"
    # Vault-provided refresh_token must never be overwritten by the operator defaults.
    assert connector.config.extra["refresh_token"] == "user_refresh_token"
    # Auto-resolved from the standalone target and persisted on the account.
    assert connector.config.extra["customer_id"] == "9998887777"
    assert "login_customer_id" not in connector.config.extra
    assert account.external_account_id == "9998887777"
    assert account.sync_status == SyncStatus.success


def test_sync_resolves_mcc_leaf_and_sets_login_customer_id(
    db_session, monkeypatch
) -> None:
    """When the single accessible customer is a manager (MCC) — i.e.
    ``list_child_customers`` returns a child with a *different* id — the
    resolver must descend to that leaf: ``external_account_id`` becomes the
    leaf id, and ``login_customer_id`` becomes the MCC id (so fetch() sends
    the right header via a future ``_auth_headers()`` call)."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    captured: dict[str, object] = {}

    def fake_authenticate(self) -> None:
        captured["connector"] = self
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["1112223333"]  # the MCC

    def fake_list_child_customers(self, manager_id):
        assert manager_id == "1112223333"
        return [{"id": "4445556666", "name": "Leaf Acct", "currency": "TRY"}]

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "capabilities", _fake_capabilities)

    sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    connector = captured["connector"]
    assert account.external_account_id == "4445556666"
    assert connector.config.extra["customer_id"] == "4445556666"
    assert connector.config.extra["login_customer_id"] == "1112223333"
    assert account.sync_status == SyncStatus.success


def test_sync_ambiguous_multiple_targets_leaves_external_account_id_blank(
    db_session, monkeypatch
) -> None:
    """Two directly-accessible standalone customers → resolver returns 2
    targets → ambiguous, so external_account_id must stay unset (the user
    picks via the discover UI) rather than being guessed."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def fake_authenticate(self) -> None:
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["1112223333", "7778889999"]

    def fake_list_child_customers(self, manager_id):
        # Both standalone — self-row only, no non-self children.
        return [{"id": manager_id, "name": f"Acct {manager_id}", "currency": "TRY"}]

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "capabilities", _fake_capabilities)

    result = sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    assert account.external_account_id == ""
    assert account.sync_status == SyncStatus.idle
    assert result["skipped"] == "no_account_selected"
    assert result["records_processed"] == 0


def test_sync_ambiguous_targets_short_circuits_before_fetch(
    db_session, monkeypatch
) -> None:
    """Regression (found via E2E): with the REAL ``capabilities()`` (a non-empty
    ``supported_streams``) so the fetch loop is genuinely reachable, an ambiguous
    resolution (>1 leaf, none picked) must short-circuit and return BEFORE calling
    ``fetch()``. Otherwise ``_customer_id()`` falls back to "" and the connector
    POSTs to a malformed ``customers//googleAds:searchStream`` URL (400), wrongly
    marking the account ``error`` on every scheduled sync. The unit suite missed
    this because every other google_ads test stubs ``capabilities()`` to empty."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def fake_authenticate(self) -> None:
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["1112223333", "7778889999"]

    def fake_list_child_customers(self, manager_id):
        return [{"id": manager_id, "name": f"Acct {manager_id}", "currency": "TRY"}]

    def fake_fetch(self, *args, **kwargs):  # must never run in this scenario
        raise AssertionError(
            "fetch() must not be called when no customer_id is resolved"
        )

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "fetch", fake_fetch)
    # NOTE: capabilities() is intentionally NOT stubbed — the real one reports
    # supported_streams=["daily_campaign_metrics"], so a missing short-circuit
    # would reach the guarded fake_fetch above and fail this test loudly.

    result = sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    assert account.external_account_id == ""
    assert account.sync_status == SyncStatus.idle
    assert result["skipped"] == "no_account_selected"
    assert result["records_processed"] == 0


def test_sync_no_accessible_customers_leaves_blank_no_crash(
    db_session, monkeypatch
) -> None:
    """Empty ``list_accessible_customers()`` → resolver returns [] → no target
    resolved → sync short-circuits to ``idle`` (awaiting account selection) with
    external_account_id left blank; no crash, no fetch, no error."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def fake_authenticate(self) -> None:
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return []

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "capabilities", _fake_capabilities)

    result = sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    assert account.external_account_id == ""
    assert account.sync_status == SyncStatus.idle
    assert result["skipped"] == "no_account_selected"
    assert result["records_processed"] == 0


def test_sync_list_child_customers_raises_is_skipped_sync_continues(
    db_session, monkeypatch
) -> None:
    """``list_child_customers`` raising for one accessible id must be logged
    and skipped by the resolver — never propagated. With no target resolved,
    the sync short-circuits to ``idle`` (awaiting account selection)."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def fake_authenticate(self) -> None:
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["1112223333"]

    def fake_list_child_customers(self, manager_id):
        raise RuntimeError("boom — Google Ads API unavailable")

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )
    monkeypatch.setattr(GoogleAdsConnector, "capabilities", _fake_capabilities)

    result = sync_module.sync_connected_account(
        db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
    )

    assert account.external_account_id == ""
    assert account.sync_status == SyncStatus.idle
    assert result["skipped"] == "no_account_selected"
    assert result["records_processed"] == 0


def test_sync_missing_developer_token_authenticate_raises_sets_error_status(
    db_session, monkeypatch
) -> None:
    """A real (non-monkeypatched) ``authenticate()`` call with an empty
    developer_token must raise RuntimeError — and that failure must now be
    caught inside the main try/except, leaving ``sync_status == error`` (never
    stuck on ``syncing``/``idle``) so the account isn't retried forever as if
    nothing happened."""
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(sync_module.settings, "google_ads_developer_token", "")

    tenant, account = _make_google_ads_tenant_account(db_session)
    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    with pytest.raises(RuntimeError):
        sync_module.sync_connected_account(
            db_session, account, since=date(2026, 7, 1), until=date(2026, 7, 10), vault=vault
        )

    assert account.sync_status == SyncStatus.error


def test_sync_endpoint_maps_missing_developer_token_to_502(
    db_session, monkeypatch
) -> None:
    """The manual /sync endpoint must translate the authenticate() RuntimeError
    (empty developer_token) into HTTP 502 — not 500, not a silent 200 — and the
    account must be left with sync_status == error, matching the contract
    documented on ``sync_account``."""
    from ayaz.services import sync as sync_module

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(sync_module.settings, "google_ads_developer_token", "")

    tenant = Tenant(
        id=uuid.uuid4(), name="502 GAds Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(), email="gads502@ayaz.app",
        hashed_password=hash_password("test1234"), full_name="GAds 502",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()
    membership = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    account = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.google_ads,
        external_account_id="1112223333", display_name="Google Ads",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add(membership)
    db_session.add(account)
    db_session.commit()

    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    _test_app.dependency_overrides[connectors_module._get_vault] = lambda: vault

    try:
        with TestClient(_test_app) as c:
            resp = c.post(f"/api/v1/connectors/accounts/{account.id}/sync")
    finally:
        _test_app.dependency_overrides.clear()

    assert resp.status_code == 502, resp.text
    db_session.refresh(account)
    assert account.sync_status == SyncStatus.error


def test_discover_accounts_google_ads_injects_creds_and_resolves_leaves(
    db_session, monkeypatch
) -> None:
    """``POST /discover`` for google_ads must (a) inject operator creds so
    ``authenticate()`` doesn't 502 on a missing developer_token, and (b) route
    through ``resolve_google_ads_targets`` so the picker shows real syncable
    leaf accounts (MCC children), not the raw accessible-customers list."""
    from ayaz.connectors.google_ads import GoogleAdsConnector
    from ayaz.services import sync as sync_module
    from ayaz.services.vault import InMemoryVault

    monkeypatch.setattr(sync_module.settings, "google_client_id", "GLOBAL_CID")
    monkeypatch.setattr(sync_module.settings, "google_client_secret", "GLOBAL_SECRET")
    monkeypatch.setattr(
        sync_module.settings, "google_ads_developer_token", "GLOBAL_DEV_TOKEN"
    )

    tenant = Tenant(
        id=uuid.uuid4(), name="Discover GAds Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(), email="discovergads@ayaz.app",
        hashed_password=hash_password("test1234"), full_name="Discover GAds",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()
    membership = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    account = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.google_ads,
        external_account_id="", display_name="Google Ads (connecting…)",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add(membership)
    db_session.add(account)
    db_session.commit()

    def fake_authenticate(self) -> None:
        self._access_token = "fake-access-token"

    def fake_list_accessible_customers(self):
        return ["1112223333"]

    def fake_list_child_customers(self, manager_id):
        assert manager_id == "1112223333"
        return [{"id": "4445556666", "name": "Leaf Acct", "currency": "TRY"}]

    monkeypatch.setattr(GoogleAdsConnector, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        GoogleAdsConnector, "list_accessible_customers", fake_list_accessible_customers
    )
    monkeypatch.setattr(
        GoogleAdsConnector, "list_child_customers", fake_list_child_customers
    )

    vault = InMemoryVault()
    vault.put(str(account.id), {"refresh_token": "user_refresh_token"})

    def override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    _test_app.dependency_overrides[connectors_module._get_vault] = lambda: vault

    try:
        with TestClient(_test_app) as c:
            resp = c.post(f"/api/v1/connectors/accounts/{account.id}/discover")
    finally:
        _test_app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"id": "4445556666", "name": "Leaf Acct", "currency": "TRY"}
    ]


def test_sync_endpoint_tenant_isolation_returns_404(ctx) -> None:
    """A tenant must not be able to trigger a sync on another tenant's
    connected account — the endpoint's explicit tenant_id filter must 404,
    never leak or sync cross-tenant data."""
    client, db, _tenant_a, _account_a = ctx

    tenant_b = Tenant(
        id=uuid.uuid4(), name="Other Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    account_b = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant_b.id, platform=Platform.sample,
        external_account_id="ACC-OTHER-1", display_name="Other Sample",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db.add(tenant_b)
    db.add(account_b)
    db.commit()

    resp = client.post(f"/api/v1/connectors/accounts/{account_b.id}/sync")
    assert resp.status_code == 404


def test_discover_lists_accounts(ctx) -> None:
    client, _db, _tenant, account = ctx
    vault = InMemoryVault()
    vault.put(str(account.id), {"access_token": "T"})
    _test_app.dependency_overrides[connectors_module._get_vault] = lambda: vault

    resp = client.post(f"/api/v1/connectors/accounts/{account.id}/discover")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Sample connector.discover() returns one fake account.
    assert isinstance(body, list)
    assert len(body) >= 1
    assert "id" in body[0]
