"""五层退出管理器。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.portfolio.models import ExitSignal, HoldingState

HARD_STOP_LOSS_PCT = -0.07
MAX_HOLDING_DAYS = 20
FUNDAMENTAL_MAX_HOLDING_DAYS = 40


def _holding_pnl_pct(holding: HoldingState, current_price: float) -> float:
    if holding.entry_price <= 0:
        return 0.0
    return (current_price - holding.entry_price) / holding.entry_price


def _atr_stop_price(holding: HoldingState, atr_14: float) -> float:
    return holding.entry_price - (2.0 * atr_14)


def _days_between(start_date: str, end_date: str) -> int:
    try:
        return (datetime.strptime(end_date, "%Y%m%d") - datetime.strptime(start_date, "%Y%m%d")).days
    except ValueError:
        return 0


def check_exit_signal(
    holding: HoldingState,
    current_price: float,
    trade_date: str,
    atr_14: float = 0.0,
    logic_score: Optional[float] = None,
) -> Optional[ExitSignal]:
    pnl_pct = _holding_pnl_pct(holding, current_price)
    holding_days = max(holding.holding_days, _days_between(holding.entry_date, trade_date))
    max_pnl = max(holding.max_unrealized_pnl_pct, pnl_pct)

    if pnl_pct <= HARD_STOP_LOSS_PCT:
        return ExitSignal(ticker=holding.ticker, level="L1", trigger_reason="hard_stop_loss", urgency="next_day", sell_ratio=1.0)

    atr_stop = _atr_stop_price(holding, atr_14)
    hard_stop_price = holding.entry_price * (1.0 + HARD_STOP_LOSS_PCT)
    if atr_14 > 0 and atr_stop > hard_stop_price and current_price < atr_stop:
        return ExitSignal(ticker=holding.ticker, level="L2", trigger_reason="atr_stop_loss", urgency="next_day", sell_ratio=1.0)

    if holding.profit_take_stage == 0 and max_pnl >= 0.08 and pnl_pct <= 0.01:
        return ExitSignal(ticker=holding.ticker, level="L2.5", trigger_reason="profit_retrace", urgency="next_day", sell_ratio=1.0)

    if logic_score is not None and logic_score <= -0.20:
        return ExitSignal(ticker=holding.ticker, level="L3", trigger_reason="logic_stop_loss", urgency="next_day", sell_ratio=1.0)

    max_days = FUNDAMENTAL_MAX_HOLDING_DAYS if holding.is_fundamental_driven else MAX_HOLDING_DAYS
    if holding.profit_take_stage == 0 and holding_days > max_days and pnl_pct < 0.03:
        return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="time_stop", urgency="next_day", sell_ratio=1.0)

    if pnl_pct >= 0.15 and holding.profit_take_stage == 0:
        return ExitSignal(ticker=holding.ticker, level="L5", trigger_reason="profit_take_stage_1", urgency="next_day", sell_ratio=0.5)

    if pnl_pct >= 0.25 and holding.profit_take_stage == 1:
        return ExitSignal(ticker=holding.ticker, level="L5", trigger_reason="profit_take_stage_2", urgency="next_day", sell_ratio=0.6)

    if holding.profit_take_stage >= 1 and max_pnl > 0:
        trailing_gap = max(0.05, max_pnl * 0.30)
        if pnl_pct <= max_pnl - trailing_gap:
            return ExitSignal(ticker=holding.ticker, level="L5", trigger_reason="trailing_profit_stop", urgency="next_day", sell_ratio=1.0)

    return None
