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

Source-type split (ad vs analytics) — çift-sayım koruması
-----------------------------------------------------------
Reklam platformları (google_ads, meta_ads, ...) ile analitik kaynakları
(ga4, search_console) aynı fact tablosuna yazar. Kanal-üstü toplamlarda
bunları kör SUM etmek çift sayıma yol açar (GA4 dönüşümü, platformun zaten
raporladığı dönüşümün üstüne eklenir). ``split_channel_totals_by_source``,
``resolve_headline_metric`` ve ``blended_roas`` bu ayrımı ve "hangi tek
değer manşette gösterilir" çözümlemesini merkezileştirir — bkz. her
birinin docstring'i ve ``ayaz/services/channels.py::source_type``.

Top-movers helpers
------------------
``compute_top_movers`` is the single source of truth for top-movers ranking
logic, shared by the dashboard REST endpoint and the Copilot tool.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


# ── Kaynak-tipi (ad vs analytics) ayrımı ───────────────────────────────────────
#
# Google Ads/Meta Ads (ad) VE GA4/Search Console (analytics) aynı
# ``fact_daily_metrics`` tablosuna, aynı ``conversions`` /
# ``conversion_value_raw`` kolonlarına yazar. Kanal-üstü SUM() bu ikisini
# ayırt etmezse GA4'ün ölçtüğü gerçek dönüşümler, reklam platformlarının
# ZATEN kendi raporladığı (self-attributed) dönüşümlerin ÜSTÜNE eklenir —
# manşet dönüşüm 2-3× şişer ve blended ROAS yapısal olarak abartılı çıkar.
# Bu üç yardımcı, dashboard/executive/scores/attribution genelinde TEK bir
# ayrım+çözümleme mantığı sağlar.


def split_channel_totals_by_source(channel_data: dict[str, dict]) -> dict[str, Decimal]:
    """Kanal-bazlı ham toplamları kaynak tipine (``ad`` / ``analytics``) göre ayırır.

    Parameters
    ----------
    channel_data:
        ``_aggregate_by_channel_raw`` ile aynı şekilde: ``{channel_key: {
        "impressions": Decimal, "clicks": Decimal, "spend": Decimal,
        "conversions": Decimal, "conversion_value": Decimal, ...}}``.
        Fazladan anahtarlar (ör. ``"label"``) yok sayılır.

    Returns
    -------
    dict[str, Decimal] anahtarları:
        ``total_spend``, ``total_impressions``, ``total_clicks``
            Tüm kanalların ham toplamı — mevcut (fix-öncesi) davranışla
            AYNI, çünkü bunlar çift-sayım bug'ının konusu değil (analytics
            kanallarının harcaması yapısal olarak 0'dır — bkz. GA4/Search
            Console connector docstring'leri).
        ``ad_spend``, ``ad_impressions``, ``ad_clicks``,
        ``ad_conversions``, ``ad_conversion_value``
            Yalnız ``source_type(channel_key) == "ad"`` olan kanalların
            toplamı.
        ``analytics_impressions``, ``analytics_clicks``,
        ``analytics_conversions``, ``analytics_conversion_value``
            Yalnız ``source_type(channel_key) == "analytics"`` olan
            kanalların toplamı (spend hariç — analytics kanallarının
            harcaması olmaz).

    Bilinmeyen kanal anahtarları ``channels.source_type`` varsayılanı
    (``"ad"``) üzerinden sınıflandırılır — bkz. o fonksiyonun docstring'i.
    """
    from ayaz.services.channels import source_type as _source_type

    total_spend = Decimal(0)
    total_impressions = Decimal(0)
    total_clicks = Decimal(0)

    ad_spend = Decimal(0)
    ad_impressions = Decimal(0)
    ad_clicks = Decimal(0)
    ad_conversions = Decimal(0)
    ad_conversion_value = Decimal(0)

    analytics_impressions = Decimal(0)
    analytics_clicks = Decimal(0)
    analytics_conversions = Decimal(0)
    analytics_conversion_value = Decimal(0)

    for channel_key, row in channel_data.items():
        spend = row.get("spend", Decimal(0))
        impressions = row.get("impressions", Decimal(0))
        clicks = row.get("clicks", Decimal(0))
        conversions = row.get("conversions", Decimal(0))
        conversion_value = row.get("conversion_value", Decimal(0))

        total_spend += spend
        total_impressions += impressions
        total_clicks += clicks

        if _source_type(channel_key) == "analytics":
            analytics_impressions += impressions
            analytics_clicks += clicks
            analytics_conversions += conversions
            analytics_conversion_value += conversion_value
        else:  # "ad" (varsayılan — bilinmeyen kanallar da buraya düşer)
            ad_spend += spend
            ad_impressions += impressions
            ad_clicks += clicks
            ad_conversions += conversions
            ad_conversion_value += conversion_value

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "ad_spend": ad_spend,
        "ad_impressions": ad_impressions,
        "ad_clicks": ad_clicks,
        "ad_conversions": ad_conversions,
        "ad_conversion_value": ad_conversion_value,
        "analytics_impressions": analytics_impressions,
        "analytics_clicks": analytics_clicks,
        "analytics_conversions": analytics_conversions,
        "analytics_conversion_value": analytics_conversion_value,
    }


def resolve_headline_metric(analytics_value: Decimal, ad_value: Decimal) -> Decimal:
    """"Manşet" (headline) metrik değerini kaynak-doğrusu (source-of-truth) kuralıyla çözer.

    İş kuralı: analytics (GA4) verisi VARSA (sıfırdan farklıysa) o esas
    alınır — GA4 sitedeki/uygulamadaki gerçek aktiviteyi ölçer ve reklam
    platformlarının kendi-raporladığı (şişirilmiş olabilen) sayısından daha
    güvenilir kabul edilir. Analytics verisi yoksa (kaynak bağlı değil ya da
    bu dönemde tam olarak sıfır) reklam kanallarının toplamına düşülür — bu
    da mevcut (fix-öncesi, yalnız-ad) davranışla birebir aynı sonucu verir,
    yani GA4 bağlanmamış kiracılar için geriye dönük olarak sayısal bir
    değişiklik YOKTUR.
    """
    return analytics_value if analytics_value != Decimal(0) else ad_value


def blended_roas(
    *,
    ad_spend: Decimal,
    analytics_conversion_value: Decimal,
    ad_conversion_value: Decimal = Decimal(0),
) -> Decimal:
    """Blended ROAS = kaynak-doğrusu gelir ÷ YALNIZ reklam harcaması.

    Pay (gelir): ``resolve_headline_metric`` kuralı uygulanır — analytics
    (GA4) geliri sıfırdan farklıysa o kullanılır; aksi halde
    ``ad_conversion_value`` (varsayılan 0) kullanılır.

    Bu varsayılan iki farklı kullanım şeklini TEK fonksiyonda birleştirir:
      * ``ad_conversion_value`` VERİLMEZSE (attribution endpoint'i): formül
        tam olarak ``ga4_revenue / ad_spend``'e indirgenir — GA4 yoksa/
        sıfırsa sonuç dürüstçe 0'dır (fallback YOK; bu endpoint'in amacı
        "gerçek" attribution sinyalinin var olup olmadığını göstermektir).
      * ``ad_conversion_value`` VERİLİRSE (dashboard/executive manşet ROAS):
        GA4 bağlı değilken/sıfırken eski (yalnız-ad) ROAS'a düşülür — geriye
        dönük uyumluluk, mevcut kullanıcıların panelinde ROAS aniden 0
        görünmez.

    Payda: yalnız ``source_type == "ad"`` kanallarının harcaması. (Analytics
    kanallarının harcaması yapısal olarak 0'dır — ama bu fonksiyon yine de
    çağıranın açıkça ``ad_spend`` geçmesini ister; "toplam harcama" ile
    karıştırılmasın diye.)

    Sıfıra bölme: ``roas()`` yardımcısı üzerinden — ``ad_spend == 0`` ise
    ``Decimal(0)`` döner, asla exception fırlatmaz.
    """
    revenue = resolve_headline_metric(analytics_conversion_value, ad_conversion_value)
    return roas(revenue, ad_spend)


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


# ── Top-movers shared logic ────────────────────────────────────────────────────

# Supported metric names for top-movers ranking.
TOP_MOVERS_METRICS: frozenset[str] = frozenset(
    {"spend", "impressions", "clicks", "conversions", "conversion_value", "roas"}
)


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, or None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def _aggregate_by_channel_raw(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Return per-channel raw metric sums for the given period.

    Returns ``{channel_key: {"label": str, "impressions": Decimal, ...}}``.
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
                func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
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


def _aggregate_by_campaign_raw(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Return per-campaign raw metric sums for the given period.

    Returns ``{str(campaign_id): {"label": campaign_name, ...}}``.
    """
    from sqlalchemy import func, select
    from ayaz.models.analytics import DimCampaign, FactDailyMetrics

    rows = db.execute(
        select(
            DimCampaign.id.label("campaign_id"),
            DimCampaign.name.label("campaign_name"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(
                func.coalesce(FactDailyMetrics.cost_base_ccy, FactDailyMetrics.cost_raw)
            ).label("spend"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .join(DimCampaign, FactDailyMetrics.campaign_id == DimCampaign.id)
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(DimCampaign.id, DimCampaign.name)
    ).mappings().all()

    return {
        str(row["campaign_id"]): {
            "label": str(row["campaign_name"]),
            "impressions": _d(row["impressions"]),
            "clicks": _d(row["clicks"]),
            "spend": _d(row["spend"]),
            "conversions": _d(row["conversions"]),
            "conversion_value": _d(row["conversion_value"]),
        }
        for row in rows
    }


def _extract_metric_from_row(row: dict, metric: str) -> Decimal:
    """Extract the requested metric value from a raw aggregation row.

    For ``roas``, computes conversion_value / spend using the ``roas`` helper.
    For other metrics, returns the pre-summed value directly.
    """
    if metric == "roas":
        return roas(row["conversion_value"], row["spend"])
    return row[metric]


def compute_top_movers(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
    dimension: str = "channel",
    metric: str = "spend",
    limit: int = 5,
) -> dict:
    """Rank channels or campaigns by absolute metric change vs the prior period.

    The comparison period is immediately before ``date_from`` and has the same
    length as [date_from, date_to].  This mirrors the ``compare=true`` logic
    used in the dashboard summary endpoint.

    Parameters
    ----------
    db:
        SQLAlchemy session scoped to the current request.
    tenant_id:
        Tenant UUID — all queries are filtered to this tenant only.
    date_from, date_to:
        Inclusive current-period date range.
    dimension:
        ``"channel"`` or ``"campaign"``.  Controls grouping.
    metric:
        One of ``TOP_MOVERS_METRICS``.  Defaults to ``"spend"``.
    limit:
        Maximum number of movers to return (top N by absolute delta).

    Returns
    -------
    dict with keys:
        dimension, metric, date_from, date_to, previous_from, previous_to,
        movers: list of dicts each containing:
            key, label, current, previous, delta, delta_pct (float|None), direction.

    Tenant isolation
    ----------------
    All SQL queries filter by ``tenant_id``.  No cross-tenant data is possible.
    """
    if metric not in TOP_MOVERS_METRICS:
        metric = "spend"
    if dimension not in ("channel", "campaign"):
        dimension = "channel"

    # Previous period: same length, immediately before date_from.
    period_len = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_len - 1)

    _zero_row: dict = {
        "label": "",
        "impressions": Decimal(0),
        "clicks": Decimal(0),
        "spend": Decimal(0),
        "conversions": Decimal(0),
        "conversion_value": Decimal(0),
    }

    if dimension == "channel":
        curr_data = _aggregate_by_channel_raw(db, tenant_id, date_from, date_to)
        prev_data = _aggregate_by_channel_raw(db, tenant_id, prev_from, prev_to)
    else:
        curr_data = _aggregate_by_campaign_raw(db, tenant_id, date_from, date_to)
        prev_data = _aggregate_by_campaign_raw(db, tenant_id, prev_from, prev_to)

    all_keys = set(curr_data) | set(prev_data)

    movers = []
    for key in all_keys:
        curr_row = curr_data.get(key, _zero_row)
        prev_row = prev_data.get(key, _zero_row)

        label: str = curr_row["label"] or prev_row["label"]

        curr_val: Decimal = _extract_metric_from_row(curr_row, metric)
        prev_val: Decimal = _extract_metric_from_row(prev_row, metric)
        delta: Decimal = curr_val - prev_val

        if prev_val == Decimal(0):
            delta_pct: float | None = None
        else:
            delta_pct = float(delta / prev_val)

        movers.append({
            "key": key,
            "label": label,
            "current": float(curr_val),
            "previous": float(prev_val),
            "delta": float(delta),
            "delta_pct": delta_pct,
            "direction": "up" if delta >= Decimal(0) else "down",
        })

    # Sort by absolute delta descending; apply limit.
    movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    movers = movers[:limit]

    return {
        "dimension": dimension,
        "metric": metric,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "previous_from": str(prev_from),
        "previous_to": str(prev_to),
        "movers": movers,
    }
