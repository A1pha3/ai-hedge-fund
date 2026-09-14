"""R219 Op1: 强度 ranker 提取等价测试 — detect 与门挡反事实读面单一实现.

行为等价证明面: counterfactual_trigger_strength(同一价格帧) 必须逐值等于
detect 命中行的 trigger_strength (ranker 单一实现, 无 fork); c2/c3/c4 门挡
候选的反事实强度可计算性 (ranker 只依赖 prices+ticker) 与 None 边界家族
钉死. fixture 非对称 (R13 教训: 对称 fixture 的数值断言无牙)。

R219 Op2 对抗收口 (变异探针 13 发: 4 TEETH + 9 SURVIVORS 定谳): 等价性测试
对 ranker 公式漂移全盲 (两侧同变恒真) — 权重/换位/cap/energy 边界由
TestRankerArithmeticPins 的 monkeypatch 绝对算术钉收口; 共享 c0 预备面
(reset_index/首行语义/ref_idx=0 下边界) 由 TestSharedPrepPins 收口。
已知夹具世界缺口 (如实披露, 不钉): collect 循环内 _counterfactual_strength
sidechannel 的实参序不可由 slot hermetic 测试到达 (需全量 panel 世界);
由宿主真实数据冒烟覆盖 (20260915 报告 1890 事件 0 uncomputable — 实参换位
即全部 uncomputable, 当场可见)。
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


class TestRankerArithmeticPins:
    """R219 Op2: ranker 算术绝对值钉 — 公式漂移在此无所遁形.

    等价性测试 (cf == detect) 对公式变异是恒真镜面: 两侧消费同一实现, 同变
    即同真。唯一能杀死权重漂移/因子换位/cap 抬升/energy 边界变异的是与实现
    独立的精确算术期望 — monkeypatch 五因子 helper 为互异常量后手算期望
    (R13 教训: 数值断言的 fixture 必须非对称)。
    """

    def _patched_components(
        self, monkeypatch, board=0.9, low_vol=0.5, position=0.3,
        squeeze=1.0, volume=0.25, range_=0.75, streak=2,
    ):
        import src.screening.offensive.setups.btst_breakout as bb

        monkeypatch.setattr(bb, "_board_quality_score", lambda ticker: board)
        monkeypatch.setattr(bb, "_compute_low_vol_score", lambda prices, idx: low_vol)
        monkeypatch.setattr(
            bb, "_compute_trend_vol_scores",
            lambda pre, prices, idx: (position, squeeze),
        )
        monkeypatch.setattr(bb, "_compute_volume_score", lambda prices, idx: volume)
        monkeypatch.setattr(bb, "_compute_range_score", lambda prices, idx: range_)
        monkeypatch.setattr(
            bb, "_compute_limit_up_streak", lambda prices, idx, lp: streak
        )
        prices = _base_prices()
        prepared = bb._prepare_trigger_frame(prices)
        idx = bb._find_trigger_index(prepared, _today(prices))
        return bb._strength_components(
            prepared, idx, idx - 5, "X", 9.5, _today(prices)
        )

    def test_distinct_components_flow_through_unchanged(self, monkeypatch):
        """因子换位变异即死: 返回 dict 的每个分量必须等于其专属 helper 值."""
        comps = self._patched_components(monkeypatch)
        assert comps["board_score"] == pytest.approx(0.9)
        assert comps["low_vol_score"] == pytest.approx(0.5)
        assert comps["position_score"] == pytest.approx(0.3)  # 换位不改变加权和, 但改变分量
        assert comps["squeeze_score"] == pytest.approx(1.0)
        assert comps["volume_score"] == pytest.approx(0.25)
        assert comps["range_score"] == pytest.approx(0.75)
        assert comps["weekday_score"] in (0.0, 1.0)
        assert comps["streak"] == 2

    def test_exact_weighted_arithmetic_no_bonus(self, monkeypatch):
        """权重漂移变异即死: 0.20×5 求和精确手算 (squeeze=1.0 但 low_vol=0.5 → 零 bonus)."""
        comps = self._patched_components(monkeypatch)
        expected = 0.20 * (0.9 + 0.5 + 1.0 + 0.25 + 0.75)
        assert comps["energy_bonus"] == 0.0
        assert comps["strength"] == pytest.approx(expected)

    def test_energy_bonus_boundary_inclusive_at_075(self, monkeypatch):
        """energy 边界变异 (> 0.75) 即死: low_vol 恰 0.75 须发满 0.08, 0.74 不发."""
        at = self._patched_components(monkeypatch, low_vol=0.75)
        assert at["energy_bonus"] == pytest.approx(0.08)
        assert at["strength"] == pytest.approx(
            min(1.0, 0.20 * (0.9 + 0.75 + 1.0 + 0.25 + 0.75) + 0.08)
        )
        below = self._patched_components(monkeypatch, low_vol=0.74)
        assert below["energy_bonus"] == 0.0

    def test_energy_bonus_requires_full_squeeze(self, monkeypatch):
        """squeeze 非满值不发 bonus (Finding A 纪律: 0.5 中性不算完整弹簧释放)."""
        comps = self._patched_components(monkeypatch, squeeze=0.99, low_vol=1.0)
        assert comps["energy_bonus"] == 0.0

    def test_strength_capped_at_one(self, monkeypatch):
        """cap 抬升变异即死: 全满因子 + bonus = 1.08, 契约上限 1.0."""
        comps = self._patched_components(
            monkeypatch, board=1.0, low_vol=1.0, squeeze=1.0,
            volume=1.0, range_=1.0,
        )
        assert comps["energy_bonus"] == pytest.approx(0.08)
        assert comps["strength"] == pytest.approx(1.0)


class TestSharedPrepPins:
    """R219 Op2: 共享 c0 预备面探针收口 (reset_index 剥除 / 首行语义 / ref_idx=0)."""

    def test_non_default_index_frame_detect_and_counterfactual_agree(self):
        """reset_index 剥除变异即死: 非零起点 index 帧必须正常检测且两读面一致."""
        prices = _base_prices().set_axis(range(100, 100 + len(_base_prices())))
        today = _today(prices)
        result = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": _flow_records(prices),
             "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert result.hit is True
        cf = counterfactual_trigger_strength(prices, today, "X")
        assert cf is not None
        assert cf == pytest.approx(result.trigger_strength)

    def test_duplicate_trigger_rows_bind_first(self):
        """index[-1] 变异即死: 同 date_str 重复行, 触发语义绑定首行 (原 detect 契约)."""
        prices = _base_prices()
        dup = prices.iloc[[-1]].copy()
        dup["close"] = 99.0
        dup["pct_change"] = 10.0
        framed = pd.concat([prices, dup], ignore_index=True)
        today = _today(framed)
        cf_full = counterfactual_trigger_strength(framed, today, "X")
        cf_first_only = counterfactual_trigger_strength(
            framed.iloc[:-1], today, "X"
        )
        assert cf_full is not None and cf_first_only is not None
        assert cf_full == pytest.approx(cf_first_only)
        assert cf_full > 0.0

    def test_ref_idx_zero_is_computable_not_none(self):
        """ref_idx <= 0 变异即死: 6 行历史 → ref_idx=0 是合法下边界, 与 detect 同门可达."""
        prices = _base_prices(n=6)
        today = _today(prices)
        cf = counterfactual_trigger_strength(prices, today, "X")
        assert cf is not None and 0.0 < cf <= 1.0
        blocked = BtstBreakoutSetup().detect(
            "X", today,
            {"prices": prices, "fund_flow_records": [],
             "industry_day_pct": 3.0, "regime": "normal"},
        )
        assert blocked.miss_stage == "c2_flow_missing"
