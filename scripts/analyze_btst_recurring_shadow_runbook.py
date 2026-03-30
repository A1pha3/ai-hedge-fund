from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_SHADOW_LANE_PRIORITY_PATH = REPORTS_DIR / "p4_shadow_lane_priority_board_20260330.json"
DEFAULT_RECURRING_PAIR_COMPARISON_PATH = REPORTS_DIR / "recurring_frontier_release_pair_comparison_600821_vs_002015_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p6_recurring_shadow_runbook_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p6_recurring_shadow_runbook_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def analyze_btst_recurring_shadow_runbook(
    shadow_lane_priority_path: str | Path,
    *,
    recurring_pair_comparison_path: str | Path,
) -> dict[str, Any]:
    shadow_lane_priority = _load_json(shadow_lane_priority_path)
    pair_comparison = _load_json(recurring_pair_comparison_path)
    lane_rows = list(shadow_lane_priority.get("lane_rows") or [])

    close_candidate = next((row for row in lane_rows if str(row.get("lane_role") or "") == "recurring_shadow_close_candidate"), {})
    intraday_control = next((row for row in lane_rows if str(row.get("lane_role") or "") == "recurring_shadow_intraday_control"), {})

    runbook = {
        "shadow_lane_priority": str(Path(shadow_lane_priority_path).expanduser().resolve()),
        "recurring_pair_comparison": str(Path(recurring_pair_comparison_path).expanduser().resolve()),
        "close_candidate": {
            **close_candidate,
            "objective": "把 recurring frontier 中最接近 close-continuation 的 lane 固定为 shadow 验证入口。",
            "keep_guardrails": [
                "继续保持 recurring lane 内部 changed_non_target_case_count=0",
                "next_close_positive_rate 不低于 0.66",
                "不得把 penalty-coupled lane 写成 threshold-only 规则",
            ],
        },
        "intraday_control": {
            **intraday_control,
            "objective": "保留 recurring intraday 控制样本，区分 intraday upside 与 close continuation。",
            "keep_guardrails": [
                "只作为 intraday 对照，不参与 close 规则升级",
                "若 next_high_return_mean 优势消失，可从 control 队列移除",
            ],
        },
        "global_guardrails": [
            "recurring shadow lane 只在 300383 same-rule expansion blocked 时启用，不与 single-name shadow 混用。",
            "002015 代表 close-continuation recurring shadow 候选，600821 代表 intraday control。",
            "若 002015 的 close continuation 再次转弱，不得因为 600821 的 intraday upside 仍强就升级 recurring shadow lane。",
        ],
        "execution_sequence": [
            "先保留 300383 作为 single-name shadow，不做参数克隆式扩张。",
            "并行把 002015 固定为 recurring shadow close 候选。",
            "同时把 600821 固定为 recurring intraday control，专门监控 intraday-only 漂移。",
        ],
        "recommendation": (
            "当前 recurring shadow lane 应按 002015 close-candidate + 600821 intraday-control 的双轨结构推进，"
            "而不是把 recurring frontier 当成单一 shadow 规则。"
        ),
        "pair_recommendation": pair_comparison.get("recommendation"),
    }
    return runbook


def render_btst_recurring_shadow_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Recurring Shadow Runbook")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append(f"- pair_recommendation: {analysis['pair_recommendation']}")
    lines.append("")
    lines.append("## Close Candidate")
    lines.append(f"- ticker: {analysis['close_candidate'].get('ticker')}")
    lines.append(f"- next_step: {analysis['close_candidate'].get('next_step')}")
    for item in analysis['close_candidate'].get('keep_guardrails') or []:
        lines.append(f"- keep_guardrail: {item}")
    lines.append("")
    lines.append("## Intraday Control")
    lines.append(f"- ticker: {analysis['intraday_control'].get('ticker')}")
    lines.append(f"- next_step: {analysis['intraday_control'].get('next_step')}")
    for item in analysis['intraday_control'].get('keep_guardrails') or []:
        lines.append(f"- keep_guardrail: {item}")
    lines.append("")
    lines.append("## Execution Sequence")
    for item in analysis['execution_sequence']:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a recurring shadow runbook from the shadow lane priority board.")
    parser.add_argument("--shadow-lane-priority", default=str(DEFAULT_SHADOW_LANE_PRIORITY_PATH))
    parser.add_argument("--recurring-pair-comparison", default=str(DEFAULT_RECURRING_PAIR_COMPARISON_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_recurring_shadow_runbook(
        args.shadow_lane_priority,
        recurring_pair_comparison_path=args.recurring_pair_comparison,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_recurring_shadow_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()