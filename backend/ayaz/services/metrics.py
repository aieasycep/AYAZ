"""Metric layer — derived KPI calculations over summed fact-table data.

Design decisions
----------------
* All inputs and outputs are ``Decimal`` to preserve precision end-to-end.
* **Divide-by-zero policy**: return ``Decimal("0")`` (not None) for every
  derived metric when the denominator is zero.  This makes downstream JSON
  serialisation straightforward (no null-handling) and matches the contract
  expected by the dashboard API.  The docstrings document this choice so
  callers are never surprised.
* "Spend" is defined as ``cost_base_ccy`` when it is non-zero (i.e. FX
  conversion has been applied), otherwise falls back to ``cost_raw``.  The
  helper ``effective_spend`` encodes this rule.

Metric formulas
---------------
    CTR  = clicks / impressions            (0 when impressions == 0)
    CPC  = spend  / clicks                 (0 when clicks == 0)
    CPA  = spend  / conversions            (0 when conversions == 0)
    ROAS = conversion_value / spend        (0 when spend == 0)
"""

from __future__ import annotations

from decimal import Decimal


# ── Spend helper ──────────────────────────────────────────────────────────────


def effective_spend(cost_raw: Decimal, cost_base_ccy: Decimal) -> Decimal:
    """Return the spend value to use for derived-metric calculations.

    Prefers ``cost_base_ccy`` (tenant base-currency spend after FX conversion)
    when it is non-zero; falls back to ``cost_raw`` (source-currency spend).

    Parameters
    ----------
    cost_raw:
        Spend in the source platform currency.
    cost_base_ccy:
        Spend converted to the tenant's base currency (0 until FX task runs).

    Returns
    -------
    Decimal
        The value to use as "spend" in metric calculations.
    """
    return cost_base_ccy if cost_base_ccy != Decimal(0) else cost_raw


# ── Individual derived metrics ────────────────────────────────────────────────


def ctr(impressions: Decimal, clicks: Decimal) -> Decimal:
    """Click-through rate = clicks / impressions.

    Returns ``Decimal("0")`` when ``impressions`` is zero.
    """
    if impressions == Decimal(0):
        return Decimal(0)
    return clicks / impressions


def cpc(spend: Decimal, clicks: Decimal) -> Decimal:
    """Cost per click = spend / clicks.

    Returns ``Decimal("0")`` when ``clicks`` is zero.
    """
    if clicks == Decimal(0):
        return Decimal(0)
    return spend / clicks


def cpa(spend: Decimal, conversions: Decimal) -> Decimal:
    """Cost per acquisition = spend / conversions.

    Returns ``Decimal("0")`` when ``conversions`` is zero.
    """
    if conversions == Decimal(0):
        return Decimal(0)
    return spend / conversions


def roas(conversion_value: Decimal, spend: Decimal) -> Decimal:
    """Return on ad spend = conversion_value / spend.

    Returns ``Decimal("0")`` when ``spend`` is zero.
    """
    if spend == Decimal(0):
        return Decimal(0)
    return conversion_value / spend


# ── Aggregate helper ──────────────────────────────────────────────────────────


def compute_derived_metrics(
    *,
    impressions: Decimal,
    clicks: Decimal,
    spend: Decimal,
    conversions: Decimal,
    conversion_value: Decimal,
) -> dict[str, Decimal]:
    """Compute all derived metrics from summed raw counters.

    Parameters
    ----------
    impressions:
        Total impressions (sum of fact rows).
    clicks:
        Total clicks.
    spend:
        Total spend (already in the correct currency — use ``effective_spend``
        to choose between cost_raw and cost_base_ccy before calling here).
    conversions:
        Total conversions.
    conversion_value:
        Total conversion value.

    Returns
    -------
    dict with keys: ``ctr``, ``cpc``, ``cpa``, ``roas``.
    All values are ``Decimal``.  Zero is returned (never None) for any metric
    whose denominator is zero.
    """
    return {
        "ctr": ctr(impressions, clicks),
        "cpc": cpc(spend, clicks),
        "cpa": cpa(spend, conversions),
        "roas": roas(conversion_value, spend),
    }
