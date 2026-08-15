"""BTST court 第二步: 构建不可变事件表 (现行公式重放, 宇宙来自权威面板).

正确性契约 (预注册, 先于数据):
1. detect 通过 import 生产类复用, 绝不复制公式代码; 公式指纹 = 源文件 sha256 记入 manifest.
2. 宇宙 = 当日全市场快照过 pct≥9.5 宽松预筛 (剔除北交所, 与生产扫描空间一致),
   逐日与 limit_list_d(U) 对账, 权威涨停票整日缺行 >5% 即中止.
3. PIT 输入: ST 用当日涨停名单 name; 行业用申万成员史 in_date/out_date 区间;
   regime 用 regime_history (Window A 全覆盖断言, 缺日中止).
4. 前视纪律: ratchet 逐字复用 exit_policy.evaluate_shadow_exit — 收盘判定,
   次日开盘执行; ATR 用生产同款 compute_atr(period=14, at_idx=index+1);
   入场前需 ≥14 个因果 TR (与生产影子路径同门槁).
5. 双锚点: 合约腿 open→open (主, gross); open→close (panel 对照列) 并存不混.
6. 停牌: T+1 缺 bar → 不可成交; 退出日缺 bar → 顺延至 T+15 内下一可用开盘,
   超限记 None 并由 views 计数 (不编造价格).

写入: 仅 data/research/btst_court/event_tables/ (event_table_v1 + manifest).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import (  # noqa: E402
    FORWARD_SESSIONS,
    RAW_DIR,
    REGIME_GATE_BLOCK,
    TABLE_DIR,
    WINDOW_A_START,
    load_regime_history,
    load_sessions,
)

from src.screening.offensive.atr_utils import compute_atr  # noqa: E402
from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402
from src.screening.offensive.exit_policy import (  # noqa: E402
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup  # noqa: E402
from src.tools.ashare_board_utils import (  # noqa: E402
    is_beijing_exchange_ts_code,
    is_excluded_ticker,
    limit_up_cap_pct_for_ticker,
)

_PRICE_COLS = {"open", "high", "low", "close", "pct_chg", "vol"}


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_panel() -> pd.DataFrame:
    frames = [pd.read_csv(p, dtype={"trade_date": str}) for p in sorted((RAW_DIR / "daily").glob("daily_*.csv"))]
    if not frames:
        raise SystemExit("panel empty — 先跑 scripts/btst_court_fetch.py")
    df = pd.concat(frames, ignore_index=True)
    for col in _PRICE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "open"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def load_limit_up_index() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for p in sorted((RAW_DIR / "limit_up").glob("lu_*.csv")):
        d = p.stem.split("_")[1]
        df = pd.read_csv(p, dtype=str)
        out[d] = df if not df.empty else pd.DataFrame(columns=["ts_code", "name"])
    return out


def load_sw_industry() -> "pd.Series":
    """→ DataFrame(symbol, l1_name, in, out) 行列表 (PIT 成员区间)."""
    sw = pd.read_csv(RAW_DIR / "sw_members.csv", dtype=str)
    codes_map = json.loads(Path("data/industry_index_cache/_industry_codes.json").read_text(encoding="utf-8"))
    norm = {str(k).split(".")[0]: v for k, v in codes_map.items()}
    sw["l1_name"] = sw["l1_code"].map(lambda c: norm.get(str(c or "").split(".")[0], ""))
    sw["symbol"] = sw["ts_code"].str.split(".").str[0]
    sw["in"] = sw["in_date"].fillna("").str.replace("-", "")
    sw["out"] = sw["out_date"].fillna("").str.replace("-", "")
    unknown_ratio = (sw["l1_name"] == "").mean() if len(sw) else 0
    if unknown_ratio > 0.2:
        raise SystemExit(f"SW 成员 l1_code 与 _industry_codes.json 对不上 (unknown {unknown_ratio:.0%})")
    return sw[["symbol", "l1_name", "in", "out"]]


def industry_of(sw_rows: dict[str, list], symbol: str, yyyymmdd: str) -> str | None:
    for l1_name, d_in, d_out in sw_rows.get(symbol, []):
        if d_in and d_in > yyyymmdd:
            continue
        if d_out and d_out <= yyyymmdd:
            continue
        if l1_name:
            return l1_name
    return None


def ticker_frame(group: pd.DataFrame, upto: str) -> pd.DataFrame:
    """detect 语义的 prices 帧 (date/open/high/low/close/volume/pct_change), 截止 upto."""
    sub = group[group["trade_date"] <= upto]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(sub["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "open": sub["open"].astype(float),
            "high": sub["high"].astype(float),
            "low": sub["low"].astype(float),
            "close": sub["close"].astype(float),
            "volume": sub["vol"].astype(float),
            "pct_change": sub["pct_chg"].astype(float),
        }
    ).reset_index(drop=True)


def ratchet_replay(frame: pd.DataFrame, entry_idx: int, entry_price: float) -> tuple[int, str] | None:
    """逐字复用生产 evaluate_shadow_exit → (exit_row_idx, reason); exit = 该行次日语义由调用方按开盘执行.

    注: 返回的 idx 已是"触发收盘后的下一行" (should_exit_next_open 语义),
    即出场发生在 frame 行 idx 的开盘.
    """
    dates_raw = list(frame["date"])
    closes = frame["close"].astype(float).tolist()
    state = ExitPolicyState.unarmed(entry_price=entry_price)
    for index in range(entry_idx, min(entry_idx + FORWARD_SESSIONS, len(frame))):
        atr = compute_atr(frame, period=14, at_idx=index + 1)
        if atr is None:
            return None
        d = dates_raw[index]
        decision = evaluate_shadow_exit(
            state,
            ExitObservation(
                trade_date=date(int(d[:4]), int(d[5:7]), int(d[8:10])),
                holding_session=index - entry_idx + 1,
                close=closes[index],
                atr=atr,
            ),
        )
        state = decision.state
        if decision.should_exit_next_open:
            return index + 1, decision.reason
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()
    end = args.end or date.today().strftime("%Y%m%d")

    sessions_cal = load_sessions(WINDOW_A_START, end)
    regime = load_regime_history()
    # regime_history 已知空窗 (AGENTS.md: 停在 20260707, 2026-07-18 起才有生产写入者):
    # 缺标签日 fail-closed 剔除信号日并披露 — 绝不静默退化 normal (07-14 大亏日正在空窗内).
    regime_missing = [s for s in sessions_cal if s not in regime]
    sessions_cal = [s for s in sessions_cal if s in regime]
    if regime_missing:
        print(f"  [warn] regime 缺标签 {len(regime_missing)} 天, 剔除: {regime_missing}")
        if len(regime_missing) / max(1, len(regime_missing) + len(sessions_cal)) > 0.10:
            raise SystemExit(f"regime 缺口 >10% ({len(regime_missing)} 天) — court 无意义, 中止")

    print("[1/6] 加载面板…")
    panel = load_panel()
    limit_up = load_limit_up_index()
    sw = load_sw_industry()
    sw_rows: dict[str, list] = {}
    for r in sw.itertuples(index=False):  # "in" 是关键字, pandas 会改字段名 → 用位置索引
        sw_rows.setdefault(r[0], []).append((r[1], r[2], r[3]))
    from scripts.setup_research import load_industry_day_pct

    industry_day_pct = load_industry_day_pct()
    print(f"  panel rows={len(panel):,} tickers={panel['ts_code'].nunique():,}")

    print("[2/6] 建索引…")
    by_day = {d: g for d, g in panel.groupby("trade_date")}
    groups = {c: g for c, g in panel.groupby("ts_code")}
    panel_dates = set(by_day.keys())
    sessions = [s for s in sessions_cal if s in panel_dates]
    print(f"  Window A sessions={len(sessions)} ({sessions[0]}..{sessions[-1]})")

    flow_store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    ff_cache: dict[str, list] = {}
    setup = BtstBreakoutSetup()

    events: list[dict] = []
    funnel = {"sessions": 0, "prefilter": 0, "history_short": 0, "hits": 0, "misses": 0}
    universe_audit = {"days_checked": 0, "auth_total": 0, "panel_missing": 0, "below_prefilter": 0}

    print("[3/6] 逐日重放 detect (现行公式)…")
    for si, s in enumerate(sessions):
        day = by_day[s]
        funnel["sessions"] += 1
        cand = day[(day["pct_chg"] >= 9.5) & day["ts_code"].notna()]
        cand = cand[~cand["ts_code"].map(is_beijing_exchange_ts_code)]
        funnel["prefilter"] += len(cand)

        auth = limit_up.get(s)
        auth_names: dict[str, str] = {}
        if auth is not None and not auth.empty:
            auth_names = dict(zip(auth["ts_code"], auth["name"].astype(str)))
            auth_sse = auth[~auth["ts_code"].map(is_beijing_exchange_ts_code)]
            need = set(auth_sse["ts_code"])
            if need:
                gap = need - set(day["ts_code"])
                if len(gap) / len(need) > 0.05:
                    raise SystemExit(f"universe gap {len(gap)}/{len(need)} on {s} 超 5% — 面板不完备, 中止")
                universe_audit["days_checked"] += 1
                universe_audit["auth_total"] += len(need)
                universe_audit["panel_missing"] += len(gap)
                universe_audit["below_prefilter"] += len(need - set(cand["ts_code"]))

        for row in cand.itertuples():
            ts_code, symbol = row.ts_code, str(row.ts_code).split(".")[0]
            group = groups.get(ts_code)
            if group is None:
                continue
            frame = ticker_frame(group, s)
            if len(frame) < 25 or frame.iloc[-1]["date"].replace("-", "") != s:
                funnel["history_short"] += 1
                continue

            flows = ff_cache.get(symbol)
            if flows is None:
                # 缓存全历史 (detect 内部自按 r.date ≤ trade_date 过滤, 语义等价).
                # ❌ 不可缓存日期截断结果: 同票后续涨停日会复用陈旧列表 → 条件2 恒 miss
                # (交叉验证 11/11 not_in_replay 即此 bug, 2026-08-15).
                flows = flow_store.get_range(symbol, "20200101", end)
                ff_cache[symbol] = flows
            ind_name = industry_of(sw_rows, symbol, s)
            ind_pct = industry_day_pct.get((ind_name, s)) if ind_name else None
            try:
                result = setup.detect(
                    symbol,
                    s,
                    {
                        "prices": frame,
                        "fund_flow_records": flows,
                        "industry_day_pct": ind_pct,
                        "regime": regime[s],
                    },
                )
            except Exception:  # noqa: BLE001 - 单票异常不拖垮全日, 不计入 hits
                continue
            if not result.hit:
                funnel["misses"] += 1
                continue
            funnel["hits"] += 1
            events.append(
                _build_event(groups, by_day, sessions_cal, symbol, ts_code, s, float(row.close), result, regime[s], auth_names, ind_name, frame)
            )
        if si % 40 == 0:
            print(f"  {s} 累计 hits={funnel['hits']}")

    print(f"[4/6] events={len(events)} funnel={funnel}")
    if not events:
        raise SystemExit("零事件 — 检查面板/资金流覆盖")
    table = pd.DataFrame(events)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    # 防覆盖护栏 (对抗性审查 2026-08-15): 必须在写入前判定 — 公式指纹变化时拒绝
    # 覆盖既有 v1 (行为变化必须开新版本文件); 同指纹重建 (bug 修复) 允许并记 rebuild_count.
    new_fp = _file_sha256("src/screening/offensive/setups/btst_breakout.py")
    prior_manifest = TABLE_DIR / "manifest_v1.json"
    rebuild_count = 0
    if prior_manifest.exists():
        prior = json.loads(prior_manifest.read_text(encoding="utf-8"))
        prior_fp = prior.get("formula_fingerprint", {}).get("btst_breakout_sha256")
        if prior_fp and prior_fp != new_fp:
            raise SystemExit(
                f"event_table_v1 已由不同公式指纹构建 ({prior_fp[:8]} → {new_fp[:8]}): "
                "行为变化须写新版本文件, 不覆盖; 如确要覆盖用 --rebuild-force"
            )
        rebuild_count = int(prior.get("rebuild_count", 0)) + 1
    out = TABLE_DIR / "event_table_v1.parquet"
    try:
        table.to_parquet(out, index=False)
    except Exception:  # noqa: BLE001 - 无 pyarrow 退 csv.gz
        out = TABLE_DIR / "event_table_v1.csv.gz"
        table.to_csv(out, index=False, compression="gzip")

    print("[5/6] 公式钉住交叉验证 (vs panel 新代)…")
    xcheck = _cross_check_vs_panel(table)

    manifest = {
        "version": 1,
        "built_at": date.today().isoformat(),
        "git_sha": _git_sha(),
        "formula_fingerprint": {
            "btst_breakout_sha256": _file_sha256("src/screening/offensive/setups/btst_breakout.py"),
            "exit_policy_sha256": _file_sha256("src/screening/offensive/exit_policy.py"),
        },
        "window": {"start": WINDOW_A_START, "end": end, "sessions": len(sessions)},
        "regime_missing_sessions": regime_missing,
        "funnel": funnel,
        "universe_audit": universe_audit,
        "cross_check_vs_panel": xcheck,
        "rebuild_count": rebuild_count,
        "rows": len(table),
        "artifact": out.name,
    }
    (TABLE_DIR / "manifest_v1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[6/6] manifest 写入完成")
    print(json.dumps({k: manifest[k] for k in ("window", "funnel", "universe_audit", "cross_check_vs_panel", "rows")}, ensure_ascii=False, indent=2))


def _build_event(groups, by_day, sessions_cal, symbol, ts_code, s, signal_close, result, regime_label, auth_names, ind_name, hist_frame) -> dict:
    """单 hit 事件: 标志 + 前向路径 + 各退出策略 gross 收益 (合约腿 open→open)."""
    md = result.metadata or {}
    fwd = [d for d in sessions_cal if d > s][:FORWARD_SESSIONS]

    bars = []  # (open, close, pre_close) 按持有Session 1..15
    for d in fwd:
        day = by_day.get(d)
        r = None
        if day is not None:
            m = day[day["ts_code"] == ts_code]
            if not m.empty:
                r = m.iloc[0]
        bars.append((float(r["open"]), float(r["close"]), float(r["pre_close"])) if r is not None else (None, None, None))

    t1_open = bars[0][0] if bars else None
    t1_unbuyable = False
    if t1_open is not None and bars[0][2] and bars[0][2] > 0:
        cap = limit_up_cap_pct_for_ticker(symbol)
        limit_price = round(bars[0][2] * (1 + cap / 100), 2)
        t1_unbuyable = t1_open >= limit_price - 0.001
    fillable = t1_open is not None and not t1_unbuyable
    gap = (t1_open / signal_close - 1) if (t1_open and signal_close > 0) else None

    ev = {
        "symbol": symbol,
        "ts_code": ts_code,
        "signal_date": s,
        "regime": regime_label,
        "trigger_strength": float(result.trigger_strength),
        "board_score": md.get("board_score"),
        "low_vol_score": md.get("low_vol_score"),
        "squeeze_score": md.get("squeeze_score"),
        "volume_score": md.get("volume_score"),
        "range_score": md.get("range_score"),
        "energy_bonus": md.get("energy_bonus"),
        "signal_close": signal_close,
        "gap_t1_open": gap,
        "fillable": fillable,
        "t1_unbuyable": t1_unbuyable,
        "t1_missing_bar": t1_open is None,
        "degraded": bool(getattr(result, "degraded", False)),
        "industry_missing": ind_name is None,
        "industry_name": ind_name,
        "st_name": bool("ST" in (auth_names.get(ts_code) or "").upper()),
        "excluded_ticker": bool(is_excluded_ticker(symbol)),
        "price_ge_3": signal_close >= 3.0,
        "gate_blocked": regime_label in REGIME_GATE_BLOCK,
    }

    if not fillable:
        return ev
    entry = t1_open

    def fixed_open(k: int):
        """T+k 开盘; 缺 bar 顺延至 T+15 内下一可用开盘 (窗口末端 bars 可能不足 15)."""
        for j in range(k - 1, min(FORWARD_SESSIONS, len(bars))):
            if bars[j][0] is not None:
                return bars[j][0], j + 1
        return None

    for k in (3, 5, 8, 10):
        ex = fixed_open(k)
        ev[f"exit_open_t{k}"] = ex[0] if ex else None
        ev[f"exit_session_t{k}"] = ex[1] if ex else None
        ev[f"gross_ret_t{k}"] = (ex[0] / entry - 1) if ex else None
        close_k = bars[k - 1][1] if k - 1 < len(bars) else None
        ev[f"ret_close_anchor_t{k}"] = (close_k / entry - 1) if close_k else None

    # ratchet: 历史帧 + 前向 bar 拼成持仓评估帧 (生产同源: 全历史, entry 前 ≥14 TR)
    ext = ticker_frame(groups[ts_code], fwd[-1] if fwd else s)
    entry_idx = int((ext["date"].str.replace("-", "") <= s).sum())  # T+1 的 0-based 行号
    if entry_idx >= 14:
        rat = ratchet_replay(ext, entry_idx, entry)
        if rat is not None:
            idx, reason = rat
            opens = ext["open"].astype(float).tolist()
            ex_open = next((o for o in opens[idx : idx + FORWARD_SESSIONS] if o == o), None)
            if ex_open is not None and idx - entry_idx < FORWARD_SESSIONS:
                ev["ratchet_reason"] = reason
                ev["ratchet_exit_session"] = idx - entry_idx + 1
                ev["ratchet_gross_ret"] = ex_open / entry - 1
    return ev


def _cross_check_vs_panel(table: pd.DataFrame) -> dict:
    """公式代际交叉验证: 重放强度 vs panel 新代 (2026-08-09 后) 记录."""
    panel_path = Path("data/reports/setup_output_panel.jsonl")
    if not panel_path.exists():
        return {"status": "panel_missing"}
    recs = [json.loads(l) for l in panel_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    new_gen = [r for r in recs if str(r.get("logged_at", ""))[:10] >= "2026-08-09"]
    matched = mismatched = absent = 0
    details = []
    for r in new_gen:
        key = (str(r.get("ticker")), str(r.get("signal_date"))[:8].replace("-", ""))
        m = table[(table["symbol"] == key[0]) & (table["signal_date"] == key[1])]
        if m.empty:
            absent += 1
            details.append({"ticker": key[0], "date": key[1], "status": "not_in_replay"})
            continue
        replay_ts = float(m.iloc[0]["trigger_strength"])
        panel_ts = float(r.get("trigger_strength") or 0)
        if abs(replay_ts - panel_ts) < 1e-6:
            matched += 1
        else:
            mismatched += 1
            details.append({"ticker": key[0], "date": key[1], "replay": replay_ts, "panel": panel_ts})
    return {"new_gen_records": len(new_gen), "matched": matched, "mismatched": mismatched, "absent": absent, "details": details[:12]}


if __name__ == "__main__":
    main()
