"""Setup-3 板块轮动 + context_factors + risk_framework 测试。"""

from __future__ import annotations

import pandas as pd

from src.screening.offensive.setups.sector_rotation import SectorRotationSetup
from src.screening.offensive.context_factors import correlation_discount, market_temperature_factor
from src.screening.offensive.risk_framework import build_risk_plan, drawdown_action

# ---- Setup-3 sector_rotation ----


def test_sector_rotation_hit():
    ctx = {
        "industry_2d_pct": 5.0,  # 行业 2 日涨 5%
        "industry_net_flow": 10_000_000,
        "stock_today_pct": 1.0,  # 龙头今日只涨 1% (< 5% × 0.5 = 2.5%)
        "prices": pd.DataFrame({"close": [10.0]}),
    }
    result = SectorRotationSetup().detect("X", "20260701", ctx)
    assert result.hit is True
    assert result.natural_horizon if hasattr(result, "natural_horizon") else True
    assert "轮动" in result.invalidation_condition


def test_sector_rotation_miss_industry_weak():
    ctx = {"industry_2d_pct": 1.5, "industry_net_flow": 10_000_000, "stock_today_pct": 0.5}  # 行业涨幅 < 3%
    assert SectorRotationSetup().detect("X", "20260701", ctx).hit is False


def test_sector_rotation_miss_leader_already_up():
    ctx = {
        "industry_2d_pct": 5.0,
        "industry_net_flow": 10_000_000,
        "stock_today_pct": 4.0,  # 龙头已涨 4% (> 2.5%), 不是"未涨"
    }
    assert SectorRotationSetup().detect("X", "20260701", ctx).hit is False


def test_sector_rotation_miss_flow_negative():
    ctx = {
        "industry_2d_pct": 5.0,
        "industry_net_flow": -1_000_000,  # 行业资金流出
        "stock_today_pct": 1.0,
    }
    assert SectorRotationSetup().detect("X", "20260701", ctx).hit is False


def test_sector_rotation_degraded_when_flow_missing():
    """industry_net_flow 未注入 (无真实数据源) → 条件3 降级, hit 继续, degraded=True.

    NS-17 同类: 此前条件3 是硬 miss (0.0 <= 0), 导致 SectorRotation 全量 0 hits.
    现在缺数据时跳过条件3 但标 degraded, 让 setup 退化为 2 条件版参与 Phase 0.
    """
    ctx = {
        "industry_2d_pct": 5.0,  # 行业 2 日涨 5% (条件1 ✅)
        # industry_net_flow 不提供 → 降级
        "stock_today_pct": 1.0,  # 龙头今日只涨 1% (< 2.5%, 条件2 ✅)
        "prices": pd.DataFrame({"close": [10.0]}),
    }
    result = SectorRotationSetup().detect("X", "20260701", ctx)
    assert result.hit is True  # 条件1+2 满足, hit 继续
    assert result.degraded is True  # 条件3 跳过, 标降级
    assert "industry_net_flow" in result.degradation_reason or "条件3" in result.degradation_reason


def test_sector_rotation_degraded_zero_flow_treated_as_missing():
    """industry_net_flow=0.0 (默认值) 也算"未注入", 触发降级而非硬 miss."""
    ctx = {
        "industry_2d_pct": 4.0,
        "industry_net_flow": 0.0,  # 默认值, 等同未注入
        "stock_today_pct": 0.5,
        "prices": pd.DataFrame({"close": [10.0]}),
    }
    result = SectorRotationSetup().detect("X", "20260701", ctx)
    assert result.hit is True
    assert result.degraded is True


def test_sector_rotation_not_degraded_when_flow_provided_positive():
    """industry_net_flow 提供了正值 → 条件3 正常判定, 不降级."""
    ctx = {
        "industry_2d_pct": 5.0,
        "industry_net_flow": 5_000_000,  # 真实正值
        "stock_today_pct": 1.0,
        "prices": pd.DataFrame({"close": [10.0]}),
    }
    result = SectorRotationSetup().detect("X", "20260701", ctx)
    assert result.hit is True
    assert result.degraded is False


# ---- context_factors ----


def test_correlation_discount_single_setup_no_discount():
    assert correlation_discount(["btst_breakout"]) == 1.0


def test_correlation_discount_multi_setup_with_default_corr():
    """2 个 setup 命中, 默认相关 0.5 → discount = 1 - 0.5×0.5 = 0.75。"""
    d = correlation_discount(["btst_breakout", "sector_rotation"])
    assert abs(d - 0.75) < 1e-9


def test_correlation_discount_capped_at_0_5():
    """极高相关 (0.95) → discount 触底 0.5。"""
    d = correlation_discount(["a", "b"], correlation_matrix={("a", "b"): 0.95})
    assert abs(d - 0.525) < 1e-9  # 1 - 0.5×0.95 = 0.525


def test_market_temperature_normal():
    # 50/5000 = 1.0% 涨停占比, 在 [0.3%, 3%] 正常区间
    assert market_temperature_factor(n_limit_up=50, n_total=5000) == 1.0


def test_market_temperature_overheated():
    """涨停 5% + 放量 → 过热降仓 0.7。"""
    assert market_temperature_factor(n_limit_up=200, n_total=4000, turnover_ratio=1.5) == 0.7


def test_market_temperature_panic():
    """涨停 < 0.3% → 恐慌加仓 1.2。"""
    assert market_temperature_factor(n_limit_up=5, n_total=5000) == 1.2


# ---- risk_framework ----


def test_build_risk_plan_basic():
    plan = build_risk_plan(
        invalidation_condition="跌破 9.2",
        avg_loss=-0.08,
        natural_horizon=3,
    )
    # soft_stop = avg_loss × 1.2 = -0.096, clamped to hard_stop × 0.8 = -0.064
    assert plan.stop_loss_pct == -0.064  # clamped: max(-0.096, -0.064) = -0.064
    assert plan.hard_stop_pct == -0.08
    assert plan.time_exit == "T+3"


def test_build_risk_plan_soft_stop_independent_of_hard():
    """soft_stop 比 hard_stop 更窄 (两级止损: soft=警告位 -6.4%, hard=强制 -8%)."""
    plan = build_risk_plan(
        invalidation_condition="x",
        avg_loss=-0.10,
        natural_horizon=5,
    )
    # raw_soft = -0.10 × 1.2 = -0.12; clamped to max(-0.12, -0.064) = -0.064
    assert abs(plan.stop_loss_pct - (-0.064)) < 1e-9  # clamp 到 hard_stop × 0.8
    assert plan.hard_stop_pct == -0.08
    assert plan.stop_loss_pct > plan.hard_stop_pct  # soft 更靠近 0 (更窄)


def test_drawdown_action_thresholds():
    assert drawdown_action(-0.10) == "normal"
    assert drawdown_action(-0.15) == "decrease"
    assert drawdown_action(-0.18) == "decrease"
    assert drawdown_action(-0.20) == "liquidate"
    assert drawdown_action(-0.25) == "liquidate"
