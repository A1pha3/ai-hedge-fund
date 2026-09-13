"""入场限价执行语义反事实决策包 CLI (R210 Op1) — R209 执行面审计的量化延伸.

R209 Op1 法证实锤: 官方 Trial 的入场限价 = 候选快照 entry_price (信号日
收盘), 且触及价成交 (min(open, limit)) — 4/4 准入行结构性混同。后果:
涨停突破候选 T+1 高开不回踩即静默 NO_FILL, 成交集被系统性逆向选择为
低开/回踩样本, 偏离宪法 #2 冻结合约「T+1 开盘买」的口径。修复属运行中
Trial 的执行语义行为变更 (宪法 #13 新证据世代), 须 owner gate。

本工具把该 gate 的决策输入一次性量化 (纯诊断, 零策略语义变更):

- S1 (现行 Trial 语义): 限价 = 信号收盘, 委托经
  ``resolve_open_execution`` 单一实现重演 (触及 → min(open, limit),
  未触及 → NO_FILL, 一字锁/缺 bar → UNKNOWN);
- S2 (冻结合约口径): T+1 开盘成交 — 即 court 证据自身口径
  (``gross_ret_t10`` 以 T+1 开盘为入场锚);
- 每准入期望差 ΔE = E[净收益 × S1 成交] − E[净收益 × S2 成交]
  (未成交 = 持币 0 收益), 配对聚类 bootstrap CI (按信号日整窗重采样,
  S1/S2 共用同一天采样);
- 高开/低开桶分解: 高开桶的 fill_rate 塌陷与被静默丢弃子集的 S2 期望
  (逆向选择的方向与幅度) 显形;
- 成交价效应: S1 成交价相对 T+1 开盘的相对偏离 (min(open, limit) 恒
  不劣于开盘, 高开回踩样本获得更优入场价)。

单一实现纪律 (零统计与口径 fork): production_aligned/net_returns/
win_loss_stats/cluster_boot_delta_ci/court_window_from_events 复用
``winrate_payoff_decomposition`` (R12/R17 收敛的单一提供方); 日线→
DailyBar 复用 ``v3_seed_market_bars.bars_from_court_csv`` (官方播种器
同源, half-up 围栏 + 严格校验); 判定表复用
``src...execution.lifecycle.resolve_open_execution``; 交易日历复用
``_btst_court_common.load_sessions``。

使用纪律:
- 纯披露 (宪法 #2): 本工具不进入任何计划/评分/仓位/执行决策路径;
  ΔE 读数 ≠ 语义修复决策 — 修复属 owner gate 且为宪法 #13 新证据世代。
- fail-open 家族 (R85/R115/R149/R181/R193/R194 同族): 单行 T+1 缺失
  → UNKNOWN 如实披露不猜测; 输入整体缺失/宇宙为空 → fail-closed
  SystemExit (typed), 绝不部分渲染。
- 输出确定性: 载荷无墙钟 (as-of = court 数据窗口末端), 同输入同字节;
  JSON ``allow_nan=False`` 硬拒非有限数。

用法::

    uv run python scripts/entry_limit_semantics_counterfactual.py
        [--event-table data/research/btst_court/event_tables/event_table_v1.csv.gz]
        [--raw-dir data/research/btst_court/raw/daily]
        [--out-dir data/reports] [--print]
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._btst_court_common import load_sessions  # noqa: E402
from scripts.v3_seed_market_bars import (  # noqa: E402
    CourtBarCsvError,
    bars_from_court_csv,
)
from scripts.winrate_payoff_decomposition import (  # noqa: E402
    MIN_CELL_N,
    ROUNDTRIP_COST,
    cluster_boot_delta_ci,
    court_window_from_events,
    net_returns,
    production_aligned,
    win_loss_stats,
)
from src.screening.offensive.gap_disclosure import GAP_HIGH_THRESHOLD  # noqa: E402
from src.screening.offensive.v3.execution.lifecycle import (  # noqa: E402
    ExecutionSide,
    resolve_open_execution,
)

PACK_SCHEMA = "entry_limit_semantics_counterfactual_v1"

# 反事实中命令恒准时点 (无墙钟依赖): resolve_open_execution 只比较
# command_at 与 send_deadline, 固定哨兵使 LATE_COMMAND 分支不可达。
_CMD_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
_SEND_DEADLINE = datetime(2000, 1, 2, tzinfo=timezone.utc)

DISCLAIMER = (
    "ΔE 读数 ≠ 语义修复决策: 入场限价语义修复属运行中 Trial 的执行语义"
    "行为变更 (宪法 #13 新证据世代), 须 owner gate; 纯披露不改变计划与"
    "执行决策 (宪法 #2)。"
)


def next_session_after(sessions: list[str], signal_date: str) -> str | None:
    """日历升序会话表中 signal_date 之后的第一个会话 (无则 None)。"""
    idx = bisect.bisect_right(sessions, str(signal_date))
    return sessions[idx] if idx < len(sessions) else None


def load_universe(event_table: Path | str) -> "pd.DataFrame":
    """court 事件表 → 生产对齐宇宙 (production_aligned 单一实现)。"""
    path = Path(event_table)
    if not path.is_file():
        raise SystemExit(f"court 事件表缺失: {path}")
    ev = pd.read_csv(path)
    return production_aligned(ev)


def _limit_cents(signal_close: float) -> int:
    # A 股价格两位小数, signal_close*100 在浮点误差内为整值; round 吸收
    # 误差 (银行家 .5 边界对 2 位小数价格不可达)。
    return int(round(float(signal_close) * 100))


def _session_date(yyyymmdd: str) -> date:
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))


def build_rows(
    universe: "pd.DataFrame", *, raw_dir: Path | str, sessions: list[str]
) -> list[dict[str, Any]]:
    """生产对齐宇宙 × T+1 日线快照 → 每行 S1/S2 反事实判定。

    T+1 快照文件缺失或行缺失 → UNKNOWN 如实披露 (fail-open 单行);
    快照文件存在但畸形 → CourtBarCsvError 向上传播 (fail-closed, 由
    main 转 typed 退出) — 半个世界的坏字节比一个 disclosed UNKNOWN 严重。
    """
    raw_dir = Path(raw_dir)
    bar_cache: dict[str, dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []
    for rec in universe.itertuples(index=False):
        ts_code = str(rec.ts_code)
        signal_date = str(rec.signal_date)
        gross_s2 = float(rec.gross_ret_t10) if pd.notna(rec.gross_ret_t10) else None
        exit_open = (
            float(rec.exit_open_t10) if pd.notna(rec.exit_open_t10) else None
        )
        s2_net = net_returns([gross_s2])[0]
        row: dict[str, Any] = {
            "ts_code": ts_code,
            "symbol": str(rec.symbol),
            "signal_date": signal_date,
            "gap_t1_open": (
                float(rec.gap_t1_open) if pd.notna(rec.gap_t1_open) else None
            ),
            "limit_cents": _limit_cents(rec.signal_close),
            "s2_net": s2_net,
            "s1_verdict": "UNKNOWN",
            "s1_reason": "unset",
            "s1_fill_cents": None,
            "s1_open_cents": None,
            "s1_net": None,
        }
        t1 = next_session_after(sessions, signal_date)
        if t1 is None:
            row["s1_reason"] = "missing_t1_session"
            rows.append(row)
            continue
        if t1 not in bar_cache:
            path = raw_dir / f"daily_{t1}.csv"
            bar_cache[t1] = (
                bars_from_court_csv(path, session=_session_date(t1))
                if path.is_file()
                else None
            )
        bars = bar_cache[t1]
        if bars is None:
            row["s1_reason"] = "missing_t1_bar"
            rows.append(row)
            continue
        bar = bars.get(ts_code)
        resolution = resolve_open_execution(
            side=ExecutionSide.ENTRY,
            limit_price_cents=row["limit_cents"],
            bar=bar,
            command_at=_CMD_AT,
            send_deadline=_SEND_DEADLINE,
        )
        row["s1_verdict"] = resolution.verdict.value
        row["s1_reason"] = resolution.reason
        if resolution.verdict.value == "FILLED":
            assert resolution.fill_price_cents is not None
            assert bar is not None
            row["s1_fill_cents"] = resolution.fill_price_cents
            row["s1_open_cents"] = bar.open_cents
            if exit_open is not None:
                row["s1_net"] = (
                    (exit_open / (resolution.fill_price_cents / 100) - 1)
                    - ROUNDTRIP_COST
                )
        rows.append(row)
    return rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def bucket_split(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """高开/低开桶分解 (阈值 = gap_disclosure.GAP_HIGH_THRESHOLD 单一实现)。"""
    labels = (
        ("gap_high", lambda gap: gap >= GAP_HIGH_THRESHOLD),
        ("gap_low", lambda gap: gap < GAP_HIGH_THRESHOLD),
    )
    out: list[dict[str, Any]] = []
    for label, predicate in labels:
        members = [
            r for r in rows
            if r["gap_t1_open"] is not None and predicate(r["gap_t1_open"])
        ]
        filled = [r for r in members if r["s1_verdict"] == "FILLED"]
        no_fill = [r for r in members if r["s1_verdict"] == "NO_FILL"]
        unknown = [r for r in members if r["s1_verdict"] == "UNKNOWN"]
        s2 = [r["s2_net"] for r in members if r["s2_net"] is not None]
        filled_nets = [r["s1_net"] for r in filled if r["s1_net"] is not None]
        unfilled_s2 = [r["s2_net"] for r in no_fill if r["s2_net"] is not None]
        s1_contrib = [
            r["s1_net"] if r["s1_net"] is not None else 0.0
            for r in members
            if r["s2_net"] is not None
        ]
        s2_days = [r["signal_date"] for r in members if r["s2_net"] is not None]
        out.append({
            "label": label,
            "gap_threshold": GAP_HIGH_THRESHOLD,
            "admitted": len(members),
            "filled": len(filled),
            "no_fill": len(no_fill),
            "unknown": len(unknown),
            "fill_rate": len(filled) / len(members) if members else None,
            "s2_expectancy": _mean(s2),
            "s1_per_admitted_expectancy": (
                _mean(s1_contrib) - _mean(s2)
                if s1_contrib and s2
                else None
            ),
            "filled_stats": win_loss_stats(filled_nets, s2_days[: len(filled_nets)])
            if filled_nets
            else win_loss_stats([]),
            "unfilled_s2_expectancy": _mean(unfilled_s2),
        })
    return out


def assemble_report(
    rows: list[dict[str, Any]], *, window: dict[str, str | None]
) -> dict[str, Any]:
    """行级反事实 → 决策包聚合 (无墙钟, 同输入同字节)。"""
    admitted = len(rows)
    filled = [r for r in rows if r["s1_verdict"] == "FILLED"]
    no_fill = [r for r in rows if r["s1_verdict"] == "NO_FILL"]
    unknown = [r for r in rows if r["s1_verdict"] == "UNKNOWN"]
    missing_exit = [r for r in rows if r["s2_net"] is None]
    if admitted == 0 or not admitted - len(missing_exit):
        raise SystemExit(
            f"生产对齐宇宙为空或无 T+10 收益: admitted={admitted}"
        )

    paired = [r for r in rows if r["s2_net"] is not None]
    s1_contrib = [
        r["s1_net"] if r["s1_net"] is not None else 0.0 for r in paired
    ]
    s2_list = [r["s2_net"] for r in paired]
    days = [r["signal_date"] for r in paired]
    s1_per_admitted = _mean(s1_contrib)
    s2_per_admitted = _mean(s2_list)

    delta_payload: dict[str, Any] = {
        "value": None,
        "cluster_ci": None,
        "reason": None,
    }
    if s1_per_admitted is not None and s2_per_admitted is not None:
        delta_payload["value"] = s1_per_admitted - s2_per_admitted
    if len(s1_contrib) < MIN_CELL_N:
        delta_payload["reason"] = f"n<{MIN_CELL_N}"
    elif delta_payload["value"] is None:
        delta_payload["reason"] = "expectancy_undefined"
    else:
        try:
            delta_payload["cluster_ci"] = cluster_boot_delta_ci(
                s1_contrib, days, s2_list, days
            )
        except ValueError as exc:
            delta_payload["reason"] = str(exc)

    filled_rets = [r["s1_net"] for r in filled if r["s1_net"] is not None]
    filled_days = [r["signal_date"] for r in filled if r["s1_net"] is not None]
    unfilled_rets = [r["s2_net"] for r in no_fill if r["s2_net"] is not None]
    unfilled_days = [r["signal_date"] for r in no_fill if r["s2_net"] is not None]

    rel_moves = [
        r["s1_fill_cents"] / r["s1_open_cents"] - 1
        for r in filled
        if r["s1_fill_cents"] is not None and r["s1_open_cents"]
    ]

    return {
        "schema": PACK_SCHEMA,
        "window": window,
        "gap_high_threshold": GAP_HIGH_THRESHOLD,
        "roundtrip_cost": ROUNDTRIP_COST,
        "counts": {
            "admitted": admitted,
            "filled": len(filled),
            "no_fill": len(no_fill),
            "unknown": len(unknown),
            "missing_exit": len(missing_exit),
        },
        "fill_rate": len(filled) / admitted if admitted else None,
        "s1_per_admitted_expectancy": s1_per_admitted,
        "s2_per_admitted_expectancy": s2_per_admitted,
        "delta_per_admitted": delta_payload,
        "s1_filled": win_loss_stats(filled_rets, filled_days),
        "s1_unfilled_would_be": win_loss_stats(unfilled_rets, unfilled_days),
        "price_effect": {
            "n": len(rel_moves),
            "mean_rel_vs_open": _mean(rel_moves),
            "n_better_than_open": sum(1 for v in rel_moves if v < 0),
        },
        "buckets": bucket_split(rows),
        "unknown_rows": [
            {"ts_code": r["ts_code"], "signal_date": r["signal_date"],
             "reason": r["s1_reason"]}
            for r in unknown[:50]
        ],
        "disclaimer": DISCLAIMER,
    }


def _fmt(value: object, pct: bool = True) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "n/a"
    return f"{value * 100:+.2f}%" if pct else f"{value:.4f}"


def render_md(report: dict[str, Any]) -> str:
    """决策包 → 确定性 markdown (同输入同字节)。"""
    counts = report["counts"]
    delta = report["delta_per_admitted"]
    lines = [
        "# 入场限价执行语义反事实 (S1 现行限价 vs S2 开盘合约口径)",
        "",
        f"- 数据窗口: {report['window'].get('start')} → "
        f"{report['window'].get('end')}",
        f"- 宇宙: 生产对齐 admitted {counts['admitted']} · S1 成交 "
        f"{counts['filled']} · NO_FILL {counts['no_fill']} · UNKNOWN "
        f"{counts['unknown']} · 缺 T+10 收益 {counts['missing_exit']}",
        f"- S1 成交率: {_fmt(report['fill_rate'])} "
        f"(限价==信号快照价, 触及才成交)",
        f"- 每准入期望差 ΔE (S1−S2): {_fmt(delta.get('value'))}",
    ]
    ci = delta.get("cluster_ci")
    if isinstance(ci, dict) and "ci_low" in ci:
        lines.append(
            f"  - 配对聚类 CI90: [{_fmt(ci['ci_low'])}, {_fmt(ci['ci_high'])}]"
            " (按信号日整窗重采样, S1/S2 共用同一天采样)"
        )
    else:
        reason = delta.get("reason") or "不可判"
        lines.append(f"  - CI 不可判: {reason}")
    filled = report["s1_filled"]
    unfilled = report["s1_unfilled_would_be"]
    lines += [
        f"- S1 成交集 (n={filled['n']}): 期望 {_fmt(filled['expectancy'])}"
        f" · 胜率 {_fmt(filled['winrate'])}",
        f"- S1 未成交集若按开盘买入 (n={unfilled['n']}): 期望 "
        f"{_fmt(unfilled['expectancy'])} — 被静默丢弃子集的方向与幅度",
        f"- 成交价效应: n={report['price_effect']['n']} · 相对开盘均值 "
        f"{_fmt(report['price_effect']['mean_rel_vs_open'])} · 优于开盘 "
        f"{report['price_effect']['n_better_than_open']} 行",
        "- 高开/低开桶 (阈值 {:.0%}):".format(report["gap_high_threshold"]),
    ]
    for bucket in report["buckets"]:
        lines.append(
            f"  - {bucket['label']}: admitted {bucket['admitted']} · 成交率 "
            f"{_fmt(bucket['fill_rate'])} · 成交集期望 "
            f"{_fmt(bucket['filled_stats'].get('expectancy'))} · 未成交若开盘买 "
            f"{_fmt(bucket['unfilled_s2_expectancy'])} · ΔE 每准入 "
            f"{_fmt(bucket['s1_per_admitted_expectancy'])}"
        )
    if report["unknown_rows"]:
        lines.append(
            f"- UNKNOWN 披露: {len(report['unknown_rows'])} 行 "
            f"(首 {min(len(report['unknown_rows']), 10)} 行: "
            + ", ".join(
                f"{r['ts_code']}@{r['signal_date']}:{r['reason']}"
                for r in report["unknown_rows"][:10]
            )
            + ")"
        )
    lines += ["", f"> {report['disclaimer']}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="入场限价执行语义反事实决策包 (纯诊断, 宪法 #2)"
    )
    parser.add_argument(
        "--event-table", type=Path,
        default=Path("data/research/btst_court/event_tables/event_table_v1.csv.gz"),
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/research/btst_court/raw/daily")
    )
    parser.add_argument("--out-dir", type=Path, default=Path("data/reports"))
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)

    if not args.raw_dir.is_dir():
        raise SystemExit(f"T+1 日线快照目录缺失: {args.raw_dir}")
    if not args.event_table.is_file():
        raise SystemExit(f"court 事件表缺失: {args.event_table}")
    ev = pd.read_csv(args.event_table)
    window = court_window_from_events(ev)
    if not window.get("start") or not window.get("end"):
        raise SystemExit("court 事件表为空 (无 signal_date)")
    sessions = load_sessions(str(window["start"]), "29991231")
    universe = load_universe(args.event_table)
    rows = build_rows(universe, raw_dir=args.raw_dir, sessions=sessions)
    report = assemble_report(rows, window=window)
    payload = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False
    ) + "\n"
    markdown = render_md(report)

    stem = f"entry_limit_semantics_counterfactual_{window['end']}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{stem}.json").write_text(payload, encoding="utf-8")
    (args.out_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
    if args.print:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CourtBarCsvError as exc:
        print(
            json.dumps(
                {"error": "bar_csv_invalid", "reason": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
