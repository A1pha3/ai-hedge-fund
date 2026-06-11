#!/usr/bin/env python3
"""
Round 89 Task 2: trend_continuation 权重网格搜索
直接用 btst_20day_backtest 多profile 模式运行，快速对比
"""
from __future__ import annotations
import os
import sys
import json
import itertools
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.btst_20day_backtest as bk
from src.targets.short_trade_target_profile_data import SHORT_TRADE_TARGET_PROFILES
from src.targets.profiles import ShortTradeTargetProfile

# ==== 从 trend_corrected_v1 继承基础设置 ====
BASE_PROFILE = SHORT_TRADE_TARGET_PROFILES["trend_corrected_v1"]

def make_variant_profile(tc_w: float, tc2d_w: float) -> ShortTradeTargetProfile:
    return ShortTradeTargetProfile(
        name=f"tc_{tc_w:.2f}_tc2d_{tc2d_w:.2f}",
        description=f"trend_continuation={tc_w}, trend_continuation_2d={tc2d_w}",
        # 继承基础配置
        select_threshold=BASE_PROFILE.select_threshold,
        near_miss_threshold=BASE_PROFILE.near_miss_threshold,
        max_candidates=BASE_PROFILE.max_candidates,
        # 因子权重 - 从基础复制，修改目标权重
        breakout_freshness_weight=BASE_PROFILE.breakout_freshness_weight,
        trend_acceleration_weight=BASE_PROFILE.trend_acceleration_weight,
        volume_expansion_quality_weight=BASE_PROFILE.volume_expansion_quality_weight,
        close_strength_weight=BASE_PROFILE.close_strength_weight,
        sector_resonance_weight=BASE_PROFILE.sector_resonance_weight,
        catalyst_freshness_weight=BASE_PROFILE.catalyst_freshness_weight,
        layer_c_alignment_weight=BASE_PROFILE.layer_c_alignment_weight,
        historical_continuation_score_weight=BASE_PROFILE.historical_continuation_score_weight,
        momentum_strength_weight=BASE_PROFILE.momentum_strength_weight,
        short_term_reversal_weight=0.0,   # 禁用负向因子
        intraday_strength_weight=BASE_PROFILE.intraday_strength_weight,
        reversal_2d_weight=0.0,
        trend_continuation_weight=tc_w,     # 搜索目标
        trend_continuation_2d_weight=tc2d_w, # 搜索目标
        # 保留 profitability / breakout close_retention 逻辑
        selected_close_retention_min=BASE_PROFILE.selected_close_retention_min,
        selected_breakout_close_gap_max=BASE_PROFILE.selected_breakout_close_gap_max,
        selected_close_retention_penalty_weight=BASE_PROFILE.selected_close_retention_penalty_weight,
        near_miss_close_retention_min=BASE_PROFILE.near_miss_close_retention_min,
        near_miss_breakout_close_gap_max=BASE_PROFILE.near_miss_breakout_close_gap_max,
        near_miss_close_retention_penalty_weight=BASE_PROFILE.near_miss_close_retention_penalty_weight,
    )

def run_all_days(pro, all_dates, test_dates):
    """主回测逻辑：返回 {profile_name: [daily_results]}"""
    next_map = {d: all_dates[i+1] for i, d in enumerate(all_dates) if i+1 < len(all_dates)}
    
    tc_values   = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    tc2d_values = [0.05, 0.10, 0.15, 0.20]
    
    variants = {
        f"tc{tc_w:.2f}_tc2d{tc2d_w:.2f}": make_variant_profile(tc_w, tc2d_w)
        for tc_w, tc2d_w in itertools.product(tc_values, tc2d_values)
    }
    print(f"共 {len(variants)} 个变体")
    
    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")
    
    profile_stats = {pn: [] for pn in variants}
    
    for di, test_date in enumerate(test_dates):
        next_date = next_map.get(test_date)
        if not next_date:
            continue
        print(f"\n[{di+1}/{len(test_dates)}] {test_date} -> {next_date}", flush=True)
        
        try:
            df = pro.daily(trade_date=test_date)
        except Exception as e:
            print(f"  API error: {e}"); continue
        if df is None or df.empty:
            print("  empty daily"); continue
        
        df = df.merge(sb, on="ts_code", how="left")
        df = df[df["amount"] >= 100000]
        df = df[~df["name"].str.contains("ST|退", na=False)]
        df = df[~bk.build_beijing_exchange_mask(df["ts_code"])]
        df = df[df["pct_chg"].between(-9.5, 9.5)]
        
        try:
            import pandas as pd
            dfn = pro.daily(trade_date=next_date)[["ts_code","pct_chg","open","close","high","pre_close"]]
            dfn = dfn.rename(columns={"pct_chg": "next_ret"})
            import numpy as np_
            dfn["open_to_close_ret"] = np_.where(dfn["open"] > 0, (dfn["close"] - dfn["open"]) / dfn["open"] * 100, np_.nan)
            dfn["next_high_pct"] = np_.where(dfn["pre_close"] > 0, (dfn["high"] - dfn["pre_close"]) / dfn["pre_close"] * 100, np_.nan)
            dfn = dfn[["ts_code","next_ret","open_to_close_ret","next_high_pct"]]
        except Exception as e:
            print(f"  next-day error: {e}"); continue
        df = df.merge(dfn, on="ts_code", how="inner")
        
        # 获取历史数据计算因子
        import pandas as pd
        codes = df["ts_code"].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i:i+80]
            try:
                h = pro.daily(ts_code=",".join(batch), start_date="20250601", end_date=test_date)
                if h is not None and not h.empty:
                    history.append(h)
            except:
                continue
        if not history:
            continue
        
        hist = pd.concat(history, ignore_index=True)
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code","trade_date"])
        
        stock_factors = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 22:
                continue
            f = bk.compute_factors(g, None)
            if f:
                stock_factors[code] = f
        
        df = df[df["ts_code"].isin(stock_factors.keys())].copy()
        if len(df) < 50:
            print(f"  too few stocks ({len(df)})")
            continue
        
        print(f"  {len(df)}只候选, {len(stock_factors)}只有因子", flush=True)
        
        # 对每个变体评分
        for variant_name, profile in variants.items():
            weights = {
                factor_key: float(getattr(profile, weight_field, 0.0))
                for factor_key, weight_field in bk.PROFILE_WEIGHT_FIELDS.items()
            }
            
            df2 = df.copy()
            scores = []
            for _, row in df2.iterrows():
                f = stock_factors.get(row["ts_code"])
                if f is None:
                    scores.append(0.0)
                else:
                    scores.append(bk.compute_score(f, weights))
            df2["score"] = scores
            
            sel = df2[df2["score"] >= profile.select_threshold]
            if len(sel) < 3:
                continue
            
            next_rets = sel["next_ret"].dropna()
            if len(next_rets) < 3:
                continue
            
            wr = float((next_rets > 0).mean())
            avg_ret = float(next_rets.mean())
            
            otc = sel["open_to_close_ret"].dropna()
            high2 = sel["next_high_pct"].dropna()
            
            profile_stats[variant_name].append({
                "date": test_date,
                "n_sel": len(sel),
                "wr": wr,
                "avg_ret": avg_ret,
                "open_wr": float((otc > 0).mean()) if len(otc) >= 3 else None,
                "high2_rate": float((high2 >= 2.0).mean()) if len(high2) >= 3 else None,
            })
    
    return profile_stats

def compute_summary(daily_stats: list[dict]) -> dict:
    import numpy as np
    if not daily_stats:
        return {}
    all_rets = [d["avg_ret"] for d in daily_stats]
    all_wrs  = [d["wr"] for d in daily_stats]
    all_otc  = [d["open_wr"] for d in daily_stats if d.get("open_wr") is not None]
    all_h2   = [d["high2_rate"] for d in daily_stats if d.get("high2_rate") is not None]
    return {
        "n_days": len(daily_stats),
        "avg_wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_rets)),
        "sharpe": float(np.mean(all_rets) / (np.std(all_rets)+1e-8) * np.sqrt(250)),
        "open_wr": float(np.mean(all_otc)) if all_otc else None,
        "high2_rate": float(np.mean(all_h2)) if all_h2 else None,
    }

def main():
    import tushare as ts
    from datetime import datetime, timedelta
    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()
    
    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=cal_start, end_date=cal_end)
    all_dates = sorted(cal[cal["is_open"]==1]["cal_date"].tolist())
    test_dates = [d for d in all_dates if d <= cal_end][-25:]  # 25天覆盖更多
    
    print(f"=== Round 89 Task 2: tc权重网格搜索 ===")
    print(f"回测窗口: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}天)")
    
    profile_stats = run_all_days(pro, all_dates, test_dates)
    
    # 汇总
    summaries = {}
    for name, daily in profile_stats.items():
        if daily:
            summaries[name] = compute_summary(daily)
    
    if not summaries:
        print("没有有效结果！")
        return
    
    # 解析参数
    rows = []
    for name, s in summaries.items():
        parts = name.split("_")
        tc_w = float(parts[0].replace("tc",""))
        tc2d_w = float(parts[1].replace("tc2d",""))
        rows.append({
            "tc_w": tc_w, "tc2d_w": tc2d_w,
            **s
        })
    
    rows.sort(key=lambda x: x.get("avg_ret", 0), reverse=True)
    
    print(f"\n=== 结果 Top 15（按日均收益排序）===")
    print(f"{'tc_w':>5} {'tc2d_w':>6} {'avg_wr':>7} {'avg_ret':>8} {'sharpe':>7} {'open_wr':>8} {'high2':>6} {'days':>5}")
    print("-"*65)
    for r in rows[:15]:
        open_wr = f"{r['open_wr']:.1%}" if r.get('open_wr') else "N/A"
        high2 = f"{r['high2_rate']:.1%}" if r.get('high2_rate') else "N/A"
        print(f"  {r['tc_w']:>3.2f}   {r['tc2d_w']:>4.2f}   {r['avg_wr']:>5.1%}   {r['avg_ret']:>+6.3f}%   {r['sharpe']:>5.2f}   {open_wr:>7}  {high2:>5}   {r['n_days']:>4}")
    
    best = rows[0]
    print(f"\n🏆 最优参数:")
    print(f"  trend_continuation_weight = {best['tc_w']}")
    print(f"  trend_continuation_2d_weight = {best['tc2d_w']}")
    print(f"  日均收益 = {best['avg_ret']:+.3f}%")
    print(f"  日均胜率 = {best['avg_wr']:.1%}")
    print(f"  Sharpe(年化) = {best['sharpe']:.2f}")
    
    out = Path("data/reports/btst_round89_tc_grid_results.json")
    out.write_text(json.dumps({"summaries": rows, "per_day": {k: v for k, v in profile_stats.items()}}, indent=2, ensure_ascii=False))
    print(f"\n✅ 结果已保存: {out}")

if __name__ == "__main__":
    main()
