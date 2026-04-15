#!/usr/bin/env python3
"""
BTST Factor Deep IC Analysis: Test each factor's standalone IC and their interactions.
Focus on short_term_reversal which has 35% weight in the winning profile.
"""

import argparse
import math
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def spearman_ic(x, y):
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1))


def compute_factors(g):
    """Compute all factors from price history group."""
    g = g.sort_values("trade_date")
    close = g["close"].values
    vol_col = "vol" if "vol" in g.columns else "volume"
    volume = g[vol_col].values
    n = len(close)
    if n < 22:
        return None

    last_close = close[-1]
    prev_close = close[-2] if n >= 2 else close[-1]
    open_price = g["open"].values[-1]

    # momentum_strength
    mom_1m = (close[-1] / close[-22] - 1) if n >= 23 else 0
    mom_3m = (close[-1] / close[-min(66, n - 1)] - 1) if n >= 67 else mom_1m
    mom_1m_n = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_n = min(max(mom_3m / 0.5, 0), 1)
    if n >= 133:
        mom_6m = close[-1] / close[-132] - 1
        mom_6m_n = min(max(mom_6m / 0.8, 0), 1)
        momentum_strength = min(max(0.4 * mom_1m_n + 0.3 * mom_3m_n + 0.3 * mom_6m_n, 0), 1)
    elif n >= 67:
        momentum_strength = min(max(0.6 * mom_1m_n + 0.4 * mom_3m_n, 0), 1)
    else:
        momentum_strength = mom_1m_n

    # volume_expansion_quality
    avg_vol_20 = np.mean(volume[-min(20, n):]) if n >= 5 else 1
    avg_vol_5 = np.mean(volume[-5:]) if n >= 5 else 1
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0
    volume_expansion = min(max((vol_ratio - 1.0) / 1.5, 0), 1)

    # close_strength
    high_20 = np.max(close[-min(20, n):])
    low_20 = np.min(close[-min(20, n):])
    price_range = high_20 - low_20 if high_20 > low_20 else 1
    close_strength = (last_close - low_20) / price_range

    # breakout_freshness
    ret_5d = (close[-1] / close[-min(6, n)] - 1) if n >= 6 else 0
    daily_return = (last_close / prev_close - 1) if prev_close > 0 else 0
    breakout_raw = 0.5 * min(max(ret_5d / 0.15, 0), 1) + 0.5 * min(max(daily_return / 0.05, 0), 1)
    breakout_freshness = min(max(breakout_raw, 0), 1)

    # trend_acceleration
    if n >= 44:
        mom_2w = close[-1] / close[-10] - 1
        mom_prev_2w = close[-11] / close[-21] - 1 if n >= 22 else 0
        accel = mom_2w - mom_prev_2w
        trend_acceleration = min(max(accel / 0.1, 0), 1)
    else:
        trend_acceleration = 0.5 * momentum_strength

    # sector_resonance (neutral)
    sector_resonance = 0.5

    # catalyst_freshness
    amount = g["amount"].values[-1]
    avg_amount = np.mean(g["amount"].values[-min(20, n):])
    amount_ratio = amount / avg_amount if avg_amount > 0 else 1.0
    catalyst_freshness = min(max(0.6 * min(amount_ratio / 3.0, 1) + 0.4 * breakout_freshness, 0), 1)

    # layer_c_alignment
    is_bull = last_close > open_price
    layer_c_alignment = min(max(0.5 * float(is_bull) + 0.5 * min(max(daily_return / 0.03, 0), 1), 0), 1)

    # short_term_reversal
    if n >= 6:
        ret_5d_raw = close[-1] / close[-6] - 1
        reversal = min(max(-ret_5d_raw / 0.10, 0), 1)
    else:
        reversal = 0.0

    # Additional reversal variants
    if n >= 3:
        ret_2d_raw = close[-1] / close[-3] - 1
        reversal_2d = min(max(-ret_2d_raw / 0.06, 0), 1)
    else:
        reversal_2d = 0.0

    if n >= 11:
        ret_10d_raw = close[-1] / close[-11] - 1
        reversal_10d = min(max(-ret_10d_raw / 0.15, 0), 1)
    else:
        reversal_10d = 0.0

    # Intraday reversal (close vs open)
    intraday_reversal = 0.0
    if open_price > 0:
        intraday_change = (last_close - open_price) / open_price
        # This measures late-day strength - not really reversal
        intraday_strength = min(max(intraday_change / 0.03, 0), 1)
    else:
        intraday_strength = 0.0

    # Volume-weighted reversal
    if n >= 6 and avg_vol_20 > 0:
        vol_weighted_reversal = reversal * min(vol_ratio, 2.0) / 2.0
    else:
        vol_weighted_reversal = 0.0

    return {
        "momentum_strength": momentum_strength,
        "volume_expansion_quality": volume_expansion,
        "close_strength": close_strength,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
        "reversal": reversal,
        "reversal_2d": reversal_2d,
        "reversal_10d": reversal_10d,
        "intraday_strength": intraday_strength,
        "vol_weighted_reversal": vol_weighted_reversal,
        "daily_return": daily_return,
        "vol_ratio": vol_ratio,
    }


ALL_FACTORS = [
    "momentum_strength", "volume_expansion_quality", "close_strength",
    "breakout_freshness", "trend_acceleration", "sector_resonance",
    "catalyst_freshness", "layer_c_alignment", "reversal",
    "reversal_2d", "reversal_10d", "intraday_strength", "vol_weighted_reversal",
]


def main():
    import tushare as ts

    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()

    # Get trading calendar - last 20 trading days
    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=cal_start, end_date=cal_end, is_open="1")
    all_dates = sorted(cal["cal_date"].tolist())
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}
    test_dates = [d for d in all_dates if d <= cal_end][-20:]

    print(f"Factor IC Analysis: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} days)")
    print("=" * 100)

    # Collect all factor ICs across all days
    all_factor_ics = {f: [] for f in ALL_FACTORS}
    all_factor_ics_t2 = {f: [] for f in ALL_FACTORS}
    all_factor_ics_t3 = {f: [] for f in ALL_FACTORS}

    # Also track quantile returns for each factor
    quantile_results = {f: {q: [] for q in range(5)} for f in ALL_FACTORS}

    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")

    for di, test_date in enumerate(test_dates):
        next_date = next_map.get(test_date)
        if not next_date:
            continue

        try:
            df = pro.daily(trade_date=test_date)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df = df.merge(sb, on="ts_code", how="left")
        df = df[df["amount"] >= 100000]
        df = df[~df["name"].str.contains("ST|退", na=False)]
        df = df[~df["ts_code"].str.startswith(("688", "8", "4"))]
        df = df[df["pct_chg"].between(-9.5, 9.5)]

        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
            df = df.merge(dfn, on="ts_code")
        except Exception:
            continue

        if len(df) < 100:
            continue

        # Get price history
        codes = df["ts_code"].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i:i + 80]
            try:
                h = pro.daily(ts_code=",".join(batch), start_date="20250601", end_date=test_date)
                if h is not None and not h.empty:
                    history.append(h)
            except Exception:
                continue

        if not history:
            continue

        hist = pd.concat(history, ignore_index=True)
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])

        stock_factors = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 22:
                continue
            f = compute_factors(g)
            if f is not None:
                stock_factors[code] = f

        if not stock_factors:
            continue

        results = df[df["ts_code"].isin(stock_factors.keys())].copy()
        if len(results) < 50:
            continue

        # Map factors to results
        for factor_name in ALL_FACTORS:
            results[factor_name] = results["ts_code"].map(
                lambda code, fn=factor_name: float((stock_factors.get(code) or {}).get(fn, 0.0))
            )

        # Compute IC for each factor vs next_ret
        for factor_name in ALL_FACTORS:
            ic = spearman_ic(results[factor_name].values, results["next_ret"].values)
            if np.isfinite(ic):
                all_factor_ics[factor_name].append(ic)

            # Quantile analysis
            results_sorted = results.dropna(subset=[factor_name, "next_ret"]).copy()
            if len(results_sorted) >= 50:
                results_sorted["q"] = pd.qcut(results_sorted[factor_name], 5, labels=False, duplicates="drop")
                for q in range(5):
                    q_df = results_sorted[results_sorted["q"] == q]
                    if not q_df.empty:
                        quantile_results[factor_name][q].append(float(q_df["next_ret"].mean()))

        print(f"[{di + 1}/{len(test_dates)}] {test_date}→{next_date}: pool={len(results)}", end="")
        # Show top 3 factors
        day_ics = [(f, spearman_ic(results[f].values, results["next_ret"].values)) for f in ALL_FACTORS]
        day_ics_sorted = sorted([(f, ic) for f, ic in day_ics if np.isfinite(ic)], key=lambda x: abs(x[1]), reverse=True)
        for f, ic in day_ics_sorted[:3]:
            print(f"  {f}={ic:+.3f}", end="")
        print()

    # ====== Summary ======
    print(f"\n{'=' * 100}")
    print("FACTOR IC SUMMARY (Spearman Rank IC vs Next-Day Return)")
    print(f"{'=' * 100}")
    print(f"{'Factor':<30s} {'Mean IC':>8s} {'IC>0%':>8s} {'IC_IR':>8s} {'Q0→Q4 Spread':>15s}")
    print("-" * 75)

    factor_summary = []
    for factor_name in ALL_FACTORS:
        ics = all_factor_ics[factor_name]
        if not ics:
            continue
        mean_ic = float(np.mean(ics))
        ic_std = float(np.std(ics)) if len(ics) > 1 else 1.0
        ic_ir = mean_ic / ic_std if ic_std > 0 else 0.0
        ic_positive_rate = float(np.mean([1 if ic > 0 else 0 for ic in ics]))

        # Quantile spread
        q0_rets = quantile_results[factor_name][0]
        q4_rets = quantile_results[factor_name][4]
        q0_avg = float(np.mean(q0_rets)) if q0_rets else 0.0
        q4_avg = float(np.mean(q4_rets)) if q4_rets else 0.0
        spread = q4_avg - q0_avg

        print(f"{factor_name:<30s} {mean_ic:>+8.4f} {ic_positive_rate:>7.0%} {ic_ir:>+8.3f} {spread:>+14.3f}%")
        factor_summary.append({
            "factor": factor_name,
            "mean_ic": mean_ic,
            "ic_ir": ic_ir,
            "ic_positive_rate": ic_positive_rate,
            "q0_avg": q0_avg,
            "q4_avg": q4_avg,
            "spread": spread,
        })

    # Sort by |mean IC|
    factor_summary.sort(key=lambda x: abs(x["mean_ic"]), reverse=True)

    print(f"\n{'=' * 100}")
    print("FACTOR RANKING (by absolute Mean IC)")
    print(f"{'=' * 100}")
    for i, fs in enumerate(factor_summary):
        print(f"  {i + 1}. {fs['factor']:<30s} IC={fs['mean_ic']:+.4f} IR={fs['ic_ir']:+.3f} Win={fs['ic_positive_rate']:.0%} Q-Spread={fs['spread']:+.3f}%")

    # ====== Detailed quantile analysis for top factors ======
    print(f"\n{'=' * 100}")
    print("QUINTILE ANALYSIS (Top 5 factors)")
    print(f"{'=' * 100}")
    for fs in factor_summary[:5]:
        factor_name = fs["factor"]
        print(f"\n  {factor_name} (IC={fs['mean_ic']:+.4f}):")
        for q in range(5):
            q_rets = quantile_results[factor_name][q]
            if q_rets:
                avg = float(np.mean(q_rets))
                win = float(np.mean([1 if r > 0 else 0 for r in q_rets]))
                print(f"    Q{q}: avg_ret={avg:+.3f}% win_rate={win:.0%} (n={len(q_rets)} days)")


if __name__ == "__main__":
    main()
