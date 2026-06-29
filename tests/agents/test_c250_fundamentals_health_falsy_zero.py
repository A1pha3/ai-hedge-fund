"""C250 TDD — fundamentals_helpers._analyze_fundamentals_health falsy-zero drain.

Background (R68/R96 family sibling, C246/C247 漏 drain):
  `fundamentals_helpers.py:63` `if debt_to_equity and debt_to_equity < 0.5:`
  truthiness `if 0.0:` 短路 → D/E=0.0 (零负债, 最优资产负债表) 不 +1,
  把最优负债结构误判为 "数据不足". 同函数 line 65 FCF=0.0 同型 bug.

C246 drained buffett/ackman-ROE; C247 drained rakesh liabilities/debt numerator.
本测试覆盖 fundamentals_helpers._analyze_fundamentals_health 的同型 drain.

Fix: `is not None` guard (与 C246/C247 同模板). 0.0 是 computed value, None 是 missing.
"""
from __future__ import annotations

from src.agents.fundamentals_helpers import _analyze_fundamentals_health
from src.data.models import FinancialMetrics


def _make_metrics(
    *,
    current_ratio: float | None = None,
    debt_to_equity: float | None = None,
    free_cash_flow_per_share: float | None = None,
    earnings_per_share: float | None = None,
) -> FinancialMetrics:
    """Build a minimal FinancialMetrics with only health-relevant fields set."""
    return FinancialMetrics(
        ticker="TEST",
        report_period="2026Q1",
        period="ttm",
        currency="CNY",
        market_cap=None,
        enterprise_value=None,
        price_to_earnings_ratio=None,
        price_to_book_ratio=None,
        price_to_sales_ratio=None,
        enterprise_value_to_ebitda_ratio=None,
        enterprise_value_to_revenue_ratio=None,
        free_cash_flow_yield=None,
        peg_ratio=None,
        gross_margin=None,
        operating_margin=None,
        net_margin=None,
        return_on_equity=None,
        return_on_assets=None,
        return_on_invested_capital=None,
        asset_turnover=None,
        inventory_turnover=None,
        receivables_turnover=None,
        days_sales_outstanding=None,
        operating_cycle=None,
        working_capital_turnover=None,
        current_ratio=current_ratio,
        quick_ratio=None,
        cash_ratio=None,
        operating_cash_flow_ratio=None,
        debt_to_equity=debt_to_equity,
        debt_to_assets=None,
        interest_coverage=None,
        revenue_growth=None,
        earnings_growth=None,
        book_value_growth=None,
        earnings_per_share_growth=None,
        free_cash_flow_growth=None,
        operating_income_growth=None,
        ebitda_growth=None,
        payout_ratio=None,
        earnings_per_share=earnings_per_share,
        book_value_per_share=None,
        free_cash_flow_per_share=free_cash_flow_per_share,
    )


class TestDebtToEquityFalsyZero:
    """D/E=0.0 (零负债, 最优) 应 +1, 不应被 truthiness 短路."""

    def test_zero_debt_to_equity_scores_health_point(self):
        """D/E=0.0 (零负债公司) health_score 应 +1 (最优资产负债表)."""
        metrics = _make_metrics(
            current_ratio=2.0,  # > 1.5, +1
            debt_to_equity=0.0,  # 零负债, < 0.5, 应 +1 (BUG: truthiness 短路)
            free_cash_flow_per_share=5.0,
            earnings_per_share=4.0,  # FCF > EPS*0.8, +1
        )
        signal, reasoning = _analyze_fundamentals_health(metrics)
        # 3 个 +1 → bullish (health_score >= 2)
        assert signal == "bullish", (
            f"D/E=0.0 (零负债) 应 +1 → bullish; got {signal} (truthiness 短路 bug)"
        )

    def test_zero_debt_to_equity_alone_is_bullish(self):
        """D/E=0.0 单独 +1, 配合 current_ratio>1.5 → bullish."""
        metrics = _make_metrics(
            current_ratio=2.0,  # +1
            debt_to_equity=0.0,  # 应 +1
            free_cash_flow_per_share=None,
            earnings_per_share=None,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bullish", (
            f"D/E=0.0 + current_ratio>1.5 应 bullish; got {signal}"
        )

    def test_none_debt_to_equity_does_not_score(self):
        """D/E=None (missing) 不 +1 (regression guard)."""
        metrics = _make_metrics(
            current_ratio=2.0,  # +1
            debt_to_equity=None,  # missing, 不 +1
            free_cash_flow_per_share=None,
            earnings_per_share=None,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        # 只有 current_ratio +1 → health_score=1 → neutral
        assert signal == "neutral", (
            f"D/E=None + current_ratio>1.5 应 neutral (1/3); got {signal}"
        )


class TestFreeCashFlowFalsyZero:
    """FCF=0.0 (breakeven) 应参与比较, 不应被 truthiness 短路."""

    def test_zero_fcf_with_negative_eps_scores_health_point(self):
        """FCF=0.0 + EPS=-1.0 → 0.0 > -0.8 → 应 +1 (FCF breakeven 优于 EPS 亏损)."""
        metrics = _make_metrics(
            current_ratio=2.0,  # +1
            debt_to_equity=0.0,  # +1
            free_cash_flow_per_share=0.0,  # breakeven, 应参与比较
            earnings_per_share=-1.0,  # 0.0 > -1.0*0.8=-0.8 → True, 应 +1
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bullish", (
            f"FCF=0.0 + EPS=-1.0 应 +1 → bullish; got {signal} (truthiness 短路 bug)"
        )

    def test_zero_fcf_with_positive_eps_does_not_score(self):
        """FCF=0.0 + EPS=4.0 → 0.0 > 3.2 → False, 不 +1 (regression guard)."""
        metrics = _make_metrics(
            current_ratio=None,
            debt_to_equity=None,
            free_cash_flow_per_share=0.0,  # 0.0 > 4.0*0.8=3.2 → False
            earnings_per_share=4.0,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        # health_score=0 → bearish
        assert signal == "bearish", (
            f"FCF=0.0 + EPS=4.0 不 +1 → bearish; got {signal}"
        )

    def test_none_fcf_does_not_score(self):
        """FCF=None (missing) 不 +1 (regression guard)."""
        metrics = _make_metrics(
            current_ratio=None,
            debt_to_equity=None,
            free_cash_flow_per_share=None,  # missing
            earnings_per_share=4.0,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bearish", (
            f"FCF=None 不 +1 → bearish; got {signal}"
        )

    def test_none_eps_does_not_score(self):
        """EPS=None (missing) 不 +1 (regression guard)."""
        metrics = _make_metrics(
            current_ratio=None,
            debt_to_equity=None,
            free_cash_flow_per_share=5.0,
            earnings_per_share=None,  # missing
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bearish", (
            f"EPS=None 不 +1 → bearish; got {signal}"
        )


class TestCurrentRatioFalsyZero:
    """current_ratio=0.0 — truthiness 短路但 0.0>1.5=False 无功能 bug; is not None guard 一致性."""

    def test_zero_current_ratio_does_not_score(self):
        """current_ratio=0.0 → 0.0 > 1.5 False, 不 +1 (无功能 bug, 但 is not None 一致)."""
        metrics = _make_metrics(
            current_ratio=0.0,  # 0.0 > 1.5 → False, 不 +1
            debt_to_equity=None,
            free_cash_flow_per_share=None,
            earnings_per_share=None,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bearish", (
            f"current_ratio=0.0 不 +1 → bearish; got {signal}"
        )

    def test_none_current_ratio_does_not_score(self):
        """current_ratio=None (missing) 不 +1 (regression guard)."""
        metrics = _make_metrics(
            current_ratio=None,
            debt_to_equity=None,
            free_cash_flow_per_share=None,
            earnings_per_share=None,
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bearish", (
            f"全 None → bearish; got {signal}"
        )


class TestNonzeroRegressionGuard:
    """非零合法值行为不变 (behavior-preserving regression guard)."""

    def test_all_healthy_nonzero_is_bullish(self):
        """全非零健康值 → bullish (3/3)."""
        metrics = _make_metrics(
            current_ratio=2.0,  # +1
            debt_to_equity=0.3,  # +1
            free_cash_flow_per_share=5.0,
            earnings_per_share=4.0,  # +1
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bullish"

    def test_mixed_signals_is_neutral(self):
        """1/3 → neutral."""
        metrics = _make_metrics(
            current_ratio=2.0,  # +1
            debt_to_equity=0.8,  # 0.8 < 0.5 False, 不 +1
            free_cash_flow_per_share=1.0,
            earnings_per_share=4.0,  # 1.0 > 3.2 False, 不 +1
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "neutral"

    def test_all_unhealthy_is_bearish(self):
        """0/3 → bearish."""
        metrics = _make_metrics(
            current_ratio=1.0,  # 1.0 > 1.5 False
            debt_to_equity=0.8,  # 0.8 < 0.5 False
            free_cash_flow_per_share=1.0,
            earnings_per_share=4.0,  # 1.0 > 3.2 False
        )
        signal, _ = _analyze_fundamentals_health(metrics)
        assert signal == "bearish"
