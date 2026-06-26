from __future__ import annotations

from .portfolio import Portfolio
from .trader_helpers import (
    coerce_trade_action,
    execute_buy_trade,
    execute_cover_trade,
    execute_sell_trade,
    execute_short_trade,
)
from .trading_constraints import (
    resolve_trade_constraints,
    TradeExecutionInputs,
    TradingConstraints,
)
from .types import Action, ActionLiteral


class TradeExecutor:
    """Executes trades against a Portfolio with Backtester-identical semantics."""

    def __init__(self, constraints: TradingConstraints | None = None) -> None:
        self._constraints = constraints or TradingConstraints()
        self._last_trade_diagnostics: dict[str, float | str | None] = {}

    def get_last_trade_diagnostics(self) -> dict[str, float | str | None]:
        return dict(self._last_trade_diagnostics)

    def execute_trade(
        self,
        ticker: str,
        action: ActionLiteral,
        quantity: float,
        current_price: float,
        portfolio: Portfolio,
        *,
        is_limit_up: bool = False,
        is_limit_down: bool = False,
        daily_turnover: float | None = None,
        execution_inputs: TradeExecutionInputs | None = None,
        trade_date: str | None = None,
    ) -> int:
        if quantity is None or quantity <= 0:
            self._last_trade_diagnostics = {}
            return 0

        action_enum = coerce_trade_action(action)
        resolved_inputs = execution_inputs if execution_inputs is not None else TradeExecutionInputs(daily_turnover=daily_turnover)
        if resolved_inputs.daily_turnover is None and daily_turnover is not None:
            resolved_inputs = TradeExecutionInputs(
                daily_turnover=daily_turnover,
                liquidity_capacity_raw_100=resolved_inputs.liquidity_capacity_raw_100,
                crowding_risk_raw_100=resolved_inputs.crowding_risk_raw_100,
                gap_risk_raw_100=resolved_inputs.gap_risk_raw_100,
                projected_theme_exposure=resolved_inputs.projected_theme_exposure,
                incremental_theme_exposure=resolved_inputs.incremental_theme_exposure,
            )
        resolved_constraints = resolve_trade_constraints(self._constraints, resolved_inputs)
        diagnostics = dict(resolved_constraints.diagnostics)
        slippage_rate = resolved_constraints.constraints.base_slippage_rate

        if action_enum == Action.BUY:
            if is_limit_up:
                self._last_trade_diagnostics = {}
                return 0
            executed = execute_buy_trade(
                ticker,
                quantity,
                current_price,
                portfolio,
                slippage_rate,
                self._constraints.commission_rate,
                resolved_inputs.daily_turnover,
                self._constraints.commission_floor_yuan,
            )
            self._last_trade_diagnostics = diagnostics if executed > 0 else {}
            return executed
        if action_enum == Action.SELL:
            if is_limit_down:
                self._last_trade_diagnostics = {}
                return 0
            executed = execute_sell_trade(
                ticker,
                quantity,
                current_price,
                portfolio,
                slippage_rate,
                self._constraints.commission_rate,
                self._constraints.stamp_duty_rate,
                trade_date,
                resolved_inputs.daily_turnover,
                self._constraints.commission_floor_yuan,
            )
            self._last_trade_diagnostics = diagnostics if executed > 0 else {}
            return executed
        if action_enum == Action.SHORT:
            executed = execute_short_trade(
                ticker,
                quantity,
                current_price,
                portfolio,
                slippage_rate,
                self._constraints.commission_rate,
                resolved_inputs.daily_turnover,
                self._constraints.commission_floor_yuan,
            )
            self._last_trade_diagnostics = diagnostics if executed > 0 else {}
            return executed
        if action_enum == Action.COVER:
            executed = execute_cover_trade(
                ticker,
                quantity,
                current_price,
                portfolio,
                slippage_rate,
                self._constraints.commission_rate,
                resolved_inputs.daily_turnover,
                self._constraints.commission_floor_yuan,
            )
            self._last_trade_diagnostics = diagnostics if executed > 0 else {}
            return executed

        # hold or unknown action
        self._last_trade_diagnostics = {}
        return 0
