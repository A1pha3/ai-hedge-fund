"""Tests for src.screening.portfolio_risk_budget — R-3 组合风险预算总览.

R-3 (C171): synthesize P-4 concentration + Q-4 correlation + R145 position into a
single read-only ``🎯 组合风险: X%/100% 预算`` line on the --top-picks footer.

P-4 (industry concentration), Q-4 (correlation discount), and R145 (per-pick
position sizing) each measure one risk dimension independently; R-3 is the
portfolio-level synthesis (how much of the risk budget is consumed), display-only.
Mirrors R-1 (horizon_conflict) / R-2 (data_quality summary) pure-fn pattern.
"""

from __future__ import annotations

import pytest

from src.screening.portfolio_risk_budget import (
    PortfolioRiskSummary,
    render_portfolio_risk_line,
    summarize_portfolio_risk,
)


def _pick(ticker: str, industry: str = "电子", score_b: float = 0.5) -> dict:
    return {"ticker": ticker, "industry_sw": industry, "score_b": score_b}


# ---------------------------------------------------------------------------
# summarize_portfolio_risk
# ---------------------------------------------------------------------------


class TestSummarizePortfolioRisk:
    def test_empty_picks_returns_no_data(self) -> None:
        """空推荐 → 无可合成的组合风险。"""
        s = summarize_portfolio_risk([])
        assert s.has_data is False

    def test_single_pick_low_risk(self) -> None:
        """单只票无集中度/相关性风险 → 预算占用低。"""
        s = summarize_portfolio_risk([_pick("000001")])
        assert s.has_data is True
        assert s.pick_count == 1
        # 单只票: 无 pair 相关 (max_pair=None), 单行业 top_share=1.0 但只 1 只不算集中
        assert s.concentration_share == pytest.approx(1.0)
        assert s.has_correlation_risk is False

    def test_high_concentration_drives_risk_up(self) -> None:
        """多只票同行业 → 集中度高 → 预算占用高。"""
        picks = [_pick(f"00000{i}", industry="电子") for i in range(4)]
        s = summarize_portfolio_risk(picks)
        assert s.concentration_share == pytest.approx(1.0)  # 全部电子
        assert s.concentration_over_threshold is True  # 100% > 30%
        assert s.risk_budget_used > 50.0  # 高集中 → 高占用

    def test_diversified_picks_lower_risk(self) -> None:
        """分散在多行业 → 集中度低 → 预算占用低于集中组合。"""
        diversified = [
            _pick("000001", industry="电子"),
            _pick("000002", industry="医药"),
            _pick("000003", industry="银行"),
            _pick("000004", industry="消费"),
        ]
        concentrated = [_pick(f"00000{i}", industry="电子") for i in range(4)]
        s_div = summarize_portfolio_risk(diversified)
        s_con = summarize_portfolio_risk(concentrated)
        assert s_div.risk_budget_used < s_con.risk_budget_used

    def test_correlation_risk_detected(self) -> None:
        """同行业 + 分数邻近 → 相关性风险标记。"""
        picks = [
            _pick("000001", industry="电子", score_b=0.50),
            _pick("000002", industry="电子", score_b=0.51),  # 同行业 + 邻近分数
        ]
        s = summarize_portfolio_risk(picks)
        assert s.has_correlation_risk is True
        assert s.max_pair_correlation is not None
        assert s.max_pair_correlation > 0.5

    def test_risk_budget_bounded_0_to_100(self) -> None:
        """预算占用始终在 [0, 100] 区间。"""
        # 极端集中
        heavy = [_pick(f"00000{i}", industry="电子") for i in range(10)]
        s = summarize_portfolio_risk(heavy)
        assert 0.0 <= s.risk_budget_used <= 100.0


# ---------------------------------------------------------------------------
# render_portfolio_risk_line
# ---------------------------------------------------------------------------


class TestRenderPortfolioRiskLine:
    def test_no_data_returns_empty(self) -> None:
        """无数据 → 空串 (前门不展示)。"""
        s = summarize_portfolio_risk([])
        assert render_portfolio_risk_line(s) == ""

    def test_renders_budget_line_with_percentage(self) -> None:
        """有数据 → 单行含百分比 + 预算字样。"""
        picks = [_pick(f"00000{i}", industry="电子") for i in range(3)]
        line = render_portfolio_risk_line(summarize_portfolio_risk(picks))
        assert line != ""
        assert "组合风险" in line
        assert "%" in line
        assert "预算" in line

    def test_high_risk_renders_warning(self) -> None:
        """高占用 → 含 ⚠ 告警 + 红/黄色。"""
        from src.utils.display import Fore

        picks = [_pick(f"00000{i}", industry="电子") for i in range(5)]
        s = summarize_portfolio_risk(picks)
        line = render_portfolio_risk_line(s)
        assert "⚠" in line or s.risk_budget_used < 50.0  # 高占用必有 ⚠
        if s.risk_budget_used >= 70.0:
            assert Fore.RED in line or Fore.YELLOW in line
