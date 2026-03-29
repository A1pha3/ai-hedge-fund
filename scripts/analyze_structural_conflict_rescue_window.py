from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_structural_conflict_rescue import analyze_structural_conflict_rescue


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_trade_dates(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _parse_float_grid(raw: str | None, *, default: list[float]) -> list[float]:
    if raw is None or not str(raw).strip():
        return list(default)
    values: list[float] = []
    for token in str(raw).split(","):
        normalized = token.strip()
        if not normalized:
            continue
        values.append(float(normalized))
    return values or list(default)


def _iter_blocked_cases(report_dir: Path, *, trade_dates: set[str] | None = None):
    selection_root = report_dir / "selection_artifacts"
    active_trade_dates = {str(value) for value in (trade_dates or set()) if str(value).strip()}
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        if active_trade_dates and day_dir.name not in active_trade_dates:
            continue
        snapshot_path = day_dir / "selection_snapshot.json"
        if not snapshot_path.exists():
            continue
        snapshot = _load_json(snapshot_path)
        trade_date = str(snapshot.get("trade_date") or day_dir.name)
        selection_targets = dict(snapshot.get("selection_targets") or {})
        for ticker, evaluation in selection_targets.items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            blockers = [str(blocker) for blocker in list(short_trade.get("blockers") or []) if str(blocker or "").strip()]
            if "layer_c_bearish_conflict" not in blockers:
                continue
            yield {
                "trade_date": trade_date,
                "ticker": str(ticker),
                "candidate_source": str((evaluation or {}).get("candidate_source") or "unknown"),
                "stored_short_trade_decision": str(short_trade.get("decision") or ""),
                "baseline_score_target": round(float(short_trade.get("score_target") or 0.0), 4),
            }


def render_structural_conflict_rescue_window_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Structural Conflict Rescue Window Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_dates_filter: {analysis['trade_dates_filter']}")
    lines.append(f"- blocked_case_count: {analysis['blocked_case_count']}")
    lines.append(f"- near_miss_rescuable_count: {analysis['near_miss_rescuable_count']}")
    lines.append(f"- selected_rescuable_count: {analysis['selected_rescuable_count']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append("")
    lines.append("## Priority Queue")
    for row in analysis["priority_queue"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: baseline={row['baseline_score_target']}, minimal_near_miss_cost={row['minimal_near_miss_adjustment_cost']}, minimal_selected_cost={row['minimal_selected_adjustment_cost']}, candidate_source={row['candidate_source']}"
        )
    lines.append("")
    lines.append("## Unrescued Cases")
    for row in analysis["unrescued_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: baseline={row['baseline_score_target']}, candidate_source={row['candidate_source']}, reason=no_near_miss_row_within_grid"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_structural_conflict_rescue_window(
    report_dir: str | Path,
    *,
    trade_dates: set[str] | None = None,
    avoid_penalty_grid: list[float] | None = None,
    stale_score_penalty_grid: list[float] | None = None,
    extension_score_penalty_grid: list[float] | None = None,
    select_threshold_grid: list[float] | None = None,
    near_miss_threshold_grid: list[float] | None = None,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    active_trade_dates = {str(value) for value in (trade_dates or set()) if str(value).strip()}
    cases = list(_iter_blocked_cases(report_path, trade_dates=active_trade_dates))
    cases.sort(key=lambda row: (row["baseline_score_target"], row["trade_date"], row["ticker"]), reverse=True)

    case_rows: list[dict[str, Any]] = []
    candidate_source_counts: Counter[str] = Counter()
    for case in cases:
        candidate_source_counts[str(case["candidate_source"])] += 1
        rescue_analysis = analyze_structural_conflict_rescue(
            report_path,
            str(case["trade_date"]),
            str(case["ticker"]),
            avoid_penalty_grid=avoid_penalty_grid,
            stale_score_penalty_grid=stale_score_penalty_grid,
            extension_score_penalty_grid=extension_score_penalty_grid,
            select_threshold_grid=select_threshold_grid,
            near_miss_threshold_grid=near_miss_threshold_grid,
        )
        frontier = dict(rescue_analysis.get("penalty_threshold_frontier") or {})
        minimal_near_miss_row = dict(frontier.get("minimal_near_miss_row") or {})
        minimal_selected_row = dict(frontier.get("minimal_selected_row") or {})
        case_rows.append(
            {
                **case,
                "minimal_near_miss_row": minimal_near_miss_row,
                "minimal_selected_row": minimal_selected_row,
                "minimal_near_miss_adjustment_cost": minimal_near_miss_row.get("adjustment_cost"),
                "minimal_selected_adjustment_cost": minimal_selected_row.get("adjustment_cost"),
                "best_score_row": frontier.get("best_score_row"),
            }
        )

    near_miss_rescuable_rows = [row for row in case_rows if row.get("minimal_near_miss_row")]
    selected_rescuable_rows = [row for row in case_rows if row.get("minimal_selected_row")]
    priority_queue = sorted(
        near_miss_rescuable_rows,
        key=lambda row: (
            float(row.get("minimal_near_miss_adjustment_cost") or 999.0),
            -float(row.get("baseline_score_target") or 0.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
    )
    unrescued_cases = [row for row in case_rows if not row.get("minimal_near_miss_row")]

    if priority_queue:
        best_row = priority_queue[0]
        recommendation = (
            f"优先审 {best_row['trade_date']} / {best_row['ticker']}。它在当前搜索空间内的最小 near_miss adjustment_cost="
            f"{best_row['minimal_near_miss_adjustment_cost']}，baseline_score_target={best_row['baseline_score_target']}。"
        )
    elif case_rows:
        recommendation = "当前搜索空间内没有任何 blocked 样本能被释放到 near_miss，优先回到 candidate-entry 或 score construction 设计。"
    else:
        recommendation = "当前筛选范围内没有 layer_c_bearish_conflict blocked 样本。"

    return {
        "report_dir": str(report_path),
        "trade_dates_filter": sorted(active_trade_dates),
        "blocked_case_count": len(case_rows),
        "near_miss_rescuable_count": len(near_miss_rescuable_rows),
        "selected_rescuable_count": len(selected_rescuable_rows),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "priority_queue": priority_queue,
        "unrescued_cases": unrescued_cases,
        "case_rows": case_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the full layer_c_bearish_conflict blocked cluster and rank rescue candidates.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--trade-dates", default="", help="Optional comma-separated trade_date filter")
    parser.add_argument("--avoid-penalty-grid", default="")
    parser.add_argument("--stale-score-penalty-grid", default="0.12,0.10,0.08,0.06,0.04,0.02")
    parser.add_argument("--extension-score-penalty-grid", default="0.08,0.06,0.04,0.02,0.00")
    parser.add_argument("--select-threshold-grid", default="0.58,0.56,0.54,0.52,0.50,0.48")
    parser.add_argument("--near-miss-threshold-grid", default="0.46,0.44,0.42,0.40,0.38,0.36")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_structural_conflict_rescue_window(
        args.report_dir,
        trade_dates=_parse_trade_dates(args.trade_dates),
        avoid_penalty_grid=_parse_float_grid(args.avoid_penalty_grid, default=[0.12]),
        stale_score_penalty_grid=_parse_float_grid(args.stale_score_penalty_grid, default=[0.12, 0.10, 0.08, 0.06, 0.04, 0.02]),
        extension_score_penalty_grid=_parse_float_grid(args.extension_score_penalty_grid, default=[0.08, 0.06, 0.04, 0.02, 0.00]),
        select_threshold_grid=_parse_float_grid(args.select_threshold_grid, default=[0.58, 0.56, 0.54, 0.52, 0.50, 0.48]),
        near_miss_threshold_grid=_parse_float_grid(args.near_miss_threshold_grid, default=[0.46, 0.44, 0.42, 0.40, 0.38, 0.36]),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_structural_conflict_rescue_window_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()