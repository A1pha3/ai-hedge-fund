#!/usr/bin/env python3
"""R6 多 horizon 增量积累诊断 (loop 47, c315): 把 n=4 的方向符号判定提升到 n=20+.

北极星 blocker (decision-state F1 / C-R6-POOL-FILTER-REDESIGN):
  c311/c312 在 n=4 天窗口上测 trend 方向 delta, 符号翻转了 (-1.088% vs +0.912%).
  方向符号在 n=4 是窗口噪声, 所以池预筛重设计决策 (A/B/C/D) 不能安全行动.
  blocker 是数据量, 不是工程——但 API 限速 (~3min/天) 让 20 天前台单次运行不可行.

本脚本: 增量积累. 今天跑 4 天, 持久化, 明天续跑下一个 4 天, 累积到 n=20+.
  - 纯逻辑 (持久化 / 状态合并 / 续跑计划) 抽成可测 helper (本文件).
  - API I/O (tushare fetch) 留在 run() 循环里, 复用 c312 的 fetch 逻辑.

复用 c312 helpers (scripts/_diag_trend_pool_filter_discrimination):
  cumulative_horizon_return / mature_horizons / get_universe_for_date /
  get_history_batch / compute_factor_snapshot / per_horizon_summary.

诚实限制 (run() 文本 + commit 都披露):
  - light-stage (0 LLM) + multi-horizon (T+1/T+5/T+10) + 增量 n.
  - 未成熟 horizon 诚实跳过 (None), 不用 T+1 替代 (NS-17 maturity-faking).
  - 同一 test_date 重跑去重 (merge_day_rows), 不重复计数 (否则 fakes N).
"""
from __future__ import annotations

import json
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
from scripts._diag_trend_pool_filter_discrimination import (  # noqa: E402
    HORIZONS,
    cumulative_horizon_return,
    mature_horizons,
    per_horizon_summary,
)

logger = logging.getLogger("r6_accrual")


# ---------------------------------------------------------------------------
# 纯 helpers (TDD-covered). 决策关键: 一个 bug 静默丢天/重复计数会 fakes N,
# 可能翻转方向 delta 判读 (NS-17 / 数据真实性).
# ---------------------------------------------------------------------------


def load_state(path: Path) -> dict[str, Any]:
    """加载积累状态 {days_done: [date...], rows: [...]}. 文件缺失/损坏 → 空状态.

    损坏文件 (部分写 / JSON 解析失败) 必须 NOT crash 续跑——返回空状态重新积累,
    而不是静默加载垃圾数据 (会 fakes N). 操作员通过 stderr 告知.
    """
    if not path.exists():
        return {"days_done": [], "rows": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # NS-17 / 数据真实性: 损坏 → 安全降级 (重新积累), 不 crash 不加载垃圾.
        print(f"[warn] 状态文件 {path} 损坏 ({e}); 重新积累.", file=sys.stderr)
        return {"days_done": [], "rows": []}
    days_done = raw.get("days_done") or []
    rows = raw.get("rows") or []
    if not isinstance(days_done, list) or not isinstance(rows, list):
        print(f"[warn] 状态文件 {path} schema 异常; 重新积累.", file=sys.stderr)
        return {"days_done": [], "rows": []}
    return {"days_done": days_done, "rows": rows}


def save_state(path: Path, state: dict[str, Any]) -> None:
    """原子写 (写临时文件 → rename), 防部分写导致下次 load_state 读到损坏 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # 原子 rename


def merge_day_rows(
    state: dict[str, Any], test_date: str, new_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """把一天的 rows 并入状态. 已完成的 test_date 去重 (不重复计数).

    决策关键: 重复计数某天会 fakes N, 可能翻转方向 delta 判读. 空 new_rows
    不标记 done (保持可重试——避免 API 失败的某天被永久跳过, 静默数据缺口).
    """
    if test_date in state["days_done"]:
        return state  # 已积累, 去重: 不覆盖不追加
    if not new_rows:
        return state  # 该天无数据: 不标记 done, 留待重试
    return {
        "days_done": state["days_done"] + [test_date],
        "rows": state["rows"] + list(new_rows),
    }


def plan_next_batch(
    test_dates: list[str], days_done: list[str], batch_size: int
) -> list[str]:
    """哪些 test_dates 还没跑, 按 chronological 顺序, cap 到 batch_size.

    保持 test_dates 原始顺序 (不是 set 迭代顺序) — 顺序对 maturity + 可复现重要.
    """
    done_set = set(days_done)
    pending = [d for d in test_dates if d not in done_set]
    return pending[:batch_size]


def maturity_for_window(
    rows: list[dict[str, Any]], horizons: tuple[int, ...]
) -> dict[str, int]:
    """每个 horizon 有多少 rows 是成熟的 (rets[h] 非 None). 仅信息性诚实.

    与 c312 aggregate_horizon 同一 maturity 原则: rets[h] is None = 未成熟,
    不计入 (不用 T+1 替代).
    """
    out: dict[str, int] = {}
    for h in horizons:
        hs = str(h)
        out[hs] = sum(1 for r in rows if r.get("rets", {}).get(hs) is not None)
    return out


# ---------------------------------------------------------------------------
# API I/O (不测, 复用 c312 fetch 逻辑). collect_one_date = 一天的 fetch+compute.
# ---------------------------------------------------------------------------


def _collect_one_date(
    pro, test_date: str, di: int, trade_dates: list[str], horizons: tuple[int, ...],
    stock_basic: pd.DataFrame, fwd_cache: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """收集一个 test_date 的 per-stock rows (trend_direction + per-horizon rets).

    复用 c312 run() 的循环体逻辑, 提取成函数以便增量调用. 未成熟 horizon →
    rets[h]=None (c312 maturity 原则).
    """
    max_h = max(horizons)
    # Forward window fetch (cache by calendar date — 跨 test_date 共享)
    for fi in range(di + 1, di + 1 + max_h):
        if fi < len(trade_dates) and trade_dates[fi] not in fwd_cache:
            try:
                dfn = pro.daily(trade_date=trade_dates[fi])
                fwd_cache[trade_dates[fi]] = (
                    dict(zip(dfn["ts_code"].tolist(), dfn["pct_chg"].astype(float).tolist()))
                    if dfn is not None and not dfn.empty else {}
                )
            except Exception:
                fwd_cache[trade_dates[fi]] = {}

    mature = mature_horizons(di, len(trade_dates), horizons)
    if not mature:
        return []
    universe = get_universe_for_date(pro, test_date, stock_basic)
    if universe.empty or len(universe) < 100:
        return []
    history_start = (datetime.strptime(test_date, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
    hist = get_history_batch(pro, universe["ts_code"].tolist(), history_start, test_date)
    if hist.empty:
        return []
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
        return []
    rows: list[dict[str, Any]] = []
    for _, r in universe.iterrows():
        snap = snapshots.get(r["ts_code"])
        if snap is None:
            continue
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
        rows.append({
            "ts_code": r["ts_code"],
            "trend_direction": int(snap.trend_direction),
            "rets": rets,
        })
    return rows


def run(
    n_days: int = 20,
    batch_size: int = 4,
    end_date: str | None = None,
    state_path: str | None = None,
) -> None:
    """增量积累运行: 每次跑 batch_size 天, 持久化, 可续跑.

    典型用法: 连续多天 `python ... --n-days 20 --batch-size 4 --state outputs/r6_accrual.json`
    每次跑下一个未完成的 4 天, 累积到 20 天后输出多 horizon 判读.
    """
    horizons = HORIZONS
    max_h = max(horizons)
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    # 预留 max_h forward 交易日, 让最早 test_date 能成熟到 T+max_h
    trade_dates = get_trading_dates(pro, n_days + max_h, end_date=end_date)
    test_dates = trade_dates[:n_days]

    sp = Path(state_path) if state_path else Path("outputs/r6_accrual_state.json")
    state = load_state(sp)
    print(f"\nR6 多 horizon 增量积累: 目标 {n_days} 日 ({test_dates[0]}~{test_dates[-1]})")
    print(f"已积累 {len(state['days_done'])}/{n_days} 日; 本批最多 +{batch_size} 日")
    print(f"{'=' * 90}")

    batch = plan_next_batch(test_dates, state["days_done"], batch_size)
    if not batch:
        print(f"  全部 {n_days} 日已积累完成 — 跳到判读.")
    else:
        print(f"  本批: {batch}")

    fwd_cache: dict[str, dict[str, float]] = {}
    for test_date in batch:
        di = test_dates.index(test_date)
        t0 = time.time()
        try:
            new_rows = _collect_one_date(
                pro, test_date, di, trade_dates, horizons, stock_basic, fwd_cache
            )
        except Exception as e:
            print(f"  [{test_date}] 失败 ({e}); 跳过 (不标记 done, 下次重试)")
            continue
        if not new_rows:
            print(f"  [{test_date}] 无数据/未成熟; 跳过 (不标记 done, 下次重试)")
            continue
        state = merge_day_rows(state, test_date, new_rows)
        save_state(sp, state)  # 每天存一次, 断点续跑
        print(f"  [{test_date}] +{len(new_rows)} rows ({time.time()-t0:.1f}s); "
              f"累计 {len(state['days_done'])}/{n_days} 日")

    print(f"\n{'=' * 90}")
    print(f"累计状态: {len(state['days_done'])}/{n_days} 日, {len(state['rows'])} rows")
    if len(state["days_done"]) < n_days:
        remaining = n_days - len(state["days_done"])
        print(f"  未完成 {remaining} 日. 再跑 `python {sys.argv[0]} --n-days {n_days} "
              f"--batch-size {batch_size} --state {sp}` 续跑.")
        print(f"  (API 限速 ~3min/日; 完成需约 {remaining} 次运行)")
        return

    # 全部积累完成 → 多 horizon 判读
    _report(state["rows"], horizons)


def _report(rows: list[dict[str, Any]], horizons: tuple[int, ...]) -> None:
    """n_days 全部积累完成后, 输出多 horizon 方向 delta 判读."""
    horizon_strs = [str(h) for h in horizons]
    print(f"\n多 horizon 判读 (n={len(rows)} records):")
    print(f"  {'horizon':<10} {'n(mature)':>10} {'delta':>9} {'verdict':>16}")
    summaries: dict[str, dict[str, Any]] = {}
    for h in horizon_strs:
        s = per_horizon_summary(rows, horizon=h)
        summaries[h] = s
        delta = s["edge"]["delta"]
        delta_s = f"{delta:+.3f}%" if not np.isnan(delta) else "n/a"
        print(f"  T+{h:<8} {s['n']:>10} {delta_s:>9} {s['verdict']:>16}")
    print(f"\n  maturity (per-horizon 成熟 rows): {maturity_for_window(rows, horizons)}")
    ns = [summaries[h] for h in ("5", "10") if summaries.get(h, {}).get("n", 0) > 0]
    if not ns:
        print("  ⚠️ T+5/T+10 无成熟 rows — 需更早 end_date 或更大 n_days.")
        return
    signs = [s["edge"]["delta"] for s in ns if not np.isnan(s["edge"]["delta"])]
    print(f"\n北极星判读 (T+5/T+10 BUY horizon, n={len(rows)} records):")
    if all(s < 0 for s in signs):
        print("  → T+5/T+10 方向 delta 均为负: trend 方向在 BUY horizon 系统性反向.")
        print("     → C-R6-POOL-FILTER-REDESIGN: pool 预筛系统性选错方向 (B/C 翻转/双向有依据).")
    elif all(s > 0 for s in signs):
        print("  → T+5/T+10 方向 delta 均为正: trend 方向在 BUY horizon 有效.")
        print("     → C-R6-POOL-FILTER-REDESIGN: pool 预筛方向 OK, 杠杆在别处.")
    else:
        print("  → T+5/T+10 方向符号不一致: trend 方向在不同 horizon 行为不同.")
        print("     → C-R6-POOL-FILTER-REDESIGN: 需 horizon-specific 设计.")
    print(f"\n注意: light-stage (0 LLM) + multi-horizon + n={len(rows)} records. "
          f"完整确认需全模型. 此判读基于 n_days 累积, 非 4 日窗口——可直接进决策包.")


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    import argparse
    ap = argparse.ArgumentParser(description="R6 多 horizon 增量积累诊断 — 把 n=4 提升到 n=20+")
    ap.add_argument("--n-days", type=int, default=20, help="目标总天数 (default 20)")
    ap.add_argument("--batch-size", type=int, default=4, help="每次运行跑几天 (default 4, 受 API 限速)")
    ap.add_argument("--end-date", default="", help="截止日期 YYYYMMDD (default 今天)")
    ap.add_argument("--state", default="outputs/r6_accrual_state.json", help="状态文件路径 (断点续跑)")
    a = ap.parse_args()
    run(n_days=a.n_days, batch_size=a.batch_size, end_date=a.end_date or None, state_path=a.state)


if __name__ == "__main__":
    main()
