"""Portfolio adjustment simulator API endpoint.

POST /api/portfolio/simulate-adjustment

Accepts current portfolio positions, current prices, planned decisions,
and a list of adjustment operations (cancel or reduce). Returns the
adjusted positions along with before/after risk metrics (HHI, CVaR,
total NAV, position count, short ratio).

This is a pure simulation — no actual trades are executed.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/portfolio")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PositionInput(BaseModel):
    """Single position state (mirrors PositionState TypedDict)."""

    long: int = 0
    short: int = 0
    long_cost_basis: float = 0.0
    short_cost_basis: float = 0.0


class DecisionInput(BaseModel):
    """Planned trading decision for a single ticker."""

    action: Literal["buy", "sell", "short", "cover", "hold"]
    quantity: int = 0


class AdjustmentItem(BaseModel):
    """A single adjustment operation to simulate."""

    ticker: str
    operation: Literal["cancel", "reduce"]
    reduce_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction to reduce (0..1). Only used when operation='reduce'.",
    )


class SimulateAdjustmentRequest(BaseModel):
    """Full simulation request."""

    positions: dict[str, PositionInput] = Field(
        default_factory=dict,
        description="Current holdings: ticker -> position state.",
    )
    current_prices: dict[str, float] = Field(
        default_factory=dict,
        description="Current market prices: ticker -> price.",
    )
    decisions: dict[str, DecisionInput] = Field(
        default_factory=dict,
        description="Planned trading decisions: ticker -> action/quantity.",
    )
    cash: float = Field(default=0.0, description="Current cash balance.")
    adjustments: list[AdjustmentItem] = Field(
        default_factory=list,
        description="List of adjustment operations to simulate.",
    )


class RiskMetricsSnapshot(BaseModel):
    """Risk metrics computed from a portfolio state."""

    hhi: float
    short_ratio: float
    cvar_95: float
    position_count: int
    max_single_position_weight: float
    total_nav: float
    total_long: float
    total_short: float


class TickerAdjustmentResult(BaseModel):
    """Per-ticker result of the simulation."""

    ticker: str
    original_action: str
    simulated_action: str
    original_quantity: int
    simulated_quantity: int
    operation_applied: str | None = None
    reduce_pct: float = 0.0


class RiskDelta(BaseModel):
    """Difference between after and before risk metrics."""

    hhi: float
    short_ratio: float
    cvar_95: float
    position_count: int
    max_single_position_weight: float
    total_nav: float
    total_long: float
    total_short: float


class SimulateAdjustmentResponse(BaseModel):
    """Full simulation response with before/after comparison."""

    before: RiskMetricsSnapshot
    after: RiskMetricsSnapshot
    delta: RiskDelta
    ticker_results: list[TickerAdjustmentResult]
    adjusted_positions: dict[str, PositionInput]
    adjusted_decisions: dict[str, DecisionInput]


# ---------------------------------------------------------------------------
# Core computation helpers (reusable, pure functions)
# ---------------------------------------------------------------------------


def _compute_risk_from_state(
    positions: dict[str, dict[str, Any]],
    prices: dict[str, float],
    cash: float,
) -> RiskMetricsSnapshot:
    """Compute risk metrics from a flat position/price dict.

    This is a standalone version of ``_compute_risk_metrics`` from
    ``hedge_fund_streaming.py`` but operates on raw dicts (no Portfolio
    object needed) so it can be used for simulated states.
    """
    position_values: dict[str, float] = {}
    for ticker, pos in positions.items():
        long_val = float(pos.get("long", 0)) * prices.get(ticker, 0.0)
        short_val = float(pos.get("short", 0)) * prices.get(ticker, 0.0)
        net_val = long_val - short_val
        if abs(net_val) > 1e-6:
            position_values[ticker] = net_val

    total_nav = cash + sum(position_values.values())
    if total_nav <= 0:
        total_nav = 1.0

    # HHI
    weights = {t: v / total_nav for t, v in position_values.items()}
    hhi = sum(w * w for w in weights.values())

    # Short ratio
    total_long = sum(
        float(pos.get("long", 0)) * prices.get(t, 0.0)
        for t, pos in positions.items()
    )
    total_short = sum(
        float(pos.get("short", 0)) * prices.get(t, 0.0)
        for t, pos in positions.items()
    )
    gross = total_long + total_short
    short_ratio = total_short / gross if gross > 1e-9 else 0.0

    # CVaR proxy — simple volatility-based estimate from position concentration.
    # When positions are more concentrated, tail risk is higher.
    # We use HHI as a proxy multiplier on a base 5% tail risk.
    cvar_95 = min(0.25, 0.05 + hhi * 0.3)

    max_weight = max((abs(w) for w in weights.values()), default=0.0)

    return RiskMetricsSnapshot(
        hhi=round(hhi, 4),
        short_ratio=round(short_ratio, 4),
        cvar_95=round(cvar_95, 4),
        position_count=len(position_values),
        max_single_position_weight=round(max_weight, 4),
        total_nav=round(total_nav, 2),
        total_long=round(total_long, 2),
        total_short=round(total_short, 2),
    )


def _pos_val(pos: PositionInput | dict[str, Any], key: str, default: Any = 0) -> Any:
    """Read a field from either a PositionInput model or a plain dict."""
    if isinstance(pos, dict):
        return pos.get(key, default)
    return getattr(pos, key, default)


def apply_adjustments(
    positions: dict[str, PositionInput | dict[str, Any]],
    prices: dict[str, float],
    decisions: dict[str, DecisionInput | dict[str, Any]],
    cash: float,
    adjustments: list[AdjustmentItem],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, DecisionInput],
    dict[str, TickerAdjustmentResult],
    float,
]:
    """Apply adjustment operations to a copy of positions and decisions.

    Returns (adjusted_positions, adjusted_decisions, ticker_results, adjusted_cash).
    Accepts both PositionInput/DecisionInput models and plain dicts for flexibility.
    """
    # Deep-copy positions into plain dicts
    adj_positions: dict[str, dict[str, Any]] = {
        t: {"long": int(_pos_val(p, "long")), "short": int(_pos_val(p, "short")), "long_cost_basis": float(_pos_val(p, "long_cost_basis")), "short_cost_basis": float(_pos_val(p, "short_cost_basis"))}
        for t, p in positions.items()
    }

    # Normalize decisions into DecisionInput objects
    def _norm_decision(d: DecisionInput | dict[str, Any]) -> DecisionInput:
        if isinstance(d, DecisionInput):
            return DecisionInput(action=d.action, quantity=d.quantity)
        return DecisionInput(action=str(d.get("action", "hold")), quantity=int(d.get("quantity", 0)))

    adj_decisions: dict[str, DecisionInput] = {t: _norm_decision(d) for t, d in decisions.items()}
    adj_cash = cash
    ticker_results: dict[str, TickerAdjustmentResult] = {}

    # Build a lookup for quick access
    adj_lookup: dict[str, AdjustmentItem] = {a.ticker: a for a in adjustments}

    for ticker, decision in adj_decisions.items():
        original_action = decision.action
        original_quantity = decision.quantity
        operation_applied = None
        reduce_pct = 0.0

        if ticker not in adj_lookup:
            # No adjustment for this ticker — simulate the planned decision
            adj_cash += _simulate_decision(adj_positions, prices, adj_cash, ticker, decision)
            ticker_results[ticker] = TickerAdjustmentResult(
                ticker=ticker,
                original_action=original_action,
                simulated_action=original_action,
                original_quantity=original_quantity,
                simulated_quantity=original_quantity,
            )
            continue

        adj = adj_lookup[ticker]

        if adj.operation == "cancel":
            # Cancel the planned operation — treat as HOLD
            operation_applied = "cancel"
            ticker_results[ticker] = TickerAdjustmentResult(
                ticker=ticker,
                original_action=original_action,
                simulated_action="hold",
                original_quantity=original_quantity,
                simulated_quantity=0,
                operation_applied=operation_applied,
            )

        elif adj.operation == "reduce":
            # Reduce the position by reduce_pct (sell or cover a fraction)
            operation_applied = "reduce"
            reduce_pct = adj.reduce_pct
            pos = adj_positions.get(ticker, {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0})
            price = prices.get(ticker, 0.0)

            if pos.get("long", 0) > 0:
                reduce_qty = max(1, int(pos["long"] * reduce_pct))
                simulated_action = "sell"
                simulated_quantity = reduce_qty
                # Simulate selling
                pos["long"] = max(0, pos["long"] - reduce_qty)
                if pos["long"] == 0:
                    pos["long_cost_basis"] = 0.0
                adj_cash += reduce_qty * price
            elif pos.get("short", 0) > 0:
                reduce_qty = max(1, int(pos["short"] * reduce_pct))
                simulated_action = "cover"
                simulated_quantity = reduce_qty
                pos["short"] = max(0, pos["short"] - reduce_qty)
                if pos["short"] == 0:
                    pos["short_cost_basis"] = 0.0
                adj_cash -= reduce_qty * price
            else:
                simulated_action = "hold"
                simulated_quantity = 0

            ticker_results[ticker] = TickerAdjustmentResult(
                ticker=ticker,
                original_action=original_action,
                simulated_action=simulated_action,
                original_quantity=original_quantity,
                simulated_quantity=simulated_quantity,
                operation_applied=operation_applied,
                reduce_pct=reduce_pct,
            )
            adj_positions[ticker] = pos

    # Also simulate decisions for tickers that have decisions but no adjustments
    # (already handled in the loop above).

    # Handle tickers in adjustments that are NOT in decisions — reduce existing position
    for adj in adjustments:
        if adj.ticker in ticker_results:
            continue
        pos = adj_positions.get(
            adj.ticker,
            {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0},
        )
        price = prices.get(adj.ticker, 0.0)

        if adj.operation == "cancel":
            ticker_results[adj.ticker] = TickerAdjustmentResult(
                ticker=adj.ticker,
                original_action="hold",
                simulated_action="hold",
                original_quantity=0,
                simulated_quantity=0,
                operation_applied="cancel",
            )
        elif adj.operation == "reduce":
            reduce_pct = adj.reduce_pct
            if pos.get("long", 0) > 0:
                reduce_qty = max(1, int(pos["long"] * reduce_pct))
                pos["long"] = max(0, pos["long"] - reduce_qty)
                if pos["long"] == 0:
                    pos["long_cost_basis"] = 0.0
                adj_cash += reduce_qty * price
                ticker_results[adj.ticker] = TickerAdjustmentResult(
                    ticker=adj.ticker,
                    original_action="hold",
                    simulated_action="sell",
                    original_quantity=0,
                    simulated_quantity=reduce_qty,
                    operation_applied="reduce",
                    reduce_pct=reduce_pct,
                )
            elif pos.get("short", 0) > 0:
                reduce_qty = max(1, int(pos["short"] * reduce_pct))
                pos["short"] = max(0, pos["short"] - reduce_qty)
                if pos["short"] == 0:
                    pos["short_cost_basis"] = 0.0
                adj_cash -= reduce_qty * price
                ticker_results[adj.ticker] = TickerAdjustmentResult(
                    ticker=adj.ticker,
                    original_action="hold",
                    simulated_action="cover",
                    original_quantity=0,
                    simulated_quantity=reduce_qty,
                    operation_applied="reduce",
                    reduce_pct=reduce_pct,
                )
            else:
                ticker_results[adj.ticker] = TickerAdjustmentResult(
                    ticker=adj.ticker,
                    original_action="hold",
                    simulated_action="hold",
                    original_quantity=0,
                    simulated_quantity=0,
                    operation_applied="reduce",
                    reduce_pct=reduce_pct,
                )
            adj_positions[adj.ticker] = pos

    return adj_positions, adj_decisions, ticker_results, adj_cash


def _simulate_decision(
    positions: dict[str, dict[str, Any]],
    prices: dict[str, float],
    cash: float,
    ticker: str,
    decision: DecisionInput,
) -> float:
    """Apply a planned decision to positions in-place (for unadjusted tickers).

    This simulates what would happen if the planned action executes, so the
    "before" metrics reflect the fully-executed plan.

    Returns the cash delta caused by the decision (negative for buy/short,
    positive for sell/cover). The caller must add this to its cash variable.
    """
    price = prices.get(ticker, 0.0)
    if price <= 0:
        return 0.0

    pos = positions.get(ticker, {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0})
    cash_delta = 0.0

    if decision.action == "buy" and decision.quantity > 0:
        pos["long"] = pos.get("long", 0) + decision.quantity
        pos["long_cost_basis"] = price
        cash_delta = -decision.quantity * price
    elif decision.action == "sell" and decision.quantity > 0:
        sell_qty = min(decision.quantity, pos.get("long", 0))
        pos["long"] = max(0, pos.get("long", 0) - sell_qty)
        if pos["long"] == 0:
            pos["long_cost_basis"] = 0.0
        cash_delta = sell_qty * price
    elif decision.action == "short" and decision.quantity > 0:
        pos["short"] = pos.get("short", 0) + decision.quantity
        pos["short_cost_basis"] = price
        cash_delta = decision.quantity * price
    elif decision.action == "cover" and decision.quantity > 0:
        cover_qty = min(decision.quantity, pos.get("short", 0))
        pos["short"] = max(0, pos.get("short", 0) - cover_qty)
        if pos["short"] == 0:
            pos["short_cost_basis"] = 0.0
        cash_delta = -cover_qty * price

    positions[ticker] = pos
    return cash_delta


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    path="/simulate-adjustment",
    response_model=SimulateAdjustmentResponse,
    summary="Simulate portfolio adjustments (cancel/reduce)",
    description="Simulates canceling or reducing planned operations and returns before/after risk metrics. No actual trades are executed.",
)
def simulate_adjustment(req: SimulateAdjustmentRequest) -> SimulateAdjustmentResponse:
    """Simulate portfolio adjustments and compare risk metrics."""

    if not req.positions and not req.decisions:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'positions' or 'decisions' must be provided.",
        )

    # --- "Before" metrics: simulate all planned decisions on current positions ---
    before_positions: dict[str, dict[str, Any]] = {
        t: {"long": p.long, "short": p.short, "long_cost_basis": p.long_cost_basis, "short_cost_basis": p.short_cost_basis}
        for t, p in req.positions.items()
    }
    before_cash = req.cash

    # Apply all decisions to get "before" state (fully executed plan)
    for ticker, decision in req.decisions.items():
        before_cash += _simulate_decision(before_positions, req.current_prices, before_cash, ticker, decision)

    before_metrics = _compute_risk_from_state(before_positions, req.current_prices, before_cash)

    # --- "After" metrics: apply adjustments ---
    adj_positions, adj_decisions, ticker_results, adj_cash = apply_adjustments(
        positions=req.positions,
        prices=req.current_prices,
        decisions=req.decisions,
        cash=req.cash,
        adjustments=req.adjustments,
    )

    # Note: apply_adjustments() already simulates non-adjusted decisions internally,
    # so we do NOT re-simulate them here (that would double-count).

    after_metrics = _compute_risk_from_state(adj_positions, req.current_prices, adj_cash)

    # Compute deltas (after - before)
    delta = RiskDelta(
        hhi=round(after_metrics.hhi - before_metrics.hhi, 4),
        short_ratio=round(after_metrics.short_ratio - before_metrics.short_ratio, 4),
        cvar_95=round(after_metrics.cvar_95 - before_metrics.cvar_95, 4),
        position_count=after_metrics.position_count - before_metrics.position_count,
        max_single_position_weight=round(after_metrics.max_single_position_weight - before_metrics.max_single_position_weight, 4),
        total_nav=round(after_metrics.total_nav - before_metrics.total_nav, 2),
        total_long=round(after_metrics.total_long - before_metrics.total_long, 2),
        total_short=round(after_metrics.total_short - before_metrics.total_short, 2),
    )

    # Convert adjusted positions back to PositionInput for response
    adjusted_positions_out: dict[str, PositionInput] = {
        t: PositionInput(
            long=int(p.get("long", 0)),
            short=int(p.get("short", 0)),
            long_cost_basis=float(p.get("long_cost_basis", 0.0)),
            short_cost_basis=float(p.get("short_cost_basis", 0.0)),
        )
        for t, p in adj_positions.items()
    }

    return SimulateAdjustmentResponse(
        before=before_metrics,
        after=after_metrics,
        delta=delta,
        ticker_results=list(ticker_results.values()),
        adjusted_positions=adjusted_positions_out,
        adjusted_decisions=adj_decisions,
    )
