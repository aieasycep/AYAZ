"""SEO analytics service — overview, opportunities, and insight emission.

All functions are tenant-scoped. Never leak data across tenants.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ayaz.models.seo import SeoSearchMetric
from ayaz.models.insights import Insight

logger = logging.getLogger(__name__)

# ── Severity score mapping ─────────────────────────────────────────────────────

_SEVERITY_SCORE: dict[str, float] = {
    "critical": 90.0,
    "warning": 60.0,
    "info": 30.0,
}

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pct_delta(current: float, prior: float) -> float | None:
    """Return (current - prior) / prior * 100, or None if prior == 0."""
    if prior == 0:
        return None
    return (current - prior) / prior * 100.0


def _weighted_avg_ctr(total_clicks: int, total_impressions: int) -> float:
    """Weighted-average CTR: sum(clicks) / sum(impressions)."""
    if total_impressions == 0:
        return 0.0
    return total_clicks / total_impressions


def _weighted_avg_position(sum_pos_imp: float, total_impressions: int) -> float:
    """Weighted-average position: sum(position * impressions) / sum(impressions)."""
    if total_impressions == 0:
        return 0.0
    return sum_pos_imp / total_impressions


# ── Overview ──────────────────────────────────────────────────────────────────


def get_overview(
    db: Session,
    tenant_id: uuid.UUID,
    period_days: int = 30,
) -> dict[str, Any]:
    """Return aggregate SEO metrics for the current period vs prior period.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only).
    tenant_id:
        Tenant UUID — all queries are scoped to this value.
    period_days:
        How many calendar days constitute the current period (ending today).

    Returns
    -------
    dict with keys: period_days, current, prior, trends, top_queries, top_pages.
    """
    today = date.today()
    current_end = today
    current_start = today - timedelta(days=period_days - 1)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=period_days - 1)

    def _aggregate_period(start: date, end: date) -> dict[str, Any]:
        row = db.execute(
            select(
                func.coalesce(func.sum(SeoSearchMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(SeoSearchMetric.impressions), 0).label("impressions"),
                func.coalesce(
                    func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions), 0.0
                ).label("sum_pos_imp"),
            ).where(
                SeoSearchMetric.tenant_id == tenant_id,
                SeoSearchMetric.date >= start,
                SeoSearchMetric.date <= end,
            )
        ).mappings().one()

        total_clicks = int(row["clicks"])
        total_impressions = int(row["impressions"])
        sum_pos_imp = float(row["sum_pos_imp"])

        return {
            "clicks": total_clicks,
            "impressions": total_impressions,
            "ctr": _weighted_avg_ctr(total_clicks, total_impressions),
            "avg_position": _weighted_avg_position(sum_pos_imp, total_impressions),
        }

    def _top_by_dimension(
        dimension_col: Any,
        start: date,
        end: date,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            select(
                dimension_col.label("dimension"),
                func.sum(SeoSearchMetric.clicks).label("clicks"),
                func.sum(SeoSearchMetric.impressions).label("impressions"),
                func.sum(
                    SeoSearchMetric.position * SeoSearchMetric.impressions
                ).label("sum_pos_imp"),
            ).where(
                SeoSearchMetric.tenant_id == tenant_id,
                SeoSearchMetric.date >= start,
                SeoSearchMetric.date <= end,
            )
            .group_by(dimension_col)
            .order_by(func.sum(SeoSearchMetric.clicks).desc())
            .limit(limit)
        ).mappings().all()

        result = []
        for r in rows:
            total_imp = int(r["impressions"])
            total_clk = int(r["clicks"])
            result.append({
                "query" if dimension_col is SeoSearchMetric.query else "page": str(r["dimension"]),
                "clicks": total_clk,
                "impressions": total_imp,
                "ctr": _weighted_avg_ctr(total_clk, total_imp),
                "avg_position": _weighted_avg_position(float(r["sum_pos_imp"]), total_imp),
            })
        return result

    current = _aggregate_period(current_start, current_end)
    prior = _aggregate_period(prior_start, prior_end)

    trends: dict[str, float | None] = {
        "clicks_delta_pct": _pct_delta(current["clicks"], prior["clicks"]),
        "impressions_delta_pct": _pct_delta(current["impressions"], prior["impressions"]),
        "ctr_delta_pct": _pct_delta(current["ctr"], prior["ctr"]),
        "position_delta_pct": _pct_delta(current["avg_position"], prior["avg_position"]),
    }

    top_queries = _top_by_dimension(SeoSearchMetric.query, current_start, current_end)
    top_pages = _top_by_dimension(SeoSearchMetric.page, current_start, current_end)

    return {
        "period_days": period_days,
        "current": current,
        "prior": prior,
        "trends": trends,
        "top_queries": top_queries,
        "top_pages": top_pages,
    }


# ── Opportunities ─────────────────────────────────────────────────────────────


def get_opportunities(
    db: Session,
    tenant_id: uuid.UUID,
    period_days: int = 30,
) -> list[dict[str, Any]]:
    """Compute structured SEO opportunity items from seo_search_metrics.

    Returns a list of opportunity dicts sorted by severity
    (critical first, then warning, then info).

    Each dict has: type, severity, title, body, data.
    """
    today = date.today()
    period_end = today
    period_start = today - timedelta(days=period_days - 1)

    opportunities: list[dict[str, Any]] = []

    # ── 1. Striking distance: queries ranked 8.0–20.0 with >= 100 impressions ─
    striking_rows = db.execute(
        select(
            SeoSearchMetric.query,
            func.sum(SeoSearchMetric.clicks).label("clicks"),
            func.sum(SeoSearchMetric.impressions).label("impressions"),
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ).label("avg_position"),
        ).where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= period_start,
            SeoSearchMetric.date <= period_end,
        )
        .group_by(SeoSearchMetric.query)
        .having(
            func.sum(SeoSearchMetric.impressions) >= 100,
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ).between(8.0, 20.0),
        )
        .order_by(func.sum(SeoSearchMetric.impressions).desc())
    ).mappings().all()

    for row in striking_rows:
        query = str(row["query"])
        clicks = int(row["clicks"])
        impressions = int(row["impressions"])
        avg_position = float(row["avg_position"])
        ctr = _weighted_avg_ctr(clicks, impressions)

        opportunities.append({
            "type": "striking_distance",
            "severity": "warning",
            "title": f"'{query}' sorgusu {avg_position:.1f}. sırada — ilk sayfaya yakın",
            "body": (
                f"Bu sorgu için {impressions} gösterim var ama tıklama oranınız düşük. "
                f"İçeriği optimize ederek ilk sayfaya taşıyabilirsiniz."
            ),
            "data": {
                "query": query,
                "avg_position": avg_position,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr,
            },
        })

    # ── 2. Low CTR: impressions >= 200, CTR < 2%, avg_position <= 10.0 ────────
    low_ctr_rows = db.execute(
        select(
            SeoSearchMetric.query,
            func.sum(SeoSearchMetric.clicks).label("clicks"),
            func.sum(SeoSearchMetric.impressions).label("impressions"),
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ).label("avg_position"),
        ).where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= period_start,
            SeoSearchMetric.date <= period_end,
        )
        .group_by(SeoSearchMetric.query)
        .having(
            func.sum(SeoSearchMetric.impressions) >= 200,
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ) <= 10.0,
        )
        .order_by(func.sum(SeoSearchMetric.impressions).desc())
    ).mappings().all()

    for row in low_ctr_rows:
        query = str(row["query"])
        clicks = int(row["clicks"])
        impressions = int(row["impressions"])
        avg_position = float(row["avg_position"])
        ctr = _weighted_avg_ctr(clicks, impressions)

        if ctr >= 0.02:
            continue

        opportunities.append({
            "type": "low_ctr",
            "severity": "warning",
            "title": f"'{query}' yüksek gösterim, düşük tıklama: %{ctr * 100:.1f} CTR",
            "body": (
                f"İlk 10'da görünüyorsunuz ama {impressions} gösterimden sadece "
                f"{clicks} tıklama alıyorsunuz. Meta açıklaması ve başlığı "
                f"iyileştirmeyi deneyin."
            ),
            "data": {
                "query": query,
                "ctr": ctr,
                "impressions": impressions,
                "avg_position": avg_position,
            },
        })

    # ── 3. Keyword cannibalization: >= 2 distinct pages with >= 50 impressions ─
    # Sub-query: per (query, page) aggregates
    subq = (
        select(
            SeoSearchMetric.query,
            SeoSearchMetric.page,
            func.sum(SeoSearchMetric.impressions).label("page_impressions"),
        ).where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= period_start,
            SeoSearchMetric.date <= period_end,
        )
        .group_by(SeoSearchMetric.query, SeoSearchMetric.page)
        .having(func.sum(SeoSearchMetric.impressions) >= 50)
    ).subquery()

    cannib_rows = db.execute(
        select(
            subq.c.query,
            func.count(subq.c.page).label("page_count"),
        )
        .group_by(subq.c.query)
        .having(func.count(subq.c.page) >= 2)
        .order_by(func.count(subq.c.page).desc())
    ).mappings().all()

    for row in cannib_rows:
        query = str(row["query"])
        page_count = int(row["page_count"])

        # Fetch the actual page URLs for this query
        page_rows = db.execute(
            select(SeoSearchMetric.page)
            .where(
                SeoSearchMetric.tenant_id == tenant_id,
                SeoSearchMetric.query == query,
                SeoSearchMetric.date >= period_start,
                SeoSearchMetric.date <= period_end,
            )
            .group_by(SeoSearchMetric.page)
            .having(func.sum(SeoSearchMetric.impressions) >= 50)
        ).scalars().all()

        pages = [str(p) for p in page_rows]

        opportunities.append({
            "type": "cannibalization",
            "severity": "info",
            "title": f"'{query}' için {page_count} sayfa rekabet ediyor",
            "body": (
                f"Birden fazla sayfa aynı sorgu için sıralanıyor, bu URL otoritesini bölüyor. "
                f"En güçlü sayfayı belirleyip diğerlerini yönlendirin veya birleştirin."
            ),
            "data": {
                "query": query,
                "page_count": page_count,
                "pages": pages,
            },
        })

    # ── 4. Top movers: position change >= 3 in last period//2 vs prior period//2 ─
    half = period_days // 2
    new_end = today
    new_start = today - timedelta(days=half - 1)
    old_end = new_start - timedelta(days=1)
    old_start = old_end - timedelta(days=half - 1)

    # Queries with >= 100 impressions in the full current period
    qualifying_subq = (
        select(SeoSearchMetric.query)
        .where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= period_start,
            SeoSearchMetric.date <= period_end,
        )
        .group_by(SeoSearchMetric.query)
        .having(func.sum(SeoSearchMetric.impressions) >= 100)
    ).subquery()

    # Aggregate for new half
    new_half_subq = (
        select(
            SeoSearchMetric.query,
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ).label("avg_position"),
        ).where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= new_start,
            SeoSearchMetric.date <= new_end,
        )
        .group_by(SeoSearchMetric.query)
    ).subquery()

    # Aggregate for old half
    old_half_subq = (
        select(
            SeoSearchMetric.query,
            (
                func.sum(SeoSearchMetric.position * SeoSearchMetric.impressions)
                / func.sum(SeoSearchMetric.impressions)
            ).label("avg_position"),
        ).where(
            SeoSearchMetric.tenant_id == tenant_id,
            SeoSearchMetric.date >= old_start,
            SeoSearchMetric.date <= old_end,
        )
        .group_by(SeoSearchMetric.query)
    ).subquery()

    movers_rows = db.execute(
        select(
            qualifying_subq.c.query,
            old_half_subq.c.avg_position.label("old_pos"),
            new_half_subq.c.avg_position.label("new_pos"),
        )
        .join(old_half_subq, qualifying_subq.c.query == old_half_subq.c.query)
        .join(new_half_subq, qualifying_subq.c.query == new_half_subq.c.query)
    ).mappings().all()

    for row in movers_rows:
        query = str(row["query"])
        old_pos = float(row["old_pos"])
        new_pos = float(row["new_pos"])
        # Positive delta = position number went up = rank worsened
        # Negative delta = position number went down = rank improved
        delta = old_pos - new_pos  # positive means improved (lower position number)

        if abs(delta) < 3.0:
            continue

        if delta > 0:
            # Improved
            opportunities.append({
                "type": "top_movers",
                "severity": "info",
                "title": f"'{query}' {delta:.1f} pozisyon yükseldi!",
                "body": (
                    f"Bu sorgu için sıralamanız iyileşti ({old_pos:.1f} → {new_pos:.1f}). "
                    f"Momentum'u korumak için içeriği güncel tutun."
                ),
                "data": {
                    "query": query,
                    "old_position": old_pos,
                    "new_position": new_pos,
                    "delta": delta,
                },
            })
        else:
            # Worsened
            drop = abs(delta)
            opportunities.append({
                "type": "top_movers",
                "severity": "warning",
                "title": f"'{query}' {drop:.1f} pozisyon düştü",
                "body": (
                    f"Bu sorgunun sıralaması geriledi ({old_pos:.1f} → {new_pos:.1f}). "
                    f"Rakip içeriklerini inceleyip sayfanızı güncelleyin."
                ),
                "data": {
                    "query": query,
                    "old_position": old_pos,
                    "new_position": new_pos,
                    "delta": delta,
                },
            })

    # Sort: critical → warning → info
    opportunities.sort(key=lambda o: _SEVERITY_ORDER.get(o["severity"], 99))

    return opportunities


# ── Insight emission ──────────────────────────────────────────────────────────


def _seo_insight_exists(
    db: Session,
    tenant_id: uuid.UUID,
    category: str,
    period_start: date,
    period_end: date,
) -> bool:
    """Return True if an open SEO insight with matching fields already exists."""
    stmt = select(Insight.id).where(
        Insight.tenant_id == tenant_id,
        Insight.category == category,
        Insight.metric == "organic_search",
        Insight.channel == "organic_search",
        Insight.period_start == period_start,
        Insight.period_end == period_end,
        Insight.status.in_(["new", "seen"]),
    )
    return db.scalar(stmt) is not None


def emit_seo_insights(
    db: Session,
    tenant_id: uuid.UUID,
    period_days: int = 30,
) -> dict[str, int]:
    """Compute SEO opportunities and persist them as Insight rows.

    Reads opportunities from :func:`get_opportunities`, deduplicates against
    existing open insights, and writes new rows.  Returns counts by severity.

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    tenant_id:
        Tenant UUID — all queries and inserts are scoped to this value.
    period_days:
        Period length passed through to :func:`get_opportunities`.

    Returns
    -------
    dict with keys: ``new_info``, ``new_warning``, ``new_critical``, ``skipped``.
    """
    today = date.today()
    period_end = today
    period_start = today - timedelta(days=period_days - 1)

    opportunities = get_opportunities(db, tenant_id, period_days)

    counts: dict[str, int] = {
        "new_info": 0,
        "new_warning": 0,
        "new_critical": 0,
        "skipped": 0,
    }

    for opp in opportunities:
        category = "seo_" + opp["type"]

        if _seo_insight_exists(db, tenant_id, category, period_start, period_end):
            counts["skipped"] += 1
            continue

        severity = opp["severity"]
        score = _SEVERITY_SCORE.get(severity, 30.0)

        insight = Insight(
            tenant_id=tenant_id,
            category=category,
            severity=severity,
            title=opp["title"],
            body=opp["body"],
            metric="organic_search",
            channel="organic_search",
            period_start=period_start,
            period_end=period_end,
            status="new",
            score=score,
            data=opp["data"],
        )
        db.add(insight)

        severity_key = f"new_{severity}"
        if severity_key in counts:
            counts[severity_key] += 1
        else:
            counts["new_info"] += 1

    db.flush()
    logger.info("[seo] emit_seo_insights done for tenant=%s: %s", tenant_id, counts)
    return counts


# ── GSC ingestion helper ──────────────────────────────────────────────────────


def store_gsc_rows(
    db: Session,
    tenant_id: uuid.UUID,
    rows: list[dict],
) -> int:
    """Upsert a list of GSC search analytics rows into seo_search_metrics.

    Each row must contain: date (str "YYYY-MM-DD"), query, page, clicks,
    impressions, ctr, position. Optional: device, country.

    Uses select-then-update/insert to stay dialect-agnostic (Postgres + SQLite).

    Returns the count of rows inserted or updated.
    """
    from sqlalchemy import and_

    written = 0
    for row in rows:
        raw_date = row.get("date")
        if isinstance(raw_date, str):
            raw_date = date.fromisoformat(raw_date)
        elif raw_date is None:
            continue  # skip rows without a date

        query_str = str(row.get("query") or "")
        page_str = str(row.get("page") or "")
        clicks = int(row.get("clicks") or 0)
        impressions = int(row.get("impressions") or 0)
        ctr = float(row.get("ctr") or 0.0)
        position = float(row.get("position") or 0.0)
        device = row.get("device") or None
        country = row.get("country") or None
        _skip = {"date", "query", "page", "clicks", "impressions", "ctr", "position", "device", "country"}
        extra = {k: v for k, v in row.items() if k not in _skip}

        existing = db.scalar(
            select(SeoSearchMetric).where(
                and_(
                    SeoSearchMetric.tenant_id == tenant_id,
                    SeoSearchMetric.date == raw_date,
                    SeoSearchMetric.query == query_str,
                    SeoSearchMetric.page == page_str,
                    SeoSearchMetric.device == device,
                    SeoSearchMetric.country == country,
                )
            )
        )

        if existing is not None:
            existing.clicks = clicks
            existing.impressions = impressions
            existing.ctr = ctr
            existing.position = position
            existing.extra = extra
        else:
            db.add(SeoSearchMetric(
                tenant_id=tenant_id,
                date=raw_date,
                query=query_str,
                page=page_str,
                clicks=clicks,
                impressions=impressions,
                ctr=ctr,
                position=position,
                device=device,
                country=country,
                extra=extra,
            ))
        written += 1

    db.flush()
    logger.info("[seo] store_gsc_rows tenant=%s wrote=%d", tenant_id, written)
    return written
