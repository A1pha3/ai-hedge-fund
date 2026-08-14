"""Setup-1 BTST 突破触发逻辑测试。"""

from __future__ import annotations

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


def test_industry_data_none_misses():
    """2026-08-14 严格化 (对抗性审查 P2): industry_day_pct=None (数据缺失) 应 miss.

    实证反转 2026-07-12 的降级放行: 全池 A/B (n=7097, 2025-07→2026-08, 条件1+4 池)
    显示行业数据缺失组 T+10 胜率 42.1%/均值 −0.75% (CI 显著为负, n=2838) —
    缺失即差票, 放行放进来的正是统计上最该砍的组. 与 capability 层
    (industry_data_missing → plan_eligible=False) 语义对齐.
    管道断裂可见性由 snapshot capability 层的 readiness block 披露保留.
    见 data/reports/gate_cond2_cond3_ab_20260814.json.
    """
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=None)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is False, "行业数据缺失应 miss (no_data 组 T+10 −0.75% 显著为负)"


def test_industry_data_zero_still_misses():
    """有行业数据但涨幅为 0.0 → 正常 miss (行业未涨 = 无板块效应).

    2026-08-14 起 industry_day_pct=0.0 (有数据没涨) 与 None (无数据) 同为 miss —
    前者因 <2.0 阈值, 后者因缺失组实证显著为负 (见 test_industry_data_none_misses).
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
    assert result.hit is False, "行业涨幅 0.0 < 2.0 应正常 miss"


def test_strength_components_exported_to_metadata():
    """因子审计契约 (2026-08-08): detect() 必须把 5 个 strength 分量导出到 metadata.

    研究/运行时同一函数: 因子审计器复核「现有分量是否仍在挣它的 0.20 权重」时,
    读的就是 detect() 实际用于打分的那组值, 不是另一份独立实现 → 消灭口径偏差.
    若此契约被破坏, 基于真实 detect-hit 的审计会失去对齐锚点.
    """
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0, main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True
    for key in ("weekday_score", "board_score", "position_score", "low_vol_score", "squeeze_score", "volume_score", "range_score", "energy_bonus"):
        assert key in result.metadata, f"metadata 缺 strength 分量 {key}"
    # 分量与 trigger_strength 自洽: weekday 已移出 (2026-08-09 Q1),
    # position 已移出 (2026-08-09 Q6, low_vol 替换, 双重计权本质解).
    # range 进 strength (2026-08-09 新一轮挖掘, 4→5 分量 0.25→0.20 重新归一化).
    # strength = min(1, 0.20*(board+low_vol+squeeze+volume+range) + energy_bonus)
    m = result.metadata
    expected = min(
        1.0,
        0.20 * (m["board_score"] + m["low_vol_score"] + m["squeeze_score"] + m["volume_score"] + m["range_score"]) + m["energy_bonus"],
    )
    assert abs(result.trigger_strength - expected) < 1e-9, (
        f"导出的分量应能重建 trigger_strength: {result.trigger_strength} vs {expected}")


def test_weekday_does_not_affect_trigger_strength():
    """回归守卫 (2026-08-09, factor_audit Q1): 星期几不再影响 trigger_strength.

    weekday_score 当初凭 n=133 单 regime 样本「Wed-Fri 78% vs Mon-Tue 51%」给 0.20 权重.
    全量复核 (factor_audit, 21232 信号日) 无区分度 — E[r] 反号、跨窗 H1 反 H2 正、
    Wilson 未分离 → 移出 strength, 保留 metadata 观测 (day-of-week 效应是真信息,
    只是不配权重). 见 data/reports/factor_audit_decision_pack_2026-08-08.md (Q1).

    锁语义: 同一构造、仅改变信号日的星期, trigger_strength 必须完全相同.
    用两组日历 (触发日分别落在周一 vs 周五) 跑 detect, 断言 strength 相等.
    """
    def _run(anchor: str) -> float:
        dates = pd.bdate_range(anchor, periods=22)
        closes = [10.0] * 21 + [11.0]
        closes[-6] = 10.5  # pre_runup ≤5%
        pct = [0.0] * 20 + [0.0, 10.0]
        prices = pd.DataFrame({"date": dates, "close": closes, "open": closes, "high": closes,
                               "low": closes, "pct_change": pct, "volume": [1000.0] * 22})
        today = prices.iloc[-1]["date"].strftime("%Y%m%d")
        recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                                     main_net_inflow=5_000_000, main_net_pct=8.0)]
        old_recs = []
        for i in range(1, 21):
            d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
            old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                           main_net_inflow=100_000, main_net_pct=0.5))
        ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
        r = BtstBreakoutSetup().detect("X", today, ctx)
        assert r.hit is True
        return r.trigger_strength

    # 触发日分别落在周二 (weekday_score=0, anchor 06-01) vs 周五 (weekday_score=1, anchor 06-04).
    low = _run("2026-06-01")   # 触发日周二, weekday_score=0
    high = _run("2026-06-04")  # 触发日周五, weekday_score=1
    assert abs(low - high) < 1e-9, (
        f"weekday 不应影响 strength: weekday=0 {low} vs weekday=1 {high}")


def test_low_vol_score_inverted_mapping():
    """锚定 2026-08-09 低波动因子 (geometry Q6) 的单调映射: 低波→1.0, 高波→0.0.

    阈值锚定池内实测分布 (q6_double_count_ab 五分位: 低波区 E[r] 最优, 高波区最差),
    是数据驱动常量, 将来会被定期复核. 构造: 涨停前 20 日的日收益波动率.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_low_vol_score

    def _mk(daily_pct: float) -> pd.DataFrame:
        # 前 20 日交替 ±daily_pct (制造指定波动率), 末日涨停
        n = 21
        pcts = [daily_pct if i % 2 == 0 else -daily_pct for i in range(n - 1)] + [10.0]
        closes = [10.0] * n
        return pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n), "close": closes,
                             "open": closes, "high": closes, "low": closes, "pct_change": pcts})

    idx = 20
    assert _compute_low_vol_score(_mk(0.5), idx) == 1.0   # rv20≈0.5% ≤ 1.5 → 满值
    assert _compute_low_vol_score(_mk(1.0), idx) == 1.0   # rv20≈1.0% ≤ 1.5 → 满值
    assert _compute_low_vol_score(_mk(6.0), idx) == 0.0   # rv20≈6.0% ≥ 4.5 → 0
    # 中间线性过渡: 中等波动率落在 (0,1) 且低波 > 高波 (单调递减)
    mid = _compute_low_vol_score(_mk(3.0), idx)
    assert 0.0 < mid < 1.0, f"rv≈3% 应落线性过渡区, got {mid}"
    assert _compute_low_vol_score(_mk(1.0), idx) > mid > _compute_low_vol_score(_mk(6.0), idx)


def test_low_vol_score_filters_non_finite_returns():
    """回归守卫 (2026-08-09, 对抗审查发现): pct_change 窗口含 ±inf 时不得返回 NaN.

    仅滤 NaN 不滤 inf 时, np.std(含inf)→NaN → rv20 比较全 False → return NaN →
    外层 min(1.0, NaN)=1.0 把 NaN 洗成满分过闸 (Python min 保留首参). 同列消费方
    chained_return_pct 用 math.isfinite 硬ening — 此处必须同样滤非有限值.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_low_vol_score

    n = 25
    for bad in (float("inf"), float("-inf"), float("nan")):
        pcts = [0.0] * 20 + [bad, 1.0, -1.0, 1.0, 10.0]
        df = pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n), "close": [10.0] * n,
                           "open": [10.0] * n, "high": [10.0] * n, "low": [10.0] * n, "pct_change": pcts})
        v = _compute_low_vol_score(df, n - 1)
        assert v == v, f"含 {bad} 窗口应滤掉而非返回 NaN, got {v}"
        assert 0.0 <= v <= 1.0, f"归一化契约: 须在 [0,1], got {v}"


def test_range_score_inverted_u_mapping():
    """锚定 2026-08-09 盘中振幅因子 (新一轮挖掘) 的倒 U 映射.

    阈值由全 universe 审计 (21232 信号日, exec-adjusted, split-half 跨窗一致) 定,
    是数据驱动常量 — 将来会被定期 factor_audit 保质期复核 (同 streak/volume 教训).
    倒 U: 一字锁死板 (<4%, 买不到) 与 盘中崩 (>=14%) 两端皆低, 健康博弈甜区 (6-11%) 满值.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_range_score

    def _mk(hi: float, lo: float) -> pd.DataFrame:
        # idx21 = trigger; prev_close = close[20] = 10.0; range = (hi-lo)/10
        n = 22
        close = [10.0] * 21 + [11.0]
        high = [10.0] * 21 + [hi]
        low = [10.0] * 21 + [lo]
        return pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n), "close": close,
                             "open": close, "high": high, "low": low,
                             "pct_change": [0.0] * 21 + [10.0]})

    idx = 21
    assert _compute_range_score(_mk(10.0, 10.0), idx) == 0.2  # range 0   一字锁死板
    assert _compute_range_score(_mk(10.4, 10.0), idx) == 0.4  # range 4%  [0.04,0.06)
    assert _compute_range_score(_mk(10.8, 10.0), idx) == 1.0  # range 8%  甜区 [0.06,0.11)
    assert _compute_range_score(_mk(11.0, 10.0), idx) == 1.0  # range 10% 甜区上沿 (<0.11)
    assert _compute_range_score(_mk(11.2, 10.0), idx) == 0.4  # range 12% [0.11,0.14)
    assert _compute_range_score(_mk(11.5, 10.0), idx) == 0.2  # range 15% 盘中崩 (>=0.14)
    # 边界: r<0.04 → 0.2; 0.0399 锁死侧
    assert _compute_range_score(_mk(10.399, 10.0), idx) == 0.2
    # 倒 U 形状: 甜区满值严格高于两端 (经济意义锚定)
    sweet = _compute_range_score(_mk(10.8, 10.0), idx)
    assert sweet > _compute_range_score(_mk(10.0, 10.0), idx), "甜区应优于一字锁死板"
    assert sweet > _compute_range_score(_mk(11.5, 10.0), idx), "甜区应优于盘中崩"
    # hi<lo (数据错) → 0.5 中性回退
    assert _compute_range_score(_mk(10.0, 11.0), idx) == 0.5


def test_range_score_filters_non_finite():
    """回归守卫 (2026-08-09): high/low/prev_close 含 ±inf/nan 时回退 0.5, 不返回 NaN.

    与 _compute_low_vol_score 同族纪律 (对抗审查发现的 inf 家族): 非有限值漏进比较会
    产生 NaN → min(1.0, NaN)=1.0 把 NaN 洗成满分过闸. range 同样须滤非有限值.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_range_score

    n = 22
    base_close = [10.0] * 21 + [11.0]
    for bad_col, bad_val in (("high", float("inf")), ("low", float("-inf")),
                             ("high", float("nan")), ("close", float("nan"))):
        close = list(base_close)
        high = [10.0] * 21 + [11.5]
        low = [10.0] * 21 + [10.0]
        if bad_col == "high":
            high = [10.0] * 21 + [bad_val]
        elif bad_col == "low":
            low = [10.0] * 21 + [bad_val]
        else:  # close (污染前收 prev_close)
            close[20] = bad_val
        df = pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n), "close": close,
                           "open": close, "high": high, "low": low,
                           "pct_change": [0.0] * 21 + [10.0]})
        v = _compute_range_score(df, n - 1)
        assert v == v, f"{bad_col}={bad_val} 应回退非 NaN, got {v}"
        assert v == 0.5, f"{bad_col}={bad_val} 应回退 0.5 中性, got {v}"
    # 数据不足: 无 high/low 列 → 0.5
    df_nocol = pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n),
                             "close": base_close, "pct_change": [0.0] * 21 + [10.0]})
    assert _compute_range_score(df_nocol, n - 1) == 0.5
    # trigger_idx<1 (无前收) → 0.5
    df_first = pd.DataFrame({"close": [11.0], "high": [11.5], "low": [10.0]})
    assert _compute_range_score(df_first, 0) == 0.5


def test_position_does_not_affect_trigger_strength():
    """回归守卫 (2026-08-09, geometry Q6): position_score 不再影响 trigger_strength.

    正交性问责发现 position 与条件4 pre_runup≤8% 同源 (ρ=-0.756), 「防追高」被双重计权.
    本质解 = 换正交轴 (low_vol), 非降权 (复印件调小声还是复印件). position 保留 metadata
    观测但不进 strength. 锁语义: 同一构造仅改 5 日窗口位置 (position 0 vs 1), strength 不变.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_trend_vol_scores

    def _run(low_pos: bool) -> tuple[float, float, float]:
        # 22 日, idx21 涨停 11.0. 用 idx16-20 (5 日窗口) 形状分处 position 两极, 同时保 pre_runup≤8%:
        #   low_pos=True  → T-1 在 5 日窗口下半区 → position=1.0 (收盘价从高点回落到低位)
        #   low_pos=False → T-1 在 5 日窗口上半区 → position=0.0 (收盘价处于高位)
        # 两构造涨停前 20 日 pct_change 窗口的全平段一致 → low_vol 相同 (隔离 position 单变量).
        dates = pd.bdate_range("2026-06-01", periods=22)
        if low_pos:
            # idx16-20: 先抬后压, T-1(idx20) 落低位. pre_runup close[20]/close[16]=10.0/10.0=0% ≤8%.
            closes = [10.0] * 16 + [10.0, 10.6, 10.6, 10.6, 10.0, 11.0]
        else:
            # idx16-20: 先压后抬, T-1(idx20) 在高位. pre_runup close[20]/close[16]=10.6/10.0=+6% ≤8%.
            closes = [10.0] * 16 + [10.0, 10.0, 10.0, 10.0, 10.6, 11.0]
        pct = [0.0] * 21 + [10.0]
        prices = pd.DataFrame({"date": dates, "close": closes, "open": closes, "high": closes,
                               "low": closes, "pct_change": pct, "volume": [1000.0] * 22})
        today = prices.iloc[-1]["date"].strftime("%Y%m%d")
        recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                                     main_net_inflow=5_000_000, main_net_pct=8.0)]
        old_recs = []
        for i in range(1, 21):
            d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
            old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                           main_net_inflow=100_000, main_net_pct=0.5))
        ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
        r = BtstBreakoutSetup().detect("X", today, ctx)
        assert r.hit is True
        trigger_idx = len(prices) - 1
        pre_window = prices.iloc[trigger_idx - 5: trigger_idx]
        pos, _sq = _compute_trend_vol_scores(pre_window, prices, trigger_idx)
        return r.trigger_strength, pos, r.metadata["low_vol_score"]

    s_low_pos, pos_low, lv_low = _run(low_pos=True)    # position=1.0
    s_high_pos, pos_high, lv_high = _run(low_pos=False)  # position=0.0
    assert pos_low == 1.0 and pos_high == 0.0, f"构造应分处 position 两极: {pos_low} vs {pos_high}"
    # position 相反 → 若 position 仍进 strength 必不等; 相等即证明 position 已被 low_vol 替换.
    assert abs(s_low_pos - s_high_pos) < 1e-9, (
        f"position 不应影响 strength: position=1 {s_low_pos} vs position=0 {s_high_pos}")


def test_volume_score_recalibrated_inverted_u_mapping():
    """锚定 2026-08-09 连续重标定 (factor_audit Q2) 的倒 U 映射.

    阈值由全量复核 (n=17994, split-half 跨窗一致) 定, 是数据驱动常量 — 将来会被
    定期复核, 此测试锚定当前值防无声漂移. 构造: 今日 volume / 前20日均量 = 指定比率.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_volume_score

    def _mk(ratio: float) -> pd.DataFrame:
        n = 25
        vols = [1000.0] * (n - 1) + [1000.0 * ratio]  # 前 20 日均 1000, 今日 = ratio×
        closes = [10.0] * n
        return pd.DataFrame({"date": pd.bdate_range("2026-06-01", periods=n), "close": closes,
                             "open": closes, "high": closes, "low": closes, "volume": vols})

    idx = 24  # 今日 (最后一天)
    assert _compute_volume_score(_mk(0.3), idx) == 0.0   # 极度缩量
    assert _compute_volume_score(_mk(0.6), idx) == 0.4   # 缩量偏弱
    assert _compute_volume_score(_mk(0.8), idx) == 1.0   # 温和放量 (平台)
    assert _compute_volume_score(_mk(1.2), idx) == 1.0   # 温和放量
    assert _compute_volume_score(_mk(1.8), idx) == 1.0   # 温和放量
    assert _compute_volume_score(_mk(2.5), idx) == 0.6   # 放量尚可
    assert _compute_volume_score(_mk(4.0), idx) == 0.2   # 过度换手
    # 单调性: 平台 (1.0) 高于两端, 且 >2.0 低于平台 (倒 U 两端压)
    assert _compute_volume_score(_mk(1.2), idx) > _compute_volume_score(_mk(0.3), idx)
    assert _compute_volume_score(_mk(1.2), idx) > _compute_volume_score(_mk(4.0), idx)


def test_board_quality_score_q3_merge_mapping():
    """Q3: 002/300/301 与 688/60x 合并到 0.95 (审计口径 Wilson 打平); 000/001 = 0.0.

    锚定合并方向 = 降 (非升): 旧 002/300 = 1.0 → 0.95. 降方向在池内挡出 823 票
    E[r]=-1.067% 的负 EV 边缘票 (其他分量弱、靠 board 满值勉强入池), 升则放入负 EV.
    二值化后无 1.0 分量.
    """
    from src.screening.offensive.setups.btst_breakout import _board_quality_score

    assert _board_quality_score("002530") == 0.95  # 中小板 (旧 1.0, Q3 降)
    assert _board_quality_score("300724") == 0.95  # 创业板 (旧 1.0, Q3 降)
    assert _board_quality_score("301088") == 0.95  # 创业板 (旧 1.0, Q3 降)
    assert _board_quality_score("688981") == 0.95  # 科创板
    assert _board_quality_score("600519") == 0.95  # 沪市主板
    assert _board_quality_score("000001") == 0.0  # 深市主板 (审计显著最差)
    assert _board_quality_score("001872") == 0.0  # 深市主板
    # 二值化: 不再有 1.0 分量
    assert _board_quality_score("002530") != 1.0


def test_compute_limit_up_streak_counts_consecutive_limit_ups():
    """连板数 helper: 从 trigger 日向前数连续涨停日 (含 trigger 日).

    首板=1, 2连板=2, 3连板=3; 中途断开 (pct<阈值) 即停.
    """
    from src.screening.offensive.setups.btst_breakout import _compute_limit_up_streak

    def _df(pcts):
        n = len(pcts)
        return pd.DataFrame({
            "date": pd.bdate_range("2026-06-01", periods=n),
            "close": [10.0] * n,
            "pct_change": pcts,
        })

    # 首板: 仅 trigger 日涨停
    assert _compute_limit_up_streak(_df([0.0] * 12 + [10.0]), 12, 9.5) == 1
    # 2连板: trigger + 前一日涨停
    assert _compute_limit_up_streak(_df([0.0] * 10 + [10.0, 10.0]), 11, 9.5) == 2
    # 3连板
    assert _compute_limit_up_streak(_df([0.0] * 9 + [10.0, 10.0, 10.0]), 11, 9.5) == 3
    # 断开: trigger 前 2 日涨停但前 1 日非涨停 → streak=1
    assert _compute_limit_up_streak(_df([0.0] * 9 + [10.0, 0.0, 10.0]), 11, 9.5) == 1
    # 20% 板 (科创/创业) 用 19.5 阈值: +10% 不算涨停
    assert _compute_limit_up_streak(_df([0.0] * 10 + [10.0, 20.0]), 11, 19.5) == 1
    assert _compute_limit_up_streak(_df([0.0] * 10 + [20.0, 20.0]), 11, 19.5) == 2


def test_no_streak_bonus_for_two_consecutive_limit_ups():
    """回归守卫 (2026-08-08): 2连板不再给 streak_bonus — 因子正当性已反转.

    streak_bonus=0.04 当初 (7/19) 凭 9497 样本「2连板 WR48.0% > 首板 45.5%」落地.
    但 2026-08-08 全量复核 (1442 票 / 21232 涨停信号日 / 至 2026-08-07) 双口径
    同向反转: 2连板 WR 39.0% vs 首板 43.3% (−4.25pp raw / −4.47pp exec-adjusted),
    E[r] 同步走弱. 因子前提不再成立 → 移除 streak_bonus, streak 仅作 metadata 观测.
    见 data/reports/streak_factor_revalidation.json.

    构造 2连板且过 pre_runup≤8%: T-5 close 10.0 → 先跌至 9.5 (T-2) 再连两涨停
    (9.5→10.45→11.495). pre_runup close[T-1]/close[T-5] = 10.45/10.0 = +4.5%.
    """
    from src.screening.offensive.setups.btst_breakout import (
        _board_quality_score,
        _compute_trend_vol_scores,
        _compute_volume_score,
    )

    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 16 + [10.0, 9.6, 9.4, 9.5, 10.45, 11.495]  # idx16-21; idx20/21 连涨停
    prices = pd.DataFrame({
        "date": dates, "close": closes, "open": closes,
        "high": closes, "low": closes, "volume": [1000.0] * 22,
    })
    prices = _sync_pct_change(prices)  # pct_change 链一致; idx20/21 自动成 +10%

    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.495, pct_change=10.0,
                                 main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                       main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)

    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True
    # streak 仍被计算并暴露供观测, 但不再影响 trigger_strength.
    assert result.metadata["limit_up_streak"] == 2, "构造为 2连板 (T-1+T 均涨停)"

    # 用同一组 helper 重算 base 公式, 断言 strength == base (streak_bonus 已移除).
    # weekday 已移出 (Q1); position 已移出 (Q6, low_vol 替换). base = 0.20*(board+low_vol+squeeze+volume+range).
    trigger_idx = len(prices) - 1
    from src.screening.offensive.setups.btst_breakout import _compute_low_vol_score, _compute_range_score
    pre_window = prices.iloc[trigger_idx - 5 : trigger_idx]
    position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)
    low_vol_score = _compute_low_vol_score(prices, trigger_idx)
    board_score = _board_quality_score("X")
    volume_score = _compute_volume_score(prices, trigger_idx)
    range_score = _compute_range_score(prices, trigger_idx)
    # energy_bonus (squeeze=1 且 low_vol>=0.75) 按实测分量推导, 与生产一致
    energy = 0.08 if squeeze_score >= 1.0 and low_vol_score >= 0.75 else 0.0
    base = min(1.0, 0.20 * board_score + 0.20 * low_vol_score
               + 0.20 * squeeze_score + 0.20 * volume_score + 0.20 * range_score + energy)
    # streak=2 不再给 bonus
    assert abs(result.trigger_strength - base) < 1e-9, (
        f"streak_bonus 已移除, 2连板不应改变 strength: got {result.trigger_strength}, base {base}")


def test_no_streak_bonus_for_high_streaks():
    """3+连板不给 bonus (实测 WR22.7% 反转风险; 样本 n=22 小, 暂仅 neutral 不排除)."""
    from src.screening.offensive.setups.btst_breakout import (
        _board_quality_score,
        _compute_trend_vol_scores,
        _compute_volume_score,
    )

    dates = pd.bdate_range("2026-06-01", periods=22)
    # 3连板 (T-2/T-1/T 均涨停) 且 pre_runup≤8%: T-5=10.0 先跌至 8.8 (T-3) 再连三涨停;
    # pre_runup close[T-1]/close[T-5] = 10.648/10.0 = +6.48%; idx19/20/21 连涨停.
    closes = [10.0] * 16 + [10.0, 8.9, 8.8, 9.68, 10.648, 11.7128]
    prices = pd.DataFrame({
        "date": dates, "close": closes, "open": closes,
        "high": closes, "low": closes, "volume": [1000.0] * 22,
    })
    prices = _sync_pct_change(prices)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.7128, pct_change=10.0,
                                 main_net_inflow=5_000_000, main_net_pct=8.0)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                       main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is True, "构造应通过所有 BTST 过滤 (pre_runup +6.48%)"
    assert result.metadata["limit_up_streak"] == 3
    trigger_idx = len(prices) - 1
    from src.screening.offensive.setups.btst_breakout import _compute_low_vol_score, _compute_range_score
    pre_window = prices.iloc[trigger_idx - 5 : trigger_idx]
    position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)
    low_vol_score = _compute_low_vol_score(prices, trigger_idx)
    board_score = _board_quality_score("X")
    volume_score = _compute_volume_score(prices, trigger_idx)
    range_score = _compute_range_score(prices, trigger_idx)
    # weekday 已移出 (Q1); position 已移出 (Q6, low_vol 替换). base = 0.20*(board+low_vol+squeeze+volume+range).
    energy = 0.08 if squeeze_score >= 1.0 and low_vol_score >= 0.75 else 0.0
    base = min(1.0, 0.20 * board_score + 0.20 * low_vol_score
               + 0.20 * squeeze_score + 0.20 * volume_score + 0.20 * range_score + energy)
    # streak=3 → streak_bonus=0 → strength == base (无任何 streak bonus)
    assert abs(result.trigger_strength - base) < 1e-9, (
        f"3+连板不应得 streak_bonus: got {result.trigger_strength}, base {base}")


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
    from src.screening.offensive.setups.btst_breakout import _compute_low_vol_score
    pre_window = prices.iloc[trigger_idx - 5 : trigger_idx]
    position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)
    low_vol_score = _compute_low_vol_score(prices, trigger_idx)
    assert position_score == 1.0, "构造应使 position=1.0 (T-1 在 5 日下半区)"
    assert squeeze_score == 0.5, "构造应使 squeeze=0.5 (前段全平 prior_atr=0 回退)"

    board_score = _board_quality_score("X")
    volume_score = _compute_volume_score(prices, trigger_idx)
    from src.screening.offensive.setups.btst_breakout import _compute_range_score
    range_score = _compute_range_score(prices, trigger_idx)
    # weekday 已移出 (Q1); position 已移出 (Q6, low_vol 替换). 无 bonus 期望 = 0.20*五项.
    expected_no_bonus = min(
        1.0,
        0.20 * board_score + 0.20 * low_vol_score + 0.20 * squeeze_score
        + 0.20 * volume_score + 0.20 * range_score,
    )
    # squeeze=0.5 (中性) 绝不可触发 "完整弹簧释放" bonus.
    assert abs(result.trigger_strength - expected_no_bonus) < 1e-9, (
        f"squeeze=0.5 时不应发 energy_bonus: got {result.trigger_strength}, "
        f"expected(no bonus) {expected_no_bonus}"
    )
