from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional, TypedDict

import pandas as pd


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"
    HOLD = "hold"


# Backward-compatible alias
ActionLiteral = Literal["buy", "sell", "short", "cover", "hold"]
BacktestMode = Literal["agent", "pipeline"]


class PositionStateRequired(TypedDict):
    """Represents required per-ticker position state in the portfolio."""

    long: int
    short: int
    long_cost_basis: float
    short_cost_basis: float
    short_margin_used: float


class PositionState(PositionStateRequired, total=False):
    """Represents per-ticker position state plus optional lifecycle metadata."""

    entry_date: str
    last_trade_date: str
    holding_days: int
    max_unrealized_pnl_pct: float
    profit_take_stage: int
    entry_score: float
    quality_score: float
    is_fundamental_driven: bool
    industry_sw: str


class TickerRealizedGains(TypedDict):
    """Realized PnL per side for a single ticker."""

    long: float
    short: float


class PortfolioSnapshot(TypedDict):
    """Snapshot of portfolio state.

    The structure mirrors the existing dict used by the current Backtester
    to ensure drop-in compatibility during incremental refactors.
    """

    cash: float
    margin_used: float
    margin_requirement: float
    positions: Dict[str, PositionState]
    realized_gains: Dict[str, TickerRealizedGains]


# DataFrame alias for clarity in interfaces
PriceDataFrame = pd.DataFrame


class AgentDecision(TypedDict):
    action: ActionLiteral
    quantity: float


AgentDecisions = Dict[str, AgentDecision]


# Analyst signal payloads can vary by agent; keep as loose dicts
AnalystSignal = Dict[str, Any]
AgentSignals = Dict[str, Dict[str, AnalystSignal]]


class AgentOutput(TypedDict):
    decisions: AgentDecisions
    analyst_signals: AgentSignals


# Use functional style to allow keys with spaces to mirror current code
PortfolioValuePoint = TypedDict(
    "PortfolioValuePoint",
    {
        "Date": datetime,
        "Portfolio Value": float,
        "Long Exposure": float,
        "Short Exposure": float,
        "Gross Exposure": float,
        "Net Exposure": float,
        "Long/Short Ratio": float,
    },
    total=False,
)


class PerformanceMetrics(TypedDict, total=False):
    """Performance metrics computed over the equity curve.

    Keys are aligned with the current implementation in src/backtester.py.
    Values are optional to support progressive calculation over time.
    """

    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown: Optional[float]
    max_drawdown_date: Optional[str]
    long_short_ratio: Optional[float]
    gross_exposure: Optional[float]
    net_exposure: Optional[float]
    # Phase 0.3 新增指标
    calmar_ratio: Optional[float]
    profit_loss_ratio: Optional[float]
    annual_turnover: Optional[float]
    cvar_95: Optional[float]
    portfolio_beta: Optional[float]
    win_rate: Optional[float]
    total_trades: Optional[int]
