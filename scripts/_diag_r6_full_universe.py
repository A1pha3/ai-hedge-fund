#!/usr/bin/env python3
"""R6 全 universe 诊断 (c303, loop 36): composite_score 的"负预测力"是否是选择偏差伪象?

回答的问题 (selection-bias-free):
  在**全 A 股 universe** (不是推荐池) 上, 用 light-stage composite score
  (trend+MR 技术因子, 当前默认权重 trend:0.65/MR:0.35 — aff989be revert 后的权重)
  排序, Top-N 等权组合的 T+1 收益 vs **等权全 universe** 收益, 跨 N 日聚合.

判读 (对照 aff989be MR precedes):
  - Top-N-by-score **跑赢** 等权全 universe → composite_score 全 universe 有正预测力;
    推荐池里的"负预测力"是**选择偏差伪象** (像 MR C225 被 aff989be 推翻那样) →
    owner **不应** flip/reweight, R6 框架 (c297/c298) 被推翻.
  - Top-N-by-score **跑输** 等权全 universe → 负预测力在全 universe 也成立 →
    真实 model defect → flip/reweight 有据.

方法限制 (诚实披露):
  - light-stage (纯技术 0 LLM): 不含 fundamental/event_sentiment LLM 因子.
    若负预测力主要来自 LLM 因子, 此路线看不到. 全模型 (with LLM) 是 c302 §7 的重型路线.
  - T+1 horizon: 与 aff989be 同 (light-stage 的标准 horizon); R6 的 BUY 决策是 T+5/T+10,
    但 T+1 是 selection-bias 检测的足够 signal (MR precedes 就用 T+1).

复用 infra: scripts/_backtest_light_stage_universe.py 的 data/scoring helpers
(get_trading_dates/get_universe_for_date/get_history_batch/compute_factor_snapshot/
provisional_score/WEIGHTS_OLD). 不修改原 script (它做 OLD vs NEW 权重对比).
"""
from __future__ import annotations

import argparse
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
# 复用 _backtest_light_stage_universe 的 helpers (模块级函数, run_backtest 由 __main__ 守卫)
from scripts._backtest_light_stage_universe import (  # noqa: E402
    WEIGHTS_OLD,
    compute_factor_snapshot,
    get_history_batch,
    get_trading_dates,
    get_universe_for_date,
    provisional_score,
    _get_pro,
)

logger = logging.getLogger("r6_full_universe_diag")


def summarize_r6_diagnostic(daily_records: list[dict[str, Any]], top_n_list: tuple[int, ...]) -> dict[str, Any]:
    """Aggregate per-day R6 diagnostic records into a summary (pure, no I/O).

    c308 (loop 41): extracted from run_r6_diagnostic for testability — the R6
    selection-bias conclusion (biggest finding of the multi-session arc) rests on
    this aggregation, so it must be unit-tested, not buried inline.

    Input: list of per-day dicts each with 'eq_all_ret' and f'top{tn}_ret' /
    f'top{tn}_beats_eq' for each tn. Output:
      {'n_days', 'eq_all': {'mean','winrate'}, 'top_n': {tn: {'mean','winrate','beats_eq','delta'}}}
    Empty input → {'n_days': 0, 'eq_all': None, 'top_n': {}}.
    """
    if not daily_records:
        return {"n_days": 0, "eq_all": None, "top_n": {}}
    n = len(daily_records)
    eq_rets = [r["eq_all_ret"] for r in daily_records]
    eq_mean = sum(eq_rets) / n
    eq_win = sum(1 for r in eq_rets if r > 0) / n
    out: dict[str, Any] = {"n_days": n, "eq_all": {"mean": eq_mean, "winrate": eq_win}, "top_n": {}}
    for tn in top_n_list:
        tn_rets = [r[f"top{tn}_ret"] for r in daily_records]
        tn_mean = sum(tn_rets) / n
        tn_win = sum(1 for r in tn_rets if r > 0) / n
        tn_beats = sum(1 for r in daily_records if r[f"top{tn}_beats_eq"]) / n
        out["top_n"][tn] = {"mean": tn_mean, "winrate": tn_win, "beats_eq": tn_beats, "delta": tn_mean - eq_mean}
    return out


def r6_selection_bias_verdict(top3_delta: float, top3_beats: float) -> str:
    """Classify the R6 selection-bias test result (pure). Returns positive|negative|ambiguous.

    positive: Top-3 BEATS equal-weight on full universe (delta>0 AND beats>0.5) →
      selection-bias artifact confirmed (pool 'negative predictive power' is spurious).
    negative: Top-3 LOSES (delta<0 AND beats<0.5) → genuine model defect.
    ambiguous: mixed signal → needs more N or full-model.
    """
    if top3_delta > 0 and top3_beats > 0.5:
        return "positive"
    if top3_delta < 0 and top3_beats < 0.5:
        return "negative"
    return "ambiguous"


def run_r6_diagnostic(n_days: int = 60, end_date: str | None = None, top_n_list: tuple[int, ...] = (3, 50)) -> None:
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_days + 1, end_date=end_date)
    if len(trade_dates) < 2:
        print("交易日不足")
        return
    test_dates = trade_dates[:-1]
    print(f"\n{'=' * 100}")
    print(f"R6 全 universe 诊断: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} 日期)")
    print(f"score 权重 = WEIGHTS_OLD (当前默认, post-aff989be): {WEIGHTS_OLD}")
    print(f"Top-N 对比: {top_n_list}  vs  等权全 universe")
    print(f"{'=' * 100}")

    # per-day records
    daily: list[dict[str, Any]] = []
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
            rows.append({"ts_code": r["ts_code"], "next_ret": float(r["next_ret"]), "score": provisional_score(snap, WEIGHTS_OLD)})
        df_day = pd.DataFrame(rows)
        if df_day.empty:
            continue
        eq_all_ret = float(df_day["next_ret"].mean())  # 等权全 universe
        rec: dict[str, Any] = {"date": test_date, "n_universe": len(df_day), "eq_all_ret": eq_all_ret}
        for tn in top_n_list:
            top = df_day.nlargest(tn, "score")
            rec[f"top{tn}_ret"] = float(top["next_ret"].mean())
            rec[f"top{tn}_beats_eq"] = rec[f"top{tn}_ret"] > eq_all_ret
        daily.append(rec)
        if (di + 1) % 10 == 0 or di == 0:
            print(f"  [{di+1}/{len(test_dates)}] {test_date}: n={len(df_day)} eq_all={eq_all_ret:+.3f}% top3={rec['top3_ret']:+.3f}% ({time.time()-t0:.1f}s)")

    if not daily:
        print("\n无有效数据")
        return
    summary = summarize_r6_diagnostic(daily, top_n_list)
    df = pd.DataFrame(daily)  # kept for the per-day mean/winrate display formatting
    print(f"\n{'=' * 100}")
    print(f"聚合 (n={summary['n_days']} 日, 全 universe, light-stage 纯技术 0 LLM, T+1):")
    eq = summary["eq_all"]
    print(f"  等权全 universe:        mean={eq['mean']:+.3f}%  winrate={eq['winrate']:.1%}")
    for tn in top_n_list:
        s = summary["top_n"][tn]
        print(f"  Top-{tn} by score:        mean={s['mean']:+.3f}%  winrate={s['winrate']:.1%}  | 跑赢等权的日数比={s['beats_eq']:.1%}  | delta vs 等权={s['delta']:+.3f}%")
    print(f"{'=' * 100}")
    # 判读 (c308: pure verdict function)
    top3 = summary["top_n"][3]
    verdict = r6_selection_bias_verdict(top3["delta"], top3["beats_eq"])
    print("\n判读 (R6 选择偏差检验, 对照 aff989be MR precede):")
    if verdict == "positive":
        print(f"  ✅ Top-3 by score 在全 universe **跑赢** 等权 (delta={top3['delta']:+.3f}%, {top3['beats_eq']:.1%} 日).")
        print(f"     → composite_score 全 universe 有**正预测力**; 推荐池的'负预测力'(c297/c298) 是**选择偏差伪象**.")
        print(f"     → owner **不应** flip/reweight; R6 pool-based A/B 框架被推翻 (像 MR C225 那样).")
    elif verdict == "negative":
        print(f"  ⚠️ Top-3 by score 在全 universe 也**跑输** 等权 (delta={top3['delta']:+.3f}%, {top3['beats_eq']:.1%} 日).")
        print(f"     → 负预测力在全 universe 也成立 → 真实 model defect, flip/reweight 有据 (但仍需 T+5/T+10 + 全模型 LLM 确认).")
    else:
        print(f"  ≈ Top-3 vs 等权 在全 universe 上分歧 (delta={top3['delta']:+.3f}%, {top3['beats_eq']:.1%} 日) — 不显著, 需更大 N 或全模型.")
    print(f"\n注意: light-stage (纯技术 0 LLM) — 不含 LLM 因子. 全模型 (with LLM) 是 c302 §7 重型路线, 未跑.")


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    parser = argparse.ArgumentParser(description="R6 全 universe 诊断 — composite_score 负预测力是否是选择偏差伪象")
    parser.add_argument("--n-days", type=int, default=60)
    parser.add_argument("--end-date", default="")
    parser.add_argument("--top-n", type=int, nargs="+", default=[3, 50])
    args = parser.parse_args()
    run_r6_diagnostic(n_days=args.n_days, end_date=args.end_date or None, top_n_list=tuple(args.top_n))


if __name__ == "__main__":
    main()
