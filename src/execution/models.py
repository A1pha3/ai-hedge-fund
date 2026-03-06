"""执行层数据模型 — Layer C 聚合结果 + 执行计划"""

from typing import Optional

from pydantic import BaseModel, Field

from src.portfolio.models import ExitSignal, PositionPlan
from src.screening.models import MarketState, StrategySignal


class LayerCResult(BaseModel):
    """单标的 Layer C 聚合结果（§5.1 Layer C 聚合规则）"""
    ticker: str
    score_c: float = Field(ge=-1, le=1)
    score_final: float = 0.0
    score_b: float = 0.0
    agent_signals: dict[str, StrategySignal] = Field(default_factory=dict)
    bc_conflict: Optional[str] = None
    decision: str = "neutral"


class PendingOrder(BaseModel):
    """待处理订单（涨跌停队列）"""
    ticker: str
    order_type: str  # "buy" or "sell"
    original_score: float = 0.0
    queue_date: str = ""
    queue_days: int = 0
    reason: str = ""


class ExecutionPlan(BaseModel):
    """每日执行计划（§5.1 七步流水线输出）"""
    date: str
    market_state: Optional[MarketState] = None
    strategy_weights: dict[str, float] = Field(default_factory=dict)
    buy_orders: list[PositionPlan] = Field(default_factory=list)
    sell_orders: list[ExitSignal] = Field(default_factory=list)
    pending_buy_queue: list[PendingOrder] = Field(default_factory=list)
    pending_sell_queue: list[PendingOrder] = Field(default_factory=list)
    portfolio_snapshot: dict = Field(default_factory=dict)
    risk_alerts: list[str] = Field(default_factory=list)
    risk_metrics: dict = Field(default_factory=dict)
    layer_a_count: int = 0
    layer_b_count: int = 0
    layer_c_count: int = 0
    watchlist: list[LayerCResult] = Field(default_factory=list)
