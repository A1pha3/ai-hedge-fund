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

    # BETA (R20.32): reject NaN / Inf score_final up-front. NaN comparisons
    # always return False in Python, so a NaN score would pass the
    # ``score_final < watchlist_min_score`` gate and then fall through to
    # the ``elif score_final >= standard_execution_score`` / watchlist_edge
    # branch (also False), ultimately defaulting to ``execution_ratio = 0.0``
    # at line 156. The bigger problem: NaN poisons every downstream numeric
    # computation (base_shares, final_shares, amount) silently, producing
    # garbage PositionPlan objects. Reject non-finite scores before any math.
    if not math.isfinite(float(score_final)):
        return PositionPlan(ticker=ticker, shares=0, amount=0.0, constraint_binding="score", score_final=float(score_final), execution_ratio=0.0, quality_score=quality_score)

    if current_price <= 0 or portfolio_nav <= 0 or score_final < watchlist_min_score:
        return PositionPlan(ticker=ticker, shares=0, amount=0.0, constraint_binding="score", score_final=score_final, execution_ratio=0.0, quality_score=quality_score)

    # NS-13 sibling: reject NaN/Inf current_price. ``current_price <= 0`` is False
    # for NaN (NaN comparisons are False), so a halted/suspended A-share with NaN
    # price passed the guard and poisoned base_shares/amount math. portfolio_nav
    # is already covered by ``<= 0`` only if finite; guard both explicitly.
    if not math.isfinite(float(current_price)) or not math.isfinite(float(portfolio_nav)):
        return PositionPlan(ticker=ticker, shares=0, amount=0.0, constraint_binding="price", score_final=score_final, execution_ratio=0.0, quality_score=quality_score)

    # GAMMA-009 / R20.26-B BETA-006: sanitize ``avg_volume_20d`` ONCE at the
    # top. ``float(NaN or 0.0)`` yields NaN (NaN is truthy in Python), so the
    # previous code passed NaN to ``_resolve_single_name_limit`` and again to
    # ``liq_limit``. Sanitize once and reuse for both the single-name cap and
    # the liquidity cap so the two paths agree.
    safe_avg_volume_20d = float(avg_volume_20d or 0.0)
    if not math.isfinite(safe_avg_volume_20d):
        safe_avg_volume_20d = 0.0

    # R146 (BETA-006 same-class drain): sanitize ``existing_position_ratio`` and
    # ``correlation_adjustment``. A held ticker whose current_price is NaN
    # (halted/suspended A-share) yields NaN existing_position_ratio at the call
    # site; NaN is truthy and wins the constraints ``min()`` as the first key
    # ('single_name') → ``int(NaN // 100)`` → ValueError crashing the WHOLE day's
    # buy pipeline. NaN correlation_adjustment makes vol_limit=NaN; as the 2nd key
    # it's skipped by min() (single_name finite), silently bypassing the vol cap
    # → up to 2x over-allocation. Treat non-finite conservatively: existing → at
    # cap (block adding when unvaluable); correlation → 0 (block when unknown).
    existing_position_ratio = float(existing_position_ratio or 0.0)
    if not math.isfinite(existing_position_ratio):
        existing_position_ratio = 1.0
    correlation_adjustment = float(correlation_adjustment or 0.0)
    if not math.isfinite(correlation_adjustment):
        correlation_adjustment = 0.0

    min_lot_amount = current_price * A_SHARE_MIN_LOT
    single_name_limit = _resolve_single_name_limit(
        allow_extended_limit=allow_extended_limit,
        avg_volume_20d=safe_avg_volume_20d,
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
        # GAMMA-008: skip zero-amount plans (no meaningful position to add)
        if plan.amount <= 0:
            continue
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
