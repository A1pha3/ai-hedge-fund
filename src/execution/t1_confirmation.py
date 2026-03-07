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
) -> dict:
    checks = {
        "price_support": day_low >= (ema30 * 0.99),
        "volume_price": intraday_volume >= (avg_same_time_volume * 0.8) and current_price > vwap,
        "industry_strength": industry_percentile <= 0.5 or (stock_pct_change - industry_pct_change) >= 0.02,
    }
    passed = sum(1 for value in checks.values() if value)
    return {"confirmed": passed >= 2, "passed_checks": passed, "checks": checks}
