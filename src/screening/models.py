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


# ---------------------------------------------------------------------------
# 策略权重 — 唯一权威源
# ---------------------------------------------------------------------------
# 所有下游 (MarketState.adjusted_weights 默认值 / custom_weights.DEFAULT_WEIGHTS /
# signal_fusion 归一化 / web slider) 都从这里派生, 禁止在别处重复硬编码.
# 融合层与所有默认权重消费者都必须从此处派生，避免行为口径漂移。

DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    # 2026-08-11/12 的降权研究重建因 universe、exit、公司行动与 event
    # 时点泄漏不匹配被拒绝；生产默认恢复到该研究变更前的最后接受语义。
    "trend": 0.40,
    "mean_reversion": 0.20,
    "fundamental": 0.15,
    "event_sentiment": 0.05,
}


def _default_adjusted_weights() -> dict[str, float]:
    """MarketState.adjusted_weights 的延迟派生默认值.

    返回 DEFAULT_STRATEGY_WEIGHTS 的副本, 保证 MarketState 默认值永远与权威源一致,
    消除重复硬编码导致的 stale 风险 (此前曾 stale 过 0.30/0.20/0.30/0.20).
    """
    return dict(DEFAULT_STRATEGY_WEIGHTS)


#: 当前启用的策略集合 (weight>0). 此集合不是额外开关，只是
#: DEFAULT_STRATEGY_WEIGHTS 的派生诊断视图。
ENABLED_STRATEGIES: frozenset[str] = frozenset(
    name for name, weight in DEFAULT_STRATEGY_WEIGHTS.items() if weight > 0.0
)


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
        # 从 DEFAULT_STRATEGY_WEIGHTS 派生 (2026-08-12): 此前是重复硬编码,
        # 每次改权重都要手动同步, 曾 stale 过 (0.30/0.20/0.30/0.20 vs 0.15/0.05).
        # 现在通过 _default_adjusted_weights() 延迟引用, 自动与权威源对齐.
        # 生产路径 (detect_market_state) 显式传 adjusted_weights, 此默认仅测试/退化兜底.
        default_factory=_default_adjusted_weights,
    )
    # P2-9: 宏观环境标签 (可选 — fetch_macro_snapshot 失败时为 None)
    macro_context: dict | None = None


# 历史注记 (2026-08-12): 此处原有一个 STRATEGY_DIRECTION_MULTIPLIER dict
# (4 个策略全 1.0). 它的语义曾是"在融合层翻转信号方向", 但历史证明这层抽象
# 是错误的 — 2026-06-25 曾据推荐池样本把 MR 设 -1.0, 全 universe 回测推翻;
# NS-4 (commit 023acd74) 最终在 generator 层 (语义对齐) 修复了方向, multiplier
# 全 1.0 沦为 no-op 占位符. 一个全 1.0 的乘性系数等价于不存在 — 已删除,
# 连同 signal_fusion.compute_score_b 里的查找. 方向修复的唯一正解在 generator
# 层 (technicals.py + strategy_scorer_mean_reversion.py), 不在融合层.
#
# 教训 (留给未来): 信号方向问题应在 generator 层用语义对齐解决 (bullish/bearish
# 标签的含义), 而非在融合层加一个"方向乘数"做盲反转 — 后者会积累历史债且无
# 人记得为什么是 -1.0. 参见 NS-4 keystone (commit 023acd74).


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


# 决策枚举 → 中文标签 (展示层统一; 未知值原样回退, 不吞新枚举)。
# 覆盖两套历史枚举域: FusedScore.classify_decision (strong_buy/watch/…) 与
# 旧推送/why-not 报告的 buy/hold/bullish/bearish — 冷读清扫 2026-08-16 前
# 这些 surface 直接渲染英文枚举 (watch/AVOID/Score B)。
DECISION_LABELS_ZH: dict[str, str] = {
    "strong_buy": "强烈买入",
    "buy": "买入",
    "watch": "关注",
    "bullish": "看多",
    "neutral": "观望",
    "hold": "持有",
    "sell": "卖出",
    "bearish": "看空",
    "strong_sell": "强烈卖出",
}


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
