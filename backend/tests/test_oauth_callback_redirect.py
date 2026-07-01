"""OAuth callback → redirect the browser back to the panel (customer flow).

When FRONTEND_BASE_URL is set the callback should 302 to the Integration
Center; when it is not, it keeps returning the JSON confirmation (dev / API).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401

from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import ConnectedAccount, Platform, SyncStatus, Tenant
from ayaz.api.v1 import oauth as oauth_module
from ayaz.services.oauth_broker import _sign_state
from ayaz.services.vault import InMemoryVault

_app = FastAPI()
_app.include_router(oauth_module.router, prefix="/api/v1")


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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
def client_and_state(db_session: Session):
    tenant = Tenant(
        id=uuid.uuid4(), name="OAuth T", base_currency="TRY", country="TR", kvkk_region="TR",
    )
    account = ConnectedAccount(
        id=uuid.uuid4(), tenant_id=tenant.id, platform=Platform.meta_ads,
        external_account_id="", display_name="meta (connecting…)",
        vault_secret_ref="", sync_status=SyncStatus.idle,
    )
    db_session.add(tenant)
    db_session.add(account)
    db_session.commit()

    state = _sign_state(str(account.id), str(tenant.id))

    def override_db():
        yield db_session

    _app.dependency_overrides[get_db] = override_db
    _app.dependency_overrides[oauth_module._get_vault] = lambda: InMemoryVault()
    with TestClient(_app) as c:
        yield c, state
    _app.dependency_overrides.clear()


_FAKE_TOKENS = {"access_token": "T", "refresh_token": "R", "expires_in": 3600}


def test_callback_redirects_to_panel_when_frontend_set(client_and_state) -> None:
    client, state = client_and_state
    with patch("ayaz.api.v1.oauth.oauth_broker.exchange_code", return_value=_FAKE_TOKENS), \
         patch.object(oauth_module.settings, "frontend_base_url", "https://panel.test"):
        resp = client.get(
            "/api/v1/oauth/meta_ads/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert "/integrations" in loc
    assert "connected=meta_ads" in loc


def test_callback_returns_json_when_no_frontend(client_and_state) -> None:
    client, state = client_and_state
    with patch("ayaz.api.v1.oauth.oauth_broker.exchange_code", return_value=_FAKE_TOKENS), \
         patch.object(oauth_module.settings, "frontend_base_url", ""):
        resp = client.get(
            "/api/v1/oauth/meta_ads/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"


def test_callback_error_redirects_when_frontend_set(client_and_state) -> None:
    client, state = client_and_state
    with patch("ayaz.api.v1.oauth.oauth_broker.exchange_code", side_effect=RuntimeError("boom")), \
         patch.object(oauth_module.settings, "frontend_base_url", "https://panel.test"):
        resp = client.get(
            "/api/v1/oauth/meta_ads/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=meta_ads" in resp.headers["location"]
