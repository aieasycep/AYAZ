"""Tests for Ürün/SKU Segment analizi (Dalga 3).

Coverage
--------
1. build_product_segments — service level (with DB)
   - empty tenant → empty products/categories, zero totals
   - seeded products → correct gross/net ROAS, return rate, net revenue
   - category rollup sums products
   - products sorted by ad_spend desc
   - tenant isolation (other tenant's products excluded)

2. HTTP endpoint
   - 200 happy path + response shape
   - default date range (last 30 days)
   - date_from > date_to → 422
   - missing auth → 401 or 403
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register models so Base.metadata.create_all builds every table.
import ayaz.models.oltp  # noqa: F401
import ayaz.models.analytics  # noqa: F401

from ayaz.database import get_db
from ayaz.models.analytics import DimChannel, DimDate, DimProduct, FactProductDaily
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import segments as segments_module
from ayaz.services.auth import hash_password
from ayaz.services.product_segments import build_product_segments

_test_app = FastAPI(title="AYAZ Segments Test App")
_test_app.include_router(segments_module.router, prefix="/api/v1")


# ── Fixtures ───────────────────────────────────────────────────────────────────


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
def client(db_session: Session):
    tenant = Tenant(
        id=uuid.uuid4(), name="Segments Tenant",
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    user = User(
        id=uuid.uuid4(), email="seg_test@ayaz.app",
        hashed_password=hash_password("test1234"), full_name="Seg Test",
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.flush()
    membership = Membership(
        id=uuid.uuid4(), user_id=user.id, tenant_id=tenant.id,
        role=MembershipRole.owner,
    )
    db_session.add(membership)
    db_session.commit()

    def override_db():
        yield db_session

    def override_membership():
        return membership

    _test_app.dependency_overrides[get_db] = override_db
    _test_app.dependency_overrides[get_current_membership] = override_membership
    with TestClient(_test_app) as c:
        yield c
    _test_app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(db_session: Session):
    def override_db():
        yield db_session

    _test_app.dependency_overrides[get_db] = override_db
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c
    _test_app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────


def _make_tenant(db: Session, name: str = "T") -> Tenant:
    t = Tenant(
        id=uuid.uuid4(), name=name,
        base_currency="TRY", country="TR", kvkk_region="TR",
    )
    db.add(t)
    db.flush()
    return t


def _make_channel(db: Session, key: str) -> DimChannel:
    ch = DimChannel(id=uuid.uuid4(), key=key, label=key.title())
    db.add(ch)
    db.flush()
    return ch


def _make_product(db: Session, tenant: Tenant, sku: str, category: str, price: str) -> DimProduct:
    p = DimProduct(
        id=uuid.uuid4(), tenant_id=tenant.id, external_id=sku, sku=sku,
        name=f"Ürün {sku}", category=category, price_raw=Decimal(price), price_ccy="TRY",
    )
    db.add(p)
    db.flush()
    return p


def _ensure_date(db: Session, d: date) -> None:
    if db.get(DimDate, d):
        return
    iso = d.isocalendar()
    db.add(DimDate(
        date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
        month=d.month, week=iso.week, day_of_week=d.weekday(),
        is_weekend=d.weekday() >= 5,
    ))
    db.flush()


def _insert_fact(
    db: Session, tenant: Tenant, product: DimProduct, channel: DimChannel, d: date,
    *, units: int, gross: str, ret_units: int, returned: str, spend: str,
) -> None:
    _ensure_date(db, d)
    db.add(FactProductDaily(
        id=uuid.uuid4(), tenant_id=tenant.id, product_id=product.id,
        channel_id=channel.id, date_key=d,
        units_sold=units, gross_revenue=Decimal(gross),
        returned_units=ret_units, returned_revenue=Decimal(returned),
        ad_spend=Decimal(spend), ccy="TRY",
    ))
    db.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Service-level tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildProductSegments:
    _from = date(2026, 1, 1)
    _to = date(2026, 1, 30)

    def test_empty_tenant(self, db_session: Session) -> None:
        t = _make_tenant(db_session, "Empty")
        res = build_product_segments(db_session, t.id, self._from, self._to)
        assert res["products"] == []
        assert res["categories"] == []
        assert res["totals"]["product_count"] == 0
        assert res["totals"]["gross_roas"] == 0.0
        assert res["totals"]["net_roas"] == 0.0

    def test_gross_and_net_roas(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        ch = _make_channel(db_session, "meta_ads_seg")
        p = _make_product(db_session, t, "SKU-1", "Elbise", "100")
        # gross=1000, returned=300, spend=250 → gross_roas 4.0, net_roas 2.8
        _insert_fact(db_session, t, p, ch, self._from,
                     units=10, gross="1000", ret_units=3, returned="300", spend="250")
        db_session.commit()
        res = build_product_segments(db_session, t.id, self._from, self._to)
        prod = res["products"][0]
        assert prod["gross_roas"] == 4.0
        assert prod["net_roas"] == 2.8
        assert prod["net_revenue"] == 700.0
        assert prod["return_rate_pct"] == 30.0

    def test_category_rollup(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        ch = _make_channel(db_session, "google_ads_seg")
        p1 = _make_product(db_session, t, "A", "Elbise", "100")
        p2 = _make_product(db_session, t, "B", "Elbise", "200")
        _insert_fact(db_session, t, p1, ch, self._from,
                     units=5, gross="500", ret_units=0, returned="0", spend="100")
        _insert_fact(db_session, t, p2, ch, self._from,
                     units=5, gross="1000", ret_units=1, returned="200", spend="200")
        db_session.commit()
        res = build_product_segments(db_session, t.id, self._from, self._to)
        assert len(res["categories"]) == 1
        cat = res["categories"][0]
        assert cat["category"] == "Elbise"
        assert cat["product_count"] == 2
        assert cat["gross_revenue"] == 1500.0
        assert cat["net_revenue"] == 1300.0  # (500-0)+(1000-200)
        assert cat["ad_spend"] == 300.0

    def test_products_sorted_by_spend_desc(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        ch = _make_channel(db_session, "tiktok_seg")
        low = _make_product(db_session, t, "LOW", "X", "10")
        high = _make_product(db_session, t, "HIGH", "Y", "10")
        _insert_fact(db_session, t, low, ch, self._from,
                     units=1, gross="100", ret_units=0, returned="0", spend="50")
        _insert_fact(db_session, t, high, ch, self._from,
                     units=1, gross="100", ret_units=0, returned="0", spend="500")
        db_session.commit()
        res = build_product_segments(db_session, t.id, self._from, self._to)
        assert res["products"][0]["sku"] == "HIGH"
        assert res["products"][1]["sku"] == "LOW"

    def test_tenant_isolation(self, db_session: Session) -> None:
        t1 = _make_tenant(db_session, "T1")
        t2 = _make_tenant(db_session, "T2")
        ch = _make_channel(db_session, "iso_seg")
        p2 = _make_product(db_session, t2, "OTHER", "Z", "100")
        _insert_fact(db_session, t2, p2, ch, self._from,
                     units=5, gross="500", ret_units=0, returned="0", spend="100")
        db_session.commit()
        res = build_product_segments(db_session, t1.id, self._from, self._to)
        assert res["products"] == []

    def test_zero_spend_roas_guarded(self, db_session: Session) -> None:
        t = _make_tenant(db_session)
        ch = _make_channel(db_session, "zero_seg")
        p = _make_product(db_session, t, "ZERO", "X", "100")
        _insert_fact(db_session, t, p, ch, self._from,
                     units=5, gross="500", ret_units=0, returned="0", spend="0")
        db_session.commit()
        res = build_product_segments(db_session, t.id, self._from, self._to)
        assert res["products"][0]["gross_roas"] == 0.0
        assert res["products"][0]["net_roas"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. HTTP endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSegmentsEndpoint:
    def test_happy_path_200_shape(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/segments/products",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"period", "currency", "totals", "categories", "products"}
        assert set(body["totals"].keys()) >= {
            "gross_roas", "net_roas", "return_rate_pct", "product_count",
        }

    def test_default_date_range(self, client: TestClient) -> None:
        today = datetime.now(timezone.utc).date()
        resp = client.get("/api/v1/segments/products")
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"]["date_to"] == today.isoformat()
        assert body["period"]["date_from"] == (today - timedelta(days=29)).isoformat()

    def test_date_from_after_date_to_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/segments/products",
            params={"date_from": "2026-01-30", "date_to": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_unauthenticated(self, unauth_client: TestClient) -> None:
        resp = unauth_client.get(
            "/api/v1/segments/products",
            params={"date_from": "2026-01-01", "date_to": "2026-01-30"},
        )
        assert resp.status_code in (401, 403)
