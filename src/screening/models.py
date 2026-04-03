"""筛选层数据模型 — Layer A 候选池 + Layer B 策略信号 + 市场状态"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CandidateStock(BaseModel):
    """Layer A 候选池标的"""
    ticker: str
    name: str
    industry_sw: str = ""
    market_cap: float = 0.0
    avg_volume_20d: float = 0.0
    listing_date: str = ""
    disclosure_risk: bool = False
    candidate_pool_rank: int = 0
    candidate_pool_lane: str = ""
    candidate_pool_shadow_reason: str = ""
    candidate_pool_avg_amount_share_of_cutoff: float = 0.0
    candidate_pool_avg_amount_share_of_min_gate: float = 0.0


class MarketStateType(str, Enum):
    """市场状态类型（§3.2 + §6.1）"""
    TREND = "trend"
    RANGE = "range"
    MIXED = "mixed"
    CRISIS = "crisis"


class SubFactor(BaseModel):
    """单个子因子"""
    name: str
    direction: int = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=1, default=1.0)
    weight: float = Field(ge=0, le=1, default=0.2)
    metrics: dict = Field(default_factory=dict)


class StrategySignal(BaseModel):
    """单策略标准三元组（§2 子因子聚合规则）"""
    direction: int = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=1)
    sub_factors: dict = Field(default_factory=dict)


class MarketState(BaseModel):
    """市场状态检测结果（§3.2 五项指标）"""
    state_type: MarketStateType = MarketStateType.MIXED
    adx: float = 0.0
    atr_price_ratio: float = 0.0
    breadth_ratio: float = 0.5
    limit_up_count: int = 0
    limit_down_count: int = 0
    limit_up_down_ratio: float = 0.0
    total_volume: float = 0.0
    northbound_flow_days: int = 0
    is_low_volume: bool = False
    position_scale: float = Field(ge=0, le=1, default=1.0)
    adjusted_weights: dict[str, float] = Field(default_factory=lambda: {
        "trend": 0.30,
        "mean_reversion": 0.20,
        "fundamental": 0.30,
        "event_sentiment": 0.20,
    })


DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "trend": 0.30,
    "mean_reversion": 0.20,
    "fundamental": 0.30,
    "event_sentiment": 0.20,
}


class FusedScore(BaseModel):
    """单标的 Layer B 融合得分（§3.1 融合公式 + §3.4 决策阈值）"""
    ticker: str
    score_b: float = Field(ge=-1, le=1)
    strategy_signals: dict[str, StrategySignal] = Field(default_factory=dict)
    arbitration_applied: list[str] = Field(default_factory=list)
    market_state: Optional[MarketState] = None
    weights_used: dict[str, float] = Field(default_factory=dict)
    decision: str = "neutral"

    @staticmethod
    def classify_decision(score: float) -> str:
        if score > 0.50:
            return "strong_buy"
        elif score >= 0.35:
            return "watch"
        elif score >= -0.20:
            return "neutral"
        elif score >= -0.50:
            return "sell"
        else:
            return "strong_sell"


class ArbitrationAction(str, Enum):
    """冲突仲裁动作"""
    AVOID = "avoid"
    SHORT_HOLD = "short_hold"
    LONG_HOLD = "long_hold"
    RISK_OFF = "risk_off"
    TRUST_TREND = "trust_trend"
    TRUST_REVERSION = "trust_reversion"
    BOTH_DEMOTE = "both_demote"
    CONSENSUS_BONUS = "consensus_bonus"
    NONE = "none"
