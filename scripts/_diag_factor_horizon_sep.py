#!/usr/bin/env python3
"""Factor direction sep across horizons (T+1 / T+5 / T+10 / T+30).

CRITICAL VALIDATION (autodev C228): C222/C223/C225 的"因子反向"结论全部基于 T+1。
但 BUY gate 真实决策 horizon 是 T+5/T+10 (C220 改的, winrate≈60%)。mean-reversion
vs momentum 是 horizon-dependent — T+1 上动量主导 (反向), T+5/T+10/T+30 上均值回归
可能生效 (反向消失)。本诊断对每个 trend+MR sub-factor 在 4 个 horizon 上分别算 sep,
判定 C224 (vol flip) / C226 (weight revert) 是否在决策 horizon 上仍然成立。

WIP-compatible: read-only diagnostic, no src/ change.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
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
from src.screening.strategy_scorer import score_trend_strategy  # noqa: E402
from src.screening.strategy_scorer_mean_reversion import (  # noqa: E402
    score_mean_reversion_strategy,
)

HORIZONS = [1, 5, 10, 30]
TREND_FACTORS = ["ema_alignment", "adx_strength", "momentum", "volatility", "long_trend_alignment"]
MR_FACTORS = ["zscore_bbands", "rsi_extreme", "stat_arb", "hurst_regime"]


def run(n_dates, sample_n, end_date=None, seed=42):
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    # need trade_dates with ~35 future trading days after the last test_date for T+30
    trade_dates = get_trading_dates(pro, n_dates + 40, end_date=end_date)
    if len(trade_dates) < n_dates + 35:
        print(f"交易日不足 (需 {n_dates+35}+, got {len(trade_dates)})")
        return
    # test on the EARLY dates so each has 30+ future trading days
    test_dates = trade_dates[:n_dates]
    rng = np.random.default_rng(seed)
    # rows: {factor, horizon, direction, ret}
    rows = []
    print(f"\nFactor sep × horizon: {test_dates[0]}~{test_dates[-1]} ({len(test_dates)} dates, sample={sample_n})")
    print(f"horizons: {HORIZONS}  (BUY gate 决策 horizon = T+5/T+10)")
    print("=" * 92)

    for di, td in enumerate(test_dates):
        t0 = time.time()
        uni = get_universe_for_date(pro, td, stock_basic)
        if uni.empty:
            continue
        if sample_n and len(uni) > sample_n:
            uni = uni.sample(n=sample_n, random_state=int(rng.integers(1 << 31)))
        if len(uni) < 50:
            continue
        # history: 180 days lookback + 35 future days (cover T+30)
        hist_start = (datetime.strptime(td, "%Y%m%d") - timedelta(days=280)).strftime("%Y%m%d")
        hist_end = trade_dates[di + 35]  # ~35 trading days ahead
        hist = get_history_batch(pro, uni["ts_code"].tolist(), hist_start, hist_end)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])
        td_ts = pd.to_datetime(td, format="%Y%m%d")
        # map: ts_code -> position (integer idx) of td in its sorted frame
        n_ok = 0
        for code, g in hist.groupby("ts_code"):
            g = g.set_index("trade_date")
            if len(g) < 126:
                continue
            if td_ts not in g.index:
                continue
            td_pos = g.index.get_loc(td_ts)
            if not isinstance(td_pos, int):
                # if duplicate/bool mask, take first
                td_pos = np.where(g.index.values == td_ts.to_datetime64())[0][0]
            # need td_pos + 30 <= len-1
            if td_pos + max(HORIZONS) >= len(g):
                continue
            close = g["close"].values
            base = close[td_pos]
            if not np.isfinite(base) or base <= 0:
                continue
            rets = {h: (close[td_pos + h] / base - 1.0) * 100.0 for h in HORIZONS}  # %
            # score factors at td (use history UP TO td, not future)
            prices_up_to_td = g.iloc[: td_pos + 1]
            if len(prices_up_to_td) < 126:
                continue
            try:
                trend_sig = score_trend_strategy(prices_up_to_td, ticker=code)
                mr_sig = score_mean_reversion_strategy(prices_up_to_td)
            except Exception:
                continue
            for sf, dump in {**trend_sig.sub_factors, **mr_sig.sub_factors}.items():
                if sf not in TREND_FACTORS + MR_FACTORS:
                    continue
                if float(dump.get("completeness", 0)) <= 0:
                    continue
                d = int(dump.get("direction", 0))
                fam = "trend" if sf in TREND_FACTORS else "mr"
                for h in HORIZONS:
                    rows.append({"family": fam, "factor": sf, "horizon": h, "direction": d, "ret": float(rets[h])})
            n_ok += 1
        print(f"[{di+1}/{len(test_dates)}] {td} stocks={n_ok} ({time.time()-t0:.1f}s)")

    if not rows:
        print("无有效数据")
        return
    _analyze(rows)


def _analyze(rows):
    df = pd.DataFrame(rows)
    print(f"\n样本: {len(df)} factor×horizon records")
    print("=" * 92)
    print(f"{'family':<6s} {'factor':<20s} {'horizon':>8s} {'n':>6s} {'dir=+1':>7s} {'dir=-1':>7s}" f" {'T(+1)':>9s} {'T(-1)':>9s} {'sep':>8s}  flag")
    print("-" * 92)
    for fam in ("trend", "mr"):
        factors = TREND_FACTORS if fam == "trend" else MR_FACTORS
        for sf in factors:
            for h in HORIZONS:
                sub = df[(df["family"] == fam) & (df["factor"] == sf) & (df["horizon"] == h)]
                if sub.empty:
                    continue
                pos = sub[sub["direction"] == 1]
                neg = sub[sub["direction"] == -1]
                pr = float(pos["ret"].mean()) if not pos.empty else float("nan")
                nr = float(neg["ret"].mean()) if not neg.empty else float("nan")
                sep = (pr - nr) if (np.isfinite(pr) and np.isfinite(nr)) else float("nan")
                flag = "✓正确" if (np.isfinite(sep) and sep > 0) else "?反向" if (np.isfinite(sep) and sep < 0) else "—"
                print(f"{fam:<6s} {sf:<20s} {('T+'+str(h)):>8s} {len(sub):>6d} {len(pos):>7d} {len(neg):>7d}" f" {pr:>+8.3f} {nr:>+8.3f} {sep:>+7.3f}  {flag}")
        print("-" * 92)
    print("\n判定: BUY gate 决策 horizon = T+5/T+10。若因子在 T+5/T+10 sep>0 (正确), " "则 C224/C226 (基于 T+1 反向) 在决策 horizon 上错误, 应回滚。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=3)
    ap.add_argument("--sample-n", type=int, default=400)
    ap.add_argument("--end-date", default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run(a.dates, a.sample_n, a.end_date)
