from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.analyze_short_trade_boundary_score_failures import analyze_short_trade_boundary_score_failures
from scripts.analyze_short_trade_boundary_score_failures_frontier import analyze_short_trade_boundary_score_failures_frontier


def render_short_trade_boundary_recurring_frontier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Short Trade Boundary Frontier Cases")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- recurring_case_count: {analysis['recurring_case_count']}")
    lines.append(f"- min_occurrences: {analysis['min_occurrences']}")
    lines.append("")
    lines.append("## Priority Queue")
    for row in analysis["priority_queue"]:
        lines.append(
            f"- {row['ticker']}: occurrences={row['occurrence_count']}, trade_dates={row['trade_dates']}, baseline_score_mean={row['baseline_score_mean']}, gap_to_near_miss_mean={row['gap_to_near_miss_mean']}, threshold_only_rescue_count={row['threshold_only_rescue_count']}, minimal_adjustment_cost={row['minimal_adjustment_cost']}, dominant_pattern={row['dominant_pattern']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_recurring_frontier_cases(report_dir: str | Path, *, min_occurrences: int = 2) -> dict[str, Any]:
    base_analysis = analyze_short_trade_boundary_score_failures(report_dir)
    frontier_analysis = analyze_short_trade_boundary_score_failures_frontier(report_dir)

    row_by_case = {(row["trade_date"], row["ticker"]): row for row in list(base_analysis.get("rows") or [])}
    frontier_by_case = {(row["trade_date"], row["ticker"]): row for row in list(frontier_analysis.get("minimal_near_miss_rows") or [])}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (trade_date, ticker), row in row_by_case.items():
        frontier_row = frontier_by_case.get((trade_date, ticker))
        if frontier_row is None:
            continue
        grouped[ticker].append({"base": row, "frontier": frontier_row})

    priority_queue: list[dict[str, Any]] = []
    for ticker, cases in grouped.items():
        if len(cases) < min_occurrences:
            continue
        trade_dates = sorted(case["base"]["trade_date"] for case in cases)
        baseline_scores = [float(case["base"]["score_target"]) for case in cases]
        gaps = [float(case["base"]["gap_to_near_miss"]) for case in cases]
        threshold_only_rescue_count = sum(
            1
            for case in cases
            if float(case["frontier"]["stale_weight"]) == 0.12 and float(case["frontier"]["extension_weight"]) == 0.08
        )
        dominant_pattern = {
            "near_miss_thresholds": sorted({float(case["frontier"]["near_miss_threshold"]) for case in cases}),
            "stale_weights": sorted({float(case["frontier"]["stale_weight"]) for case in cases}),
            "extension_weights": sorted({float(case["frontier"]["extension_weight"]) for case in cases}),
        }
        priority_queue.append(
            {
                "ticker": ticker,
                "occurrence_count": len(cases),
                "trade_dates": trade_dates,
                "baseline_score_mean": round(mean(baseline_scores), 4),
                "gap_to_near_miss_mean": round(mean(gaps), 4),
                "minimal_adjustment_cost": round(min(float(case["frontier"]["adjustment_cost"]) for case in cases), 4),
                "max_adjustment_cost": round(max(float(case["frontier"]["adjustment_cost"]) for case in cases), 4),
                "threshold_only_rescue_count": threshold_only_rescue_count,
                "dominant_pattern": dominant_pattern,
                "cases": [
                    {
                        "trade_date": case["base"]["trade_date"],
                        "baseline_score_target": case["base"]["score_target"],
                        "gap_to_near_miss": case["base"]["gap_to_near_miss"],
                        "near_miss_threshold": case["frontier"]["near_miss_threshold"],
                        "stale_weight": case["frontier"]["stale_weight"],
                        "extension_weight": case["frontier"]["extension_weight"],
                        "adjustment_cost": case["frontier"]["adjustment_cost"],
                    }
                    for case in sorted(cases, key=lambda item: item["base"]["trade_date"])
                ],
            }
        )

    priority_queue.sort(
        key=lambda row: (
            -int(row["occurrence_count"]),
            float(row["minimal_adjustment_cost"]),
            float(row["gap_to_near_miss_mean"]),
            row["ticker"],
        )
    )

    if priority_queue:
        lead = priority_queue[0]
        recommendation = (
            f"当前重复出现的 score frontier 样本应按 recurring ticker 处理，而不是逐天零散讨论。"
            f" 优先从 {lead['ticker']} 开始，因为它在 {lead['occurrence_count']} 个 trade_date 上重复出现，"
            f"且最小 rescue cost 只有 {lead['minimal_adjustment_cost']}。"
        )
    else:
        recommendation = "当前窗口里没有满足最小重复次数的 recurring short_trade_boundary frontier 样本。"

    return {
        "report_dir": base_analysis["report_dir"],
        "min_occurrences": int(min_occurrences),
        "recurring_case_count": len(priority_queue),
        "priority_queue": priority_queue,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize recurring rejected short_trade_boundary frontier cases by ticker.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--min-occurrences", type=int, default=2)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_recurring_frontier_cases(args.report_dir, min_occurrences=int(args.min_occurrences))
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_recurring_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()