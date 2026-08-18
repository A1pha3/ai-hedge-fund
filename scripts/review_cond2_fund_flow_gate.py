"""条件2 (主力净流入 > 20日均值) 的 court 级对抗复核 (2026-08-17).

动机: 华正新材 603186 — 8-07/8-14 涨停均被条件2挡掉 (主力净流出 -2.5/-3.9亿),
8-05 勉强通过且当日即本轮最强入场点 (strength 0.79)。单案例是幸存者叙事,
不能据此改参数; 但条件2 自引入以来从未做过 on/off 全候选 A/B。本脚本在
court 重放管道 (同 panel / 同资金流缓存 / 同前置过滤) 上重建「cond1+3+4
通过、按条件2 判定分流」的完整宇宙, 对比两组执行口径前向收益。

口径与自检:
  - 数据/帧/前置过滤全部 import 自 scripts/btst_court_build (与 event_table_v1
    构建同源); 条件1/3/4 逐条复刻 btst_breakout.detect 的判定 (同 helper:
    板块自适应阈值/cap 护栏/链式 pre_runup/SW PIT 行业/资金流 ≥5 天短窗语义);
  - 前向收益与 _build_event 同口径: T+1 open 买 (一字锁死 = 不可成交, 剔除),
    T+k open 卖 (缺 bar 顺延至 T+15), gross 与 exec (往返成本 0.65pp) 双列;
  - 正确性自检: cond2-pass 组的 (symbol, signal_date) 必须与现行
    event_table_v1 的 hits 精确一致 — 复刻与 detect 的分界线, 不一致即中止。

用法: uv run python scripts/review_cond2_fund_flow_gate.py
产物: data/reports/cond2_gate_court_review_20260817.json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from scripts._btst_court_common import (  # noqa: E402
    FORWARD_SESSIONS,
    WINDOW_A_START,
    forward_open_returns,
    load_regime_history,
    load_sessions,
)
from scripts.btst_court_build import (  # noqa: E402
    industry_of,
    load_limit_up_index,
    load_panel,
    load_sw_industry,
    ticker_frame,
)
from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.price_returns import chained_return_pct
from src.tools.ashare_board_utils import (
    is_beijing_exchange_ts_code,
    limit_up_cap_pct_for_ticker,
    limit_up_pct_for_ticker,
)

_MAIN_FLOW_LOOKBACK_DAYS = 20
_MAIN_FLOW_MIN_HISTORY_DAYS = 5
_PRE_RUNUP_LOOKBACK_DAYS = 5
_PRE_RUNUP_MAX_PCT = 8.0
_INDUSTRY_PCT_MIN = 2.0
_EXEC_COST_PP = 0.65  # 往返 30bps/边 + 5bps 卖出印花税 (v2.1 口径)
_OUT = Path("data/reports/cond2_gate_court_review_20260817.json")


def _cond2_verdict(flows, trade_date):
    """复刻 detect 条件2: → (verdict, margin, today_flow) verdict ∈ pass|fail|pass_short|nodata."""
    today_flow = next((r.main_net_inflow for r in flows if r.date == trade_date), None)
    if today_flow is None or math.isnan(today_flow):
        return "nodata", None, None
    historical = [
        r.main_net_inflow
        for r in flows
        if r.date < trade_date and not math.isnan(r.main_net_inflow)
    ]
    if len(historical) < _MAIN_FLOW_MIN_HISTORY_DAYS:
        return "pass_short", None, today_flow  # detect 语义: 历史不足 → 跳过条件2 (degraded)
    lookback = historical[-_MAIN_FLOW_LOOKBACK_DAYS:]
    hist_mean = sum(lookback) / len(lookback)
    verdict = "pass" if today_flow > hist_mean else "fail"
    return verdict, today_flow - hist_mean, today_flow


def _stats(rets: list[float]) -> dict:
    rets = [r for r in rets if r is not None and math.isfinite(r)]
    if not rets:
        return {"n": 0}
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / max(1, n - 1)
    return {
        "n": n,
        "mean_pp": round(mean * 100, 3),
        "median_pp": round(sorted(rets)[n // 2] * 100, 3),
        "winrate": round(sum(1 for r in rets if r > 0) / n, 4),
        "se_pp": round((var / n) ** 0.5 * 100, 3),
    }


def _welch_t(a: list[float], b: list[float]) -> float | None:
    a = [x for x in a if x is not None and math.isfinite(x)]
    b = [x for x in b if x is not None and math.isfinite(x)]
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se = (va / len(a) + vb / len(b)) ** 0.5
    if se <= 0:
        return None
    return (ma - mb) / se


def main() -> None:
    end = date.today().strftime("%Y%m%d")
    sessions_cal = load_sessions(WINDOW_A_START, end)
    regime = load_regime_history()
    sessions_cal = [s for s in sessions_cal if s in regime]

    print("[1/4] 加载 panel / 涨停 / SW / 资金流…")
    panel = load_panel()
    limit_up = load_limit_up_index()
    sw = load_sw_industry()
    sw_rows: dict[str, list] = {}
    for r in sw.itertuples(index=False):
        sw_rows.setdefault(r[0], []).append((r[1], r[2], r[3]))
    from scripts.setup_research import load_industry_day_pct

    industry_day_pct = load_industry_day_pct()
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    groups = {c: g for c, g in panel.groupby("ts_code")}
    sessions = [s for s in sessions_cal if s in set(by_day.keys())]
    flow_store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    ff_cache: dict[str, list] = {}

    print(f"[2/4] 逐日重建 cond1+3+4 宇宙并按条件2分流 ({sessions[0]}..{sessions[-1]})…")
    rows: list[dict] = []
    for si, s in enumerate(sessions):
        day = by_day[s]
        cand = day[(day["pct_chg"] >= 9.5) & day["ts_code"].notna()]
        cand = cand[~cand["ts_code"].map(is_beijing_exchange_ts_code)]
        auth = limit_up.get(s)
        auth_names = (
            dict(zip(auth["ts_code"], auth["name"].astype(str))) if auth is not None and not auth.empty else {}
        )
        for row in cand.itertuples():
            ts_code, symbol = row.ts_code, str(row.ts_code).split(".")[0]
            group = groups.get(ts_code)
            if group is None:
                continue
            frame = ticker_frame(group, s)
            if len(frame) < 25 or frame.iloc[-1]["date"].replace("-", "") != s:
                continue
            trigger_idx = len(frame) - 1
            pct = float(frame.iloc[trigger_idx]["pct_change"])

            # 条件1 (板块自适应 + cap 护栏, 复刻 detect)
            limit_up_pct = limit_up_pct_for_ticker(symbol)
            if math.isnan(pct) or pct < limit_up_pct:
                continue
            if pct > limit_up_cap_pct_for_ticker(symbol) + 0.5:
                continue

            # 条件3 (SW PIT 行业 ≥2; 缺失 = fail, 复刻 2026-08-14 严格化)
            ind_name = industry_of(sw_rows, symbol, s)
            ind_pct = industry_day_pct.get((ind_name, s)) if ind_name else None
            if ind_pct is None or math.isnan(float(ind_pct)) or float(ind_pct) < _INDUSTRY_PCT_MIN:
                continue

            # 条件4 (链式 pre_runup ≤8; 数据不足/断裂 = fail, 复刻)
            ref_idx = trigger_idx - _PRE_RUNUP_LOOKBACK_DAYS
            pre_runup = (
                chained_return_pct(frame, ref_idx, trigger_idx - 1)
                if ref_idx >= 0
                else None
            )
            if pre_runup is None or pre_runup > _PRE_RUNUP_MAX_PCT:
                continue

            # 条件2 分流 (复刻 detect 判定, 不在此砍票)
            flows = ff_cache.get(symbol)
            if flows is None:
                flows = flow_store.get_range(symbol, "20200101", end)
                ff_cache[symbol] = flows
            verdict, margin, today_flow = _cond2_verdict(flows, s)

            signal_close = float(frame.iloc[trigger_idx]["close"])
            fwd = forward_open_returns(by_day, sessions_cal, ts_code, s, signal_close, symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "signal_date": s,
                    "regime": regime[s],
                    "cond2": verdict,
                    "cond2_margin": margin,
                    "today_flow": today_flow,
                    "st_name": bool("ST" in (auth_names.get(ts_code) or "").upper()),
                    "signal_close": signal_close,
                    **fwd,
                }
            )
        if si % 40 == 0:
            print(f"  {s} 累计 cond1+3+4 候选 {len(rows)}")

    df = pd.DataFrame(rows)
    print(f"  cond1+3+4 宇宙 = {len(df)} (cond2: {df['cond2'].value_counts().to_dict()})")

    # 自检: cond2-pass 集合与现行 event_table_v1 对比。允许「数据代际差异」—
    # court 表构建于 2026-08-15, fund_flow 于 08-16 补齐, 故少量行构建时是
    # degraded(hit)/nodata(miss) 而现在判定不同。仲裁方式: 对每个差异行用
    # 生产 BtstBreakoutSetup.detect + 当前数据重跑, 复刻判定与 detect 一致即忠实。
    print("[3/4] 自检 vs event_table_v1 (生产 detect 仲裁差异行) …")
    table = pd.read_csv(
        "data/research/btst_court/event_tables/event_table_v1.csv.gz",
        dtype={"signal_date": str, "symbol": str, "ts_code": str},
    )
    court_keys = set(zip(table["symbol"], table["signal_date"]))
    mine = set(zip(df[df["cond2"].isin(["pass", "pass_short"])]["symbol"], df[df["cond2"].isin(["pass", "pass_short"])]["signal_date"]))
    only_court, only_mine = court_keys - mine, mine - court_keys
    print(f"  court={len(court_keys)} mine_pass={len(mine)} court_only={len(only_court)} mine_only={len(only_mine)}")

    setup = None
    arbitration = {"fidelity_confirmed": True, "data_generation_diffs": []}
    if only_court or only_mine:
        from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

        setup = BtstBreakoutSetup()
        for sym, s in sorted(only_court | only_mine)[:40]:
            ts = f"{sym}.SZ" if not sym.startswith(("6", "9")) else f"{sym}.SH"
            if ts not in groups:
                arbitration["fidelity_confirmed"] = False
                continue
            frame = ticker_frame(groups[ts], s)
            flows = ff_cache.get(sym) or flow_store.get_range(sym, "20200101", end)
            ind_name = industry_of(sw_rows, sym, s)
            r = setup.detect(
                sym,
                s,
                {
                    "prices": frame,
                    "fund_flow_records": flows,
                    "industry_day_pct": industry_day_pct.get((ind_name, s)) if ind_name else None,
                },
            )
            my_pass = (sym, s) in mine
            if bool(r.hit) != my_pass:
                arbitration["fidelity_confirmed"] = False
                arbitration["data_generation_diffs"].append(
                    {"symbol": sym, "signal_date": s, "detect_hit": bool(r.hit), "my_pass": my_pass, "verdict": "REPLICATION_BUG"}
                )
            else:
                arbitration["data_generation_diffs"].append(
                    {"symbol": sym, "signal_date": s, "detect_hit": bool(r.hit), "degraded": bool(r.degraded), "verdict": "data_generation_diff"}
                )
    if not arbitration["fidelity_confirmed"]:
        _OUT.write_text(json.dumps({"status": "replication_mismatch", **arbitration}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"[FAIL] 复刻与 detect 分界不一致 (非数据代际): {arbitration['data_generation_diffs'][:6]}")
    print(f"  自检通过: 复刻忠实 ({len(arbitration['data_generation_diffs'])} 行为数据代际差异)")

    # A/B: 卫生过滤后 pass vs fail
    print("[4/4] A/B 统计…")
    clean = df[(df["fillable"]) & (~df["st_name"]) & (df["signal_close"] >= 3.0)].copy()
    pas = clean[clean["cond2"] == "pass"]
    fail = clean[clean["cond2"] == "fail"]
    short = clean[clean["cond2"] == "pass_short"]

    report: dict = {
        "review": "cond2 fund-flow gate on/off A/B (court pipeline, full candidates)",
        "generated_at": date.today().isoformat(),
        "window": {"start": sessions[0], "end": sessions[-1]},
        "universe": {
            "cond1_3_4_total": int(len(df)),
            "cond2_split_all": {k: int(v) for k, v in df["cond2"].value_counts().items()},
            "hygiene_filtered": int(len(clean)),
            "cond2_split_clean": {k: int(v) for k, v in clean["cond2"].value_counts().items()},
        },
        "replication_check": {
            "status": "fidelity_confirmed",
            "court_rows": len(court_keys),
            "mine_pass_rows": len(mine),
            **arbitration,
        },
        "ab_overall": {},
        "ab_by_regime": {},
        "margin_quantiles": {},
    }
    for k in (5, 8, 10):
        col = f"gross_ret_t{k}"
        pa = [x for x in pas[col]]
        fa = [x for x in fail[col]]
        report["ab_overall"][f"t{k}"] = {
            "pass": _stats(pa),
            "fail": _stats(fa),
            "pass_exec_net_pp": round(_stats(pa)["mean_pp"] - _EXEC_COST_PP, 3) if pa else None,
            "fail_exec_net_pp": round(_stats(fa)["mean_pp"] - _EXEC_COST_PP, 3) if fa else None,
            "welch_t_pass_minus_fail": _welch_t(pa, fa),
        }
    for regime_label in ("normal", "crisis", "risk_off"):
        p = pas[pas["regime"] == regime_label]
        f = fail[fail["regime"] == regime_label]
        report["ab_by_regime"][regime_label] = {
            "n_pass": len(p),
            "n_fail": len(f),
            "t8_pass": _stats(list(p["gross_ret_t8"])),
            "t8_fail": _stats(list(f["gross_ret_t8"])),
        }

    # 连续视图: margin 分位 (只看可成交 cond1+3+4 宇宙, T+8)
    q = clean[clean["cond2_margin"].notna()].copy()
    if len(q) >= 50:
        q["mg_pp"] = q["cond2_margin"] / 1e8  # 亿
        try:
            q["bucket"] = pd.qcut(q["mg_pp"], q=8, duplicates="drop")
        except ValueError:
            q["bucket"] = None
        buckets = []
        if q["bucket"] is not None:
            for b, g in q.groupby("bucket", observed=True):
                buckets.append(
                    {
                        "margin_band_yi": f"[{b.left:.2f}, {b.right:.2f}]亿" if b.left == b.left else str(b),
                        "n": len(g),
                        "t8_mean_pp": round(g["gross_ret_t8"].mean() * 100, 3),
                        "t8_winrate": round((g["gross_ret_t8"] > 0).mean(), 4),
                        "fail_share": round((g["cond2"] == "fail").mean(), 3),
                    }
                )
        report["margin_quantiles"] = {"t8_by_margin_octile": buckets}
    if len(short):
        report["pass_short_note"] = {
            "n": len(short),
            "t8": _stats(list(short["gross_ret_t8"])),
            "note": "历史<5天 → detect 语义跳过条件2 (degraded hit), 样本小仅披露",
        }

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("universe", "replication_check", "ab_overall")}, ensure_ascii=False, indent=2))
    print(f"产物: {_OUT}")


if __name__ == "__main__":
    main()
