from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradingConstraints:
    commission_rate: float = 0.00025
    stamp_duty_rate: float = 0.001
    base_slippage_rate: float = 0.0015
    low_liquidity_slippage_rate: float = 0.003
    low_liquidity_turnover_threshold: float = 50_000_000.0


@dataclass(frozen=True)
class TradeExecutionInputs:
    daily_turnover: float | None = None
    liquidity_capacity_raw_100: float | None = None
    crowding_risk_raw_100: float | None = None
    gap_risk_raw_100: float | None = None
    projected_theme_exposure: float | None = None
    incremental_theme_exposure: float | None = None


@dataclass(frozen=True)
class ResolvedTradeConstraints:
    constraints: TradingConstraints
    constraint_bucket: str
    capacity_penalty_ratio: float
    diagnostics: dict[str, float | str | None]


def resolve_trade_constraints(base: TradingConstraints, inputs: TradeExecutionInputs | None) -> ResolvedTradeConstraints:
    payload = inputs or TradeExecutionInputs()
    slippage = base.base_slippage_rate
    capacity_penalty_ratio = 0.0
    constraint_bucket = "baseline"

    if payload.daily_turnover is not None and payload.daily_turnover < base.low_liquidity_turnover_threshold:
        slippage = max(slippage, base.low_liquidity_slippage_rate)
        constraint_bucket = "tightened"
    if payload.liquidity_capacity_raw_100 is not None and payload.liquidity_capacity_raw_100 < 50.0:
        slippage += 0.001
        capacity_penalty_ratio += 0.15
        constraint_bucket = "tightened"
    if payload.crowding_risk_raw_100 is not None and payload.crowding_risk_raw_100 >= 70.0:
        slippage += 0.0005
        capacity_penalty_ratio += 0.10
        constraint_bucket = "tightened"
    if payload.gap_risk_raw_100 is not None and payload.gap_risk_raw_100 >= 60.0:
        slippage += 0.0005
        constraint_bucket = "tightened"

    resolved = TradingConstraints(
        commission_rate=base.commission_rate,
        stamp_duty_rate=base.stamp_duty_rate,
        base_slippage_rate=round(slippage, 6),
        low_liquidity_slippage_rate=max(base.low_liquidity_slippage_rate, round(slippage, 6)),
        low_liquidity_turnover_threshold=base.low_liquidity_turnover_threshold,
    )
    capped_capacity_penalty_ratio = round(min(capacity_penalty_ratio, 0.35), 4)
    return ResolvedTradeConstraints(
        constraints=resolved,
        constraint_bucket=constraint_bucket,
        capacity_penalty_ratio=capped_capacity_penalty_ratio,
        diagnostics={
            "constraint_bucket": constraint_bucket,
            "resolved_slippage_rate": resolved.base_slippage_rate,
            "capacity_penalty_ratio": capped_capacity_penalty_ratio,
            "daily_turnover": payload.daily_turnover,
            "liquidity_capacity_raw_100": payload.liquidity_capacity_raw_100,
            "crowding_risk_raw_100": payload.crowding_risk_raw_100,
            "gap_risk_raw_100": payload.gap_risk_raw_100,
            "projected_theme_exposure": payload.projected_theme_exposure,
            "incremental_theme_exposure": payload.incremental_theme_exposure,
        },
    )
