"""组合层数据模型 — 仓位计划 + 退出信号 + 持仓跟踪"""

from pydantic import BaseModel, Field


class PositionPlan(BaseModel):
    """仓位计划（§4.1 四约束取最小值）"""
    ticker: str
    shares: int = 0
    amount: float = 0.0
    constraint_binding: str = ""
    score_final: float = 0.0
    execution_ratio: float = 0.0
    quality_score: float = Field(ge=0, le=1, default=0.5)


class ExitSignal(BaseModel):
    """退出信号（§4.3 五层退出级联）"""
    ticker: str
    level: str
    trigger_reason: str
    urgency: str = "next_day"
    sell_ratio: float = Field(ge=0, le=1, default=1.0)


class HoldingState(BaseModel):
    """持仓跟踪状态（需持久化至 JSON）"""
    ticker: str
    entry_price: float
    entry_date: str
    shares: int
    cost_basis: float
    industry_sw: str = ""
    max_unrealized_pnl_pct: float = 0.0
    holding_days: int = 0
    profit_take_stage: int = Field(ge=0, le=3, default=0)
    entry_score: float = 0.0
    quality_score: float = Field(ge=0, le=1, default=0.5)
    is_fundamental_driven: bool = False


class IndustryExposure(BaseModel):
    """行业暴露度"""
    industry: str
    market_value: float = 0.0
    weight: float = 0.0
    remaining_quota: float = 0.0


class PortfolioRiskMetrics(BaseModel):
    """组合风险指标"""
    total_nav: float = 0.0
    cash: float = 0.0
    position_count: int = 0
    max_drawdown: float = 0.0
    cvar_95: float = 0.0
    portfolio_beta: float = 0.0
    hhi: float = 0.0
    max_industry_exposure: float = 0.0
