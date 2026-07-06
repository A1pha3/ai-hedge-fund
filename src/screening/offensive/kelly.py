"""Kelly 仓位计算 — v2 真正的排序键。

half-Kelly 默认 (v2 §C.2 + 设计讨论): full Kelly 对估计误差敏感, half-Kelly
牺牲 25% 长期收益换大幅降低破产概率和方差。

公式 (离散二元结果):
    kelly_fraction = winrate / |avg_loss| - (1 - winrate) / avg_gain
    half_kelly = 0.5 × kelly_fraction

含仓位上限: 单 setup ≤ max_pct (默认 10%)。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.screening.offensive.statistics import Distribution

# half-Kelly 系数 (v2 决定: 半凯利, 非 full)
_KELLY_FRACTION = 0.5
# 单 setup 仓位上限 (设计文档 §4.2 步骤 8)
_DEFAULT_MAX_PCT = 0.10


@dataclass(frozen=True)
class KellySize:
    """Kelly 仓位计算结果。"""

    kelly_raw: float  # full kelly fraction (可能 > 1 或 < 0)
    kelly_half: float  # 0.5 × kelly_raw
    position_pct: float  # 实际建议仓位 (half-kelly × 折价, capped at max_pct)
    capped: bool  # 是否触顶


def kelly_fraction(winrate: float, avg_gain: float, avg_loss: float) -> float:
    """计算 full Kelly 下注比例。

    Args:
        winrate: 胜率 [0, 1]
        avg_gain: 单次盈利幅度 (正数, e.g. 0.20 = +20%)
        avg_loss: 单次亏损幅度 (负数, e.g. -0.08 = -8%)

    Returns:
        Kelly fraction; 负值 = 不该下注; > 1 = 极端有利 (实际会 cap)
    """
    if avg_gain <= 0 or avg_loss >= 0 or winrate <= 0 or winrate >= 1:
        return 0.0
    # kelly = w/b - (1-w)/g, 其中 b = |avg_loss|, g = avg_gain
    b = abs(avg_loss)
    g = avg_gain
    return winrate / b - (1 - winrate) / g


def compute_kelly_size(
    dist: Distribution,
    correlation_discount: float = 1.0,
    market_temperature_factor: float = 1.0,
    max_pct: float = _DEFAULT_MAX_PCT,
) -> KellySize:
    """从分布 + 折价因子 → 最终建议仓位 (half-Kelly)。

    Args:
        dist: setup 历史分布
        correlation_discount: 多 setup 相关性折价 [0, 1] (1=无折价)
        market_temperature_factor: 市场温度调整 [0, ∞) (1=正常, <1=过热降仓, >1=恐慌加仓)
        max_pct: 单票仓位上限

    Returns:
        KellySize; position_pct ≤ max_pct
    """
    kelly_raw = kelly_fraction(dist.winrate, dist.avg_gain, dist.avg_loss)
    kelly_half = _KELLY_FRACTION * kelly_raw
    adjusted = kelly_half * correlation_discount * market_temperature_factor
    if adjusted < 0:
        return KellySize(kelly_raw=kelly_raw, kelly_half=kelly_half, position_pct=0.0, capped=False)
    capped = adjusted > max_pct
    position_pct = min(adjusted, max_pct)
    return KellySize(kelly_raw=kelly_raw, kelly_half=kelly_half, position_pct=position_pct, capped=capped)
