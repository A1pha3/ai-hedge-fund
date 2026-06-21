"""买入信号盘中确认器 (buy-signal intraday confirmation)。

R148: 此模块原名 ``t1_confirmation``，但其唯一函数 :func:`confirm_buy_signal`
做的是**买入信号的盘中软/硬检查**（价格支撑 / 量能 / 行业强度 / 开盘缺口 / 突破），
与 A 股 T+1 结算无关。真正的 T+1 卖出门控在
``src/backtesting/trader_helpers.py:execute_sell_trade``（entry_date==trade_date
+ long>0 → block）+ ``src/backtesting/portfolio.py`` 的 holding-days 账本。
旧名是维护陷阱（grep "t1" 会落到错文件、漏掉真正的 T+1 闸门），故改名。

.. note::
    ``day_low`` 是收盘后才能确定的指标。在回测场景下这没有问题，但如果用于
    盘中实时确认则存在前视偏差 (look-ahead bias)。当 ``is_intraday=True``
    时，涉及 ``day_low`` 的检查会自动替换为基于 ``current_price`` 的版本。
"""

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
    is_intraday: bool = False,
) -> dict:
    """Confirm a buy signal using soft/hard checks.

    Args:
        day_low: Intraday lowest price — only known after market close.
            In backtest mode (``is_intraday=False``) this is fine.  When
            ``is_intraday=True`` the function substitutes ``current_price``
            for ``day_low`` in every check that would otherwise rely on it,
            thereby eliminating look-ahead bias.
        is_intraday: Set to ``True`` when this function is called during
            live intraday decision-making.  Defaults to ``False`` (backtest).
    """
    # When used intraday, day_low is not yet known — use current_price as a
    # conservative real-time substitute to avoid look-ahead bias.
    effective_low = current_price if is_intraday else day_low

    soft_checks = {
        "price_support": effective_low >= (ema30 * 0.99),
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
        active_soft_checks["breakout_anchor_hold"] = effective_low >= (breakout_anchor * 0.995) and current_price >= breakout_anchor

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
