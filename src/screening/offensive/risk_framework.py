"""风险框架 (v2 §C.6) — 每 setup 的失效条件 + 止损 + 时间退出 + 组合 drawdown 熔断。

设计文档 §4.2 步骤 12: 每个入选票附风险计划。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPlan:
    """单票风险计划。"""

    invalidation_condition: str  # setup 触发反转的描述性条件
    stop_loss_pct: float  # 软止损 (基于 setup 历史最大亏损)
    hard_stop_pct: float  # 硬止损 (绝对值, 默认 -8%)
    time_exit: str  # 时间退出 ("T+N")
    natural_horizon: int  # setup 自然 horizon


def build_risk_plan(
    invalidation_condition: str,
    avg_loss: float,
    natural_horizon: int,
    hard_stop_pct: float = -0.08,
) -> RiskPlan:
    """从 setup 失效条件 + 历史亏损 → 风险计划。

    软止损 = avg_loss × 1.5 (给一点缓冲, 不在历史均值处就止损)。
    硬止损 = -8% (绝对底线)。
    时间退出 = T+<natural_horizon>。
    """
    soft_stop = avg_loss * 1.5  # 软止损 = 历史均值 × 1.5 (给缓冲); 与硬止损是两个独立层级
    return RiskPlan(
        invalidation_condition=invalidation_condition,
        stop_loss_pct=soft_stop,
        hard_stop_pct=hard_stop_pct,
        time_exit=f"T+{natural_horizon}",
        natural_horizon=natural_horizon,
    )


# 组合层 drawdown 熔断阈值 (设计文档 §6.3)
DRAWDOWN_DECREASE_THRESHOLD = -0.15  # -15% 降仓
DRAWDOWN_LIQUIDATE_THRESHOLD = -0.20  # -20% 清仓


def drawdown_action(current_drawdown_pct: float) -> str:
    """根据当前组合 drawdown 返回动作。

    Args:
        current_drawdown_pct: 当前回撤 (负数, e.g. -0.12 = -12%)

    Returns:
        "normal" / "decrease" (降仓) / "liquidate" (清仓)
    """
    if current_drawdown_pct <= DRAWDOWN_LIQUIDATE_THRESHOLD:
        return "liquidate"
    if current_drawdown_pct <= DRAWDOWN_DECREASE_THRESHOLD:
        return "decrease"
    return "normal"
