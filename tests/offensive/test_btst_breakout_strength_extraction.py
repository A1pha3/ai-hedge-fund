"""R219 Op1: 强度 ranker 提取等价测试 — detect 与门挡反事实读面单一实现.

行为等价证明面: counterfactual_trigger_strength(同一价格帧) 必须逐值等于
detect 命中行的 trigger_strength (ranker 单一实现, 无 fork); c2/c3/c4 门挡
候选的反事实强度可计算性 (ranker 只依赖 prices+ticker) 与 None 边界家族
钉死. fixture 非对称 (R13 教训: 对称 fixture 的数值断言无牙)。
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.setups.btst_breakout import (
    BtstBreakoutSetup,
    _strength_components,
    counterfactual_trigger_strength,
)


def _base_prices(today_pct=10.0, pre5_close=10.5, n=22, pre5_pct=None):
    """今天涨停 (+10%), 5 日前 close=pre5_close (默认 4.76% runup, 过条件4).

    pre5_pct: 可选, 把 trigger 前窗口 (chained_return_pct 复合 iloc[ref+1..trigger-1])
    内的 pct_change 设为该值 (构造 c4_runup_exceeded 用)。
    """
    dates = pd.bdate_range("2026-06-01", periods=n)
    closes = [10.0] * (n - 1) + [11.0]
    if n >= 6:
        closes[-6] = pre5_close
    pct = [0.0] * (n - 2) + [0.0, today_pct]
    if pre5_pct is not None and n >= 5:
        pct[-5] = pre5_pct
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "open": closes,
            "high": closes,
            "low": closes,
            "pct_change": pct,
        }
    )


def _flow_records(prices, today_inflow=5_000_000, old_inflow=100_000):
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [
        FundFlowRecord(
            ticker="X", date=today, close=11.0, pct_change=10.0,
            main_net_inflow=today_inflow, main_net_pct=8.0,
        )
    ]
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        recs.append(
            FundFlowRecord(
                ticker="X", date=d, close=10.0, pct_change=0.0,
                main_net_inflow=old_inflow, main_net_pct=0.5,
            )
        )
    return recs


def _today(prices):
    return prices.iloc[-1]["date"].strftime("%Y%m%d")


class TestCounterfactualMatchesDetect:
    def test_hit_case_value_and_component_equality(self):
        """等价核心: hit 候选的反事实强度与分量 == detect 返回值逐项相等."""
        prices = _base_prices()
        today = _today(prices)
        ctx = {
            "prices": prices,
            "fund_flow_records": _flow_records(prices),
            "industry_day_pct": 3.0,
            "regime": "normal",
        }
        result = BtstBreakoutSetup().detect("X", today, ctx)
        assert result.hit is True
        cf = counterfactual_trigger_strength(prices, today, "X")
        assert cf == pytest.approx(result.trigger_strength)
        assert 0.0 < cf <= 1.0
        # 分量面: 提取函数在同一帧上的分量 == detect metadata 分量 (单一实现)
        ref_idx = len(prices) - 1 - 5
        components = _strength_components(
            prices.reset_index(drop=True).assign(
                date_str=pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
            ),
            len(prices) - 1,
            ref_idx,
            "X",
            result.metadata["limit_up_pct_threshold"],
            today,
        )
        for key in (
            "board_score",
            "low_vol_score",
            "squeeze_score",
            "volume_score",
            "range_score",
            "weekday_score",
            "position_score",
            "energy_bonus",
        ):
            assert components[key] == pytest.approx(result.metadata[key]), key
        assert components["strength"] == pytest.approx(result.trigger_strength)
        assert result.metadata["limit_up_streak"] >= 1

    def test_flow_blocked_candidate_strength_computable(self):
        """c2 门挡候选 (flow 缺失) 反事实强度可计算 — R140 Op2 局限收口."""
        prices = _base_prices()
        today = _today(prices)
        blocked = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": [], "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert blocked.hit is False
        assert blocked.miss_stage == "c2_flow_missing"
        assert blocked.trigger_strength == 0.0  # _miss 契约: 0.0 而非真实强度
        cf = counterfactual_trigger_strength(prices, today, "X")
        assert cf is not None and cf > 0.0  # 反事实读面显出真实强度

    def test_flow_blocked_strength_equals_hit_strength_same_frame(self):
        """强度只依赖 prices+ticker: 同帧 hit 与 c2 门挡的反事实值相等."""
        prices = _base_prices()
        today = _today(prices)
        hit = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": _flow_records(prices), "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert hit.hit is True
        assert counterfactual_trigger_strength(prices, today, "X") == pytest.approx(
            hit.trigger_strength
        )

    def test_industry_blocked_candidate_strength_computable(self):
        """c3 门挡候选 (行业缺失/弱) 反事实强度可计算 — c3 归因判读关键."""
        prices = _base_prices()
        today = _today(prices)
        blocked = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": _flow_records(prices), "industry_day_pct": None, "regime": "normal"},
        )
        assert blocked.hit is False
        assert blocked.miss_stage == "c3_industry_missing"
        cf = counterfactual_trigger_strength(prices, today, "X")
        # 强度只依赖 prices+ticker: c3 门挡候选的反事实值 == 同帧 hit 值
        hit = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": _flow_records(prices), "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert hit.hit is True
        assert cf == pytest.approx(hit.trigger_strength)
        assert cf > 0.0

    def test_runup_blocked_candidate_strength_computable(self):
        """c4_runup_exceeded 门挡候选 (pre5 runup >8%) 反事实强度可计算."""
        prices = _base_prices(pre5_pct=9.0)
        today = _today(prices)
        blocked = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": _flow_records(prices), "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert blocked.hit is False
        assert blocked.miss_stage == "c4_runup_exceeded"
        cf = counterfactual_trigger_strength(prices, today, "X")
        assert cf is not None and cf > 0.0


class TestCounterfactualNoneBoundaries:
    """None = 不可计算, 绝不冒充 0.0 (0.0 是合法强度值)."""

    def test_none_prices(self):
        assert counterfactual_trigger_strength(None, "20260622", "X") is None

    def test_empty_prices(self):
        assert counterfactual_trigger_strength(
            pd.DataFrame(columns=["date", "close", "pct_change"]), "20260622", "X"
        ) is None

    def test_missing_trigger_row(self):
        prices = _base_prices()
        assert counterfactual_trigger_strength(prices, "19990101", "X") is None

    def test_short_history_ref_idx_negative(self):
        """与 detect c4_data_short 同边界: 历史不足 (<6 行) 强度不可比."""
        prices = _base_prices(n=4)
        today = _today(prices)
        assert counterfactual_trigger_strength(prices, today, "X") is None

    def test_deterministic_same_input_same_value(self):
        prices = _base_prices()
        today = _today(prices)
        a = counterfactual_trigger_strength(prices, today, "X")
        b = counterfactual_trigger_strength(prices, today, "X")
        assert a == b and a is not None and math.isfinite(a)
