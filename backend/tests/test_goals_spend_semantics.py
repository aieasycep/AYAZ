"""Spend-goal (budget) semantics — the two-sided status band and the
overrun/forecast-overrun recommendation branches.

These behaviours were introduced when "spend" goals were reinterpreted as
BUDGETS (overshooting is bad, not a success). They previously had no direct
test, so a regression could silently flip a budget-overrun warning back into
"you're behind, spend more" — the exact bug the ultracode verification caught.
"""

from ayaz.services.goals import (
    SPEND_AT_RISK_OVERRUN,
    SPEND_OFF_TRACK_OVERRUN,
    _build_recommendation,
    _classify_status,
)


class TestClassifyStatusSpend:
    def test_spend_within_band_is_on_track(self):
        # forecast == target → not an overrun
        assert _classify_status(100_000, 100_000, metric="spend") == "on_track"

    def test_spend_small_overrun_within_tolerance_on_track(self):
        # 3% over, below the 5% at-risk threshold
        assert _classify_status(103_000, 100_000, metric="spend") == "on_track"

    def test_spend_moderate_overrun_at_risk(self):
        # 10% over → between 1.05 and 1.20
        assert _classify_status(110_000, 100_000, metric="spend") == "at_risk"

    def test_spend_large_overrun_off_track(self):
        # 35% over → beyond 1.20
        assert _classify_status(135_000, 100_000, metric="spend") == "off_track"

    def test_thresholds_are_ordered(self):
        assert SPEND_AT_RISK_OVERRUN < SPEND_OFF_TRACK_OVERRUN

    def test_growth_goal_uses_one_sided_band(self):
        # A non-spend goal forecasting 135% is a GOOD outcome (on track)
        assert _classify_status(135_000, 100_000, metric="roas") == "on_track"


class TestBuildRecommendationSpend:
    def _rec(self, **kw):
        base = dict(
            metric="spend",
            status="off_track",
            pct_to_target=0.45,
            target_value=100_000,
            current_value=45_000,
            days_elapsed=15,
            days_total=30,
            days_remaining=15,
            forecast_value=135_000,
        )
        base.update(kw)
        return _build_recommendation(**base)

    def test_mid_period_forecast_overrun_says_slow_down_not_speed_up(self):
        msg = self._rec()
        assert "aşılacak" in msg
        assert "düşürün" in msg
        # must NOT tell the user to spend more / catch up
        assert "gerisindesiniz" not in msg
        assert "hızlanmak" not in msg

    def test_realized_overrun_end_of_period(self):
        msg = self._rec(
            pct_to_target=1.395, current_value=251_192, target_value=180_000,
            days_remaining=0, forecast_value=251_192,
        )
        assert "aşıldı" in msg

    def test_small_realized_overrun_no_alarm_next_to_on_track_badge(self):
        # 3% realized overrun stays on_track — the copy must not scream "aşıldı"
        msg = self._rec(
            status="on_track", pct_to_target=1.03,
            current_value=103_000, target_value=100_000,
            days_remaining=0, forecast_value=103_000,
        )
        assert "aşıldı" not in msg
        assert "aşılıyor" not in msg
