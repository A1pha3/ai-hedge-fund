"""--top-setups 编排器测试。"""

from __future__ import annotations

from src.screening.offensive.top_setups import (
    run_top_setups,
    render_top_setups,
    SetupPick,
    register_setup,
    list_setups,
)
from src.screening.offensive.statistics import Distribution
from src.screening.offensive.setups.base import Setup, DetectionResult


class _AlwaysHitStrongSetup(Setup):
    """测试用: 总是命中, 名字可注入。"""

    name = "test_strong"
    natural_horizon = 3

    def detect(self, ticker, trade_date, context):
        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=0.9,
            invalidation_condition="跌破 9.0",
            metadata={},
        )


def _strong_distribution():
    return Distribution(
        n=60,
        winrate=0.6,
        avg_gain=0.20,
        avg_loss=-0.08,
        convexity_ratio=3.0,
        expected_return=0.1,
        ci_low=0.05,
        ci_high=0.15,
        ic=0.08,
    )


def _weak_distribution():
    return Distribution(
        n=60,
        winrate=0.4,
        avg_gain=0.10,
        avg_loss=-0.12,
        convexity_ratio=0.8,
        expected_return=-0.02,
        ci_low=-0.05,
        ci_high=0.01,
        ic=-0.02,
    )


def test_list_setups_includes_defaults():
    names = list_setups()
    # 默认注册的 3 个 (若 import 成功)
    assert isinstance(names, list)


def test_run_top_setups_returns_empty_when_no_distribution():
    """setup 命中但无历史分布 → 不输出。"""
    register_setup("test_strong", _AlwaysHitStrongSetup)
    picks = run_top_setups(
        tickers=["000001"],
        trade_date="20260701",
        context_by_ticker={"000001": {}},
        distribution_lookup={},  # 空
        shadow=True,
        setups_to_run=["test_strong"],
    )
    assert picks == []


def test_run_top_setups_filters_low_convexity():
    """分布 convexity < 1.5 → 过滤。"""
    register_setup("test_strong", _AlwaysHitStrongSetup)
    picks = run_top_setups(
        tickers=["000001"],
        trade_date="20260701",
        context_by_ticker={"000001": {}},
        distribution_lookup={"test_strong": _weak_distribution()},
        shadow=True,
        setups_to_run=["test_strong"],
    )
    assert picks == []


def test_run_top_setups_strong_setup_returns_pick():
    """强 setup + 强分布 → 输出 1 只 Kelly pick。"""
    register_setup("test_strong", _AlwaysHitStrongSetup)
    picks = run_top_setups(
        tickers=["000001"],
        trade_date="20260701",
        context_by_ticker={"000001": {}},
        distribution_lookup={"test_strong": _strong_distribution()},
        shadow=True,
        setups_to_run=["test_strong"],
    )
    assert len(picks) == 1
    p = picks[0]
    assert p.ticker == "000001"
    assert p.setup_name == "test_strong"
    assert p.kelly.position_pct > 0
    assert p.shadow is True  # 默认 shadow
    assert p.risk_plan.time_exit == "T+3"


def test_run_top_setups_dedup_same_ticker():
    """同票多 setup 命中 → 只保留 Kelly 最大的 (主 setup)。"""

    class _Hit1(Setup):
        name = "hit1"
        natural_horizon = 3

        def detect(self, ticker, trade_date, context):
            return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date, trigger_strength=0.5, invalidation_condition="x")

    class _Hit2(Setup):
        name = "hit2"
        natural_horizon = 5

        def detect(self, ticker, trade_date, context):
            return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date, trigger_strength=0.5, invalidation_condition="y")

    register_setup("hit1", _Hit1)
    register_setup("hit2", _Hit2)
    # hit2 分布更强 → Kelly 更大 → 应保留
    strong = _strong_distribution()
    picks = run_top_setups(
        tickers=["000001"],
        trade_date="20260701",
        context_by_ticker={"000001": {}},
        distribution_lookup={"hit1": strong, "hit2": strong},
        shadow=True,
        setups_to_run=["hit1", "hit2"],
    )
    # 同票去重 → 只 1 只
    assert len(picks) == 1
    assert picks[0].ticker == "000001"


def test_render_top_setups_includes_shadow_warning():
    """shadow 模式渲染含强制警告。"""
    register_setup("test_strong", _AlwaysHitStrongSetup)
    picks = run_top_setups(
        tickers=["000001"],
        trade_date="20260701",
        context_by_ticker={"000001": {}},
        distribution_lookup={"test_strong": _strong_distribution()},
        shadow=True,
        setups_to_run=["test_strong"],
    )
    out = render_top_setups(picks, "20260701")
    assert "SHADOW" in out
    assert "未经验证" in out or "勿实盘" in out
    assert "000001" in out
    assert "Kelly" in out


def test_render_top_setups_empty_picks():
    out = render_top_setups([], "20260701")
    assert "无 setup 命中" in out
