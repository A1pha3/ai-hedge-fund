"""增强仓位计算器。"""

from __future__ import annotations

import math

from src.portfolio.models import PositionPlan
from src.utils.env_helpers import get_env_float

WATCHLIST_MIN_SCORE = 0.225
FULL_EXECUTION_SCORE = 0.50
STANDARD_EXECUTION_SCORE = 0.25
WATCHLIST_EDGE_EXECUTION_RATIO = 0.3
AVG_VOLUME_20D_AMOUNT_UNIT = 10_000.0
A_SHARE_MIN_LOT = 100
MIN_LOT_OVERRIDE_MAX_RATIO = 0.15
LOWEST_LIQUIDITY_TIER_SINGLE_NAME_LIMIT = 0.08
LOWEST_LIQUIDITY_TIER_MAX_AVG_VOLUME_20D = 7_500.0


def _get_execution_thresholds() -> tuple[float, float, float, float]:
    return (
        get_env_float("PIPELINE_WATCHLIST_MIN_SCORE", WATCHLIST_MIN_SCORE),
        get_env_float("PIPELINE_FULL_EXECUTION_SCORE", FULL_EXECUTION_SCORE),
        get_env_float("PIPELINE_STANDARD_EXECUTION_SCORE", STANDARD_EXECUTION_SCORE),
        get_env_float("PIPELINE_WATCHLIST_EDGE_EXECUTION_RATIO", WATCHLIST_EDGE_EXECUTION_RATIO),
    )


def _round_down_lot(shares: float, lot_size: int = 100) -> int:
    if shares <= 0:
        return 0
    return int(shares // lot_size) * lot_size


def _quality_execution_multiplier(quality_score: float) -> float:
    clamped = max(0.0, min(1.0, quality_score))
    return 0.85 + (0.30 * clamped)


def _resolve_single_name_limit(*, allow_extended_limit: bool, avg_volume_20d: float) -> float:
    base_limit = 0.12 if allow_extended_limit else 0.10
    if 0.0 < avg_volume_20d <= LOWEST_LIQUIDITY_TIER_MAX_AVG_VOLUME_20D:
        return min(base_limit, LOWEST_LIQUIDITY_TIER_SINGLE_NAME_LIMIT)
    return base_limit


def _compute_beta(portfolio_returns: list[float], benchmark_returns: list[float]) -> float | None:
    """Compute portfolio beta against a benchmark.

    **Precondition**: both lists must be aligned by date (same trading
    days in the same order). If lengths differ, a warning is emitted
    and only the overlapping prefix is used (ALPHA-007 / GAMMA-005).

    This is an intentional near-duplicate of
    :func:`src.backtesting.metrics.compute_beta` — they are kept as
    separate implementations to avoid a circular import between
    ``src.portfolio`` and ``src.backtesting`` (engine → execution →
    position_calculator → metrics → ...). If a third caller ever needs
    beta, extract to a leaf module.
    """
    import warnings

    import numpy as np

    if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
        return None
    n = min(len(portfolio_returns), len(benchmark_returns))
    if len(portfolio_returns) != len(benchmark_returns):
        warnings.warn(
            f"_compute_beta: portfolio_returns ({len(portfolio_returns)}) and "
            f"benchmark_returns ({len(benchmark_returns)}) differ in length. "
            f"Using first {n} — may be wrong if not date-aligned (ALPHA-007).",
            stacklevel=2,
        )
    portfolio_array = np.array(portfolio_returns[:n])
    benchmark_array = np.array(benchmark_returns[:n])
    benchmark_variance = np.var(benchmark_array, ddof=1)
    if benchmark_variance < 1e-12:
        return None
    covariance = np.cov(portfolio_array, benchmark_array)[0][1]
    return float(covariance / benchmark_variance)


def calculate_position(
    ticker: str,
    current_price: float,
    score_final: float,
    portfolio_nav: float,
    available_cash: float,
    avg_volume_20d: float,
    industry_remaining_quota: float,
    quality_score: float = 0.5,
    correlation_adjustment: float = 1.0,
    vol_adjusted_ratio: float = 0.10,
    existing_position_ratio: float = 0.0,
    allow_extended_limit: bool = False,
    watchlist_min_score_override: float | None = None,
    watchlist_edge_execution_ratio_override: float | None = None,
) -> PositionPlan:
    watchlist_min_score, full_execution_score, standard_execution_score, watchlist_edge_execution_ratio = _get_execution_thresholds()
    if watchlist_min_score_override is not None:
        watchlist_min_score = float(watchlist_min_score_override)
    if watchlist_edge_execution_ratio_override is not None:
        watchlist_edge_execution_ratio = float(watchlist_edge_execution_ratio_override)

    if current_price <= 0 or portfolio_nav <= 0 or score_final < watchlist_min_score:
        return PositionPlan(ticker=ticker, shares=0, amount=0.0, constraint_binding="score", score_final=score_final, execution_ratio=0.0, quality_score=quality_score)

    min_lot_amount = current_price * A_SHARE_MIN_LOT
    single_name_limit = _resolve_single_name_limit(
        allow_extended_limit=allow_extended_limit,
        avg_volume_20d=float(avg_volume_20d or 0.0),
    )
    min_lot_override_ratio = MIN_LOT_OVERRIDE_MAX_RATIO
    if single_name_limit <= LOWEST_LIQUIDITY_TIER_SINGLE_NAME_LIMIT:
        min_lot_override_ratio = min(min_lot_override_ratio, single_name_limit)
    allow_min_lot_override = existing_position_ratio <= 0 and min_lot_amount <= portfolio_nav * min_lot_override_ratio
    remaining_single_name_amount = max((single_name_limit - existing_position_ratio) * portfolio_nav, 0.0)
    if allow_min_lot_override:
        remaining_single_name_amount = max(remaining_single_name_amount, min_lot_amount)
    vol_limit = portfolio_nav * vol_adjusted_ratio * max(correlation_adjustment, 0.0)
    if allow_min_lot_override:
        vol_limit = max(vol_limit, min_lot_amount)
    cash_limit = available_cash
    # CandidatePool stores avg_volume_20d in wan-CNY from Tushare amount fields.
    safe_avg_volume_20d = float(avg_volume_20d or 0.0)
    liq_limit = safe_avg_volume_20d * AVG_VOLUME_20D_AMOUNT_UNIT * 0.02
    industry_limit = industry_remaining_quota

    constraints = {
        "single_name": remaining_single_name_amount,
        "vol": vol_limit,
        "cash": cash_limit,
        "liquidity": liq_limit,
        "industry": industry_limit,
    }
    binding_constraint, allowed_amount = min(constraints.items(), key=lambda item: item[1])
    base_shares = _round_down_lot(allowed_amount / current_price)

    if score_final > full_execution_score:
        execution_ratio = 1.0
    elif score_final >= standard_execution_score:
        execution_ratio = 0.6
    elif score_final >= watchlist_min_score:
        execution_ratio = watchlist_edge_execution_ratio
    else:
        execution_ratio = 0.0

    execution_ratio = min(1.0, execution_ratio * _quality_execution_multiplier(quality_score))

    final_shares = _round_down_lot(base_shares * execution_ratio)
    if final_shares == 0 and execution_ratio > 0 and base_shares >= A_SHARE_MIN_LOT:
        final_shares = A_SHARE_MIN_LOT
    amount = round(final_shares * current_price, 4)
    return PositionPlan(
        ticker=ticker,
        shares=final_shares,
        amount=amount,
        constraint_binding=binding_constraint,
        score_final=score_final,
        execution_ratio=execution_ratio,
        quality_score=max(0.0, min(1.0, quality_score)),
        daily_limit_priority=score_final,
    )


def enforce_daily_trade_limit(plans: list[PositionPlan], portfolio_nav: float, limit_ratio: float = 0.20, max_new_positions: int = 3) -> list[PositionPlan]:
    allowed_amount = portfolio_nav * limit_ratio
    selected: list[PositionPlan] = []
    consumed = 0.0
    for plan in sorted(
        plans,
        key=lambda item: (
            float(getattr(item, "daily_limit_priority", item.score_final) or 0.0),
            item.score_final,
            item.quality_score,
        ),
        reverse=True,
    ):
        if len(selected) >= max_new_positions:
            break
        if consumed + plan.amount > allowed_amount:
            continue
        selected.append(plan)
        consumed += plan.amount
    return selected


# REF-001: ``evaluate_portfolio_risk_guardrails`` was deleted as dead code
# in 2026-06-08. The function computed HHI / CVaR / beta risk alerts and
# returned ``block_buy``/``prefer_low_beta`` flags, but had zero production
# call sites (only 4 unit tests exercised it). The product doc references
# "风险护栏" as a design concept but does NOT advertise this specific
# function as an enforced check. If/when the gating is wired into the
# buy-order prep path, the function should be re-introduced at that
# boundary, not resurrected here. See docs/bugs/2026-06-05 for the
# historical triage.

