"""Phase 3 组合风控核心测试。"""

from src.portfolio.exit_manager import check_exit_signal
from src.portfolio.industry_exposure import calculate_industry_exposures, calculate_portfolio_hhi, get_industry_remaining_quota
from src.portfolio.models import HoldingState
from src.portfolio.position_calculator import calculate_position


def test_position_min_constraint():
    plan = calculate_position(
        ticker="000001",
        current_price=10.0,
        score_final=0.60,
        portfolio_nav=1_000_000,
        available_cash=500_000,
        avg_volume_20d=80.0,
        industry_remaining_quota=300_000,
        correlation_adjustment=0.8,
        vol_adjusted_ratio=0.10,
    )
    assert plan.constraint_binding == "liquidity"
    assert plan.amount == 16000.0


def test_round_to_100():
    plan = calculate_position(
        ticker="000001",
        current_price=10.3,
        score_final=0.60,
        portfolio_nav=1_000_000,
        available_cash=500_000,
        avg_volume_20d=81_111,
        industry_remaining_quota=500_000,
    )
    assert plan.shares % 100 == 0


def test_watchlist_edge_score_gets_small_position_instead_of_full_block():
    plan = calculate_position(
        ticker="000001",
        current_price=10.0,
        score_final=0.2042,
        portfolio_nav=100_000,
        available_cash=33_333,
        avg_volume_20d=10_000_000,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 300
    assert plan.amount == 3000.0


def test_avg_volume_20d_uses_wan_cny_unit_before_liquidity_cap_is_applied():
    plan = calculate_position(
        ticker="300724",
        current_price=142.71,
        score_final=0.2209,
        portfolio_nav=100_000,
        available_cash=33_333,
        avg_volume_20d=253_911.41073,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 100
    assert plan.amount == 14271.0


def test_watchlist_edge_high_price_name_keeps_one_lot_when_constraints_allow_it():
    plan = calculate_position(
        ticker="300724",
        current_price=142.71,
        score_final=0.2186,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=253_911.41073,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 100
    assert plan.amount == 14271.0


def test_existing_position_ratio_blocks_additional_single_name_pyramiding():
    plan = calculate_position(
        ticker="300724",
        current_price=142.71,
        score_final=0.2269,
        portfolio_nav=100_000,
        available_cash=20_000,
        avg_volume_20d=253_911.41073,
        industry_remaining_quota=25_000,
        existing_position_ratio=0.857,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.shares == 0
    assert plan.amount == 0.0


def test_industry_limit():
    holdings = [
        HoldingState(ticker="000001", entry_price=10, entry_date="20260201", shares=10_000, cost_basis=100_000, industry_sw="银行"),
        HoldingState(ticker="000002", entry_price=15, entry_date="20260201", shares=10_000, cost_basis=150_000, industry_sw="银行"),
    ]
    exposures = calculate_industry_exposures(holdings, {"000001": 10, "000002": 15}, total_nav=1_000_000)
    remaining = get_industry_remaining_quota("银行", exposures, 1_000_000)
    assert remaining == 0.0


def test_hhi_calculation():
    holdings = [
        HoldingState(ticker="000001", entry_price=10, entry_date="20260201", shares=10_000, cost_basis=100_000, industry_sw="银行"),
        HoldingState(ticker="000002", entry_price=20, entry_date="20260201", shares=5_000, cost_basis=100_000, industry_sw="医药"),
    ]
    exposures = calculate_industry_exposures(holdings, {"000001": 10, "000002": 20}, total_nav=500_000)
    hhi = calculate_portfolio_hhi(exposures)
    assert round(hhi, 4) == 0.08


def test_hard_stop_loss():
    holding = HoldingState(ticker="000001", entry_price=10.0, entry_date="20260201", shares=1000, cost_basis=10_000, industry_sw="银行")
    signal = check_exit_signal(holding, current_price=9.2, trade_date="20260307")
    assert signal is not None
    assert signal.level == "L1"


def test_trailing_stop():
    holding = HoldingState(
        ticker="000001",
        entry_price=10.0,
        entry_date="20260201",
        shares=1000,
        cost_basis=10_000,
        industry_sw="银行",
        max_unrealized_pnl_pct=0.18,
        profit_take_stage=1,
    )
    signal = check_exit_signal(holding, current_price=10.8, trade_date="20260307")
    assert signal is not None
    assert signal.level == "L5"
    assert signal.trigger_reason == "trailing_profit_stop"


def test_staged_profit_take():
    holding = HoldingState(ticker="000001", entry_price=10.0, entry_date="20260201", shares=1000, cost_basis=10_000, industry_sw="银行")
    signal_stage_1 = check_exit_signal(holding, current_price=11.6, trade_date="20260307")
    assert signal_stage_1 is not None
    assert signal_stage_1.sell_ratio == 0.5

    holding.profit_take_stage = 1
    signal_stage_2 = check_exit_signal(holding, current_price=12.6, trade_date="20260307")
    assert signal_stage_2 is not None
    assert signal_stage_2.sell_ratio == 0.6


def test_l25_l5_mutual_exclusion():
    holding = HoldingState(
        ticker="000001",
        entry_price=10.0,
        entry_date="20260201",
        shares=1000,
        cost_basis=10_000,
        industry_sw="银行",
        max_unrealized_pnl_pct=0.20,
        profit_take_stage=1,
    )
    signal = check_exit_signal(holding, current_price=10.0, trade_date="20260307")
    assert signal is not None
    assert signal.level == "L5"
    assert signal.trigger_reason == "trailing_profit_stop"


def test_l4_l5_mutual_exclusion():
    holding = HoldingState(
        ticker="000001",
        entry_price=10.0,
        entry_date="20260101",
        shares=1000,
        cost_basis=10_000,
        industry_sw="银行",
        holding_days=40,
        profit_take_stage=1,
        max_unrealized_pnl_pct=0.30,
    )
    signal = check_exit_signal(holding, current_price=12.0, trade_date="20260307")
    assert signal is not None
    assert signal.level == "L5"
