"""R-1 多周期冲突 — 短期 vs 长期 horizon sign 冲突标记.

一只票可 T+1 看多但 T+30 看空 (短线 pop + 长线 fade), 或反之。用户当前看到
各 horizon 的数字却无冲突标记——短线 bullish + 长线 bearish 与各周期一致 bullish
是不同的决策信号。

本模块从 expected_returns 的短期 (T+1/T+5) 与长期 (T+20/T+30) 平均 sign 是否
一致判定冲突, 仅当双侧都 materially 非零时才标记 (避免噪声)。

设计原则:
  - **materiality 阈值** — 双侧均值 |value| >= ``_MATERIAL_THRESHOLD`` 才判定
    (0.05% 太小, 噪声)
  - **缺关键 horizon → 不判定** (诚实, 非猜)
  - **aligned bearish ≠ conflict** — 全负是"一致看空", 不是冲突

CLI: ``--top-picks`` per-pick 经 ``_render_horizon_conflict`` 展示
「⚠ 多周期冲突: T+1 +2.0% 但 T+30 -1.5% (短线 pop, 长线 fade)」。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.display import Fore, Style

#: materiality 阈值 (百分点): 双侧均值 |value| 须 >= 此值才判定冲突
_MATERIAL_THRESHOLD: float = 0.5


@dataclass
class HorizonConflict:
    """多周期冲突检测结果。"""

    has_conflict: bool = False
    short_label: str = ""  # "T+1" 等
    short_value: float = 0.0
    long_label: str = ""
    long_value: float = 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def detect_horizon_conflict(expected_returns: dict[str, float | None]) -> HorizonConflict:
    """检测短期 vs 长期 horizon 的 sign 冲突。

    Args:
        expected_returns: ``{"t1": ..., "t5": ..., "t10": ..., "t20": ..., "t30": ...}``
            (percent 单位; None = 该 horizon 无数据)

    Returns:
        :class:`HorizonConflict` (缺关键 horizon 或 materiality 不足 → has_conflict=False)
    """
    if not expected_returns:
        return HorizonConflict()

    # Anchor horizons: t5 (short-term), t20 (long-term) — same anchors R144 rhythm uses.
    # Requires BOTH to assess a short-vs-long sign conflict (extremes t1/t30 alone
    # are noisy without the mid-points).
    short = expected_returns.get("t5")
    long = expected_returns.get("t20")
    if short is None or long is None:
        return HorizonConflict()  # can't determine without anchors

    # Materiality: both sides must be materially non-zero
    if abs(short) < _MATERIAL_THRESHOLD or abs(long) < _MATERIAL_THRESHOLD:
        return HorizonConflict()

    # Conflict = opposite signs (one bullish, one bearish)
    if (short > 0) == (long > 0):
        return HorizonConflict()  # aligned (both bullish or both bearish)

    short_label = "T+5"
    long_label = "T+20"
    return HorizonConflict(
        has_conflict=True,
        short_label=short_label,
        short_value=round(short, 2),
        long_label=long_label,
        long_value=round(long, 2),
    )


def render_horizon_conflict(c: HorizonConflict) -> str:
    """渲染多周期冲突提示 (无冲突 → 空串)。"""
    if not c.has_conflict:
        return ""
    short_sign = "看多" if c.short_value > 0 else "看空"
    long_sign = "看多" if c.long_value > 0 else "看空"
    narrative = "短线 pop, 长线 fade" if c.short_value > 0 else "短线回调, 长线恢复"
    return (
        f"  {Fore.YELLOW}⚠ 多周期冲突:{Style.RESET_ALL} "
        f"{c.short_label} {c.short_value:+.1f}% ({short_sign}) 但 "
        f"{c.long_label} {c.long_value:+.1f}% ({long_sign})  ({narrative})"
    )


__all__ = [
    "HorizonConflict",
    "detect_horizon_conflict",
    "render_horizon_conflict",
]
