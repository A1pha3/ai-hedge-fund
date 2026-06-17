"""Tests for P3-2: weight_calibration module."""

from src.research.weight_calibration import (
    _calibrate_weights,
    _infer_strategy,
    compute_weight_calibration,
    DEFAULT_EQUAL_WEIGHTS,
    MIN_OBSERVATIONS_FOR_CALIBRATION,
    render_weight_calibration,
    StrategyICSummary,
    WEIGHT_FLOOR,
    WeightCalibrationResult,
)

# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestInferStrategy:
    def test_trend_prefix(self):
        assert _infer_strategy("trend.momentum_20d") == "trend"

    def test_fundamental_prefix(self):
        assert _infer_strategy("fundamental.pe_ratio") == "fundamental"

    def test_mean_reversion_prefix(self):
        assert _infer_strategy("mean_reversion.bounce_2d") == "mean_reversion"

    def test_event_sentiment_prefix(self):
        assert _infer_strategy("event_sentiment.news") == "event_sentiment"

    def test_unknown_prefix(self):
        assert _infer_strategy("random.xyz") == "unknown"

    def test_no_dot(self):
        assert _infer_strategy("trend_indicator") == "unknown"


class TestCalibrateWeights:
    def test_uniform_ir_yields_uniform_weights(self):
        summaries = [
            StrategyICSummary(strategy_name="trend", avg_ir=0.5),
            StrategyICSummary(strategy_name="mean_reversion", avg_ir=0.5),
            StrategyICSummary(strategy_name="fundamental", avg_ir=0.5),
            StrategyICSummary(strategy_name="event_sentiment", avg_ir=0.5),
        ]
        result = _calibrate_weights(summaries, DEFAULT_EQUAL_WEIGHTS)
        # All equal → weights should be 0.25
        for v in result.values():
            assert abs(v - 0.25) < 0.01

    def test_higher_ir_gets_higher_weight(self):
        summaries = [
            StrategyICSummary(strategy_name="trend", avg_ir=2.0),  # Best
            StrategyICSummary(strategy_name="mean_reversion", avg_ir=0.0),  # Zero
            StrategyICSummary(strategy_name="fundamental", avg_ir=1.0),
            StrategyICSummary(strategy_name="event_sentiment", avg_ir=0.0),
        ]
        original = DEFAULT_EQUAL_WEIGHTS.copy()
        result = _calibrate_weights(summaries, original)
        assert result["trend"] > result["fundamental"]  # Higher IR → higher weight
        # Zero-IR strategies get the (smaller) floor after normalization
        # Floor is applied to raw weights; final weights may be < floor after normalization
        assert result["mean_reversion"] < result["trend"]
        # Sum to 1.0
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_all_zero_ir_falls_back(self):
        summaries = [
            StrategyICSummary(strategy_name="trend", avg_ir=0.0),
            StrategyICSummary(strategy_name="mean_reversion", avg_ir=0.0),
        ]
        original = {"trend": 0.6, "mean_reversion": 0.4}
        result = _calibrate_weights(summaries, original)
        # When all IR=0, only WEIGHT_FLOOR remains, then normalized
        # Floor = 0.05 for all → still 0.5/0.5 after normalization
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_bh027_floor_honored_after_normalization(self):
        """BH-027: WEIGHT_FLOOR must remain a real lower bound after
        normalization. A dominating strategy (high IR) must not silently
        squeeze floored strategies to a fraction of the stated floor —
        that contradicts the module's "保守校准" + "避免某个策略权重为 0
        完全失效" contract."""
        summaries = [
            StrategyICSummary(strategy_name="trend", avg_ir=3.0),          # strong
            StrategyICSummary(strategy_name="mean_reversion", avg_ir=0.0),  # floored
            StrategyICSummary(strategy_name="fundamental", avg_ir=0.0),     # floored
            StrategyICSummary(strategy_name="event_sentiment", avg_ir=0.0), # floored
        ]
        result = _calibrate_weights(summaries, DEFAULT_EQUAL_WEIGHTS)
        assert abs(sum(result.values()) - 1.0) < 0.001
        # Every strategy must stay >= WEIGHT_FLOOR post-normalization.
        for strat, w in result.items():
            assert w >= WEIGHT_FLOOR - 1e-9, (
                f"BH-027 regression: {strat}={w:.4f} < WEIGHT_FLOOR={WEIGHT_FLOOR}"
            )

    def test_bh027_no_data_strategy_not_worse_than_zero_ir(self):
        """BH-027: a strategy with no IC data should not be treated worse
        than a strategy with IR=0 (both are "no positive signal"). The
        match-is-None branch must apply the same floor as the IR=0 branch."""
        summaries = [
            StrategyICSummary(strategy_name="trend", avg_ir=0.0),  # zero signal
            # mean_reversion absent from summaries → no data
        ]
        original = {"trend": 0.5, "mean_reversion": 0.5}
        result = _calibrate_weights(summaries, original)
        # Both should land on the floor (equal), not trend=floor while
        # mean_reversion is squeezed below it.
        assert abs(result["trend"] - result["mean_reversion"]) < 1e-9


class TestComputeWeightCalibration:
    def test_empty_data(self):
        result = compute_weight_calibration(
            factor_history={}, return_history=[]
        )
        assert result.calibration_skipped is True
        assert result.n_factors == 0

    def test_insufficient_data(self):
        # Only 3 observations (less than MIN_OBSERVATIONS_FOR_CALIBRATION=5)
        factor_history = {
            "trend.momentum_20d": [0.1, 0.2, 0.3],
            "fundamental.pe_ratio": [0.05, 0.06, 0.07],
        }
        return_history = [0.01, 0.02, 0.03]
        result = compute_weight_calibration(
            factor_history=factor_history, return_history=return_history
        )
        # Will be skipped due to insufficient observations
        assert result.calibration_skipped is True
        # Should fall back to default weights
        assert result.calibrated_weights == result.original_weights

    def test_sufficient_data_with_different_ir(self):
        # Need 3+ factors for compute_factor_ic to register
        factor_history = {
            "trend.momentum_20d": [0.1 * i for i in range(10)],
            "fundamental.pe_ratio": [0.01 * (i % 3) for i in range(10)],
            "mean_reversion.bounce": [0.5 - 0.05 * i for i in range(10)],
        }
        # Return: trend predicts well
        return_history = [0.1 * i for i in range(10)]

        result = compute_weight_calibration(
            factor_history=factor_history,
            return_history=return_history,
            lookback_days=10,
        )
        # Should not be skipped (10 obs >= 5)
        assert result.calibration_skipped is False
        assert result.n_factors == 3
        assert result.n_observations >= MIN_OBSERVATIONS_FOR_CALIBRATION

        # Sum to 1.0
        assert abs(sum(result.calibrated_weights.values()) - 1.0) < 0.001

        # All weights >= 0 (no negative weights)
        for w in result.calibrated_weights.values():
            assert w >= 0.0

    def test_strategy_summaries_populated(self):
        # Need 3+ factors for compute_factor_ic to return results
        factor_history = {
            "trend.momentum_20d": [0.1 * i for i in range(10)],
            "fundamental.pe_ratio": [0.01 * i for i in range(10)],
            "mean_reversion.bounce": [0.5 - 0.05 * i for i in range(10)],
        }
        return_history = [0.1 * i for i in range(10)]

        result = compute_weight_calibration(
            factor_history=factor_history, return_history=return_history
        )
        # 3 strategies
        strat_names = {s.strategy_name for s in result.strategy_summaries}
        assert "trend" in strat_names
        assert "fundamental" in strat_names
        assert "mean_reversion" in strat_names


class TestRenderWeightCalibration:
    def test_renders_basic(self):
        factor_history = {
            "trend.momentum_20d": [0.1 * i for i in range(10)],
            "fundamental.pe_ratio": [0.01 * i for i in range(10)],
        }
        return_history = [0.1 * i for i in range(10)]
        result = compute_weight_calibration(
            factor_history=factor_history, return_history=return_history
        )
        output = render_weight_calibration(result)
        assert "策略权重校准" in output
        assert "权重对比" in output

    def test_renders_skipped(self):
        result = WeightCalibrationResult(calibration_skipped=True)
        output = render_weight_calibration(result)
        assert "校准跳过" in output

    def test_renders_floor_enforcement_note_when_strategies_floored(self):
        """BH-027 follow-up: when some strategies are held at WEIGHT_FLOOR by
        the post-normalization floor projection (rather than reaching their
        weight via IR), the render must surface this so the user can calibrate
        trust in the result — a floored weight is a *conservative floor*, not
        an IR-driven signal. Without this note the user cannot distinguish
        "5% because IR≈0" from "5% because the floor held it there"."""
        # Construct a result where two strategies sit exactly at the floor.
        result = WeightCalibrationResult(
            lookback_days=30,
            original_weights=DEFAULT_EQUAL_WEIGHTS.copy(),
            calibrated_weights={
                "trend": 0.85,
                "mean_reversion": WEIGHT_FLOOR,
                "fundamental": WEIGHT_FLOOR,
                "event_sentiment": WEIGHT_FLOOR,
            },
            strategy_summaries=[
                StrategyICSummary(strategy_name="trend", avg_ir=3.0),
                StrategyICSummary(strategy_name="mean_reversion", avg_ir=0.0),
                StrategyICSummary(strategy_name="fundamental", avg_ir=0.0),
                StrategyICSummary(strategy_name="event_sentiment", avg_ir=0.0),
            ],
            n_factors=4,
            n_observations=20,
            calibration_skipped=False,
        )
        output = render_weight_calibration(result)
        # The note must (a) be present, (b) name which strategies are floored,
        # (c) reference WEIGHT_FLOOR so the user understands the bound.
        assert "下限保护" in output
        assert "mean_reversion" in output
        assert f"{WEIGHT_FLOOR:g}" in output

    def test_renders_no_floor_note_when_nothing_floored(self):
        """When no strategy is at the floor, the note must be absent to avoid
        clutter — floor enforcement is only relevant when it actually bit."""
        result = WeightCalibrationResult(
            lookback_days=30,
            original_weights=DEFAULT_EQUAL_WEIGHTS.copy(),
            # Uniform 0.25 each — none at the 0.05 floor.
            calibrated_weights=DEFAULT_EQUAL_WEIGHTS.copy(),
            strategy_summaries=[
                StrategyICSummary(strategy_name="trend", avg_ir=0.5),
            ],
            n_factors=4,
            n_observations=20,
            calibration_skipped=False,
        )
        output = render_weight_calibration(result)
        assert "下限保护" not in output
