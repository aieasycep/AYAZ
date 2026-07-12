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
    blended_roas,
    compute_derived_metrics,
    cpa,
    cpc,
    ctr,
    effective_spend,
    resolve_headline_metric,
    roas,
    split_channel_totals_by_source,
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


# ── split_channel_totals_by_source ─────────────────────────────────────────────
#
# Regression tests for the "kaynak-tipi mutabakatı" fix: Google Ads/Meta Ads
# (ad) and GA4/Search Console (analytics) write to the same fact-table
# columns, so a blind cross-channel SUM double-counts GA4's conversions on
# top of what the ad platforms already report. These tests lock in the split.


def _row(*, spend="0", impressions="0", clicks="0", conversions="0", cv="0") -> dict:
    return {
        "spend": Decimal(spend),
        "impressions": Decimal(impressions),
        "clicks": Decimal(clicks),
        "conversions": Decimal(conversions),
        "conversion_value": Decimal(cv),
    }


class TestSplitChannelTotalsBySource:
    def test_empty_input_all_zeros(self) -> None:
        result = split_channel_totals_by_source({})
        for key, value in result.items():
            assert value == Decimal(0), f"{key} should be 0"

    def test_single_ad_channel_all_in_ad_bucket(self) -> None:
        data = {
            "google_ads": _row(
                spend="1000", impressions="10000", clicks="500",
                conversions="20", cv="4000",
            )
        }
        result = split_channel_totals_by_source(data)
        assert result["ad_spend"] == Decimal("1000")
        assert result["ad_conversions"] == Decimal("20")
        assert result["ad_conversion_value"] == Decimal("4000")
        assert result["analytics_conversions"] == Decimal(0)
        assert result["analytics_conversion_value"] == Decimal(0)
        assert result["total_spend"] == Decimal("1000")

    def test_single_analytics_channel_all_in_analytics_bucket(self) -> None:
        data = {
            "ga4": _row(impressions="5000", conversions="15", cv="3000"),
        }
        result = split_channel_totals_by_source(data)
        assert result["analytics_conversions"] == Decimal("15")
        assert result["analytics_conversion_value"] == Decimal("3000")
        assert result["ad_conversions"] == Decimal(0)
        assert result["ad_conversion_value"] == Decimal(0)
        # GA4 has structurally zero spend/clicks (sessions != clicks).
        assert result["ad_spend"] == Decimal(0)
        assert result["ad_clicks"] == Decimal(0)

    def test_mixed_ad_and_analytics_no_double_counting(self) -> None:
        """The core bug scenario: google_ads (ad) + ga4 (analytics) both
        report conversions on the SAME period. ad/analytics buckets must
        stay separate — never summed into one 'conversions' number here."""
        data = {
            "google_ads": _row(
                spend="1000", clicks="500", conversions="20", cv="4000",
            ),
            "ga4": _row(clicks="0", conversions="15", cv="3000"),
        }
        result = split_channel_totals_by_source(data)
        assert result["ad_conversions"] == Decimal("20")
        assert result["analytics_conversions"] == Decimal("15")
        # Neither bucket contains the other's contribution.
        assert result["ad_conversions"] != Decimal("35")
        assert result["ad_conversion_value"] == Decimal("4000")
        assert result["analytics_conversion_value"] == Decimal("3000")
        assert result["ad_spend"] == Decimal("1000")
        assert result["total_spend"] == Decimal("1000")  # GA4 contributes 0

    def test_search_console_clicks_excluded_from_ad_clicks(self) -> None:
        """Search Console reports real organic clicks — these must NOT be
        counted as ad_clicks (would dilute conversion-rate scoring)."""
        data = {
            "google_ads": _row(clicks="500", conversions="20"),
            "search_console": _row(clicks="1000", impressions="50000"),
        }
        result = split_channel_totals_by_source(data)
        assert result["ad_clicks"] == Decimal("500")
        assert result["analytics_clicks"] == Decimal("1000")
        assert result["total_clicks"] == Decimal("1500")

    def test_unknown_channel_key_defaults_to_ad_bucket(self) -> None:
        data = {"brand_new_platform": _row(spend="500", conversions="10")}
        result = split_channel_totals_by_source(data)
        assert result["ad_spend"] == Decimal("500")
        assert result["ad_conversions"] == Decimal("10")

    def test_multiple_ad_channels_summed_together(self) -> None:
        data = {
            "google_ads": _row(spend="1000", conversions="20", cv="4000"),
            "meta_ads": _row(spend="500", conversions="10", cv="2000"),
        }
        result = split_channel_totals_by_source(data)
        assert result["ad_spend"] == Decimal("1500")
        assert result["ad_conversions"] == Decimal("30")
        assert result["ad_conversion_value"] == Decimal("6000")


# ── resolve_headline_metric ─────────────────────────────────────────────────────


class TestResolveHeadlineMetric:
    def test_analytics_value_wins_when_nonzero(self) -> None:
        result = resolve_headline_metric(Decimal("15"), Decimal("20"))
        assert result == Decimal("15")

    def test_falls_back_to_ad_when_analytics_zero(self) -> None:
        result = resolve_headline_metric(Decimal("0"), Decimal("20"))
        assert result == Decimal("20")

    def test_both_zero_returns_zero(self) -> None:
        result = resolve_headline_metric(Decimal("0"), Decimal("0"))
        assert result == Decimal(0)

    def test_analytics_nonzero_ad_zero(self) -> None:
        """GA4 present but no ad spend/conversions this period — still uses GA4."""
        result = resolve_headline_metric(Decimal("15"), Decimal("0"))
        assert result == Decimal("15")


# ── blended_roas ─────────────────────────────────────────────────────────────────


class TestBlendedRoas:
    def test_uses_analytics_revenue_over_ad_spend(self) -> None:
        """Core formula: analytics (GA4) revenue / ad-only spend."""
        result = blended_roas(
            ad_spend=Decimal("1000"),
            analytics_conversion_value=Decimal("5000"),
        )
        assert result == Decimal("5")

    def test_no_fallback_by_default_ga4_zero_gives_zero(self) -> None:
        """Without an explicit ad_conversion_value fallback (attribution
        endpoint usage), GA4=0 must yield 0 — NOT silently reuse ad revenue."""
        result = blended_roas(
            ad_spend=Decimal("1000"),
            analytics_conversion_value=Decimal("0"),
        )
        assert result == Decimal(0)

    def test_falls_back_to_ad_conversion_value_when_provided(self) -> None:
        """Dashboard/executive usage: explicit ad_conversion_value fallback
        keeps the headline ROAS from zeroing out when GA4 isn't connected."""
        result = blended_roas(
            ad_spend=Decimal("1000"),
            analytics_conversion_value=Decimal("0"),
            ad_conversion_value=Decimal("4000"),
        )
        assert result == Decimal("4")

    def test_analytics_wins_even_when_ad_conversion_value_provided(self) -> None:
        result = blended_roas(
            ad_spend=Decimal("1000"),
            analytics_conversion_value=Decimal("3000"),
            ad_conversion_value=Decimal("4000"),
        )
        assert result == Decimal("3")

    def test_zero_ad_spend_returns_zero_never_raises(self) -> None:
        result = blended_roas(
            ad_spend=Decimal("0"),
            analytics_conversion_value=Decimal("5000"),
        )
        assert result == Decimal(0)

    def test_return_type_is_decimal(self) -> None:
        result = blended_roas(
            ad_spend=Decimal("100"), analytics_conversion_value=Decimal("200")
        )
        assert isinstance(result, Decimal)
