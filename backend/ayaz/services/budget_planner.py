"""Aylık Bütçe Planlayıcısı — M12 allocation algorithm.

Architecture
------------
The public entry point ``allocate_budget`` pulls historical performance data
from the warehouse and delegates all numerical work to pure helpers that take
plain Python dicts.  This separation means:

* The DB-read path can be tested in integration tests with a seeded SQLite DB.
* The allocation math (``compute_allocation``, ``_compute_channel_weights``,
  ``_apply_guardrails``, ``_build_campaign_allocations``) can be unit-tested
  by passing hand-crafted ``channel_metrics`` dicts — no database needed.

Algorithm overview
------------------
1. Aggregate per-channel: spend, conversions, conversion_value, clicks,
   impressions over the lookback window.  For each channel also aggregate
   per-campaign metrics (same window) carrying the channel key + label.
2. Derive scalar KPIs per channel:
   - roas = conversion_value / spend  (0 if spend == 0)
   - cpa  = spend / conversions       (0 if conversions == 0)
   - historical_share = channel_spend / total_spend
3. Compute a weight per channel based on the objective:
   - balanced:             weight = historical_share × (0.5 + 0.5 × roas_norm)
   - maximize_roas:        weight = historical_share × (roas + 0.01)
   - maximize_conversions: weight = historical_share × (1 / (cpa + 1))
4. Normalise weights → raw_share.  Apply guardrails:
   - Floor: every channel that had historical spend gets ≥ 5 % (0.05).
   - Cap:   no channel receives > 60 % (0.60).
   Re-normalise after clamping.
5. Distribute total_budget by recommended_share.
6. Project per channel: expected_conversions, expected_revenue, expected_roas.
7. For each channel split its budget across campaigns (same weighting).
   Top 8 campaigns are returned individually; the rest are folded into
   "Diğer kampanyalar".
8. Plan-level projection = sums of channel projections.
9. Notes list in Turkish explaining applied logic.

Edge cases
----------
* No historical spend → even split across available channels.
* Division by zero in KPI derivation → return 0 (never raise).
* No channels in the warehouse → return empty platforms list with a note.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Constants ─────────────────────────────────────────────────────────────────

_FLOOR = 0.05   # each active channel gets at least 5 %
_CAP = 0.60     # no channel gets more than 60 %
_MAX_CAMPAIGNS = 8  # top N campaigns shown individually


# ── Pure helper: derive KPIs for a single channel row ─────────────────────────


def _kpis(spend: float, conversions: float, conversion_value: float) -> dict:
    """Derive roas and cpa from raw aggregates (0 on divide-by-zero)."""
    roas = conversion_value / spend if spend > 0 else 0.0
    cpa = spend / conversions if conversions > 0 else 0.0
    return {"roas": roas, "cpa": cpa}


# ── Pure helper: compute per-channel weights by objective ─────────────────────


def _compute_channel_weights(
    channel_metrics: dict[str, dict],
    objective: str,
) -> dict[str, float]:
    """Compute an un-normalised weight for each channel.

    Parameters
    ----------
    channel_metrics:
        Mapping of channel_key → {spend, conversions, conversion_value, clicks,
        impressions, roas, cpa, historical_share}.
    objective:
        "balanced" | "maximize_roas" | "maximize_conversions"

    Returns
    -------
    Mapping of channel_key → raw weight (always >= 0).
    """
    if objective == "maximize_roas":
        return {
            ch: m["historical_share"] * (m["roas"] + 0.01)
            for ch, m in channel_metrics.items()
        }

    if objective == "maximize_conversions":
        return {
            ch: m["historical_share"] * (1.0 / (m["cpa"] + 1.0))
            for ch, m in channel_metrics.items()
        }

    # "balanced" (default)
    max_roas = max((m["roas"] for m in channel_metrics.values()), default=0.0)
    weights: dict[str, float] = {}
    for ch, m in channel_metrics.items():
        roas_norm = m["roas"] / max_roas if max_roas > 0 else 0.0
        weights[ch] = m["historical_share"] * (0.5 + 0.5 * roas_norm)
    return weights


# ── Pure helper: apply floor/cap guardrails and re-normalise ──────────────────


def _apply_guardrails(
    raw_shares: dict[str, float],
    active_channels: set[str],
) -> dict[str, float]:
    """Apply floor (5 %) and cap (60 %) guardrails, then re-normalise.

    Parameters
    ----------
    raw_shares:
        Mapping channel_key → share (pre-normalised, 0–1).
    active_channels:
        Set of channel keys that had historical spend; only these receive the
        floor.  Channels with no spend are not floored (they would not appear
        in raw_shares anyway if the caller builds it correctly).

    Returns
    -------
    Normalised shares dict (values sum to 1.0 ± floating-point rounding).

    Implementation note
    -------------------
    A simple two-pass clamp + re-normalise does not guarantee that the cap
    holds after re-normalisation (the cap channel's share grows again when the
    remaining channels sum to less than 1.0).  We therefore use an iterative
    approach that pegs the capped channels first and then re-distributes the
    remaining budget only among uncapped channels until convergence.
    """
    if not raw_shares:
        return {}

    shares = dict(raw_shares)

    # Step 1: enforce floor on active channels (raise any below _FLOOR)
    for ch in list(shares):
        if ch in active_channels and shares[ch] < _FLOOR:
            shares[ch] = _FLOOR

    # Step 2: iterative cap — channels that hit the cap are pegged; the
    # residual (1 - sum_of_pegged) is re-distributed among the free channels.
    # We iterate until no new channel is capped.
    MAX_ITER = 20
    for _ in range(MAX_ITER):
        capped: dict[str, float] = {}
        free: dict[str, float] = {}
        for ch, v in shares.items():
            if v >= _CAP:
                capped[ch] = _CAP
            else:
                free[ch] = v

        if not capped:
            break  # nothing capped → done

        residual = 1.0 - sum(capped.values())
        if residual <= 0 or not free:
            # Edge case: all channels capped; distribute equally among all
            n = len(shares)
            shares = {ch: 1.0 / n for ch in shares}
            break

        # Re-scale free channels to fill the residual
        free_total = sum(free.values())
        if free_total == 0:
            # Free channels all have zero share; split residual equally
            n_free = len(free)
            free = {ch: residual / n_free for ch in free}
        else:
            free = {ch: v / free_total * residual for ch, v in free.items()}

        # Re-apply floor to free channels that fell below minimum
        for ch in list(free):
            if ch in active_channels and free[ch] < _FLOOR:
                free[ch] = _FLOOR

        shares = {**capped, **free}

        # Check convergence: if no free channel exceeds cap, we're done
        if all(v <= _CAP + 1e-9 for v in shares.values()):
            break

    # Final normalise to absorb any floating-point drift
    total = sum(shares.values())
    if total == 0:
        n = len(shares)
        return {ch: 1.0 / n for ch in shares}

    return {ch: v / total for ch, v in shares.items()}


# ── Pure helper: allocate one channel's budget across its campaigns ───────────


def _build_campaign_allocations(
    campaign_metrics: dict[str, dict],
    channel_budget: float,
    objective: str,
) -> list[dict]:
    """Allocate ``channel_budget`` across campaigns, return top-8 + remainder.

    Parameters
    ----------
    campaign_metrics:
        Mapping campaign_id_str → {name, spend, conversions, conversion_value,
        clicks, impressions, roas, cpa, historical_share}.
    channel_budget:
        Total TRY (or configured currency) allocated to this channel.
    objective:
        Allocation objective (same as parent call).

    Returns
    -------
    List of campaign dicts ordered by recommended_budget descending.
    The tail is folded into a "Diğer kampanyalar" bucket when > _MAX_CAMPAIGNS.
    """
    if not campaign_metrics:
        return []

    # Compute campaign weights using same objective logic
    weights = _compute_channel_weights(campaign_metrics, objective)
    total_w = sum(weights.values())

    if total_w == 0:
        n = len(campaign_metrics)
        shares: dict[str, float] = {k: 1.0 / n for k in campaign_metrics}
    else:
        shares = {k: w / total_w for k, w in weights.items()}

    campaigns: list[dict] = []
    for camp_id, m in campaign_metrics.items():
        share = shares.get(camp_id, 0.0)
        rec_budget = round(share * channel_budget, 2)
        camps_roas = m.get("roas", 0.0)
        camps_cpa = m.get("cpa", 0.0)
        expected_conv = round(rec_budget / camps_cpa, 4) if camps_cpa > 0 else 0.0
        expected_rev = round(rec_budget * camps_roas, 2)
        campaigns.append(
            {
                "campaign_id": camp_id,
                "name": m.get("name", m.get("label", "—")),
                "recommended_budget": rec_budget,
                "recommended_share": round(share * 100, 1),
                "roas": round(camps_roas, 4),
                "expected_conversions": expected_conv,
                "expected_revenue": expected_rev,
            }
        )

    # Sort by recommended_budget descending
    campaigns.sort(key=lambda c: c["recommended_budget"], reverse=True)

    if len(campaigns) <= _MAX_CAMPAIGNS:
        return campaigns

    top = campaigns[:_MAX_CAMPAIGNS]
    rest = campaigns[_MAX_CAMPAIGNS:]
    remainder_budget = round(sum(c["recommended_budget"] for c in rest), 2)
    remainder_conv = round(sum(c["expected_conversions"] for c in rest), 4)
    remainder_rev = round(sum(c["expected_revenue"] for c in rest), 2)
    remainder_share = round(sum(c["recommended_share"] for c in rest), 1)
    top.append(
        {
            "campaign_id": None,
            "name": "Diğer kampanyalar",
            "recommended_budget": remainder_budget,
            "recommended_share": remainder_share,
            "roas": 0.0,
            "expected_conversions": remainder_conv,
            "expected_revenue": remainder_rev,
        }
    )
    return top


# ── Pure public function: compute allocation from a metrics dict ───────────────


def compute_allocation(
    channel_metrics: dict[str, dict],
    total_budget: float,
    objective: str = "balanced",
    *,
    campaign_metrics: dict[str, dict] | None = None,
) -> list[dict]:
    """Allocate ``total_budget`` across channels (and optionally campaigns).

    This is a **pure function** — it does not touch the database.  All inputs
    are plain Python dicts so it can be called directly from unit tests.

    Parameters
    ----------
    channel_metrics:
        ``{channel_key: {label, spend, conversions, conversion_value,
        clicks, impressions}}``.
        All numeric values should be ``float``.
    total_budget:
        The total budget (in the plan's currency) to distribute.
    objective:
        "balanced" | "maximize_roas" | "maximize_conversions"
    campaign_metrics:
        Optional ``{campaign_id_str: {name, channel_key, spend, conversions,
        conversion_value, clicks, impressions}}``.
        When provided, campaigns are split within each channel.

    Returns
    -------
    List of channel allocation dicts.  Each dict has the shape described in
    the module docstring ``platforms`` field.
    """
    if not channel_metrics:
        return []

    # ── Step 1: derive KPIs and historical share per channel ──────────────────
    total_spend = sum(m.get("spend", 0.0) for m in channel_metrics.values())
    has_spend = total_spend > 0

    enriched: dict[str, dict] = {}
    for ch, m in channel_metrics.items():
        spend = float(m.get("spend", 0.0))
        conversions = float(m.get("conversions", 0.0))
        conv_value = float(m.get("conversion_value", 0.0))
        kpi = _kpis(spend, conversions, conv_value)
        hist_share = spend / total_spend if has_spend else 1.0 / len(channel_metrics)
        enriched[ch] = {
            "label": m.get("label", ch),
            "spend": spend,
            "conversions": conversions,
            "conversion_value": conv_value,
            "clicks": float(m.get("clicks", 0.0)),
            "impressions": float(m.get("impressions", 0.0)),
            "roas": kpi["roas"],
            "cpa": kpi["cpa"],
            "historical_share": hist_share,
        }

    # ── Step 2: compute weights by objective ──────────────────────────────────
    weights = _compute_channel_weights(enriched, objective)

    # ── Step 3: raw share → normalise ─────────────────────────────────────────
    total_w = sum(weights.values())
    if total_w == 0:
        n = len(enriched)
        raw_shares: dict[str, float] = {ch: 1.0 / n for ch in enriched}
    else:
        raw_shares = {ch: w / total_w for ch, w in weights.items()}

    # ── Step 4: apply guardrails ──────────────────────────────────────────────
    active_channels = {ch for ch, m in enriched.items() if m["spend"] > 0}
    # If no channels had spend, treat all as "active" for even-split guardrails
    if not active_channels:
        active_channels = set(enriched)

    final_shares = _apply_guardrails(raw_shares, active_channels)

    # ── Step 5-6: build platform rows with projections ────────────────────────
    platforms: list[dict] = []
    for ch, m in enriched.items():
        share = final_shares.get(ch, 0.0)
        rec_budget = round(share * total_budget, 2)
        hist_share_pct = round(m["historical_share"] * 100, 1)
        rec_share_pct = round(share * 100, 1)
        delta_pct = round(rec_share_pct - hist_share_pct, 1)

        cpa = m["cpa"]
        roas_val = m["roas"]
        expected_conv = round(rec_budget / cpa, 4) if cpa > 0 else 0.0
        expected_rev = round(rec_budget * roas_val, 2)

        # ── Step 7: campaign-level allocations ────────────────────────────────
        camps: list[dict] = []
        if campaign_metrics:
            ch_campaigns = {
                cid: cm
                for cid, cm in campaign_metrics.items()
                if cm.get("channel_key") == ch
            }
            camps = _build_campaign_allocations(ch_campaigns, rec_budget, objective)

        platforms.append(
            {
                "channel": ch,
                "label": m["label"],
                "historical_spend": round(m["spend"], 2),
                "historical_share": hist_share_pct,
                "roas": round(roas_val, 4),
                "cpa": round(cpa, 4),
                "recommended_budget": rec_budget,
                "recommended_share": rec_share_pct,
                "delta_pct": delta_pct,
                "expected_conversions": expected_conv,
                "expected_revenue": expected_rev,
                "expected_roas": round(roas_val, 4),
                "campaigns": camps,
            }
        )

    # Sort by recommended_budget descending for consistent output
    platforms.sort(key=lambda p: p["recommended_budget"], reverse=True)
    return platforms


# ── DB-read helpers ────────────────────────────────────────────────────────────


def _d(v: Any) -> float:
    """Coerce a DB-returned value (Decimal, int, float, or None) to float."""
    if v is None:
        return 0.0
    return float(v)


def _fetch_channel_metrics(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Aggregate per-channel metrics from the warehouse for the given window.

    Returns ``{channel_key: {label, spend, conversions, conversion_value,
    clicks, impressions}}``.

    Filters strictly by ``FactDailyMetrics.tenant_id`` to enforce tenant
    isolation — no cross-tenant data can leak through this function.
    """
    from sqlalchemy import func, select
    from ayaz.models.analytics import DimChannel, FactDailyMetrics

    rows = db.execute(
        select(
            DimChannel.key.label("channel_key"),
            DimChannel.label.label("channel_label"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(DimChannel.key, DimChannel.label)
    ).mappings().all()

    return {
        str(row["channel_key"]): {
            "label": str(row["channel_label"]),
            "impressions": _d(row["impressions"]),
            "clicks": _d(row["clicks"]),
            "spend": _d(row["spend"]),
            "conversions": _d(row["conversions"]),
            "conversion_value": _d(row["conversion_value"]),
        }
        for row in rows
    }


def _fetch_campaign_metrics(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Aggregate per-campaign metrics from the warehouse for the given window.

    Returns ``{campaign_id_str: {name, channel_key, channel_label, spend,
    conversions, conversion_value, clicks, impressions}}``.

    Each campaign row also carries ``channel_key`` and ``channel_label`` so
    ``compute_allocation`` can split campaigns within their parent channel.
    """
    from sqlalchemy import func, select
    from ayaz.models.analytics import DimCampaign, DimChannel, FactDailyMetrics

    rows = db.execute(
        select(
            DimCampaign.id.label("campaign_id"),
            DimCampaign.name.label("campaign_name"),
            DimChannel.key.label("channel_key"),
            DimChannel.label.label("channel_label"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .join(DimChannel, FactDailyMetrics.channel_id == DimChannel.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(
            DimCampaign.id,
            DimCampaign.name,
            DimChannel.key,
            DimChannel.label,
        )
    ).mappings().all()

    result: dict[str, dict] = {}
    for row in rows:
        camp_id = str(row["campaign_id"])
        result[camp_id] = {
            "name": str(row["campaign_name"]),
            "channel_key": str(row["channel_key"]),
            "channel_label": str(row["channel_label"]),
            "label": str(row["campaign_name"]),
            "impressions": _d(row["impressions"]),
            "clicks": _d(row["clicks"]),
            "spend": _d(row["spend"]),
            "conversions": _d(row["conversions"]),
            "conversion_value": _d(row["conversion_value"]),
        }
    return result


# ── Public entry point ────────────────────────────────────────────────────────


def allocate_budget(
    db: "Session",
    tenant_id: uuid.UUID,
    *,
    total_budget: float,
    objective: str = "balanced",
    lookback_days: int = 90,
    currency: str = "TRY",
    as_of: date | None = None,
) -> dict:
    """Compute a monthly budget allocation for the given tenant.

    This is the main public entry point that orchestrates DB reads and
    delegates all numerical work to the pure helpers above.

    Parameters
    ----------
    db:
        SQLAlchemy session scoped to the current request.
    tenant_id:
        Tenant UUID — all warehouse queries are filtered to this tenant.
    total_budget:
        Total amount (in ``currency``) to distribute across channels.
    objective:
        Optimisation objective (see module docstring).
    lookback_days:
        Number of days of historical data to pull (default 90).
    currency:
        ISO 4217 code for the plan currency (informational; not used for FX).
    as_of:
        Reference date; defaults to today UTC.  Useful for testing.

    Returns
    -------
    dict with keys: total_budget, currency, objective, lookback_days,
    based_on, platforms, projection, notes.
    """
    today = as_of or date.today()
    date_from = today - timedelta(days=lookback_days)
    date_to = today

    # ── Pull metrics from warehouse ───────────────────────────────────────────
    channel_metrics = _fetch_channel_metrics(db, tenant_id, date_from, date_to)
    campaign_metrics = _fetch_campaign_metrics(db, tenant_id, date_from, date_to)

    notes: list[str] = []
    has_any_spend = any(m["spend"] > 0 for m in channel_metrics.values())

    if not channel_metrics:
        notes.append(
            f"Son {lookback_days} gün için kanal verisi bulunamadı. "
            "Bütçe dağılımı yapılamadı."
        )
        return {
            "total_budget": float(total_budget),
            "currency": currency,
            "objective": objective,
            "lookback_days": lookback_days,
            "based_on": {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
            },
            "platforms": [],
            "projection": {
                "expected_conversions": 0.0,
                "expected_revenue": 0.0,
                "expected_roas": 0.0,
            },
            "notes": notes,
        }

    if not has_any_spend:
        notes.append(
            f"Son {lookback_days} günde hiç harcama verisi bulunamadı. "
            "Bütçe kanallar arasında eşit olarak dağıtıldı."
        )
    else:
        obj_label = {
            "balanced": "dengeli dağılım",
            "maximize_roas": "maksimum ROAS",
            "maximize_conversions": "maksimum dönüşüm",
        }.get(objective, objective)
        notes.append(
            f"Son {lookback_days} günün ROAS ve harcama dağılımına göre "
            f"{obj_label} hedefli dağılım hesaplandı; "
            f"her aktif kanala en az %5, en çok %60 sınırı uygulandı."
        )

    # ── Enrich campaign metrics with KPIs ─────────────────────────────────────
    for cid, cm in campaign_metrics.items():
        kpi = _kpis(cm["spend"], cm["conversions"], cm["conversion_value"])
        cm.update(kpi)
        # Build historical_share within the channel (needed by weight functions)
        channel_key = cm.get("channel_key", "")
        ch_spend = channel_metrics.get(channel_key, {}).get("spend", 0.0)
        cm["historical_share"] = (
            cm["spend"] / ch_spend if ch_spend > 0 else 0.0
        )

    # ── Run pure allocation ───────────────────────────────────────────────────
    platforms = compute_allocation(
        channel_metrics,
        float(total_budget),
        objective,
        campaign_metrics=campaign_metrics,
    )

    # ── Step 8: plan-level projection ─────────────────────────────────────────
    total_expected_conv = sum(p["expected_conversions"] for p in platforms)
    total_expected_rev = sum(p["expected_revenue"] for p in platforms)
    total_budget_f = float(total_budget)
    plan_roas = (
        round(total_expected_rev / total_budget_f, 4) if total_budget_f > 0 else 0.0
    )

    return {
        "total_budget": total_budget_f,
        "currency": currency,
        "objective": objective,
        "lookback_days": lookback_days,
        "based_on": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
        "platforms": platforms,
        "projection": {
            "expected_conversions": round(total_expected_conv, 4),
            "expected_revenue": round(total_expected_rev, 2),
            "expected_roas": plan_roas,
        },
        "notes": notes,
    }
