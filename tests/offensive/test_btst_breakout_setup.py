"""BtstBreakoutSetup miss 阶段标注测试 (R80 Op2).

检测器四条件 miss 此前经 _miss() 静默返回 — prefilter→hits 之间是黑箱,
零命中日 (0828: 85 prefilter→0 命中) 的取证只能手工复现检测路径. 本文件
钉死每个条件的 miss_stage 标签: 漏斗 per-condition 分桶 (ScanFunnel.
detect_miss_stages) 的单一事实源.
"""

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


def _base_prices(today_pct=10.0, pre5_close=10.5):
    """今天涨停 (+10%), 5 日前 close=10.5 (4.76% runup, 过条件4)."""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [11.0]
    closes[-6] = pre5_close
    pct = [0.0] * 20 + [0.0, today_pct]
    return pd.DataFrame(
        {"date": dates, "close": closes, "open": closes, "high": closes, "low": closes, "pct_change": pct}
    )


def _flow_records(prices, today_inflow=5_000_000, old_inflow=100_000):
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [
        FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                       main_net_inflow=today_inflow, main_net_pct=8.0)
    ]
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        recs.append(
            FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                           main_net_inflow=old_inflow, main_net_pct=0.5)
        )
    return recs


def _stage_of(prices, today, ctx) -> str:
    result = BtstBreakoutSetup().detect("X", today, ctx)
    assert result.hit is False
    return result.miss_stage


def test_miss_stage_hit_result_has_empty_stage():
    """命中行 miss_stage 为空 — 字段只描述 miss, 命中零语义."""
    prices = _base_prices()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    result = BtstBreakoutSetup().detect(
        "X", today, _ctx(prices, fund_flow_records=_flow_records(prices), industry_pct=3.0)
    )
    assert result.hit is True
    assert result.miss_stage == ""


def test_miss_stage_c0_prices_missing():
    result = BtstBreakoutSetup().detect("X", "20260630", _ctx(None))
    assert result.miss_stage == "c0_prices_missing"


def test_miss_stage_c0_trigger_row_missing():
    prices = _base_prices()
    assert _stage_of(prices, "20991231", _ctx(prices, fund_flow_records=_flow_records(prices))) == (
        "c0_trigger_row_missing"
    )


def test_miss_stage_c1_limit_up_pct():
    """今日 +3% — 低于板块涨停阈 (主板 9.5%)."""
    prices = _base_prices(today_pct=3.0)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(prices))) == (
        "c1_limit_up_pct"
    )


def test_miss_stage_c1_cap_guard():
    """今日 +11% — 超过交易所板帽护栏 (无涨跌幅限制日, 非涨停)."""
    prices = _base_prices(today_pct=11.0)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(prices))) == (
        "c1_cap_guard"
    )


def test_miss_stage_c2_flow_missing():
    prices = _base_prices()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=[], industry_pct=3.0)) == (
        "c2_flow_missing"
    )


def test_miss_stage_c2_flow_below_mean():
    """今日主力净流入 50k < 历史 20 日均 100k — 0828 普跌分发日的主挡点."""
    prices = _base_prices()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = _flow_records(prices, today_inflow=50_000, old_inflow=100_000)
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=recs, industry_pct=3.0)) == (
        "c2_flow_below_mean"
    )


def test_miss_stage_c3_industry_missing():
    prices = _base_prices()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(prices), industry_pct=None)) == (
        "c3_industry_missing"
    )


def test_miss_stage_c3_industry_weak():
    """行业当日 +1% < 2% 阈 — 板块效应 gate."""
    prices = _base_prices()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(prices), industry_pct=1.0)) == (
        "c3_industry_weak"
    )


def test_miss_stage_c4_data_short():
    """价格窗口不足 6 行 — ref_idx < 0 保守 miss (flow 记录独立构造, 不随截断)."""
    full = _base_prices()
    today = full.iloc[-1]["date"].strftime("%Y%m%d")
    prices = full.iloc[-3:].reset_index(drop=True)
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(full))) == (
        "c4_data_short"
    )


def test_miss_stage_c4_runup_exceeded():
    """涨停前一日 +9% → 链式复合 (1.09×1.10−1)=19.9% > 8% — 防追高 gate.

    条件4 按 pct_change 链复合 (688167 幻影修复后的语义), 改 close 不影响判定.
    """
    prices = _base_prices()
    prices.loc[prices.index[-2], "pct_change"] = 9.0
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    assert _stage_of(prices, today, _ctx(prices, fund_flow_records=_flow_records(prices))) == (
        "c4_runup_exceeded"
    )
