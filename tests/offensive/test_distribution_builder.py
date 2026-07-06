"""分布构建器测试 — 编排 setup + execution_adjuster + statistics。"""
from __future__ import annotations

import pandas as pd

from src.screening.offensive.distribution_builder import (
    build_distribution,
    TermStructureDistribution,
)
from src.screening.offensive.setups.base import Setup, DetectionResult
from src.screening.offensive.execution_adjuster import ExecutionConfig


class _AlwaysHitSetup(Setup):
    """测试用: 每个样本都命中。"""
    name = "test_always_hit"
    natural_horizon = 3

    def detect(self, ticker, trade_date, context):
        return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date,
                               trigger_strength=1.0, invalidation_condition="n/a")


def _make_prices(ticker, start="2026-07-01", days=12, drift=0.01):
    dates = pd.bdate_range(start, periods=days)
    closes = [10.0]
    for _ in range(days - 1):
        closes.append(closes[-1] * (1 + drift))
    return pd.DataFrame({
        "date": dates,
        "close": closes,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "pct_change": [0.0] + [drift * 100] * (days - 1),
    })


def test_build_distribution_returns_term_structure():
    setup = _AlwaysHitSetup()
    tickers = ["000001", "000002"]
    trade_dates = ["20260701", "20260701"]
    prices = {t: _make_prices(t) for t in tickers}

    tsd = build_distribution(
        setup=setup,
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices,
        regimes_by_date={"20260701": "normal"},
        horizons=(1, 3, 5),
    )
    assert isinstance(tsd, TermStructureDistribution)
    assert tsd.setup_name == "test_always_hit"
    assert set(tsd.horizons.keys()) == {1, 3, 5}
    assert tsd.horizons[5].n == 2  # 2 个样本


def test_build_distribution_skips_non_hits():
    """setup 命中率 < 100% 时, 未命中样本不进分布。"""
    class _SometimesHit(Setup):
        name = "sometimes"
        natural_horizon = 1
        def detect(self, ticker, trade_date, context):
            hit = ticker.endswith("1")  # 000001 命中, 000002 不命中
            return DetectionResult(hit=hit, ticker=ticker, trade_date=trade_date,
                                   trigger_strength=1.0 if hit else 0.0,
                                   invalidation_condition="n/a")

    prices = {t: _make_prices(t) for t in ("000001", "000002")}
    tsd = build_distribution(
        setup=_SometimesHit(),
        tickers=["000001", "000002"],
        trade_dates=["20260701", "20260701"],
        prices_by_ticker=prices,
        regimes_by_date={"20260701": "normal"},
        horizons=(1,),
    )
    assert tsd.horizons[1].n == 1  # 只有 000001


def test_build_distribution_period_label():
    """period 参数 ('IS'/'OOS'/'ALL') 写入 TermStructureDistribution。"""
    setup = _AlwaysHitSetup()
    prices = {"000001": _make_prices("000001")}
    tsd = build_distribution(
        setup=setup, tickers=["000001"], trade_dates=["20260701"],
        prices_by_ticker=prices, regimes_by_date={"20260701": "normal"},
        horizons=(1,), period="OOS",
    )
    assert tsd.period == "OOS"
