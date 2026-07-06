"""分布构建器 — 编排 setup 检测 + execution_adjuster + statistics。

给定 setup + 一批 (ticker, trade_date) 样本 + 价格数据, 产出期限结构分布
(T+1/T+3/T+5/T+10 各一个 Distribution)。

Phase 0a 核心: 所有分布都经 execution_adjuster 处理 (v2 §C.2 硬约束)。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    adjust_returns,
)
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.statistics import Distribution, compute_distribution


@dataclass(frozen=True)
class TermStructureDistribution:
    """单 setup 在某 regime + 某时段的完整期限结构。"""

    setup_name: str
    horizons: dict[int, Distribution]  # {1: dist, 3: dist, 5: dist, ...}
    natural_horizon: int
    regime: str
    period: str  # "IS" / "OOS" / "ALL"
    n_hits: int  # 命中样本总数 (跨 horizon 一致)


def build_distribution(
    setup: Setup,
    tickers: list[str],
    trade_dates: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    regimes_by_date: dict[str, str],
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    config: ExecutionConfig | None = None,
    period: str = "ALL",
) -> TermStructureDistribution:
    """对一批样本回测 setup 的期限结构分布。

    流程:
    1. setup.detect 过滤命中样本
    2. 对每个 horizon, execution-adjusted 计算 T+horizon 收益
    3. compute_distribution 算 winrate/convexity/IC/CI
    4. 取所有样本的 regime (假设同批次同 regime; 不同则取众数)
    """
    assert len(tickers) == len(trade_dates)
    config = config or ExecutionConfig()

    # 1. 过滤命中样本
    hit_tickers, hit_dates = [], []
    for ticker, date_str in zip(tickers, trade_dates):
        ctx = {"prices": prices_by_ticker.get(ticker), "regime": regimes_by_date.get(date_str, "normal")}
        result = setup.detect(ticker, date_str, ctx)
        if result.hit:
            hit_tickers.append(ticker)
            hit_dates.append(date_str)

    # 2. 每 horizon 算 execution-adjusted 分布
    horizon_dists: dict[int, Distribution] = {}
    for h in horizons:
        adj = adjust_returns(hit_dates, hit_tickers, prices_by_ticker, horizon=h, config=config)
        finite = adj[np.isfinite(adj)]
        horizon_dists[h] = compute_distribution(finite)

    # 3. regime 众数 (假设批次内同 regime)
    if hit_dates:
        regime_counts: dict[str, int] = {}
        for d in hit_dates:
            r = regimes_by_date.get(d, "unknown")
            regime_counts[r] = regime_counts.get(r, 0) + 1
        regime = max(regime_counts.items(), key=lambda kv: kv[1])[0]
    else:
        regime = "unknown"

    return TermStructureDistribution(
        setup_name=setup.name,
        horizons=horizon_dists,
        natural_horizon=setup.natural_horizon,
        regime=regime,
        period=period,
        n_hits=len(hit_tickers),
    )
