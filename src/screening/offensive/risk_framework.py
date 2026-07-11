"""风险框架 (v2 §C.6) — 每 setup 的失效条件 + 止损 + 时间退出 + 组合 drawdown 熔断。

设计文档 §4.2 步骤 12: 每个入选票附风险计划。

优化 (2026-07-11): per-setup 止损策略. BTST 止损只披露 (回测验证不执行更优);
OversoldBounce 止损真正执行 -8% (无 alpha, 尾部亏损 20%, 执行止损截断尾部).
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
    stop_policy: str = "disclose_only"  # "disclose_only" (只披露) / "execute" (真按止损平仓)


# per-setup 默认止损策略
# BTST: disclose_only — 回测验证 (2026-07-10, 91 笔): no_stop E=+5.55%/Sharpe 0.37
#   优于所有止损变体. 均值回归 setup 的波动反而赚钱.
# OversoldBounce: execute fixed8 — 无 alpha (E=+0.34%), 尾部亏损 20% (>-10%).
#   执行止损截断尾部, 避免单笔大亏侵蚀组合.
_DEFAULT_STOP_POLICY: dict[str, str] = {
    "btst_breakout": "disclose_only",
    "oversold_bounce": "execute",
}


def build_risk_plan(
    invalidation_condition: str,
    avg_loss: float,
    natural_horizon: int,
    hard_stop_pct: float = -0.08,
    setup_name: str = "",
) -> RiskPlan:
    """从 setup 失效条件 + 历史亏损 → 风险计划。

    软止损 = avg_loss × 1.2 (温和缓冲), 且 clamp 到比 hard_stop 更窄 (否则不可达)。
    硬止损 = -8% (绝对底线)。
    时间退出 = T+<natural_horizon>。
    止损策略 = per-setup (BTST disclose_only, OversoldBounce execute).
    """
    # Bug fix: 旧公式 avg_loss×1.5 对 BTST 产生 -13.8% soft_stop, 比 hard_stop -8% 更宽 → 不可达。
    # 改为 avg_loss×1.2 + clamp 到 hard_stop 的 80% (确保 soft < hard).
    raw_soft = avg_loss * 1.2
    soft_stop = max(raw_soft, hard_stop_pct * 0.8)  # soft_stop 更靠近 0 (更窄)
    stop_policy = _DEFAULT_STOP_POLICY.get(setup_name, "disclose_only")
    return RiskPlan(
        invalidation_condition=invalidation_condition,
        stop_loss_pct=soft_stop,
        hard_stop_pct=hard_stop_pct,
        time_exit=f"T+{natural_horizon}",
        natural_horizon=natural_horizon,
        stop_policy=stop_policy,
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
