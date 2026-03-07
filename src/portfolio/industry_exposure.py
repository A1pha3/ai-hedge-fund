"""行业暴露计算器。"""

from __future__ import annotations

from collections import defaultdict

from src.portfolio.models import HoldingState, IndustryExposure


def calculate_industry_exposures(
    holdings: list[HoldingState],
    prices: dict[str, float],
    total_nav: float,
    industry_limit_ratio: float = 0.25,
) -> list[IndustryExposure]:
    grouped_values: dict[str, float] = defaultdict(float)
    for holding in holdings:
        current_price = prices.get(holding.ticker, holding.entry_price)
        grouped_values[holding.industry_sw or "unknown"] += current_price * holding.shares

    exposures: list[IndustryExposure] = []
    for industry, market_value in sorted(grouped_values.items()):
        weight = (market_value / total_nav) if total_nav > 0 else 0.0
        remaining_quota = max(industry_limit_ratio * total_nav - market_value, 0.0)
        exposures.append(
            IndustryExposure(
                industry=industry,
                market_value=market_value,
                weight=weight,
                remaining_quota=remaining_quota,
            )
        )
    return exposures


def calculate_portfolio_hhi(exposures: list[IndustryExposure]) -> float:
    return sum(exposure.weight ** 2 for exposure in exposures)


def get_industry_remaining_quota(
    industry: str,
    exposures: list[IndustryExposure],
    total_nav: float,
    industry_limit_ratio: float = 0.25,
) -> float:
    for exposure in exposures:
        if exposure.industry == industry:
            return exposure.remaining_quota
    return industry_limit_ratio * total_nav
