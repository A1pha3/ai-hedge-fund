"""上下文因子: setup 间相关性折价 + 市场温度 (v2 §2.5 §2.6)。

这两个因子调整 Kelly 仓位:
- correlation_discount: 多 setup 命中同票时, 按历史相关性降仓 (防顺周期)
- market_temperature_factor: 市场过热降仓 / 恐慌加仓 (countercyclical)
"""

from __future__ import annotations

from typing import Any

import numpy as np


def correlation_discount(hit_setup_names: list[str], correlation_matrix: dict[tuple[str, str], float] | None = None) -> float:
    """多 setup 命中同票时的折价系数。

    v2 §2.5: 不加分, 反而降仓。
    discount = 1 - 0.5 × max(pairwise_correlation among hit setups)

    Args:
        hit_setup_names: 同票命中的 setup 名称列表
        correlation_matrix: {(setup_a, setup_b): 相关系数}; None 时用默认

    Returns:
        折价系数 [0.5, 1.0]; 单 setup 命中 = 1.0 (无折价)
    """
    if len(hit_setup_names) <= 1:
        return 1.0
    # 默认相关性矩阵 (经验值, 同类 setup 相关性高)
    default_corr = correlation_matrix or {}
    max_corr = 0.0
    for i in range(len(hit_setup_names)):
        for j in range(i + 1, len(hit_setup_names)):
            a, b = hit_setup_names[i], hit_setup_names[j]
            c = default_corr.get((a, b), default_corr.get((b, a), 0.5))  # 默认 0.5 中等相关
            max_corr = max(max_corr, abs(c))
    return max(0.5, 1.0 - 0.5 * max_corr)


def market_temperature_factor(
    n_limit_up: int,
    n_total: int,
    turnover_ratio: float = 1.0,
) -> float:
    """市场温度因子 (countercyclical)。

    v2 §2.6: 过热降仓, 恐慌加仓。
    用涨停家数占比 + 换手率判断温度。

    Args:
        n_limit_up: 今日涨停家数
        n_total: 全市场家数
        turnover_ratio: 今日换手率 vs 20 日均值 (1.0 = 正常)

    Returns:
        温度因子; > 1 = 加仓 (恐慌), < 1 = 降仓 (过热), 1.0 = 正常
    """
    if n_total <= 0:
        return 1.0
    limit_up_pct = n_limit_up / n_total
    # 涨停占比 z-score 近似 (经验阈值: 1% 为正常, > 3% 过热, < 0.3% 过冷)
    if limit_up_pct > 0.03 and turnover_ratio > 1.3:
        return 0.7  # 过热: 涨停多 + 放量 → 顺周期风险, 降仓 30%
    if limit_up_pct < 0.003:
        return 1.2  # 过冷/恐慌: 超跌反弹 setup 的 countercyclical 机会, 加仓 20%
    return 1.0
