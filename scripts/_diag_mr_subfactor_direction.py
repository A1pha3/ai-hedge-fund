#!/usr/bin/env python3
"""Mean-reversion sub-factor direction audit (extends C223 method to MR family).

Hypothesis (autodev C225): MR factors use mean-reversion logic (oversold→bullish,
overbought→bearish) — the SAME pattern as the reversed volatility factor (C222-C224).
If short-term momentum dominates T+1 (as volatility's reversal showed), the MR family
may be SYSTEMICALLY reversed, not just volatility-specific.

Reuses _diag_trend_subfactor_direction data-fetch; calls score_mean_reversion_strategy,
extracts 4 MR sub-factors (zscore_bbands / rsi_extreme / stat_arb / hurst_regime),
measures sep = T+1(dir=+1) - T+1(dir=-1) per sub-factor. sep>0 = direction correct.
WIP-compatible: read-only diagnostic, no src/ change.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_trend_subfactor_direction import (  # noqa: E402
    _get_pro,
    get_history_batch,
    get_trading_dates,
    get_universe_for_date,
)
from src.screening.strategy_scorer_mean_reversion import (  # noqa: E402
    score_mean_reversion_strategy,
)

MR_SUBFACTORS = ["zscore_bbands", "rsi_extreme", "stat_arb", "hurst_regime"]


def run(n_dates, sample_n, end_date=None, seed=42):
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_dates + 1, end_date=end_date)
    if len(trade_dates) < 2:
        print("交易日不足")
        return
    test_dates = trade_dates[:-1]
    rng = np.random.default_rng(seed)
    rows = []
    print(f"\nMR sub-factor direction audit: {test_dates[0]}~{test_dates[-1]} " f"({len(test_dates)} dates, sample={sample_n}/date)")
    print("=" * 78)
    for di, td in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        t0 = time.time()
        uni = get_universe_for_date(pro, td, stock_basic)
        if uni.empty:
            continue
        if sample_n and len(uni) > sample_n:
            uni = uni.sample(n=sample_n, random_state=int(rng.integers(1 << 31)))
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
            continue
        uni = uni.merge(dfn, on="ts_code", how="inner")
        if len(uni) < 50:
            continue
        hist_start = (pd.to_datetime(td, format="%Y%m%d") - pd.Timedelta(days=400)).strftime("%Y%m%d")
        hist = get_history_batch(pro, uni["ts_code"].tolist(), hist_start, td)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])
        next_map = dict(zip(uni["ts_code"], uni["next_ret"]))
        n_ok = 0
        for code, g in hist.groupby("ts_code"):
            if len(g) < 80:
                continue
            nr = next_map.get(code)
            if nr is None or not np.isfinite(nr):
                continue
            try:
                mr = score_mean_reversion_strategy(g.set_index("trade_date"))
            except Exception:
                continue
            for sf_name, sf_dump in mr.sub_factors.items():
                if sf_name not in MR_SUBFACTORS:
                    continue
                rows.append(
                    {
                        "subfactor": sf_name,
                        "direction": int(sf_dump.get("direction", 0)),
                        "completeness": float(sf_dump.get("completeness", 0.0)),
                        "next_ret": float(nr),
                    }
                )
                n_ok += 1
        print(f"[{di + 1}/{len(test_dates)}] {td} records={n_ok} ({time.time() - t0:.1f}s)")
    if not rows:
        print("无有效数据")
        return
    _analyze(rows)


def _analyze(rows):
    df = pd.DataFrame(rows)
    valid = df[df["completeness"] > 0]
    baseline = float(df["next_ret"].mean())
    print(f"\n样本: {len(df)} records (valid completeness>0: {len(valid)}), 全样本基准 T+1={baseline:+.3f}%")
    print("=" * 78)
    print(f"{'sub-factor':<18s} {'valid':>7s} {'dir=+1':>8s} {'dir=0':>8s} {'dir=-1':>8s}" f" {'T+1(+1)':>10s} {'T+1(-1)':>10s} {'sep':>9s}")
    print("-" * 78)
    for sf in MR_SUBFACTORS:
        sub = valid[valid["subfactor"] == sf]
        if sub.empty:
            print(f"{sf:<18s} (empty)")
            continue
        pos = sub[sub["direction"] == 1]
        neg = sub[sub["direction"] == -1]
        zero = sub[sub["direction"] == 0]
        pr = float(pos["next_ret"].mean()) if not pos.empty else float("nan")
        nr = float(neg["next_ret"].mean()) if not neg.empty else float("nan")
        sep = (pr - nr) if (np.isfinite(pr) and np.isfinite(nr)) else float("nan")
        flag = "✓正确" if (np.isfinite(sep) and sep > 0) else "?反向" if (np.isfinite(sep) and sep < 0) else "—"
        print(f"{sf:<18s} {len(sub):>7d} {len(pos):>8d} {len(zero):>8d} {len(neg):>8d}" f" {pr:>+9.3f} {nr:>+9.3f} {sep:>+8.3f}  {flag}")
    print("\n判定: sep = T+1(bullish) - T+1(bearish); >0 正确, <0 反向 (同 volatility C222).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=3)
    ap.add_argument("--sample-n", type=int, default=400)
    ap.add_argument("--end-date", default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run(a.dates, a.sample_n, a.end_date)
