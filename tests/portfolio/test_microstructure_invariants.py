"""R20.26-B 防御层: 微结构 / 执行 invariant 测试。

这些测试不验证具体策略行为, 而是验证系统在所有合法输入下维持的不变量
(invariant) — 退出信号域、仓位非负、危机上限域、每日限额总量上限等。
任何未来重构只要违反这些不变量, 此文件应当 fail (红) 以阻止回归。

不变量分类:
  I-1 退出信号 sell_ratio 域 [0, 1]
  I-2 退出信号 level 取自封闭枚举
  I-3 仓位计算 shares 非负 (含 NaN / 边界)
  I-4 enforce_daily_trade_limit 总额 ≤ portfolio_nav * limit_ratio
  I-5 crisis_handler position_cap 域 [0, 1]
  I-6 limit_handler 三跌停后强制 risk_reduce_others
  I-7 suspension_handler release_ratio 域 [0, 0.5]
"""

from __future__ import annotations

import math

import pytest

from src.execution.crisis_handler import evaluate_crisis_response
from src.portfolio.exit_manager import HARD_STOP_LOSS_PCT, check_exit_signal
from src.portfolio.limit_handler import process_pending_buy, process_pending_sell, queue_pending_buy, queue_pending_sell
from src.portfolio.models import ExitSignal, HoldingState
from src.portfolio.position_calculator import calculate_position, enforce_daily_trade_limit
from src.portfolio.suspension_handler import can_resume_screening, handle_suspension_emergency
from src.execution.models import PendingOrder


# I-1 & I-2: exit signal domain invariants

def test_exit_signal_sell_ratio_always_within_unit_interval():
    """I-1: 任何触发条件下的 ExitSignal.sell_ratio 必须 ∈ [0, 1]。

    Pydantic Field(ge=0, le=1) 已强制此约束, 但 exit_manager 的所有分支
    都必须产生合法值 — 我们 fuzz 多个 pnl / holding_days 组合确认。"""
    base_holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260101",
        shares=1000,
        cost_basis=10_000.0,
    )
    # 全 pnl / holding_days / quality 网格
    for pnl_pct in [-0.20, -0.07, -0.06, -0.05, 0.0, 0.03, 0.10, 0.16, 0.26, 0.50]:
        for holding_days in [0, 1, 2, 3, 5, 7, 9, 12, 20, 40, 60]:
            for quality_score in [0.0, 0.35, 0.5, 0.75, 1.0]:
                for profit_take_stage in [0, 1, 2, 3]:
                    holding = base_holding.model_copy(
                        update={
                            "holding_days": holding_days,
                            "quality_score": quality_score,
                            "profit_take_stage": profit_take_stage,
                            "max_unrealized_pnl_pct": max(0.0, pnl_pct),
                            "execution_contract_bucket": "formal_full",
                        }
                    )
                    current_price = holding.entry_price * (1.0 + pnl_pct)
                    signal = check_exit_signal(holding, current_price=current_price, trade_date="20260610", atr_14=0.5)
                    if signal is not None:
                        assert isinstance(signal, ExitSignal)
                        assert 0.0 <= signal.sell_ratio <= 1.0, (
                            f"sell_ratio={signal.sell_ratio} 越界 [0,1] "
                            f"pnl={pnl_pct} days={holding_days} quality={quality_score} stage={profit_take_stage}"
                        )


def test_exit_signal_level_from_closed_enum():
    """I-2: ExitSignal.level 必须取自已知层级集合 {L1, L2, L2.5, L3, L4, L5}。

    防止未来新增层级后遗忘更新下游消费者。"""
    allowed_levels = {"L1", "L2", "L2.5", "L3", "L4", "L5"}
    holding = HoldingState(
        ticker="300724",
        entry_price=10.0,
        entry_date="20260101",
        shares=1000,
        cost_basis=10_000.0,
        holding_days=10,
        max_unrealized_pnl_pct=0.30,
        execution_contract_bucket="formal_full",
    )
    signal = check_exit_signal(holding, current_price=12.5, trade_date="20260610", atr_14=0.5)
    assert signal is not None
    assert signal.level in allowed_levels, f"未知 level: {signal.level}"


# I-3: position calculation non-negative

@pytest.mark.parametrize("avg_volume_20d", [float("nan"), 0.0, 1.0, 7_000.0, 100_000.0, 1e9])
def test_calculate_position_shares_non_negative(avg_volume_20d):
    """I-3: 任何 avg_volume_20d (含 NaN / 0 / 极大值) 下 shares 必须 ≥ 0。"""
    plan = calculate_position(
        ticker="300724",
        current_price=20.0,
        score_final=0.60,
        portfolio_nav=100_000,
        available_cash=50_000,
        avg_volume_20d=avg_volume_20d,
        industry_remaining_quota=25_000,
    )
    assert plan.shares >= 0, f"shares={plan.shares} < 0 (avg_volume_20d={avg_volume_20d})"
    assert plan.amount >= 0.0


# I-4: daily trade limit aggregate cap

def test_enforce_daily_trade_limit_total_amount_never_exceeds_cap():
    """I-4: enforce_daily_trade_limit 选出的 plan 总额 ≤ portfolio_nav * limit_ratio。"""
    from src.portfolio.models import PositionPlan

    plans = [
        PositionPlan(ticker=f"T{i}", shares=100, amount=90_000.0, constraint_binding="cash", score_final=0.9 - i * 0.05, execution_ratio=1.0)
        for i in range(10)
    ]
    portfolio_nav = 1_000_000
    limit_ratio = 0.20
    selected = enforce_daily_trade_limit(plans, portfolio_nav=portfolio_nav, limit_ratio=limit_ratio, max_new_positions=5)
    total = sum(plan.amount for plan in selected)
    assert total <= portfolio_nav * limit_ratio + 1e-9, f"total={total} > cap={portfolio_nav * limit_ratio}"
    assert len(selected) <= 5


# I-5: crisis position_cap domain

@pytest.mark.parametrize(
    "hs300_ret, limit_down, volumes, drawdown",
    [
        (0.0, 0, [10_000, 10_000, 10_000], 0.0),  # normal
        (-0.06, 600, [10_000, 10_000, 10_000], -0.05),  # defense
        (0.0, 0, [3_000, 3_000, 3_000], -0.05),  # shrink
        (-0.06, 600, [3_000, 3_000, 3_000], -0.16),  # all triggers
        (-0.10, 1000, [1_000, 1_000, 1_000], -0.20),  # extreme
    ],
)
def test_crisis_position_cap_within_unit_interval(hs300_ret, limit_down, volumes, drawdown):
    """I-5: crisis position_cap 始终 ∈ [0, 1], pause_new_buys 为 bool。"""
    result = evaluate_crisis_response(
        hs300_daily_return=hs300_ret,
        limit_down_count=limit_down,
        recent_total_volumes=volumes,
        drawdown_pct=drawdown,
    )
    assert 0.0 <= result["position_cap"] <= 1.0, f"position_cap={result['position_cap']} 越界"
    assert isinstance(result["pause_new_buys"], bool)
    assert isinstance(result["forced_reduce_ratio"], float)
    assert 0.0 <= result["forced_reduce_ratio"] <= 1.0


# I-6: three limit-down days forces risk_reduce_others

def test_pending_sell_three_consecutive_limit_down_forces_risk_reduce():
    """I-6: 持续跌停后必须最终触发 risk_reduce_others (而非无限 keep)。

    queue_pending_sell 初始 queue_days=1, 每次调用 next_days += 1,
    当 next_days >= 3 (即连续两个处理日 limit_down) 触发 risk_reduce_others。
    这是防止"流动性枯竭标的无止境占用队列"的关键护栏。"""
    order = queue_pending_sell("000001", -0.6, "20260305")
    # First processing day: queue_days=1 → next_days=2 (< 3, keep)
    r1 = process_pending_sell(order, is_limit_down=True)
    assert r1["action"] == "keep"
    order = order.model_copy(update={"queue_days": r1["queue_days"]})
    # Second processing day: queue_days=2 → next_days=3 (>= 3, escalate)
    r2 = process_pending_sell(order, is_limit_down=True)
    assert r2["action"] == "risk_reduce_others", f"持续跌停后应 risk_reduce_others, 实际 {r2['action']}"


# I-7: suspension release_ratio domain

def test_suspension_release_ratio_capped_at_half():
    """I-7: handle_suspension_emergency 的 release_ratio 必须 ∈ (0, 0.5]。"""
    holdings = [
        HoldingState(ticker="000001", entry_price=10.0, entry_date="20260201", shares=20_000, cost_basis=200_000, industry_sw="银行"),
        HoldingState(ticker="000002", entry_price=10.0, entry_date="20260201", shares=15_000, cost_basis=150_000, industry_sw="医药"),
    ]
    # suspended 占 80% NAV, 远超 10% 阈值
    result = handle_suspension_emergency(
        holdings,
        {"000001": 10.0, "000002": 10.0},
        {"000001"},
        total_nav=250_000,
    )
    assert "000002" in result
    release_ratio = result["000002"]
    assert 0.0 < release_ratio <= 0.5, f"release_ratio={release_ratio} 越界 (0, 0.5]"


def test_hard_stop_loss_threshold_is_six_percent():
    """I-8: HARD_STOP_LOSS_PCT = -6% — 防止有人改阈值时静默改变风控语义。"""
    assert HARD_STOP_LOSS_PCT == -0.06


def test_resume_screening_requires_three_clean_days():
    """I-9: 复牌后恢复筛选需 3 天无涨停 — 单日不达标, 三天全 clean 才放行。"""
    assert can_resume_screening(days_since_resume=3, recent_limit_statuses=[False, False, False]) is True
    assert can_resume_screening(days_since_resume=2, recent_limit_statuses=[False, False, False]) is False
    assert can_resume_screening(days_since_resume=3, recent_limit_statuses=[False, True, False]) is False
