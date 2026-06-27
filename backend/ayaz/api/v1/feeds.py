"""Feed Management API — M5 (Channable-style).

Tenant-scoped endpoints (require auth JWT with ``tid`` claim):

    GET    /feeds/sources                   — list feed sources for tenant
    POST   /feeds/sources                   — create a new feed source
    GET    /feeds/sources/{id}              — get one feed source
    PATCH  /feeds/sources/{id}              — update a feed source
    DELETE /feeds/sources/{id}              — delete a feed source
    POST   /feeds/sources/{id}/sync         — ingest (upload bytes or fetch URL)
    GET    /feeds/sources/{id}/channels     — list channels for a source
    POST   /feeds/sources/{id}/channels     — create a channel for a source
    GET    /feeds/channels/{id}             — get one channel
    PATCH  /feeds/channels/{id}             — update a channel
    DELETE /feeds/channels/{id}             — delete a channel
    GET    /feeds/channels/{id}/rules       — list rules for a channel
    POST   /feeds/channels/{id}/rules       — create a rule
    POST   /feeds/channels/{id}/rules/reorder — reorder rules by position list
    PATCH  /feeds/rules/{id}               — update a rule
    DELETE /feeds/rules/{id}               — delete a rule

Public (no auth — token is the secret):

    GET /feeds/public/{public_token}        — serve the generated channel feed

Public URL scheme
-----------------
    https://<host>/api/v1/feeds/public/<public_token>

Users paste this URL directly into Google Merchant Center, Meta Catalog,
TikTok Shop, or any other feed consumer.  The 32-byte urlsafe token is
generated at channel creation time and is unguessable.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, field_validator
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.config import settings
from ayaz.models.feeds import FeedChannel, FeedProduct, FeedRule, FeedSource
from ayaz.models.oltp import Membership
from ayaz.security.rate_limit import rate_limit
from ayaz.services.feeds import (
    VALID_CHANNEL_TYPES,
    VALID_OUTPUT_FORMATS,
    VALID_RULE_TYPES,
    VALID_SOURCE_TYPES,
    _IMPACT_SAMPLE_LIMIT,
    compute_rules_impact,
    generate_channel_feed,
    ingest_feed_source,
    lint_rules,
    simulate_rule,
)

router = APIRouter(prefix="/feeds", tags=["feeds"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _require_source(
    source_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> FeedSource:
    src = db.scalar(
        select(FeedSource).where(
            FeedSource.id == source_id,
            FeedSource.tenant_id == tenant_id,
        )
    )
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed source not found.")
    return src


def _require_channel(
    channel_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> FeedChannel:
    ch = db.scalar(
        select(FeedChannel).where(
            FeedChannel.id == channel_id,
            FeedChannel.tenant_id == tenant_id,
        )
    )
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed channel not found.")
    return ch


def _require_rule(
    rule_id: uuid.UUID, tenant_id: uuid.UUID, db: Session
) -> FeedRule:
    rule = db.scalar(
        select(FeedRule).where(
            FeedRule.id == rule_id,
            FeedRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed rule not found.")
    return rule


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class FeedSourceCreate(BaseModel):
    name: str
    source_type: str
    source_url: str | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str) -> str:
        if v not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}")
        return v


class FeedSourcePatch(BaseModel):
    name: str | None = None
    source_type: str | None = None
    source_url: str | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}")
        return v


class FeedSourceResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    source_type: str
    source_url: str | None
    status: str
    item_count: int
    last_synced_at: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: FeedSource) -> "FeedSourceResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            source_type=obj.source_type,
            source_url=obj.source_url,
            status=obj.status,
            item_count=obj.item_count,
            last_synced_at=obj.last_synced_at,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class FeedChannelCreate(BaseModel):
    name: str
    channel_type: str
    output_format: str = "xml"

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v: str) -> str:
        if v not in VALID_CHANNEL_TYPES:
            raise ValueError(f"channel_type must be one of {sorted(VALID_CHANNEL_TYPES)}")
        return v

    @field_validator("output_format")
    @classmethod
    def validate_output_format(cls, v: str) -> str:
        if v not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {sorted(VALID_OUTPUT_FORMATS)}")
        return v


class FeedChannelPatch(BaseModel):
    name: str | None = None
    channel_type: str | None = None
    output_format: str | None = None
    is_active: bool | None = None

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CHANNEL_TYPES:
            raise ValueError(f"channel_type must be one of {sorted(VALID_CHANNEL_TYPES)}")
        return v

    @field_validator("output_format")
    @classmethod
    def validate_output_format(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {sorted(VALID_OUTPUT_FORMATS)}")
        return v


class FeedChannelResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    feed_source_id: uuid.UUID
    name: str
    channel_type: str
    output_format: str
    public_token: str
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: FeedChannel) -> "FeedChannelResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            feed_source_id=obj.feed_source_id,
            name=obj.name,
            channel_type=obj.channel_type,
            output_format=obj.output_format,
            public_token=obj.public_token,
            is_active=obj.is_active,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class FeedRuleCreate(BaseModel):
    rule_type: str
    position: int = 0
    config: dict = {}
    is_paused: bool = False

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(VALID_RULE_TYPES)}")
        return v


class FeedRulePatch(BaseModel):
    rule_type: str | None = None
    position: int | None = None
    config: dict | None = None
    is_paused: bool | None = None

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(VALID_RULE_TYPES)}")
        return v


class FeedRuleResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    feed_channel_id: uuid.UUID
    position: int
    rule_type: str
    config: dict
    is_paused: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: FeedRule) -> "FeedRuleResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            feed_channel_id=obj.feed_channel_id,
            position=obj.position,
            rule_type=obj.rule_type,
            config=obj.config,
            is_paused=obj.is_paused,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class ReorderBody(BaseModel):
    """List of rule IDs in the desired order (position = index in list)."""
    rule_ids: list[uuid.UUID]


class SyncResponse(BaseModel):
    item_count: int
    status: str
    last_synced_at: str | None


# ── Feed Source CRUD ──────────────────────────────────────────────────────────


@router.get(
    "/sources",
    response_model=list[FeedSourceResponse],
    summary="List all feed sources for the current tenant",
)
def list_sources(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[FeedSourceResponse]:
    rows = list(
        db.scalars(
            select(FeedSource).where(FeedSource.tenant_id == membership.tenant_id)
        )
    )
    return [FeedSourceResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/sources",
    response_model=FeedSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new feed source",
)
def create_source(
    body: FeedSourceCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedSourceResponse:
    src = FeedSource(
        tenant_id=membership.tenant_id,
        name=body.name,
        source_type=body.source_type,
        source_url=body.source_url,
        status="pending",
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return FeedSourceResponse.from_orm_obj(src)


@router.get(
    "/sources/{source_id}",
    response_model=FeedSourceResponse,
    summary="Get one feed source",
)
def get_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedSourceResponse:
    src = _require_source(source_id, membership.tenant_id, db)
    return FeedSourceResponse.from_orm_obj(src)


@router.patch(
    "/sources/{source_id}",
    response_model=FeedSourceResponse,
    summary="Update a feed source",
)
def patch_source(
    source_id: uuid.UUID,
    body: FeedSourcePatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedSourceResponse:
    src = _require_source(source_id, membership.tenant_id, db)
    if body.name is not None:
        src.name = body.name
    if body.source_type is not None:
        src.source_type = body.source_type
    if body.source_url is not None:
        src.source_url = body.source_url
    db.add(src)
    db.commit()
    db.refresh(src)
    return FeedSourceResponse.from_orm_obj(src)


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a feed source and all its products and channels",
)
def delete_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    src = _require_source(source_id, membership.tenant_id, db)
    db.delete(src)
    db.commit()


# ── Sync (ingest) ─────────────────────────────────────────────────────────────


@router.post(
    "/sources/{source_id}/sync",
    response_model=SyncResponse,
    summary="Ingest a feed source (upload file or fetch from source_url)",
)
def sync_source(
    source_id: uuid.UUID,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SyncResponse:
    """Trigger feed ingestion.

    If a file is uploaded, its bytes are used as feed content.
    Otherwise the source_url on the FeedSource is fetched (live network).
    """
    src = _require_source(source_id, membership.tenant_id, db)

    raw_bytes: bytes | None = None
    if file is not None:
        raw_bytes = file.file.read()

    try:
        count = ingest_feed_source(db, src, raw_bytes=raw_bytes)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SyncResponse(
        item_count=count,
        status=src.status,
        last_synced_at=src.last_synced_at,
    )


# ── Channel CRUD ──────────────────────────────────────────────────────────────


@router.get(
    "/sources/{source_id}/channels",
    response_model=list[FeedChannelResponse],
    summary="List channels for a feed source",
)
def list_channels_for_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[FeedChannelResponse]:
    _require_source(source_id, membership.tenant_id, db)
    rows = list(
        db.scalars(
            select(FeedChannel).where(
                FeedChannel.feed_source_id == source_id,
                FeedChannel.tenant_id == membership.tenant_id,
            )
        )
    )
    return [FeedChannelResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/sources/{source_id}/channels",
    response_model=FeedChannelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a channel for a feed source",
)
def create_channel(
    source_id: uuid.UUID,
    body: FeedChannelCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedChannelResponse:
    _require_source(source_id, membership.tenant_id, db)

    # Derive default output_format from channel_type if not overridden
    fmt = body.output_format
    if body.channel_type in ("meta_catalog", "tiktok_catalog") and fmt == "xml":
        fmt = "csv"  # these channels are always CSV

    ch = FeedChannel(
        tenant_id=membership.tenant_id,
        feed_source_id=source_id,
        name=body.name,
        channel_type=body.channel_type,
        output_format=fmt,
        public_token=secrets.token_urlsafe(32),
        is_active=True,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return FeedChannelResponse.from_orm_obj(ch)


@router.get(
    "/channels/{channel_id}",
    response_model=FeedChannelResponse,
    summary="Get one feed channel",
)
def get_channel(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedChannelResponse:
    ch = _require_channel(channel_id, membership.tenant_id, db)
    return FeedChannelResponse.from_orm_obj(ch)


@router.patch(
    "/channels/{channel_id}",
    response_model=FeedChannelResponse,
    summary="Update a feed channel",
)
def patch_channel(
    channel_id: uuid.UUID,
    body: FeedChannelPatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedChannelResponse:
    ch = _require_channel(channel_id, membership.tenant_id, db)
    if body.name is not None:
        ch.name = body.name
    if body.channel_type is not None:
        ch.channel_type = body.channel_type
    if body.output_format is not None:
        ch.output_format = body.output_format
    if body.is_active is not None:
        ch.is_active = body.is_active
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return FeedChannelResponse.from_orm_obj(ch)


@router.delete(
    "/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a feed channel and its rules",
)
def delete_channel(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    ch = _require_channel(channel_id, membership.tenant_id, db)
    db.delete(ch)
    db.commit()


# ── Rule CRUD ─────────────────────────────────────────────────────────────────


@router.get(
    "/channels/{channel_id}/rules",
    response_model=list[FeedRuleResponse],
    summary="List rules for a channel",
)
def list_rules(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[FeedRuleResponse]:
    _require_channel(channel_id, membership.tenant_id, db)
    rows = list(
        db.scalars(
            select(FeedRule)
            .where(
                FeedRule.feed_channel_id == channel_id,
                FeedRule.tenant_id == membership.tenant_id,
            )
            .order_by(FeedRule.position)
        )
    )
    return [FeedRuleResponse.from_orm_obj(r) for r in rows]


@router.post(
    "/channels/{channel_id}/rules",
    response_model=FeedRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule for a channel",
)
def create_rule(
    channel_id: uuid.UUID,
    body: FeedRuleCreate,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedRuleResponse:
    _require_channel(channel_id, membership.tenant_id, db)
    rule = FeedRule(
        tenant_id=membership.tenant_id,
        feed_channel_id=channel_id,
        rule_type=body.rule_type,
        position=body.position,
        config=body.config,
        is_paused=body.is_paused,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return FeedRuleResponse.from_orm_obj(rule)


@router.post(
    "/channels/{channel_id}/rules/reorder",
    response_model=list[FeedRuleResponse],
    summary="Reorder rules by providing an ordered list of rule IDs",
)
def reorder_rules(
    channel_id: uuid.UUID,
    body: ReorderBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> list[FeedRuleResponse]:
    """Assign ``position = index`` for each rule ID in the given list."""
    _require_channel(channel_id, membership.tenant_id, db)
    updated: list[FeedRule] = []
    for idx, rule_id in enumerate(body.rule_ids):
        rule = _require_rule(rule_id, membership.tenant_id, db)
        if rule.feed_channel_id != channel_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rule {rule_id} does not belong to channel {channel_id}.",
            )
        rule.position = idx
        db.add(rule)
        updated.append(rule)
    db.commit()
    for r in updated:
        db.refresh(r)
    return [FeedRuleResponse.from_orm_obj(r) for r in updated]


@router.patch(
    "/rules/{rule_id}",
    response_model=FeedRuleResponse,
    summary="Update a feed rule",
)
def patch_rule(
    rule_id: uuid.UUID,
    body: FeedRulePatch,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> FeedRuleResponse:
    rule = _require_rule(rule_id, membership.tenant_id, db)
    if body.rule_type is not None:
        rule.rule_type = body.rule_type
    if body.position is not None:
        rule.position = body.position
    if body.config is not None:
        rule.config = body.config
    if body.is_paused is not None:
        rule.is_paused = body.is_paused
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return FeedRuleResponse.from_orm_obj(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a feed rule",
)
def delete_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> None:
    rule = _require_rule(rule_id, membership.tenant_id, db)
    db.delete(rule)
    db.commit()


# ── Feed Rule Studio: Pydantic schemas ───────────────────────────────────────


class RuleImpactStat(BaseModel):
    rule_id: str
    position: int
    rule_type: str
    is_paused: bool
    affected_count: int
    excluded_count: int


class RulesImpactResponse(BaseModel):
    total_before: int
    total_after: int
    sampled: bool
    sampled_total: int | None
    rules: list[RuleImpactStat]


class SimulateRuleBody(BaseModel):
    rule_type: str
    config: dict = {}
    position: int | None = None

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(VALID_RULE_TYPES)}")
        return v


class SimulateRuleResponse(BaseModel):
    affected_count: int
    excluded_count: int
    sample_before: list[dict]
    sample_after: list[dict]


class LintIssue(BaseModel):
    severity: str
    rule_id: str
    position: int
    code: str
    message: str


class LintResponse(BaseModel):
    issues: list[LintIssue]


# ── Feed Rule Studio: helper to load channel products ────────────────────────


def _load_channel_products(
    channel: FeedChannel, db: Session, limit: int = _IMPACT_SAMPLE_LIMIT
) -> tuple[list[dict], int]:
    """Load FeedProduct rows for a channel's source (tenant-scoped).

    Returns (products, total_count) where products is capped at limit.
    """
    total_count: int = db.scalar(
        select(sa_func.count(FeedProduct.id)).where(
            FeedProduct.feed_source_id == channel.feed_source_id,
            FeedProduct.tenant_id == channel.tenant_id,
        )
    ) or 0

    rows = list(
        db.scalars(
            select(FeedProduct)
            .where(
                FeedProduct.feed_source_id == channel.feed_source_id,
                FeedProduct.tenant_id == channel.tenant_id,
            )
            .limit(limit)
        )
    )
    products = [r.data for r in rows]
    return products, total_count


# ── Feed Rule Studio: new endpoints ──────────────────────────────────────────


@router.get(
    "/channels/{channel_id}/rules/impact",
    response_model=RulesImpactResponse,
    summary="Impact preview — per-rule affected/excluded counts for a channel",
)
def rules_impact(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> RulesImpactResponse:
    """Return how many products each rule affects or excludes.

    Products are sampled (up to 1000) for performance on large catalogues.
    ``sampled=True`` and ``sampled_total`` indicate when sampling was applied.
    Paused rules appear with zero counts and ``is_paused=True``.
    """
    ch = _require_channel(channel_id, membership.tenant_id, db)

    products, total_count = _load_channel_products(ch, db, limit=_IMPACT_SAMPLE_LIMIT)
    sampled = total_count > _IMPACT_SAMPLE_LIMIT

    rules = list(
        db.scalars(
            select(FeedRule)
            .where(
                FeedRule.feed_channel_id == channel_id,
                FeedRule.tenant_id == membership.tenant_id,
            )
            .order_by(FeedRule.position)
        )
    )

    result = compute_rules_impact(products, rules)

    return RulesImpactResponse(
        total_before=result["total_before"],
        total_after=result["total_after"],
        sampled=sampled,
        sampled_total=total_count if sampled else None,
        rules=[RuleImpactStat(**stat) for stat in result["rules"]],
    )


@router.post(
    "/channels/{channel_id}/rules/simulate",
    response_model=SimulateRuleResponse,
    summary="Dry-run an unsaved rule without persisting it",
)
def simulate_channel_rule(
    channel_id: uuid.UUID,
    body: SimulateRuleBody,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> SimulateRuleResponse:
    """Simulate a candidate rule on top of the channel's saved non-paused rules.

    Nothing is persisted.  The candidate rule is applied after all saved
    non-paused rules whose position is less than ``body.position`` (or after
    all of them if position is not specified).

    Returns affected_count, excluded_count, and up to 3 sample products
    before/after the candidate rule is applied.
    """
    ch = _require_channel(channel_id, membership.tenant_id, db)

    products, _ = _load_channel_products(ch, db, limit=_IMPACT_SAMPLE_LIMIT)

    saved_rules = list(
        db.scalars(
            select(FeedRule)
            .where(
                FeedRule.feed_channel_id == channel_id,
                FeedRule.tenant_id == membership.tenant_id,
            )
            .order_by(FeedRule.position)
        )
    )

    result = simulate_rule(
        products=products,
        saved_rules=saved_rules,
        candidate_rule_type=body.rule_type,
        candidate_config=body.config,
        candidate_position=body.position,
    )

    return SimulateRuleResponse(**result)


@router.get(
    "/channels/{channel_id}/rules/lint",
    response_model=LintResponse,
    summary="Lint a channel's rules for common mistakes",
)
def lint_channel_rules(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> LintResponse:
    """Run the rule linter against a sample of the channel's products.

    Returns a list of issues with severity (error/warning/info), a machine-
    readable code, and a Turkish language message.  An empty issues list means
    no problems were detected.
    """
    ch = _require_channel(channel_id, membership.tenant_id, db)

    products, _ = _load_channel_products(ch, db, limit=_IMPACT_SAMPLE_LIMIT)

    rules = list(
        db.scalars(
            select(FeedRule)
            .where(
                FeedRule.feed_channel_id == channel_id,
                FeedRule.tenant_id == membership.tenant_id,
            )
            .order_by(FeedRule.position)
        )
    )

    issues = lint_rules(products, rules)

    return LintResponse(issues=[LintIssue(**issue) for issue in issues])


# ── Public feed endpoint (no auth) ────────────────────────────────────────────


@router.get(
    "/public/{public_token}",
    summary="Serve a public channel feed (no auth — paste this URL into Merchant Center / Meta / TikTok)",
    include_in_schema=True,
)
def public_feed(
    public_token: str,
    request: Request,
    db: Session = Depends(get_db),
    _rl: None = Depends(
        rate_limit(
            "feeds:public",
            limit=settings.rate_limit_public_limit,
            window_seconds=settings.rate_limit_public_window,
        )
    ),
) -> Response:
    """Return the generated channel feed for the given public token.

    This endpoint requires NO authentication.  The public_token is a 32-byte
    urlsafe random string generated at channel creation and is the sole secret.

    Content-Type is ``application/xml`` for XML feeds and
    ``text/csv; charset=utf-8`` for CSV feeds.

    Rate limited: 120 requests/minute/IP (configurable via settings).
    """
    channel = db.scalar(
        select(FeedChannel).where(
            FeedChannel.public_token == public_token,
            FeedChannel.is_active.is_(True),
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found or inactive.",
        )

    content, content_type = generate_channel_feed(db, channel)
    return Response(content=content, media_type=content_type)
