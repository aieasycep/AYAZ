"""Ürün / SKU segment analizi (Dalga 3 — segment derinliği).

Aggregates ``fact_product_daily`` into per-product and per-category performance
with **gross** and **return-adjusted (net) ROAS**, plus return rate — the
breakdown textile-e-commerce and omnichannel tenants asked for.

Public API
----------
build_product_segments(db, tenant_id, date_from, date_to) -> dict

Tenant isolation
----------------
Every query filters on ``tenant_id``. No cross-tenant data is reachable.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ayaz.models.analytics import DimProduct, FactProductDaily

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Derived-metric helpers (div-by-zero safe) ─────────────────────────────────


def _f(value) -> float:
    return float(value or 0)


def _roas(revenue, spend) -> float:
    spend_f = _f(spend)
    return round(_f(revenue) / spend_f, 2) if spend_f else 0.0


def _rate_pct(part, whole) -> float:
    whole_f = _f(whole)
    return round(_f(part) / whole_f * 100, 1) if whole_f else 0.0


def _metrics(gross, returned, spend, units, ret_units) -> dict:
    """Build the shared metric block for a product / category / totals row."""
    net = _f(gross) - _f(returned)
    return {
        "units_sold": int(units or 0),
        "returned_units": int(ret_units or 0),
        "gross_revenue": round(_f(gross), 2),
        "returned_revenue": round(_f(returned), 2),
        "net_revenue": round(net, 2),
        "ad_spend": round(_f(spend), 2),
        "gross_roas": _roas(gross, spend),
        "net_roas": _roas(net, spend),
        "return_rate_pct": _rate_pct(returned, gross),
    }


# ── Public API ────────────────────────────────────────────────────────────────


def build_product_segments(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict:
    """Return per-SKU and per-category performance for the tenant.

    Aggregates ``fact_product_daily`` over [date_from, date_to] (inclusive),
    grouped by product, then rolls the products up into categories and an
    account-level total.

    Returns
    -------
    dict with keys ``period``, ``currency``, ``totals``, ``categories``,
    ``products``.  Products are sorted by ad_spend desc (biggest bets first);
    categories by net_revenue desc.
    """
    rows = db.execute(
        select(
            DimProduct.id,
            DimProduct.sku,
            DimProduct.name,
            DimProduct.category,
            DimProduct.price_raw,
            func.sum(FactProductDaily.units_sold),
            func.sum(FactProductDaily.returned_units),
            func.sum(FactProductDaily.gross_revenue),
            func.sum(FactProductDaily.returned_revenue),
            func.sum(FactProductDaily.ad_spend),
        )
        .join(FactProductDaily, FactProductDaily.product_id == DimProduct.id)
        .where(
            FactProductDaily.tenant_id == tenant_id,
            FactProductDaily.date_key >= date_from,
            FactProductDaily.date_key <= date_to,
        )
        .group_by(
            DimProduct.id,
            DimProduct.sku,
            DimProduct.name,
            DimProduct.category,
            DimProduct.price_raw,
        )
    ).all()

    products: list[dict] = []
    # category_key -> accumulator of raw Decimals
    cat_acc: dict[str, dict] = {}
    tot = {
        "units": 0, "ret_units": 0,
        "gross": Decimal(0), "returned": Decimal(0), "spend": Decimal(0),
    }

    for (
        pid, sku, name, category, price,
        units, ret_units, gross, returned, spend,
    ) in rows:
        units = int(units or 0)
        ret_units = int(ret_units or 0)
        gross = gross or Decimal(0)
        returned = returned or Decimal(0)
        spend = spend or Decimal(0)

        product = {
            "product_id": str(pid),
            "sku": sku,
            "name": name,
            "category": category or "(kategorisiz)",
            "price": round(_f(price), 2),
            **_metrics(gross, returned, spend, units, ret_units),
        }
        products.append(product)

        cat_key = category or "(kategorisiz)"
        acc = cat_acc.setdefault(
            cat_key,
            {"units": 0, "ret_units": 0, "gross": Decimal(0),
             "returned": Decimal(0), "spend": Decimal(0), "count": 0},
        )
        acc["units"] += units
        acc["ret_units"] += ret_units
        acc["gross"] += gross
        acc["returned"] += returned
        acc["spend"] += spend
        acc["count"] += 1

        tot["units"] += units
        tot["ret_units"] += ret_units
        tot["gross"] += gross
        tot["returned"] += returned
        tot["spend"] += spend

    # Biggest ad bets first — that's where a return problem hurts most.
    products.sort(key=lambda p: p["ad_spend"], reverse=True)

    categories = [
        {
            "category": cat_key,
            "product_count": acc["count"],
            **_metrics(acc["gross"], acc["returned"], acc["spend"],
                       acc["units"], acc["ret_units"]),
        }
        for cat_key, acc in cat_acc.items()
    ]
    categories.sort(key=lambda c: c["net_revenue"], reverse=True)

    totals = {
        "product_count": len(products),
        **_metrics(tot["gross"], tot["returned"], tot["spend"],
                   tot["units"], tot["ret_units"]),
    }

    return {
        "period": {"date_from": str(date_from), "date_to": str(date_to)},
        "currency": "TRY",
        "totals": totals,
        "categories": categories,
        "products": products,
    }
