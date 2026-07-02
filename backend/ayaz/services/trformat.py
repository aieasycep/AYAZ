"""Türkçe sayı biçimlendirme yardımcıları — kullanıcıya dönük metinler için.

Backend'in ürettiği Türkçe cümlelerdeki TÜM sayılar bu modülden geçmeli.
``f"{x:,.0f}"`` gibi İngilizce biçimler ("398,123") Türkçe okuyucuya
"398 virgül 123" olarak yanlış okunur; ondalık noktalı "3.244" ise binlik
sanılır. Buradaki yardımcılar Türkçe ayraç kuralını uygular:
binlik = nokta, ondalık = virgül.
"""

from __future__ import annotations


def tr_num(value: float, decimals: int = 2) -> str:
    """1234567.89 → '1.234.567,89'."""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def tr_int(value: float) -> str:
    """4682.32 → '4.682' (adet metrikleri için)."""
    return tr_num(value, 0)


def tr_tl(value: float, decimals: int = 0) -> str:
    """398123 → '₺398.123'."""
    return "₺" + tr_num(value, decimals)


def tr_pct(value: float, decimals: int = 1) -> str:
    """9.9 → '%9,9' (işaret önde — Türkçe yazım)."""
    return "%" + tr_num(value, decimals)


def tr_roas(value: float) -> str:
    """3.27 → '3,27x'."""
    return tr_num(value, 2) + "x"
