"""Command Center at-risk counting must respect spend (budget) semantics.

_is_at_risk historically short-circuited to "not at risk" whenever a goal was
>= 100% of target — correct for GROWTH goals (target met = success) but wrong
for SPEND goals, where 120% of budget is exactly the risk. The metric-aware
guard added to fix this had no test; this locks it in.
"""

from ayaz.services.command_center import _goal_with_pct, _is_at_risk


class TestIsAtRiskSpendSemantics:
    def test_overspent_budget_counts_as_at_risk(self):
        # 120% of a budget → the goal service returns ratio 1.2
        goal = _goal_with_pct(
            {"name": "Aylık Bütçe", "metric": "spend",
             "status": "off_track", "pct_to_target": 1.2}
        )
        assert _is_at_risk(goal) is True

    def test_achieved_growth_goal_not_at_risk(self):
        # A 120%-complete revenue goal IS a success — shortcut still applies
        goal = _goal_with_pct(
            {"name": "Gelir Hedefi", "metric": "conversion_value",
             "status": "at_risk", "pct_to_target": 1.2}
        )
        assert _is_at_risk(goal) is False

    def test_behind_growth_goal_at_risk(self):
        goal = _goal_with_pct(
            {"name": "ROAS Hedefi", "metric": "roas",
             "status": "off_track", "pct_to_target": 0.55}
        )
        assert _is_at_risk(goal) is True

    def test_on_track_status_not_at_risk(self):
        goal = _goal_with_pct(
            {"name": "İyi Giden", "metric": "spend",
             "status": "on_track", "pct_to_target": 0.9}
        )
        assert _is_at_risk(goal) is False


class TestGoalWithPct:
    def test_ratio_scaled_to_percent(self):
        out = _goal_with_pct({"pct_to_target": 0.45})
        assert out["pct_to_target"] == 45.0

    def test_missing_ratio_defaults_zero(self):
        out = _goal_with_pct({"name": "x"})
        assert out["pct_to_target"] == 0.0
