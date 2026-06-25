"""筛选层数据模型 — Layer A 候选池 + Layer B 策略信号 + 市场状态"""

from enum import StrEnum

from pydantic import BaseModel, Field


class CandidateStock(BaseModel):
    """Layer A 候选池标的"""
    ticker: str
    name: str
    industry_sw: str = ""
    # R117 / NaN 防御: ge=0 与 StrategySignal 一致, 让 Pydantic 在模型层拒绝 NaN/负值。
    # build_candidate_stocks 用 mv_map.get(ts_code,0.0)/10000.0 与 amount_map.get(ts_code,0.0)
    # 填充, .get 只挡 missing key, 不挡已有 key 的 NaN —— tushare/pandas 脏 NaN 会流入 model
    # 再进 _candidate_liquidity_sort_key / _technical_stage_ranking_key 的 sort tuple, 让
    # sorted() 比较非确定性, 候选池排序跨 run 不可复现。ge=0 把脏值挡在排序前。
    market_cap: float = Field(0.0, ge=0)
    avg_volume_20d: float = Field(0.0, ge=0)
    listing_date: str = ""
    disclosure_risk: bool = False
    candidate_pool_rank: int = 0
    candidate_pool_lane: str = ""
    candidate_pool_shadow_reason: str = ""
    candidate_pool_avg_amount_share_of_cutoff: float = 0.0
    candidate_pool_avg_amount_share_of_min_gate: float = 0.0
    shadow_focus_selected: bool = False
    shadow_focus_relaxed_band: bool = False
    shadow_visibility_gap_selected: bool = False
    shadow_visibility_gap_relaxed_band: bool = False
    source_layer_release_stage: str = ""
    source_layer_release_reason: str = ""


class MarketStateType(StrEnum):
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
    daily_return: float = 0.0
    limit_up_count: int = 0
    limit_down_count: int = 0
    limit_up_down_ratio: float = 0.0
    total_volume: float = 0.0
    northbound_flow_days: int = 0
    is_low_volume: bool = False
    style_dispersion: float = 0.0
    regime_flip_risk: float = 0.0
    regime_gate_level: str = "normal"
    regime_gate_reasons: list[str] = Field(default_factory=list)
    btst_kill_switch_metrics: dict[str, float] = Field(default_factory=dict)
    position_scale: float = Field(ge=0, le=1, default=1.0)
    adjusted_weights: dict[str, float] = Field(default_factory=lambda: {
        "trend": 0.30,
        "mean_reversion": 0.20,
        "fundamental": 0.30,
        "event_sentiment": 0.20,
    })
    # P2-9: 宏观环境标签 (可选 — fetch_macro_snapshot 失败时为 None)
    macro_context: dict | None = None


DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "trend": 0.30,
    "mean_reversion": 0.20,
    "fundamental": 0.30,
    "event_sentiment": 0.20,
}


#: 策略方向乘数 — A 股市场特性修正 (诊断 2026-06-25, n=472 真实回测).
#:
#: ``mean_reversion`` 在 A 股是**反向指标**: 因子诊断 (493 条 tracking_history ×
#: 32 auto_screening 报告) 证明 MR bullish (超跌) 的票 mean -3.52%, MR bearish
#: (超涨) 的票 mean +5.10%, bull-bear 差 -8.62% (2025+2026 两时段稳定).
#: 原因: A 股是动量市场, 超跌的票往往有基本面问题继续跌, 超涨的票有资金推动
#: 继续涨. MR 因子的均值回归假设在 A 股不成立.
#:
#: 反转后 (multiplier=-1): MR bullish 拉低 score, MR bearish 拉高 score —
#: 让 score 从反向 (IC=-0.124) 变成弱正向 (IC=+0.033), crisis regime 下 IC=+0.056.
STRATEGY_DIRECTION_MULTIPLIER: dict[str, float] = {
    "trend": 1.0,
    "mean_reversion": -1.0,  # A 股动量市场: MR 信号反向贡献
    "fundamental": 1.0,
    "event_sentiment": 1.0,
}


class FusedScore(BaseModel):
    """单标的 Layer B 融合得分（§3.1 融合公式 + §3.4 决策阈值）"""
    ticker: str
    name: str = ""
    industry_sw: str = ""
    score_b: float = Field(ge=-1, le=1)
    strategy_signals: dict[str, StrategySignal] = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    arbitration_applied: list[str] = Field(default_factory=list)
    market_state: MarketState | None = None
    weights_used: dict[str, float] = Field(default_factory=dict)
    decision: str = "neutral"
    theme_name: str = ""
    theme_category: str = ""
    is_new_theme: bool = False

    @staticmethod
    def classify_decision(score: float) -> str:
        if score > 0.50:
            return "strong_buy"
        if score >= 0.35:
            return "watch"
        if score >= -0.20:
            return "neutral"
        if score >= -0.50:
            return "sell"
        return "strong_sell"


class ArbitrationAction(StrEnum):
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
