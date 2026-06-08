"""R20.5 tests for the factor-level waterfall (P1-3 O-2 扩展) feature."""

from __future__ import annotations

import pytest

from src.screening.models import FusedScore, StrategySignal
from src.screening.signal_fusion import compute_score_decomposition


def _make_fused(
    ticker: str = "000001",
    score_b: float = 0.5,
    trend: tuple[float, float, float] = (1.0, 80.0, 1.0),  # direction, confidence, completeness
    mean_reversion: tuple[float, float, float] = (-1.0, 60.0, 0.8),
    fundamental: tuple[float, float, float] = (1.0, 90.0, 1.0),
    event_sentiment: tuple[float, float, float] = (1.0, 50.0, 0.5),
    weights: dict[str, float] | None = None,
    attention: float = 0.0,
    arbitration: list[str] | None = None,
) -> FusedScore:
    weights = weights or {"trend": 0.25, "mean_reversion": 0.25, "fundamental": 0.3, "event_sentiment": 0.2}
    return FusedScore(
        ticker=ticker,
        name="测试",
        score_b=score_b,
        weights_used=weights,
        strategy_signals={
            "trend": StrategySignal(direction=trend[0], confidence=trend[1], completeness=trend[2]),
            "mean_reversion": StrategySignal(direction=mean_reversion[0], confidence=mean_reversion[1], completeness=mean_reversion[2]),
            "fundamental": StrategySignal(direction=fundamental[0], confidence=fundamental[1], completeness=fundamental[2]),
            "event_sentiment": StrategySignal(direction=event_sentiment[0], confidence=event_sentiment[1], completeness=event_sentiment[2]),
        },
        metrics={"attention_composite": attention} if attention else {},
        arbitration_applied=arbitration or [],
    )


class TestComputeScoreDecomposition:
    def test_basic_decomposition(self):
        """Each strategy contribution = w * dir * conf/100 * completeness."""
        fused = _make_fused(score_b=0.5)
        decomp = compute_score_decomposition(fused)
        # trend: 0.25 * 1.0 * 0.8 * 1.0 = 0.20
        assert decomp["base_contributions"]["trend"] == pytest.approx(0.20, rel=1e-3)
        # MR: 0.25 * -1.0 * 0.6 * 0.8 = -0.12
        assert decomp["base_contributions"]["mean_reversion"] == pytest.approx(-0.12, rel=1e-3)
        # F: 0.30 * 1.0 * 0.9 * 1.0 = 0.27
        assert decomp["base_contributions"]["fundamental"] == pytest.approx(0.27, rel=1e-3)
        # E: 0.20 * 1.0 * 0.5 * 0.5 = 0.05
        assert decomp["base_contributions"]["event_sentiment"] == pytest.approx(0.05, rel=1e-3)

    def test_attention_contribution_extracted(self):
        fused = _make_fused(attention=0.15)
        decomp = compute_score_decomposition(fused)
        assert decomp["attention_contribution"] == pytest.approx(0.15)

    def test_stability_bonus_from_consecutive_info(self):
        fused = _make_fused()
        decomp = compute_score_decomposition(fused, {"consecutive_days": 3, "stability_bonus": 10.0})
        # stability_bonus is in 0-10 range from consecutive_recommendation
        assert decomp["stability_bonus"] == pytest.approx(10.0)

    def test_consensus_bonus_bullish(self):
        fused = _make_fused(arbitration=["consensus_bonus_bullish"])
        decomp = compute_score_decomposition(fused)
        assert decomp["consensus_bonus"] == pytest.approx(0.05)

    def test_consensus_bonus_bearish(self):
        fused = _make_fused(arbitration=["consensus_bonus_bearish"])
        decomp = compute_score_decomposition(fused)
        assert decomp["consensus_bonus"] == pytest.approx(-0.05)

    def test_no_consensus_bonus(self):
        fused = _make_fused(arbitration=[])
        decomp = compute_score_decomposition(fused)
        assert decomp["consensus_bonus"] == 0.0

    def test_other_adjustments_is_residual(self):
        """other_adjustments = score_b - sum(components)"""
        # Construct a fused where the math will produce a residual
        fused = _make_fused(score_b=0.9, attention=0.1)  # components sum to ~0.6, residual ~0.3
        decomp = compute_score_decomposition(fused)
        components_sum = (
            sum(decomp["base_contributions"].values())
            + decomp["attention_contribution"]
            + decomp["stability_bonus"]
            + decomp["consensus_bonus"]
        )
        assert decomp["other_adjustments"] == pytest.approx(fused.score_b - components_sum, rel=1e-6)

    def test_total_equals_score_b(self):
        fused = _make_fused(score_b=0.42)
        decomp = compute_score_decomposition(fused)
        assert decomp["total"] == pytest.approx(0.42)

    def test_empty_signals(self):
        """If no signals present, base contributions are 0."""
        fused = FusedScore(
            ticker="X", name="", score_b=0.0,
            weights_used={}, strategy_signals={}, metrics={},
        )
        decomp = compute_score_decomposition(fused)
        assert all(v == 0.0 for v in decomp["base_contributions"].values())
        assert decomp["total"] == 0.0

    def test_zero_weight_strategy_excluded(self):
        """If a strategy has weight 0, its contribution is 0 regardless of signal."""
        fused = _make_fused(weights={"trend": 0, "mean_reversion": 0.5, "fundamental": 0.5, "event_sentiment": 0})
        decomp = compute_score_decomposition(fused)
        assert decomp["base_contributions"]["trend"] == 0.0
        assert decomp["base_contributions"]["event_sentiment"] == 0.0
        # MR and F should still contribute
        assert decomp["base_contributions"]["mean_reversion"] != 0.0
        assert decomp["base_contributions"]["fundamental"] != 0.0

    def test_zero_confidence_handled(self):
        """A signal with confidence=0 should produce 0 contribution."""
        from src.screening.models import StrategySignal
        fused = FusedScore(
            ticker="X", score_b=0.0,
            weights_used={"trend": 1.0},
            strategy_signals={
                "trend": StrategySignal(direction=1.0, confidence=0.0, completeness=1.0),
            },
            metrics={},
        )
        decomp = compute_score_decomposition(fused)
        # 0 confidence → 0 contribution
        assert decomp["base_contributions"]["trend"] == 0.0

    def test_negative_score_b(self):
        """Negative score_b should work correctly."""
        fused = _make_fused(score_b=-0.3)
        decomp = compute_score_decomposition(fused)
        assert decomp["total"] == pytest.approx(-0.3)


class TestWaterfallPrint:
    """Smoke tests for the waterfall print function."""

    def test_waterfall_with_empty_input(self, capsys):
        from src.main import _print_score_waterfall
        _print_score_waterfall([], {})
        captured = capsys.readouterr()
        # Should produce no output for empty input
        assert "因子瀑布" not in captured.out

    def test_waterfall_renders_for_one_ticker(self, capsys):
        from src.main import _print_score_waterfall
        fused = _make_fused(ticker="000001", score_b=0.5)
        _print_score_waterfall([fused], {"000001": {"consecutive_days": 2, "stability_bonus": 3.0}})
        out = capsys.readouterr().out
        assert "000001" in out
        assert "score_b" in out
        assert "T" in out  # trend label
        assert "F" in out  # fundamental label
        assert "MR" in out  # mean reversion label
        assert "E" in out  # event sentiment label
