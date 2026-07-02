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
import logging, os, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any
import numpy as np, pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from scripts._backtest_light_stage_universe import (  # noqa: E402
    get_trading_dates, get_universe_for_date, _get_pro,
)
from scipy.stats import spearmanr

BUCKETS = [(0, 10), (10, 20), (20, 40), (40, 80), (80, 200), (200, 1e9)]


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
    for di, test_date in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            continue
        try:
            # 当日 close (price anchor) + 次日 pct_chg (T+1 return)
            d0 = pro.daily(trade_date=test_date)[["ts_code", "close"]].rename(columns={"close": "price"})
            d1 = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
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
        print("无数据"); return
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
    print(f"\n{'=' * 90}")
    print("判读 (池内 price-IC +0.176 是否是选择偏差伪象):")
    if overall_rho < 0.05:
        print(f"  ✅ 全 universe price-IC ≈ {overall_rho:+.3f} (~0 或负, 小盘溢价) 但池内 +0.176 → **选择偏差伪象**")
        print(f"     池反转了 price 效应 (像 score 那样); price 不是真实可用的排序 signal。")
    elif overall_rho > 0.10:
        print(f"  ⚠️ 全 universe price-IC ≈ {overall_rho:+.3f} (正, 与池内同向) → price 是真实 factor (高价=质量代理)。")
        print(f"     可考虑作为池内排序辅助 signal (但需 T+5/T+10 + 全模型确认)。")
    else:
        print(f"  ≈ 全 universe price-IC ≈ {overall_rho:+.3f} (弱) — 池内 +0.176 部分是真实, 部分是偏差放大。")


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
