"""Müşteri Yolculuğu / Dönüşüm Hunisi servisi — 5 aşamalı e-ticaret hunisi.

Her aşamada ConversionEvent satır sayısını gruplar; önceki aşamaya göre
dönüşüm oranı (conversion_from_prev_pct), düşüş (dropoff_pct) ve giriş
aşamasına göre pay (share_of_entry_pct) hesaplar.

Genel API
---------
FUNNEL_STAGES   : Sıralı (key, label) çiftleri
build_funnel()  : Kilit şemalı dict döner

Kiracı Yalıtımı
---------------
Tüm sorgular tenant_id filtresiyle kısıtlanır — çapraz kiracı veri sızıntısı
mümkün değildir.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Huni aşamaları (sıralı) ───────────────────────────────────────────────────

FUNNEL_STAGES: list[tuple[str, str]] = [
    ("PageView", "Sayfa Görüntüleme"),
    ("ViewContent", "Ürün Görüntüleme"),
    ("AddToCart", "Sepete Ekleme"),
    ("InitiateCheckout", "Ödeme Başlatma"),
    ("Purchase", "Satın Alma"),
]

_FUNNEL_KEYS: set[str] = {key for key, _ in FUNNEL_STAGES}


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────


def _safe_pct(numerator: int, denominator: int) -> float | None:
    """Yüzde hesaplar; denominator sıfırsa None döner."""
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


# ── Genel API ─────────────────────────────────────────────────────────────────


def build_funnel(
    db: "Session",
    tenant_id: uuid.UUID,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Kiracı için Dönüşüm Hunisi raporunu oluşturur.

    Yalnızca FUNNEL_STAGES içindeki 5 event_name katılır; diğerleri yoksayılır.
    Tarih filtresi uygulandığında ConversionEvent.event_time (ISO-8601 metin)
    string karşılaştırmasıyla filtrelenir — consent_center ile aynı yöntem.

    Parametreler
    ------------
    db:
        Mevcut isteğe kapsamlı SQLAlchemy session.
    tenant_id:
        Kiracı UUID. Tüm sorgular bu kiracıyla sınırlıdır.
    date_from:
        YYYY-MM-DD biçiminde başlangıç tarihi (dahil). None ise filtre yok.
    date_to:
        YYYY-MM-DD biçiminde bitiş tarihi (dahil, T23:59:59 sonuna kadar).
        None ise filtre yok.

    Döner
    -----
    Aşağıdaki sabit şemayı taşıyan dict::

        {
          "period": {"date_from": str|null, "date_to": str|null},
          "total_events": int,
          "stages": [...],
          "entry_count": int,
          "final_count": int,
          "overall_conversion_pct": float,
          "biggest_dropoff": {"from_label": str, "to_label": str, "dropoff_pct": float} | null,
        }
    """
    from sqlalchemy import func, select

    from ayaz.models.tracking import ConversionEvent

    # ── Aşama bazında sayım sorgusu ───────────────────────────────────────────
    stmt = (
        select(ConversionEvent.event_name, func.count().label("cnt"))
        .where(
            ConversionEvent.tenant_id == tenant_id,
            ConversionEvent.event_name.in_(_FUNNEL_KEYS),
        )
    )

    if date_from is not None:
        stmt = stmt.where(ConversionEvent.event_time >= date_from)
    if date_to is not None:
        # Kapsayan bitiş: o günün sonuna kadar — consent_center ile aynı yöntem
        stmt = stmt.where(ConversionEvent.event_time <= date_to + "T23:59:59")

    stmt = stmt.group_by(ConversionEvent.event_name)

    rows = db.execute(stmt).all()
    counts_by_name: dict[str, int] = {row[0]: row[1] for row in rows}

    # ── Aşama listesi oluştur ─────────────────────────────────────────────────
    entry_count = counts_by_name.get(FUNNEL_STAGES[0][0], 0)
    stages: list[dict] = []

    prev_count: int | None = None
    biggest_dropoff_pct: float | None = None
    biggest_dropoff: dict | None = None

    for i, (key, label) in enumerate(FUNNEL_STAGES):
        count = counts_by_name.get(key, 0)

        if i == 0:
            # İlk aşama — önceki aşamadan dönüşüm tanımsız
            conversion_from_prev_pct = None
            dropoff_count = 0
            dropoff_pct = None
            share_of_entry_pct = 100.0 if entry_count > 0 else 0.0
        else:
            prev = prev_count if prev_count is not None else 0
            conversion_from_prev_pct = _safe_pct(count, prev)
            dropoff_count = prev - count
            if conversion_from_prev_pct is not None:
                dropoff_pct = round(100.0 - conversion_from_prev_pct, 2)
            else:
                dropoff_pct = None
            share_of_entry_pct = _safe_pct(count, entry_count) if entry_count > 0 else 0.0

            # En büyük düşüşü izle
            if dropoff_pct is not None and (
                biggest_dropoff_pct is None or dropoff_pct > biggest_dropoff_pct
            ):
                biggest_dropoff_pct = dropoff_pct
                prev_label = FUNNEL_STAGES[i - 1][1]
                biggest_dropoff = {
                    "from_label": prev_label,
                    "to_label": label,
                    "dropoff_pct": dropoff_pct,
                }

        stages.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "conversion_from_prev_pct": conversion_from_prev_pct,
                "dropoff_count": dropoff_count if i > 0 else 0,
                "dropoff_pct": dropoff_pct,
                "share_of_entry_pct": share_of_entry_pct,
            }
        )
        prev_count = count

    final_count = counts_by_name.get(FUNNEL_STAGES[-1][0], 0)
    total_events = sum(counts_by_name.get(k, 0) for k, _ in FUNNEL_STAGES)

    overall_conversion_pct = (
        round(final_count / entry_count * 100, 2) if entry_count > 0 else 0.0
    )

    return {
        "period": {
            "date_from": date_from,
            "date_to": date_to,
        },
        "total_events": total_events,
        "stages": stages,
        "entry_count": entry_count,
        "final_count": final_count,
        "overall_conversion_pct": overall_conversion_pct,
        "biggest_dropoff": biggest_dropoff,
    }
