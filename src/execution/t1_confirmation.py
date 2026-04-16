"""T+1 确认执行器。"""

from __future__ import annotations


def confirm_buy_signal(
    day_low: float,
    ema30: float,
    current_price: float,
    vwap: float,
    intraday_volume: float,
    avg_same_time_volume: float,
    industry_percentile: float,
    stock_pct_change: float = 0.0,
    industry_pct_change: float = 0.0,
    open_price: float = 0.0,
    prev_close: float = 0.0,
    breakout_anchor: float = 0.0,
    open_gap_pct: float | None = None,
    minutes_since_open: int | float | None = None,
    failed_breakout: bool = False,
    max_open_gap_pct: float = 0.03,
) -> dict:
    soft_checks = {
        "price_support": day_low >= (ema30 * 0.99),
        "volume_price": intraday_volume >= (avg_same_time_volume * 0.8) and current_price > vwap,
        "industry_strength": industry_percentile <= 0.5 or (stock_pct_change - industry_pct_change) >= 0.02,
    }
    hard_failures: dict[str, bool] = {}
    active_soft_checks = dict(soft_checks)

    resolved_open_gap_pct = float(open_gap_pct) if open_gap_pct is not None else ((open_price / prev_close) - 1.0 if open_price > 0 and prev_close > 0 else None)
    if resolved_open_gap_pct is not None:
        hard_failures["open_gap_overextended"] = float(resolved_open_gap_pct) > float(max_open_gap_pct)
        active_soft_checks["open_gap_controlled"] = float(resolved_open_gap_pct) <= float(max_open_gap_pct)

    if open_price > 0 and prev_close > 0 and minutes_since_open is not None and float(minutes_since_open) >= 5.0:
        active_soft_checks["reclaimed_open_and_prev_close"] = current_price >= max(open_price, prev_close)

    if breakout_anchor > 0:
        active_soft_checks["breakout_anchor_hold"] = day_low >= (breakout_anchor * 0.995) and current_price >= breakout_anchor

    if failed_breakout:
        hard_failures["failed_breakout_abort"] = True

    hard_failed = any(hard_failures.values())
    passed = sum(1 for value in active_soft_checks.values() if value)
    total_checks = len(active_soft_checks)
    required_passes = 2 if total_checks <= 3 else 3 if total_checks <= 5 else 4
    confirmed = (not hard_failed) and passed >= required_passes
    return {
        "confirmed": confirmed,
        "passed_checks": passed,
        "required_passes": required_passes,
        "checks": active_soft_checks,
        "hard_failures": hard_failures,
    }
