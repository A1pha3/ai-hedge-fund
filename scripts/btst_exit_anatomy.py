"""BTST 退出路径解剖 — court 全候选宇宙的 MFE/MAE/时间到峰 + 诚实止损反事实.

第一性原理: 退出时机是赔率的一阶杠杆 (生产对齐 t10 avg_loss=-10.59% vs t5
-6.88%), 但既有证据只有固定 horizon 端点, 无路径级形态。本工具在 court
预注册证据宇宙 (trap 19: 全候选执行口径, 非 journal 子集) 上回答三个问题:
  ① 持有期内最优可实现退出在哪 (MFE/时间到峰) — 退出契约讨论的上界证据;
  ② 亏损有多深、何时见底 (MAE/时间到谷) — 止损启用条件 (AGENTS.md 8 项
    清单项 5: 启用前先跑退出策略证据) 的判定输入;
  ③ 止损反事实网格 — 假如设了 -X% 止损, E 会怎样 (诚实成交语义)。

纪律 (先于数据写死):
  - A 股 T+1 规则: 买入当日不可卖 — 可实现退出窗口从 T+2 起; T+1 日内
    高低价不可实现, 不进 MFE/MAE/止损路径。
  - corp-action 识别: 会话日 pre_close ≠ 上一可见收盘 (超过一档容忍) 即
    除权除息, 该事件显式排除并计数, 绝不静默用失真路径。
  - 止损诚实成交 (镜像 backtest_exit_strategies 既定纪律): 触发日 open 已
    低于止损价按 open 成交 (跳空无法按止损价成交), 日内触及按止损价;
    未触及按合约 T+10 开盘退出。
  - entry 与事件表交叉验证: signal_close×(1+gap_t1_open) 与 T+1 open 不一致
    即跳过并计数 (数据漂移不可信)。
  - 双宇宙: 生产 (event_tables) + 早期去幸存 (event_tables_early), 同一实现。
  - 确定性: 无 RNG; 同输入逐字节同输出。

纯诊断 (宪法 #2): 胜率/赔率/路径形态不替代组合路径证据; 任何止损启用或
退出契约变化 = 新证据世代 owner 决策, 本工具只产出证据。

用法:
    uv run python scripts/btst_exit_anatomy.py               # 双宇宙默认路径
    uv run python scripts/btst_exit_anatomy.py --output-json PATH --output-md PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._btst_court_common import (  # noqa: E402
    FORWARD_SESSIONS,
    RAW_DIR,
    RESEARCH_DIR,
    load_sessions,
)
from scripts.review_btst_prior_court import (  # noqa: E402
    PRODUCTION_EXCLUDE_COLS,
    candidate_universe,
)
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST  # noqa: E402

# ---- 预注册常量 (先于数据写死) ----
STOP_GRID_PCT = (-0.05, -0.08, -0.10, -0.12, -0.15)
# corp-action 容忍: 一档价格 tick (0.01) + 浮点余量; pre_close 偏差超过即视为除权
CORP_ACTION_TICK = 0.011
# entry 交叉验证相对容忍 (两路独立浮点计算)
ENTRY_CROSSCHECK_TOL = 1e-6
# 解剖日历下界 = 早期窗口起点 (生产+早期双宇宙统一)
ANATOMY_CAL_START = "20220101"

EARLY_RAW_DIR = RESEARCH_DIR / "raw_early"
EVENT_TABLE = RESEARCH_DIR / "event_tables" / "event_table_v1.csv.gz"
EVENT_TABLE_EARLY = RESEARCH_DIR / "event_tables_early" / "event_table_v1.csv.gz"

_REQUIRED_EVENT_COLS = (
    "ts_code",
    "signal_date",
    "regime",
    "signal_close",
    "gap_t1_open",
    "exit_session_t10",
    "fillable",
)
_TIME_TO_PEAK_BUCKETS = (
    "T+2",
    "T+3..T+5",
    "T+6..T+10",
    "beyond_T+10",
    "no_high_observed",
)


class ExitAnatomyError(SystemExit):
    """输入证据不可信时 fail-closed 退出 (exit 2)。"""


def _fail_closed(message: str) -> "ExitAnatomyError":
    print(f"btst_exit_anatomy: {message}", file=sys.stderr)
    return ExitAnatomyError(2)


# ---------------------------------------------------------------------------
# 数据加载 (薄 IO; 纯逻辑全部不碰文件系统)
# ---------------------------------------------------------------------------


def load_event_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise _fail_closed(f"事件表缺失: {path}")
    ev = pd.read_csv(path, dtype={"signal_date": str, "exit_session_t10": str})
    missing = [c for c in _REQUIRED_EVENT_COLS if c not in ev.columns]
    if missing:
        raise _fail_closed(f"事件表缺少必需列: {sorted(missing)}")
    return ev


def load_daily_bars(raw_dir: Path, sessions: list[str]) -> dict[str, pd.DataFrame]:
    """按需加载会话日快照 {session: frame}; 缺文件 = 该会话无行情 (合法空)。"""
    by_day: dict[str, pd.DataFrame] = {}
    for s in sessions:
        path = raw_dir / f"daily_{s}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "ts_code" not in frame.columns:
            raise _fail_closed(f"日线快照缺少 ts_code 列: {path}")
        by_day[s] = frame
    return by_day


def sessions_for_window(signal_session: str, exit_session: str, cal: list[str]) -> list[str]:
    """(signal, exit] 会话切片; exit 不在日历/超出前向窗口时按日历截断。"""
    fwd = [d for d in cal if d > signal_session][:FORWARD_SESSIONS]
    if exit_session in fwd:
        return fwd[: fwd.index(exit_session) + 1]
    return fwd


# ---------------------------------------------------------------------------
# 纯函数核心
# ---------------------------------------------------------------------------


def extract_path_bars(
    by_day: dict[str, pd.DataFrame],
    sessions: list[str],
    ts_code: str,
) -> list[dict[str, Any]]:
    """(signal, exit] 逐会话取该票 OHLC; 缺 bar 会话原样缺失 (停牌语义)。

    bars[0] = T+1 (入场日); 其余为 T+2..exit。
    """
    bars: list[dict[str, Any]] = []
    for s in sessions:
        day = by_day.get(s)
        row: pd.Series | None = None
        if day is not None:
            m = day[day["ts_code"] == ts_code]
            if not m.empty:
                row = m.iloc[0]
        bars.append(
            {
                "session": s,
                "open": None if row is None else float(row["open"]),
                "high": None if row is None else float(row["high"]),
                "low": None if row is None else float(row["low"]),
                "close": None if row is None else float(row["close"]),
                "pre_close": None if row is None else float(row["pre_close"]),
            }
        )
    return bars


def detect_corp_action(bars: list[dict[str, Any]]) -> list[str]:
    """pre_close ≠ 上一可见收盘 (超过一档容忍) 的会话列表。

    与上一*可见*收盘比较 (跨停牌仍有效: 交易所 pre_close 已按公司行动调整);
    路径首根 bar 无前收盘可比较, 不标记。
    """
    flagged: list[str] = []
    last_close: float | None = None
    for bar in bars:
        if bar["close"] is None:
            continue
        if last_close is not None and bar["pre_close"] is not None:
            if abs(bar["pre_close"] - last_close) > CORP_ACTION_TICK:
                flagged.append(bar["session"])
        last_close = bar["close"]
    return flagged


def realizable_path(bars: list[dict[str, Any]], exit_session: str) -> list[dict[str, Any]]:
    """可实现退出路径: T+2 起至 exit_session (A 股 T+1 规则, 先于数据钉死)。"""
    out: list[dict[str, Any]] = []
    for bar in bars[1:]:  # bars[0] = T+1 (入场日, 不可卖)
        out.append(bar)
        if bar["session"] == exit_session:
            break
    return out


def path_anatomy(entry: float, path: list[dict[str, Any]]) -> dict[str, Any]:
    """MFE/MAE/时间到峰/时间到谷 (index 0 = T+2); 缺 bar 会话跳过。"""
    highs = [(i, bar["high"]) for i, bar in enumerate(path) if bar["high"] is not None]
    lows = [(i, bar["low"]) for i, bar in enumerate(path) if bar["low"] is not None]
    out: dict[str, Any] = {
        "mfe": None,
        "mae": None,
        "time_to_peak": None,
        "time_to_trough": None,
        "realizable_sessions": len(path),
        "observed_sessions": len(highs),
    }
    if highs:
        peak_i, peak_high = max(highs, key=lambda t: (t[1], -t[0]))
        out["mfe"] = peak_high / entry - 1
        out["time_to_peak"] = peak_i
    if lows:
        trough_i, trough_low = min(lows, key=lambda t: (t[1], t[0]))
        out["mae"] = trough_low / entry - 1
        out["time_to_trough"] = trough_i
    return out


def stop_counterfactual(
    entry: float,
    path: list[dict[str, Any]],
    contract_exit_open: float | None,
    stop_pct: float,
) -> dict[str, Any]:
    """单档止损反事实 (诚实成交): 返回触发方式/成交会话/净收益。

    语义: 触发日 open ≤ 止损价 → 按 open 成交 (跳空穿越);
          否则日内 low ≤ 止损价 → 按止损价成交;
          全程未触及 → 按合约 T+10 开盘退出 (与基准同出口)。
    """
    stop_price = entry * (1 + stop_pct)
    for bar in path:
        if bar["open"] is None:
            continue
        if bar["open"] <= stop_price:
            fill, session, reason = bar["open"], bar["session"], "gap_through_open"
            break
        if bar["low"] is not None and bar["low"] <= stop_price:
            fill, session, reason = stop_price, bar["session"], "intrabar_touch"
            break
    else:
        if contract_exit_open is None:
            return {
                "stopped": False,
                "reason": "contract_exit_missing_bar",
                "session": None,
                "fill": None,
                "net": None,
            }
        fill, session, reason = contract_exit_open, path[-1]["session"], "contract_exit"
    return {
        "stopped": reason != "contract_exit",
        "reason": reason,
        "session": session,
        "fill": fill,
        "net": fill / entry - 1 - ROUNDTRIP_COST,
    }


def anatomy_event(
    event: pd.Series,
    by_day: dict[str, pd.DataFrame],
    cal: list[str],
    stop_grid: tuple[float, ...] = STOP_GRID_PCT,
) -> dict[str, Any] | None:
    """单事件路径解剖; entry 交叉验证失败或 T+1 缺 bar 返回 None (调用方计数)。

    corp-action 事件返回 {"excluded_corp_action": [...]} 标记 (聚合层计数)。
    """
    signal_session = str(event["signal_date"])
    exit_session = str(event["exit_session_t10"])
    sessions = sessions_for_window(signal_session, exit_session, cal)
    bars = extract_path_bars(by_day, sessions, str(event["ts_code"]))
    if not bars or bars[0]["open"] is None:
        return None
    entry = bars[0]["open"]
    expected_entry = float(event["signal_close"]) * (1 + float(event["gap_t1_open"]))
    if abs(entry / expected_entry - 1) > ENTRY_CROSSCHECK_TOL:
        return None

    corp = detect_corp_action(bars)
    if corp:
        return {"excluded_corp_action": corp, "signal_date": signal_session}

    path = realizable_path(bars, exit_session)
    exit_bar = path[-1] if path else None
    if not path or exit_bar["session"] != exit_session or exit_bar["open"] is None:
        # exit_session_t10 是 build 层前向顺延后的实际卖出会话, 其开盘必在
        # (signal, exit] 切片内; 缺失 = 数据不可信, 显式排除。
        return {"excluded_exit_bar_missing": True, "signal_date": signal_session}

    anatomy = path_anatomy(entry, path)
    anatomy["contract_exit_net"] = exit_bar["open"] / entry - 1 - ROUNDTRIP_COST
    anatomy["stops"] = {
        f"{stop_pct:.0%}": stop_counterfactual(entry, path, exit_bar["open"], stop_pct)
        for stop_pct in stop_grid
    }
    anatomy["signal_date"] = signal_session
    return anatomy


# ---------------------------------------------------------------------------
# 聚合 (确定性, 无 RNG)
# ---------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def _bucket_time_to_peak(idx: int | None) -> str:
    if idx is None:
        return "no_high_observed"
    if idx == 0:
        return "T+2"
    if idx <= 3:
        return "T+3..T+5"
    if idx <= 8:
        return "T+6..T+10"
    return "beyond_T+10"


def aggregate_anatomy(rows: list[dict[str, Any] | None]) -> dict[str, Any]:
    """行集合聚合: 形态分布 + 止损网格对比 + 排除计数。确定性输出。"""
    included = [
        r
        for r in rows
        if r is not None
        and not r.get("excluded_corp_action")
        and not r.get("excluded_exit_bar_missing")
    ]
    out: dict[str, Any] = {
        "n_events": len(rows),
        "n_entry_crosscheck_failed": sum(1 for r in rows if r is None),
        "n_corp_action_excluded": sum(1 for r in rows if r and r.get("excluded_corp_action")),
        "n_exit_bar_missing": sum(1 for r in rows if r and r.get("excluded_exit_bar_missing")),
        "n_included": len(included),
    }
    if not included:
        out["base"] = {"n": 0, "mean_net": None}
        return out
    mfe = [r["mfe"] for r in included if r["mfe"] is not None]
    mae = [r["mae"] for r in included if r["mae"] is not None]
    base_net = [
        r["contract_exit_net"] for r in included if r["contract_exit_net"] is not None
    ]
    out["mfe"] = {
        "p25": _percentile(mfe, 0.25),
        "p50": _percentile(mfe, 0.50),
        "p75": _percentile(mfe, 0.75),
    }
    out["mae"] = {
        "p25": _percentile(mae, 0.25),
        "p50": _percentile(mae, 0.50),
        "p75": _percentile(mae, 0.75),
    }
    base_mean = sum(base_net) / len(base_net) if base_net else None
    out["base"] = {"n": len(base_net), "mean_net": base_mean}
    buckets: dict[str, int] = {}
    for r in included:
        key = _bucket_time_to_peak(r["time_to_peak"])
        buckets[key] = buckets.get(key, 0) + 1
    out["time_to_peak_buckets"] = {k: buckets.get(k, 0) for k in _TIME_TO_PEAK_BUCKETS}
    peak_ids = [r["time_to_peak"] for r in included if r["time_to_peak"] is not None]
    out["time_to_peak_sessions_mean"] = (
        sum(peak_ids) / len(peak_ids) if peak_ids else None
    )
    out["stop_grid"] = {}
    for key in (f"{p:.0%}" for p in STOP_GRID_PCT):
        nets = [
            r["stops"][key]["net"] for r in included if r["stops"][key]["net"] is not None
        ]
        mean_net = sum(nets) / len(nets) if nets else None
        out["stop_grid"][key] = {
            "n": len(nets),
            "mean_net": mean_net,
            "n_stopped": sum(1 for r in included if r["stops"][key]["stopped"]),
            "n_gap_through": sum(
                1 for r in included if r["stops"][key]["reason"] == "gap_through_open"
            ),
            "delta_vs_base": (
                mean_net - base_mean if (mean_net is not None and base_mean is not None) else None
            ),
        }
    return out


def aligned_mask(ev: pd.DataFrame) -> "pd.Series | None":
    """生产对齐布尔掩码; 缺生产过滤列时返回 None (诚实缺位, 不猜)。"""
    required = ["fillable", "gate_blocked", "price_ge_3", *PRODUCTION_EXCLUDE_COLS]
    if any(c not in ev.columns for c in required):
        return None
    universe = candidate_universe(ev)
    excluded_any = universe[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1) | (
        universe["price_ge_3"] != True  # noqa: E712
    )
    aligned_index = universe.loc[~excluded_any].index
    return ev.index.isin(aligned_index)


def analyze_universe(
    ev: pd.DataFrame,
    raw_dir: Path,
    cal: list[str],
    stop_grid: tuple[float, ...] = STOP_GRID_PCT,
) -> dict[str, Any]:
    """单宇宙端到端: 逐事件解剖 (单遍) → 全体/生产对齐/regime 分组聚合。"""
    work = ev[ev["fillable"] == True].copy()  # noqa: E712
    sessions_union = sorted(
        {
            s
            for _, e in work.iterrows()
            for s in sessions_for_window(str(e["signal_date"]), str(e["exit_session_t10"]), cal)
        }
    )
    by_day = load_daily_bars(raw_dir, sessions_union)
    rows: list[dict[str, Any] | None] = [
        anatomy_event(event, by_day, cal, stop_grid) for _, event in work.iterrows()
    ]

    mask = aligned_mask(work)
    payload: dict[str, Any] = {"all_candidates": aggregate_anatomy(rows)}
    payload["production_aligned"] = (
        aggregate_anatomy([r for r, keep in zip(rows, mask) if keep])
        if mask is not None
        else {"skipped": "production_filter_columns_missing"}
    )
    regimes = sorted({str(r) for r in work["regime"].fillna("unknown")})
    payload["by_regime"] = {
        regime: aggregate_anatomy(
            [r for r, keep in zip(rows, (work["regime"].fillna("unknown") == regime)) if keep]
        )
        for regime in regimes
    }
    return payload


# ---------------------------------------------------------------------------
# 渲染 + CLI
# ---------------------------------------------------------------------------


def _fmt_pct(v: object) -> str:
    return "—" if v is None else f"{float(v) * 100:+.2f}%"


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# BTST 退出路径解剖 (court 宇宙, 净收益扣往返 0.65%)",
        "",
        "纯诊断 (宪法 #2); 可实现窗口 T+2 起 (A 股 T+1 规则); corp-action 事件显式排除。",
        "",
    ]
    for universe, block in payload.items():
        for scope in ("all_candidates", "production_aligned"):
            agg = block.get(scope)
            if agg is None:
                continue
            lines.append(f"## {universe} / {scope}")
            lines.append("")
            if "skipped" in agg:
                lines.append(f"skipped: {agg['skipped']}")
                lines.append("")
                continue
            lines.append(
                f"n_events={agg['n_events']} included={agg['n_included']} "
                f"corp_action_excluded={agg['n_corp_action_excluded']} "
                f"exit_bar_missing={agg['n_exit_bar_missing']} "
                f"entry_crosscheck_failed={agg['n_entry_crosscheck_failed']}"
            )
            if agg["n_included"] == 0:
                lines.append("")
                continue
            lines.append("")
            lines.append("| 指标 | p25 | p50 | p75 |")
            lines.append("|---|---|---|---|")
            for key, name in (("mfe", "MFE (可实现最高)"), ("mae", "MAE (可实现最低)")):
                row = agg[key]
                lines.append(
                    f"| {name} | {_fmt_pct(row['p25'])} | {_fmt_pct(row['p50'])} "
                    f"| {_fmt_pct(row['p75'])} |"
                )
            lines.append("")
            lines.append(
                f"基准 (合约 T+10 开盘退出) 平均净收益: {_fmt_pct(agg['base']['mean_net'])}"
            )
            ttp = agg["time_to_peak_buckets"]
            n = agg["n_included"]
            lines.append(
                "时间到峰分布: "
                + ", ".join(f"{k}={v} ({v / n:.0%})" for k, v in ttp.items())
            )
            lines.append("")
            lines.append("| 止损档 | 平均净收益 | Δ vs 基准 | 触发数 | 跳空穿越 |")
            lines.append("|---|---|---|---|---|")
            lines.append(
                f"| 无止损(基准) | {_fmt_pct(agg['base']['mean_net'])} | — | 0 | 0 |"
            )
            for stop_key, s in agg["stop_grid"].items():
                lines.append(
                    f"| {stop_key} | {_fmt_pct(s['mean_net'])} | {_fmt_pct(s['delta_vs_base'])} "
                    f"| {s['n_stopped']} | {s['n_gap_through']} |"
                )
            lines.append("")
        for regime, agg in block.get("by_regime", {}).items():
            if agg["n_included"] == 0:
                continue
            base = agg["base"]["mean_net"]
            best_stop = max(
                (
                    (k, s["mean_net"])
                    for k, s in agg["stop_grid"].items()
                    if s["mean_net"] is not None
                ),
                key=lambda t: t[1],
                default=None,
            )
            lines.append(
                f"### {universe} / regime={regime}: n={agg['n_included']}, "
                f"基准 {_fmt_pct(base)}, MAE p50 {_fmt_pct(agg['mae']['p50'])}, "
                f"最佳止损档 {best_stop[0] if best_stop else '—'} "
                f"({_fmt_pct(best_stop[1]) if best_stop else '—'})"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTST 退出路径解剖 (纯诊断)")
    parser.add_argument("--event-table", type=Path, default=EVENT_TABLE)
    parser.add_argument("--event-table-early", type=Path, default=EVENT_TABLE_EARLY)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--raw-dir-early", type=Path, default=EARLY_RAW_DIR)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    cal = load_sessions(ANATOMY_CAL_START, "29991231")
    universes = {
        "production": (args.event_table, args.raw_dir),
        "early": (args.event_table_early, args.raw_dir_early),
    }
    payload: dict[str, Any] = {}
    for name, (table, raw_dir) in universes.items():
        if not table.exists():
            print(f"btst_exit_anatomy: 跳过 {name} (事件表缺失: {table})")
            continue
        ev = load_event_table(table)
        payload[name] = analyze_universe(ev, raw_dir, cal)

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(body + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_md(payload) + "\n", encoding="utf-8")
    print(body if not args.output_json else f"written: {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
