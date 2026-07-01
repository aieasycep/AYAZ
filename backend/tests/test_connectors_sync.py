"""Manual sync endpoint — POST /connectors/accounts/{id}/sync.

Uses the credential-free ``sample`` connector so the whole trigger→fetch→upsert
path runs end-to-end and actually writes fact rows, without real OAuth.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

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
