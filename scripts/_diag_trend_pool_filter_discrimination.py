#!/usr/bin/env python3
"""全 universe trend 池预筛区分度诊断 (loop 43 c311 / loop 44 c312 multi-horizon):
trend 因子的池预筛在全 universe 上是否有区分度?

北极星路径 (decision-state R6 RESOLVED-as-selection-bias-artifact 之后):
  R6 的"负预测力"是选择偏差伪象 (c303/c304 已确认 do-not-flip). 真正的杠杆是
  **池预筛机制**, 不是排序权重. aff989be 在 commit message 里断言 "trend 几乎全
  bullish, 无区分度 — 完全无用, 需要重新设计", 但这只是一个**定性断言**, 从未
  用干净的诊断量化. 本脚本量化它.

回答的问题 (selection-bias-free, 全 universe):
  1. **区分度**: trend_direction 在全 universe 上的分布 (bullish/bearish/neutral 占比)?
     若 ~100% bullish → trend 预筛等于"全选", 无区分度 (aff989be 断言).
  2. **方向有效性**: trend bullish 子集 vs bearish 子集的 T+1/T+5/T+10 收益差. 若 trend
     无区分度, bullish 和 bearish 子集收益应无显著差. 若 bullish 跑赢 → trend 方向
     有效 (即使分布偏斜, 预筛仍有方向价值).
  3. **预筛增量**: trend 预筛 (保留 bullish) 后的等权组合 vs 全 universe 等权的
     T+1/T+5/T+10 delta. 若 delta≈0 → 预筛无增量. 若 delta>0 → 预筛有方向增量.

loop 44 (c312) 改动:
  c311 仅测 T+1, 并在脚本里明确标注 "完整确认需 T+5/T+10 + 全模型". 但 R6 BUY 决策
  用 T+5/T+10 — C-R6-POOL-FILTER-REDESIGN 决策包不能只依赖 T+1: 若 trend 信号在
  T+1→T+5 反转, 判读会翻转. 本 loop 把 horizon 扩到 T+1/T+5/T+10, 每个 horizon 独立
  判读, 并对未成熟 horizon 诚实跳过 (NS-17 silent-skip disease class).

方法限制 (诚实披露):
  - light-stage (纯技术 0 LLM): trend 因子是 light-stage 的 trend_strategy signal
    (复用 _backtest_light_stage_universe 的 compute_factor_snapshot). 不含 LLM 因子.
  - multi-horizon: T+1/T+5/T+10 (loop 44). 完整确认仍需全模型 (c302 §7).
  - maturity: 距末日 < horizon 的 test_date 在该 horizon 上诚实标记未成熟, 不用 T+1
    替代 (避免 look-ahead / maturity-faking).

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

# North-star BUY decision horizons (R6). c311 (loop 43) measured T+1 only; loop
# 44 adds T+5/T+10 so the pool-filter verdict rests on the decision-relevant
# horizon, not a proxy. A trend signal that inverts across horizons would
# reverse the verdict, so all three are reported.
HORIZONS: tuple[int, ...] = (1, 5, 10)


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


# ---------------------------------------------------------------------------
# T+5/T+10 horizon extension (loop 44) — the north-star BUY horizon.
#
# c311 (loop 43) measured the trend pool-filter at T+1 only and flagged
# "完整确认需 T+5/T+10 + 全模型". R6 BUY decisions use T+5/T+10, so a
# pool-filter redesign decision pack must not rest on T+1 alone — a trend
# signal that inverts between T+1 and T+5 would reverse the verdict. These
# pure helpers add the decision-relevant horizons. Maturity handling is
# critical: the most recent test_dates have no forward T+5/T+10 return, so
# per-horizon aggregation drops them rather than silently reusing T+1
# (look-ahead / maturity-faking — same NS-17 disease class retired in F5).
# ---------------------------------------------------------------------------


def cumulative_horizon_return(pct_chgs: list[float], horizon: int) -> float:
    """Geometric cumulative return over the first `horizon` daily pct changes (pure).

    T+1 with [1.5] → 1.5%. T+5 with five daily pct chgs → (Π(1+rᵢ/100) - 1) * 100.
    Insufficient history (< horizon entries) or empty → NaN (maturity signal,
    NOT 0 — 0 is a real return and would fake maturity).
    """
    if len(pct_chgs) < horizon:
        return float("nan")
    factor = 1.0
    for i in range(horizon):
        factor *= 1.0 + pct_chgs[i] / 100.0
    return (factor - 1.0) * 100.0


def mature_horizons(di_index: int, n_dates: int, horizons: tuple[int, ...]) -> frozenset[int]:
    """Which forward horizons have a mature return at trade_dates[di_index]? (pure).

    Returns the set of h ∈ horizons such that di_index + h is a valid index in
    trade_dates (strict < n_dates). The last index has no mature horizon; the
    penultimate has only T+1. This is the maturity gate that prevents the
    diagnostic from reusing T+1 returns where a T+5/T+10 return is unavailable.
    """
    return frozenset(h for h in horizons if di_index + h < n_dates)


def aggregate_horizon(rows: list[dict[str, Any]], horizon: str) -> dict[str, list[Any]]:
    """Group rows' returns at `horizon` by trend direction (pure).

    Each row is {"trend_direction": int, "rets": {horizon_str: float | None}}.
    Rows missing or with None return at `horizon` are dropped (maturity
    honesty — they did not mature, not "zero return"). Returns split lists so
    downstream edge/distribution math reuses the existing pure helpers.
    """
    bullish: list[float] = []
    bearish: list[float] = []
    neutral: list[float] = []
    directions: list[int] = []
    for row in rows:
        rets = row.get("rets", {}) or {}
        if horizon not in rets:
            continue
        val = rets[horizon]
        if val is None:
            continue
        d = int(row["trend_direction"])
        directions.append(d)
        if d > 0:
            bullish.append(float(val))
        elif d < 0:
            bearish.append(float(val))
        else:
            neutral.append(float(val))
    return {
        "bullish_rets": bullish,
        "bearish_rets": bearish,
        "neutral_rets": neutral,
        "directions": directions,
    }


def per_horizon_summary(rows: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
    """Distribution + directional edge + verdict for one horizon (pure).

    Returns {"n", "bullish_frac", "edge", "verdict"}. Reuses
    trend_direction_distribution / trend_directional_edge / pool_filter_verdict
    so the per-horizon verdict uses identical thresholds as T+1. Empty rows →
    verdict "no_data" (distinct from real verdicts; signals the horizon did
    not mature for any date).
    """
    agg = aggregate_horizon(rows, horizon)
    n = len(agg["directions"])
    if n == 0:
        return {
            "n": 0,
            "bullish_frac": 0.0,
            "edge": {"bullish_mean": float("nan"), "bearish_mean": float("nan"), "delta": float("nan")},
            "verdict": "no_data",
        }
    dist = trend_direction_distribution(agg["directions"])
    edge = trend_directional_edge(agg["bullish_rets"], agg["bearish_rets"])
    delta = edge["delta"] if not np.isnan(edge["delta"]) else 0.0
    verdict = pool_filter_verdict(dist["bullish"], delta)
    return {"n": n, "bullish_frac": dist["bullish"], "edge": edge, "verdict": verdict}


def _fetch_forward_pcts(pro, trade_dates: list[str], start_idx: int, end_idx: int) -> dict[str, dict[str, float]]:
    """Fetch per-ts_code daily pct_chg for trade_dates[start_idx:end_idx] (cached by date).

    Returns {trade_date: {ts_code: pct_chg}}. A forward date may be shared across
    many test_dates (e.g. trade_dates[di+1] is T+1 for di but T-? for di+1's
    forward window); caching avoids re-fetching the same calendar date daily.
    The cache is the maturity source: a missing date ⇒ that horizon's forward
    return is unavailable for the test_date that needs it.
    """
    cache: dict[str, dict[str, float]] = {}
    for di in range(start_idx, min(end_idx, len(trade_dates))):
        td = trade_dates[di]
        if td in cache:
            continue
        try:
            dfn = pro.daily(trade_date=td)
        except Exception:
            cache[td] = {}
            continue
        if dfn is None or dfn.empty:
            cache[td] = {}
            continue
        cache[td] = dict(zip(dfn["ts_code"].tolist(), dfn["pct_chg"].astype(float).tolist()))
    return cache


def run(n_days: int = 20, end_date: str | None = None) -> None:
    """Multi-horizon (T+1/T+5/T+10) trend pool-filter discrimination.

    Loop 44 extends c311 (T+1 only) to the decision-relevant north-star BUY
    horizons. The pool pre-filter must be judged at T+5/T+10, not T+1: a trend
    signal that inverts across horizons would reverse the verdict, and the
    C-R6-POOL-FILTER-REDESIGN decision pack must not rest on T+1 alone.
    """
    horizons = HORIZONS
    max_h = max(horizons)
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    # Reserve max_h forward trade dates so the earliest test_date can mature to T+max_h.
    trade_dates = get_trading_dates(pro, n_days + max_h, end_date=end_date)
    test_dates = trade_dates[:n_days]
    horizon_strs = [str(h) for h in horizons]
    print(f"\n全 universe trend 池预筛区分度诊断 (multi-horizon): {test_dates[0]}~{test_dates[-1]} ({len(test_dates)} 日)")
    print(f"问: aff989be 断言 'trend 几乎全 bullish, 无区分度' 在 T+1/T+5/T+10 上是否一致成立?")
    print(f"{'=' * 100}")

    all_rows: list[dict[str, Any]] = []
    per_day_bull_frac: list[float] = []
    fwd_cache: dict[str, dict[str, float]] = {}
    for di, test_date in enumerate(test_dates):
        t0 = time.time()
        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            continue
        # Forward window: trade_dates[di+1 .. di+max_h]. Fetch any not yet cached.
        for fi in range(di + 1, di + 1 + max_h):
            if fi < len(trade_dates) and trade_dates[fi] not in fwd_cache:
                try:
                    dfn = pro.daily(trade_date=trade_dates[fi])
                    fwd_cache[trade_dates[fi]] = dict(zip(dfn["ts_code"].tolist(), dfn["pct_chg"].astype(float).tolist())) if dfn is not None and not dfn.empty else {}
                except Exception:
                    fwd_cache[trade_dates[fi]] = {}
        mature = mature_horizons(di, len(trade_dates), horizons)
        if not mature:
            continue
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
            # Per-horizon cumulative forward return (None where immature / missing ticker).
            rets: dict[str, float | None] = {}
            for h in horizons:
                if h not in mature:
                    rets[str(h)] = None
                    continue
                pcts: list[float] = []
                ok = True
                for fi in range(di + 1, di + 1 + h):
                    td = trade_dates[fi]
                    p = fwd_cache.get(td, {}).get(r["ts_code"])
                    if p is None:
                        ok = False
                        break
                    pcts.append(p)
                rets[str(h)] = cumulative_horizon_return(pcts, h) if ok else None
            rows.append(
                {
                    "ts_code": r["ts_code"],
                    "trend_direction": int(snap.trend_direction),
                    "rets": rets,
                }
            )
        df_day = pd.DataFrame(rows)
        if df_day.empty:
            continue
        dist = trend_direction_distribution(df_day["trend_direction"].tolist())
        per_day_bull_frac.append(dist["bullish"])
        for _, r in df_day.iterrows():
            all_rows.append({"trend_direction": int(r["trend_direction"]), "rets": dict(r["rets"])})
        if (di + 1) % 5 == 0 or di == 0 or di == len(test_dates) - 1:
            mature_h = sorted(mature)
            print(f"  [{di+1}/{len(test_dates)}] {test_date}: n={len(df_day)} mature={'+'.join(f'T{h}' for h in mature_h)} " f"bullish={dist['bullish']:.1%} neutral={dist['neutral']:.1%} bearish={dist['bearish']:.1%} ({time.time()-t0:.1f}s)")

    if not all_rows:
        print("无数据")
        return

    avg_bull_frac = float(np.mean(per_day_bull_frac)) if per_day_bull_frac else 0.0
    print(f"\n{'=' * 100}")
    print(f"全 universe 聚合 (n={len(all_rows)} records, {len(per_day_bull_frac)} 日):")
    print(f"  日均 bullish 占比: {avg_bull_frac:.1%}  (aff989be 断言 '~100%')")
    all_dirs = [r["trend_direction"] for r in all_rows]
    dist_overall = trend_direction_distribution(all_dirs)
    print(f"  全 universe 分布: bullish={dist_overall['bullish']:.1%} neutral={dist_overall['neutral']:.1%} bearish={dist_overall['bearish']:.1%}")

    print(f"\n  per-horizon verdict (decision-relevant north-star horizons):")
    print(f"  {'horizon':<10} {'n(mature)':>10} {'bullish':>9} {'bearish':>9} {'bull mean':>11} {'bear mean':>11} {'delta':>9} {'verdict':>16}")
    summaries: dict[str, dict[str, Any]] = {}
    for h in horizon_strs:
        s = per_horizon_summary(all_rows, horizon=h)
        summaries[h] = s
        if s["n"] == 0:
            print(f"  T+{h:<8} {0:>10} {'-':>9} {'-':>9} {'-':>11} {'-':>11} {'-':>9} {s['verdict']:>16}  (未成熟)")
            continue
        agg = aggregate_horizon(all_rows, horizon=h)
        bm = s["edge"]["bullish_mean"]
        sm = s["edge"]["bearish_mean"]
        delta = s["edge"]["delta"]
        print(f"  T+{h:<8} {s['n']:>10} {len(agg['bullish_rets']):>9} {len(agg['bearish_rets']):>9} " f"{(f'{bm:+.3f}%' if not np.isnan(bm) else '-'):>11} {(f'{sm:+.3f}%' if not np.isnan(sm) else '-'):>11} " f"{(f'{delta:+.3f}%' if not np.isnan(delta) else '-'):>9} {s['verdict']:>16}")

    print(f"\n  预筛增量 (trend-bullish 等权 vs 全 universe 等权), per-horizon:")
    for h in horizon_strs:
        s = summaries[h]
        if s["n"] == 0:
            print(f"    T+{h}: 未成熟, 无数据")
            continue
        agg = aggregate_horizon(all_rows, horizon=h)
        all_rets = agg["bullish_rets"] + agg["bearish_rets"] + agg["neutral_rets"]
        eq_all = float(np.mean(all_rets)) if all_rets else float("nan")
        eq_bull = float(np.mean(agg["bullish_rets"])) if agg["bullish_rets"] else float("nan")
        fd = eq_bull - eq_all if not (np.isnan(eq_bull) or np.isnan(eq_all)) else float("nan")
        print(f"    T+{h}: eq_all={eq_all:+.3f}%  eq_bullish={eq_bull:+.3f}%  filter_delta={fd:+.3f}%")

    print(f"\n{'=' * 100}")
    print("判读 (aff989be 'trend 无区分度' 断言在 T+1/T+5/T+10 上是否一致成立):")
    for h in horizon_strs:
        s = summaries[h]
        if s["n"] == 0:
            print(f"  T+{h}: 未成熟 (test_dates 太近末日, 无足够 forward 交易日) — 跳过, 避免用 T+1 替代.")
            continue
        v = s["verdict"]
        delta = s["edge"]["delta"]
        delta_s = f"{delta:+.3f}%" if not np.isnan(delta) else "n/a"
        if v == "no_filter":
            print(f"  T+{h}: ✅ 断言成立 (bullish {avg_bull_frac:.1%}>95%, |delta {delta_s}|<0.05%) → 预筛近似全选, 无区分度.")
        elif v == "weak_filter":
            print(f"  T+{h}: ≈ 部分成立 (bullish {avg_bull_frac:.1%}>95%, 但 delta {delta_s} 存在) → 分布无区分度, 方向仍有信号.")
        elif v == "directional_filter":
            print(f"  T+{h}: ⚠️ 断言不成立 (bullish {avg_bull_frac:.1%} 50-95%, delta {delta_s}) → 预筛有实际筛选作用.")
        else:  # strong_filter
            print(f"  T+{h}: ⚠️ 断言不成立 (bullish {avg_bull_frac:.1%}<50%, delta {delta_s}) → 预筛高度选择性, 与'无区分度'矛盾.")
    print(f"\n北极星判读 (T+5/T+10 是 BUY 决策 horizon):")
    ns = [summaries[h] for h in ("5", "10") if summaries.get(h, {}).get("n", 0) > 0]
    if not ns:
        print(f"  ⚠️ T+5/T+10 均未成熟 — 当前 test_dates 距末日 <5/10 交易日. 需更早 end_date 或更大 n_days.")
    else:
        signs = {h: summaries[h]["edge"]["delta"] for h in ("1", "5", "10") if summaries.get(h, {}).get("n", 0) > 0 and not np.isnan(summaries[h]["edge"]["delta"])}
        ns_signs = [signs[h] for h in ("5", "10") if h in signs]
        if all(s < 0 for s in ns_signs):
            print(f"  → 本窗口 T+5/T+10 方向增量均为负: 该窗口内 trend 方向反向.")
        elif all(s > 0 for s in ns_signs):
            print(f"  → 本窗口 T+5/T+10 方向增量均为正: 该窗口内 trend 方向在 BUY horizon 上正向.")
        else:
            print(f"  → 本窗口 T+5/T+10 方向增量符号不一致: trend 方向在不同 horizon 行为不同.")
        # Cross-window honesty (F5): c311 (loop 43) T+1 delta ≈ -1.09% on a different 4-day
        # window; this run's T+1 delta sign may differ. n=4 ⇒ direction sign is window-noise,
        # NOT decision-grade. Do NOT claim "trend direction effective/inverted" from one window.
        t1 = signs.get("1")
        if t1 is not None:
            t1_sign = "正" if t1 > 0 else "负"
            print(f"  ⚠️ 本窗口 T+1 delta = {t1:+.3f}% (c311 不同 4 日窗口 T+1 delta ≈ -1.088%). " f"n=4 ⇒ 方向符号是窗口噪声, 非 decision-grade.")
            print(f"     → C-R6-POOL-FILTER-REDESIGN 决策包: aff989be '无区分度' 仍被证伪 " f"(bullish {avg_bull_frac:.1%} ≠ ~100%), 但方向符号需远大于 4 日的 N 才能定.")
            if t1 < 0:
                print(f"     → 若多窗口一致为负, pool 预筛可能系统性选错方向; 若摇摆, 方向信号弱.")
            else:
                print(f"     → 本窗口方向正向且 T+5/T+10 更强, 但单窗口不能排除方向信号是噪声.")
    print(f"\n注意: light-stage (纯技术 0 LLM) + multi-horizon — 池预筛区分度的 horizon signal; " f"完整确认需全模型 + 远大于 4 日的 N (API 限速 ~3min/日, 大 N 需后台). " f"关键未决: trend 方向符号是否在更大 N 上稳定 (c311 vs 本窗口 T+1 已分歧).")


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
