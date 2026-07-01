"""Advanced Reporting service — M3+.

Public API
----------
    build_report_payload(db, report_definition, date_from, date_to) -> dict
    render_report_html(payload, branding) -> str
    due_schedules(db, now) -> list[ReportSchedule]
    mark_sent(db, schedule) -> None

Design notes
------------
* ``build_report_payload`` re-uses the same SQL aggregations as the dashboard
  API (func.sum / func.coalesce pattern, compute_derived_metrics from the
  metric layer).  No bespoke queries — same tenant_id guard on every call.
* ``render_report_html`` produces a fully self-contained HTML document (inline
  CSS, no external CDN / JS).  It is the deliverable served at the public link
  and can be printed to PDF by headless Chrome in a later phase.  Turkish labels
  are used throughout the client-facing HTML.
* ``due_schedules`` is designed to be called from a Celery beat task.  Celery
  is NOT wired here — this is a pure service function.  The caller is responsible
  for scheduling the periodic call (e.g. every minute) and for calling
  ``mark_sent`` after a successful delivery.
* PDF export: out of scope for now.  The intended approach is to have a
  headless-Chrome sidecar render ``render_report_html``'s output and save the
  PDF.  Wire in a later phase.

Scheduling logic
----------------
  daily:    fires when last_sent_at is null or the last send date < today UTC
            AND the current UTC hour >= schedule.hour
  weekly:   fires when (today is the right weekday) AND (daily condition above)
  monthly:  fires when (today is the 1st of the month) AND (daily condition above)
"""

from __future__ import annotations

import html
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.analytics import DimChannel, FactDailyMetrics
from ayaz.models.reports import ReportDefinition, ReportSchedule
from ayaz.services.metrics import compute_derived_metrics

logger = logging.getLogger(__name__)

# ── Aggregation helpers (mirrors dashboard.py) ────────────────────────────────


def _d(v: object) -> Decimal:
    """Coerce a DB-returned value (Decimal, int, float, None) to Decimal."""
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def _query_channel_rows(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """Return per-channel aggregated raw rows for the date range."""
    rows = db.execute(
        select(
            DimChannel.key.label("channel_key"),
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
        .group_by(DimChannel.key)
        .order_by(DimChannel.key)
    ).mappings().all()

    return [dict(r) for r in rows]


def _query_timeseries_rows(
    db: Session,
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """Return daily spend timeseries rows for the date range."""
    rows = db.execute(
        select(
            FactDailyMetrics.date_key.label("date_key"),
            func.sum(
                func.coalesce(
                    FactDailyMetrics.cost_base_ccy,
                    FactDailyMetrics.cost_raw,
                )
            ).label("spend"),
            func.sum(FactDailyMetrics.impressions).label("impressions"),
            func.sum(FactDailyMetrics.clicks).label("clicks"),
            func.sum(FactDailyMetrics.conversions).label("conversions"),
            func.sum(FactDailyMetrics.conversion_value_raw).label("conversion_value"),
        )
        .where(
            FactDailyMetrics.tenant_id == tenant_id,
            FactDailyMetrics.date_key >= date_from,
            FactDailyMetrics.date_key <= date_to,
        )
        .group_by(FactDailyMetrics.date_key)
        .order_by(FactDailyMetrics.date_key)
    ).mappings().all()

    return [dict(r) for r in rows]


# ── Report payload builder ────────────────────────────────────────────────────


def build_report_payload(
    db: Session,
    report_definition: ReportDefinition,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Assemble a structured report payload from fact-table aggregations.

    The payload shape is::

        {
            "report_id": str(uuid),
            "report_name": str,
            "date_from": "YYYY-MM-DD",
            "date_to": "YYYY-MM-DD",
            "generated_at": "ISO-8601 UTC",
            "branding": {
                "brand_name": str,
                "logo_url": str | None,
                "primary_color": str,
            },
            "sections": list[str],
            "totals": {
                "spend": float,
                "impressions": float,
                "clicks": float,
                "conversions": float,
                "conversion_value": float,
                "ctr": float,
                "cpc": float,
                "cpa": float,
                "roas": float,
            },
            "by_channel": [
                {
                    "channel": str,
                    "spend": float,
                    "impressions": float,
                    "clicks": float,
                    "conversions": float,
                    "conversion_value": float,
                    "ctr": float,
                    "cpc": float,
                    "cpa": float,
                    "roas": float,
                },
                ...
            ],
            "timeseries": [
                {"date": "YYYY-MM-DD", "spend": float},
                ...
            ],
            "insights": [
                {
                    "category": str,
                    "severity": str,
                    "title": str,
                    "body": str,
                    "score": float,
                },
                ...
            ],
        }

    Only sections listed in ``report_definition.config["sections"]`` are
    populated (defaults to all four if the key is absent).

    Channel filtering: if ``report_definition.config["channels"]`` is a non-empty
    list, only those channels are included in ``by_channel`` and the totals.

    Tenant isolation: all queries are scoped to ``report_definition.tenant_id``.
    """
    tenant_id: uuid.UUID = report_definition.tenant_id
    config: dict[str, Any] = report_definition.config or {}
    sections: list[str] = config.get(
        "sections", ["totals", "by_channel", "timeseries", "insights"]
    )
    channel_filter: list[str] | None = config.get("channels") or None  # [] -> None

    # Branding — defaults when not configured
    branding = {
        "brand_name": config.get("brand_name") or "AYAZ",
        "logo_url": config.get("logo_url") or None,
        "primary_color": config.get("primary_color") or "#1A73E8",
    }

    payload: dict[str, Any] = {
        "report_id": str(report_definition.id),
        "report_name": report_definition.name,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branding": branding,
        "sections": sections,
        "totals": {
            "spend": 0.0,
            "impressions": 0.0,
            "clicks": 0.0,
            "conversions": 0.0,
            "conversion_value": 0.0,
            "ctr": 0.0,
            "cpc": 0.0,
            "cpa": 0.0,
            "roas": 0.0,
        },
        "by_channel": [],
        "timeseries": [],
        "insights": [],
    }

    # ── by_channel ────────────────────────────────────────────────────────────

    if "by_channel" in sections or "totals" in sections:
        raw_rows = _query_channel_rows(db, tenant_id, date_from, date_to)

        channel_items: list[dict[str, Any]] = []
        for row in raw_rows:
            channel_key = str(row["channel_key"])
            if channel_filter and channel_key not in channel_filter:
                continue

            imp = _d(row["impressions"])
            clk = _d(row["clicks"])
            spd = _d(row["spend"])
            cvr = _d(row["conversions"])
            cvv = _d(row["conversion_value"])
            derived = compute_derived_metrics(
                impressions=imp,
                clicks=clk,
                spend=spd,
                conversions=cvr,
                conversion_value=cvv,
            )
            channel_items.append(
                {
                    "channel": channel_key,
                    "spend": float(spd),
                    "impressions": float(imp),
                    "clicks": float(clk),
                    "conversions": float(cvr),
                    "conversion_value": float(cvv),
                    "ctr": float(derived["ctr"]),
                    "cpc": float(derived["cpc"]),
                    "cpa": float(derived["cpa"]),
                    "roas": float(derived["roas"]),
                }
            )

        if "by_channel" in sections:
            payload["by_channel"] = channel_items

        # Totals: sum across filtered channels
        if "totals" in sections:
            t_imp = sum(_d(c["impressions"]) for c in channel_items)
            t_clk = sum(_d(c["clicks"]) for c in channel_items)
            t_spd = sum(_d(c["spend"]) for c in channel_items)
            t_cvr = sum(_d(c["conversions"]) for c in channel_items)
            t_cvv = sum(_d(c["conversion_value"]) for c in channel_items)
            t_derived = compute_derived_metrics(
                impressions=t_imp,
                clicks=t_clk,
                spend=t_spd,
                conversions=t_cvr,
                conversion_value=t_cvv,
            )
            payload["totals"] = {
                "spend": float(t_spd),
                "impressions": float(t_imp),
                "clicks": float(t_clk),
                "conversions": float(t_cvr),
                "conversion_value": float(t_cvv),
                "ctr": float(t_derived["ctr"]),
                "cpc": float(t_derived["cpc"]),
                "cpa": float(t_derived["cpa"]),
                "roas": float(t_derived["roas"]),
            }

    # ── timeseries ────────────────────────────────────────────────────────────

    if "timeseries" in sections:
        ts_rows = _query_timeseries_rows(db, tenant_id, date_from, date_to)
        payload["timeseries"] = [
            {
                "date": str(row["date_key"]),
                "spend": float(_d(row["spend"])),
            }
            for row in ts_rows
        ]

    # ── insights ──────────────────────────────────────────────────────────────

    if "insights" in sections:
        try:
            from ayaz.models.insights import Insight  # lazy — avoids circular

            insight_rows = db.scalars(
                select(Insight)
                .where(
                    Insight.tenant_id == tenant_id,
                    Insight.period_start >= date_from,
                    Insight.period_end <= date_to,
                    Insight.status.in_(["new", "seen"]),
                )
                .order_by(Insight.score.desc())
                .limit(10)
            ).all()

            payload["insights"] = [
                {
                    "category": row.category,
                    "severity": row.severity,
                    "title": row.title,
                    "body": row.body,
                    "score": row.score,
                }
                for row in insight_rows
            ]
        except Exception:
            logger.warning(
                "[reports] Could not load insights for report %s",
                report_definition.id,
                exc_info=True,
            )

    return payload


# ── HTML renderer ─────────────────────────────────────────────────────────────

# Inline SVG bar chart: renders spend timeseries as a simple horizontal bar chart
# embedded directly in the HTML — no external JS/CDN required.
_SEVERITY_BADGE = {
    "critical": "#dc3545",
    "warning": "#fd7e14",
    "info": "#0d6efd",
}


def _fmt(value: float, decimals: int = 2) -> str:
    """Format a float to a fixed number of decimal places."""
    return f"{value:,.{decimals}f}"


def _esc(text: str) -> str:
    """HTML-escape a string for safe embedding."""
    return html.escape(str(text))


def _build_spend_chart(timeseries: list[dict[str, Any]], primary_color: str) -> str:
    """Return an inline SVG bar chart for the spend timeseries.

    Uses a simple horizontal layout: each bar is proportional to its spend
    value relative to the maximum in the series.  Falls back to a plain
    'no data' message when the series is empty.
    """
    if not timeseries:
        return "<p style='color:#666;font-style:italic;'>Zaman serisi verisi yok.</p>"

    max_spend = max((r["spend"] for r in timeseries), default=0)
    if max_spend == 0:
        max_spend = 1.0

    bar_height = 22
    bar_gap = 6
    chart_width = 580
    label_width = 90
    bar_area_width = chart_width - label_width - 10
    chart_height = len(timeseries) * (bar_height + bar_gap) + 20

    bars: list[str] = []
    for i, point in enumerate(timeseries):
        y = i * (bar_height + bar_gap) + 10
        bar_w = int((point["spend"] / max_spend) * bar_area_width)
        label = _esc(str(point["date"]))
        value_label = _esc(_fmt(point["spend"]))
        bars.append(
            f'<text x="{label_width - 5}" y="{y + bar_height - 6}" '
            f'text-anchor="end" font-size="11" fill="#555">{label}</text>'
        )
        bars.append(
            f'<rect x="{label_width}" y="{y}" width="{bar_w}" height="{bar_height}" '
            f'fill="{_esc(primary_color)}" rx="3"/>'
        )
        bars.append(
            f'<text x="{label_width + bar_w + 5}" y="{y + bar_height - 6}" '
            f'font-size="11" fill="#333">{value_label}</text>'
        )

    bars_svg = "\n".join(bars)
    return (
        f'<svg width="{chart_width}" height="{chart_height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto;">'
        f"{bars_svg}"
        f"</svg>"
    )


def render_report_html(payload: dict[str, Any], branding: dict[str, Any]) -> str:
    """Render a self-contained white-label HTML report for a client.

    Parameters
    ----------
    payload:
        The structured report dict returned by ``build_report_payload``.
    branding:
        Dict with keys: brand_name, logo_url (nullable), primary_color.
        (This is also available as payload["branding"] — pass it separately so
        callers can override branding without mutating the payload.)

    Returns
    -------
    A complete HTML document (<!DOCTYPE html> … </html>) with all CSS inlined.
    No external JS or CDN dependencies.  Turkish labels throughout.

    PDF note
    --------
    This HTML is designed to be rendered by headless Chrome in a later phase
    to produce a pixel-perfect PDF.  Until then, the HTML itself is the
    deliverable for the white-label client link.
    """
    brand_name = _esc(branding.get("brand_name") or "AYAZ")
    logo_url = branding.get("logo_url") or ""
    primary_color = _esc(branding.get("primary_color") or "#1A73E8")

    date_from = _esc(payload.get("date_from", ""))
    date_to = _esc(payload.get("date_to", ""))
    report_name = _esc(payload.get("report_name", "Rapor"))
    generated_at = _esc(payload.get("generated_at", ""))
    sections: list[str] = payload.get("sections", [])
    totals: dict[str, float] = payload.get("totals", {})
    by_channel: list[dict] = payload.get("by_channel", [])
    timeseries: list[dict] = payload.get("timeseries", [])
    insights: list[dict] = payload.get("insights", [])

    # ── Logo block ────────────────────────────────────────────────────────────
    logo_html = ""
    if logo_url:
        logo_html = (
            f'<img src="{_esc(logo_url)}" alt="{brand_name} logo" '
            f'style="max-height:60px;margin-bottom:10px;display:block;">'
        )

    # ── KPI cards ─────────────────────────────────────────────────────────────
    kpi_cards_html = ""
    if "totals" in sections:
        kpi_items = [
            ("Harcama", _fmt(totals.get("spend", 0))),
            ("Gösterim", _fmt(totals.get("impressions", 0), 0)),
            ("Tiklama", _fmt(totals.get("clicks", 0), 0)),
            ("Donusum", _fmt(totals.get("conversions", 0), 0)),
            ("Donusum Degeri", _fmt(totals.get("conversion_value", 0))),
            ("CTR", f"{totals.get('ctr', 0) * 100:.2f}%"),
            ("CPC", _fmt(totals.get("cpc", 0))),
            ("CPA", _fmt(totals.get("cpa", 0))),
            ("ROAS", _fmt(totals.get("roas", 0))),
        ]
        cards = []
        for label, value in kpi_items:
            cards.append(
                f'<div style="background:#fff;border:1px solid #e0e0e0;border-radius:8px;'
                f'padding:16px 20px;min-width:130px;flex:1;text-align:center;'
                f'box-shadow:0 1px 3px rgba(0,0,0,.06);">'
                f'<div style="font-size:12px;color:#666;text-transform:uppercase;'
                f'letter-spacing:.5px;margin-bottom:6px;">{_esc(label)}</div>'
                f'<div style="font-size:22px;font-weight:700;color:{primary_color};">'
                f'{_esc(value)}</div>'
                f"</div>"
            )
        kpi_cards_html = (
            f'<section style="margin-bottom:36px;">'
            f'<h2 style="font-size:16px;font-weight:600;color:#333;margin-bottom:14px;">'
            f"Ozet Metrikler</h2>"
            f'<div style="display:flex;flex-wrap:wrap;gap:12px;">'
            + "".join(cards)
            + "</div></section>"
        )

    # ── Channel table ─────────────────────────────────────────────────────────
    channel_table_html = ""
    if "by_channel" in sections and by_channel:
        header_cells = [
            "Kanal", "Harcama", "Gosurim", "Tiklama",
            "Donusum", "Donusum Degeri", "CTR", "CPC", "CPA", "ROAS",
        ]
        th_style = (
            f"background:{primary_color};color:#fff;padding:10px 12px;"
            f"text-align:left;font-size:12px;font-weight:600;white-space:nowrap;"
        )
        header_row = "".join(
            f"<th style='{th_style}'>{_esc(h)}</th>" for h in header_cells
        )

        body_rows: list[str] = []
        for idx, ch in enumerate(by_channel):
            bg = "#f9f9f9" if idx % 2 == 0 else "#fff"
            td = (
                f"background:{bg};padding:9px 12px;"
                f"font-size:13px;border-bottom:1px solid #eee;"
            )
            ctr_pct = "{:.2f}%".format(ch.get("ctr", 0) * 100)
            cells = [
                f"<td style='{td}'><strong>{_esc(ch['channel'])}</strong></td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('spend', 0)))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('impressions', 0), 0))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('clicks', 0), 0))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('conversions', 0), 0))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('conversion_value', 0)))}</td>",
                f"<td style='{td}'>{_esc(ctr_pct)}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('cpc', 0)))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('cpa', 0)))}</td>",
                f"<td style='{td}'>{_esc(_fmt(ch.get('roas', 0)))}</td>",
            ]
            body_rows.append(f"<tr>{''.join(cells)}</tr>")

        channel_table_html = (
            f'<section style="margin-bottom:36px;overflow-x:auto;">'
            f'<h2 style="font-size:16px;font-weight:600;color:#333;margin-bottom:14px;">'
            f"Kanala Gore Performans</h2>"
            f'<table style="width:100%;border-collapse:collapse;font-family:sans-serif;">'
            f"<thead><tr>{header_row}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            f"</table></section>"
        )

    # ── Timeseries chart ──────────────────────────────────────────────────────
    timeseries_html = ""
    if "timeseries" in sections:
        chart_svg = _build_spend_chart(timeseries, branding.get("primary_color") or "#1A73E8")
        timeseries_html = (
            f'<section style="margin-bottom:36px;">'
            f'<h2 style="font-size:16px;font-weight:600;color:#333;margin-bottom:14px;">'
            f"Gunluk Harcama Trendi</h2>"
            f"{chart_svg}"
            f"</section>"
        )

    # ── Insights ──────────────────────────────────────────────────────────────
    insights_html = ""
    if "insights" in sections and insights:
        insight_items: list[str] = []
        for ins in insights:
            sev = ins.get("severity", "info")
            badge_color = _SEVERITY_BADGE.get(sev, "#6c757d")
            badge = (
                f'<span style="background:{badge_color};color:#fff;'
                f'padding:2px 8px;border-radius:10px;font-size:11px;'
                f'font-weight:600;margin-right:8px;">{_esc(sev.upper())}</span>'
            )
            insight_items.append(
                f'<div style="border-left:4px solid {badge_color};'
                f'background:#fff;padding:12px 16px;margin-bottom:10px;'
                f'border-radius:0 6px 6px 0;box-shadow:0 1px 2px rgba(0,0,0,.05);">'
                f'<div style="margin-bottom:4px;">{badge}'
                f'<strong style="font-size:14px;color:#222;">'
                f'{_esc(ins.get("title", ""))}</strong></div>'
                f'<div style="font-size:13px;color:#555;line-height:1.5;">'
                f'{_esc(ins.get("body", ""))}</div>'
                f"</div>"
            )
        insights_html = (
            f'<section style="margin-bottom:36px;">'
            f'<h2 style="font-size:16px;font-weight:600;color:#333;margin-bottom:14px;">'
            f"Onemli Bulgular</h2>"
            + "".join(insight_items)
            + "</section>"
        )

    # ── Assemble full document ────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand_name} — {report_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         background: #f4f6f8; color: #222; padding: 24px; }}
  .report-wrapper {{ max-width: 860px; margin: 0 auto; }}
  .report-header {{ background: {primary_color}; color: #fff; border-radius: 10px;
                    padding: 28px 32px; margin-bottom: 28px; }}
  .report-header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .report-header .meta {{ font-size: 13px; opacity: .85; }}
  .report-footer {{ text-align: center; font-size: 11px; color: #999;
                    margin-top: 32px; padding-top: 16px;
                    border-top: 1px solid #e0e0e0; }}
</style>
</head>
<body>
<div class="report-wrapper">

  <div class="report-header">
    {logo_html}
    <h1>{brand_name} — {report_name}</h1>
    <div class="meta">
      Donem: {date_from} / {date_to} &nbsp;&bull;&nbsp;
      Olusturulma: {generated_at}
    </div>
  </div>

  {kpi_cards_html}
  {channel_table_html}
  {timeseries_html}
  {insights_html}

  <div class="report-footer">
    Bu rapor {brand_name} tarafindan olusturulmustur. &copy; {brand_name}
  </div>

</div>
</body>
</html>"""


# ── Scheduling helpers ────────────────────────────────────────────────────────


def due_schedules(
    db: Session,
    now: datetime,
) -> list[ReportSchedule]:
    """Return all active schedules that are due for delivery at ``now`` (UTC).

    Firing rules
    ------------
    A schedule is due when ALL of the following are true:

    1. ``is_active`` is True.
    2. The current UTC hour >= ``schedule.hour``.
    3. The schedule has never run (last_sent_at is None) OR the last run date
       (date part of last_sent_at) is strictly before today UTC.
    4. Cadence-specific day check:
       - ``daily``  : always passes (checked daily)
       - ``weekly``  : today's weekday (0=Mon) == ``schedule.weekday``
       - ``monthly`` : today is the 1st of the month

    This function is designed to be called from a Celery beat task (e.g. every
    minute).  It is idempotent: calling it twice for the same ``now`` is safe
    because ``mark_sent`` updates ``last_sent_at`` to today.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only usage).
    now:
        The current UTC datetime.  Pass ``datetime.now(timezone.utc)`` from
        the Celery task.

    Returns
    -------
    List of ReportSchedule ORM objects that should be delivered.
    """
    today = now.date()
    current_hour = now.hour

    active_schedules = db.scalars(
        select(ReportSchedule).where(ReportSchedule.is_active.is_(True))
    ).all()

    due: list[ReportSchedule] = []
    for sched in active_schedules:
        # Hour gate
        if current_hour < sched.hour:
            continue

        # Last-sent gate: skip if already sent today
        if sched.last_sent_at is not None:
            try:
                last_sent_date = datetime.fromisoformat(
                    sched.last_sent_at.replace("Z", "+00:00")
                ).date()
            except (ValueError, AttributeError):
                last_sent_date = None

            if last_sent_date is not None and last_sent_date >= today:
                continue

        # Cadence-specific day check
        cadence = sched.cadence
        if cadence == "daily":
            pass  # every day
        elif cadence == "weekly":
            if sched.weekday is None or today.weekday() != sched.weekday:
                continue
        elif cadence == "monthly":
            if today.day != 1:
                continue
        else:
            # Unknown cadence — skip
            logger.warning(
                "[reports] Unknown cadence %r for schedule %s — skipping",
                cadence,
                sched.id,
            )
            continue

        due.append(sched)

    return due


def mark_sent(db: Session, schedule: ReportSchedule) -> None:
    """Record a successful delivery for ``schedule``.

    Sets ``last_sent_at`` to the current UTC datetime (ISO-8601) and commits.
    Call this after the delivery has been confirmed (email sent, etc.).
    """
    schedule.last_sent_at = datetime.now(timezone.utc).isoformat()
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    logger.info("[reports] Schedule %s marked as sent at %s", schedule.id, schedule.last_sent_at)


def send_scheduled_report(
    db: Session,
    schedule: ReportSchedule,
    date_from: date,
    date_to: date,
) -> None:
    """Build and deliver a scheduled report (stub — logs only).

    This function is the hook for Celery beat integration.  Wire it by:
    1. Calling ``due_schedules(db, now)`` to get the list of due schedules.
    2. For each due schedule, resolving the date range (e.g. last 30 days),
       calling ``send_scheduled_report``, then calling ``mark_sent``.

    Actual email delivery is deferred until SMTP/SES credentials are configured.
    Currently this function logs the report payload size and recipient list.

    Parameters
    ----------
    db:
        SQLAlchemy Session.
    schedule:
        The due ReportSchedule object.
    date_from / date_to:
        The date range the caller has resolved from the cadence/preset.
    """
    defn = db.get(ReportDefinition, schedule.report_definition_id)
    if defn is None:
        logger.error(
            "[reports] ReportDefinition %s not found for schedule %s — skipping",
            schedule.report_definition_id,
            schedule.id,
        )
        return

    # Tenant-isolation guard: this runs in a background job that processes
    # schedules across all tenants, so re-validate the definition belongs to the
    # schedule's tenant before rendering (defence-in-depth against a stale/forged
    # FK leaking another tenant's metrics into this tenant's report).
    if defn.tenant_id != schedule.tenant_id:
        logger.error(
            "[reports] ReportDefinition %s tenant=%s does not match schedule %s "
            "tenant=%s — skipping to avoid cross-tenant leak",
            defn.id,
            defn.tenant_id,
            schedule.id,
            schedule.tenant_id,
        )
        return

    payload = build_report_payload(db, defn, date_from, date_to)
    html_content = render_report_html(payload, payload["branding"])

    recipients: list[str] = schedule.recipients or []
    logger.info(
        "[reports] Delivering report %r (%d bytes HTML) to %d recipient(s): %s",
        defn.name,
        len(html_content),
        len(recipients),
        recipients,
    )
    # TODO (Faz 3): Send via SMTP/SES — integrate credentials from Vault.
    # Example:
    #   email_client.send(
    #       to=recipients,
    #       subject=f"{defn.name} — {date_from} / {date_to}",
    #       html=html_content,
    #   )
