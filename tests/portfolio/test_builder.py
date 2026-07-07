"""Tests for P3-4: portfolio builder."""

import pytest

from src.portfolio.builder import (
    _allocate_weights,
    compute_portfolio,
    DEFAULT_INDUSTRY_CAP,
    DEFAULT_POSITION_CAP,
    PortfolioPosition,
    PortfolioSummary,
    render_portfolio,
)

SAMPLE_RECS = [
    {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "score_b": 0.85},
    {"ticker": "600036", "name": "招商银行", "industry_sw": "银行", "score_b": 0.75},
    {"ticker": "000858", "name": "五粮液", "industry_sw": "食品饮料", "score_b": 0.90},
    {"ticker": "600519", "name": "贵州茅台", "industry_sw": "食品饮料", "score_b": 0.80},
    {"ticker": "300750", "name": "宁德时代", "industry_sw": "电力设备", "score_b": 0.65},
    {"ticker": "601012", "name": "隆基绿能", "industry_sw": "电力设备", "score_b": 0.55},
    {"ticker": "002594", "name": "比亚迪", "industry_sw": "汽车", "score_b": 0.50},
    {"ticker": "000333", "name": "美的集团", "industry_sw": "家电", "score_b": 0.45},
]


class TestAllocateWeights:
    def test_basic_allocation(self):
        # With no real constraint tightness, sum should be ~1.0
        weights = _allocate_weights([0.5, 0.3, 0.2], ["A", "B", "C"], position_cap=0.5, industry_cap=0.5)
        assert sum(weights) == pytest.approx(1.0, abs=0.01)

    def test_position_cap_enforced(self):
        # First stock has 0.9 score, should be capped
        weights = _allocate_weights([0.9, 0.5, 0.4], ["A", "B", "C"], position_cap=0.4, industry_cap=1.0)
        assert max(weights) <= 0.4 + 0.01  # Cap respected

    def test_industry_cap_enforced(self):
        # All 3 in same industry
        weights = _allocate_weights([0.5, 0.3, 0.2], ["X", "X", "X"], position_cap=1.0, industry_cap=0.5)
        industry_x_weight = sum(w for w in weights)  # All are X
        # Cannot exceed 0.5
        assert industry_x_weight <= 0.5 + 0.01

    def test_all_zero_scores(self):
        weights = _allocate_weights([0, 0, 0], ["A", "B", "C"], position_cap=0.5, industry_cap=0.5)
        # All equal weight
        assert all(abs(w - 1 / 3) < 0.01 for w in weights)

    def test_empty_input(self):
        weights = _allocate_weights([], [], position_cap=0.5, industry_cap=0.5)
        assert weights == []


class TestComputePortfolio:
    def test_basic(self):
        # Loose constraints → sum should be ~1.0
        summary = compute_portfolio(SAMPLE_RECS, top_n=5, position_cap=0.5, industry_cap=0.5)
        assert summary.n_positions == 5
        # Sum to ~1.0 (loose constraints)
        assert abs(summary.total_weight - 1.0) < 0.01

    def test_top_n_respected(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=3)
        assert summary.n_positions == 3

    def test_top_n_tiebreak_deterministic_across_input_order(self):
        """R120/BH-011 family (sibling of top_picks._apply_consecutive_bonus_and_resort):
        at the Top-N membership boundary, three recs tied on ``score_b`` with top_n=2
        must drop/keep deterministically by ticker ascending — not by whatever order
        the upstream auto_screening report array happened to arrive in. Before the fix,
        ``filtered.sort(key=score_b)`` preserved input order on ties, so two identical
        runs over the same data could allocate capital to different tickers, breaking
        the "稳定找到" goal."""
        tied_recs = [
            {"ticker": "600999", "name": "B", "industry_sw": "综合", "score_b": 0.90},
            {"ticker": "300118", "name": "C", "industry_sw": "电子", "score_b": 0.90},
            {"ticker": "000001", "name": "A", "industry_sw": "银行", "score_b": 0.90},
        ]
        # top_n=2 with three tied-at-0.9: the boundary cut (keep 2, drop 1) must be
        # deterministic. By ticker ascending the kept set is {000001, 300118} and the
        # dropped is 600999, regardless of input order.
        summary_forward = compute_portfolio(list(tied_recs), top_n=2, position_cap=0.9, industry_cap=0.9)
        summary_reversed = compute_portfolio(list(reversed(tied_recs)), top_n=2, position_cap=0.9, industry_cap=0.9)

        forward_tickers = {p.ticker for p in summary_forward.positions}
        reversed_tickers = {p.ticker for p in summary_reversed.positions}
        assert forward_tickers == reversed_tickers == {"000001", "300118"}

    def test_position_cap_respected(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5, position_cap=0.30)
        for p in summary.positions:
            assert p.weight <= 0.30 + 0.01

    def test_industry_cap_respected(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=8, position_cap=0.5, industry_cap=0.3)
        # No industry should exceed 0.3
        for ind, w in summary.industry_breakdown.items():
            assert w <= 0.30 + 0.01

    def test_empty_recommendations(self):
        summary = compute_portfolio([])
        assert summary.n_positions == 0
        assert summary.positions == []

    def test_concentration_metrics(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        assert summary.concentration_top1 > 0
        assert summary.concentration_top3 >= summary.concentration_top1

    def test_sharpe_comparison(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        # Both should be positive
        assert summary.expected_sharpe > 0
        assert summary.equal_weight_sharpe > 0


class TestRenderPortfolio:
    def test_renders_basic(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        output = render_portfolio(summary)
        assert "推荐组合构建器" in output
        assert "持仓" in output
        assert "行业分布" in output
        assert "组合指标" in output

    def test_renders_front_door_verdict_beside_weighted_positions(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        output = render_portfolio(summary)

        assert "前门" in output
        assert "AVOID" in output

    def test_renders_empty(self):
        summary = PortfolioSummary()
        output = render_portfolio(summary)
        assert "无组合数据" in output


class TestRenderPortfolioVerdictSummary:
    """autodev-25 loop 135: portfolio CLl 前门列着色 + 🎯 汇总行."""

    def test_verdict_summary_line_shown(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        output = render_portfolio(summary)

        assert "前门判决" in output
        # summary positions
        assert "BUY" in output
        # matching count
        total = len(summary.positions)
        assert f"/{total}" in output

    def test_verdict_column_color_coded(self):
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        output = render_portfolio(summary)

        # table must contain 前门 column
        assert "前门" in output
        # color code must be present (ANSI Fore.RED or Fore.GREEN or Fore.YELLOW)
        assert "\x1b[" in output  # ANSI escape present

    def test_empty_renders_no_summary(self):
        output = render_portfolio(PortfolioSummary())
        assert "前门判决" not in output  # 空组合无汇总
        assert "无组合数据" in output

    def test_summary_shows_AVOID_tickers_when_present(self):
        """验证 AVOID 个票以 ⚠ 形式列出 (当组合中有 AVOID)."""
        summary = compute_portfolio(SAMPLE_RECS, top_n=5)
        output = render_portfolio(summary)

        # SAMPLE_RECS 无额外验证, 用 gate 默认值; 如果全是 gate 拒绝则标签存在
        if "AVOID" in output:
            assert "⚠" in output  # AVOID tickers 以警告形式出现
