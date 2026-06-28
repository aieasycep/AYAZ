"""Tests for M7 Event Match Quality scoring (Dalga 55).

Coverage
--------
1. compute_match_quality — pure unit tests
   - empty / None → score 0, tier "weak", no present keys
   - single signal weights, alias resolution, blank-value rejection
   - tier boundaries (weak / medium / good / excellent)
   - full payload → score 100, tier "excellent"
   - present keys ordered by descending weight
2. compute_match_quality_stats — aggregation
   - None when no event carries a score
   - avg_score, scored_events, tier_distribution, field_coverage
3. hash_identity — external_id hashing + fbc/fbp passthrough
4. ingest_event stores match_quality on the persisted event
5. GET /sources/{id}/stats exposes the match_quality block
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Register all models so Base.metadata.create_all works
import ayaz.models.oltp  # noqa: F401
import ayaz.models.tracking  # noqa: F401

from ayaz.api.deps import get_current_membership
from ayaz.api.v1 import tracking as tracking_module
from ayaz.database import get_db
from ayaz.models.base import Base
from ayaz.models.oltp import Membership, MembershipRole, Tenant, User
from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.services.auth import hash_password
from ayaz.services.tracking import (
    MATCH_QUALITY_WEIGHTS,
    compute_match_quality,
    compute_match_quality_stats,
    hash_identity,
    ingest_event,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compute_match_quality — pure unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeMatchQuality:
    def test_empty_and_none(self) -> None:
        for raw in ({}, None):
            mq = compute_match_quality(raw)
            assert mq["score"] == 0
            assert mq["tier"] == "weak"
            assert mq["present"] == []

    def test_weights_sum_to_100(self) -> None:
        assert sum(MATCH_QUALITY_WEIGHTS.values()) == 100

    def test_full_payload_scores_100_excellent(self) -> None:
        raw = {
            "email": "a@b.com",
            "phone": "5551112233",
            "fbc": "fb.1.123.abc",
            "fbp": "fb.1.123.def",
            "external_id": "cust-1",
            "client_ip_address": "1.2.3.4",
            "client_user_agent": "Mozilla/5.0",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "zip": "34000",
            "city": "Istanbul",
            "state": "IST",
            "country": "TR",
            "gender": "f",
        }
        mq = compute_match_quality(raw)
        assert mq["score"] == 100
        assert mq["tier"] == "excellent"

    def test_single_email_is_weak(self) -> None:
        mq = compute_match_quality({"email": "a@b.com"})
        assert mq["score"] == MATCH_QUALITY_WEIGHTS["em"]  # 22
        assert mq["tier"] == "weak"
        assert mq["present"] == ["em"]

    def test_alias_resolution(self) -> None:
        # short native keys and friendly names resolve to the same signal
        assert compute_match_quality({"em": "x"})["score"] == 22
        assert compute_match_quality({"user_agent": "UA"})["present"] == [
            "client_user_agent"
        ]
        assert compute_match_quality({"ip": "1.2.3.4"})["present"] == [
            "client_ip_address"
        ]
        # pre-hashed variant counts the same
        assert compute_match_quality({"email_hash": "deadbeef"})["score"] == 22

    def test_blank_values_do_not_count(self) -> None:
        mq = compute_match_quality({"email": "  ", "phone": None, "fbp": ""})
        assert mq["score"] == 0
        assert mq["present"] == []

    def test_unknown_keys_ignored(self) -> None:
        mq = compute_match_quality({"foo": "bar", "email": "a@b.com"})
        assert mq["present"] == ["em"]

    def test_tier_boundaries(self) -> None:
        # medium starts at 30 (em + fbp = 32)
        assert compute_match_quality({"email": "x", "fbp": "y"})["tier"] == "medium"
        # good starts at 60 (em + ph + fbp + external_id = 60)
        good = compute_match_quality(
            {"email": "x", "phone": "y", "fbp": "z", "external_id": "e"}
        )
        assert good["score"] == 60
        assert good["tier"] == "good"
        # excellent starts at 85 (em+ph+fbc+fbp+external_id+ip+ua = 87)
        exc = compute_match_quality(
            {
                "email": "x", "phone": "y", "fbc": "c", "fbp": "p",
                "external_id": "e", "client_ip_address": "i",
                "client_user_agent": "u",
            }
        )
        assert exc["score"] == 87
        assert exc["tier"] == "excellent"

    def test_present_ordered_by_weight_desc(self) -> None:
        mq = compute_match_quality(
            {"country": "TR", "email": "a@b.com", "fbp": "z"}
        )
        # em (22) > fbp (10) > country (1)
        assert mq["present"] == ["em", "fbp", "country"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compute_match_quality_stats — aggregation
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeMQEvent:
    def __init__(self, match_quality) -> None:
        self.match_quality = match_quality


class TestMatchQualityStats:
    def test_none_when_no_scores(self) -> None:
        assert compute_match_quality_stats([]) is None
        assert compute_match_quality_stats([_FakeMQEvent(None)]) is None

    def test_aggregates_avg_and_distribution(self) -> None:
        events = [
            _FakeMQEvent({"score": 100, "tier": "excellent", "present": ["em", "ph"]}),
            _FakeMQEvent({"score": 0, "tier": "weak", "present": []}),
            _FakeMQEvent({"score": 22, "tier": "weak", "present": ["em"]}),
        ]
        stats = compute_match_quality_stats(events)
        assert stats is not None
        assert stats["scored_events"] == 3
        assert stats["avg_score"] == round((100 + 0 + 22) / 3)  # 41
        assert stats["tier_distribution"]["excellent"] == 1
        assert stats["tier_distribution"]["weak"] == 2

    def test_field_coverage(self) -> None:
        events = [
            _FakeMQEvent({"score": 40, "tier": "medium", "present": ["em", "ph"]}),
            _FakeMQEvent({"score": 22, "tier": "weak", "present": ["em"]}),
        ]
        stats = compute_match_quality_stats(events)
        cov = {f["key"]: f for f in stats["field_coverage"]}
        assert cov["em"]["present"] == 2
        assert cov["em"]["coverage_pct"] == 100
        assert cov["ph"]["present"] == 1
        assert cov["ph"]["coverage_pct"] == 50
        # field_coverage ordered by weight descending
        weights = [f["weight"] for f in stats["field_coverage"]]
        assert weights == sorted(weights, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. hash_identity — external_id + fbc/fbp
# ═══════════════════════════════════════════════════════════════════════════════


class TestHashIdentityExtended:
    def test_external_id_hashed_and_normalized(self) -> None:
        r1 = hash_identity({"external_id": "  Cust-1  "})
        r2 = hash_identity({"external_id": "cust-1"})
        assert r1["external_id"] == r2["external_id"]  # trim + lower
        assert len(r1["external_id"]) == 64
        assert "Cust-1" not in r1["external_id"]

    def test_fbc_fbp_passthrough_not_hashed(self) -> None:
        r = hash_identity({"fbc": "fb.1.1.abc", "fbp": "fb.1.1.def"})
        assert r["fbc"] == "fb.1.1.abc"
        assert r["fbp"] == "fb.1.1.def"

    def test_blank_external_id_dropped(self) -> None:
        assert "external_id" not in hash_identity({"external_id": "   "})

    def test_empty_input_still_empty(self) -> None:
        assert hash_identity({}) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 4 + 5. ingest stores match_quality; stats endpoint exposes it
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def _make_source(db: Session, tenant_id: uuid.UUID) -> TrackingSource:
    src = TrackingSource(
        tenant_id=tenant_id,
        name="MQ Test Source",
        domain="example.com",
        public_token="mq-test-token-0001",
        is_active=True,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


class TestIngestStoresMatchQuality:
    def test_match_quality_persisted(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        event = ingest_event(
            db_session,
            src,
            {
                "event_name": "Purchase",
                "event_time": "2026-06-25T10:00:00+00:00",
                "event_id": "mq-evt-1",
                "user_data": {
                    "email": "buyer@test.com",
                    "phone": "5551112233",
                    "fbp": "fb.1.1.xyz",
                },
                "custom_data": {},
                "consent": True,
            },
        )
        assert event.match_quality is not None
        # em(22) + ph(18) + fbp(10) = 50 → medium
        assert event.match_quality["score"] == 50
        assert event.match_quality["tier"] == "medium"
        assert set(event.match_quality["present"]) == {"em", "ph", "fbp"}
        # raw PII not persisted
        assert "email" not in event.user_data
        assert "email_hash" in event.user_data


class TestStatsEndpointMatchQuality:
    def _build_app(self, db_session: Session, tenant_id: uuid.UUID):
        app = FastAPI()
        app.include_router(tracking_module.router, prefix="/api/v1")

        def _override_db():
            yield db_session

        fake_membership = Membership(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            role=MembershipRole.owner,
        )

        def _override_membership():
            return fake_membership

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_membership] = _override_membership
        return TestClient(app)

    def test_stats_includes_match_quality(self, db_session: Session) -> None:
        tenant_id = uuid.uuid4()
        src = _make_source(db_session, tenant_id)
        today = datetime.now(timezone.utc).date()
        created = today.isoformat() + "T10:00:00+00:00"
        # two scored events
        for i, raw in enumerate(
            [
                {"email": "a@b.com", "phone": "5551112233", "fbp": "p"},  # 50
                {"email": "c@d.com"},  # 22
            ]
        ):
            ingest_event(
                db_session,
                src,
                {
                    "event_name": "Purchase",
                    "event_time": created,
                    "event_id": f"mq-stats-{i}",
                    "user_data": raw,
                    "custom_data": {},
                    "consent": True,
                },
            )
            # normalize created_at into range
        for e in db_session.query(ConversionEvent).all():
            e.created_at = created
        db_session.commit()

        client = self._build_app(db_session, tenant_id)
        resp = client.get(f"/api/v1/tracking/sources/{src.id}/stats")
        assert resp.status_code == 200
        body = resp.json()
        mq = body["match_quality"]
        assert mq is not None
        assert mq["scored_events"] == 2
        assert mq["avg_score"] == round((50 + 22) / 2)  # 36
        assert mq["tier_distribution"]["weak"] >= 1
        cov = {f["key"]: f for f in mq["field_coverage"]}
        assert cov["em"]["coverage_pct"] == 100
