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
    adjusted_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "trend": 0.30,
            "mean_reversion": 0.20,
            "fundamental": 0.30,
            "event_sentiment": 0.20,
        }
    )
    # P2-9: 宏观环境标签 (可选 — fetch_macro_snapshot 失败时为 None)
    macro_context: dict | None = None


DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "trend": 0.40,
    "mean_reversion": 0.20,
    "fundamental": 0.15,
    "event_sentiment": 0.05,
}


#: 策略方向乘数 — 默认全部正向 (1.0).
#:
#: 历史: 2026-06-25 曾基于推荐池 (n=472) 诊断将 mean_reversion 设为 -1.0 (反向),
#: 但随后全 universe 回测 (n=8136, 470 票 × 20 日期, 零 LLM 纯技术指标) 推翻了
#: 该结论: 在全市场下 MR 是**正向有效因子** (IC=+0.040, p=0.0003, bullish mean
#: +6.86% vs bearish +3.32%, bull-bear 差 +3.54%). 推荐池的反向现象是**选择偏差**
#: (池子预筛选强势股, 把能反弹的超跌票过滤掉了), 不是 MR 因子本身的问题.
#:
#: NS-4 (commit 023acd74, autodev C225 n=1193/sub-factor, sep=-2.58%, IC=-0.128)
#: 进一步发现 4 个 MR sub-factor 信号相对 T+1 系统性反向 — 短期 momentum 主导,
#: 超卖票继续跌. NS-4 在 signal generators (technicals.py +
#: strategy_scorer_mean_reversion.py) 内翻转 bullish/bearish 标签使信号方向
#: 对齐 T+1; multiplier 保持 1.0 (信号已对齐, 无需再反转).
#:
#: 教训: 因子诊断必须用全 universe (无选择偏差), 不能只看推荐池; 信号方向修复
#: 应在 generator 层 (语义对齐) 而非 multiplier 层 (盲反转). 参见 NS-4 keystone
#: (commit 023acd74) 与 mean-reversion-reversed-20260625 memory 修正记录.
STRATEGY_DIRECTION_MULTIPLIER: dict[str, float] = {
    "trend": 1.0,
    "mean_reversion": 1.0,  # NS-4 generator 层已对齐 T+1, multiplier 保持 1.0
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
