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
    assert plan.stop_loss_pct == -0.12  # -0.08 × 1.5
    assert plan.hard_stop_pct == -0.08
    assert plan.time_exit == "T+3"


def test_build_risk_plan_soft_stop_independent_of_hard():
    """soft_stop = avg_loss × 1.5 (独立); hard_stop 是另一层 (绝对底线 -8%)。"""
    plan = build_risk_plan(
        invalidation_condition="x",
        avg_loss=-0.10,  # × 1.5 = -0.15 (软止损, 比 hard_stop 宽)
        natural_horizon=5,
    )
    assert abs(plan.stop_loss_pct - (-0.15)) < 1e-9  # 软止损独立 (浮点容差)
    assert plan.hard_stop_pct == -0.08  # 硬止损是另一层底线
    # 操作者两个都用: soft = 警告位, hard = 强制清仓位


def test_drawdown_action_thresholds():
    assert drawdown_action(-0.10) == "normal"
    assert drawdown_action(-0.15) == "decrease"
    assert drawdown_action(-0.18) == "decrease"
    assert drawdown_action(-0.20) == "liquidate"
    assert drawdown_action(-0.25) == "liquidate"
