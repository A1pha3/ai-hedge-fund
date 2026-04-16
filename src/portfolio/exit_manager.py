"""五层退出管理器。"""

from __future__ import annotations

import os

from src.portfolio.models import ExitSignal, HoldingState


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


HARD_STOP_LOSS_PCT = -0.06
LOGIC_STOP_LOSS_SCORE_THRESHOLD = _get_env_float("LOGIC_STOP_LOSS_SCORE_THRESHOLD", -0.20)
PROFIT_RETRACE_ARM_PCT = 0.06
PROFIT_RETRACE_EXIT_PCT = 0.01
MAX_HOLDING_DAYS = 20
FUNDAMENTAL_MAX_HOLDING_DAYS = 40


def _quality_adjusted_profit_retrace_thresholds(holding: HoldingState) -> tuple[float, float]:
    quality_score = max(0.0, min(1.0, float(holding.quality_score)))
    if quality_score >= 0.75:
        return 0.08, -0.01
    if quality_score <= 0.35:
        return 0.05, 0.02
    return PROFIT_RETRACE_ARM_PCT, PROFIT_RETRACE_EXIT_PCT


def _quality_adjusted_max_holding_days(holding: HoldingState) -> int:
    base_days = FUNDAMENTAL_MAX_HOLDING_DAYS if holding.is_fundamental_driven else MAX_HOLDING_DAYS
    quality_score = max(0.0, min(1.0, float(holding.quality_score)))
    if quality_score >= 0.75:
        return base_days + 10
    if quality_score <= 0.35:
        return max(10, base_days - 5)
    return base_days


def _holding_pnl_pct(holding: HoldingState, current_price: float) -> float:
    if holding.entry_price <= 0:
        return 0.0
    return (current_price - holding.entry_price) / holding.entry_price


def _atr_stop_price(holding: HoldingState, atr_14: float) -> float:
    return holding.entry_price - (2.0 * atr_14)


def check_exit_signal(
    holding: HoldingState,
    current_price: float,
    trade_date: str,
    atr_14: float = 0.0,
    logic_score: float | None = None,
) -> ExitSignal | None:
    pnl_pct = _holding_pnl_pct(holding, current_price)
    holding_days = max(0, int(holding.holding_days))
    max_pnl = max(holding.max_unrealized_pnl_pct, pnl_pct)
    profit_retrace_arm_pct, profit_retrace_exit_pct = _quality_adjusted_profit_retrace_thresholds(holding)

    if pnl_pct <= HARD_STOP_LOSS_PCT:
        return ExitSignal(ticker=holding.ticker, level="L1", trigger_reason="hard_stop_loss", urgency="next_day", sell_ratio=1.0)

    atr_stop = _atr_stop_price(holding, atr_14)
    hard_stop_price = holding.entry_price * (1.0 + HARD_STOP_LOSS_PCT)
    if atr_14 > 0 and atr_stop > hard_stop_price and current_price < atr_stop:
        return ExitSignal(ticker=holding.ticker, level="L2", trigger_reason="atr_stop_loss", urgency="next_day", sell_ratio=1.0)

    if holding.profit_take_stage == 0 and max_pnl >= profit_retrace_arm_pct and pnl_pct <= profit_retrace_exit_pct:
        return ExitSignal(ticker=holding.ticker, level="L2.5", trigger_reason="profit_retrace", urgency="next_day", sell_ratio=1.0)

    if logic_score is not None and logic_score <= LOGIC_STOP_LOSS_SCORE_THRESHOLD:
        return ExitSignal(ticker=holding.ticker, level="L3", trigger_reason="logic_stop_loss", urgency="next_day", sell_ratio=1.0)

    max_days = _quality_adjusted_max_holding_days(holding)
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
