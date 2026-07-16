"""Unit tests for the shared Turkish number-formatting module.

trformat.py is the single source for ALL user-facing numbers produced by the
backend (imported by 12+ services). A regression here silently corrupts every
AI text, report, and dashboard card, so it deserves direct coverage.

TR convention under test: thousands separator = dot, decimal separator = comma,
percent sign is a PREFIX.
"""

from ayaz.services.trformat import tr_int, tr_num, tr_pct, tr_roas, tr_tl


class TestTrNum:
    def test_thousands_dot_decimal_comma(self):
        assert tr_num(1234567.89) == "1.234.567,89"

    def test_default_two_decimals(self):
        assert tr_num(3.5) == "3,50"

    def test_zero_decimals(self):
        assert tr_num(4682.32, 0) == "4.682"

    def test_small_value(self):
        assert tr_num(3.244) == "3,24"

    def test_negative(self):
        assert tr_num(-1234.5) == "-1.234,50"

    def test_zero(self):
        assert tr_num(0) == "0,00"

    def test_no_english_comma_leaks(self):
        # 398123 must never render as the EN "398,123"
        assert tr_num(398123, 0) == "398.123"
        assert "," not in tr_num(398123, 0)


class TestTrInt:
    def test_rounds_and_groups(self):
        assert tr_int(4682.32) == "4.682"

    def test_large(self):
        assert tr_int(1234567) == "1.234.567"


class TestTrTl:
    def test_prefix_symbol_and_grouping(self):
        assert tr_tl(398123) == "₺398.123"

    def test_with_decimals(self):
        assert tr_tl(1234.5, 2) == "₺1.234,50"


class TestTrPct:
    def test_prefix_sign_and_comma(self):
        # % is a PREFIX in Turkish, decimal is a comma
        assert tr_pct(9.9) == "%9,9"

    def test_two_decimals(self):
        assert tr_pct(2.115, 2) == "%2,11" or tr_pct(2.115, 2) == "%2,12"

    def test_zero_decimals(self):
        assert tr_pct(6.0, 0) == "%6"

    def test_sign_is_prefix_not_suffix(self):
        assert tr_pct(15.0).startswith("%")
        assert not tr_pct(15.0).endswith("%")


class TestTrRoas:
    def test_two_decimals_and_x_suffix(self):
        assert tr_roas(3.27) == "3,27x"

    def test_whole_number(self):
        assert tr_roas(4.0) == "4,00x"
