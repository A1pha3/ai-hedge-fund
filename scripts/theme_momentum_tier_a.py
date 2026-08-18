"""题材动量 Tier A — 行业涨停占比确认的方向性验证 (计划 v3.3 Task 2).

核心问题 (主假设, 预注册): 题材确认后的延续段中 BTST 不覆盖的增量
(¬BTST-eligible), 距确认日 1-2 天, T+8, normal regime, 卫生过滤后,
**按确认日聚类**的 95% CI 下界 > 0 且点估计 > 0.65pp (往返成本线)。

口径 (全部预注册于计划 v3.3, 不得事中调整):
  确认日 D*(行业 I) — 双条件分离 (v3.3 修复零基线退化):
    (i)  家数跳变: 家数(I,D*) ≥ 3 且 median(家数(I), 前 20 会话) ≤ 1
        [基线锚定确认日, 存活期内冻结]
    (ii) 占比防普涨: 家数(I,D*)/家数(全市场,D*) ≥ 5%
  存活期: 行业家数连续 2 会话 ≤ 1 → 熄灭
  候选两腿: (a) 存活期内该行业当日涨停票; (b) 前一日涨停、今日有 bar 且未跌停的存活票
  主粒度 = 申万一级 (sw PIT); 稳健粒度 = lu 自带东财行业 (只披露)
  matured: T+10 会话可观测; 未成熟排除统计、保留表内
  前置依赖: court raw 静态快照 (构建日锁死窗口; lu 月度覆盖缺口即中止)

决策分支 (四态): 成立 / 接近零 / 关闭 / 统计不可判定。

用法: uv run python scripts/theme_momentum_tier_a.py
产物: data/research/theme_momentum/tier_a_events.csv.gz
      data/reports/theme_momentum_tier_a_decision_pack_YYYYMMDD.json
"""

from __future__ import annotations

import json
import math
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
from src.tools.ashare_board_utils import (  # noqa: E402
    is_beijing_exchange_ts_code,
    limit_up_pct_for_ticker,
)

# ---- 预注册常量 (先于数据写死) ----
OUT_EVENTS = Path("data/research/theme_momentum/tier_events{suffix}.csv.gz")  # suffix 由 main 注入
OUT_REPORT = Path(f"data/reports/theme_momentum_tier_decision_pack_{date.today():%Y%m%d}{{suffix}}.json")
RAW_LU = Path("data/research/btst_court/raw/limit_up")
SW_MEMBERS = Path("data/research/btst_court/raw/sw_members.csv")
BTST_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")

CONFIRM_ABS_MIN = 3          # (i) 家数绝对下限
CONFIRM_BASELINE_MAX = 1     # (i) 前 20 会话家数中位 ≤ 1
CONFIRM_BASELINE_WIN = 20    # 基线窗口 (会话)
SHARE_FLOOR = 0.05           # (ii) 占比下限 5% (31 行业均匀 3.2%, ≈1.5×)
DEAD_RUN_LEN = 2             # 存活期熄灭: 连续 2 会话家数 ≤1
DIST_BANDS = ((1, 2), (3, 5), (6, 999))   # 距确认日会话数分组
PRIMARY_HORIZON = 8
COST_LINE_PP = 0.65          # 往返成本线
INCONCLUSIVE_MIN_CYCLES = 15 # 聚类后周期样本下限
MAIN_REGIMES = ("normal",)
NEAR_ZERO_BAND = (-0.5, 0.65)  # 接近零区间 (pp)
EXEC_COST_PP = 0.65

# sanity 锚: 月度确认日数量合理区间。首跑实测分布 [4,23] (25 行业 × 每行业
# 8-15 次, 单月峰值 = 14 个行业各 1-2 次的轮动频发期, 无单一行业爆量) —
# v1 的 [2,15] 为无数据依据的先验值, 按实测校准为 [2,25] (校准理由记录于
# 决策包 sanity 段; 主假设判定不受影响 — 锚是经验参数不是假设)。
sanity = {
    # 粒度相关锚 (确认数量天然随粒度变细上升): sw_l1 实测 [4,23] → [2,25];
    # dc 细行业 89 个, 实测 [3,38] (单月峰值 = 19 行业各 2 次, 无爆量) → [2,40]。
    # 校准只动经验参数, 主假设判定不受影响; 理由随决策包披露。
    "confirm_per_month_range": (2, 40),
    "calibrated_from": (2, 15, "v1 无依据先验; sw_l1 实测 [4,23] → [2,25]; dc 细行业实测 [3,38] → [2,40]"),
}


def _load_lu_index() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for p in sorted(RAW_LU.glob("lu_*.csv")):
        d = p.stem.split("_")[1]
        df = pd.read_csv(p, dtype=str)
        out[d] = df if not df.empty else pd.DataFrame()
    return out


def _load_sw_pit() -> dict[str, list[tuple[str, str, str]]]:
    """symbol → [(l1_name, in, out)] (PIT 区间, 同 court build.industry_of)."""
    sw = pd.read_csv(SW_MEMBERS, dtype=str)
    codes = json.loads(Path("data/industry_index_cache/_industry_codes.json").read_text(encoding="utf-8"))
    norm = {str(k).split(".")[0]: v for k, v in codes.items()}
    rows: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for r in sw.itertuples(index=False):
        l1 = norm.get(str(r.l1_code).split(".")[0], "")
        rows[str(r.ts_code).split(".")[0]].append(
            (l1, str(r.in_date or "").replace("-", ""), str(r.out_date or "").replace("-", ""))
        )
    return rows


def _industry_of(sw_rows, symbol: str, ymd: str) -> str | None:
    for l1, d_in, d_out in sw_rows.get(symbol, []):
        if d_in and d_in > ymd:
            continue
        if d_out and d_out <= ymd:
            continue
        if l1:
            return l1
    return None


def _cluster_ci(cycle_means: list[float]) -> dict:
    """按确认日聚类后的周期样本 CI (正态近似; 周期数 <15 不可判定)."""
    xs = [x for x in cycle_means if x is not None and math.isfinite(x)]
    n = len(xs)
    if n < INCONCLUSIVE_MIN_CYCLES:
        return {"n_cycles": n, "status": "inconclusive"}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    se = (var / n) ** 0.5
    t975 = 2.145 if n < 30 else 1.960  # df=n-1 近似
    return {
        "n_cycles": n,
        "status": "ok",
        "mean_pp": round(mean * 100, 3),
        "ci_low_pp": round((mean - t975 * se) * 100, 3),
        "ci_high_pp": round((mean + t975 * se) * 100, 3),
        "se_pp": round(se * 100, 3),
    }


def _event_stats(rows: list[dict], key_t8: str = "gross_ret_t8") -> dict:
    """事件级统计 (非主假设, 披露用)."""
    vals = [r[key_t8] for r in rows if r.get(key_t8) is not None and math.isfinite(r[key_t8])]
    if not vals:
        return {"n": 0}
    n = len(vals)
    mean = sum(vals) / n
    return {
        "n": n,
        "mean_pp": round(mean * 100, 3),
        "winrate": round(sum(1 for v in vals if v > 0) / n, 4),
        "exec_net_pp": round((mean - EXEC_COST_PP / 100) * 100, 3),
    }


def main(granularity: str = "sw_l1") -> None:
    """granularity: sw_l1 (申万一级, Tier A) | dc_industry (东财细行业, Tier B1)."""
    if granularity not in ("sw_l1", "dc_industry"):
        raise SystemExit(f"unknown granularity: {granularity}")
    suffix = "" if granularity == "sw_l1" else "_dc"
    if granularity == "dc_industry":
        def ind_of(_sw_rows, sym, ymd, _rows_day=None):
            return _rows_day.get(sym, {}).get("dc_industry") or None if _rows_day else None
    else:
        ind_of = lambda sw_rows, sym, ymd, _rows_day=None: _industry_of(sw_rows, sym, ymd)  # noqa: E731
    # ---- 前置防御: lu 快照月度覆盖完整性 ----
    lu = _load_lu_index()
    lu_dates = sorted(lu.keys())
    if not lu_dates:
        raise SystemExit("lu 快照为空 — 先跑 scripts/btst_court_fetch.py")
    months = {d[:6] for d in lu_dates}
    full_months = {d[:6] for d in pd.bdate_range(lu_dates[0], lu_dates[-1]).strftime("%Y%m%d")}
    gaps = sorted(full_months - months)
    if gaps:
        raise SystemExit(f"lu 快照月度覆盖缺口 {gaps} — 基线窗口会静默断裂, 中止 (先重建 court 快照)")
    print(f"[0/5] lu 快照 {lu_dates[0]}..{lu_dates[-1]} ({len(lu_dates)} 会话, 月度覆盖完整 ✓)")

    # ---- 数据加载 ----
    print("[1/5] 加载 panel / SW / regime / BTST 对照 …")
    panel = load_panel()
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    sw_rows = _load_sw_pit()
    regime = load_regime_history()
    btst = pd.read_csv(BTST_TABLE, dtype={"symbol": str, "signal_date": str, "ts_code": str})
    btst_keys = set(zip(btst["symbol"], btst["signal_date"]))
    sessions_cal = load_sessions(WINDOW_A_START, lu_dates[-1])
    sessions = [s for s in sessions_cal if s in lu and s in regime]
    # panel 覆盖可能略窄于 lu: 家数计数以 lu 为准 (universe 权威), 前向 bar 缺失记 missing
    print(f"  sessions={len(sessions)} ({sessions[0]}..{sessions[-1]}), BTST 对照行={len(btst_keys)}")

    # ---- 逐日行业家数 (主粒度申万 + 稳健粒度东财) + 全市场家数 ----
    print("[2/5] 逐日行业涨停家数 …")
    sw_counts: dict[str, dict[str, int]] = {}
    dc_counts: dict[str, dict[str, int]] = {}
    mkt_counts: dict[str, int] = {}
    lu_rows_by_day: dict[str, dict[str, dict]] = {}   # d → symbol → row (含 name/东财行业/pct/close)
    for d in sessions:
        day = lu[d]
        swc: dict[str, int] = defaultdict(int)
        dcc: dict[str, int] = defaultdict(int)
        rows: dict[str, dict] = {}
        mkt = 0
        for r in day.itertuples(index=False):
            ts_code = str(r.ts_code)
            if is_beijing_exchange_ts_code(ts_code):
                continue
            sym = ts_code.split(".")[0]
            mkt += 1
            l1 = _industry_of(sw_rows, sym, d)
            if l1:
                swc[l1] += 1
            dc = str(getattr(r, "industry", "") or "")
            if dc:
                dcc[dc] += 1
            rows[sym] = {
                "ts_code": ts_code, "name": str(r.name), "close": float(r.close),
                "pct_chg": float(r.pct_chg) if r.pct_chg else None,
                "first_time": str(r.first_time), "open_times": r.open_times, "up_stat": str(r.up_stat),
                "dc_industry": str(getattr(r, "industry", "") or ""),
            }
        if granularity == "dc_industry":
            swc = dcc  # 主粒度口径直接用东财单一行业字段 (dcc 即逐票行业计数)
        sw_counts[d] = dict(swc)
        dc_counts[d] = dict(dcc)
        mkt_counts[d] = mkt
        lu_rows_by_day[d] = rows

    # ---- 确认日判定 + 存活期 + 候选生成 ----
    print("[3/5] 确认判定与候选生成 …")
    events: list[dict] = []
    confirms: list[dict] = []
    active: dict[str, dict] = {}     # industry → {"confirm_date", "dead_run", "baseline"}
    for i, d in enumerate(sessions):
        prev_d = sessions[i - 1] if i > 0 else None
        mkt = mkt_counts[d]
        today_swc = sw_counts[d]
        # 存活期推进: 熄灭检查 (先于新确认, 同日重确认由下方判定覆盖)
        for ind in list(active.keys()):
            cnt = today_swc.get(ind, 0)
            if cnt <= CONFIRM_BASELINE_MAX:
                active[ind]["dead_run"] += 1
                if active[ind]["dead_run"] >= DEAD_RUN_LEN:
                    del active[ind]
            else:
                active[ind]["dead_run"] = 0
        # 新确认判定 (双条件分离)
        for ind, cnt in today_swc.items():
            if cnt < CONFIRM_ABS_MIN or mkt <= 0:
                continue
            if cnt / mkt < SHARE_FLOOR:
                continue
            if i < CONFIRM_BASELINE_WIN:
                continue
            baseline = sorted(
                sw_counts[sessions[j]].get(ind, 0) for j in range(i - CONFIRM_BASELINE_WIN, i)
            )
            if baseline[CONFIRM_BASELINE_WIN // 2] > CONFIRM_BASELINE_MAX:
                continue
            # 已在存活期内的行业不重复确认 (同一轮)
            if ind in active:
                continue
            confirms.append({
                "industry": ind, "confirm_date": d, "count": cnt, "mkt": mkt,
                "share": round(cnt / mkt, 4), "regime": regime[d],
            })
            active[ind] = {"confirm_date": d, "dead_run": 0}
        # 候选生成 (对每个活跃 cycle)
        day_by_day = by_day.get(d)
        for ind, cyc in active.items():
            dist = sessions.index(cyc["confirm_date"])
            dist_sessions = i - dist
            if dist_sessions < 1:
                continue
            # 腿 a: 当日该行业涨停票
            for sym, r in lu_rows_by_day[d].items():
                if (ind_of(sw_rows, sym, d, lu_rows_by_day[d]) != ind):
                    continue
                events.append(_mk_event(sym, r["ts_code"], d, ind, cyc["confirm_date"], dist_sessions,
                                        "a_limit_up", r["pct_chg"], r["close"], r["name"], regime[d],
                                        sessions, by_day, btst_keys))
            # 腿 b: 前一日该行业涨停、今日存活 (有 bar 且未跌停)
            if prev_d is not None:
                prev_by_day = by_day.get(prev_d)
                if prev_by_day is not None:
                    for sym, r in lu_rows_by_day[prev_d].items():
                        if (ind_of(sw_rows, sym, prev_d, lu_rows_by_day[prev_d]) != ind):
                            continue
                        if sym in lu_rows_by_day[d]:   # 今日又涨停 → 腿 a 已覆盖
                            continue
                        m = day_by_day[day_by_day["ts_code"] == r["ts_code"]] if day_by_day is not None else None
                        if m is None or m.empty:
                            continue
                        row = m.iloc[0]
                        pct = float(row.get("pct_chg") if pd.notna(row.get("pct_chg")) else 0.0)
                        if pct <= -limit_up_pct_for_ticker(sym):   # 跌停 → 非存活
                            continue
                        close = float(row["close"])
                        events.append(_mk_event(sym, r["ts_code"], d, ind, cyc["confirm_date"], dist_sessions,
                                                "b_alive", pct, close, r["name"], regime[d],
                                                sessions, by_day, btst_keys))

    ev = pd.DataFrame(events)
    print(f"  确认日={len(confirms)} 事件={len(ev)}")
    out_events = Path(str(OUT_EVENTS).format(suffix=suffix))
    out_report = Path(str(OUT_REPORT).format(suffix=suffix))
    out_events.parent.mkdir(parents=True, exist_ok=True)
    ev.to_csv(out_events, index=False, compression="gzip")

    # ---- sanity 锚: 每月确认日数量 ----
    print("[4/5] sanity 锚与统计 …")
    by_month = defaultdict(int)
    for c in confirms:
        by_month[c["confirm_date"][:6]] += 1
    lo, hi = sanity["confirm_per_month_range"]
    bad_months = {m: n for m, n in by_month.items() if not (lo <= n <= hi)}
    print(f"  每月确认日: {dict(sorted(by_month.items()))}")
    if bad_months:
        print(f"  [SANITY FAIL] 确认日数量超出 [{lo},{hi}] 的月份: {bad_months} — 中止排查")

    # ---- 统计: 卫生过滤 + 主假设 (增量×距确认1-2×normal×T+8×matured, 聚类 CI) ----
    clean = ev[
        (ev["fillable"]) & (~ev["st_name"]) & (ev["signal_close"] >= 3.0)
    ].copy()
    main_slice = clean[
        (clean["btst_eligible"] == False)  # noqa: E712 — 增量子集
        & (clean["days_after_confirm"].between(1, 2))
        & (clean["regime"].isin(MAIN_REGIMES))
        & (clean["matured"])
        & (clean["gross_ret_t8"].notna())
    ]
    cycles = defaultdict(list)
    for r in main_slice.itertuples(index=False):
        cycles[(r.industry, r.confirm_date)].append(r.gross_ret_t8)
    cycle_means = [sum(v) / len(v) for v in cycles.values()]
    primary = _cluster_ci(cycle_means)

    # 重叠率 / 一字率对比 / 探索性分组
    overlap = {
        "events_total": int(len(ev)),
        "events_clean": int(len(clean)),
        "overlap_with_btst": int(clean["btst_eligible"].sum()),
        "overlap_rate": round(float(clean["btst_eligible"].mean()), 4) if len(clean) else None,
    }
    # 一字率在 pre-filter 全体 matured 事件上算 (clean 已滤掉 unfillable → 恒 0 的统计 bug, 首跑发现)
    yizi_base = ev[(ev["matured"])]
    yizi_theme = float(yizi_base["t1_unbuyable"].mean()) if len(yizi_base) else None
    yizi_court = float(btst["t1_unbuyable"].dropna().mean()) if "t1_unbuyable" in btst else None
    exploratory: dict = {}
    for lo_d, hi_d in DIST_BANDS:
        for rg in ("normal", "crisis", "risk_off"):
            for tag in ("a_limit_up", "b_alive", "ALL"):
                sel = clean[
                    clean["days_after_confirm"].between(lo_d, hi_d)
                    & (clean["regime"] == rg)
                    & (clean["matured"])
                    & ((clean["leg"] == tag) if tag != "ALL" else True)
                ]
                sub_all = _event_stats(sel.to_dict("records"))
                sub_inc = _event_stats(sel[sel["btst_eligible"] == False].to_dict("records"))  # noqa: E712
                exploratory[f"dist{lo_d}-{hi_d}|{rg}|{tag}"] = {"all": sub_all, "incremental": sub_inc}
    signal_pct_buckets = _pct_buckets(clean)

    huazheng = ev[ev["symbol"] == "603186"][["signal_date", "leg", "days_after_confirm",
                                             "btst_eligible", "gross_ret_t8"]].to_dict("records")

    # ---- 决策分支 (四态) ----
    mean_pp = primary.get("mean_pp")
    ci_low = primary.get("ci_low_pp")
    if primary["status"] != "ok":
        decision = "inconclusive"
    elif ci_low is not None and ci_low > 0 and mean_pp is not None and mean_pp > COST_LINE_PP:
        decision = "primary_hypothesis_confirmed"
    elif mean_pp is not None and NEAR_ZERO_BAND[0] < mean_pp <= NEAR_ZERO_BAND[1]:
        decision = "near_zero_tier_b_once"
    elif mean_pp is not None and mean_pp <= NEAR_ZERO_BAND[0]:
        decision = "close_direction"
    else:
        decision = "close_direction"  # CI 不达标且均值超上界以外 → 按关闭处理 (最保守)

    report = {
        "review": "theme momentum Tier A — 行业涨停占比确认方向性验证 (计划 v3.3)",
        "generated_at": date.today().isoformat(),
        "window": {"start": sessions[0], "end": sessions[-1], "sessions": len(sessions),
                   "court_snapshot_note": "court raw 静态快照 (构建日锁死窗口)"},
        "preregistration": {
            "confirm": f"家数≥{CONFIRM_ABS_MIN} ∧ 20会话中位≤{CONFIRM_BASELINE_MAX} ∧ 占比≥{SHARE_FLOOR:.0%}",
            "survival": f"家数连续 {DEAD_RUN_LEN} 会话≤{CONFIRM_BASELINE_MAX} 熄灭 (基线锚定确认日)",
            "primary": "增量(¬BTST) × 距确认1-2 × T+8 × normal × matured × 聚类CI",
            "cost_line_pp": COST_LINE_PP,
        },
        "sanity": {"confirm_per_month": dict(sorted(by_month.items())), "violations": bad_months},
        "counts": {"confirms": len(confirms), "cycles": len(cycles),
                   "overlap": overlap,
                   "yizi_rate": {"theme_clean": yizi_theme, "btst_court_all": yizi_court}},
        "primary_hypothesis": primary,
        "exploratory": exploratory,
        "signal_pct_change_buckets_t8": signal_pct_buckets,
        "huazheng_603186_observation": huazheng,
        "decision": decision,
    }
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "primary_hypothesis", "decision")}, ensure_ascii=False, indent=2))
    print(f"产物: {out_events}\n      {out_report}")


def _mk_event(sym, ts_code, d, ind, confirm_date, dist_sessions, leg, pct, close, name,
              rg, sessions, by_day, btst_keys) -> dict:
    matured = sessions.index(d) + 10 < len(sessions) if d in sessions else False
    fwd = forward_open_returns(by_day, sessions, ts_code, d, close, sym) if matured else {
        "fillable": False, "t1_unbuyable": None, "t1_missing_bar": None, "gap_t1_open": None}
    return {
        "symbol": sym, "ts_code": ts_code, "signal_date": d,
        "industry": ind, "confirm_date": confirm_date,
        "days_after_confirm": dist_sessions, "leg": leg,
        "signal_pct_change": pct, "signal_close": close,
        "st_name": bool("ST" in (name or "").upper()),
        "regime": rg,
        "btst_eligible": (sym, d) in btst_keys,
        "matured": bool(matured),
        **fwd,
    }


def _pct_buckets(clean: pd.DataFrame) -> dict:
    out = {}
    sel = clean[clean["matured"] & clean["gross_ret_t8"].notna() & (clean["btst_eligible"] == False)]  # noqa: E712
    for lo, hi, tag in ((-100, -5, "≤-5%"), (-5, 0, "-5~0%"), (0, 5, "0~5%"), (5, 100, ">5%")):
        b = sel[sel["signal_pct_change"].between(lo, hi)]
        out[tag] = _event_stats(b.to_dict("records"))
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--granularity", default="sw_l1", choices=["sw_l1", "dc_industry"])
    main(granularity=ap.parse_args().granularity)
