from scripts.btst_momentum_threshold_rollout_assessment import build_momentum_threshold_rollout_assessment


def test_momentum_threshold_rollout_promotes_when_backtest_and_windows_clear_guardrails() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "promote"
    assert assessment["blockers"] == []


def test_momentum_threshold_rollout_holds_when_window_validation_keeps_baseline() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 1,
        "variant_supports_t1_count": 0,
        "mixed_count": 2,
        "recommendation": "Baseline should remain the default: the variant loses T+1 edge in at least one window without offsetting T+1 improvement elsewhere.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "window_validation_keeps_baseline" in assessment["blockers"]


def test_momentum_threshold_rollout_holds_when_backtest_payoff_is_below_round82_reference() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.38,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "backtest_payoff_below_round82_reference" in assessment["blockers"]


def test_momentum_threshold_rollout_holds_when_backtest_win_rate_is_below_round82_reference() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.47,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "backtest_win_rate_below_round82_reference" in assessment["blockers"]
