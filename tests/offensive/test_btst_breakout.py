"""Setup-1 BTST 突破触发逻辑测试。"""

from __future__ import annotations

from datetime import datetime as _dt

import pandas as pd

from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.data.fund_flow_store import FundFlowRecord


def _ctx(prices, fund_flow_records=None, industry_pct=3.0, regime="normal"):
    return {
        "prices": prices,
        "fund_flow_records": fund_flow_records or [],
        "industry_day_pct": industry_pct,  # 行业当日涨幅 (None = 数据未加载)
        "regime": regime,
    }


def _sync_pct_change(prices):
    """让 pct_change 与 close 链一致 (检测条件现按 pct_change 链复合窗口收益)."""
    prices = prices.copy()
    prices["pct_change"] = prices["close"].pct_change().fillna(0.0) * 100.0
    return prices


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
    prices = _sync_pct_change(prices)
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
    prices = _sync_pct_change(prices)
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
    """回归: natural_horizon 必须是 8 (T+8 mean 最优, 避免 T+10 回吐).

    全池 execution-adjusted 回测 (2020-2026, n=5374) 显示 BTST 的 alpha 在长周期:
      T+1 凸性 0.91 (负凸性), T+3 凸性 1.17 (< 1.5 准入门槛),
      T+10 凸性 1.53 (首次过门槛), T+20 凸性 1.70.
    paper_trading_backtest 91 笔 T+k 曲线 (2026) 显示:
      T+7 median 最优 +5.34%, T+8 mean 最优 +6.33%, T+10 回吐到 median +3.43%.
    从 T+10 缩短到 T+8: 避免 T+9/T+10 给回吐, 锁定更高 mean 和 Sharpe.
    """
    assert BtstBreakoutSetup().natural_horizon == 8


def _prices_with_20pct_limit_up_today():
    """科创/创业 20% 板涨停: 今日 +20% (真涨停), 主力强, 行业涨 3%.

    用与 _prices_with_limit_up_today 同结构, 但涨停幅度改成 20%.
    """
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [12.0]  # +20% (10→12)
    closes[-6] = 11.5  # 5 日前 close=11.5, 今日 12.0 → 涨幅 4.35% (≤5% ✅)
    pct = [0.0] * 20 + [0.0, 20.0]
    return pd.DataFrame({"date": dates, "close": closes, "open": closes, "high": closes, "low": closes, "pct_change": pct})


def test_hit_when_star_market_20pct_limit_up():
    """科创板 (688) +20% 真涨停 → 命中 (板块自适应阈值 19.5%)."""
    prices = _prices_with_20pct_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="688037", date=today, close=12.0, pct_change=20.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="688037", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("688037", today, ctx)
    assert result.hit is True


def test_miss_when_star_market_15pct_not_limit_up():
    """科创板 +15% 是大涨但非涨停 (20% 板涨停要 ≥19.5%) → 不命中.

    Bug A 回归: 旧固定 _LIMIT_UP_PCT=9.5 会把这种非涨停大涨误判为涨停,
    污染「涨停突破」语义. 板块自适应修复后必须正确 miss.
    """
    prices = _prices_with_limit_up_today()
    # 改成 +15% (主板涨停, 但科创/创业非涨停)
    prices.loc[prices.index[-1], "pct_change"] = 15.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="688037", date=today, close=11.0, pct_change=15.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="688037", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("688037", today, ctx)
    assert result.hit is False, "688 +15% 非涨停 (20% 板), 不应命中 BTST"


def test_miss_when_chinext_15pct_not_limit_up():
    """创业板 (300) +15% 非涨停 → 不命中 (同 test_miss_when_star_market_15pct_not_limit_up)."""
    prices = _prices_with_limit_up_today()
    prices.loc[prices.index[-1], "pct_change"] = 15.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="300903", date=today, close=11.0, pct_change=15.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="300903", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("300903", today, ctx)
    assert result.hit is False


def test_degraded_when_fund_flow_history_insufficient():
    """Bug B: 资金流历史 < 5 日 → 命中但 degraded=True (诚实降级).

    当前 fund_flow_cache 普遍浅 (<5 天), 绝大多数 BTST 命中会是 degraded.
    旧逻辑: 历史不足时静默跳过均值检查 (条件2 退化为只验 today_flow>0),
    无任何标识 → 下游误以为命中了完整 4 条件 setup. 现在必须 degraded=True 披露.
    """
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    # 只有今日 1 条资金流记录 (历史 0 条 < 5)
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    ctx = _ctx(prices, fund_flow_records=recs_today, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True
    assert result.degraded is True, "资金流历史 <5 日应标 degraded"
    assert "历史不足" in result.degradation_reason or "历史数据不足" in result.degradation_reason


def test_not_degraded_when_fund_flow_history_sufficient():
    """资金流历史 ≥ 5 日且 today_flow > 均值 → degraded=False (完整 4 条件命中)."""
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):  # 20 条历史
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True
    assert result.degraded is False


def test_industry_data_none_degrades_not_kills():
    """Bug fix: industry_day_pct=None (数据管道断裂) 时应 degraded, 不应静默 miss.

    旧实现: daily_action 把加载失败映射为 industry_pct=0.0 → 0.0 < 2.0 → 全部 BTST miss.
    用户看到"今日无信号", 实际是行业缓存缺失/import 失败. 修正后: None 时跳过行业
    过滤但标 degraded=True, 让 operator 知道行业条件未验证.

    场景: 涨停 + 主力强 + 前5日涨幅 OK, 但行业数据未加载 (industry_day_pct=None).
    """
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    # industry_day_pct=None: 模拟 _load_industry_day_pct_by_ticker 返回空字典
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=None)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True, "行业数据缺失时 BTST 仍应命中 (降级, 不静默全杀)"
    assert result.degraded is True, "行业数据缺失应标 degraded"
    assert "行业" in result.degradation_reason or "条件3" in result.degradation_reason


def test_industry_data_zero_still_misses():
    """有行业数据但涨幅为 0.0 → 正常 miss (行业未涨 = 无板块效应).

    区分: industry_day_pct=0.0 (有数据, 行业没涨) vs industry_day_pct=None (无数据).
    前者应正常 miss, 后者应 degraded hit. 这保证降级只发生在数据缺失时, 不放宽过滤.
    """
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=0.0)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is False, "行业涨幅 0.0 < 2.0 应正常 miss (非降级)"


def test_energy_bonus_not_granted_when_squeeze_neutral():
    """Finding A 回归: energy_bonus 只在 position+squeeze 同时=1.0 (完整弹簧释放) 时发放.

    docstring(:348) 明确 "position+squeeze 同时=1". 旧代码 ``>= 0.5`` 把 squeeze=0.5
    (中性/数据不足: 前段波动率为 0 → prior_atr<=0 → _compute_squeeze_score 回退 0.5)
    的票也算"完整弹簧释放"而发 +0.08 奖金 → 与文档矛盾, 且把阶段证据不足的票抬过
    ``_MIN_TRIGGER_STRENGTH=0.50`` 选股门.

    构造 (22 日): 前 18 日全平 10.0; 第 18/19 日 12.0; 第 20 日 close=10/high=12
    (制造一根 range bar); 第 21 日涨停 11.0. 由此得:
      - position_score = 1.0  (T-1 close=10 在 5 日 [10,10,12,12,10] 下半区)
      - squeeze_score  = 0.5  (前 17 日全平 → prior_atr=0 → 回退 0.5)
    断言 trigger_strength 不含 +0.08 bonus (即等于无 bonus 的公式值).
    """
    from src.screening.offensive.setups.btst_breakout import (
        _board_quality_score,
        _compute_trend_vol_scores,
        _compute_volume_score,
    )

    dates = pd.bdate_range("2026-06-01", periods=22)
    close = [10.0] * 18 + [12.0, 12.0, 10.0, 11.0]  # idx18,19=12; idx20=10; idx21=11 涨停
    high = [10.0] * 18 + [12.0, 12.0, 12.0, 11.0]  # idx20 high=12 制造 range bar
    low = [10.0] * 18 + [12.0, 12.0, 10.0, 11.0]  # idx20 low=10
    pct = [0.0] * 21 + [10.0]
    vol = [1000.0] * 22
    prices = pd.DataFrame(
        {"date": dates, "close": close, "high": high, "low": low, "open": list(close), "pct_change": pct, "volume": vol}
    )

    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)

    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True

    # 复现数据构造达到的因子值 (sanity) + strength 公式 (不含 bonus).
    trigger_idx = len(prices) - 1
    pre_window = prices.iloc[trigger_idx - 5 : trigger_idx]
    position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)
    assert position_score == 1.0, "构造应使 position=1.0 (T-1 在 5 日下半区)"
    assert squeeze_score == 0.5, "构造应使 squeeze=0.5 (前段全平 prior_atr=0 回退)"

    weekday_score = 1.0 if _dt.strptime(today, "%Y%m%d").weekday() >= 2 else 0.0
    board_score = _board_quality_score("X")
    volume_score = _compute_volume_score(prices, trigger_idx)
    expected_no_bonus = min(
        1.0,
        0.20 * weekday_score + 0.20 * board_score + 0.20 * position_score + 0.20 * squeeze_score + 0.20 * volume_score,
    )
    # squeeze=0.5 (中性) 绝不可触发 "完整弹簧释放" bonus.
    assert abs(result.trigger_strength - expected_no_bonus) < 1e-9, (
        f"squeeze=0.5 时不应发 energy_bonus: got {result.trigger_strength}, "
        f"expected(no bonus) {expected_no_bonus}"
    )
