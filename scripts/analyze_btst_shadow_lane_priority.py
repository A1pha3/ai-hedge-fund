from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_SHADOW_EXPANSION_BOARD_PATH = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.json"
DEFAULT_RECURRING_PAIR_COMPARISON_PATH = REPORTS_DIR / "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_RECURRING_CLOSE_CANDIDATE_PATH = REPORTS_DIR / "recurring_frontier_ticker_release_outcomes_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_RECURRING_INTRADAY_CONTROL_PATH = REPORTS_DIR / "recurring_frontier_ticker_release_outcomes_600821_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p4_shadow_lane_priority_board_20260401.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p4_shadow_lane_priority_board_20260401.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_lane_row(report: dict[str, Any], *, lane_role: str, why_now: str, next_step: str) -> dict[str, Any]:
    return {
        "ticker": report.get("ticker"),
        "lane_role": lane_role,
        "target_case_count": report.get("target_case_count"),
        "promoted_target_case_count": report.get("promoted_target_case_count"),
        "next_high_return_mean": report.get("next_high_return_mean"),
        "next_close_return_mean": report.get("next_close_return_mean"),
        "next_close_positive_rate": report.get("next_close_positive_rate"),
        "why_now": why_now,
        "next_step": next_step,
        "release_report": report.get("release_report"),
        "outcome_report": str(report.get("outcome_report") or ""),
        "recommendation": report.get("recommendation"),
    }


def analyze_btst_shadow_lane_priority(
    shadow_expansion_board_path: str | Path,
    *,
    recurring_pair_comparison_path: str | Path,
    recurring_close_candidate_path: str | Path | None = None,
    recurring_intraday_control_path: str | Path | None = None,
    recurring_002015_path: str | Path | None = None,
    recurring_600821_path: str | Path | None = None,
) -> dict[str, Any]:
    shadow_board = _load_json(shadow_expansion_board_path)
    pair_comparison = _load_json(recurring_pair_comparison_path)
    resolved_close_candidate_path = recurring_close_candidate_path or recurring_002015_path
    resolved_intraday_control_path = recurring_intraday_control_path or recurring_600821_path
    if resolved_close_candidate_path is None or resolved_intraday_control_path is None:
        raise ValueError("Both recurring close-candidate and intraday-control reports are required")

    close_candidate_report = _load_json(resolved_close_candidate_path)
    intraday_control_report = _load_json(resolved_intraday_control_path)

    close_candidate_ticker = str(close_candidate_report.get("ticker") or "close_candidate")
    intraday_control_ticker = str(intraday_control_report.get("ticker") or "intraday_control")

    if not bool(dict(shadow_board.get("frontier_uniqueness") or {}).get("same_rule_expansion_ready")):
        expansion_constraint = "300383_same_rule_expansion_blocked"
    else:
        expansion_constraint = "300383_same_rule_expansion_available"

    lane_rows = [
        _build_lane_row(
            close_candidate_report,
            lane_role="recurring_shadow_close_candidate",
            why_now=f"{close_candidate_ticker} 在当前 recurring frontier peer 里给出了更强的 close-continuation 证据，应作为 close-candidate 主车道。",
            next_step=f"先把 {close_candidate_ticker} 固定为 recurring shadow 的 close-continuation 候选，再决定是否需要新一轮 recurring lane runbook。",
        ),
        _build_lane_row(
            intraday_control_report,
            lane_role="recurring_shadow_intraday_control",
            why_now=f"{intraday_control_ticker} 的 intraday upside 更强，但 close continuation 更弱，适合作为 recurring shadow 的 intraday 控制样本。",
            next_step=f"把 {intraday_control_ticker} 保留为 recurring intraday control，不要把它误写成 close-continuation 规则。",
        ),
    ]

    lane_rows.sort(
        key=lambda row: (
            0 if row["lane_role"] == "recurring_shadow_close_candidate" else 1,
            -float(row.get("next_close_positive_rate") or -999.0),
            -float(row.get("next_close_return_mean") or -999.0),
            -float(row.get("next_high_return_mean") or -999.0),
        )
    )
    for index, row in enumerate(lane_rows, start=1):
        row["priority_rank"] = index

    if expansion_constraint == "300383_same_rule_expansion_blocked":
        recommendation = "300383 继续保留单票 shadow entry，但下一条可推进的 shadow 扩展路线应切到 recurring frontier。" f"其中 {close_candidate_ticker} 优先作为 close-continuation shadow 候选，{intraday_control_ticker} 作为 intraday control。"
    else:
        recommendation = "300383 之外仍有同规则 threshold-only peer，可继续优先做同规则 shadow 扩展。"

    return {
        "generated_on": shadow_board.get("generated_on"),
        "shadow_expansion_board": str(Path(shadow_expansion_board_path).expanduser().resolve()),
        "recurring_pair_comparison": str(Path(recurring_pair_comparison_path).expanduser().resolve()),
        "expansion_constraint": expansion_constraint,
        "pair_recommendation": pair_comparison.get("recommendation"),
        "lane_rows": lane_rows,
        "next_3_tasks": [
            {
                "task_id": "300383_keep_single_name_shadow",
                "title": "维持 300383 单票 shadow",
                "why_now": "它仍是当前唯一 threshold-only 低成本 release，但同规则扩样条件尚不成立。",
                "next_step": "继续保留单票 shadow，不做参数克隆式扩张。",
            },
            {
                "task_id": f"{close_candidate_ticker}_recurring_shadow_close_candidate",
                "title": f"推进 {close_candidate_ticker} recurring shadow close 候选",
                "why_now": lane_rows[0]["why_now"],
                "next_step": lane_rows[0]["next_step"],
            },
            {
                "task_id": f"{intraday_control_ticker}_recurring_intraday_control",
                "title": f"保留 {intraday_control_ticker} recurring intraday control",
                "why_now": lane_rows[1]["why_now"],
                "next_step": lane_rows[1]["next_step"],
            },
        ],
        "recommendation": recommendation,
    }


def render_btst_shadow_lane_priority_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Shadow Lane Priority Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- expansion_constraint: {analysis['expansion_constraint']}")
    lines.append(f"- pair_recommendation: {analysis['pair_recommendation']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Lanes")
    for row in analysis["lane_rows"]:
        lines.append(f"- rank={row['priority_rank']} ticker={row['ticker']} lane_role={row['lane_role']} target_case_count={row['target_case_count']} next_high_return_mean={row['next_high_return_mean']} next_close_return_mean={row['next_close_return_mean']} next_close_positive_rate={row['next_close_positive_rate']}")
        lines.append(f"  why_now: {row['why_now']}")
        lines.append(f"  next_step: {row['next_step']}")
    lines.append("")
    lines.append("## Immediate Next 3")
    for task in analysis["next_3_tasks"]:
        lines.append(f"- {task['task_id']}: {task['title']}")
        lines.append(f"  why_now: {task['why_now']}")
        lines.append(f"  next_step: {task['next_step']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prioritize the next shadow lane once the 300383 threshold-only path cannot be cloned.")
    parser.add_argument("--shadow-expansion-board", default=str(DEFAULT_SHADOW_EXPANSION_BOARD_PATH))
    parser.add_argument("--recurring-pair-comparison", default=str(DEFAULT_RECURRING_PAIR_COMPARISON_PATH))
    parser.add_argument("--recurring-close-candidate", default=str(DEFAULT_RECURRING_CLOSE_CANDIDATE_PATH))
    parser.add_argument("--recurring-intraday-control", "--recurring-600821", default=str(DEFAULT_RECURRING_INTRADAY_CONTROL_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_shadow_lane_priority(
        args.shadow_expansion_board,
        recurring_pair_comparison_path=args.recurring_pair_comparison,
        recurring_close_candidate_path=args.recurring_close_candidate,
        recurring_intraday_control_path=args.recurring_intraday_control,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_shadow_lane_priority_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
