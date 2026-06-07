"""Crisis handler unit tests — evaluate_crisis_response() logic.

Covers:
  - Normal mode (no triggers)
  - Defense mode (hs300 <= -5% or limit_down > 500)
  - Shrink mode (low volume)
  - Drawdown warning (-10%)
  - Recovery mode / forced reduce (-15%)
  - Combined triggers: recovery + shrink must not lose forced_reduce_ratio
  - Combined triggers: defense + recovery must preserve strongest response
"""

from __future__ import annotations

from src.execution.crisis_handler import evaluate_crisis_response


class TestCrisisHandlerNormalMode:
    def test_no_triggers_returns_normal(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.01,
            limit_down_count=0,
            recent_total_volumes=[8000, 9000, 10000],
            drawdown_pct=-0.02,
        )
        assert result["mode"] == "normal"
        assert result["position_cap"] == 1.0
        assert result["pause_new_buys"] is False
        assert result["forced_reduce_ratio"] == 0.0
        assert result["alerts"] == []

    def test_mild_negative_return_still_normal(self):
        result = evaluate_crisis_response(
            hs300_daily_return=-0.03,
            limit_down_count=10,
            recent_total_volumes=[6000, 7000, 8000],
            drawdown_pct=-0.05,
        )
        assert result["mode"] == "normal"


class TestCrisisHandlerDefenseMode:
    def test_hs300_crash_triggers_defense(self):
        result = evaluate_crisis_response(
            hs300_daily_return=-0.06,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "defense"
        assert result["position_cap"] == 0.3
        assert result["pause_new_buys"] is True
        assert "crisis_defense_mode" in result["alerts"]

    def test_limit_down_500_triggers_defense(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=501,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "defense"
        assert "crisis_defense_mode" in result["alerts"]

    def test_hs300_exactly_negative_five_pct_triggers_defense(self):
        result = evaluate_crisis_response(
            hs300_daily_return=-0.05,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "defense"

    def test_limit_down_exactly_500_triggers_defense(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=500,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "defense"


class TestCrisisHandlerShrinkMode:
    def test_low_volume_triggers_shrink(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[3000, 3500, 3999],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "shrink"
        assert result["position_cap"] <= 0.5
        assert result["pause_new_buys"] is True
        assert "low_volume_shrink" in result["alerts"]

    def test_low_volume_requires_at_least_3_data_points(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[3000, 3500],
            drawdown_pct=0.0,
        )
        assert result["mode"] == "normal"
        assert "low_volume_shrink" not in result["alerts"]


class TestCrisisHandlerDrawdownWarning:
    def test_drawdown_10pct_triggers_warning(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=-0.10,
        )
        assert result["pause_new_buys"] is True
        assert "drawdown_warning" in result["alerts"]

    def test_drawdown_9pct_no_warning(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=-0.09,
        )
        assert result["pause_new_buys"] is False
        assert "drawdown_warning" not in result["alerts"]


class TestCrisisHandlerRecoveryMode:
    def test_drawdown_15pct_triggers_recovery_forced_reduce(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=-0.15,
        )
        assert result["mode"] == "recovery"
        assert result["forced_reduce_ratio"] == 0.5
        assert result["recovery_cooldown_days"] == 5
        assert result["pause_new_buys"] is True
        assert "drawdown_forced_reduce" in result["alerts"]

    def test_drawdown_14pct_no_recovery(self):
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=-0.14,
        )
        assert result["mode"] == "normal"
        assert result["forced_reduce_ratio"] == 0.0


class TestCrisisHandlerCombinedTriggers:
    def test_recovery_plus_low_volume_preserves_forced_reduce_ratio(self):
        """BUG: shrink running after recovery overwrites mode='recovery' with mode='shrink',
        losing forced_reduce_ratio=0.5. After fix, recovery should take precedence."""
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[3000, 3500, 3999],
            drawdown_pct=-0.18,
        )
        # Both shrink and recovery triggered.
        # Recovery is more severe — forced_reduce_ratio must be preserved.
        assert result["forced_reduce_ratio"] == 0.5
        assert result["pause_new_buys"] is True
        assert "drawdown_forced_reduce" in result["alerts"]
        assert "low_volume_shrink" in result["alerts"]

    def test_defense_plus_recovery_preserves_both_escalation(self):
        """Defense mode + recovery drawdown — recovery must override defense since it's more severe."""
        result = evaluate_crisis_response(
            hs300_daily_return=-0.06,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=-0.16,
        )
        assert result["forced_reduce_ratio"] == 0.5
        assert result["pause_new_buys"] is True
        assert "crisis_defense_mode" in result["alerts"]
        assert "drawdown_forced_reduce" in result["alerts"]

    def test_defense_plus_shrink_position_cap_is_stricter(self):
        """defense sets 0.3, shrink min(0.3, 0.5) = 0.3."""
        result = evaluate_crisis_response(
            hs300_daily_return=-0.06,
            limit_down_count=0,
            recent_total_volumes=[3000, 3500, 3999],
            drawdown_pct=0.0,
        )
        assert result["position_cap"] <= 0.3
