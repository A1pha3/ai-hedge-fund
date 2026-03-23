"""增强仓位计算器。"""

from __future__ import annotations

import os

from src.portfolio.models import PositionPlan


WATCHLIST_MIN_SCORE = 0.225
FULL_EXECUTION_SCORE = 0.50
STANDARD_EXECUTION_SCORE = 0.25
WATCHLIST_EDGE_EXECUTION_RATIO = 0.3
AVG_VOLUME_20D_AMOUNT_UNIT = 10_000.0
A_SHARE_MIN_LOT = 100
MIN_LOT_OVERRIDE_MAX_RATIO = 0.15


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _get_execution_thresholds() -> tuple[float, float, float, float]:
    return (
        _get_env_float("PIPELINE_WATCHLIST_MIN_SCORE", WATCHLIST_MIN_SCORE),
        _get_env_float("PIPELINE_FULL_EXECUTION_SCORE", FULL_EXECUTION_SCORE),
        _get_env_float("PIPELINE_STANDARD_EXECUTION_SCORE", STANDARD_EXECUTION_SCORE),
        _get_env_float("PIPELINE_WATCHLIST_EDGE_EXECUTION_RATIO", WATCHLIST_EDGE_EXECUTION_RATIO),
    )


def _round_down_lot(shares: float, lot_size: int = 100) -> int:
    if shares <= 0:
        return 0
    return int(shares // lot_size) * lot_size


def _quality_execution_multiplier(quality_score: float) -> float:
    clamped = max(0.0, min(1.0, quality_score))
    return 0.85 + (0.30 * clamped)


def _compute_beta(portfolio_returns: list[float], benchmark_returns: list[float]) -> float | None:
    import numpy as np

    if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
        return None
    sample_size = min(len(portfolio_returns), len(benchmark_returns))
    portfolio_array = np.array(portfolio_returns[:sample_size])
    benchmark_array = np.array(benchmark_returns[:sample_size])
    benchmark_variance = np.var(benchmark_array)
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
) -> PositionPlan:
    watchlist_min_score, full_execution_score, standard_execution_score, watchlist_edge_execution_ratio = _get_execution_thresholds()

    if current_price <= 0 or portfolio_nav <= 0 or score_final < watchlist_min_score:
        return PositionPlan(ticker=ticker, shares=0, amount=0.0, constraint_binding="score", score_final=score_final, execution_ratio=0.0, quality_score=quality_score)

    min_lot_amount = current_price * A_SHARE_MIN_LOT
    allow_min_lot_override = existing_position_ratio <= 0 and min_lot_amount <= portfolio_nav * MIN_LOT_OVERRIDE_MAX_RATIO
    single_name_limit = 0.12 if allow_extended_limit else 0.10
    remaining_single_name_amount = max((single_name_limit - existing_position_ratio) * portfolio_nav, 0.0)
    if allow_min_lot_override:
        remaining_single_name_amount = max(remaining_single_name_amount, min_lot_amount)
    vol_limit = portfolio_nav * vol_adjusted_ratio * max(correlation_adjustment, 0.0)
    if allow_min_lot_override:
        vol_limit = max(vol_limit, min_lot_amount)
    cash_limit = available_cash
    # CandidatePool stores avg_volume_20d in wan-CNY from Tushare amount fields.
    liq_limit = avg_volume_20d * AVG_VOLUME_20D_AMOUNT_UNIT * 0.02
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
    )


def enforce_daily_trade_limit(plans: list[PositionPlan], portfolio_nav: float, limit_ratio: float = 0.20, max_new_positions: int = 3) -> list[PositionPlan]:
    allowed_amount = portfolio_nav * limit_ratio
    selected: list[PositionPlan] = []
    consumed = 0.0
    for plan in sorted(plans, key=lambda item: (item.score_final, item.quality_score), reverse=True):
        if len(selected) >= max_new_positions:
            break
        if consumed + plan.amount > allowed_amount:
            continue
        selected.append(plan)
        consumed += plan.amount
    return selected


def evaluate_portfolio_risk_guardrails(
    industry_hhi: float,
    candidate_industry_weight: float,
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    candidate_beta: float,
    candidate_is_high_vol: bool,
) -> dict:
    cvar_95 = 0.0
    if portfolio_returns:
        sorted_returns = sorted(portfolio_returns)
        tail_size = max(1, int(len(sorted_returns) * 0.05))
        cvar_95 = sum(sorted_returns[:tail_size]) / tail_size
    portfolio_beta = _compute_beta(portfolio_returns, benchmark_returns)

    alerts: list[str] = []
    block_buy = False
    prefer_low_beta = False
    if abs(cvar_95) > 0.03 and candidate_is_high_vol:
        alerts.append("cvar_warning")
        block_buy = True
    if portfolio_beta is not None and portfolio_beta > 1.3 and candidate_beta > 1.0:
        alerts.append("beta_rebalance")
        prefer_low_beta = True
    if industry_hhi > 0.15 and candidate_industry_weight >= 0.25:
        alerts.append("hhi_block")
        block_buy = True

    return {
        "alerts": alerts,
        "block_buy": block_buy,
        "prefer_low_beta": prefer_low_beta,
        "cvar_95": cvar_95,
        "portfolio_beta": portfolio_beta,
    }

