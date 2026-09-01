"""BTST 持有期全曲线 — court 双宇宙 t2..t15 逐 k 退出证据.

第一性原理: 退出契约 (T+10 开盘) 是组合单位净值的一阶参数, 但既有证据
只有 t3/t5/t8/t10 四个固定端点。本工具在 court 预注册证据宇宙上给出
t2..t15 连续曲线: 逐 k 的 n/胜率/avg_win/avg_loss/payoff/E/聚类 CI90
下界 + 与 T+10 基准的差值。生产对齐 t5 (E +0.20%, avg_loss −6.88%) vs
t10 (E +0.25%, avg_loss −10.59%) 的讨论自此有一等连续证据。

纪律 (先于数据写死):
  - T+k 顺延语义与 build 层单一事实源逐一对应 (btst_court_build.fixed_open):
    T+k 缺 bar 顺延至 T+15 内下一可用开盘; 窗口末端不足则该 k 无退出
    (披露计数, 绝不静默丢弃事件)。
  - corp-action 事件整体排除 (复用 btst_exit_anatomy.detect_corp_action
    单一实现, 与退出解剖同口径)。
  - t10 交叉验证哨点: 本工具 t10 毛收益逐事件与事件表 gross_ret_t10 一致
    (1e-9), 不一致即 fail-closed — 工具口径与 court 口径漂移不可能静默。
  - 聚类 CI 复用 winrate_payoff_decomposition.cluster_boot_ci_low 单一
    实现 (per-call seeded RNG, R13 纪律); n<30 只披露不判定 (MIN_CELL_N)。
  - 确定性: 同输入逐字节同输出。

纯诊断 (宪法 #2): 持有期契约变化 = 新证据世代 owner 决策, 本工具只产出证据。

用法:
    uv run python scripts/btst_horizon_curve.py
    uv run python scripts/btst_horizon_curve.py --output-json PATH --output-md PATH
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

from scripts.btst_exit_anatomy import (  # noqa: E402
    ANATOMY_CAL_START,
    EARLY_DAILY_DIR,
    EVENT_TABLE,
    EVENT_TABLE_EARLY,
    RAW_DAILY_DIR,
    detect_corp_action,
    extract_path_bars,
    load_daily_bars,
    load_event_table,
    sessions_for_window,
)
from scripts._btst_court_common import FORWARD_SESSIONS  # noqa: E402
from scripts.winrate_payoff_decomposition import (  # noqa: E402
    MIN_CELL_N,
    ROUNDTRIP_COST,
    cluster_boot_ci_low,
    production_aligned,
    win_loss_stats,
)

# ---- 预注册常量 ----
HORIZONS = tuple(range(2, 16))  # t2..t15 (FORWARD_SESSIONS=15 上限)
PRIMARY_K = 10  # 现行合约锚
T10_CROSSCHECK_TOL = 1e-9

def horizon_curve_error(message: str) -> "SystemExit":
    print(f"btst_horizon_curve: {message}", file=sys.stderr)
    return SystemExit(2)


def _offset(event: pd.Series) -> int | None:
    """exit_session_t10 偏移 (build 层语义); NaN/None = 窗口内未成交。"""
    v = event["exit_session_t10"]
    if v is None or (isinstance(v, float) and v != v):
        return None
    return int(v)


def event_horizon_gross(
    event: pd.Series,
    by_day: dict[str, pd.DataFrame],
    cal: list[str],
) -> dict[int, float] | dict[str, Any]:
    """单事件 t2..t15 毛收益; 返回排除标记 dict 或 {k: gross}。

    顺延语义 = fixed_open: T+k 起找窗口内下一可用开盘; 全窗无 bar 的 k
    缺席 (聚合层披露 unexited 计数)。
    """
    signal_session = str(event["signal_date"])
    offset = _offset(event)
    if offset is None:
        return {"excluded_exit_unfilled": True}
    sessions = sessions_for_window(signal_session, FORWARD_SESSIONS, cal)
    bars = extract_path_bars(by_day, sessions, str(event["ts_code"]))
    if not bars or bars[0]["open"] is None:
        return {"excluded_t1_bar_missing": True}
    entry = bars[0]["open"]
    expected_entry = float(event["signal_close"]) * (1 + float(event["gap_t1_open"]))
    if abs(entry / expected_entry - 1) > 1e-6:
        return {"excluded_entry_mismatch": True}
    corp = detect_corp_action(bars)
    if corp:
        return {"excluded_corp_action": corp}

    out: dict[int, float] = {}
    for k in HORIZONS:
        for j in range(k - 1, min(FORWARD_SESSIONS, len(bars))):
            if bars[j]["open"] is not None:
                out[k] = bars[j]["open"] / entry - 1
                break
    if PRIMARY_K in out:
        table_gross = event["gross_ret_t10"]
        if table_gross is None or (
            isinstance(table_gross, float) and table_gross != table_gross
        ):
            return {"excluded_t10_sentinel_mismatch": True}
        if abs(out[PRIMARY_K] - float(table_gross)) > T10_CROSSCHECK_TOL:
            return {"excluded_t10_sentinel_mismatch": True}
    return out


def aggregate_curve(
    per_event: list[dict[int, float]],
    days_by_event: list[dict[int, str]],
) -> list[dict[str, Any]]:
    """逐 k 聚合 (净收益口径); CI 仅在 n≥MIN_CELL_N 时计算。确定性。"""
    rows: list[dict[str, Any]] = []
    for k in HORIZONS:
        rets: list[float] = []
        days: list[str] = []
        for grid, day_grid in zip(per_event, days_by_event):
            if k in grid:
                rets.append(grid[k] - ROUNDTRIP_COST)
                days.append(day_grid[k])
        stats = win_loss_stats(rets)
        stats.update(
            {
                "k": k,
                "unexited": sum(1 for grid in per_event if k not in grid),
                "ci90_low": (
                    cluster_boot_ci_low(rets, days)
                    if len(rets) >= MIN_CELL_N
                    else None
                ),
            }
        )
        rows.append(stats)

    return rows


def analyze_universe(
    ev: pd.DataFrame,
    raw_dir: Path,
    cal: list[str],
) -> dict[str, Any]:
    """单宇宙端到端: 逐事件 t2..t15 → 全体/生产对齐聚合。"""
    work = ev[ev["fillable"] == True].copy()  # noqa: E712
    sessions_union = sorted(
        {
            s
            for _, e in work.iterrows()
            if _offset(e) is not None
            for s in sessions_for_window(str(e["signal_date"]), FORWARD_SESSIONS, cal)
        }
    )
    by_day = load_daily_bars(raw_dir, sessions_union)
    per_event: list[dict[int, float]] = []
    days_by_event: list[dict[int, str]] = []
    exclusions: dict[str, int] = {}
    for _, event in work.iterrows():
        out = event_horizon_gross(event, by_day, cal)
        if all(isinstance(key, str) for key in out):
            key = next(iter(out))
            exclusions[key] = exclusions.get(key, 0) + 1
            continue
        per_event.append(out)  # type: ignore[arg-type]
        days_by_event.append({k: str(event["signal_date"]) for k in out})

    def _agg(indices: list[int]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "n_events": len(indices),
            "exclusions": dict(exclusions),
            "curve": aggregate_curve(
                [per_event[i] for i in indices],
                [days_by_event[i] for i in indices],
            ),
        }
        return payload

    all_idx = list(range(len(per_event)))
    payload: dict[str, Any] = {"all_candidates": _agg(all_idx)}
    mask = aligned_mask(work)
    if mask is not None:
        aligned_idx = [i for i, keep in zip(all_idx, mask) if keep]
        payload["production_aligned"] = _agg(aligned_idx)
    else:
        payload["production_aligned"] = {
            "skipped": "production_filter_columns_missing"
        }
    return payload


def aligned_mask(ev: pd.DataFrame) -> "pd.Series | None":
    """生产对齐布尔掩码 (与 winrate_payoff_decomposition 同式); 缺列返回 None。"""
    from scripts.review_btst_prior_court import PRODUCTION_EXCLUDE_COLS

    required = ["fillable", "gate_blocked", "price_ge_3", *PRODUCTION_EXCLUDE_COLS]
    if any(c not in ev.columns for c in required):
        return None
    universe = production_aligned(ev)
    return ev.index.isin(universe.index)


# ---------------------------------------------------------------------------
# 渲染 + CLI
# ---------------------------------------------------------------------------


def _fmt_pct(v: object) -> str:
    return "—" if v is None else f"{float(v) * 100:+.2f}%"


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# BTST 持有期全曲线 (t2..t15, 净收益扣往返 0.65%)",
        "",
        "纯诊断 (宪法 #2); 顺延语义 = court fixed_open; corp-action 事件排除; "
        "t10 与事件表逐事件交叉验证。",
        "",
    ]
    for universe, block in payload.items():
        for scope in ("all_candidates", "production_aligned"):
            agg = block.get(scope)
            if agg is None:
                continue
            lines.append(f"## {universe} / {scope}")
            if "skipped" in agg:
                lines.append("")
                lines.append(f"skipped: {agg['skipped']}")
                lines.append("")
                continue
            lines[-1] += f" (n={agg['n_events']})"
            lines.append("")
            if not agg["curve"]:
                lines.append("(无可用事件)")
                lines.append("")
                continue
            lines.append("| k | n | unexited | 胜率 | avg_win | avg_loss | payoff | E | CI90 下界 | ΔE vs t10 |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|")
            e10 = next(
                (r["expectancy"] for r in agg["curve"] if r["k"] == PRIMARY_K),
                None,
            )
            for r in agg["curve"]:
                delta = (
                    r["expectancy"] - e10
                    if (r["expectancy"] is not None and e10 is not None)
                    else None
                )
                payoff = (
                    "—" if r["payoff"] is None else f"{r['payoff']:.2f}"
                )
                lines.append(
                    f"| t{r['k']} | {r['n']} | {r['unexited']} "
                    f"| {_fmt_pct(r['winrate'])} | {_fmt_pct(r['avg_win'])} "
                    f"| {_fmt_pct(r['avg_loss'])} | {payoff} "
                    f"| {_fmt_pct(r['expectancy'])} | {_fmt_pct(r['ci90_low'])} "
                    f"| {_fmt_pct(delta)} |"
                )
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTST 持有期全曲线 (纯诊断)")
    parser.add_argument("--event-table", type=Path, default=EVENT_TABLE)
    parser.add_argument("--event-table-early", type=Path, default=EVENT_TABLE_EARLY)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DAILY_DIR)
    parser.add_argument("--raw-dir-early", type=Path, default=EARLY_DAILY_DIR)
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
            print(f"btst_horizon_curve: 跳过 {name} (事件表缺失: {table})")
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
