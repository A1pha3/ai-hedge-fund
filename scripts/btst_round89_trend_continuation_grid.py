# flake8: noqa
#!/usr/bin/env python3
"""
Round 89 - trend_continuation 因子权重快速网格搜索
目标：找到最优的 trend_continuation_weight + trend_continuation_2d_weight 组合

设计：基于 btst_20day_backtest 的轻量化版本
- 只测试 trend_corrected_v1 的变体
- 固定其他参数，只搜索 2 个新因子权重
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.btst_20day_backtest import (
    _load_open_trade_dates,
    compute_factors,
    PROFILE_WEIGHT_FIELDS,
)
from scripts.btst_data_utils import build_beijing_exchange_mask
from src.targets.short_trade_target_profile_data import SHORT_TRADE_TARGET_PROFILES


def _build_variant_weights(tc_w: float, tc2d_w: float) -> dict:
    """基于 trend_corrected_v1 基础权重，仅替换 trend_continuation 权重"""
    base = SHORT_TRADE_TARGET_PROFILES["trend_corrected_v1"]
    weights = {}
    for factor_key, weight_field in PROFILE_WEIGHT_FIELDS.items():
        w = float(getattr(base, weight_field, 0.0))
        if factor_key == "trend_continuation":
            w = tc_w
        elif factor_key == "trend_continuation_2d":
            w = tc2d_w
        weights[factor_key] = w
    return weights


def run_grid_search(data_cache: list[dict], param_grid: list[tuple[float, float]]) -> list[dict]:
    """在预缓存的数据上跑参数网格，无需重新调用API"""
    results = []
    for tc_w, tc2d_w in param_grid:
        weights = _build_variant_weights(tc_w, tc2d_w)

        all_rets = []
        all_otc = []
        all_high2 = []
        daily_wrs = []

        # 基准：base profile select_threshold
        select_threshold = 0.46

        for day_data in data_cache:
            results_df = day_data["df"].copy()
            stock_factors = day_data["factors"]

            # 计算分数
            scores = []
            for _, row in results_df.iterrows():
                f = stock_factors.get(row["ts_code"])
                if f is None:
                    scores.append(0)
                    continue
                # 归一化权重后计算
                total = sum(max(0, v) for v in weights.values())
                nw = {k: v / total for k, v in weights.items() if v > 0} if total > 0 else weights
                s = sum(nw.get(k, 0) * f.get(k, 0) for k in nw)
                scores.append(min(max(s, 0), 1))
            results_df["score"] = scores

            sel = results_df[results_df["score"] >= select_threshold]
            if len(sel) < 3:
                continue

            next_rets = sel["next_ret"].dropna()
            if len(next_rets) < 3:
                continue

            wr = float((next_rets > 0).mean())
            daily_wrs.append(wr)
            all_rets.extend(next_rets.tolist())
            if "open_to_close_ret" in sel.columns:
                all_otc.extend(sel["open_to_close_ret"].dropna().tolist())
            if "next_high_pct" in sel.columns:
                all_high2.extend((sel["next_high_pct"].dropna() >= 2.0).tolist())

        if not daily_wrs:
            continue

        all_s = pd.Series(all_rets, dtype=float)
        wins = all_s[all_s > 0]
        losses = all_s[all_s <= 0]
        avg_wr = float(np.mean(daily_wrs))
        avg_ret = float(all_s.mean()) if not all_s.empty else 0.0
        payoff = float(wins.mean() / abs(losses.mean())) if (not wins.empty and not losses.empty and losses.mean() < 0) else None
        expectancy = float((avg_wr * float(wins.mean() if not wins.empty else 0)) + ((1 - avg_wr) * float(losses.mean() if not losses.empty else 0)))

        results.append(
            {
                "tc_w": tc_w,
                "tc2d_w": tc2d_w,
                "avg_wr": avg_wr,
                "total_ret": avg_ret,
                "payoff": payoff,
                "expectancy": expectancy,
                "n_samples": len(all_rets),
                "n_days": len(daily_wrs),
                "open_wr": float(np.mean([x > 0 for x in all_otc])) if all_otc else None,
                "high2_rate": float(np.mean(all_high2)) if all_high2 else None,
            }
        )

    return sorted(results, key=lambda x: x["expectancy"], reverse=True)


def main():
    from src.tools.tushare_api import _get_pro

    pro = _get_pro()

    print("=== Round 89: trend_continuation 权重网格搜索 ===")
    print("正在获取交易日历...")

    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    all_dates = _load_open_trade_dates(pro, cal_start, cal_end)
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}
    test_dates = [d for d in all_dates if d <= cal_end][-20:]

    print(f"回测日期: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}天)")
    print("正在预缓存数据（此步骤只需一次）...")

    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")

    data_cache = []
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
        df = df[~build_beijing_exchange_mask(df["ts_code"])]
        df = df[df["pct_chg"].between(-9.5, 9.5)]

        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg", "open", "close", "high", "pre_close"]]
            dfn = dfn.rename(columns={"pct_chg": "next_ret"})
            dfn["open_to_close_ret"] = np.where(dfn["open"] > 0, (dfn["close"] - dfn["open"]) / dfn["open"] * 100, np.nan)
            dfn["next_high_pct"] = np.where(dfn["pre_close"] > 0, (dfn["high"] - dfn["pre_close"]) / dfn["pre_close"] * 100, np.nan)
            dfn = dfn[["ts_code", "next_ret", "open_to_close_ret", "next_high_pct"]]
        except Exception:
            continue
        df = df.merge(dfn, on="ts_code")
        if len(df) < 100:
            continue

        # 获取历史价格计算因子
        codes = df["ts_code"].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i : i + 80]
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
            f = compute_factors(g, None)
            if f is not None:
                stock_factors[code] = f

        if not stock_factors:
            continue

        df = df[df["ts_code"].isin(stock_factors.keys())]
        if len(df) < 50:
            continue

        data_cache.append({"df": df.copy(), "factors": stock_factors, "date": test_date, "next_date": next_date})
        print(f"  [{di+1}/{len(test_dates)}] {test_date}: {len(df)}只候选, {len(stock_factors)}只有因子")

    print(f"\n数据缓存完成: {len(data_cache)}天有效数据")
    print("\n开始网格搜索...")

    # 网格：tc_w in [0.10, 0.15, 0.20, 0.25, 0.30], tc2d_w in [0.06, 0.10, 0.14, 0.18, 0.22]
    tc_values = [0.10, 0.15, 0.20, 0.25, 0.30]
    tc2d_values = [0.06, 0.10, 0.14, 0.18, 0.22]
    param_grid = list(itertools.product(tc_values, tc2d_values))
    print(f"参数组合: {len(param_grid)} 个 ({len(tc_values)} x {len(tc2d_values)})")

    search_results = run_grid_search(data_cache, param_grid)

    print("\n=== 搜索结果 Top 10（按期望收益排序）===")
    print(f"{'tc_w':>6} {'tc2d_w':>7} {'avg_wr':>7} {'avg_ret':>8} {'payoff':>7} {'expectancy':>11} {'open_wr':>8} {'high2':>6}")
    print("-" * 80)
    for r in search_results[:15]:
        payoff_str = f"{r['payoff']:.2f}" if r["payoff"] else "N/A"
        open_wr_str = f"{r['open_wr']:.1%}" if r["open_wr"] else "N/A"
        high2_str = f"{r['high2_rate']:.1%}" if r["high2_rate"] else "N/A"
        print(f"  {r['tc_w']:>4.2f}   {r['tc2d_w']:>5.2f}   {r['avg_wr']:>6.1%}   {r['total_ret']:>+7.3f}%   {payoff_str:>6}   {r['expectancy']:>+10.3f}%   {open_wr_str:>7}  {high2_str:>5}")

    best = search_results[0]
    print("\n🏆 最优参数:")
    print(f"  trend_continuation_weight = {best['tc_w']}")
    print(f"  trend_continuation_2d_weight = {best['tc2d_w']}")
    print(f"  期望收益 = {best['expectancy']:+.3f}%")
    print(f"  日均胜率 = {best['avg_wr']:.1%}")
    print(f"  赔率 = {best['payoff']:.2f}" if best["payoff"] else "  赔率 = N/A")

    # 保存结果
    out_path = Path("data/reports/btst_round89_trend_continuation_grid.json")
    out_path.write_text(json.dumps(search_results, indent=2, ensure_ascii=False))
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
