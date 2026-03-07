from __future__ import annotations

from dataclasses import dataclass

from .portfolio import Portfolio
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

        # Coerce to enum if strings provided
        try:
            action_enum = Action(action) if not isinstance(action, Action) else action
        except Exception:
            action_enum = Action.HOLD

        slippage_rate = _effective_slippage_rate(self._constraints, daily_turnover)

        if action_enum == Action.BUY:
            if is_limit_up:
                return 0
            executed_price = float(current_price) * (1 + slippage_rate)
            max_affordable = int(portfolio.get_cash() / (executed_price * (1 + self._constraints.commission_rate))) if executed_price > 0 else 0
            requested_quantity = min(int(quantity), max_affordable)
            executed = portfolio.apply_long_buy(ticker, requested_quantity, executed_price)
            if executed > 0:
                commission = executed * executed_price * self._constraints.commission_rate
                portfolio.adjust_cash(-commission)
            return executed
        if action_enum == Action.SELL:
            if is_limit_down:
                return 0
            executed_price = float(current_price) * (1 - slippage_rate)
            executed = portfolio.apply_long_sell(ticker, int(quantity), executed_price)
            if executed > 0:
                gross_amount = executed * executed_price
                fees = gross_amount * (self._constraints.commission_rate + self._constraints.stamp_duty_rate)
                portfolio.adjust_cash(-fees)
            return executed
        if action_enum == Action.SHORT:
            executed_price = float(current_price) * (1 - slippage_rate)
            executed = portfolio.apply_short_open(ticker, int(quantity), executed_price)
            if executed > 0:
                commission = executed * executed_price * self._constraints.commission_rate
                portfolio.adjust_cash(-commission)
            return executed
        if action_enum == Action.COVER:
            executed_price = float(current_price) * (1 + slippage_rate)
            executed = portfolio.apply_short_cover(ticker, int(quantity), executed_price)
            if executed > 0:
                commission = executed * executed_price * self._constraints.commission_rate
                portfolio.adjust_cash(-commission)
            return executed

        # hold or unknown action
        return 0
