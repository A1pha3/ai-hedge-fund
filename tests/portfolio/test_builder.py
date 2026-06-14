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

    def test_renders_empty(self):
        summary = PortfolioSummary()
        output = render_portfolio(summary)
        assert "无组合数据" in output
