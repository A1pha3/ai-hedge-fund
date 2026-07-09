"""Tests for _print_score_decomposition (O-2: 推荐排序策略透明化)."""

import pytest

from src.main import _build_auto_screening_table_row, _print_score_decomposition
from src.screening.models import FusedScore, StrategySignal


def _make_fused(
    ticker: str = "000001",
    score_b: float = 0.45,
    weights: dict | None = None,
    signals: dict | None = None,
    metrics: dict | None = None,
    arbitration: list[str] | None = None,
) -> FusedScore:
    """Helper to create a FusedScore for testing."""
    default_signals = {
        "trend": StrategySignal(direction=1, confidence=70.0, completeness=1.0, sub_factors={}),
        "fundamental": StrategySignal(direction=1, confidence=60.0, completeness=1.0, sub_factors={}),
    }
    return FusedScore(
        ticker=ticker,
        score_b=score_b,
        strategy_signals=signals or default_signals,
        metrics=metrics or {},
        weights_used=weights or {"trend": 0.4, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.1},
        arbitration_applied=arbitration or [],
    )


class TestPrintScoreDecomposition:
    """O-2: --auto CLI 表格下方的评分构成摘要块。"""

    def test_empty_results_no_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        """空结果不崩溃。"""
        _print_score_decomposition([], {})
        output = capsys.readouterr().out
        assert output == ""

    def test_single_result_prints_ticker_and_score(self, capsys: pytest.CaptureFixture[str]) -> None:
        """单个结果输出 ticker 和 score_b。"""
        item = _make_fused(ticker="300750", score_b=0.55)
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "300750" in output
        assert "+0.5500" in output

    def test_strategy_contributions_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """各策略贡献值被计算并显示。"""
        item = _make_fused(
            ticker="000001",
            weights={"trend": 0.5, "mean_reversion": 0.2, "fundamental": 0.2, "event_sentiment": 0.1},
            signals={
                "trend": StrategySignal(direction=1, confidence=80.0, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=-1, confidence=50.0, completeness=1.0, sub_factors={}),
            },
        )
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        # trend contribution = 0.5 * 1 * 0.8 * 1.0 = 0.400
        assert "T:↑0.400" in output
        # fundamental contribution = 0.2 * (-1) * 0.5 * 1.0 = -0.100
        assert "F:↓0.100" in output

    def test_attention_composite_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """attention_composite 从 metrics 中提取并显示。"""
        item = _make_fused(ticker="000002", metrics={"attention_composite": 0.75})
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "att:0.75" in output

    def test_stability_bonus_from_consecutive_lookup(self, capsys: pytest.CaptureFixture[str]) -> None:
        """stability_bonus 从 consecutive_lookup 中提取。"""
        item = _make_fused(ticker="000003")
        lookup = {"000003": {"consecutive_days": 3, "stability_bonus": 10.0}}
        _print_score_decomposition([item], lookup)
        output = capsys.readouterr().out
        assert "stab:10.0" in output

    def test_consensus_bonus_star(self, capsys: pytest.CaptureFixture[str]) -> None:
        """consensus_bonus 标记为 ★。"""
        item = _make_fused(ticker="000004", arbitration=["consensus_bonus"])
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "★" in output

    def test_no_consensus_no_star(self, capsys: pytest.CaptureFixture[str]) -> None:
        """无 consensus_bonus 不显示 ★。"""
        item = _make_fused(ticker="000005", arbitration=["risk_off"])
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        # Should have space, not star
        lines = [l for l in output.split("\n") if "000005" in l]  # noqa: E741
        assert len(lines) == 1
        assert "★" not in lines[0]

    def test_missing_strategy_shows_dash(self, capsys: pytest.CaptureFixture[str]) -> None:
        """缺失的策略信号显示 —。"""
        item = _make_fused(
            ticker="000006",
            weights={"trend": 0.5, "mean_reversion": 0.5},
            signals={
                "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0, sub_factors={}),
            },
        )
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "MR:—" in output
        assert "F:—" in output
        assert "E:—" in output

    def test_score_color_high(self, capsys: pytest.CaptureFixture[str]) -> None:
        """score_b >= 0.35 时使用绿色（ANSI escape）。"""
        item = _make_fused(ticker="000007", score_b=0.45)
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        # ANSI green escape sequence present
        assert "\x1b[32m" in output

    def test_score_color_negative(self, capsys: pytest.CaptureFixture[str]) -> None:
        """score_b < 0 时使用红色（ANSI escape）。"""
        item = _make_fused(ticker="000008", score_b=-0.30)
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "\x1b[31m" in output


class TestAutoScreeningTableCompositeColumn:
    """Bug 3: the --auto table must show a Composite column (the primary sort key)
    so that a non-descending Score B column doesn't look like a sorting bug."""

    def test_row_has_composite_value(self):
        """The row list includes a composite_score cell when provided."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=0.4823
        )
        # The row now has 10 columns: #, Ticker, Industry, Score B, Composite, ...
        assert len(row) == 10
        # Composite is the 5th element (index 4)
        assert "0.4823" in row[4]

    def test_row_shows_dash_when_composite_missing(self):
        """When composite_score is None, the Composite cell shows a dash."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "—" in row[4]
