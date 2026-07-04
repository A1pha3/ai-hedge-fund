"""Q-2 回撤预期 — 从 calibration per-horizon 累计收益估同分位平均路径最大回撤.

T+30 edge 是端点 (+3.2%), 但路径重要——+3.2% 配 −15% mid-hold 回撤 ≠ +3.2%
配 −2%。本模块从 score 桶的 per-horizon (t1/t5/t10/t20/t30) **平均**累计收益序列
估"平均路径"的最大回撤 (worst peak-to-trough dip along the avg path)。

诚实边界 (文档化):
  - 这是**平均路径**的回撤, 不是 per-record 回撤的均值 (Jensen 不等式: 回撤是凹
    操作, 平均路径回撤 ≤ per-record 均值回撤)。per-record 路径不在聚合桶统计里,
    v1 用平均路径作 proxy。展示文案明确"平均路径"。
  - None 当 <2 个有效 horizon (无法构成路径)。

CLI: ``--expected-returns`` / ``--decision-flow`` 展示
「T+30 +3.2%, 平均路径最大回撤 −8%」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.display import Fore, Style

#: HORIZON 顺序 (累计收益路径的时间轴)
_HORIZON_ORDER: tuple[str, ...] = ("t1", "t5", "t10", "t20", "t30")

#: 回撤深于此阈值 (百分点) → ⚠ 警告
_DEEP_DRAWDOWN_THRESHOLD: float = -10.0


@dataclass
class DrawdownEstimate:
    """平均路径最大回撤估计。"""

    #: 最大回撤 (百分点, ≤0; 0 = 无回撤; None = 数据不足)
    max_drawdown: float | None = None
    #: T+30 端点收益 (百分点, 供展示配对)
    t30_return: float | None = None
    available: bool = False


def _estimate_path_max_drawdown(
    cumulative_returns: list[float | None],
) -> float | None:
    """从累计收益序列估最大回撤 (worst peak-to-trough)。

    跳过 None horizon; <2 个有效点 → None。单调上升 → 0.0。
    """
    values = [v for v in cumulative_returns if v is not None]
    if len(values) < 2:
        return None
    peak = values[0]
    max_dd = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        dd = v - peak  # ≤ 0 when below peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def compute_drawdown_estimate(
    horizon_returns: dict[str, float | None],
) -> DrawdownEstimate:
    """从 per-horizon 累计收益估平均路径最大回撤。

    Args:
        horizon_returns: ``{"t1": ..., "t5": ..., "t10": ..., "t20": ..., "t30": ...}``
            (值在 PERCENT 单位, 匹配 calibration 惯例; None = 该 horizon 无数据)

    Returns:
        :class:`DrawdownEstimate` (<2 有效 horizon → available=False)
    """
    path = [horizon_returns.get(h) for h in _HORIZON_ORDER]
    dd = _estimate_path_max_drawdown(path)
    t30 = horizon_returns.get("t30")
    if dd is None:
        return DrawdownEstimate(max_drawdown=None, t30_return=t30, available=False)
    return DrawdownEstimate(max_drawdown=dd, t30_return=t30, available=True)


def render_drawdown_line(est: DrawdownEstimate) -> str:
    """渲染一行回撤预期 (数据不足 → 空串)。"""
    if not est.available or est.max_drawdown is None:
        return ""
    dd = est.max_drawdown
    t30 = est.t30_return
    t30_str = f"{t30:+.1f}%" if t30 is not None else "—"
    if dd <= _DEEP_DRAWDOWN_THRESHOLD:
        return f"  {Fore.CYAN}📉 回撤预期:{Style.RESET_ALL} " f"T+30 {t30_str}, 平均路径最大回撤 {Fore.RED}{dd:.1f}% ⚠ (深){Style.RESET_ALL}"
    return f"  {Fore.CYAN}📉 回撤预期:{Style.RESET_ALL} " f"T+30 {t30_str}, 平均路径最大回撤 {dd:.1f}%"


__all__ = [
    "DrawdownEstimate",
    "compute_drawdown_estimate",
    "render_drawdown_line",
]
