from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_boundary_score_failures import analyze_short_trade_boundary_score_failures
from scripts.analyze_short_trade_boundary_score_failures_frontier import _compute_replayed_score, _resolve_default_thresholds


def _parse_targets(raw: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for token in str(raw or "").split(","):
        normalized = token.strip()
        if not normalized:
            continue
        if ":" not in normalized:
            raise ValueError(f"Target must use trade_date:ticker format, got: {normalized}")
        trade_date, ticker = normalized.split(":", 1)
        targets.add((trade_date.strip(), ticker.strip()))
    return targets


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


def render_targeted_short_trade_boundary_release_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Targeted Short Trade Boundary Release Review")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- targets: {analysis['targets']}")
    lines.append(f"- total_case_count: {analysis['total_case_count']}")
    lines.append(f"- changed_case_count: {analysis['changed_case_count']}")
    lines.append(f"- changed_non_target_case_count: {analysis['changed_non_target_case_count']}")
    lines.append("")
    lines.append("## Transitions")
    lines.append(f"- before: {analysis['before_decision_counts']}")
    lines.append(f"- after: {analysis['after_decision_counts']}")
    lines.append(f"- transitions: {analysis['decision_transition_counts']}")
    lines.append("")
    lines.append("## Changed Cases")
    for row in analysis["changed_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, before_score={row['before_score_target']}, after_score={row['after_score_target']}, target_case={row['is_target_case']}"
        )
    if not analysis["changed_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_targeted_short_trade_boundary_release(
    report_dir: str | Path,
    *,
    targets: set[tuple[str, str]],
    near_miss_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any]:
    base_analysis = analyze_short_trade_boundary_score_failures(report_dir)
    rows = list(base_analysis.get("rows") or [])

    before_decision_counts: Counter[str] = Counter()
    after_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    changed_cases: list[dict[str, Any]] = []
    matched_targets: set[tuple[str, str]] = set()

    for row in rows:
        case_key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        is_target_case = case_key in targets
        before_decision = "rejected"
        after_snapshot = {"decision": before_decision, "score_target": row.get("score_target")}
        if is_target_case:
            after_snapshot = _evaluate_after_snapshot(
                row,
                near_miss_threshold=near_miss_threshold,
                stale_weight=stale_weight,
                extension_weight=extension_weight,
            )
            matched_targets.add(case_key)

        after_decision = str(after_snapshot.get("decision") or "rejected")
        before_decision_counts[before_decision] += 1
        after_decision_counts[after_decision] += 1
        transition_counts[f"{before_decision}->{after_decision}"] += 1

        if before_decision != after_decision or row.get("score_target") != after_snapshot.get("score_target"):
            changed_cases.append(
                {
                    "trade_date": row["trade_date"],
                    "ticker": row["ticker"],
                    "is_target_case": is_target_case,
                    "before_decision": before_decision,
                    "after_decision": after_decision,
                    "before_score_target": row.get("score_target"),
                    "after_score_target": after_snapshot.get("score_target"),
                    "near_miss_threshold": after_snapshot.get("near_miss_threshold"),
                    "stale_weight": after_snapshot.get("stale_weight"),
                    "extension_weight": after_snapshot.get("extension_weight"),
                }
            )

    unmatched_targets = sorted(f"{trade_date}:{ticker}" for trade_date, ticker in (targets - matched_targets))
    if unmatched_targets:
        raise ValueError(f"Targets not found in rejected short_trade_boundary rows: {', '.join(unmatched_targets)}")

    changed_non_target_case_count = sum(1 for row in changed_cases if not row["is_target_case"])
    target_changed_cases = [row for row in changed_cases if row["is_target_case"]]

    if target_changed_cases and changed_non_target_case_count == 0:
        promoted_rows = [row for row in target_changed_cases if row["after_decision"] in {"near_miss", "selected"}]
        if promoted_rows:
            first = promoted_rows[0]
            recommendation = (
                f"当前定向 release 只改变目标样本。{first['trade_date']} / {first['ticker']} 从 rejected -> {first['after_decision']}，"
                f"可作为低污染的 case-based short_trade_boundary rescue 实验。"
            )
        else:
            recommendation = "目标样本分数变化了，但还没有进入 near_miss/selected，当前 release 参数不够强。"
    elif changed_non_target_case_count > 0:
        recommendation = "出现了非目标样本变化，当前实验不再是严格的 case-based release。"
    else:
        recommendation = "目标样本没有发生任何变化，当前定向 release 不值得继续推进。"

    return {
        "report_dir": base_analysis["report_dir"],
        "targets": sorted(f"{trade_date}:{ticker}" for trade_date, ticker in targets),
        "near_miss_threshold": _round(near_miss_threshold),
        "stale_weight": _round(stale_weight),
        "extension_weight": _round(extension_weight),
        "total_case_count": len(rows),
        "changed_case_count": len(changed_cases),
        "changed_non_target_case_count": changed_non_target_case_count,
        "before_decision_counts": dict(before_decision_counts.most_common()),
        "after_decision_counts": dict(after_decision_counts.most_common()),
        "decision_transition_counts": dict(transition_counts.most_common()),
        "changed_cases": changed_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a case-based release experiment on rejected short_trade_boundary candidates.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--targets", required=True, help="Comma-separated trade_date:ticker targets")
    parser.add_argument("--near-miss-threshold", type=float, required=True)
    parser.add_argument("--stale-weight", type=float, required=True)
    parser.add_argument("--extension-weight", type=float, required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_targeted_short_trade_boundary_release(
        args.report_dir,
        targets=_parse_targets(args.targets),
        near_miss_threshold=float(args.near_miss_threshold),
        stale_weight=float(args.stale_weight),
        extension_weight=float(args.extension_weight),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_targeted_short_trade_boundary_release_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()