"""Setup-1 BTST 突破触发逻辑测试。"""

from __future__ import annotations

import pandas as pd

from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.data.fund_flow_store import FundFlowRecord


def _ctx(prices, fund_flow_records=None, industry_pct=3.0, regime="normal"):
    return {
        "prices": prices,
        "fund_flow_records": fund_flow_records or [],
        "industry_day_pct": industry_pct,  # 行业当日涨幅
        "regime": regime,
    }


def _prices_with_limit_up_today():
    """今天涨停 (+10%), 主力净流入强, 行业涨 3%.

    条件4: 涨停日/5日前 涨幅 ≤5%. 5日前 close=10.5, 今日 11.0 → 涨幅 4.76% (≤5% ✅).
    """
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [11.0]
    closes[-6] = 10.5  # 5 日前 close 设 10.5 (今日 11.0 → 涨幅 4.76%, 过 ≤5% 门槛)
    pct = [0.0] * 20 + [0.0, 10.0]
    return pd.DataFrame({"date": dates, "close": closes, "open": closes, "high": closes, "low": closes, "pct_change": pct})


def test_hit_when_all_conditions_met():
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is True
    assert result.trigger_strength > 0
    assert "跌破" in result.invalidation_condition or "破" in result.invalidation_condition


def test_hit_when_pre_limit_up_5d_runup_is_flat():
    """涨停前 5 日横盘、今日首板涨停应命中条件4.

    条件4的语义是"涨停前5日累计涨幅≤5%", 不应把今天涨停本身计入追高过滤。
    """
    prices = _prices_with_limit_up_today()
    prices.loc[prices.index[-6], "close"] = 10.0
    prices.loc[prices.index[-2], "close"] = 10.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))

    result = BtstBreakoutSetup().detect(
        "X",
        today,
        _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0),
    )

    assert result.hit is True
    assert result.metadata["pre_5d_runup_pct"] == 0.0


def test_miss_when_no_limit_up():
    """今天没涨停 → 不命中。"""
    prices = _prices_with_limit_up_today()
    prices.loc[prices.index[-1], "pct_change"] = 2.0  # 改成 +2% (没涨停)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    ctx = _ctx(prices, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_industry_weak():
    """涨停 + 主力强, 但行业涨幅 < 2% → 不命中 (无板块效应)。"""
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    ctx = _ctx(prices, fund_flow_records=recs, industry_pct=1.0)  # 行业弱
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_main_inflow_weak():
    """涨停 + 行业强, 但主力净流入 < 20 日均值 → 不命中。"""
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=100_000, main_net_pct=0.5)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=200_000, main_net_pct=1.0))
    ctx = _ctx(prices, fund_flow_records=recs + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_pre_runup_too_high():
    """涨停 + 主力强 + 行业强, 但涨停前5日已涨 >5% (追高) → 不命中 (条件4).

    数据驱动条件: 涨停前涨幅越大后续越弱. ≤5% 保留, >5% 过滤.
    """
    prices = _prices_with_limit_up_today()
    # 把前5日 close 从 10.0 改成 9.0 (今日涨停 11.0, 前5日 9.0 → 涨幅 22% > 5%)
    prices.loc[prices.index[-6], "close"] = 9.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=[recs[0]] + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False  # 前5日涨幅 22% > 5% 阈值


def test_hit_when_oversold_then_limit_up():
    """超跌后首板涨停 (前5日跌后涨停) → 命中, 且 strength 应较高 (反转深度加分).

    数据验证: 前5日<0% 的涨停 T+5 E[r]=+4.17%, 胜率61%, 是最强子集.
    """
    prices = _prices_with_limit_up_today()
    # 前5日 close 设为 12.0 (今日涨停 11.0, 前5日 12.0 → 跌幅 -8.3%)
    prices.loc[prices.index[-6], "close"] = 12.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is True
    assert result.trigger_strength > 0
    # metadata 应含 pre_5d_runup_pct
    assert "pre_5d_runup_pct" in result.metadata
    assert result.metadata["pre_5d_runup_pct"] < 0  # 负值 (超跌)


def test_natural_horizon_is_10_not_3():
    """回归: natural_horizon 必须是 10, 不是文档原假设的 3.

    全池 execution-adjusted 回测 (2020-2026, n=5374) 显示 BTST 的 alpha 在长周期:
      T+1 凸性 0.91 (负凸性), T+3 凸性 1.17 (< 1.5 准入门槛),
      T+10 凸性 1.53 (首次过门槛), T+20 凸性 1.70.
    文档 §3.1 "T+1~T+3 最强" 的预假设被数据推翻. known_distributions.BTST_BREAKOUT_T10
    和 --daily-action 都用 T+10 口径; natural_horizon 与之一致才能让 evaluate_setup
    的 FDR p-value (H0: expected_return=0) 算在正确的 horizon 上.

    曾有 bug: natural_horizon=3 导致 evaluate_setup 算 T+3 收益 (均值 +0.53%, 弱)
    却被当成 setup 的代表分布, 与 known_distributions 的 T+10 (均值 +2.57%) 矛盾,
    使 FDR 误判 IS 段不显著.
    """
    assert BtstBreakoutSetup().natural_horizon == 10
