from __future__ import annotations

from dataclasses import dataclass

from .portfolio import Portfolio
from .trader_helpers import coerce_trade_action, execute_buy_trade, execute_cover_trade, execute_sell_trade, execute_short_trade
from .types import Action, ActionLiteral


@dataclass(frozen=True)
class TradingConstraints:
    commission_rate: float = 0.00025
    stamp_duty_rate: float = 0.001
    base_slippage_rate: float = 0.0015
    low_liquidity_slippage_rate: float = 0.003
    low_liquidity_turnover_threshold: float = 50_000_000.0


def _effective_slippage_rate(constraints: TradingConstraints, daily_turnover: float | None) -> float:
    if daily_turnover is not None and daily_turnover < constraints.low_liquidity_turnover_threshold:
        return constraints.low_liquidity_slippage_rate
    return constraints.base_slippage_rate


class TradeExecutor:
    """Executes trades against a Portfolio with Backtester-identical semantics."""

    def __init__(self, constraints: TradingConstraints | None = None) -> None:
        self._constraints = constraints or TradingConstraints()

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
    ) -> int:
        if quantity is None or quantity <= 0:
            return 0

        action_enum = coerce_trade_action(action)
        slippage_rate = _effective_slippage_rate(self._constraints, daily_turnover)

        if action_enum == Action.BUY:
            if is_limit_up:
                return 0
            return execute_buy_trade(ticker, quantity, current_price, portfolio, slippage_rate, self._constraints.commission_rate)
        if action_enum == Action.SELL:
            if is_limit_down:
                return 0
            return execute_sell_trade(ticker, quantity, current_price, portfolio, slippage_rate, self._constraints.commission_rate, self._constraints.stamp_duty_rate)
        if action_enum == Action.SHORT:
            return execute_short_trade(ticker, quantity, current_price, portfolio, slippage_rate, self._constraints.commission_rate)
        if action_enum == Action.COVER:
            return execute_cover_trade(ticker, quantity, current_price, portfolio, slippage_rate, self._constraints.commission_rate)

        # hold or unknown action
        return 0
