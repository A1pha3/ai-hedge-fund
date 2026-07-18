"""除权免疫的窗口收益计算 (pct_change 链式复合).

price_cache 存不复权原始价: 除权日 close 机械跳变 (10送10 直接腰斩), 原始价
比值会把"假跌"读成超跌/回调 —— 2026H1 全市场实测 817 个幻影超跌票日 (raw
30d ≤ -20% 但真实跌幅远不足), 漏检仅 5 个, 方向高度不对称. pct_change 列是
数据源给出的真实日涨幅 (除权基准价已由交易所重置), 链式复合即可还原调整后
窗口收益: 与原始价同窗口、无未来数据、无复权因子依赖.
"""

from __future__ import annotations

import math

import pandas as pd


def chained_return_pct(
    prices: pd.DataFrame, start_idx: int, end_idx: int
) -> float | None:
    """close[start_idx] → close[end_idx] 的调整后收益 (%) — pct_change 链式复合.

    数学恒等: ``close[end]/close[start] - 1 == prod(1 + pct_i/100) - 1``
    (i ∈ (start, end]), 右端对除权缺口免疫. 窗口内任一 pct_change 缺失/非有限
    返回 None — 调用方按各自的保守语义处理 (过滤器 fail-closed, 预过滤放行给
    detect 判定).
    """

    if prices is None or "pct_change" not in prices.columns:
        return None
    n = len(prices)
    if not (0 <= start_idx < end_idx < n):
        return None
    window = prices.iloc[start_idx + 1 : end_idx + 1]["pct_change"]
    compound = 1.0
    for value in window:
        try:
            pct = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(pct):
            return None
        compound *= 1.0 + pct / 100.0
    return (compound - 1.0) * 100.0
