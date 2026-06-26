"""Cross-channel Budget Optimizer — READ-ONLY reallocation suggestions.

Design overview
---------------
This service answers the question: "Given how our budget is currently spread
across channels, where should we move money to maximise conversion value?"

Heuristic
---------
1. Aggregate each channel's spend, conversions, and conversion_value for the
   requested date range.
2. Compute ROAS per channel using the shared metric layer rule
   (conversion_value / spend, 0 when spend == 0).
3. Rank channels by ROAS descending.  Channels with ROAS == 0 (no spend or
   no conversion value) are ranked last.
4. Identify "donor" channels (lowest ROAS) and "recipient" channels (highest
   ROAS).  A move is only proposed when the ROAS gap exceeds a minimum
   threshold (_MIN_ROAS_GAP_FOR_SUGGESTION) to avoid noise from nearly-equal
   channels.
5. Cap the total reallocation at ``max_shift_pct`` × total_spend so no single
   optimization recommendation triggers a radical budget upheaval.  Each donor
   can surrender at most that same fraction of *its own* spend, capped again
   to the global budget.
6. Project the impact of each dollar moved using the recipient channel's
   *current average ROAS as a marginal rate*.

Projection method
-----------------
    projected_conversion_value_delta = amount_moved × recipient_roas
    projected_conversion_delta       = amount_moved × (recipient_conversions
                                                        / recipient_spend)
                                       when recipient_spend > 0, else 0

This is a FIRST-ORDER (linear) estimate.  It assumes the additional budget
earns the same ROAS as the existing budget.  In practice:

    * Advertising efficiency degrades with scale (diminishing returns /
      auction pressure / audience saturation).  The real uplift will be
      smaller than projected, especially for large shifts.
    * The estimate ignores seasonality, creative fatigue, and bid dynamics.
    * The projection should be treated as an upper-bound directional signal,
      not a precise forecast.

This caveat is surfaced explicitly in every suggestion dict (``caveat`` key)
and in the summary returned by ``suggest_reallocation``.

Tenant isolation
----------------
Every query filters by tenant_id.  No cross-tenant data is ever returned.

Read-only
---------
This service issues only SELECT queries.  No writes, no mutations, no
side-effects.  Execution of any reallocation is strictly out of scope.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.services.metrics import roas as _roas

# ── Constants ─────────────────────────────────────────────────────────────────

# Do not suggest moving budget between channels whose ROAS values are within
# this absolute threshold of each other.  Below this gap the difference is
# likely noise rather than a real efficiency signal.
_MIN_ROAS_GAP_FOR_SUGGESTION = Decimal("0.5")

# The caveat text surfaced in every response (Turkish UI, English code comments)
_CAVEAT_TR = (
    "Bu projeksiyon, mevcut ROAS'ın sabit kalacağını varsayan birinci-dereceden "
    "(doğrusal) bir tahmindir. Gerçekte reklam verimliliği ölçekle azalır "
    "(azalan getiri, açık artırma baskısı, kitle doygunluğu). "
    "Önerilen taşıma miktarı büyüdükçe gerçek kazanım bu tahminin altında kalacaktır. "
    "Bu öneri yön gösterici bir sinyaldir; kesin bir tahmin değildir."
)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, or None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


class _ChannelAgg(NamedTuple):
    """Internal aggregation row for one channel."""

    channel: str
    spend: Decimal
    conversions: Decimal
    conversion_value: Decimal
    roas: Decimal
    share_of_spend: Decimal  # fraction of total spend, 0.0–1.0


def _query_channel_aggregates(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> list[_ChannelAgg]:
    """Run a single aggregation query grouped by channel and return typed rows.

    Spend uses ``cost_base_ccy`` when non-zero; falls back to ``cost_raw``
    (the ``effective_spend`` rule from the metric layer, applied via COALESCE
    at SQL level to match what the dashboard does).

    Channels with zero spend are excluded — they cannot be donors or recipients
    in any meaningful budget reallocation.
    """
    rows = db.execute(
        select(
            DimChannel.key.label("channel_key"),
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
        .group_by(DimChannel.key)
        .order_by(DimChannel.key)
    ).mappings().all()

    total_spend = sum(_d(r["spend"]) for r in rows)

    aggs: list[_ChannelAgg] = []
    for row in rows:
        spend = _d(row["spend"])
        if spend == Decimal(0):
            # Exclude zero-spend channels — no allocation to shift from or to.
            continue
        conversions = _d(row["conversions"])
        conv_value = _d(row["conversion_value"])
        channel_roas = _roas(conv_value, spend)
        share = spend / total_spend if total_spend > Decimal(0) else Decimal(0)
        aggs.append(
            _ChannelAgg(
                channel=str(row["channel_key"]),
                spend=spend,
                conversions=conversions,
                conversion_value=conv_value,
                roas=channel_roas,
                share_of_spend=share,
            )
        )

    return aggs


# ── Public service functions ──────────────────────────────────────────────────


def current_allocation(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Return the current per-channel spend allocation for the date range.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries issued).
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    date_from:
        Inclusive start of the date range.
    date_to:
        Inclusive end of the date range.

    Returns
    -------
    list of dicts, one per channel that had spend > 0 in the range, with keys:
        channel           : str   — DimChannel.key
        spend             : float — total spend (base currency)
        conversions       : float — total conversions
        conversion_value  : float — total conversion value
        roas              : float — conversion_value / spend (0 when spend == 0)
        share_of_spend    : float — this channel's spend as a fraction of total
                                    (0.0 – 1.0)

    All monetary/count values are returned as float at the API edge; Decimal is
    used internally throughout to preserve precision.
    """
    aggs = _query_channel_aggregates(db, tenant_id, date_from, date_to)
    return [
        {
            "channel": agg.channel,
            "spend": float(agg.spend),
            "conversions": float(agg.conversions),
            "conversion_value": float(agg.conversion_value),
            "roas": float(agg.roas),
            "share_of_spend": float(agg.share_of_spend),
        }
        for agg in aggs
    ]


def suggest_reallocation(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    max_shift_pct: float = 0.20,
) -> dict:
    """Recommend a budget reallocation from low-efficiency to high-efficiency channels.

    Heuristic (see module docstring for full rationale)
    ---------------------------------------------------
    1. Rank channels by ROAS descending.
    2. The bottom half (by ROAS) are donor candidates; the top half are recipients.
       With only two channels, the lower-ROAS one is the donor and the higher-ROAS
       one is the recipient.
    3. A suggestion is only generated when the ROAS gap exceeds
       ``_MIN_ROAS_GAP_FOR_SUGGESTION`` (currently 0.5 ROAS points).
    4. The total budget shifted is capped at ``max_shift_pct × total_spend``.
       Each donor can contribute at most ``max_shift_pct × donor_spend``.
    5. Each recipient receives the amount freed by their paired donor (or the
       total available amount if there is one recipient for multiple donors).

    Projection
    ----------
    For each move of ``amount`` from a donor to a recipient channel:
        projected_conversion_value_delta = amount × recipient_roas
        projected_conversion_delta       = amount × (recipient_conversions
                                                      / recipient_spend)

    This uses the recipient's *current average ROAS* as a proxy for its marginal
    ROAS — a first-order linear estimate.  See module docstring and the ``caveat``
    field for the important diminishing-returns caveat.

    Parameters
    ----------
    db:
        SQLAlchemy Session.
    tenant_id:
        Tenant UUID.
    date_from:
        Inclusive start date.
    date_to:
        Inclusive end date.
    max_shift_pct:
        Maximum fraction of total spend to reallocate (default 0.20 = 20%).
        Clamped to [0, 1].

    Returns
    -------
    dict with keys:
        suggestions : list of suggestion dicts, each with:
            from_channel                     : str
            to_channel                       : str
            amount                           : float  (in base currency)
            from_roas                        : float
            to_roas                          : float
            projected_conversion_value_delta : float
            projected_conversion_delta       : float
            rationale                        : str    (Turkish)
            caveat                           : str    (Turkish)
        summary : dict with:
            total_shift              : float  (total budget moved)
            projected_total_uplift   : float  (sum of conversion_value deltas)
            projected_conversion_uplift : float
            channels_evaluated       : int
            suggestions_count        : int
            caveat                   : str    (Turkish — identical to per-suggestion)
        caveat  : str  (top-level repetition for caller convenience)
    """
    max_shift_pct = max(0.0, min(1.0, max_shift_pct))
    shift_pct = Decimal(str(max_shift_pct))

    aggs = _query_channel_aggregates(db, tenant_id, date_from, date_to)

    if len(aggs) < 2:
        # Cannot suggest a cross-channel move with fewer than 2 channels.
        return {
            "suggestions": [],
            "summary": {
                "total_shift": 0.0,
                "projected_total_uplift": 0.0,
                "projected_conversion_uplift": 0.0,
                "channels_evaluated": len(aggs),
                "suggestions_count": 0,
                "caveat": _CAVEAT_TR,
            },
            "caveat": _CAVEAT_TR,
        }

    total_spend = sum(a.spend for a in aggs)
    # Hard cap on total dollars that can be moved across all suggestions.
    max_total_shift = total_spend * shift_pct

    # Rank by ROAS descending.  Equal-ROAS channels get a secondary sort by
    # channel key (alphabetical) for determinism.
    ranked = sorted(aggs, key=lambda a: (a.roas, a.channel), reverse=True)

    # Split into recipients (top half by ROAS) and donors (bottom half).
    # With an odd number of channels the middle one is excluded from both roles.
    n = len(ranked)
    half = n // 2
    recipients = ranked[:half]    # highest ROAS — receive budget
    donors = ranked[n - half:]    # lowest ROAS  — give budget; reversed below

    # Donors ordered worst-first so the worst performer donates first.
    donors = list(reversed(donors))

    suggestions: list[dict] = []
    budget_shifted = Decimal(0)

    for donor in donors:
        if budget_shifted >= max_total_shift:
            break

        # Best available recipient at this point (highest ROAS).
        # We always direct to the single best recipient for clarity.
        recipient = recipients[0]

        roas_gap = recipient.roas - donor.roas
        if roas_gap < _MIN_ROAS_GAP_FOR_SUGGESTION:
            # Gap is negligible — skip this pair to avoid noise suggestions.
            continue

        # How much this donor can give: up to max_shift_pct of its own spend,
        # further capped by the remaining global budget.
        donor_max = donor.spend * shift_pct
        remaining_global = max_total_shift - budget_shifted
        amount = min(donor_max, remaining_global)

        if amount <= Decimal(0):
            break

        # First-order projection using recipient's current average ROAS.
        # CAVEAT: this assumes linearity — real marginal ROAS will be lower
        # as the channel scales up (diminishing returns, auction pressure).
        projected_cv_delta = amount * recipient.roas
        if recipient.spend > Decimal(0):
            conv_rate = recipient.conversions / recipient.spend
            projected_conv_delta = amount * conv_rate
        else:
            projected_conv_delta = Decimal(0)

        rationale_tr = (
            f"'{donor.channel}' kanalının ROAS değeri {float(donor.roas):.2f}x, "
            f"'{recipient.channel}' kanalının ise {float(recipient.roas):.2f}x. "
            f"Bu bütçenin bir kısmını ({float(amount):.2f}) yüksek verimli kanala "
            f"taşımak tahminen {float(projected_cv_delta):.2f} tutarında ek dönüşüm "
            f"değeri kazandırabilir."
        )

        suggestions.append(
            {
                "from_channel": donor.channel,
                "to_channel": recipient.channel,
                "amount": float(amount),
                "from_roas": float(donor.roas),
                "to_roas": float(recipient.roas),
                "projected_conversion_value_delta": float(projected_cv_delta),
                "projected_conversion_delta": float(projected_conv_delta),
                "rationale": rationale_tr,
                "caveat": _CAVEAT_TR,
            }
        )
        budget_shifted += amount

    total_cv_uplift = sum(Decimal(str(s["projected_conversion_value_delta"])) for s in suggestions)
    total_conv_uplift = sum(Decimal(str(s["projected_conversion_delta"])) for s in suggestions)

    return {
        "suggestions": suggestions,
        "summary": {
            "total_shift": float(budget_shifted),
            "projected_total_uplift": float(total_cv_uplift),
            "projected_conversion_uplift": float(total_conv_uplift),
            "channels_evaluated": len(aggs),
            "suggestions_count": len(suggestions),
            "caveat": _CAVEAT_TR,
        },
        "caveat": _CAVEAT_TR,
    }
