from src.backtesting.portfolio import Portfolio
from src.backtesting.trader import TradeExecutor
from src.backtesting.trading_constraints import TradeExecutionInputs, TradingConstraints, resolve_trade_constraints


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
