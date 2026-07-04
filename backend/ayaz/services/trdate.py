"""Türkçe tarih/saat biçimlendirme — tek kaynak.

Kullanıcıya dönük TÜM tarihler bu modülden geçmeli; ham ISO ("2026-07-01")
veya İngilizce ay adı (strftime '%B' → "July") arayüze/rapora SIZMAMALI.
Türkiye sabit UTC+3 kullanır (yaz saati uygulamıyor).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TR_MONTHS_FULL: dict[int, str] = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

TR_MONTHS_SHORT: dict[int, str] = {
    1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
    7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara",
}

_ISTANBUL = timezone(timedelta(hours=3))


def tr_date(value: date | str) -> str:
    """date/'2026-07-01' → '1 Temmuz 2026'. Parse hatasında girdiyi döndürür."""
    d = _coerce_date(value)
    if d is None:
        return str(value)
    return f"{d.day} {TR_MONTHS_FULL[d.month]} {d.year}"


def tr_date_short(value: date | str) -> str:
    """date/'2026-07-01' → '1 Tem 2026' (dar alanlar için)."""
    d = _coerce_date(value)
    if d is None:
        return str(value)
    return f"{d.day} {TR_MONTHS_SHORT[d.month]} {d.year}"


def tr_datetime(value: datetime | str) -> str:
    """ISO datetime → '4 Tem 2026 15:34' (Europe/Istanbul, UTC+3)."""
    dt: datetime | None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return str(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_ISTANBUL)
    return (
        f"{dt.day} {TR_MONTHS_SHORT[dt.month]} {dt.year} "
        f"{dt.hour:02d}:{dt.minute:02d}"
    )


def _coerce_date(value: date | str) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
