"""Bütçe Senaryo Simülatörü — what-if kanal bütçe simülasyonu.

Bu modül tarihsel kanal verimliliğini baz alarak interaktif senaryo
analizine olanak tanır: kullanıcı kanallar arası bütçeyi istediği gibi
dağıtır; modül geçmiş veriye dayalı tıklama/gösterim/dönüşüm/gelir
projeksiyon hesaplar.

Mimari
------
* ``get_baseline`` — DB'den son N günlük kanal metriklerini çeker ve her
  kanal için verimlilik katsayılarını hesaplar (cpc, cpm, cvr, roas, aov, cpa).
* ``simulate`` — kullanıcı tarafından verilen kanal→bütçe tahsislerini
  alır, verimliliği baz alarak doğrusal projeksiyon üretir ve senaryo
  sonuçlarını döner.

Önemli varsayım: projeksiyon tamamen doğrusaldır. Büyük ölçek değişimlerinde
(örn. bütçeyi 10x artırma) gerçek ROAS azalabilir (diminishing returns).
Bu etki modellenmemiştir; varsayım listesinde Türkçe olarak belirtilir.

Tenant izolasyonu: tüm DB sorguları ``tenant_id`` ile filtrelenir.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Yeniden kullan: mevcut _fetch_channel_metrics ve _d yardımcıları ─────────


def _fetch_channel_metrics(
    db: "Session",
    tenant_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, dict]:
    """Mevcut budget_planner._fetch_channel_metrics ile birebir aynı mantık.

    Tekrarı önlemek için doğrudan import edilir.
    """
    from ayaz.services.budget_planner import _fetch_channel_metrics as _orig
    return _orig(db, tenant_id, date_from, date_to)


def _d(v) -> float:
    """DB'den dönen değeri (Decimal/int/float/None) float'a çevirir."""
    if v is None:
        return 0.0
    return float(v)


# ── Verimlilik katsayıları ─────────────────────────────────────────────────────


def _efficiency(
    spend: float,
    clicks: float,
    impressions: float,
    conversions: float,
    conversion_value: float,
) -> dict:
    """Kanal başına verimlilik katsayılarını hesaplar (sıfıra bölme → 0.0).

    Döndürülen değerler:
        cpc   = spend / clicks
        cpm   = spend / impressions * 1000
        cvr   = conversions / clicks
        roas  = conversion_value / spend
        aov   = conversion_value / conversions   (Average Order Value)
        cpa   = spend / conversions
    """
    cpc = spend / clicks if clicks > 0 else 0.0
    cpm = spend / impressions * 1000 if impressions > 0 else 0.0
    cvr = conversions / clicks if clicks > 0 else 0.0
    roas = conversion_value / spend if spend > 0 else 0.0
    aov = conversion_value / conversions if conversions > 0 else 0.0
    cpa = spend / conversions if conversions > 0 else 0.0
    return {
        "cpc": round(cpc, 4),
        "cpm": round(cpm, 4),
        "cvr": round(cvr, 6),
        "roas": round(roas, 4),
        "aov": round(aov, 2),
        "cpa": round(cpa, 2),
    }


# ── Genel yuvarlama yardımcıları ──────────────────────────────────────────────


def _r2(v: float) -> float:
    """İki ondalık basamağa yuvarla (para birimi)."""
    return round(v, 2)


def _r4(v: float) -> float:
    """Dört ondalık basamağa yuvarla (oran/katsayı)."""
    return round(v, 4)


# ── get_baseline ──────────────────────────────────────────────────────────────


def get_baseline(
    db: "Session",
    tenant_id: uuid.UUID,
    *,
    lookback_days: int = 30,
    as_of: date | None = None,
) -> dict:
    """Son ``lookback_days`` günün kanal metriklerini çekip verimlilik hesaplar.

    Parametreler
    ------------
    db:
        SQLAlchemy oturumu.
    tenant_id:
        Kiracı UUID'si — tüm sorgular bu filtre ile kısıtlanır.
    lookback_days:
        Geriye bakış penceresi (gün). Varsayılan 30.
    as_of:
        Referans tarihi; belirtilmezse bugün (UTC). Test için kullanışlıdır.

    Döndürdüğü yapı
    ---------------
    {
      "lookback_days": int,
      "period": {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"},
      "total_spend": float,
      "channels": [
        {
          "key", "label", "spend", "impressions", "clicks",
          "conversions", "conversion_value",
          "cpc", "cpm", "cvr", "roas", "aov", "cpa", "spend_share_pct"
        }
      ],
      "totals": {
        "spend", "impressions", "clicks", "conversions", "conversion_value",
        "roas", "cpc", "cvr", "cpa"
      }
    }
    """
    today = as_of or date.today()
    date_from = today - timedelta(days=lookback_days)
    date_to = today

    raw = _fetch_channel_metrics(db, tenant_id, date_from, date_to)

    total_spend = sum(m["spend"] for m in raw.values())

    channels: list[dict] = []
    for key, m in raw.items():
        spend = m["spend"]
        eff = _efficiency(
            spend,
            m["clicks"],
            m["impressions"],
            m["conversions"],
            m["conversion_value"],
        )
        spend_share_pct = spend / total_spend * 100 if total_spend > 0 else 0.0
        channels.append({
            "key": key,
            "label": m["label"],
            "spend": _r2(spend),
            "impressions": _r2(m["impressions"]),
            "clicks": _r2(m["clicks"]),
            "conversions": _r4(m["conversions"]),
            "conversion_value": _r2(m["conversion_value"]),
            "cpc": eff["cpc"],
            "cpm": eff["cpm"],
            "cvr": eff["cvr"],
            "roas": eff["roas"],
            "aov": eff["aov"],
            "cpa": eff["cpa"],
            "spend_share_pct": round(spend_share_pct, 2),
        })

    # Toplam metrikler
    tot_spend = _r2(total_spend)
    tot_impressions = _r2(sum(m["impressions"] for m in raw.values()))
    tot_clicks = _r2(sum(m["clicks"] for m in raw.values()))
    tot_conversions = _r4(sum(m["conversions"] for m in raw.values()))
    tot_conv_value = _r2(sum(m["conversion_value"] for m in raw.values()))

    tot_roas = _r4(tot_conv_value / tot_spend) if tot_spend > 0 else 0.0
    tot_cpc = _r4(tot_spend / tot_clicks) if tot_clicks > 0 else 0.0
    tot_cvr = _r4(tot_conversions / tot_clicks) if tot_clicks > 0 else 0.0
    tot_cpa = _r2(tot_spend / tot_conversions) if tot_conversions > 0 else 0.0

    # Harcama payına göre azalan sırala (tutarlı çıktı için)
    channels.sort(key=lambda c: c["spend"], reverse=True)

    return {
        "lookback_days": lookback_days,
        "period": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
        "total_spend": tot_spend,
        "channels": channels,
        "totals": {
            "spend": tot_spend,
            "impressions": tot_impressions,
            "clicks": tot_clicks,
            "conversions": tot_conversions,
            "conversion_value": tot_conv_value,
            "roas": tot_roas,
            "cpc": tot_cpc,
            "cvr": tot_cvr,
            "cpa": tot_cpa,
        },
    }


# ── simulate ──────────────────────────────────────────────────────────────────


def simulate(
    db: "Session",
    tenant_id: uuid.UUID,
    allocations: dict[str, float],
    *,
    lookback_days: int = 30,
    as_of: date | None = None,
) -> dict:
    """Verilen kanal tahsislerinden doğrusal projeksiyon üretir.

    Her kanal için geçmiş verimlilik katsayıları (cpc, cpm, cvr, aov) baz
    alınarak planlanan bütçeden beklenen tıklama/gösterim/dönüşüm/gelir
    hesaplanır.

    Projeksiyon formülleri (doğrusal):
        clicks           = planned_spend / cpc         (cpc > 0 ise, aksi 0)
        impressions      = planned_spend / cpm * 1000  (cpm > 0 ise, aksi 0)
        conversions      = clicks * cvr
        conversion_value = conversions * aov
        roas             = conversion_value / planned_spend  (> 0 ise, aksi 0)
        cpa              = planned_spend / conversions       (> 0 ise, aksi 0)

    Parametreler
    ------------
    db:
        SQLAlchemy oturumu.
    tenant_id:
        Kiracı UUID'si.
    allocations:
        {channel_key: planned_spend} sözlüğü. Tüm değerler >= 0 olmalıdır.
    lookback_days:
        Verimlilik hesabı için geriye bakış penceresi (gün).
    as_of:
        Referans tarihi.

    Hatalar
    -------
    ValueError:
        - allocations boşsa.
        - Herhangi bir tahsis değeri negatifse.

    Döndürdüğü yapı
    ---------------
    {
      "lookback_days": int,
      "total_spend": float,
      "channels": [
        {
          "key", "label", "spend", "impressions", "clicks",
          "conversions", "conversion_value", "roas", "cpa",
          "baseline_spend", "spend_delta", "spend_delta_pct"
        }
      ],
      "projected_totals": {"spend","impressions","clicks","conversions",
                           "conversion_value","roas","cpa","cvr"},
      "baseline_totals":  {"spend","impressions","clicks","conversions",
                           "conversion_value","roas","cpa","cvr"},
      "deltas": {
          "impressions_pct","clicks_pct","conversions_pct",
          "conversion_value_pct","roas_pct"
      },
      "assumptions": ["<TR>", ...]
    }
    """
    if not allocations:
        raise ValueError("allocations boş olamaz — en az bir kanal gerekli.")

    for key, val in allocations.items():
        if val < 0:
            raise ValueError(
                f"Negatif bütçe geçersizdir: {key!r} = {val}. "
                "Tüm kanal bütçeleri 0 veya daha büyük olmalıdır."
            )

    # Baz çizgisini al
    baseline = get_baseline(db, tenant_id, lookback_days=lookback_days, as_of=as_of)

    # Kanal → baz metrik haritası
    baseline_by_key: dict[str, dict] = {ch["key"]: ch for ch in baseline["channels"]}

    assumptions: list[str] = [
        f"Son {lookback_days} günlük kanal verimliliği baz alınmıştır.",
        "Doğrusal projeksiyon — büyük ölçek değişimlerinde gerçek sonuç farklılaşabilir.",
    ]

    projected_channels: list[dict] = []
    zero_history_keys: list[str] = []

    for channel_key, planned_spend in allocations.items():
        bch = baseline_by_key.get(channel_key)

        if bch is None:
            # Geçmişte bu kanal yok → sıfır projeksiyon
            zero_history_keys.append(channel_key)
            projected_channels.append({
                "key": channel_key,
                "label": channel_key,
                "spend": _r2(planned_spend),
                "impressions": 0.0,
                "clicks": 0.0,
                "conversions": 0.0,
                "conversion_value": 0.0,
                "roas": 0.0,
                "cpa": 0.0,
                "baseline_spend": 0.0,
                "spend_delta": _r2(planned_spend),
                "spend_delta_pct": 0.0,
            })
            continue

        cpc = bch["cpc"]
        cpm = bch["cpm"]
        cvr = bch["cvr"]
        aov = bch["aov"]

        clicks = planned_spend / cpc if cpc > 0 else 0.0
        impressions = planned_spend / cpm * 1000 if cpm > 0 else 0.0
        conversions = clicks * cvr
        conversion_value = conversions * aov
        roas = conversion_value / planned_spend if planned_spend > 0 else 0.0
        cpa = planned_spend / conversions if conversions > 0 else 0.0

        baseline_spend = bch["spend"]
        spend_delta = planned_spend - baseline_spend
        spend_delta_pct = (
            spend_delta / baseline_spend * 100 if baseline_spend > 0 else 0.0
        )

        projected_channels.append({
            "key": channel_key,
            "label": bch["label"],
            "spend": _r2(planned_spend),
            "impressions": _r2(impressions),
            "clicks": _r2(clicks),
            "conversions": _r4(conversions),
            "conversion_value": _r2(conversion_value),
            "roas": _r4(roas),
            "cpa": _r2(cpa),
            "baseline_spend": _r2(baseline_spend),
            "spend_delta": _r2(spend_delta),
            "spend_delta_pct": round(spend_delta_pct, 2),
        })

    if zero_history_keys:
        keys_str = ", ".join(f"'{k}'" for k in zero_history_keys)
        assumptions.append(
            f"Geçmiş veri bulunmayan kanal(lar) sıfır projeksiyon ile dahil edildi: "
            f"{keys_str}."
        )

    # Projeksiyon toplamları
    total_spend = sum(ch["spend"] for ch in projected_channels)
    proj_impressions = _r2(sum(ch["impressions"] for ch in projected_channels))
    proj_clicks = _r2(sum(ch["clicks"] for ch in projected_channels))
    proj_conversions = _r4(sum(ch["conversions"] for ch in projected_channels))
    proj_conv_value = _r2(sum(ch["conversion_value"] for ch in projected_channels))

    proj_roas = _r4(proj_conv_value / total_spend) if total_spend > 0 else 0.0
    proj_cpa = _r2(total_spend / proj_conversions) if proj_conversions > 0 else 0.0
    proj_cvr = _r4(proj_conversions / proj_clicks) if proj_clicks > 0 else 0.0

    # Baz totalleri (mevcut dağılım toplamları — dürüst karşılaştırma için)
    b_totals = baseline["totals"]
    base_spend = b_totals["spend"]
    base_impressions = b_totals["impressions"]
    base_clicks = b_totals["clicks"]
    base_conversions = b_totals["conversions"]
    base_conv_value = b_totals["conversion_value"]
    base_roas = b_totals["roas"]
    base_cpa = b_totals["cpa"]
    base_cvr = b_totals["cvr"]

    def _delta_pct(proj_val: float, base_val: float) -> float:
        if base_val == 0:
            return 0.0
        return round((proj_val - base_val) / base_val * 100, 2)

    deltas = {
        "impressions_pct": _delta_pct(proj_impressions, base_impressions),
        "clicks_pct": _delta_pct(proj_clicks, base_clicks),
        "conversions_pct": _delta_pct(proj_conversions, base_conversions),
        "conversion_value_pct": _delta_pct(proj_conv_value, base_conv_value),
        "roas_pct": _delta_pct(proj_roas, base_roas),
    }

    # Harcama büyüklüğüne göre azalan sırala
    projected_channels.sort(key=lambda c: c["spend"], reverse=True)

    return {
        "lookback_days": lookback_days,
        "total_spend": _r2(total_spend),
        "channels": projected_channels,
        "projected_totals": {
            "spend": _r2(total_spend),
            "impressions": proj_impressions,
            "clicks": proj_clicks,
            "conversions": proj_conversions,
            "conversion_value": proj_conv_value,
            "roas": proj_roas,
            "cpa": proj_cpa,
            "cvr": proj_cvr,
        },
        "baseline_totals": {
            "spend": base_spend,
            "impressions": base_impressions,
            "clicks": base_clicks,
            "conversions": base_conversions,
            "conversion_value": base_conv_value,
            "roas": base_roas,
            "cpa": base_cpa,
            "cvr": base_cvr,
        },
        "deltas": deltas,
        "assumptions": assumptions,
    }
