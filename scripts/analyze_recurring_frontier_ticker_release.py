from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_score_replay_utils import compute_replayed_score as _compute_replayed_score, resolve_default_thresholds as _resolve_default_thresholds
from scripts.analyze_short_trade_boundary_score_failures import analyze_short_trade_boundary_score_failures


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _round(value: float) -> float:
    return round(float(value), 4)


def _evaluate_after_snapshot(
    row: dict[str, Any],
    *,
    near_miss_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any]:
    thresholds = _resolve_default_thresholds(row)
    select_threshold = float(dict(row.get("thresholds") or {}).get("select_threshold") or 0.58)
    replayed_score = _compute_replayed_score(
        row=row,
        stale_weight=stale_weight,
        overhead_weight=thresholds["overhead_score_penalty_weight"],
        extension_weight=extension_weight,
        avoid_weight=thresholds["layer_c_avoid_penalty"],
    )
    if replayed_score >= select_threshold:
        decision = "selected"
    elif replayed_score >= near_miss_threshold:
        decision = "near_miss"
    else:
        decision = "rejected"
    return {
        "decision": decision,
        "score_target": _round(replayed_score),
        "near_miss_threshold": _round(near_miss_threshold),
        "stale_weight": _round(stale_weight),
        "extension_weight": _round(extension_weight),
    }


def render_recurring_frontier_ticker_release_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Frontier Ticker Release Review")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- recurring_frontier_report: {analysis['recurring_frontier_report']}")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- target_case_count: {analysis['target_case_count']}")
    lines.append(f"- promoted_target_case_count: {analysis['promoted_target_case_count']}")
    lines.append(f"- changed_non_target_case_count: {analysis['changed_non_target_case_count']}")
    lines.append("")
    lines.append("## Changed Cases")
    for row in analysis["changed_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, before_score={row['before_score_target']}, after_score={row['after_score_target']}, near_miss_threshold={row['near_miss_threshold']}, stale_weight={row['stale_weight']}, extension_weight={row['extension_weight']}"
        )
    if not analysis["changed_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_recurring_frontier_ticker_release(
    report_dir: str | Path,
    *,
    recurring_frontier_report: str | Path,
    ticker: str,
) -> dict[str, Any]:
    base_analysis = analyze_short_trade_boundary_score_failures(report_dir)
    recurring_analysis = _load_json(recurring_frontier_report)
    normalized_ticker = str(ticker).strip()

    target_row = None
    for row in list(recurring_analysis.get("priority_queue") or []):
        if str(row.get("ticker") or "") == normalized_ticker:
            target_row = row
            break
    if target_row is None:
        raise ValueError(f"Ticker not found in recurring frontier report: {normalized_ticker}")

    case_plan = {
        (str(case.get("trade_date") or ""), normalized_ticker): {
            "near_miss_threshold": float(case.get("near_miss_threshold") or 0.46),
            "stale_weight": float(case.get("stale_weight") or 0.12),
            "extension_weight": float(case.get("extension_weight") or 0.08),
            "adjustment_cost": float(case.get("adjustment_cost") or 0.0),
        }
        for case in list(target_row.get("cases") or [])
    }

    before_decision_counts: Counter[str] = Counter()
    after_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    changed_cases: list[dict[str, Any]] = []
    matched_targets: set[tuple[str, str]] = set()

    for row in list(base_analysis.get("rows") or []):
        case_key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        before_decision = "rejected"
        after_snapshot = {"decision": before_decision, "score_target": row.get("score_target")}
        if case_key in case_plan:
            plan = case_plan[case_key]
            after_snapshot = _evaluate_after_snapshot(
                row,
                near_miss_threshold=float(plan["near_miss_threshold"]),
                stale_weight=float(plan["stale_weight"]),
                extension_weight=float(plan["extension_weight"]),
            )
            matched_targets.add(case_key)

        after_decision = str(after_snapshot.get("decision") or "rejected")
        before_decision_counts[before_decision] += 1
        after_decision_counts[after_decision] += 1
        transition_counts[f"{before_decision}->{after_decision}"] += 1

        if case_key in case_plan:
            changed_cases.append(
                {
                    "trade_date": row["trade_date"],
                    "ticker": row["ticker"],
                    "before_decision": before_decision,
                    "after_decision": after_decision,
                    "before_score_target": row.get("score_target"),
                    "after_score_target": after_snapshot.get("score_target"),
                    "near_miss_threshold": after_snapshot.get("near_miss_threshold"),
                    "stale_weight": after_snapshot.get("stale_weight"),
                    "extension_weight": after_snapshot.get("extension_weight"),
                    "adjustment_cost": _round(case_plan[case_key]["adjustment_cost"]),
                }
            )

    expected_targets = set(case_plan)
    unmatched_targets = sorted(f"{trade_date}:{ticker_name}" for trade_date, ticker_name in (expected_targets - matched_targets))
    if unmatched_targets:
        raise ValueError(f"Targets not found in rejected short_trade_boundary rows: {', '.join(unmatched_targets)}")

    promoted_target_case_count = sum(1 for row in changed_cases if row["after_decision"] in {"near_miss", "selected"})
    changed_non_target_case_count = 0

    if promoted_target_case_count == len(changed_cases) and changed_cases:
        recommendation = (
            f"{normalized_ticker} 的 recurring frontier release 已在 {promoted_target_case_count} 个样本上全部进入 "
            f"near_miss/selected，可作为该 ticker 的局部 frontier 实验基线。"
        )
    elif changed_cases:
        recommendation = f"{normalized_ticker} 的 recurring frontier release 只在部分样本上生效，当前更适合保留为条件性实验。"
    else:
        recommendation = f"{normalized_ticker} 当前没有可执行的 recurring frontier release 样本。"

    return {
        "report_dir": base_analysis["report_dir"],
        "recurring_frontier_report": str(Path(recurring_frontier_report).expanduser().resolve()),
        "ticker": normalized_ticker,
        "target_case_count": len(changed_cases),
        "promoted_target_case_count": promoted_target_case_count,
        "changed_non_target_case_count": changed_non_target_case_count,
        "before_decision_counts": dict(before_decision_counts.most_common()),
        "after_decision_counts": dict(after_decision_counts.most_common()),
        "decision_transition_counts": dict(transition_counts.most_common()),
        "changed_cases": changed_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply recurring frontier rescue rows to all occurrences of a ticker.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--recurring-frontier-report", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_recurring_frontier_ticker_release(
        args.report_dir,
        recurring_frontier_report=args.recurring_frontier_report,
        ticker=args.ticker,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_recurring_frontier_ticker_release_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()