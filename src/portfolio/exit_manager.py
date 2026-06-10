"""五层退出管理器。"""

from __future__ import annotations

from src.portfolio.models import ExitSignal, HoldingState
from src.targets.short_trade_target_committee_helpers import (
    _flow_raw_score,
    _retention_raw_score,
    _sector_raw_score,
)
from src.utils.env_helpers import get_env_float

HARD_STOP_LOSS_PCT = -0.06
LOGIC_STOP_LOSS_SCORE_THRESHOLD = get_env_float("LOGIC_STOP_LOSS_SCORE_THRESHOLD", -0.20)
PROFIT_RETRACE_ARM_PCT = 0.06
PROFIT_RETRACE_EXIT_PCT = 0.01
MAX_HOLDING_DAYS = 20
FUNDAMENTAL_MAX_HOLDING_DAYS = 40
BTST_FAST_CONFIRM_HIGH_PCT = 0.04
BTST_FAST_CONFIRM_CLOSE_PCT = 0.01
BTST_MAIN_SEGMENT_CLOSE_PCT = 0.01
BTST_MAIN_SEGMENT_LOGIC_SCORE_MIN = 0.25
BTST_MAIN_SEGMENT_ENTRY_SCORE_TOLERANCE = 0.08
BTST_MAIN_SEGMENT_GROUP_SCORE_MIN = 60.0


def _is_btst_formal_contract(holding: HoldingState) -> bool:
    return str(getattr(holding, "execution_contract_bucket", "") or "").strip().lower() in {"formal_full", "formal_capped"}


def _btst_tail_trim_sell_ratio(holding: HoldingState) -> float | None:
    stage = max(0, int(holding.profit_take_stage))
    if stage >= 3:
        return None
    if stage <= 0:
        return 2.0 / 3.0
    if stage == 1:
        return 1.0 / 3.0
    return None


def _btst_main_segment_logic_threshold(holding: HoldingState) -> float:
    return max(
        BTST_MAIN_SEGMENT_LOGIC_SCORE_MIN,
        float(holding.entry_score or 0.0) - BTST_MAIN_SEGMENT_ENTRY_SCORE_TOLERANCE,
    )


def _btst_has_precise_main_segment_metrics(raw_metrics: dict[str, object]) -> bool:
    required_groups = (
        {"sector_amt_share", "sector_breadth_3", "follow_ratio_2", "catalyst_freshness"},
        {"flow_60", "persist_120", "close_support_30"},
        {"retention_proxy", "supply_pressure_60", "failed_breakout_10", "prior_retention_score"},
    )
    return all(any(key in raw_metrics for key in group_keys) for group_keys in required_groups)


def _btst_precise_main_segment_failed(raw_metrics: dict[str, object]) -> bool:
    if not _btst_has_precise_main_segment_metrics(raw_metrics):
        return False
    sector_score, _ = _sector_raw_score({}, raw_metrics)
    flow_score, _ = _flow_raw_score({}, raw_metrics)
    retention_score, _ = _retention_raw_score({}, raw_metrics)
    return min(sector_score, flow_score, retention_score) < BTST_MAIN_SEGMENT_GROUP_SCORE_MIN


def _btst_formal_contract_signal(
    holding: HoldingState,
    *,
    pnl_pct: float,
    max_pnl: float,
    logic_score: float | None,
) -> ExitSignal | None:
    if not _is_btst_formal_contract(holding):
        return None

    holding_days = max(0, int(holding.holding_days))
    if 2 <= holding_days <= 3:
        if pnl_pct <= 0:
            return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="btst_close_retention_fail", urgency="next_day", sell_ratio=1.0)
        fast_confirmed = max_pnl >= BTST_FAST_CONFIRM_HIGH_PCT or pnl_pct >= BTST_FAST_CONFIRM_CLOSE_PCT
        if not fast_confirmed:
            # Position is still positive on close (already returned above for pnl<=0).
            # Treat a positive close itself as a soft confirm — only half-exit, not full.
            return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="btst_fast_fail", urgency="next_day", sell_ratio=0.5)

    if 4 <= holding_days <= 6:
        runtime_metrics = dict(getattr(holding, "btst_runtime_metrics", {}) or {})
        if _btst_precise_main_segment_failed(runtime_metrics):
            return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="btst_main_segment_fail", urgency="next_day", sell_ratio=1.0)
        continuation_logic_threshold = _btst_main_segment_logic_threshold(holding)
        continuation_logic_ok = logic_score is not None and float(logic_score) >= continuation_logic_threshold
        continuation_close_ok = pnl_pct >= BTST_MAIN_SEGMENT_CLOSE_PCT
        if not continuation_logic_ok or not continuation_close_ok:
            return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="btst_main_segment_fail", urgency="next_day", sell_ratio=1.0)

    return None


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
    # Only apply the ATR-based stop when it's *wider* than the hard stop
    # (i.e. 2*atr_14 >= 6% of entry). Otherwise the ATR stop is a no-op that
    # would fire on tiny dips in low-vol names, which is not the intent.
    atr_wider_than_hard = (
        atr_14 > 0
        and (holding.entry_price - atr_stop) >= abs(holding.entry_price * HARD_STOP_LOSS_PCT)
    )
    if atr_wider_than_hard and current_price < atr_stop:
        return ExitSignal(ticker=holding.ticker, level="L2", trigger_reason="atr_stop_loss", urgency="next_day", sell_ratio=1.0)

    if holding.profit_take_stage == 0 and max_pnl >= profit_retrace_arm_pct and pnl_pct <= profit_retrace_exit_pct:
        return ExitSignal(ticker=holding.ticker, level="L2.5", trigger_reason="profit_retrace", urgency="next_day", sell_ratio=1.0)

    if logic_score is not None and logic_score <= LOGIC_STOP_LOSS_SCORE_THRESHOLD:
        return ExitSignal(ticker=holding.ticker, level="L3", trigger_reason="logic_stop_loss", urgency="next_day", sell_ratio=1.0)

    btst_formal_contract_signal = _btst_formal_contract_signal(
        holding,
        pnl_pct=pnl_pct,
        max_pnl=max_pnl,
        logic_score=logic_score,
    )
    if btst_formal_contract_signal is not None:
        return btst_formal_contract_signal

    if _is_btst_formal_contract(holding):
        if holding_days > 9:
            return ExitSignal(ticker=holding.ticker, level="L4", trigger_reason="btst_time_stop", urgency="next_day", sell_ratio=1.0)
        if 7 <= holding_days <= 9:
            tail_trim_sell_ratio = _btst_tail_trim_sell_ratio(holding)
            if tail_trim_sell_ratio is not None:
                return ExitSignal(ticker=holding.ticker, level="L5", trigger_reason="btst_tail_trim", urgency="next_day", sell_ratio=tail_trim_sell_ratio)

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
