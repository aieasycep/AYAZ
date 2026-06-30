"""Sync pipeline — pulls data from a connector and upserts into the warehouse.

Entry point
-----------
    sync_connected_account(db, account, since, until)

The function is deliberately synchronous (matching the existing session layer)
and idempotent: running it twice for the same date range is safe — it will
update existing fact rows rather than insert duplicates.

Grain
-----
The unique grain is defined by the ``uq_fact_daily_grain`` unique constraint on
``fact_daily_metrics``:

    (tenant_id, connected_account_id, channel_id, campaign_id, adset_id, ad_id, date_key)

Upsert strategy: SELECT for existing row → UPDATE if found, INSERT if not.
This avoids needing dialect-specific ON CONFLICT syntax so the same code works
with both Postgres (production) and SQLite (tests).

Currency
--------
FX conversion is not yet implemented (TODO Faz 1 — rate fetch task).
``cost_base_ccy`` is set equal to ``cost_raw`` and
``conv_value_base_ccy`` equal to ``conversion_value_raw`` as a placeholder.
The dashboard's "spend" column always prefers ``cost_base_ccy`` when non-zero.

dim_date seeding
----------------
Because fact_daily_metrics.date_key is a FK into dim_date, this module
ensures a dim_date row exists for every date it touches (get-or-create).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.connectors import ConnectorRegistry
from ayaz.connectors.base import ConnectorConfig, UnifiedRecord
from ayaz.models.analytics import (
    DimAd,
    DimAdSet,
    DimCampaign,
    DimChannel,
    DimDate,
    FactDailyMetrics,
)
from ayaz.models.oltp import ConnectedAccount, SyncStatus

logger = logging.getLogger(__name__)


# ── dim_date helper ───────────────────────────────────────────────────────────


def _ensure_dim_date(db: Session, d: date) -> None:
    """Insert a dim_date row for ``d`` if one does not already exist."""
    existing = db.get(DimDate, d)
    if existing is not None:
        return
    iso_cal = d.isocalendar()  # (year, week, weekday 1=Mon)
    dim = DimDate(
        date_key=d,
        year=d.year,
        quarter=(d.month - 1) // 3 + 1,
        month=d.month,
        week=iso_cal.week,
        day_of_week=d.weekday(),  # 0=Mon … 6=Sun
        is_weekend=d.weekday() >= 5,
    )
    db.add(dim)
    # Flush immediately so the FK is satisfiable in the same transaction.
    db.flush()


# ── dim_channel helper ────────────────────────────────────────────────────────


def _get_or_create_channel(db: Session, platform_key: str) -> DimChannel:
    """Return the DimChannel for ``platform_key``, creating it if absent."""
    channel = db.scalar(
        select(DimChannel).where(DimChannel.key == platform_key)
    )
    if channel is None:
        channel = DimChannel(
            key=platform_key,
            label=platform_key.replace("_", " ").title(),
        )
        db.add(channel)
        db.flush()
    return channel


# ── dim_campaign / adset / ad helpers ────────────────────────────────────────


def _get_or_create_campaign(
    db: Session,
    tenant_id: Any,
    channel: DimChannel,
    external_id: str,
    name: str,
) -> DimCampaign:
    campaign = db.scalar(
        select(DimCampaign).where(
            DimCampaign.tenant_id == tenant_id,
            DimCampaign.channel_id == channel.id,
            DimCampaign.external_id == external_id,
        )
    )
    if campaign is None:
        campaign = DimCampaign(
            tenant_id=tenant_id,
            channel_id=channel.id,
            external_id=external_id,
            name=name,
        )
        db.add(campaign)
        db.flush()
    elif campaign.name != name and name:
        campaign.name = name
    return campaign


def _get_or_create_adset(
    db: Session,
    tenant_id: Any,
    campaign: DimCampaign,
    external_id: str,
    name: str,
) -> DimAdSet:
    adset = db.scalar(
        select(DimAdSet).where(
            DimAdSet.tenant_id == tenant_id,
            DimAdSet.campaign_id == campaign.id,
            DimAdSet.external_id == external_id,
        )
    )
    if adset is None:
        adset = DimAdSet(
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            external_id=external_id,
            name=name,
        )
        db.add(adset)
        db.flush()
    elif adset.name != name and name:
        adset.name = name
    return adset


def _get_or_create_ad(
    db: Session,
    tenant_id: Any,
    adset: DimAdSet,
    external_id: str,
    name: str,
) -> DimAd:
    ad = db.scalar(
        select(DimAd).where(
            DimAd.tenant_id == tenant_id,
            DimAd.ad_set_id == adset.id,
            DimAd.external_id == external_id,
        )
    )
    if ad is None:
        ad = DimAd(
            tenant_id=tenant_id,
            ad_set_id=adset.id,
            external_id=external_id,
            name=name,
        )
        db.add(ad)
        db.flush()
    elif ad.name != name and name:
        ad.name = name
    return ad


# ── Upsert fact row ───────────────────────────────────────────────────────────


def _upsert_fact(
    db: Session,
    *,
    tenant_id: Any,
    connected_account_id: Any,
    channel: DimChannel,
    campaign: DimCampaign,
    adset: DimAdSet,
    ad: DimAd,
    record: UnifiedRecord,
) -> tuple[FactDailyMetrics, bool]:
    """Return (fact_row, created).  Updates metrics if the row already exists."""
    # Prefer cost_base_ccy when it has been populated; fall back to cost_raw.
    # (FX conversion is a TODO; for now they are equal.)
    spend = record.cost_raw  # Decimal

    existing = db.scalar(
        select(FactDailyMetrics).where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.connected_account_id == connected_account_id,
            FactDailyMetrics.channel_id == channel.id,
            FactDailyMetrics.campaign_id == campaign.id,
            FactDailyMetrics.adset_id == adset.id,
            FactDailyMetrics.ad_id == ad.id,
            FactDailyMetrics.date_key == record.date_key,
        )
    )

    now_utc = datetime.now(timezone.utc)

    if existing is None:
        fact = FactDailyMetrics(
            tenant_id=tenant_id,
            connected_account_id=connected_account_id,
            channel_id=channel.id,
            campaign_id=campaign.id,
            adset_id=adset.id,
            ad_id=ad.id,
            date_key=record.date_key,
            impressions=record.impressions,
            clicks=record.clicks,
            cost_raw=record.cost_raw,
            cost_ccy=record.cost_ccy,
            conversions=record.conversions,
            conversion_value_raw=record.conversion_value_raw,
            conversion_value_ccy=record.conversion_value_ccy,
            # Placeholder: no FX conversion yet.
            cost_base_ccy=spend,
            conv_value_base_ccy=record.conversion_value_raw,
            ingested_at=now_utc,
        )
        db.add(fact)
        db.flush()
        return fact, True
    else:
        existing.impressions = record.impressions
        existing.clicks = record.clicks
        existing.cost_raw = record.cost_raw
        existing.cost_ccy = record.cost_ccy
        existing.conversions = record.conversions
        existing.conversion_value_raw = record.conversion_value_raw
        existing.conversion_value_ccy = record.conversion_value_ccy
        existing.cost_base_ccy = spend
        existing.conv_value_base_ccy = record.conversion_value_raw
        existing.ingested_at = now_utc
        return existing, False


# ── Public API ────────────────────────────────────────────────────────────────


def sync_connected_account(
    db: Session,
    account: ConnectedAccount,
    since: date,
    until: date,
) -> dict[str, int]:
    """Sync one connected account for the given date range.

    Steps
    -----
    1. Resolve connector class from ``ConnectorRegistry``.
    2. Instantiate with a ``ConnectorConfig`` built from the account row
       (no Vault call — fixture / no-creds path for demo).
    3. ``fetch`` + ``normalize`` for each supported stream.
    4. For each ``UnifiedRecord``:
       a. Ensure dim_date, dim_channel, dim_campaign, dim_adset, dim_ad rows.
       b. Upsert into fact_daily_metrics.
    5. Update ``account.watermark`` to the latest date synced.
    6. Set ``account.sync_status`` to ``success`` (or ``error`` on exception).
    7. Commit.

    Parameters
    ----------
    db:
        SQLAlchemy Session.
    account:
        ConnectedAccount ORM row — provides tenant_id, platform, etc.
    since:
        Inclusive start date of the sync window (UTC).
    until:
        Inclusive end date of the sync window (UTC).

    Returns
    -------
    dict with ``inserted``, ``updated``, ``records_processed`` counts.

    Raises
    ------
    KeyError
        If no connector is registered for ``account.platform``.
    Exception
        Any connector or DB error — the caller is responsible for rollback.
    """
    platform_key: str = account.platform.value  # Platform enum → str
    tenant_id = account.tenant_id
    connected_account_id = account.id

    logger.info(
        "[sync] Starting sync: account=%s platform=%s since=%s until=%s",
        account.id,
        platform_key,
        since,
        until,
    )

    # 1. Resolve connector class
    connector_cls = ConnectorRegistry.get(platform_key)

    config = ConnectorConfig(
        tenant_id=str(tenant_id),
        connected_account_id=str(connected_account_id),
        external_account_id=account.external_account_id,
        platform_key=platform_key,
        vault_secret_ref=account.vault_secret_ref or "",
        extra={},
    )
    connector = connector_cls(config=config)

    account.sync_status = SyncStatus.syncing
    db.flush()

    try:
        caps = connector.capabilities()
        all_records: list[UnifiedRecord] = []

        # 2. Fetch + normalize every supported stream
        for stream in caps.supported_streams:
            raw = connector.fetch(stream=stream, since=since, until=until)
            records = connector.normalize(raw)
            all_records.extend(records)

        # 3. Ensure shared channel dim (once per platform)
        channel = _get_or_create_channel(db, platform_key)

        inserted = 0
        updated = 0

        # 4. Upsert each record
        for rec in all_records:
            _ensure_dim_date(db, rec.date_key)

            campaign = _get_or_create_campaign(
                db, tenant_id, channel,
                external_id=rec.campaign_id,
                name=rec.campaign_name,
            )
            adset = _get_or_create_adset(
                db, tenant_id, campaign,
                external_id=rec.adset_id,
                name=rec.adset_name,
            )
            ad = _get_or_create_ad(
                db, tenant_id, adset,
                external_id=rec.ad_id,
                name=rec.ad_name,
            )

            _, created = _upsert_fact(
                db,
                tenant_id=tenant_id,
                connected_account_id=connected_account_id,
                channel=channel,
                campaign=campaign,
                adset=adset,
                ad=ad,
                record=rec,
            )
            if created:
                inserted += 1
            else:
                updated += 1

        # 5. Update watermark to the latest date seen
        if all_records:
            latest_date = max(r.date_key for r in all_records)
            account.watermark = latest_date.isoformat()

        # 5b. For Search Console: also ingest query+page-level data into
        # seo_search_metrics using the "search_query_metrics" extended stream.
        # This is a best-effort step — failure does not roll back the main sync.
        if platform_key == "search_console":
            try:
                gsc_rows = connector.fetch_query_page(since=since, until=until)
                from ayaz.services.seo import store_gsc_rows
                gsc_written = store_gsc_rows(db, tenant_id, gsc_rows)
                logger.info(
                    "[sync] GSC seo_search_metrics: wrote %d rows for tenant=%s",
                    gsc_written,
                    tenant_id,
                )
            except Exception:
                logger.warning(
                    "[sync] GSC seo_search_metrics ingest skipped (connector not authenticated "
                    "or fetch_query_page not available) for account=%s",
                    account.id,
                )

        # 6. Mark success
        account.sync_status = SyncStatus.success
        db.commit()

        logger.info(
            "[sync] Done: account=%s inserted=%d updated=%d",
            account.id, inserted, updated,
        )
        return {
            "inserted": inserted,
            "updated": updated,
            "records_processed": len(all_records),
        }

    except Exception:
        account.sync_status = SyncStatus.error
        db.flush()
        db.commit()
        logger.exception("[sync] Failed for account=%s", account.id)
        raise
