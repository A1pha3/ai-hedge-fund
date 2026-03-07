"""停牌应急处理器。"""

from __future__ import annotations

from src.portfolio.models import HoldingState


def handle_suspension_emergency(
    holdings: list[HoldingState],
    prices: dict[str, float],
    suspended_tickers: set[str],
    total_nav: float,
    suspension_threshold: float = 0.10,
) -> dict[str, float]:
    suspended_value = 0.0
    liquid_holdings: list[HoldingState] = []
    liquid_value = 0.0
    for holding in holdings:
        market_value = prices.get(holding.ticker, holding.entry_price) * holding.shares
        if holding.ticker in suspended_tickers:
            suspended_value += market_value
        else:
            liquid_holdings.append(holding)
            liquid_value += market_value

    if total_nav <= 0 or suspended_value / total_nav <= suspension_threshold or liquid_value <= 0:
        return {}

    release_ratio = min((suspended_value / total_nav) - suspension_threshold, 0.5)
    return {holding.ticker: release_ratio for holding in liquid_holdings}


def can_resume_screening(days_since_resume: int, recent_limit_statuses: list[bool]) -> bool:
    if days_since_resume < 3:
        return False
    if len(recent_limit_statuses) < 3:
        return False
    return not any(recent_limit_statuses[-3:])
