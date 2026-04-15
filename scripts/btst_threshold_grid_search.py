#!/usr/bin/env python3
"""
Grid search over btst_precision_v2 profile thresholds.
Tests select_threshold, near_miss_threshold, and selected_rank_cap_ratio combinations.
"""

import math
import os
from datetime import datetime, timedelta
from itertools import product

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Import factor computation from 20day backtest
from btst_20day_backtest import (
    compute_factors,
    compute_score,
    _apply_rank_caps_to_scored_results,
    summarize_return_stats,
    spearman_ic,
)


def run_single_config(
    results_list: list[dict],
    profiles_config: dict,
    profile_name: str,
):
    """Run a single profile config on pre-computed data and return summary stats."""
    config = profiles_config[profile_name]
    all_returns = []
    all_tplus2 = []
    all_tplus3 = []
    daily_stats = []

    for day_data in results_list:
        results = day_data["results"].copy()
        day_factors = day_data["factors"]  # Use per-day factors (no lookahead)
        if len(results) < 50:
            continue

        # Compute scores
        scores = []
        for _, row in results.iterrows():
            f = day_factors.get(row["ts_code"])
            if f is None:
                scores.append(0)
                continue
            s = compute_score(f, config["weights"])
            scores.append(s)
        results[f"score_{profile_name}"] = scores

        sel, nm = _apply_rank_caps_to_scored_results(
            results,
            score_col=f"score_{profile_name}",
            select_threshold=float(config["select_threshold"]),
            near_miss_threshold=float(config["near_miss_threshold"]),
            selected_rank_cap=0,
            near_miss_rank_cap=0,
            selected_rank_cap_ratio=float(config["selected_rank_cap_ratio"]),
            near_miss_rank_cap_ratio=float(config["near_miss_rank_cap_ratio"]),
            selected_breakout_freshness_min=float(config.get("selected_breakout_freshness_min", 0.10)),
            selected_trend_acceleration_min=float(config.get("selected_trend_acceleration_min", 0.16)),
        )

        if len(sel) < 1:
            continue

        stats = summarize_return_stats(sel["next_ret"])
        all_returns.extend(sel["next_ret"].dropna().tolist())
        if "tplus2_ret" in sel:
            all_tplus2.extend(sel["tplus2_ret"].dropna().tolist())
        if "tplus3_ret" in sel:
            all_tplus3.extend(sel["tplus3_ret"].dropna().tolist())
        daily_stats.append(stats)

    if not daily_stats:
        return None

    # Aggregate
    all_rets = pd.Series(all_returns)
    overall_stats = summarize_return_stats(all_rets)
    avg_wr = float(np.mean([d["win_rate"] for d in daily_stats]))
    avg_ret = float(np.mean([d["avg_ret"] for d in daily_stats]))
    n_pos_days = int(sum(1 for d in daily_stats if d["avg_ret"] > 0))

    return {
        "profile": profile_name,
        "n_days": len(daily_stats),
        "n_total": len(all_returns),
        "overall_win_rate": overall_stats["win_rate"],
        "overall_avg_ret": overall_stats["avg_ret"],
        "overall_payoff": overall_stats["payoff_ratio"],
        "overall_expectancy": overall_stats["expectancy"],
        "daily_avg_win_rate": avg_wr,
        "daily_avg_ret": avg_ret,
        "positive_days": n_pos_days,
        "downside_p10": overall_stats["downside_p10"],
    }


def main():
    import tushare as ts

    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()

    # v2 base weights
    v2_base_weights = {
        "breakout_freshness": 0.123,
        "trend_acceleration": 0.345,
        "volume_expansion_quality": 0.014,
        "close_strength": 0.051,
        "sector_resonance": 0.040,
        "catalyst_freshness": 0.044,
        "layer_c_alignment": 0.007,
        "momentum_strength": 0.027,
        "reversal": 0.350,
    }

    # Grid search parameters
    select_thresholds = [0.28, 0.30, 0.32, 0.34, 0.36, 0.38, 0.40]
    near_miss_thresholds = [0.20, 0.22, 0.24, 0.26, 0.28, 0.30]
    selected_rank_cap_ratios = [0.08, 0.10, 0.12, 0.14, 0.16, 0.20, 0.24, 0.30]

    print("Grid search: v2 threshold optimization")
    print(f"select_threshold: {select_thresholds}")
    print(f"near_miss_threshold: {near_miss_thresholds}")
    print(f"selected_rank_cap_ratio: {selected_rank_cap_ratios}")
    print(f"Total configs: {len(select_thresholds) * len(near_miss_thresholds) * len(selected_rank_cap_ratios)}")
    print("=" * 100)

    # Load data once
    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=cal_start, end_date=cal_end, is_open="1")
    all_dates = sorted(cal["cal_date"].tolist())
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}
    test_dates = [d for d in all_dates if d <= cal_end][-20:]

    print(f"Test dates: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} days)")

    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")

    # Pre-compute all data
    all_day_data = []

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

        # Store per-day factors to avoid lookahead bias
        day_factors = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 22:
                continue
            f = compute_factors(g, None)
            if f is not None:
                day_factors[code] = f

        results = df[df["ts_code"].isin(day_factors.keys())].copy()
        if len(results) < 50:
            continue

        all_day_data.append({"date": test_date, "results": results, "factors": day_factors})
        print(f"[{di + 1}/{len(test_dates)}] {test_date}: pool={len(results)}")

    print(f"\nLoaded {len(all_day_data)} days of data")
    print("=" * 100)

    # Run grid search
    results_grid = []
    total_configs = len(select_thresholds) * len(near_miss_thresholds) * len(selected_rank_cap_ratios)
    config_count = 0

    for st in select_thresholds:
        for nmt in near_miss_thresholds:
            if nmt >= st:
                continue
            for rcr in selected_rank_cap_ratios:
                config_count += 1
                nmcr = rcr * 2  # near_miss cap = 2x selected cap (v2 pattern)

                profile_name = f"v2_st{st}_nm{nmt}_rc{rcr}"
                config = {
                    "weights": v2_base_weights,
                    "select_threshold": st,
                    "near_miss_threshold": nmt,
                    "selected_rank_cap_ratio": rcr,
                    "near_miss_rank_cap_ratio": nmcr,
                    "selected_breakout_freshness_min": 0.10,
                    "selected_trend_acceleration_min": 0.16,
                }

                result = run_single_config(all_day_data, {profile_name: config}, profile_name)
                if result:
                    result["select_threshold"] = st
                    result["near_miss_threshold"] = nmt
                    result["rank_cap_ratio"] = rcr
                    results_grid.append(result)

                if config_count % 50 == 0:
                    print(f"  [{config_count}/{total_configs}] tested...")

    print(f"\nTested {len(results_grid)} configurations")
    print("=" * 100)

    # Sort by composite score: expectancy * win_rate
    for r in results_grid:
        r["composite"] = (r["overall_expectancy"] or 0) * (r["overall_win_rate"] or 0)

    results_grid.sort(key=lambda x: x["composite"], reverse=True)

    print("\nTOP 20 CONFIGURATIONS (by expectancy * win_rate):")
    print(f"{'Rank':>4s} {'ST':>5s} {'NMT':>5s} {'RCR':>5s} {'WinR':>6s} {'AvgR':>7s} {'Exp':>7s} {'Payoff':>7s} {'PosD':>5s} {'P10':>7s} {'N':>6s}")
    print("-" * 80)
    for i, r in enumerate(results_grid[:20]):
        payoff = f"{r['overall_payoff']:.2f}" if r['overall_payoff'] else "N/A"
        print(f"{i + 1:4d} {r['select_threshold']:5.2f} {r['near_miss_threshold']:5.2f} {r['rank_cap_ratio']:5.2f} "
              f"{r['overall_win_rate']:5.0%} {r['overall_avg_ret']:+6.2f}% {r['overall_expectancy']:+6.2f}% "
              f"{payoff:>7s} {r['positive_days']:3d}/{r['n_days']:2d} "
              f"{r['downside_p10']:+6.2f}% {r['n_total']:6d}")

    # Also show top by positive days
    print("\nTOP 10 by MOST POSITIVE DAYS:")
    by_pos_days = sorted(results_grid, key=lambda x: (x["positive_days"], x["overall_avg_ret"]), reverse=True)
    for i, r in enumerate(by_pos_days[:10]):
        payoff = f"{r['overall_payoff']:.2f}" if r['overall_payoff'] else "N/A"
        print(f"{i + 1:4d} ST={r['select_threshold']:.2f} NMT={r['near_miss_threshold']:.2f} RCR={r['rank_cap_ratio']:.2f} "
              f"WinR={r['overall_win_rate']:.0%} AvgR={r['overall_avg_ret']:+.2f}% Exp={r['overall_expectancy']:+.2f}% "
              f"PosDays={r['positive_days']}/{r['n_days']} Payoff={payoff} N={r['n_total']}")


if __name__ == "__main__":
    main()
