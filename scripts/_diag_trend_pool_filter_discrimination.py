#!/usr/bin/env python3
"""全 universe trend 池预筛区分度诊断 (loop 43): trend 因子的池预筛在全 universe 上是否有区分度?

北极星路径 (decision-state R6 RESOLVED-as-selection-bias-artifact 之后):
  R6 的"负预测力"是选择偏差伪象 (c303/c304 已确认 do-not-flip). 真正的杠杆是
  **池预筛机制**, 不是排序权重. aff989be 在 commit message 里断言 "trend 几乎全
  bullish, 无区分度 — 完全无用, 需要重新设计", 但这只是一个**定性断言**, 从未
  用干净的诊断量化. 本脚本量化它.

回答的问题 (selection-bias-free, 全 universe):
  1. **区分度**: trend_direction 在全 universe 上的分布 (bullish/bearish/neutral 占比)?
     若 ~100% bullish → trend 预筛等于"全选", 无区分度 (aff989be 断言).
  2. **方向有效性**: trend bullish 子集 vs bearish 子集的 T+1 收益差. 若 trend 无区分度,
     bullish 和 bearish 子集收益应无显著差. 若 bullish 跑赢 → trend 方向有效 (即使
     分布偏斜, 预筛仍有方向价值).
  3. **预筛增量**: trend 预筛 (保留 bullish) 后的等权组合 vs 全 universe 等权的 T+1
     delta. 若 delta≈0 → 预筛无增量 (因为几乎全选). 若 delta>0 → 预筛有方向增量.

方法限制 (诚实披露):
  - light-stage (纯技术 0 LLM): trend 因子是 light-stage 的 trend_strategy signal
    (复用 _backtest_light_stage_universe 的 compute_factor_snapshot). 不含 LLM 因子.
  - T+1 horizon: 与 aff989be/c303 同 (light-stage 标准 horizon). R6 BUY 决策是 T+5/T+10,
    但 T+1 是池预筛区分度检测的足够 signal.

复用 infra: scripts/_backtest_light_stage_universe.py 的 helpers
(get_trading_dates/get_universe_for_date/get_history_batch/compute_factor_snapshot).
不修改原 script.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from scripts._backtest_light_stage_universe import (  # noqa: E402
    compute_factor_snapshot,
    get_history_batch,
    get_trading_dates,
    get_universe_for_date,
    _get_pro,
)

logger = logging.getLogger("trend_pool_filter_diag")


def trend_direction_distribution(directions: list[int]) -> dict[str, float]:
    """Fraction of universe in each trend bucket (pure). c310: extracted from run()
    for testability — the aff989be 'trend 几乎全 bullish, 无区分度' claim rests on
    this distribution.

    Returns {'bullish': frac, 'neutral': frac, 'bearish': frac}. Empty input →
    all-zero dict. trend_direction ∈ {1 (bullish), 0 (neutral), -1 (bearish)}.
    """
    n = len(directions)
    if n == 0:
        return {"bullish": 0.0, "neutral": 0.0, "bearish": 0.0}
    return {
        "bullish": sum(1 for d in directions if d > 0) / n,
        "neutral": sum(1 for d in directions if d == 0) / n,
        "bearish": sum(1 for d in directions if d < 0) / n,
    }


def trend_directional_edge(bullish_rets: list[float], bearish_rets: list[float]) -> dict[str, float]:
    """Does trend direction predict T+1 return? (pure). c310: the second half of the
    aff989be claim — even if trend is ~all-bullish, is the *direction* meaningful?

    Returns {'bullish_mean', 'bearish_mean', 'delta', 'bullish_n', 'bearish_n'}.
    delta = bullish_mean - bearish_mean (positive → trend bullish outperforms, i.e.
    direction is informative). Empty side → mean is NaN, delta is NaN.
    """
    b_mean = float(np.mean(bullish_rets)) if bullish_rets else float("nan")
    s_mean = float(np.mean(bearish_rets)) if bearish_rets else float("nan")
    delta = b_mean - s_mean if not (np.isnan(b_mean) or np.isnan(s_mean)) else float("nan")
    return {
        "bullish_mean": b_mean,
        "bearish_mean": s_mean,
        "delta": delta,
        "bullish_n": len(bullish_rets),
        "bearish_n": len(bearish_rets),
    }


def pool_filter_verdict(bullish_frac: float, directional_delta: float) -> str:
    """Classify whether the trend pool-filter discriminates (pure). Returns
    'no_filter' | 'weak_filter' | 'directional_filter' | 'strong_filter'.

    - 'no_filter': bullish_frac > 0.95 AND |directional_delta| < 0.05 → trend
      pre-filter is ~all-pass with no directional edge → aff989be claim CONFIRMED
      (trend pool-filter has zero discrimination; leverage lives elsewhere).
    - 'weak_filter': bullish_frac > 0.95 but directional edge exists (|delta|>=0.05)
      → distribution skewed but direction still informative (filter is coarse).
    - 'directional_filter': bullish_frac in [0.5, 0.95] → filter is meaningfully
      selective (excludes a real slice of the universe).
    - 'strong_filter': bullish_frac < 0.5 → filter is highly selective.
    """
    if bullish_frac > 0.95:
        if abs(directional_delta) < 0.05:
            return "no_filter"
        return "weak_filter"
    if bullish_frac >= 0.5:
        return "directional_filter"
    return "strong_filter"


def run(n_days: int = 20, end_date: str | None = None) -> None:
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_days + 1, end_date=end_date)
    test_dates = trade_dates[:-1]
    print(f"\n全 universe trend 池预筛区分度诊断: {test_dates[0]}~{test_dates[-1]} ({len(test_dates)} 日)")
    print(f"问: aff989be 断言 'trend 几乎全 bullish, 无区分度' 是否成立?")
    print(f"{'=' * 90}")

    all_rows: list[dict[str, float | int]] = []
    per_day_bull_frac: list[float] = []
    for di, test_date in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        t0 = time.time()
        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            continue
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
            continue
        universe = universe.merge(dfn, on="ts_code", how="inner")
        if len(universe) < 100:
            continue
        history_start = (datetime.strptime(test_date, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        hist = get_history_batch(pro, universe["ts_code"].tolist(), history_start, test_date)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])
        snapshots: dict[str, Any] = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 50:
                continue
            snap = compute_factor_snapshot(code, g.set_index("trade_date"))
            if snap is not None:
                snapshots[code] = snap
        if len(snapshots) < 100:
            continue
        rows = []
        for _, r in universe.iterrows():
            snap = snapshots.get(r["ts_code"])
            if snap is None:
                continue
            rows.append({
                "ts_code": r["ts_code"],
                "next_ret": float(r["next_ret"]),
                "trend_direction": int(snap.trend_direction),
            })
        df_day = pd.DataFrame(rows)
        if df_day.empty:
            continue
        dist = trend_direction_distribution(df_day["trend_direction"].tolist())
        per_day_bull_frac.append(dist["bullish"])
        for _, r in df_day.iterrows():
            all_rows.append({"trend_direction": int(r["trend_direction"]), "next_ret": float(r["next_ret"])})
        if (di + 1) % 5 == 0 or di == 0:
            print(f"  [{di+1}/{len(test_dates)}] {test_date}: n={len(df_day)} bullish={dist['bullish']:.1%} "
                  f"neutral={dist['neutral']:.1%} bearish={dist['bearish']:.1%} ({time.time()-t0:.1f}s)")

    if not all_rows:
        print("无数据")
        return
    df = pd.DataFrame(all_rows)
    print(f"\n{'=' * 90}")
    print(f"全 universe 聚合 (n={len(df)} records, {len(per_day_bull_frac)} 日, T+1):")
    avg_bull_frac = float(np.mean(per_day_bull_frac)) if per_day_bull_frac else 0.0
    print(f"  日均 bullish 占比: {avg_bull_frac:.1%}  (aff989be 断言 '~100%')")
    dist_overall = trend_direction_distribution(df["trend_direction"].tolist())
    print(f"  全 universe 分布: bullish={dist_overall['bullish']:.1%} neutral={dist_overall['neutral']:.1%} bearish={dist_overall['bearish']:.1%}")

    print(f"\n  trend 方向子集 T+1 收益:")
    print(f"  {'方向':<12} {'n':>8} {'winrate':>9} {'mean T+1':>10}")
    bull = df[df["trend_direction"] > 0]["next_ret"]
    bear = df[df["trend_direction"] < 0]["next_ret"]
    neut = df[df["trend_direction"] == 0]["next_ret"]
    for label, s in [("bullish", bull), ("neutral", neut), ("bearish", bear)]:
        if len(s):
            print(f"  {label:<12} {len(s):>8} {(s > 0).mean():>8.1%} {s.mean():>+9.3f}%")

    edge = trend_directional_edge(bull.tolist(), bear.tolist())
    print(f"\n  方向增量 (bullish - bearish mean T+1): {edge['delta']:+.3f}%  "
          f"(bullish n={edge['bullish_n']}, bearish n={edge['bearish_n']})")

    # 预筛增量: 保留 bullish 的等权组合 vs 全 universe 等权
    eq_all = float(df["next_ret"].mean())
    eq_bull = float(bull.mean()) if len(bull) else float("nan")
    filter_delta = eq_bull - eq_all if not np.isnan(eq_bull) else float("nan")
    print(f"  预筛增量 (trend-bullish 等权 vs 全 universe 等权): {filter_delta:+.3f}%")

    print(f"\n{'=' * 90}")
    verdict = pool_filter_verdict(avg_bull_frac, edge["delta"] if not np.isnan(edge["delta"]) else 0.0)
    print("判读 (aff989be 'trend 无区分度' 断言是否成立):")
    if verdict == "no_filter":
        print(f"  ✅ 断言成立: trend bullish 占比 {avg_bull_frac:.1%} (>95%) 且方向增量 |{edge['delta']:+.3f}%|<0.05%")
        print(f"     → trend 池预筛 = 近似'全选', 既无分布区分度也无方向增量.")
        print(f"     → 北极星路径确认: 杠杆在**池预筛机制本身**, 不在排序权重 (与 R6 RESOLVED 结论一致).")
    elif verdict == "weak_filter":
        print(f"  ≈ 部分成立: trend bullish 占比 {avg_bull_frac:.1%} (>95%, 分布偏斜) 但方向增量 {edge['delta']:+.3f}% 存在")
        print(f"     → 预筛分布无区分度, 但方向仍有信号; 预筛过粗 (只留 bullish 损失了方向细节).")
    elif verdict == "directional_filter":
        print(f"  ⚠️ 断言不成立: trend bullish 占比 {avg_bull_frac:.1%} (50-95%), 预筛有实际筛选作用.")
        print(f"     → trend 预筛不是'全选', aff989be 断言过强; 池预筛机制可能本身有效.")
    else:  # strong_filter
        print(f"  ⚠️ 断言不成立: trend bullish 占比 {avg_bull_frac:.1%} (<50%), 预筛高度选择性.")
        print(f"     → trend 预筛是强筛选, 与'无区分度'断言矛盾; 重新审视 aff989be 结论.")
    print(f"\n注意: light-stage (纯技术 0 LLM) + T+1 horizon — 池预筛区分度的足够 signal, "
          f"但完整确认需 T+5/T+10 + 全模型.")


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    import argparse
    ap = argparse.ArgumentParser(description="全 universe trend 池预筛区分度诊断 — aff989be '无区分度' 断言是否成立")
    ap.add_argument("--n-days", type=int, default=20)
    ap.add_argument("--end-date", default="")
    a = ap.parse_args()
    run(n_days=a.n_days, end_date=a.end_date or None)


if __name__ == "__main__":
    main()
