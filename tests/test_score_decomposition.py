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
        """缺失的策略信号整段省略 (零信息噪声), 不再占位 "MR:—"."""
        item = _make_fused(
            ticker="000006",
            weights={"trend": 0.5, "mean_reversion": 0.5},
            signals={
                "trend": StrategySignal(direction=1, confidence=60.0, completeness=1.0, sub_factors={}),
            },
        )
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "T:↑" in output
        assert "MR:" not in output
        assert "F:" not in output
        assert "E:" not in output

    def test_neutral_strategy_omitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        """direction==0 (无信号) 的策略省略 — "MR:—0.000" 是自相矛盾的每日噪声."""
        item = _make_fused(
            ticker="000009",
            signals={
                "trend": StrategySignal(direction=1, confidence=45.0, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=59.8, completeness=1.0, sub_factors={}),
            },
        )
        _print_score_decomposition([item], {})
        output = capsys.readouterr().out
        assert "T:↑" in output
        assert "MR:" not in output

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
    """表格列契约: 「池胜率」(profit_aware 排序主键, 2026-07-18 起默认) 与
    「综合分」(同档 tie-break) 都必须显示, 否则非单调的综合分列看起来像排序 bug
    (8/14 实证: 第 8 行综合分 0.58 高于第 1 行 0.47, 主键池胜率不可见)."""

    def test_row_has_composite_value(self):
        """The row list includes a composite_score cell when provided."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=0.4823
        )
        # 11 columns: #, Ticker, Industry, Score B, 池胜率, Composite, ...
        assert len(row) == 11
        # Composite is the 6th element (index 5)
        assert "0.4823" in row[5]

    def test_row_shows_dash_when_composite_missing(self):
        """When composite_score is None, the Composite cell shows a dash."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "—" in row[5]

    def test_row_has_bucket_winrate_value(self):
        """池胜率单元格: 胜率百分比 + 样本数."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None,
            composite_score=0.4823, bucket_stat=(0.4825, 428),
        )
        assert "48%·428" in row[4]

    def test_row_shows_dash_when_bucket_winrate_missing(self):
        """无桶证据时池胜率单元格显示 — (未知证据, 不编造)."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None,
            composite_score=0.4823, bucket_stat=(None, 0),
        )
        assert row[4] == "—"

    def test_neutral_signal_hides_confidence_number(self):
        """direction==0 的策略只显示 "—" — "—60" (无信号却带信心数) 自相矛盾."""
        item = _make_fused(
            ticker="000001", score_b=0.50,
            signals={
                "trend": StrategySignal(direction=1, confidence=45.0, completeness=1.0, sub_factors={}),
                "mean_reversion": StrategySignal(direction=0, confidence=59.8, completeness=1.0, sub_factors={}),
            },
        )
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        signal_cell = row[7]
        assert "↑45" in signal_cell
        assert "—60" not in signal_cell
        # MR 槽位只剩裸 "—"
        assert signal_cell.split()[1] == "—"


class TestScoreWaterfallAdditiveOnly:
    """因子瀑布必须严格加性: 瀑布体行之和 = score_b; att/stab 量纲差一个数量级
    (stab +10.0 vs 总分 +0.33), 混入瀑布体会破坏视觉契约 — 收进标题行附注."""

    def test_att_and_stab_in_header_not_waterfall_body(self, capsys: pytest.CaptureFixture[str]) -> None:
        from src.main import _print_score_waterfall

        item = _make_fused(
            ticker="600988",
            score_b=0.3601,
            metrics={"attention_composite": 0.4629},
        )
        lookup = {"600988": {"consecutive_days": 3, "stability_bonus": 10.0}}
        _print_score_waterfall([item], lookup)
        output = capsys.readouterr().out
        lines = output.splitlines()
        header_line = next(line for line in lines if "600988" in line)
        # 非加性上下文在标题行
        assert "att 0.46" in header_line
        assert "连续 3 天" in header_line
        # 瀑布体不再有 att/stab 加性行 (旧格式: "att +0.4629 (non-additive...)")
        body = "\n".join(lines[lines.index(header_line) + 1:])
        assert "non-additive" not in body
        assert "stab" not in body
        assert "+10.0000" not in body

    def test_waterfall_body_sums_to_score_b(self, capsys: pytest.CaptureFixture[str]) -> None:
        """瀑布体只留真加性分量: base + consensus ± clamp 残差 = score_b."""
        from src.main import _print_score_waterfall

        item = _make_fused(
            ticker="000001",
            score_b=0.33,
            weights={"trend": 0.5, "fundamental": 0.2},
            signals={
                "trend": StrategySignal(direction=1, confidence=50.0, completeness=1.0, sub_factors={}),
                "fundamental": StrategySignal(direction=1, confidence=50.0, completeness=1.0, sub_factors={}),
            },
        )
        _print_score_waterfall([item], {})
        output = capsys.readouterr().out
        # T: 0.5*0.5=+0.2500, F: 0.2*0.5=+0.1000; total 行 = score_b +0.3300
        assert "+0.2500" in output
        assert "+0.1000" in output
        assert "score_b" in output
        assert "+0.3300" in output
