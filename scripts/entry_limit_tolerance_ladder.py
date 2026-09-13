"""入场限价容忍度梯子反事实决策包 CLI (R211 Op1) — R210 Op1 的分级延伸.

R210 Op1 把入场限价语义作为二选一量化 (S1 限价==信号快照价 vs S2
开盘合约口径): ΔE +0.12% CI90[-0.62,+0.85] 跨零, 且高开桶成交率塌陷
(21.52%) 与桶内成交集负期望 (-9.73%) 显形逆向选择。单点读数不足以
支撑 owner gate 判断「限价语义留不留、留的话给多少容忍度」。本工具
把该 gate 升级为**分级决策面**: limit = signal_close × (1+t),
t ∈ TOLERANCES, 逐档经 ``resolve_open_execution`` 单一实现重演, 输出
每档 fill_rate / 每准入期望差 ΔE(t) 与配对聚类 CI / 高开低开桶分解
(成交率恢复与逆向选择吸收的边际交换逐档显形)。

单一实现纪律 (零统计与口径 fork): 行级反事实复用
``entry_limit_semantics_counterfactual.build_rows`` 参数化入口 (t=0 与
Op1 工具逐字节一致, 跨工具一致性有测试钉); 每档聚合整体复用 Op1
``assemble_report`` (期望/配对聚类 CI/桶分解/价格效应零 fork); 日线→
DailyBar 复用 ``v3_seed_market_bars.bars_from_court_csv``; 交易日历
复用 ``_btst_court_common.load_sessions``。

结构性事实 (成文, 不实现死代码): 梯子 t ≤ 5% 恒低于全板块 T+1 涨停
围栏 (主板 10% / 创业板科创板 20% / 北交所 30%, 与限价同锚
pre_close=signal_close), 涨停价封顶分支在本梯子定义域内不可达; 一字
涨停板经 resolve_open_execution 判定表 → UNKNOWN 如实披露 (各档一致)。

使用纪律:
- 纯披露 (宪法 #2): ΔE(t) 读数 ≠ 语义修复决策 — 入场限价语义变更属
  运行中 Trial 的执行语义行为变更 (宪法 #13 新证据世代), 须 owner gate。
- fail-open/fail-closed 家族与输出确定性纪律同 R210 Op1 (单行 T+1
  缺失 → UNKNOWN 披露; 输入整体缺失/宇宙为空 → typed SystemExit;
  载荷无墙钟, 同输入同字节, ``allow_nan=False``)。

用法::

    uv run python scripts/entry_limit_tolerance_ladder.py
        [--event-table data/research/btst_court/event_tables/event_table_v1.csv.gz]
        [--raw-dir data/research/btst_court/raw/daily]
        [--out-dir data/reports] [--print]
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

from scripts._btst_court_common import load_sessions  # noqa: E402
from scripts.entry_limit_semantics_counterfactual import (  # noqa: E402
    _fmt,
    assemble_report,
    build_rows,
    court_window_from_events,
    load_universe,
)
from scripts.v3_seed_market_bars import (  # noqa: E402
    CourtBarCsvError,
)

LADDER_SCHEMA = "entry_limit_tolerance_ladder_v1"

# 档位 (占信号收盘比例): 0 = 现行语义锚点; 0.5% 捕捉贴边回踩; 1–3%
# 覆盖常见高开带; 5% = gap_high 阈值 (GAP_HIGH_THRESHOLD) — 超过该档
# 后高开桶全体按开盘成交, 梯子相对 S2 的自由度耗尽。
TOLERANCES: tuple[float, ...] = (0.0, 0.005, 0.01, 0.02, 0.03, 0.05)

DISCLAIMER = (
    "ΔE(t) 读数 ≠ 语义修复决策: 入场限价语义 (含任何容忍度档位) 属运行中"
    " Trial 的执行语义行为变更 (宪法 #13 新证据世代), 须 owner gate; 纯披露"
    "不改变计划与执行决策 (宪法 #2)。"
)


def limit_cents_at(signal_close: float, tolerance: float) -> int:
    """信号收盘 × (1+t) → 分 (half-cent 吸收浮点误差, A 股最小变动 1 分)。"""
    return int(round(float(signal_close) * (1.0 + tolerance) * 100))


def build_ladder(
    universe: "pd.DataFrame",
    *,
    raw_dir: Path | str,
    sessions: list[str],
    tolerances: tuple[float, ...] = TOLERANCES,
) -> dict[float, list[dict[str, Any]]]:
    """逐档行级反事实 (每档独立 build_rows, 判定表单一实现)。"""
    rows_by_tolerance: dict[float, list[dict[str, Any]]] = {}
    for tolerance in tolerances:
        rows_by_tolerance[tolerance] = build_rows(
            universe,
            raw_dir=raw_dir,
            sessions=sessions,
            limit_cents_of=lambda close, _t=tolerance: limit_cents_at(close, _t),
        )
    return rows_by_tolerance


def assemble_ladder(
    rows_by_tolerance: dict[float, list[dict[str, Any]]],
    *,
    window: dict[str, str | None],
    tolerances: tuple[float, ...] = TOLERANCES,
) -> dict[str, Any]:
    """每档整体复用 Op1 决策包聚合 (期望/CI/桶分解零 fork), 无墙钟。"""
    rungs: list[dict[str, Any]] = []
    for tolerance in tolerances:
        report = assemble_report(rows_by_tolerance[tolerance], window=window)
        rungs.append({"tolerance": tolerance, "report": report})
    return {
        "schema": LADDER_SCHEMA,
        "window": window,
        "tolerances": list(tolerances),
        "rungs": rungs,
        "disclaimer": DISCLAIMER,
    }


def render_md(ladder: dict[str, Any]) -> str:
    """梯子 → 确定性 markdown 汇总表 (同输入同字节)。"""
    counts = ladder["rungs"][0]["report"]["counts"]
    lines = [
        "# 入场限价容忍度梯子反事实 (limit = 信号收盘 × (1+t))",
        "",
        f"- 数据窗口: {ladder['window'].get('start')} → "
        f"{ladder['window'].get('end')}",
        f"- 宇宙: 生产对齐 admitted {counts['admitted']} (各档同宇宙同判定面, "
        f"仅限价随档位变化)",
        "- 每档: 成交率 · 每准入期望差 ΔE(t)=S1(t)−S2 (配对聚类 CI90) · "
        "高开桶成交率与未成交子集若开盘买的期望 (逆向选择显形)",
        "",
        "| t | 成交率 | ΔE(t) | CI90 下界 | CI90 上界 | 高开桶成交率 |"
        " 高开未成交若开盘买 | 高开成交集期望 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rung in ladder["rungs"]:
        report = rung["report"]
        delta = report["delta_per_admitted"]
        ci = delta.get("cluster_ci")
        ci_low = _fmt(ci["ci_low"]) if isinstance(ci, dict) and "ci_low" in ci else "n/a"
        ci_high = _fmt(ci["ci_high"]) if isinstance(ci, dict) and "ci_high" in ci else "n/a"
        gap_high = next(
            b for b in report["buckets"] if b["label"] == "gap_high"
        )
        lines.append(
            f"| {rung['tolerance']:.1%} | {_fmt(report['fill_rate'])} "
            f"| {_fmt(delta.get('value'))} | {ci_low} | {ci_high} "
            f"| {_fmt(gap_high['fill_rate'])} "
            f"| {_fmt(gap_high['unfilled_s2_expectancy'])} "
            f"| {_fmt(gap_high['filled_stats'].get('expectancy'))} |"
        )
    lines += ["", f"> {ladder['disclaimer']}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="入场限价容忍度梯子反事实决策包 (纯诊断, 宪法 #2)"
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
    rows_by_tolerance = build_ladder(universe, raw_dir=args.raw_dir, sessions=sessions)
    ladder = assemble_ladder(rows_by_tolerance, window=window)
    payload = json.dumps(
        ladder, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False
    ) + "\n"
    markdown = render_md(ladder)

    stem = f"entry_limit_tolerance_ladder_{window['end']}"
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
