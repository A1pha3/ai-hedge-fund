"""Q-5 尾部风险 — T+30 收益的 5th percentile (worst plausible outcome / CVaR proxy).

R144 赔率(下行) 给亏损**均值** (typical loss), P-2 给**标准差** (dispersion), 但都
不给**最坏情形**——-5% 均值配 -30% 尾 ≠ -5% 配 -8% 尾, 即使 std 相同尾部分布
也不同。本模块从 calibration 桶 T+30 收益算 5th percentile (5% 最差情形的阈值),
让用户看到"最坏 plausible 结果"。

服务产品目标"赔率"深尾维度。与 R144 (mean of losers) + P-2 (std) 三者互补:
均值 + 离散度 + 尾部 = 完整的风险三联体。

设计原则:
  - **percentile (linear interp)** — 标准统计, 非 min (min 是单点, 噪声大; p5 是
    分布的 5% 阈值, 更稳)
  - **None when <2 样本** — 诚实, 非 fake 0
  - **v1: 单只标的用其桶的 p5** — per-record 尾部需 raw returns (聚合桶已有)

CLI: ``--expected-returns`` / ``--decision-flow`` 展示
「T+30 +3.2%, 5% 分位 -18% (尾部) ⚠」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.display import Fore, Style

#: 深尾阈值 (百分点): p5 恶于此 → ⚠ deep-tail warning
_DEEP_TAIL_THRESHOLD: float = -15.0


@dataclass
class TailRiskReport:
    """T+30 收益的 5th-percentile 尾部风险。"""

    #: 5th percentile return (百分点; ≤0 typically; None = <2 样本)
    p5_return: float | None = None
    sample_count: int = 0
    available: bool = False


def _percentile_or_none(values: list[float], percentile: float) -> float | None:
    """Linear-interpolation percentile (numpy-style 'linear'); None when <2 samples.

    percentile in [0, 100]. 5 = 5th percentile (worst tail).
    """
    n = len(values)
    if n < 2:
        return None
    ordered = sorted(values)
    # linear interpolation index
    rank = (percentile / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def compute_tail_risk(
    t30_returns: list[float | None],
    *,
    percentile: float = 5.0,
) -> TailRiskReport:
    """从 T+30 收益列表算尾部风险 (5th percentile)。

    Args:
        t30_returns: per-record T+30 收益 (百分点单位, 匹配 calibration 惯例;
            None 元素被过滤)
        percentile: 分位 (默认 5 = 5th percentile worst-tail)

    Returns:
        :class:`TailRiskReport` (<2 有效 → available=False)
    """
    valid = [x for x in t30_returns if x is not None]
    if len(valid) < 2:
        return TailRiskReport(p5_return=None, sample_count=len(valid), available=False)
    p5 = _percentile_or_none(valid, percentile)
    if p5 is None:
        return TailRiskReport(p5_return=None, sample_count=len(valid), available=False)
    return TailRiskReport(p5_return=round(p5, 4), sample_count=len(valid), available=True)


def render_tail_risk_line(report: TailRiskReport) -> str:
    """渲染一行尾部风险 (数据不足 → 空串)。"""
    if not report.available or report.p5_return is None:
        return ""
    p5 = report.p5_return
    if p5 <= _DEEP_TAIL_THRESHOLD:
        return f"  {Fore.CYAN}🦎 尾部风险 (5% 分位):{Style.RESET_ALL} " f"{Fore.RED}{p5:.1f}% ⚠ (深尾, n={report.sample_count}){Style.RESET_ALL}"
    return f"  {Fore.CYAN}🦎 尾部风险 (5% 分位):{Style.RESET_ALL} " f"{p5:.1f}%  (n={report.sample_count})"


__all__ = [
    "TailRiskReport",
    "compute_tail_risk",
    "render_tail_risk_line",
]
