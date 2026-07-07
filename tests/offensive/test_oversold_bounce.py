"""Setup-2 超跌反弹触发逻辑测试。"""

from __future__ import annotations

import pandas as pd

from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
from src.screening.offensive.data.fund_flow_store import FundFlowRecord


def _ctx(prices, fund_flow_records=None, regime="normal"):
    return {"prices": prices, "fund_flow_records": fund_flow_records or [], "regime": regime}


def _prices_with_30d_drop(drop_pct=-25.0):
    """30 日前 close=10, 今天 close = 10 × (1 + drop_pct/100)。
    前 30 日 + 今天共 31 行; 末行是 trigger。"""
    dates = pd.bdate_range("2026-01-01", periods=32)
    closes = [10.0] * 30 + [11.0, 10.0 * (1 + drop_pct / 100)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "open": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "pct_change": [0.0] + [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))],
            "volume": [1000] * 31 + [2000],  # 末行放量
        }
    )


def test_hit_when_oversold_and_flow_returns():
    prices = _prices_with_30d_drop(-25.0)  # 跌 25%
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    # 近 3 日主力净流入累计 > 0
    recent_dates = [prices.iloc[-1 - i]["date"].strftime("%Y%m%d") for i in range(3)]
    recs = [FundFlowRecord(ticker="X", date=d, close=8.0, pct_change=1.0, main_net_inflow=2_000_000, main_net_pct=2.0) for d in recent_dates]
    ctx = _ctx(prices, fund_flow_records=recs)
    result = OversoldBounceSetup().detect("X", today, ctx)
    assert result.hit is True
    assert result.trigger_strength > 0


def test_miss_when_not_oversold_enough():
    """30 日跌幅 < 20% → 不命中。"""
    prices = _prices_with_30d_drop(-15.0)  # 只跌 15%
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recent_dates = [prices.iloc[-1 - i]["date"].strftime("%Y%m%d") for i in range(3)]
    recs = [FundFlowRecord(ticker="X", date=d, close=8.0, pct_change=1.0, main_net_inflow=2_000_000, main_net_pct=2.0) for d in recent_dates]
    ctx = _ctx(prices, fund_flow_records=recs)
    result = OversoldBounceSetup().detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_flow_not_positive():
    """跌幅够但近 3 日主力净流出 → 不命中。"""
    prices = _prices_with_30d_drop(-25.0)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recent_dates = [prices.iloc[-1 - i]["date"].strftime("%Y%m%d") for i in range(3)]
    recs = [FundFlowRecord(ticker="X", date=d, close=8.0, pct_change=-1.0, main_net_inflow=-1_000_000, main_net_pct=-1.0) for d in recent_dates]
    ctx = _ctx(prices, fund_flow_records=recs)
    result = OversoldBounceSetup().detect("X", today, ctx)
    assert result.hit is False


def test_degraded_when_volume_column_missing():
    """缺 volume 列 (真实 price_cache 现状) → 条件3 跳过, 但必须标注 degraded.

    此前 bug: volume_col = None 时条件3 静默跳过, OversoldBounce 退化为 2 条件
    setup 却无任何标识. Phase 0 报告据此判 PASS, 但那不是设计的 3 条件 setup.
    诚实降级: hit 仍可为 True (条件1+2 满足), 但 degraded=True + reason 披露,
    让下游 (evaluate/报告/operator) 知道这个命中基于残缺条件.
    """
    prices_full = _prices_with_30d_drop(-25.0)
    today = prices_full.iloc[-1]["date"].strftime("%Y%m%d")
    recent_dates = [prices_full.iloc[-1 - i]["date"].strftime("%Y%m%d") for i in range(3)]
    recs = [FundFlowRecord(ticker="X", date=d, close=8.0, pct_change=1.0, main_net_inflow=2_000_000, main_net_pct=2.0) for d in recent_dates]

    # 移除 volume 列 (模拟真实 price_cache)
    prices_no_vol = prices_full.drop(columns=["volume"])
    assert "volume" not in prices_no_vol.columns
    ctx = _ctx(prices_no_vol, fund_flow_records=recs)
    result = OversoldBounceSetup().detect("X", today, ctx)

    # 条件1+2 满足 → 仍 hit (降级不改变命中, 只披露)
    assert result.hit is True
    # 必须标注降级 (不再静默)
    assert result.degraded is True, "缺 volume 时必须标注 degraded, 不能静默跳过条件3"
    assert "volume" in result.degradation_reason.lower() or "量比" in result.degradation_reason


def test_not_degraded_when_volume_present():
    """有 volume 列且条件3 通过 → degraded=False (正常路径)."""
    prices = _prices_with_30d_drop(-25.0)  # 含 volume 列, 末行放量 2000 vs 均量 1000
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recent_dates = [prices.iloc[-1 - i]["date"].strftime("%Y%m%d") for i in range(3)]
    recs = [FundFlowRecord(ticker="X", date=d, close=8.0, pct_change=1.0, main_net_inflow=2_000_000, main_net_pct=2.0) for d in recent_dates]
    ctx = _ctx(prices, fund_flow_records=recs)
    result = OversoldBounceSetup().detect("X", today, ctx)
    assert result.hit is True
    assert result.degraded is False
