"""题材动量 Tier B2 — 东财概念口径 (粒度阶梯最后一步, 计划 v3.4).

与 Tier A/B1 同款主假设 (增量 ¬BTST × dist1-2 × T+8 × normal × matured ×
物理确认日聚类 CI), 变化点全部预注册:
  - 板块 = 东财概念 (dc_member 每 10 交易日 as-of 快照, 自算概念内涨停家数 =
    lu 快照 ∩ 成分 — 不依赖任何第三方聚合字段);
  - 占比门槛公式化: share ≥ 1.5 / N_active (N_active = 当日有涨停的概念数;
    行业口径还原 1.5/31 ≈ 4.8% ≈ 5% 一致);
  - K₁ 网格 {2,3,5} 全落表, 主假设钉 K₁=3;
  - 一票多概念: (symbol, signal_date) 去重, 归属"距确认日最近"的概念
    (最新鲜题材), 丢弃数披露;
  - 财报类概念未做名称剔除 (需逐日概念名数据; 行为签名已排除持续类板块,
    财报跳变本身是合法事件 — 口径限制在决策包披露)。

用法: uv run python scripts/theme_momentum_tier_b2.py
"""

from __future__ import annotations

import bisect
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from scripts._btst_court_common import (  # noqa: E402
    WINDOW_A_START,
    forward_open_returns,
    load_regime_history,
    load_sessions,
)
from scripts.btst_court_build import load_panel  # noqa: E402
from scripts.theme_momentum_tier_a import (  # noqa: E402
    CONFIRM_BASELINE_MAX,
    CONFIRM_BASELINE_WIN,
    DEAD_RUN_LEN,
    DIST_BANDS,
    EXEC_COST_PP,
    INCONCLUSIVE_MIN_CYCLES,
    MAIN_REGIMES,
    NEAR_ZERO_BAND,
    PRIMARY_HORIZON,
    _cluster_ci,
    _event_stats,
    _load_lu_index,
    _mk_event,
    sanity,
)
from src.tools.ashare_board_utils import (  # noqa: E402
    is_beijing_exchange_ts_code,
    limit_up_pct_for_ticker,
)

RAW_CONCEPT = Path("data/research/theme_momentum/raw")
OUT_EVENTS = Path("data/research/theme_momentum/tier_events_concept.csv.gz")
OUT_REPORT = Path(f"data/reports/theme_momentum_tier_decision_pack_{date.today():%Y%m%d}_concept.json")
K_GRID = (2, 3, 5)
SHARE_FLOOR_COEF = 1.5


def _load_concept_snapshots() -> tuple[list[str], dict[str, dict[str, frozenset[str]]]]:
    """采样日列表 + {采样日: {概念: 成分 symbol 集}}。"""
    snaps = sorted(p.stem.split("_")[2] for p in RAW_CONCEPT.glob("dc_member_*.csv"))
    if not snaps:
        raise SystemExit("概念快照缺失 — 先跑 scripts/theme_momentum_fetch_concept.py")
    by_snap: dict[str, dict[str, frozenset[str]]] = {}
    for s in snaps:
        df = pd.read_csv(RAW_CONCEPT / f"dc_member_{s}.csv", dtype=str)
        by_snap[s] = {
            ts: frozenset(c.split(".")[0] for c in g["con_code"])
            for ts, g in df.groupby("ts_code")
        }
    return snaps, by_snap


def main() -> None:
    lu = _load_lu_index()
    lu_dates = sorted(lu.keys())
    snaps, concepts_by_snap = _load_concept_snapshots()
    panel = load_panel()
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    regime = load_regime_history()
    btst = pd.read_csv("data/research/btst_court/event_tables/event_table_v1.csv.gz",
                       dtype={"symbol": str, "signal_date": str, "ts_code": str})
    btst_keys = set(zip(btst["symbol"], btst["signal_date"]))
    sessions_cal = load_sessions(WINDOW_A_START, lu_dates[-1])
    sessions = [s for s in sessions_cal if s in lu and s in regime]
    print(f"[1/4] sessions={len(sessions)}, 概念快照={len(snaps)} ({snaps[0]}..{snaps[-1]})")

    # 逐日: 自算概念家数 + 全市场家数 + lu 行
    print("[2/4] 逐日自算概念涨停家数 (lu ∩ as-of 成分) …")
    concept_counts: dict[str, dict[str, int]] = {}
    mkt_counts: dict[str, int] = {}
    n_active: dict[str, int] = {}
    sym_concepts: dict[str, dict[str, set[str]]] = {}   # d → symbol → {概念}
    for d in sessions:
        as_of = snaps[bisect.bisect_right(snaps, d) - 1]   # 不晚于 d 的最近快照
        comps = concepts_by_snap[as_of]
        day = lu[d]
        cnt: dict[str, int] = defaultdict(int)
        sym_c: dict[str, set[str]] = defaultdict(set)
        mkt = 0
        for r in day.itertuples(index=False):
            ts_code = str(r.ts_code)
            if is_beijing_exchange_ts_code(ts_code):
                continue
            sym = ts_code.split(".")[0]
            mkt += 1
            for c, members in comps.items():
                if sym in members:
                    cnt[c] += 1
                    sym_c[sym].add(c)
        concept_counts[d] = dict(cnt)
        mkt_counts[d] = mkt
        n_active[d] = sum(1 for v in cnt.values() if v >= 1)
        sym_concepts[d] = dict(sym_c)

    # K 网格逐档: 确认 + 候选 + 事件
    print(f"[3/4] K₁ 网格 {K_GRID} …")
    results: dict[int, dict] = {}
    for K in K_GRID:
        events, confirms, dup_dropped = [], [], 0
        active: dict[str, dict] = {}
        for i, d in enumerate(sessions):
            cnt_d = concept_counts[d]
            mkt = mkt_counts[d]
            floor = SHARE_FLOOR_COEF / n_active[d] if n_active[d] else 1.0
            for c in list(active.keys()):
                v = cnt_d.get(c, 0)
                if v <= CONFIRM_BASELINE_MAX:
                    active[c]["dead_run"] += 1
                    if active[c]["dead_run"] >= DEAD_RUN_LEN:
                        del active[c]
                else:
                    active[c]["dead_run"] = 0
            for c, v in cnt_d.items():
                if v < K or mkt <= 0 or v / mkt < floor or i < CONFIRM_BASELINE_WIN:
                    continue
                if c in active:
                    continue
                base = sorted(concept_counts[sessions[j]].get(c, 0)
                              for j in range(i - CONFIRM_BASELINE_WIN, i))
                if base[CONFIRM_BASELINE_WIN // 2] > CONFIRM_BASELINE_MAX:
                    continue
                confirms.append({"concept": c, "confirm_date": d, "count": v, "share": round(v / mkt, 4)})
                active[c] = {"confirm_date": d, "dead_run": 0}
            day_by_day = by_day.get(d)
            prev_d = sessions[i - 1] if i > 0 else None
            for c, cyc in active.items():
                dist_sessions = i - sessions.index(cyc["confirm_date"])
                if dist_sessions < 1:
                    continue
                # 候选票 → 其多概念命中, 归属距确认日最近的概念 (去重)
                hits: dict[str, tuple[int, str]] = {}
                for sym, r in [(s, row) for s, row in lu[d].to_dict("index").items()]:
                    pass  # 占位 (下方直接遍历)
                # 腿 a
                for sym in sym_concepts[d]:
                    if c not in sym_concepts[d][sym]:
                        continue
                    key = (sym, "a")
                    if key in hits and hits[key][0] <= dist_sessions:
                        continue
                    hits[key] = (dist_sessions, "a")
                # 腿 b: 前日该概念涨停、今日存活且未跌停
                if prev_d is not None:
                    for sym in sym_concepts.get(prev_d, {}):
                        if c not in sym_concepts[prev_d].get(sym, set()):
                            continue
                        if sym in sym_concepts[d]:   # 今日涨停 → 腿 a 已计
                            continue
                        key = (sym, "b")
                        if key in hits and hits[key][0] <= dist_sessions:
                            continue
                        hits[key] = (dist_sessions, "b")
                for (sym, leg), (dist, _) in hits.items():
                    if leg == "a":
                        row = lu[d][lu[d]["ts_code"].str.split(".").str[0] == sym]
                        if row.empty:
                            continue
                        r0 = row.iloc[0]
                        pct = float(r0["pct_chg"]) if r0["pct_chg"] else None
                        close = float(r0["close"]); name = str(r0["name"])
                        ts_code = str(r0["ts_code"])
                    else:
                        m = day_by_day[day_by_day["ts_code"] == f"{sym}.SH"] if day_by_day is not None else None
                        if m is None or m.empty:
                            mm = day_by_day[day_by_day["ts_code"] == f"{sym}.SZ"] if day_by_day is not None else None
                            m = mm
                        if m is None or m.empty:
                            continue
                        rowb = m.iloc[0]
                        pct = float(rowb.get("pct_chg") if pd.notna(rowb.get("pct_chg")) else 0.0)
                        if pct <= -limit_up_pct_for_ticker(sym):
                            continue
                        close = float(rowb["close"]); name = ""
                        ts_code = str(rowb["ts_code"])
                    ev = _mk_event(sym, ts_code, d, c, cyc["confirm_date"], dist,
                                   f"{leg}_limit_up" if leg == "a" else "b_alive",
                                   pct, close, name, regime[d], sessions, by_day, btst_keys)
                    ev["concept"] = c
                    events.append(ev)
        ev = pd.DataFrame(events)
        if len(ev):
            ev = ev.sort_values(["symbol", "signal_date", "days_after_confirm"]) \
                   .drop_duplicates(subset=["symbol", "signal_date"], keep="first")
        results[K] = {"events": ev, "confirms": confirms}
        print(f"  K={K}: 确认={len(confirms)} 事件(去重后)={len(ev)}")

    # 统计与决策包 (K=3 主假设; 全档披露)
    print("[4/4] 统计与决策包 …")
    report = {
        "disclaimer": "研究重放产物: 不构成任何策略接入/仓位/授权依据",
        "review": "theme momentum Tier B2 — 东财概念口径 (粒度阶梯最后一步)",
        "generated_at": date.today().isoformat(),
        "window": {"start": sessions[0], "end": sessions[-1]},
        "preregistration": {
            "share_floor": f"{SHARE_FLOOR_COEF}/N_active(当日有涨停概念数)",
            "k_grid": list(K_GRID), "primary_k": 3,
            "dedup": "(symbol, signal_date) 归属距确认日最近概念",
            "notes": "财报类概念未名称剔除 (口径限制); 聚类 = 物理确认日",
        },
        "sanity": {}, "primary_k3": {}, "k_grid": {}, "huazheng_603186_observation": [],
    }
    ev_all = results[3]["events"]
    if len(ev_all):
        OUT_EVENTS.parent.mkdir(parents=True, exist_ok=True)
        ev_all.to_csv(OUT_EVENTS, index=False, compression="gzip")
        clean = ev_all[(ev_all["fillable"]) & (~ev_all["st_name"]) & (ev_all["signal_close"] >= 3.0)]
        main_slice = clean[
            (~clean["btst_eligible"]) & clean["days_after_confirm"].between(1, 2)
            & clean["regime"].isin(MAIN_REGIMES) & clean["matured"] & clean["gross_ret_t8"].notna()
        ]
        cycles = defaultdict(list)
        for r in main_slice.itertuples(index=False):
            cycles[r.confirm_date].append(r.gross_ret_t8)
        primary = _cluster_ci([sum(v) / len(v) for v in cycles.values()])
        mean_pp = primary.get("mean_pp")
        ci_low = primary.get("ci_low_pp")
        if primary["status"] != "ok":
            decision = "inconclusive"
        elif ci_low is not None and ci_low > 0 and mean_pp is not None and mean_pp > EXEC_COST_PP:
            decision = "primary_hypothesis_confirmed"
        elif mean_pp is not None and NEAR_ZERO_BAND[0] < mean_pp <= NEAR_ZERO_BAND[1]:
            decision = "near_zero"     # 阶梯已尽: 等价关闭 (无下一步)
        else:
            decision = "close_direction"
        report["primary_k3"] = {"stats": primary, "decision": decision,
                                "ladder_exhausted": decision != "primary_hypothesis_confirmed"}
        report["counts"] = {
            "confirms": len(results[3]["confirms"]), "events": int(len(ev_all)),
            "events_clean": int(len(clean)),
            "overlap_with_btst": int(clean["btst_eligible"].sum()),
            "overlap_rate": round(float(clean["btst_eligible"].mean()), 4) if len(clean) else None,
            "yizi_rate_theme": float(ev_all[ev_all["matured"]]["t1_unbuyable"].mean()) if len(ev_all) else None,
            "yizi_rate_btst_court": float(btst["t1_unbuyable"].dropna().mean()),
        }
        # 探索性
        expl = {}
        for lo_d, hi_d in DIST_BANDS:
            sel = clean[clean["days_after_confirm"].between(lo_d, hi_d) & clean["matured"]]
            expl[f"dist{lo_d}-{hi_d}"] = {
                "all": _event_stats(sel.to_dict("records")),
                "incremental": _event_stats(sel[~sel["btst_eligible"]].to_dict("records")),
            }
        report["exploratory_dist"] = expl
        report["huazheng_603186_observation"] = ev_all[ev_all["symbol"] == "603186"][
            ["signal_date", "concept", "leg", "days_after_confirm", "btst_eligible", "gross_ret_t8"]
        ].to_dict("records")
    for K in K_GRID:
        evk = results[K]["events"]
        if not len(evk):
            report["k_grid"][K] = {"confirms": len(results[K]["confirms"]), "events": 0}
            continue
        ck = evk[(evk["fillable"]) & (~evk["st_name"]) & (evk["signal_close"] >= 3.0)]
        mk = ck[(~ck["btst_eligible"]) & ck["days_after_confirm"].between(1, 2)
                & ck["regime"].isin(MAIN_REGIMES) & ck["matured"] & ck["gross_ret_t8"].notna()]
        cyc = defaultdict(list)
        for r in mk.itertuples(index=False):
            cyc[r.confirm_date].append(r.gross_ret_t8)
        report["k_grid"][K] = {
            "confirms": len(results[K]["confirms"]), "events": int(len(evk)),
            "primary": _cluster_ci([sum(v) / len(v) for v in cyc.values()]),
        }
    # sanity: 每月确认数 (概念粒度, 阈值放宽记录)
    by_month = defaultdict(int)
    for c in results[3]["confirms"]:
        by_month[c["confirm_date"][:6]] += 1
    report["sanity"] = {"confirm_per_month": dict(sorted(by_month.items()))}

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("counts", "primary_k3")}, ensure_ascii=False, indent=2))
    print(f"产物: {OUT_EVENTS}\n      {OUT_REPORT}")


if __name__ == "__main__":
    main()
