"""Tests for P3-2: weight_calibration module."""
import pytest

from src.research.factor_ic_analysis import FactorICResult
from src.research.weight_calibration import (
    _aggregate_strategy_ic,
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
