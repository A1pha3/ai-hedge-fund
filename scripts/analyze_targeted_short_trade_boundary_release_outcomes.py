from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def render_targeted_short_trade_boundary_release_outcomes_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Targeted Short Trade Boundary Release Outcome Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- release_report: {analysis['release_report']}")
    lines.append(f"- outcome_report: {analysis['outcome_report']}")
    lines.append(f"- target_case_count: {analysis['target_case_count']}")
    lines.append(f"- promoted_target_case_count: {analysis['promoted_target_case_count']}")
    lines.append("")
    lines.append("## Target Cases")
    for row in analysis["target_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, before_score={row['before_score_target']}, after_score={row['after_score_target']}, next_open_return={row['next_open_return']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, release_verdict={row['release_verdict']}"
        )
    if not analysis["target_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_targeted_short_trade_boundary_release_outcomes(
    release_report: str | Path,
    outcome_report: str | Path,
) -> dict[str, Any]:
    release_analysis = _load_json(release_report)
    outcome_analysis = _load_json(outcome_report)

    targets = {token for token in list(release_analysis.get("targets") or [])}
    outcome_by_case = {
        f"{row.get('trade_date')}:{row.get('ticker')}": row
        for row in list(outcome_analysis.get("rows") or [])
    }

    target_cases: list[dict[str, Any]] = []
    promoted_target_case_count = 0
    positive_next_close_count = 0
    high_hit_count = 0
    next_high_hit_threshold = float(outcome_analysis.get("next_high_hit_threshold") or 0.02)

    for row in list(release_analysis.get("changed_cases") or []):
        case_key = f"{row.get('trade_date')}:{row.get('ticker')}"
        if case_key not in targets:
            continue
        outcome = dict(outcome_by_case.get(case_key) or {})
        next_high_return = outcome.get("next_high_return")
        next_close_return = outcome.get("next_close_return")
        promoted = str(row.get("after_decision") or "") in {"near_miss", "selected"}
        if promoted:
            promoted_target_case_count += 1
        if next_close_return is not None and float(next_close_return) > 0:
            positive_next_close_count += 1
        if next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
            high_hit_count += 1

        if promoted and next_close_return is not None and float(next_close_return) > 0:
            release_verdict = "promoted_with_positive_close"
        elif promoted and next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
            release_verdict = "promoted_with_intraday_upside"
        elif promoted:
            release_verdict = "promoted_but_outcome_mixed"
        else:
            release_verdict = "not_promoted"

        target_cases.append(
            {
                **row,
                "next_trade_date": outcome.get("next_trade_date"),
                "next_open_return": outcome.get("next_open_return"),
                "next_high_return": next_high_return,
                "next_close_return": next_close_return,
                "next_open_to_close_return": outcome.get("next_open_to_close_return"),
                "release_verdict": release_verdict,
            }
        )

    if target_cases and promoted_target_case_count == len(target_cases) and positive_next_close_count == len(target_cases):
        lead = target_cases[0]
        recommendation = (
            f"当前 targeted release 值得继续保留。{lead['trade_date']} / {lead['ticker']} 不仅被提升到 {lead['after_decision']}，"
            f"且 next_close_return={lead['next_close_return']}，说明 release 与真实次日表现方向一致。"
        )
    elif target_cases and promoted_target_case_count == len(target_cases) and high_hit_count == len(target_cases):
        recommendation = "当前 targeted release 至少兑现了稳定的 intraday upside，但收盘延续仍需谨慎观察。"
    elif target_cases:
        recommendation = "当前 targeted release 已发生变化，但真实次日表现没有形成一致支持，建议只保留为观察样本。"
    else:
        recommendation = "当前没有可供评估的 targeted release 样本。"

    return {
        "release_report": str(Path(release_report).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report).expanduser().resolve()),
        "target_case_count": len(target_cases),
        "promoted_target_case_count": promoted_target_case_count,
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "positive_next_close_count": positive_next_close_count,
        "target_cases": target_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Join targeted short_trade_boundary release results with next-day outcomes.")
    parser.add_argument("--release-report", required=True)
    parser.add_argument("--outcome-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_targeted_short_trade_boundary_release_outcomes(args.release_report, args.outcome_report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_targeted_short_trade_boundary_release_outcomes_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()