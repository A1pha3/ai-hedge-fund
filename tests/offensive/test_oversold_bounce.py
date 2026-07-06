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
