import pytest

from src.backtesting.portfolio import Portfolio
from src.backtesting.trader import TradeExecutor
from src.backtesting.trading_constraints import (
    resolve_trade_constraints,
    TradeExecutionInputs,
    TradingConstraints,
)


def test_resolve_trade_constraints_tightens_costs_for_crowded_low_capacity_trade():
    resolved = resolve_trade_constraints(
        TradingConstraints(),
        TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
            projected_theme_exposure=0.31,
            incremental_theme_exposure=0.14,
        ),
    )

    assert resolved.constraint_bucket == "tightened"
    assert resolved.constraints.base_slippage_rate > 0.0015
    assert resolved.capacity_penalty_ratio > 0.0


def test_resolve_trade_constraints_keeps_baseline_path_without_fragility_inputs():
    base_constraints = TradingConstraints()

    resolved = resolve_trade_constraints(base_constraints, None)

    assert resolved.constraint_bucket == "baseline"
    assert resolved.constraints == base_constraints
    assert resolved.capacity_penalty_ratio == 0.0
    assert resolved.diagnostics["daily_turnover"] is None
    assert resolved.diagnostics["liquidity_capacity_raw_100"] is None


def test_trade_executor_records_last_trade_diagnostics():
    portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260422",
    )

    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"


def test_trade_executor_clears_diagnostics_after_noop_trade():
    portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260422",
    )
    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"

    noop_executed = executor.execute_trade("300724", "buy", 0, 10.0, portfolio, trade_date="20260423")

    assert noop_executed == 0
    assert executor.get_last_trade_diagnostics() == {}


def test_trade_executor_clears_diagnostics_after_helper_level_buy_noop():
    seeded_portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    cash_constrained_portfolio = Portfolio(tickers=["300724"], initial_cash=5.0, margin_requirement=0.0)
    executor = TradeExecutor()
    execution_inputs = TradeExecutionInputs(
        daily_turnover=20_000_000.0,
        liquidity_capacity_raw_100=42.0,
        crowding_risk_raw_100=78.0,
        gap_risk_raw_100=64.0,
    )

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        seeded_portfolio,
        execution_inputs=execution_inputs,
        trade_date="20260422",
    )
    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"

    noop_executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        cash_constrained_portfolio,
        execution_inputs=execution_inputs,
        trade_date="20260423",
    )

    assert noop_executed == 0
    assert executor.get_last_trade_diagnostics() == {}


def test_trade_executor_clears_diagnostics_after_helper_level_sell_noop():
    seeded_portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    empty_portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()
    execution_inputs = TradeExecutionInputs(
        daily_turnover=20_000_000.0,
        liquidity_capacity_raw_100=42.0,
        crowding_risk_raw_100=78.0,
        gap_risk_raw_100=64.0,
    )

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        seeded_portfolio,
        execution_inputs=execution_inputs,
        trade_date="20260422",
    )
    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"

    noop_executed = executor.execute_trade(
        "300724",
        "sell",
        1000,
        10.0,
        empty_portfolio,
        execution_inputs=execution_inputs,
        trade_date="20260423",
    )

    assert noop_executed == 0
    assert executor.get_last_trade_diagnostics() == {}


@pytest.mark.parametrize(
    ("action", "trade_kwargs"),
    [
        ("buy", {"is_limit_up": True}),
        ("sell", {"is_limit_down": True}),
    ],
)
def test_trade_executor_clears_diagnostics_after_limit_blocked_noop(action, trade_kwargs):
    portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()

    if action == "sell":
        portfolio.apply_long_buy("300724", 1000, 10.0)

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260422",
    )
    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"

    noop_executed = executor.execute_trade(
        "300724",
        action,
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260423",
        **trade_kwargs,
    )

    assert noop_executed == 0
    assert executor.get_last_trade_diagnostics() == {}


@pytest.mark.parametrize("action", ["hold", "unknown"])
def test_trade_executor_clears_diagnostics_after_hold_or_unknown_noop(action):
    portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260422",
    )
    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"

    noop_executed = executor.execute_trade(
        "300724",
        action,
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260423",
    )

    assert noop_executed == 0
    assert executor.get_last_trade_diagnostics() == {}
