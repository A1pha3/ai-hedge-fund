"""Phase 3 剩余模块测试。"""

from __future__ import annotations

import pandas as pd

from src.execution.models import PendingOrder
from src.portfolio.correlation_cluster import build_correlation_clusters, correlation_threshold_for_market
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


def test_cvar_uses_ceil_not_truncation_for_tail_count():
    """GAMMA-006 / ALPHA-002: N=21 returns → tail_size must be 2 (ceil),
    not 1 (int() truncation). With 2 worst observations averaging -0.10,
    abs(cvar)=-0.10 is below the -0.03 threshold → cvar_warning fires.
    The old int-truncation formula would have used only 1 obs and the
    same threshold still fires — so this test alone doesn't catch the
    off-by-one; the real test is for cases where the 2nd-worst is
    significantly less bad than the worst. Here we use:
       20 returns of -0.05 (worst) + 1 return of -0.005 (second-worst)
    With ceil: k=2 → cvar_95 = (-0.05 + -0.005)/2 = -0.0275 (NOT < -0.03)
    With int-truncation: k=1 → cvar_95 = -0.05 (< -0.03, fires warning)
    The fix changes the verdict for this case from BLOCK to NO-BLOCK."""
    # 21 returns: 1 worst, 20 second-worst
    portfolio_returns = [-0.005] * 20 + [-0.05]
    result = evaluate_portfolio_risk_guardrails(
        industry_hhi=0.10,
        candidate_industry_weight=0.10,
        portfolio_returns=portfolio_returns,
        benchmark_returns=[0.0] * 21,
        candidate_beta=1.0,
        candidate_is_high_vol=True,
    )
    # With ceil: k=2 → cvar_95=-0.0275 (NOT < -0.03) → no cvar_warning
    assert "cvar_warning" not in result["alerts"]
    assert result["block_buy"] is False
    # Sanity: cvar_95 is signed and approximately what we expect
    assert -0.030 <= result["cvar_95"] <= -0.025


def test_cvar_sign_convention_uses_negative_threshold():
    """GAMMA-006: cvar_95 is signed (negative for losses). The old
    `abs(cvar_95) > 0.03` was a band-aid that would also fire for a
    positive tail-mean. The fix uses `cvar_95 < -0.03` (explicit
    negative sign) so that only a true loss tail triggers the block.

    Construct a portfolio where the tail is POSITIVE (mean of 5 worst
    observations is positive because all returns are positive) — the
    old abs() would have triggered cvar_warning (>0.03), the new sign
    check correctly does not."""
    # 20 returns all positive; tail = ceil(0.05*20)=1 → mean of the
    # single smallest = 0.01 > 0. Old abs()=0.01 would not fire either,
    # so use a more aggressive setup.
    # 20 returns: 5 at -0.08 (worst), 15 at +0.10. tail = 1 → worst = -0.08
    # abs() old code: |-0.08| > 0.03 → fires; new sign: -0.08 < -0.03 → fires.
    # This doesn't differentiate. Instead construct: 20 obs of +0.05.
    # tail=1 → mean of 1 obs of +0.05 = +0.05. abs() old: |0.05|>0.03 → fires
    # (false positive!). New sign: 0.05 < -0.03 → False → no fire.
    portfolio_returns = [0.05] * 20
    result = evaluate_portfolio_risk_guardrails(
        industry_hhi=0.10,
        candidate_industry_weight=0.10,
        portfolio_returns=portfolio_returns,
        benchmark_returns=[0.0] * 20,
        candidate_beta=1.0,
        candidate_is_high_vol=True,
    )
    # Old abs() code: |+0.05| = 0.05 > 0.03 → fires cvar_warning (WRONG)
    # New sign code: +0.05 < -0.03 is False → no warning (CORRECT)
    assert "cvar_warning" not in result["alerts"], (
        "Positive tail-mean should not trigger cvar_warning; "
        "old abs() was too permissive"
    )
    assert result["block_buy"] is False
    assert result["cvar_95"] > 0.0, (
        f"Expected positive tail-mean, got {result['cvar_95']}"
    )


# ---------------------------------------------------------------------------
# BETA-005: pending buy queue max expiry
# ---------------------------------------------------------------------------

def test_pending_buy_expires_after_max_queue_days():
    """BETA-005: a pending buy order that stays in the queue beyond
    MAX_PENDING_BUY_QUEUE_DAYS must be auto-removed with reason
    'queue_expired', even if it was never limit-up and no board opened."""
    from src.portfolio.limit_handler import MAX_PENDING_BUY_QUEUE_DAYS
    # Walk the order up to the max
    order = queue_pending_buy("000001", 0.5, "20260305")
    for _ in range(MAX_PENDING_BUY_QUEUE_DAYS):
        result = process_pending_buy(order, current_score=0.45, is_limit_up=False, opened_board=False, current_price=10.0, reference_close=10.0)
        if result["action"] == "keep":
            order = PendingOrder(
                ticker=order.ticker, order_type=order.order_type,
                original_score=order.original_score, queue_date=order.queue_date,
                queue_days=result["queue_days"], reason=order.reason,
                shares=order.shares, amount=order.amount,
            )
    # After MAX days, the next call should expire
    result = process_pending_buy(order, current_score=0.45, is_limit_up=False, opened_board=False, current_price=10.0, reference_close=10.0)
    assert result["action"] == "remove"
    assert result["reason"] == "queue_expired"


def test_pending_buy_does_not_expire_before_max_queue_days():
    """BETA-005: order should still be kept when queue_days < MAX."""
    order = queue_pending_buy("000001", 0.5, "20260305")
    result = process_pending_buy(order, current_score=0.45, is_limit_up=False, opened_board=False, current_price=10.0, reference_close=10.0)
    assert result["action"] == "keep"
