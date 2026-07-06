"""Phase 0 研究 CLI 测试 — IS/OOS 切分 + 准入判定 + 报告渲染。"""

from __future__ import annotations

import pandas as pd

from scripts.setup_research import (
    split_is_oos,
    evaluate_setup,
    render_report,
    is_setup_qualified,
)
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup


def test_split_is_oos_by_date():
    dates = ["20240101", "20240601", "20250101", "20250601", "20260101"]
    is_dates, oos_dates = split_is_oos(dates, split_date="20250101")
    assert is_dates == ["20240101", "20240601"]
    assert oos_dates == ["20250101", "20250601", "20260101"]


def test_is_setup_qualified_passes_strong_setup():
    """convexity 2.0 + winrate 0.6 + n 60 + ic 0.08 → qualified。"""
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is True


def test_is_setup_qualified_fails_low_n():
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=40, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is False  # n < 50


def test_is_setup_qualified_fails_low_convexity():
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=60, winrate=0.55, avg_gain=0.1, avg_loss=-0.1, convexity_ratio=1.2, expected_return=0.005, ci_low=-0.02, ci_high=0.03, ic=0.06)
    assert is_setup_qualified(dist) is False  # convexity < 1.5


def test_render_report_contains_verdict_and_stats():
    """报告含 PASS/FAIL verdict + 分布数字 + IS vs OOS 对比。"""
    from src.screening.offensive.distribution_builder import TermStructureDistribution
    from src.screening.offensive.statistics import Distribution

    dist_is = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    dist_oos = Distribution(n=55, winrate=0.55, avg_gain=0.15, avg_loss=-0.06, convexity_ratio=2.5, expected_return=0.07, ci_low=0.02, ci_high=0.12, ic=0.06)
    eval_result = {
        "setup_name": "btst_breakout",
        "natural_horizon": 3,
        "is": TermStructureDistribution("btst_breakout", {3: dist_is}, 3, "ALL", "IS", 60),
        "oos": TermStructureDistribution("btst_breakout", {3: dist_oos}, 3, "ALL", "OOS", 55),
        "qualified_is": True,
        "qualified_oos": True,
        "verdict": "PASS",
    }
    report = render_report(eval_result)
    assert "PASS" in report
    assert "btst_breakout" in report
    assert "IS" in report and "OOS" in report
    assert "60" in report  # n


def test_evaluate_setup_integration():
    """端到端: evaluate_setup 跑 setup 在样本上, 返回 IS/OOS/ALL 分布。"""
    tickers = ["000001", "000002", "000003"]
    prices_by_ticker = {}
    for t in tickers:
        dates = pd.bdate_range("2024-01-01", periods=15)
        closes = [10.0 + i * 0.1 for i in range(15)]
        closes[5] = closes[4] * 1.10  # 第 5 日涨停
        pct = [0.0] * 5 + [10.0] + [0.0] * 9
        prices_by_ticker[t] = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "open": closes,
                "high": closes,
                "low": closes,
                "pct_change": pct,
            }
        )

    from src.screening.offensive.data.fund_flow_store import FundFlowRecord

    fund_flow = {}
    for t in tickers:
        trigger_date = prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d")
        fund_flow[t] = [
            FundFlowRecord(ticker=t, date=trigger_date, close=closes[5], pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0),
        ]

    trade_dates = [prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d") for t in tickers]

    result = evaluate_setup(
        setup=BtstBreakoutSetup(),
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices_by_ticker,
        fund_flow_by_ticker=fund_flow,
        industry_pct_by_date={d: 3.0 for d in trade_dates},
        regimes_by_date={d: "normal" for d in trade_dates},
    )
    assert "is" in result and "oos" in result
    assert result["setup_name"] == "btst_breakout"
