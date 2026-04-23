#!/usr/bin/env python3
"""
Market Regime Analysis for BTST: Identify which days are winners vs losers
and find predictive market-level signals to filter out bad days.
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main():
    import tushare as ts

    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()

    # Get trading calendar
    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=cal_start, end_date=cal_end, is_open="1")
    all_dates = sorted(cal["cal_date"].tolist())
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}
    test_dates = [d for d in all_dates if d <= cal_end][-20:]

    print(f"Market Regime Analysis: {test_dates[0]} ~ {test_dates[-1]}")
    print("=" * 100)

    # Get market index data (SSE Composite: 000001.SH)
    # Get 60 days of history for indicators
    start_hist = (datetime.strptime(test_dates[0], "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
    end_hist = test_dates[-1]

    idx = pro.index_daily(ts_code="000001.SH", start_date=start_hist, end_date=end_hist)
    idx = idx.sort_values("trade_date").reset_index(drop=True)
    idx["trade_date"] = idx["trade_date"].astype(str)

    # Compute market indicators
    idx["ma5"] = idx["close"].rolling(5).mean()
    idx["ma10"] = idx["close"].rolling(10).mean()
    idx["ma20"] = idx["close"].rolling(20).mean()
    idx["ma60"] = idx["close"].rolling(60).mean()
    idx["vol_ma5"] = idx["vol"].rolling(5).mean()
    idx["vol_ma20"] = idx["vol"].rolling(20).mean()
    idx["pct_chg"] = idx["pct_chg"].astype(float)
    idx["ret_5d"] = idx["close"].pct_change(5) * 100
    idx["ret_10d"] = idx["close"].pct_change(10) * 100
    idx["vol_ratio"] = idx["vol_ma5"] / idx["vol_ma20"]

    # ATR-like volatility (5-day range)
    idx["range_5d"] = (idx["high"].rolling(5).max() - idx["low"].rolling(5).min()) / idx["close"].rolling(5).mean() * 100

    # Trend: above MA20?
    idx["above_ma20"] = (idx["close"] > idx["ma20"]).astype(int)
    idx["above_ma5"] = (idx["close"] > idx["ma5"]).astype(int)
    idx["ma5_above_ma20"] = (idx["ma5"] > idx["ma20"]).astype(int)

    # Momentum: 5-day return
    idx["momentum_5d"] = idx["pct_chg"].rolling(5).sum()

    # Get daily return distribution for ALL stocks on each day
    print("\n--- Daily Market Statistics ---")
    print(f"{'Date':>10s} {'IdxRet':>7s} {'AboveMA20':>10s} {'MA5>MA20':>9s} {'VolRatio':>9s} {'Range5d':>8s} {'Mom5d':>7s} {'UpRatio':>8s} {'AdvDec':>7s}")
    print("-" * 95)

    day_stats = {}
    for test_date in test_dates:
        next_date = next_map.get(test_date)
        if not next_date:
            continue

        # Market index stats
        idx_row = idx[idx["trade_date"] == test_date]
        if idx_row.empty:
            continue
        row = idx_row.iloc[0]

        # Get next-day market return
        idx_next = idx[idx["trade_date"] == next_date]
        next_idx_ret = float(idx_next.iloc[0]["pct_chg"]) if not idx_next.empty else 0.0

        # Get all stock returns for next day
        try:
            df = pro.daily(trade_date=test_date)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df = df[~build_beijing_exchange_mask(df["ts_code"])]
        df = df[df["amount"] >= 100000]
        n_stocks = len(df)

        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
            df = df.merge(dfn, on="ts_code")
        except Exception:
            continue

        # Market breadth
        up_ratio = float((df["next_ret"] > 0).mean())
        adv_dec = float((df["next_ret"] > 0).sum()) - float((df["next_ret"] <= 0).sum())
        avg_ret = float(df["next_ret"].mean())

        above_ma20 = int(row.get("above_ma20", 0))
        ma5_above_ma20 = int(row.get("ma5_above_ma20", 0))
        vol_ratio = float(row.get("vol_ratio", 0)) if pd.notna(row.get("vol_ratio")) else 0
        range_5d = float(row.get("range_5d", 0)) if pd.notna(row.get("range_5d")) else 0
        mom_5d = float(row.get("momentum_5d", 0)) if pd.notna(row.get("momentum_5d")) else 0
        idx_ret = float(row.get("pct_chg", 0))

        print(f"{test_date:>10s} {idx_ret:>+6.2f}% {above_ma20:>10d} {ma5_above_ma20:>9d} {vol_ratio:>9.2f} {range_5d:>7.2f}% {mom_5d:>+6.2f}% {up_ratio:>7.0%} {int(adv_dec):>+6d}")

        day_stats[test_date] = {
            "idx_ret": idx_ret,
            "next_idx_ret": next_idx_ret,
            "above_ma20": above_ma20,
            "ma5_above_ma20": ma5_above_ma20,
            "vol_ratio": vol_ratio,
            "range_5d": range_5d,
            "momentum_5d": mom_5d,
            "up_ratio": up_ratio,
            "adv_dec": adv_dec,
            "avg_ret": avg_ret,
        }

    # Analyze patterns
    print(f"\n{'=' * 100}")
    print("PATTERN ANALYSIS: What predicts good vs bad days?")
    print(f"{'=' * 100}")

    good_days = {d: s for d, s in day_stats.items() if s["avg_ret"] > 0}
    bad_days = {d: s for d, s in day_stats.items() if s["avg_ret"] <= 0}

    print(f"\nGood days ({len(good_days)}/{len(day_stats)}):")
    if good_days:
        print(f"  Avg market return (T):   {np.mean([s['idx_ret'] for s in good_days.values()]):+.2f}%")
        print(f"  Avg market return (T+1): {np.mean([s['next_idx_ret'] for s in good_days.values()]):+.2f}%")
        print(f"  Above MA20:              {np.mean([s['above_ma20'] for s in good_days.values()]):.0%}")
        print(f"  MA5 > MA20:              {np.mean([s['ma5_above_ma20'] for s in good_days.values()]):.0%}")
        print(f"  Avg vol_ratio:           {np.mean([s['vol_ratio'] for s in good_days.values()]):.2f}")
        print(f"  Avg 5d range:            {np.mean([s['range_5d'] for s in good_days.values()]):.2f}%")
        print(f"  Avg 5d momentum:         {np.mean([s['momentum_5d'] for s in good_days.values()]):+.2f}%")
        print(f"  Avg up_ratio:            {np.mean([s['up_ratio'] for s in good_days.values()]):.0%}")

    print(f"\nBad days ({len(bad_days)}/{len(day_stats)}):")
    if bad_days:
        print(f"  Avg market return (T):   {np.mean([s['idx_ret'] for s in bad_days.values()]):+.2f}%")
        print(f"  Avg market return (T+1): {np.mean([s['next_idx_ret'] for s in bad_days.values()]):+.2f}%")
        print(f"  Above MA20:              {np.mean([s['above_ma20'] for s in bad_days.values()]):.0%}")
        print(f"  MA5 > MA20:              {np.mean([s['ma5_above_ma20'] for s in bad_days.values()]):.0%}")
        print(f"  Avg vol_ratio:           {np.mean([s['vol_ratio'] for s in bad_days.values()]):.2f}")
        print(f"  Avg 5d range:            {np.mean([s['range_5d'] for s in bad_days.values()]):.2f}%")
        print(f"  Avg 5d momentum:         {np.mean([s['momentum_5d'] for s in bad_days.values()]):+.2f}%")
        print(f"  Avg up_ratio:            {np.mean([s['up_ratio'] for s in bad_days.values()]):.0%}")

    # Try specific filters
    print(f"\n{'=' * 100}")
    print("FILTER EVALUATION")
    print(f"{'=' * 100}")

    filters = [
        ("above_ma20", lambda s: s["above_ma20"] == 1),
        ("ma5_above_ma20", lambda s: s["ma5_above_ma20"] == 1),
        ("vol_ratio <= 1.2", lambda s: s["vol_ratio"] <= 1.2),
        ("momentum_5d >= -2", lambda s: s["momentum_5d"] >= -2),
        ("momentum_5d >= 0", lambda s: s["momentum_5d"] >= 0),
        ("idx_ret >= -1", lambda s: s["idx_ret"] >= -1),
        ("range_5d <= 6", lambda s: s["range_5d"] <= 6),
        ("above_ma20 AND mom5d>=-2", lambda s: s["above_ma20"] == 1 and s["momentum_5d"] >= -2),
        ("above_ma20 AND mom5d>=0", lambda s: s["above_ma20"] == 1 and s["momentum_5d"] >= 0),
        ("ma5>ma20 AND mom5d>=-2", lambda s: s["ma5_above_ma20"] == 1 and s["momentum_5d"] >= -2),
        ("ma5>ma20 AND vol_ratio<=1.2", lambda s: s["ma5_above_ma20"] == 1 and s["vol_ratio"] <= 1.2),
        ("above_ma20 AND range5d<=6", lambda s: s["above_ma20"] == 1 and s["range_5d"] <= 6),
        ("mom5d>=-2 AND vol_ratio<=1.2", lambda s: s["momentum_5d"] >= -2 and s["vol_ratio"] <= 1.2),
    ]

    print(f"\n{'Filter':<40s} {'Days':>5s} {'PassWR':>7s} {'PassAvgR':>9s} {'FailWR':>7s} {'FailAvgR':>9s} {'Edge':>7s}")
    print("-" * 90)

    for fname, fcond in filters:
        pass_days = {d: s for d, s in day_stats.items() if fcond(s)}
        fail_days = {d: s for d, s in day_stats.items() if not fcond(s)}

        pass_wr = np.mean([1 if s["avg_ret"] > 0 else 0 for s in pass_days.values()]) if pass_days else 0
        pass_avg = np.mean([s["avg_ret"] for s in pass_days.values()]) if pass_days else 0
        fail_wr = np.mean([1 if s["avg_ret"] > 0 else 0 for s in fail_days.values()]) if fail_days else 0
        fail_avg = np.mean([s["avg_ret"] for s in fail_days.values()]) if fail_days else 0
        edge = pass_avg - fail_avg

        print(f"{fname:<40s} {len(pass_days):>5d} {pass_wr:>6.0%} {pass_avg:>+8.2f}% {fail_wr:>6.0%} {fail_avg:>+8.2f}% {edge:>+6.2f}%")


if __name__ == "__main__":
    main()
