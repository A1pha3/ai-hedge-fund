"""Tests for the --auto 表格行构造器与因子瀑布 (v3 桶分组版, 2026-08-16).

v3 重构后行内不再有「信号分/池胜率/决策」列 — 桶级统计上桶头 (scorecard
模块的 ``format_bucket_header``), 决策语义由 header 记分牌承担。本文件钉住:
- 新 8 列契约与综合分 (同档 tie-break) 渲染;
- gap_to_limit ≤ 1% 的次日可执行性提示;
- 因子瀑布严格加性 (att/stab 收标题行)。
"""

import pytest

from src.main import _build_auto_screening_table_row
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


class TestAutoScreeningTableRowV3:
    """v3 8 列契约: #, 代码 名称, 行业, 综合分, 信号, 连续, 衰减, 提示."""

    def test_row_has_eight_columns(self):
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=0.4823
        )
        assert len(row) == 8
        # Composite is the 4th element (index 3) — 同档 tie-break 键
        assert "+0.48" in row[3]

    def test_composite_two_decimals_not_four(self):
        """同档内 score 差异是 tie-break 噪声 — 4 位小数是假精度 (v3)."""
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=0.4823
        )
        assert "0.4823" not in "".join(row)

    def test_row_shows_dash_when_composite_missing(self):
        item = _make_fused(ticker="000001", score_b=0.50)
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "—" in row[3]

    def test_gap_to_limit_flag_at_threshold(self):
        """gap_to_limit ≤ 0.01 (距涨停 <1%) → ⚠距涨停提示 (T+1 买不进风险)."""
        item = _make_fused(ticker="688498", score_b=0.40, metrics={"gap_to_limit": 0.005})
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "⚠距涨停<1%" in row[7]

    def test_gap_to_limit_no_flag_when_far(self):
        item = _make_fused(ticker="000001", score_b=0.40, metrics={"gap_to_limit": 0.05})
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "距涨停" not in row[7]

    def test_gap_to_limit_missing_metric_no_flag(self):
        """metrics 无 gap_to_limit → 不提示 (未知不编造)."""
        item = _make_fused(ticker="000001", score_b=0.40, metrics={})
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "距涨停" not in row[7]

    def test_arbitration_label_in_hints(self):
        item = _make_fused(ticker="000004", arbitration=["short_hold", "consensus_bonus"])
        row = _build_auto_screening_table_row(
            idx=1, item=item, consecutive_lookup={}, decay_map=None, composite_score=None
        )
        assert "短线持有" in row[7]
        assert "★" in row[7]

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
        signal_cell = row[4]
        assert "↑45" in signal_cell
        assert "—60" not in signal_cell
        # MR 槽位只剩裸 "—"
        assert signal_cell.split()[1] == "—"
