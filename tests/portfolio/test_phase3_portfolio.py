"""Phase 3 组合风控核心测试。"""

import math

import pytest

import src.portfolio.exit_manager as exit_manager_module
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


def test_score_below_buy_threshold_is_blocked_even_if_it_remains_on_watchlist():
    plan = calculate_position(
        ticker="000001",
        current_price=10.0,
        score_final=0.2042,
        portfolio_nav=100_000,
        available_cash=33_333,
        avg_volume_20d=10_000_000,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "score"
    assert plan.execution_ratio == 0.0
    assert plan.shares == 0
    assert plan.amount == 0.0


def test_avg_volume_20d_uses_wan_cny_unit_before_liquidity_cap_is_applied():
    plan = calculate_position(
        ticker="300724",
        current_price=142.71,
        score_final=0.2309,
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
        score_final=0.2260,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=253_911.41073,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 100
    assert plan.amount == 14271.0


def test_lowest_liquidity_tier_formal_position_is_capped_at_eight_percent():
    plan = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=0.60,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=7_000.0,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.shares == 400
    assert plan.amount == 8_000.0


def test_lowest_liquidity_tier_high_price_name_cannot_bypass_eight_percent_with_min_lot_override():
    plan = calculate_position(
        ticker="300724",
        current_price=85.0,
        score_final=0.2260,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=7_000.0,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.shares == 0
    assert plan.amount == 0.0


def test_nan_avg_volume_20d_does_not_bypass_liquidity_constraint():
    """R20.26-B BETA-006: ``avg_volume_20d`` may arrive as NaN (a ticker
    with no 20-day history, or a Tushare amount field that occasionally
    returns null). The previous code computed ``liq_limit =
    avg_volume_20d * unit * 0.02`` directly — NaN propagates through and
    ``min()`` over a dict containing NaN is non-deterministic (returns
    the first key, "single_name"), so the engine bought the position with
    NO liquidity information at all. NaN must be sanitized before any
    constraint is computed so a liquidity-unknown name is treated as
    illiquid (liq_limit = 0, no position)."""
    plan = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=0.60,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=float("nan"),
        industry_remaining_quota=25_000,
    )
    # NaN-as-liquidity-unknown must surface as a "liquidity" binding at zero
    # (no position), NOT as a silent full-size single_name purchase.
    assert plan.shares == 0
    assert plan.amount == 0.0
    assert plan.constraint_binding == "liquidity"


def test_nan_score_final_returns_zero_position_plan():
    """BETA (R20.32) 回归测试: NaN score_final 必须被拒绝为 0 股 plan.

    修复前: ``score_final < watchlist_min_score`` 对 NaN 返回 False,
    通过了 score gate。后续 ``elif score_final >= standard_execution_score``
    也返回 False, 落到 ``else: execution_ratio = 0.0``, 但中间的所有数值
    计算 (base_shares = allowed_amount / current_price, final_shares = ...)
    都被 NaN 污染。最终 plan 的 shares / amount 是 NaN 而非 0, 会被
    下游误当成合法仓位。

    修复后: 非有限 score_final 在函数入口就被拒绝, 直接返回 shares=0
    且 amount=0.0 的 plan, 与低于 watchlist_min_score 的情况行为一致。
    """
    plan = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=float("nan"),
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=1_000.0,
        industry_remaining_quota=25_000,
    )
    assert plan.shares == 0
    assert plan.amount == 0.0
    assert math.isfinite(plan.amount) or plan.amount == 0.0
    assert plan.execution_ratio == 0.0
    assert plan.constraint_binding == "score"


def test_inf_score_final_returns_zero_position_plan():
    """BETA (R20.32): +Inf / -Inf score_final 也必须被拒绝."""
    for bad_score in (float("inf"), float("-inf")):
        plan = calculate_position(
            ticker="300724",
            current_price=20.0,
            score_final=bad_score,
            portfolio_nav=100_000,
            available_cash=50_000,
            avg_volume_20d=1_000.0,
            industry_remaining_quota=25_000,
        )
        assert plan.shares == 0, f"+/-Inf score_final should yield 0 shares, got {plan.shares} for {bad_score}"
        assert plan.amount == 0.0
        assert plan.execution_ratio == 0.0


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


def test_quality_score_tilts_execution_ratio_for_same_score_band():
    high_quality = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=0.30,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=500_000,
        industry_remaining_quota=25_000,
        quality_score=0.90,
    )
    low_quality = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=0.30,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=500_000,
        industry_remaining_quota=25_000,
        quality_score=0.10,
    )

    assert high_quality.execution_ratio > low_quality.execution_ratio
    assert high_quality.amount > low_quality.amount
    assert high_quality.quality_score == 0.9
    assert low_quality.quality_score == 0.1


def test_watchlist_min_score_can_be_lowered_via_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PIPELINE_WATCHLIST_MIN_SCORE", "0.21")

    plan = calculate_position(
        ticker="600988",
        current_price=20.0,
        score_final=0.217,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=10_000_000,
        industry_remaining_quota=25_000,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 100
    assert plan.amount == 2000.0


def test_watchlist_min_score_can_be_lowered_via_explicit_override():
    plan = calculate_position(
        ticker="600988",
        current_price=20.0,
        score_final=0.217,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=10_000_000,
        industry_remaining_quota=25_000,
        watchlist_min_score_override=0.21,
    )

    assert plan.constraint_binding == "single_name"
    assert plan.execution_ratio == 0.3
    assert plan.shares == 100
    assert plan.amount == 2000.0


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


def test_hard_stop_loss_triggers_at_six_percent_drawdown_boundary():
    holding = HoldingState(ticker="000001", entry_price=10.0, entry_date="20260201", shares=1000, cost_basis=10_000, industry_sw="银行")
    signal = check_exit_signal(holding, current_price=9.39, trade_date="20260307")
    assert signal is not None
    assert signal.level == "L1"
    assert signal.trigger_reason == "hard_stop_loss"


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


def test_profit_retrace_triggers_after_six_percent_peak_reverses_to_one_percent():
    holding = HoldingState(
        ticker="603993",
        entry_price=10.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=10_000,
        industry_sw="有色金属",
        max_unrealized_pnl_pct=0.062,
    )

    signal = check_exit_signal(holding, current_price=10.0, trade_date="20260303")

    assert signal is not None
    assert signal.trigger_reason == "profit_retrace"


def test_high_quality_holding_tolerates_shallow_profit_retrace():
    holding = HoldingState(
        ticker="603993",
        entry_price=10.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=10_000,
        industry_sw="有色金属",
        max_unrealized_pnl_pct=0.082,
        quality_score=0.85,
    )

    signal = check_exit_signal(holding, current_price=10.0, trade_date="20260303")

    assert signal is None


def test_low_quality_holding_exits_on_shallower_profit_retrace():
    holding = HoldingState(
        ticker="603993",
        entry_price=10.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=10_000,
        industry_sw="有色金属",
        max_unrealized_pnl_pct=0.055,
        quality_score=0.2,
    )

    signal = check_exit_signal(holding, current_price=10.19, trade_date="20260303")

    assert signal is not None
    assert signal.trigger_reason == "profit_retrace"


def test_logic_stop_loss_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(exit_manager_module, "LOGIC_STOP_LOSS_SCORE_THRESHOLD", -0.10)
    holding = HoldingState(ticker="603993", entry_price=10.0, entry_date="20260203", shares=1000, cost_basis=10_000, industry_sw="有色金属")

    signal = check_exit_signal(holding, current_price=10.0, trade_date="20260303", logic_score=-0.15)

    assert signal is not None
    assert signal.trigger_reason == "logic_stop_loss"


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


def test_btst_tail_trim_reduces_formal_position_to_last_third_on_day_seven():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=7,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=10.8, trade_date="20260310")

    assert signal is not None
    assert signal.trigger_reason == "btst_tail_trim"
    assert signal.sell_ratio == pytest.approx(2 / 3, rel=1e-6)


def test_btst_fast_confirm_window_trims_when_no_quick_edge_is_confirmed():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=2,
        max_unrealized_pnl_pct=0.02,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=10.02, trade_date="20260304")

    assert signal is not None
    assert signal.trigger_reason == "btst_fast_fail"
    assert signal.sell_ratio == 0.5


def test_btst_fast_confirm_window_exits_when_close_retention_fails():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=2,
        max_unrealized_pnl_pct=0.03,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=9.95, trade_date="20260304")

    assert signal is not None
    assert signal.trigger_reason == "btst_close_retention_fail"
    assert signal.sell_ratio == 1.0


def test_btst_main_trade_window_exits_when_continuation_strength_has_faded():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=5,
        entry_score=0.46,
        max_unrealized_pnl_pct=0.03,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=10.04, trade_date="20260307", logic_score=0.18)

    assert signal is not None
    assert signal.trigger_reason == "btst_main_segment_fail"
    assert signal.sell_ratio == 1.0


def test_btst_main_trade_window_uses_refreshed_runtime_metrics_when_available():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=5,
        entry_score=0.46,
        max_unrealized_pnl_pct=0.03,
        execution_contract_bucket="formal_full",
        btst_runtime_metrics={
            "sector_amt_share": 0.01,
            "sector_breadth_3": 0.08,
            "follow_ratio_2": 0.05,
            "catalyst_freshness": 0.15,
            "flow_60": 0.01,
            "persist_120": 0.44,
            "close_support_30": 0.0,
            "retention_proxy": 0.42,
            "supply_pressure_60": 0.28,
            "failed_breakout_10": 3.0,
            "prior_retention_score": 42.0,
        },
    )

    signal = check_exit_signal(holding, current_price=10.12, trade_date="20260307", logic_score=0.40)

    assert signal is not None
    assert signal.trigger_reason == "btst_main_segment_fail"
    assert signal.sell_ratio == 1.0


def test_btst_tail_trim_respects_existing_stage_one_profit_take():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=7,
        profit_take_stage=1,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=10.8, trade_date="20260310")

    assert signal is not None
    assert signal.trigger_reason == "btst_tail_trim"
    assert signal.sell_ratio == pytest.approx(1 / 3, rel=1e-6)


def test_btst_time_stop_exits_formal_position_after_nine_holding_days():
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260301",
        shares=1000,
        cost_basis=10_000,
        industry_sw="半导体",
        holding_days=10,
        execution_contract_bucket="formal_full",
    )

    signal = check_exit_signal(holding, current_price=10.5, trade_date="20260312")

    assert signal is not None
    assert signal.trigger_reason == "btst_time_stop"
    assert signal.sell_ratio == 1.0


def test_time_stop_uses_trading_day_state_instead_of_calendar_gap():
    holding = HoldingState(
        ticker="603993",
        entry_price=6.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=6000.0,
        industry_sw="有色金属",
        holding_days=15,
    )

    signal = check_exit_signal(holding, current_price=5.88, trade_date="20260224")

    assert signal is None


def test_time_stop_triggers_once_trading_day_limit_is_exceeded():
    holding = HoldingState(
        ticker="603993",
        entry_price=6.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=6000.0,
        industry_sw="有色金属",
        holding_days=21,
    )

    signal = check_exit_signal(holding, current_price=5.88, trade_date="20260224")

    assert signal is not None
    assert signal.trigger_reason == "time_stop"


def test_high_quality_holding_gets_longer_time_stop_grace_period():
    holding = HoldingState(
        ticker="603993",
        entry_price=6.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=6000.0,
        industry_sw="有色金属",
        holding_days=25,
        quality_score=0.9,
    )

    signal = check_exit_signal(holding, current_price=5.88, trade_date="20260224")

    assert signal is None


def test_low_quality_holding_hits_time_stop_earlier():
    holding = HoldingState(
        ticker="603993",
        entry_price=6.0,
        entry_date="20260203",
        shares=1000,
        cost_basis=6000.0,
        industry_sw="有色金属",
        holding_days=16,
        quality_score=0.2,
    )

    signal = check_exit_signal(holding, current_price=5.88, trade_date="20260224")

    assert signal is not None
    assert signal.trigger_reason == "time_stop"
