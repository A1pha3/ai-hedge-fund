#!/usr/bin/env python3
"""全 universe price-IC 测试 (c307, loop 40): 池内 price-IC +0.18 是真实效应还是选择偏差伪象?

loop 39 发现: 池内 (tracking_history, n=7993) recommended_price 与 T+5 return
Spearman IC = +0.176 (p=2e-56), 单调: ¥0-10 winrate 53% → ¥200+ 71%.

关键问题 (对照 aff989be/c303 选择偏差教训): price 在**全 universe** 上是否也
正向预测 T+5? A 股常识是**小盘股溢价** (低价 → 高收益, price-IC 应为负)。若:
  - 全 universe price-IC ≈ 池内 (+0.18): price 是真实 factor (高价 = 质量代理), 可用作池内排序
  - 全 universe price-IC < 0 (小盘溢价) 但池内 > 0: **选择偏差伪象** (池反转了 price 效应, 像 score 那样)

lean 设计: 只需 universe + 当日 close + 次日 pct_chg, 不算因子 → 快 (~2 API/日)。
复用 _backtest_light_stage_universe 的 _get_pro/get_trading_dates/get_universe_for_date。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from scipy.stats import spearmanr  # noqa: E402

from scripts._backtest_light_stage_universe import (  # noqa: E402
    _get_pro,
    get_trading_dates,
    get_universe_for_date,
)

BUCKETS = [(0, 10), (10, 20), (20, 40), (40, 80), (80, 200), (200, 1e9)]

logger = logging.getLogger("universe_price_ic")


def classify_price_effect(universe_ic: float, pool_ic: float | None = None) -> str:
    """Classify whether a within-pool price-IC reflects a real universe-level price
    effect or selection-bias amplification (pure). Returns 'bias_amplified' |
    'real_factor' | 'mixed'. c308 (loop 42): extracted from run() for testability —
    the c307 conclusion (pool price-IC +0.176 is bias-amplified, universe +0.049)
    rests on this classification.

    - universe_ic < 0.05: weak universe effect → pool's strong IC is bias-amplified
      (the 3rd selection-bias instance after score/MR; not an actionable ranking signal).
    - universe_ic > 0.10: real universe-level price factor (high price = quality proxy).
    - else: mixed (partially real, partially amplified).
    """
    if universe_ic < 0.05:
        return "bias_amplified"
    if universe_ic > 0.10:
        return "real_factor"
    return "mixed"


def amplification_ratio(universe_ic: float, pool_ic: float) -> float | None:
    """How many times stronger the pool IC is vs the universe IC (pure). None if
    universe_ic is 0 (avoid divide-by-zero). c307 real-data: pool +0.176 / universe
    +0.049 = 3.6× amplification."""
    if universe_ic == 0:
        return None
    return pool_ic / universe_ic


def render_price_verdict(
    universe_ic: float,
    pool_ic: float,
    *,
    n_records: int,
    n_days: int,
) -> list[str]:
    """Render the bias-amplification verdict as a list of print lines (pure).

    c317b (loop 50): extracted from run() so the verdict block is testable AND
    so ``amplification_ratio`` is actually surfaced (it was orphaned — defined +
    unit-tested but never called in run(); the c307 commit message's '3.59×
    amplification' headline was computed only by the helper test, never shown
    to the operator reading the diagnostic). Also discloses sample size so the
    owner can gauge verdict reliability.
    """
    verdict = classify_price_effect(universe_ic)
    amp = amplification_ratio(universe_ic, pool_ic)
    amp_str = f"{amp:.1f}×" if amp is not None else "N/A (universe IC=0)"
    lines = [
        "=" * 90,
        f"判读 (池内 price-IC {pool_ic:+.3f} 是否是选择偏差伪象; n={n_records}, {n_days} 日):",
        f"  amplification: {amp_str} (pool / universe)",
    ]
    if verdict == "bias_amplified":
        lines.append(f"  ✅ 全 universe price-IC ≈ {universe_ic:+.3f} (~0 或负, 小盘溢价) 但池内 {pool_ic:+.3f} " f"→ **选择偏差伪象** ({amp_str} 放大)")
        lines.append("     池反转了 price 效应 (像 score 那样); price 不是真实可用的排序 signal。")
    elif verdict == "real_factor":
        lines.append(f"  ⚠️ 全 universe price-IC ≈ {universe_ic:+.3f} (正, 与池内同向) → price 是真实 factor (高价=质量代理)。")
        lines.append("     可考虑作为池内排序辅助 signal (但需 T+5/T+10 + 全模型确认)。")
    else:  # mixed
        lines.append(f"  ≈ 全 universe price-IC ≈ {universe_ic:+.3f} (弱) — 池内 {pool_ic:+.3f} 部分是真实, 部分是偏差放大 ({amp_str})。")
    return lines


def run(n_days: int = 20, end_date: str | None = None) -> None:
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_days + 1, end_date=end_date)
    test_dates = trade_dates[:-1]
    print(f"\n全 universe price-IC 测试: {test_dates[0]}~{test_dates[-1]} ({len(test_dates)} 日)")
    print(f"池内 (loop 39): price-IC +0.176, ¥0-10 winrate 53% → ¥200+ 71%")
    print(f"{'=' * 90}")

    all_rows: list[dict[str, float]] = []
    per_day_ics: list[float] = []
    fetch_failures: list[str] = []  # c317b: NS-17 drain — track silently-dropped days
    for di, test_date in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            fetch_failures.append(f"{test_date}: empty universe")
            continue
        try:
            # 当日 close (price anchor) + 次日 pct_chg (T+1 return)
            d0 = pro.daily(trade_date=test_date)[["ts_code", "close"]].rename(columns={"close": "price"})
            d1 = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception as exc:
            # c317b: NS-17 silent-except drain — surface the dropped day + cause
            # so the operator can tell 'API rate-limited' from 'genuinely no data'.
            fetch_failures.append(f"{test_date}: {type(exc).__name__}: {exc}")
            logger.warning("universe price-IC: dropped day %s (data fetch failed: %s)", test_date, exc)
            continue
        df = universe.merge(d0, on="ts_code", how="inner").merge(d1, on="ts_code", how="inner")
        if len(df) < 100:
            continue
        rho, _ = spearmanr(df["price"].values, df["next_ret"].values)
        per_day_ics.append(rho)
        for _, r in df.iterrows():
            all_rows.append({"price": float(r["price"]), "next_ret": float(r["next_ret"])})
        if (di + 1) % 5 == 0 or di == 0:
            print(f"  [{di+1}/{len(test_dates)}] {test_date}: n={len(df)} day-price-IC={rho:+.4f}")

    if not all_rows:
        print("无数据")
        return
    df = pd.DataFrame(all_rows)
    overall_rho, p = spearmanr(df["price"].values, df["next_ret"].values)
    print(f"\n{'=' * 90}")
    print(f"全 universe 聚合 (n={len(df)} records, {len(per_day_ics)} 日, T+1):")
    print(f"  overall Spearman IC(price, T+1) = {overall_rho:+.4f} (p={p:.2e})")
    print(f"  per-day IC: mean={np.mean(per_day_ics):+.4f}  (range {min(per_day_ics):+.3f}..{max(per_day_ics):+.3f})")
    print(f"\n全 universe price buckets (T+1):")
    print(f"  {'price range':<16} {'n':>7} {'winrate':>8} {'mean':>9}")
    for lo, hi in BUCKETS:
        b = df[(df["price"] >= lo) & (df["price"] < hi)]
        if len(b):
            wr = (b["next_ret"] > 0).mean()
            print(f"  ¥{lo:<6}-{hi:<8} {len(b):>7} {wr:>8.1%} {b['next_ret'].mean():>+8.2f}%")
    # c317b: dropped-days disclosure (NS-17 drain) — operator can tell how many
    # of the requested n_days actually contributed, and why the rest were dropped.
    if fetch_failures:
        print(f"\n  ⚠ 丢弃 {len(fetch_failures)}/{len(test_dates)} 天 (前几条):")
        for f in fetch_failures[:5]:
            print(f"    - {f}")
    # c317b: verdict via pure helper (de-orphans amplification_ratio; pins text)
    for line in render_price_verdict(
        universe_ic=overall_rho,
        pool_ic=0.176,  # loop-39 within-pool benchmark
        n_records=len(df),
        n_days=len(per_day_ics),
    ):
        print(line)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--n-days", type=int, default=20)
    ap.add_argument("--end-date", default="")
    a = ap.parse_args()
    run(n_days=a.n_days, end_date=a.end_date or None)


if __name__ == "__main__":
    main()
