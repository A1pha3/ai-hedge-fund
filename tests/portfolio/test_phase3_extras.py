"""Phase 3 剩余模块测试。"""

from __future__ import annotations

import pandas as pd

from src.execution.models import PendingOrder
from src.portfolio.correlation_cluster import build_correlation_clusters, correlation_threshold_for_market, compute_correlation_matrix, market_median_correlation
from src.portfolio.limit_handler import process_pending_buy, process_pending_sell, queue_pending_buy, queue_pending_sell
from src.portfolio.models import HoldingState, PositionPlan
from src.portfolio.position_calculator import enforce_daily_trade_limit, evaluate_portfolio_risk_guardrails
from src.portfolio.suspension_handler import can_resume_screening, handle_suspension_emergency


def _price_frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": values})


def test_limit_up_queue():
    order = queue_pending_buy("000001", 0.5, "20260305")
    result = process_pending_buy(order, current_score=0.45, is_limit_up=False, opened_board=True, current_price=10.4, reference_close=10.0)
    assert result["action"] == "execute"

    hot_order = PendingOrder(ticker="000001", order_type="buy", original_score=0.5, queue_date="20260305", queue_days=1, reason="limit_up_block")
    hot_result = process_pending_buy(hot_order, current_score=0.45, is_limit_up=True, opened_board=False, current_price=10.0, reference_close=10.0)
    assert hot_result["action"] == "remove"
    assert hot_result["cooldown_days"] == 30


def test_limit_down_queue():
    order = queue_pending_sell("000001", -0.6, "20260305")
    keep = process_pending_sell(order, is_limit_down=True)
    assert keep["action"] == "keep"

    order.queue_days = 2
    risk = process_pending_sell(order, is_limit_down=True)
    assert risk["action"] == "risk_reduce_others"


def test_correlation_cluster():
    matrix = pd.DataFrame(
        [[1.0, 0.85, 0.60], [0.85, 1.0, 0.82], [0.60, 0.82, 1.0]],
        index=["A", "B", "C"],
        columns=["A", "B", "C"],
    )
    clusters = build_correlation_clusters(matrix, threshold=0.8)
    assert any(cluster == {"A", "B", "C"} for cluster in clusters)


def test_correlation_market_correction():
    assert correlation_threshold_for_market(0.61) == 0.7
    assert correlation_threshold_for_market(0.59) == 0.8


def test_suspend_emergency():
    holdings = [
        HoldingState(ticker="000001", entry_price=10, entry_date="20260201", shares=20_000, cost_basis=200_000, industry_sw="银行"),
        HoldingState(ticker="000002", entry_price=10, entry_date="20260201", shares=15_000, cost_basis=150_000, industry_sw="医药"),
        HoldingState(ticker="000003", entry_price=10, entry_date="20260201", shares=10_000, cost_basis=100_000, industry_sw="电子"),
    ]
    result = handle_suspension_emergency(holdings, {"000001": 10, "000002": 10, "000003": 10}, {"000001"}, total_nav=400_000)
    assert "000002" in result
    assert "000003" in result


def test_resume_after_suspension():
    assert can_resume_screening(3, [False, False, False]) is True
    assert can_resume_screening(2, [False, False, False]) is False
    assert can_resume_screening(3, [False, True, False]) is False


def test_daily_trade_limit():
    plans = [
        PositionPlan(ticker="A", shares=100, amount=90_000, constraint_binding="cash", score_final=0.9, execution_ratio=1.0),
        PositionPlan(ticker="B", shares=100, amount=70_000, constraint_binding="cash", score_final=0.8, execution_ratio=1.0),
        PositionPlan(ticker="C", shares=100, amount=50_000, constraint_binding="cash", score_final=0.7, execution_ratio=1.0),
        PositionPlan(ticker="D", shares=100, amount=40_000, constraint_binding="cash", score_final=0.6, execution_ratio=1.0),
    ]
    selected = enforce_daily_trade_limit(plans, portfolio_nav=1_000_000)
    assert len(selected) == 3
    assert sum(plan.amount for plan in selected) <= 200_000


def test_daily_trade_limit_prefers_higher_quality_when_scores_tie():
    plans = [
        PositionPlan(ticker="A", shares=100, amount=60_000, constraint_binding="cash", score_final=0.8, execution_ratio=1.0, quality_score=0.2),
        PositionPlan(ticker="B", shares=100, amount=60_000, constraint_binding="cash", score_final=0.8, execution_ratio=1.0, quality_score=0.9),
        PositionPlan(ticker="C", shares=100, amount=60_000, constraint_binding="cash", score_final=0.8, execution_ratio=1.0, quality_score=0.8),
    ]

    selected = enforce_daily_trade_limit(plans, portfolio_nav=600_000, limit_ratio=0.20, max_new_positions=2)

    assert [plan.ticker for plan in selected] == ["B", "C"]


def test_cvar_warning():
    result = evaluate_portfolio_risk_guardrails(
        industry_hhi=0.10,
        candidate_industry_weight=0.10,
        portfolio_returns=[-0.08, -0.05, -0.02, 0.01, 0.02] * 60,
        benchmark_returns=[-0.03, -0.02, -0.01, 0.01, 0.01] * 60,
        candidate_beta=1.2,
        candidate_is_high_vol=True,
    )
    assert "cvar_warning" in result["alerts"]
    assert result["block_buy"] is True


def test_beta_rebalance():
    result = evaluate_portfolio_risk_guardrails(
        industry_hhi=0.10,
        candidate_industry_weight=0.10,
        portfolio_returns=[-0.03, -0.01, 0.02, 0.03] * 80,
        benchmark_returns=[-0.01, -0.005, 0.01, 0.012] * 80,
        candidate_beta=1.4,
        candidate_is_high_vol=False,
    )
    assert "beta_rebalance" in result["alerts"]
    assert result["prefer_low_beta"] is True


def test_hhi_block():
    result = evaluate_portfolio_risk_guardrails(
        industry_hhi=0.16,
        candidate_industry_weight=0.26,
        portfolio_returns=[0.0] * 50,
        benchmark_returns=[0.0] * 50,
        candidate_beta=0.8,
        candidate_is_high_vol=False,
    )
    assert "hhi_block" in result["alerts"]
    assert result["block_buy"] is True
