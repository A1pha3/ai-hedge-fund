"""P2-5 自定义策略权重 — 用户调整四策略权重, 重算 score_b 和推荐排序。

高级用户希望自定义四策略 (趋势 / 均值回归 / 基本面 / 事件情绪) 的权重,
Web 端通过滑块调整, 实时看到推荐变化。本模块是纯函数实现, 便于单测。

主入口:
  - :class:`StrategyWeights` — 四策略权重 dataclass (sum-to-1 校验)
  - :func:`reweight_recommendations` — 输入 rec 列表 + 权重, 返回按新 score_b 排序
  - :func:`load_latest_recommendations` (re-export) — 从最新 auto_screening 报告加载
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.screening.models import DEFAULT_STRATEGY_WEIGHTS
from src.utils.numeric import safe_float as _safe_float

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 四策略名称 (内部 strategy key, 与 :data:`src.screening.models.DEFAULT_STRATEGY_WEIGHTS` 对齐)
STRATEGY_KEYS: tuple[str, ...] = (
    "trend",
    "mean_reversion",
    "fundamental",
    "event_sentiment",
)

#: 单策略有符号分数上限 (direction ∈ {-1, 0, +1}, confidence ∈ [0, 100])
MAX_STRATEGY_SCORE: float = 100.0

#: 权重和容差 (允许 1e-6 浮点误差)
WEIGHT_SUM_TOLERANCE: float = 1e-6

#: 默认权重 — 从权威源 :data:`src.screening.models.DEFAULT_STRATEGY_WEIGHTS` 派生 (2026-08-12).
#: 此前是独立的 0.25 等分硬编码, 与权威源不一致,
#: 导致 --auto 生产路径与 web slider 重算用两套互相冲突的"默认"权重. 派生后
#: 权威源改一处, 此处自动同步. sum 可以 < 1.0 (disabled 策略 weight=0 是合法的);
#: StrategyWeights.__post_init__ 已放宽 sum 校验到 sum>0, 归一化在消费时进行.
DEFAULT_WEIGHTS: dict[str, float] = dict(DEFAULT_STRATEGY_WEIGHTS)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class StrategyWeights:
    """四策略权重 — sum-to-1 校验。

    Fields:
        trend: 趋势策略权重
        mean_reversion: 均值回归策略权重
        fundamental: 基本面策略权重
        event_sentiment: 事件情绪策略权重

    Examples:
        >>> w = StrategyWeights()  # 默认从 DEFAULT_STRATEGY_WEIGHTS 派生
        >>> w.to_dict()  # 当前权威源: trend=.40, MR=.20, f=.15, e=.05
        {'trend': 0.4, 'mean_reversion': 0.2, 'fundamental': 0.15, 'event_sentiment': 0.05}
    """

    # 默认值从 DEFAULT_WEIGHTS (= DEFAULT_STRATEGY_WEIGHTS) 派生 (2026-08-12).
    # 此前硬编码 0.25 等分, 与权威源不一致; 现在自动同步.
    trend: float = field(default_factory=lambda: DEFAULT_WEIGHTS["trend"])
    mean_reversion: float = field(default_factory=lambda: DEFAULT_WEIGHTS["mean_reversion"])
    fundamental: float = field(default_factory=lambda: DEFAULT_WEIGHTS["fundamental"])
    event_sentiment: float = field(default_factory=lambda: DEFAULT_WEIGHTS["event_sentiment"])

    def __post_init__(self) -> None:
        # NaN/Inf 防御: 不走 _safe_float (会归零, 绕开检查) — 直接用 math.isfinite 验证
        for key in STRATEGY_KEYS:
            val = getattr(self, key)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(f"权重 {key} 必须为有限数, 当前: {val!r}")
            if not math.isfinite(float(val)):
                raise ValueError(f"权重 {key} 必须为有限数, 当前: {val!r}")
            if val < 0.0:
                raise ValueError(f"权重 {key} 不能为负数, 当前: {val}")
            if val > 1.0:
                raise ValueError(f"权重 {key} 不能超过 1.0, 当前: {val}")
        # 求和校验允许任意正的相对权重和；DEFAULT_STRATEGY_WEIGHTS 未来即使
        # 禁用某个策略也无需凑成 1.0。
        # slider 语义是"指定相对权重", 接受任意正权和, 归一化在消费时 (_normalize_active_weights) 进行.
        # 全 0 仍然非法 (无法归一化, 会污染排序).
        total = self.trend + self.mean_reversion + self.fundamental + self.event_sentiment
        if total <= 0.0:
            raise ValueError(f"权重之和必须 > 0 (全 0 无法归一化), 当前: {total:.9f}")

    def to_dict(self) -> dict[str, float]:
        """转为 dict。"""
        return {
            "trend": float(self.trend),
            "mean_reversion": float(self.mean_reversion),
            "fundamental": float(self.fundamental),
            "event_sentiment": float(self.event_sentiment),
        }

    def normalize(self) -> "StrategyWeights":
        """归一化到 sum=1.0 (disabled 策略 weight=0 会被排除后的相对权重).

        2026-08-12: __post_init__ 现在校验 sum>0 而非 sum==1, 所以输入可能是
        sum<1 的 (disabled 策略 weight=0). 此方法把 enabled 策略归一化到 sum=1.
        """
        total = self.trend + self.mean_reversion + self.fundamental + self.event_sentiment
        if total <= 0.0 or not math.isfinite(total):
            raise ValueError(f"无法归一化: 权重和 = {total}")
        return StrategyWeights(
            trend=self.trend / total,
            mean_reversion=self.mean_reversion / total,
            fundamental=self.fundamental / total,
            event_sentiment=self.event_sentiment / total,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategyWeights":
        """从 dict 构造, 缺省字段 = DEFAULT_WEIGHTS 对应值。"""
        kwargs: dict[str, float] = {}
        for key in STRATEGY_KEYS:
            if key in payload:
                kwargs[key] = _safe_float(payload[key], 0.0)
            else:
                kwargs[key] = DEFAULT_WEIGHTS[key]
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# 核心算法
# ---------------------------------------------------------------------------


def _extract_strategy_score(rec: Mapping[str, Any], strategy: str) -> float:
    """从单条 rec 中提取某策略的 ``direction * confidence`` 分数。

    缺失 / 异常 / completeness=0 时返回 0.0。

    Args:
        rec: 单条推荐 dict, 应含 ``strategy_signals`` 子字段
        strategy: 策略名 (``trend`` / ``mean_reversion`` / ``fundamental`` / ``event_sentiment``)

    Returns:
        有符号分数, 范围 [-100, +100]
    """
    if not isinstance(rec, Mapping):
        return 0.0
    signals = rec.get("strategy_signals")
    if not isinstance(signals, Mapping):
        return 0.0
    sig = signals.get(strategy)
    if not isinstance(sig, Mapping):
        return 0.0
    direction_raw = sig.get("direction", 0)
    try:
        direction_int = int(direction_raw)
    except (TypeError, ValueError):
        return 0.0
    # direction ∈ {-1, 0, +1}; 容忍 0 以外的小数退化
    if direction_int > 0:
        sign = 1.0
    elif direction_int < 0:
        sign = -1.0
    else:
        return 0.0
    confidence = _safe_float(sig.get("confidence"), 0.0)
    completeness = _safe_float(sig.get("completeness"), 0.0)
    # completeness=0 → 数据不可用, 视为 0 避免污染
    if completeness <= 0.0:
        return 0.0
    return sign * confidence


def _compute_weighted_score_b(
    rec: Mapping[str, Any],
    weights: StrategyWeights,
) -> float:
    """重算单条 rec 的 score_b (归一化到 [-1, +1])。

    公式::

        per_strategy_score[s] = sign(direction_s) * confidence_s        # 范围 [-100, +100]
        new_score_b = sum_s( weight_s * per_strategy_score[s] ) / (100 * sum_s(weight_s))

    权重归一化后计算 (2026-08-12): 此前要求 sum(weight)==1 才能保证输出范围正确,
    但权威源 DEFAULT_STRATEGY_WEIGHTS 是相对权重，sum 可能小于 1（当前 0.80）。现在显式
    归一化, 无论权重 sum 是多少, 输出范围都是 [-1, +1], 与生产路径 compute_score_b
    的 _normalize_active_weights 语义一致. 全 0 权重由 __post_init__ 拒绝.

    当 rec 缺失 ``strategy_signals`` 或四策略分数全为 0 时, 返回原 ``score_b`` (容错)。
    """
    if not isinstance(rec, Mapping):
        return 0.0
    weights_dict = weights.to_dict()
    total_weight = sum(weights_dict[strategy] for strategy in STRATEGY_KEYS)
    if total_weight <= 0.0:
        return _safe_float(rec.get("score_b"), 0.0)
    has_any_signal = False
    weighted_sum = 0.0
    for strategy in STRATEGY_KEYS:
        score = _extract_strategy_score(rec, strategy)
        if score != 0.0:
            has_any_signal = True
        weighted_sum += weights_dict[strategy] * score
    if not has_any_signal:
        # 无任何信号 — 回退到原 score_b
        return _safe_float(rec.get("score_b"), 0.0)
    return max(-1.0, min(1.0, weighted_sum / (MAX_STRATEGY_SCORE * total_weight)))


def reweight_recommendations(
    recommendations: Sequence[Mapping[str, Any]],
    weights: StrategyWeights,
    *,
    sort: bool = True,
) -> list[dict[str, Any]]:
    """重新计算每条 rec 的 score_b (按用户指定权重)。

    Args:
        recommendations: 推荐列表, 每条至少含 ``ticker`` / ``strategy_signals``
            (内含四策略 ``direction`` / ``confidence`` / ``completeness``)
        weights: 用户指定的四策略权重 (必须 sum-to-1)
        sort: 是否按新 score_b 降序排序 (默认 True)

    Returns:
        新推荐列表 — 每条新增 ``original_score_b`` 字段保留旧值, ``score_b`` 被覆盖,
        ``custom_weights`` 字段记录所用权重, 按新 ``score_b`` 降序。

    Notes:
        - 不修改入参, 内部 deep-copy
        - NaN/Inf 防御: 缺信号/异常 rec → 保留原 ``score_b``
        - 排序: 同分时 ticker 字典序升序 (稳定)
    """
    if not isinstance(recommendations, Sequence):
        return []
    # Lazy import: confidence_calibration → data_quality_audit → custom_weights
    # 形成 indirect cycle, 必须延迟到函数内 import (见下方 bucket-stale reset).
    from src.screening.confidence_calibration import _find_bucket as _find_score_bucket

    weights_dict = weights.to_dict()
    enriched: list[dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, Mapping):
            continue
        rec_copy: dict[str, Any] = dict(rec)
        original = _safe_float(rec.get("score_b"), 0.0)
        new_score_b = _compute_weighted_score_b(rec, weights)
        rec_copy["original_score_b"] = original
        rec_copy["score_b"] = new_score_b
        rec_copy["custom_weights"] = dict(weights_dict)
        # NS-19/c284: bucket-stale reset on score_b boundary cross.
        # auto_screening 报告里的 bucket 校准 (bucket_label / expected_returns /
        # win_rates / bucket_sample_count / bucket_t30_mature_count / downside)
        # 是为 ORIGINAL score_b 所属桶计算的. reweight 改了 score_b, 一旦越过桶
        # 边界 (dogfood 20260702 实测 5 只 top 中 3 只越界: 688019 中→中低,
        # 002463/300308 中低→低), 这些字段就 STALE — 反映的是旧桶的历史胜率/edge,
        # 对新 score_b 不成立. 下游 (CLI JSON / web slider / build_front_door_verdict)
        # 读到的是新 score_b 配旧桶校准, 误导决策.
        #
        # reweight 是纯函数, 无 tracking-record 访问, 无法重算校准. 正确做法是
        # 检测越界并 reset 为未知, 让调用方 (run_custom_weights 可调
        # compute_expected_returns 重算; web slider 可提示用户) 自行重算或当缺失处理.
        # composite_score 独立于 score_b (从 agent 信号 + bonuses 算, dogfood 实测
        # reweight 前后不变), 不在 reset 范围.
        _orig_bucket = _find_score_bucket(original) if math.isfinite(original) else None
        _new_bucket = _find_score_bucket(new_score_b) if math.isfinite(new_score_b) else None
        if _orig_bucket is not None and _new_bucket is not None and _orig_bucket[0] != _new_bucket[0] and rec.get("bucket_label") is not None:
            rec_copy["bucket_label"] = "未知"
            rec_copy["bucket_sample_count"] = 0
            rec_copy["bucket_t30_mature_count"] = 0
            rec_copy["bucket_t30_avg_negative_return"] = None
            rec_copy["expected_returns"] = {}
            rec_copy["win_rates"] = {}
            rec_copy["bucket_recalibration_needed"] = True
        enriched.append(rec_copy)

    if sort and enriched:
        enriched.sort(key=lambda r: (-_safe_float(r.get("score_b"), 0.0), str(r.get("ticker", ""))))
    return enriched


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------

# 复用 compare_tool 的 loader — 避免重复实现文件解析
__all__ = [
    "STRATEGY_KEYS",
    "MAX_STRATEGY_SCORE",
    "WEIGHT_SUM_TOLERANCE",
    "DEFAULT_WEIGHTS",
    "StrategyWeights",
    "reweight_recommendations",
    "load_latest_recommendations",
]


def load_latest_recommendations(
    report_dir: str | None = None,
    *,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """从最新 (或指定日期) ``auto_screening_*.json`` 报告加载推荐列表。

    Re-export :func:`src.screening.compare_tool.load_latest_recommendations`,
    便于 CLI / Web 端不需额外 import。
    """
    from src.screening.compare_tool import load_latest_recommendations as _loader

    if report_dir is not None:
        return _loader(report_dir=report_dir, trade_date=trade_date)
    return _loader(trade_date=trade_date)
