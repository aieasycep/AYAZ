"""Demo seed script — populates fact_daily_metrics with fixture data.

Usage
-----
From the ``backend/`` directory:

    python -m scripts.seed_demo          # as a module
    python scripts/seed_demo.py          # as a script

The script is fully idempotent: running it multiple times will not duplicate
data.  It creates:

1. A demo Tenant (name "AYAZ Demo", base_currency "TRY").
2. A demo User (email ``demo@ayaz.app``, password ``demo12345``).
3. An owner Membership linking the user to the tenant.
4. Two ConnectedAccounts: platforms ``sample`` (ACC-001) and
   ``google_ads`` (1234567890).
5. Calls ``sync_connected_account`` for both accounts, which reads from the
   fixture JSON files — no live network calls are made.

Connector fixtures
------------------
``sample``    — ``tests/fixtures/sample_metrics.json`` (3 rows, 2024-03)
``google_ads`` — ``tests/fixtures/google_ads_search_stream.json`` (3 rows, 2024-06)

The GoogleAdsConnector is used in *fixture mode*: we directly call
``normalize()`` on the pre-recorded fixture rather than calling ``fetch()``
(which would hit the real API).  We do this by subclassing GoogleAdsConnector
and overriding ``fetch()`` to load the local fixture instead.

Exit codes
----------
0 — success
1 — DB unreachable (prints the error and instructions)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# Ensure the backend package root is on sys.path when run as a plain script.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ayaz.connectors.base import ConnectorConfig
from ayaz.connectors.google_ads import GoogleAdsConnector
from ayaz.connectors.sample import SampleConnector
from ayaz.database import SessionLocal, engine
from ayaz.models.analytics import DimChannel  # noqa: F401 — ensure table known
from ayaz.models.base import Base
from ayaz.models.oltp import (
    ConnectedAccount,
    Membership,
    MembershipRole,
    Platform,
    SyncStatus,
    Tenant,
    User,
)
from ayaz.services.auth import hash_password
from ayaz.services.sync import sync_connected_account


# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_EMAIL = "demo@ayaz.app"
DEMO_PASSWORD = "demo12345"
DEMO_TENANT_NAME = "AYAZ Demo"
DEMO_CURRENCY = "TRY"

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
_SAMPLE_FIXTURE = _FIXTURES_DIR / "sample_metrics.json"
_GOOGLE_ADS_FIXTURE = _FIXTURES_DIR / "google_ads_search_stream.json"

# Date range wide enough to capture all fixture rows
_SYNC_SINCE = date(2024, 1, 1)
_SYNC_UNTIL = date(2024, 12, 31)


# ── Fixture-backed GoogleAds connector ────────────────────────────────────────


class _FixtureGoogleAdsConnector(GoogleAdsConnector):
    """GoogleAdsConnector with fetch() replaced by fixture loading.

    Used by the seed script only — never registers itself in the ConnectorRegistry
    because ``platform_key`` is cleared at the class level so ``__init_subclass__``
    skips registration (only subclasses that define platform_key as a non-empty
    string are registered).
    No live network calls are made.
    """

    # Clear platform_key so __init_subclass__ skips registration
    platform_key = ""  # type: ignore[assignment]

    def __init__(self, config: ConnectorConfig, fixture_path: Path) -> None:
        super().__init__(config)
        self._fixture_path = fixture_path
        # Provide a dummy access token so _auth_headers() won't raise
        self._access_token = "fixture-mode-no-token"

    def fetch(self, stream: str, since: date, until: date):  # type: ignore[override]
        """Load the recorded fixture and return the flattened row list."""
        with self._fixture_path.open(encoding="utf-8") as fh:
            raw_body = json.load(fh)
        rows = self._parse_stream_response(raw_body)
        # Filter by date range
        filtered = [
            r for r in rows
            if since <= date.fromisoformat(r["segments"]["date"]) <= until
        ]
        return filtered

    def authenticate(self) -> None:  # type: ignore[override]
        """No-op in fixture mode."""

    def refresh_token(self) -> None:  # type: ignore[override]
        """No-op in fixture mode."""


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _get_or_create_tenant(db) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.name == DEMO_TENANT_NAME))
    if tenant is None:
        tenant = Tenant(
            name=DEMO_TENANT_NAME,
            base_currency=DEMO_CURRENCY,
            country="TR",
            kvkk_region="TR",
        )
        db.add(tenant)
        db.flush()
        print(f"  Created tenant: {DEMO_TENANT_NAME} ({tenant.id})")
    else:
        print(f"  Tenant already exists: {DEMO_TENANT_NAME} ({tenant.id})")
    return tenant


def _get_or_create_user(db) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name="AYAZ Demo User",
        )
        db.add(user)
        db.flush()
        print(f"  Created user: {DEMO_EMAIL} ({user.id})")
    else:
        print(f"  User already exists: {DEMO_EMAIL} ({user.id})")
    return user


def _get_or_create_membership(db, user: User, tenant: Tenant) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant.id,
        )
    )
    if membership is None:
        membership = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=MembershipRole.owner,
        )
        db.add(membership)
        db.flush()
        print("  Created owner membership")
    else:
        print("  Membership already exists")
    return membership


def _get_or_create_connected_account(
    db,
    tenant: Tenant,
    platform: Platform,
    external_id: str,
    display_name: str,
) -> ConnectedAccount:
    account = db.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.tenant_id == tenant.id,
            ConnectedAccount.platform == platform,
            ConnectedAccount.external_account_id == external_id,
        )
    )
    if account is None:
        account = ConnectedAccount(
            tenant_id=tenant.id,
            platform=platform,
            external_account_id=external_id,
            display_name=display_name,
            vault_secret_ref="",
            sync_status=SyncStatus.idle,
        )
        db.add(account)
        db.flush()
        print(f"  Created ConnectedAccount: {platform.value} / {external_id}")
    else:
        print(f"  ConnectedAccount already exists: {platform.value} / {external_id}")
    return account


# ── Main ──────────────────────────────────────────────────────────────────────


def run_seed() -> None:
    print("=" * 60)
    print("AYAZ Demo Seed Script")
    print("=" * 60)

    # Test DB connectivity
    try:
        with engine.connect() as conn:
            conn.execute(select(1))  # type: ignore[arg-type]
    except OperationalError as exc:
        print(f"\nERROR: Cannot connect to database.\n  {exc}")
        print(
            "\nTo run the seed you need a Postgres instance with the schema applied:\n"
            "  cd backend && alembic upgrade head\n"
            "  python -m scripts.seed_demo\n"
        )
        sys.exit(1)

    db = SessionLocal()
    total_inserted = 0
    total_updated = 0

    try:
        print("\n[1/4] Creating demo tenant, user, and membership…")
        tenant = _get_or_create_tenant(db)
        user = _get_or_create_user(db)
        _get_or_create_membership(db, user, tenant)
        db.commit()

        print("\n[2/4] Creating connected accounts…")
        sample_account = _get_or_create_connected_account(
            db, tenant,
            platform=Platform.sample,
            external_id="ACC-001",
            display_name="Sample Ad Account (fixture)",
        )
        gads_account = _get_or_create_connected_account(
            db, tenant,
            platform=Platform.google_ads,
            external_id="1234567890",
            display_name="Google Ads Account (fixture)",
        )
        db.commit()

        print("\n[3/4] Syncing 'sample' connector (fixture mode)…")
        # SampleConnector reads from fixture natively via ConnectorRegistry.
        sample_result = sync_connected_account(
            db,
            account=sample_account,
            since=_SYNC_SINCE,
            until=_SYNC_UNTIL,
        )
        total_inserted += sample_result["inserted"]
        total_updated += sample_result["updated"]
        print(
            f"  sample: inserted={sample_result['inserted']} "
            f"updated={sample_result['updated']} "
            f"records={sample_result['records_processed']}"
        )

        print("\n[4/4] Syncing 'google_ads' connector (fixture mode)…")
        # Use the fixture-backed subclass; instantiate it directly (bypasses registry).
        gads_config = ConnectorConfig(
            tenant_id=str(tenant.id),
            connected_account_id=str(gads_account.id),
            external_account_id=gads_account.external_account_id,
            platform_key="google_ads",
            vault_secret_ref="",
            extra={"customer_id": "1234567890", "currency": "USD"},
        )
        fixture_connector = _FixtureGoogleAdsConnector(
            config=gads_config,
            fixture_path=_GOOGLE_ADS_FIXTURE,
        )

        # Run sync manually (mirrors sync_connected_account logic but uses our
        # fixture connector instance directly instead of the registry).
        from ayaz.services.sync import (
            _ensure_dim_date,
            _get_or_create_channel,
            _get_or_create_campaign,
            _get_or_create_adset,
            _get_or_create_ad,
            _upsert_fact,
        )
        from datetime import datetime, timezone

        gads_account.sync_status = SyncStatus.syncing
        db.flush()

        caps = fixture_connector.capabilities()
        all_records = []
        for stream in caps.supported_streams:
            raw = fixture_connector.fetch(
                stream=stream, since=_SYNC_SINCE, until=_SYNC_UNTIL
            )
            all_records.extend(fixture_connector.normalize(raw))

        channel = _get_or_create_channel(db, "google_ads")
        g_inserted = 0
        g_updated = 0
        for rec in all_records:
            _ensure_dim_date(db, rec.date_key)
            campaign = _get_or_create_campaign(
                db, tenant.id, channel, rec.campaign_id, rec.campaign_name
            )
            adset = _get_or_create_adset(
                db, tenant.id, campaign, rec.adset_id, rec.adset_name
            )
            ad = _get_or_create_ad(
                db, tenant.id, adset, rec.ad_id, rec.ad_name
            )
            _, created = _upsert_fact(
                db,
                tenant_id=tenant.id,
                connected_account_id=gads_account.id,
                channel=channel,
                campaign=campaign,
                adset=adset,
                ad=ad,
                record=rec,
            )
            if created:
                g_inserted += 1
            else:
                g_updated += 1

        if all_records:
            latest = max(r.date_key for r in all_records)
            gads_account.watermark = latest.isoformat()
        gads_account.sync_status = SyncStatus.success
        db.commit()

        total_inserted += g_inserted
        total_updated += g_updated
        print(
            f"  google_ads: inserted={g_inserted} updated={g_updated} "
            f"records={len(all_records)}"
        )

    finally:
        db.close()

    print("\n" + "=" * 60)
    print("Seed complete.")
    print(f"  Fact rows inserted : {total_inserted}")
    print(f"  Fact rows updated  : {total_updated}")
    print()
    print("Demo login credentials:")
    print(f"  Email    : {DEMO_EMAIL}")
    print(f"  Password : {DEMO_PASSWORD}")
    print()
    print("To obtain a JWT:")
    print(
        f'  curl -s -X POST http://localhost:8000/api/v1/auth/login \\\n'
        f'    -H "Content-Type: application/json" \\\n'
        f'    -d \'{{"email":"{DEMO_EMAIL}","password":"{DEMO_PASSWORD}"}}\''
    )
    print("=" * 60)


if __name__ == "__main__":
    run_seed()
