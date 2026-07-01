"""Unit tests for the metric layer (ayaz/services/metrics.py).

All tests are pure-function: no DB, no network, no fixtures on disk.
Decimal arithmetic is used throughout to match the service contract.

Divide-by-zero policy
---------------------
All derived metrics return ``Decimal("0")`` (not None) when the denominator
is zero.  These tests validate that explicitly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ayaz.services.metrics import (
    compute_derived_metrics,
    cpa,
    cpc,
    ctr,
    effective_spend,
    roas,
)


# ── effective_spend ───────────────────────────────────────────────────────────


class TestEffectiveSpend:
    def test_prefers_base_ccy_when_nonzero(self) -> None:
        result = effective_spend(Decimal("100"), Decimal("350"))
        assert result == Decimal("350")

    def test_falls_back_to_cost_raw_when_base_is_zero(self) -> None:
        result = effective_spend(Decimal("100"), Decimal("0"))
        assert result == Decimal("100")

    def test_both_zero_returns_zero(self) -> None:
        result = effective_spend(Decimal("0"), Decimal("0"))
        assert result == Decimal("0")

    def test_base_zero_string_variant(self) -> None:
        """Decimal('0.000') should also be treated as zero."""
        result = effective_spend(Decimal("50.00"), Decimal("0.000"))
        assert result == Decimal("50.00")


# ── ctr ───────────────────────────────────────────────────────────────────────


class TestCtr:
    def test_normal_case(self) -> None:
        result = ctr(Decimal("1000"), Decimal("50"))
        assert result == Decimal("0.05")

    def test_zero_impressions_returns_zero(self) -> None:
        result = ctr(Decimal("0"), Decimal("50"))
        assert result == Decimal(0)

    def test_zero_clicks_returns_zero_ctr(self) -> None:
        result = ctr(Decimal("1000"), Decimal("0"))
        assert result == Decimal("0")

    def test_return_type_is_decimal(self) -> None:
        result = ctr(Decimal("500"), Decimal("10"))
        assert isinstance(result, Decimal)

    def test_high_ctr(self) -> None:
        # 100% CTR
        result = ctr(Decimal("100"), Decimal("100"))
        assert result == Decimal("1")


# ── cpc ───────────────────────────────────────────────────────────────────────


class TestCpc:
    def test_normal_case(self) -> None:
        result = cpc(Decimal("500"), Decimal("100"))
        assert result == Decimal("5")

    def test_zero_clicks_returns_zero(self) -> None:
        result = cpc(Decimal("500"), Decimal("0"))
        assert result == Decimal(0)

    def test_zero_spend_with_clicks(self) -> None:
        result = cpc(Decimal("0"), Decimal("100"))
        assert result == Decimal("0")

    def test_return_type_is_decimal(self) -> None:
        result = cpc(Decimal("100"), Decimal("10"))
        assert isinstance(result, Decimal)

    def test_fractional_cpc(self) -> None:
        result = cpc(Decimal("1"), Decimal("3"))
        # 1/3 — just check it's close (Decimal division is exact to precision)
        assert result == Decimal("1") / Decimal("3")


# ── cpa ───────────────────────────────────────────────────────────────────────


class TestCpa:
    def test_normal_case(self) -> None:
        result = cpa(Decimal("1000"), Decimal("10"))
        assert result == Decimal("100")

    def test_zero_conversions_returns_zero(self) -> None:
        result = cpa(Decimal("1000"), Decimal("0"))
        assert result == Decimal(0)

    def test_zero_spend_with_conversions(self) -> None:
        result = cpa(Decimal("0"), Decimal("5"))
        assert result == Decimal("0")

    def test_return_type_is_decimal(self) -> None:
        result = cpa(Decimal("300"), Decimal("3"))
        assert isinstance(result, Decimal)


# ── roas ──────────────────────────────────────────────────────────────────────


class TestRoas:
    def test_normal_case(self) -> None:
        result = roas(Decimal("5000"), Decimal("1000"))
        assert result == Decimal("5")

    def test_zero_spend_returns_zero(self) -> None:
        result = roas(Decimal("5000"), Decimal("0"))
        assert result == Decimal(0)

    def test_zero_conversion_value_with_spend(self) -> None:
        result = roas(Decimal("0"), Decimal("500"))
        assert result == Decimal("0")

    def test_both_zero_returns_zero(self) -> None:
        result = roas(Decimal("0"), Decimal("0"))
        assert result == Decimal(0)

    def test_return_type_is_decimal(self) -> None:
        result = roas(Decimal("2000"), Decimal("400"))
        assert isinstance(result, Decimal)

    def test_roas_below_one(self) -> None:
        """ROAS < 1 means losing money — still valid."""
        result = roas(Decimal("50"), Decimal("200"))
        assert result == Decimal("0.25")


# ── compute_derived_metrics ───────────────────────────────────────────────────


class TestComputeDerivedMetrics:
    def _run(self, *, imp, clicks, spend, conv, cv):
        return compute_derived_metrics(
            impressions=Decimal(str(imp)),
            clicks=Decimal(str(clicks)),
            spend=Decimal(str(spend)),
            conversions=Decimal(str(conv)),
            conversion_value=Decimal(str(cv)),
        )

    def test_all_zeros_no_exception(self) -> None:
        result = self._run(imp=0, clicks=0, spend=0, conv=0, cv=0)
        for key in ("ctr", "cpc", "cpa", "roas"):
            assert result[key] == Decimal(0), f"{key} should be 0"

    def test_normal_values(self) -> None:
        result = self._run(
            imp=100_000, clicks=2_000, spend=1_000, conv=50, cv=5_000
        )
        # CTR = 2000 / 100000 = 0.02
        assert result["ctr"] == Decimal("2000") / Decimal("100000")
        # CPC = 1000 / 2000 = 0.5
        assert result["cpc"] == Decimal("0.5")
        # CPA = 1000 / 50 = 20
        assert result["cpa"] == Decimal("20")
        # ROAS = 5000 / 1000 = 5
        assert result["roas"] == Decimal("5")

    def test_return_contains_all_keys(self) -> None:
        result = self._run(imp=1, clicks=1, spend=1, conv=1, cv=1)
        for key in ("ctr", "cpc", "cpa", "roas"):
            assert key in result

    def test_all_values_are_decimal(self) -> None:
        result = self._run(imp=500, clicks=10, spend=100, conv=2, cv=200)
        for key, val in result.items():
            assert isinstance(val, Decimal), f"{key} should be Decimal, got {type(val)}"

    def test_zero_impressions_zero_clicks_zero_spend(self) -> None:
        """Edge case: brand-new account with no data."""
        result = self._run(imp=0, clicks=0, spend=0, conv=0, cv=0)
        assert result["ctr"] == Decimal(0)
        assert result["cpc"] == Decimal(0)
        assert result["cpa"] == Decimal(0)
        assert result["roas"] == Decimal(0)

    def test_impressions_but_no_clicks(self) -> None:
        result = self._run(imp=10_000, clicks=0, spend=500, conv=0, cv=0)
        assert result["ctr"] == Decimal(0)
        assert result["cpc"] == Decimal(0)  # 0 clicks → 0
        assert result["cpa"] == Decimal(0)
        assert result["roas"] == Decimal(0)  # 0 conv_value → 0

    def test_spend_no_conversions(self) -> None:
        """Spend occurred but no conversions — CPA should be 0 (not inf)."""
        result = self._run(imp=5000, clicks=100, spend=200, conv=0, cv=0)
        assert result["cpa"] == Decimal(0)

    def test_roas_with_zero_spend_but_conv_value(self) -> None:
        """Organic / zero-cost attribution — ROAS is 0 (undefined, not inf)."""
        result = self._run(imp=1000, clicks=50, spend=0, conv=5, cv=500)
        assert result["roas"] == Decimal(0)
