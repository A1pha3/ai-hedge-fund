from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "p3_top3_post_execution_action_board_20260330.json"
DEFAULT_PRIMARY_ROLL_FORWARD_PATH = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.json"
DEFAULT_SHADOW_EXPANSION_PATH = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.json"
DEFAULT_SHADOW_LANE_PRIORITY_PATH = REPORTS_DIR / "p4_shadow_lane_priority_board_20260330.json"
DEFAULT_PRIMARY_WINDOW_GAP_PATH = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p6_recurring_shadow_runbook_20260330.json"
DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.json"
DEFAULT_SHADOW_PEER_SCAN_PATH = REPORTS_DIR / "p7_shadow_peer_scan_300383_20260330.json"
DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p5_btst_rollout_governance_board_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p5_btst_rollout_governance_board_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def analyze_btst_rollout_governance_board(
    action_board_path: str | Path,
    *,
    primary_roll_forward_path: str | Path,
    shadow_expansion_path: str | Path,
    shadow_lane_priority_path: str | Path,
    primary_window_gap_path: str | Path,
    recurring_shadow_runbook_path: str | Path,
    primary_window_validation_runbook_path: str | Path,
    shadow_peer_scan_path: str | Path,
    structural_shadow_runbook_path: str | Path,
) -> dict[str, Any]:
    action_board = _load_json(action_board_path)
    primary_roll = _load_json(primary_roll_forward_path)
    shadow_expansion = _load_json(shadow_expansion_path)
    shadow_lane_priority = _load_json(shadow_lane_priority_path)
    primary_window_gap = _load_json(primary_window_gap_path)
    recurring_shadow_runbook = _load_json(recurring_shadow_runbook_path)
    primary_window_validation_runbook = _load_json(primary_window_validation_runbook_path)
    shadow_peer_scan = _load_json(shadow_peer_scan_path)
    structural_shadow_runbook = _load_json(structural_shadow_runbook_path)

    structural_row = next(
        (row for row in list(action_board.get("board_rows") or []) if str(row.get("ticker") or "") == "300724"),
        {},
    )
    recurring_rows = list(shadow_lane_priority.get("lane_rows") or [])

    governance_rows = [
        {
            "ticker": "001309",
            "governance_tier": "primary_roll_forward_only",
            "status": primary_roll.get("roll_forward_verdict"),
            "blocker": "cross_window_stability_missing",
            "next_step": list(primary_window_validation_runbook.get("rerun_commands") or list(primary_window_gap.get("next_step_commands") or list(primary_roll.get("next_actions") or [""])))[0],
            "evidence": {
                "target_case_count": primary_roll.get("target_case_count"),
                "distinct_window_count": primary_roll.get("distinct_window_count"),
                "next_close_positive_rate": primary_roll.get("next_close_positive_rate"),
                "missing_window_count": primary_window_gap.get("missing_window_count"),
                "scanned_window_count": len(list(primary_window_validation_runbook.get("window_scan_rows") or [])),
            },
        },
        {
            "ticker": "300383",
            "governance_tier": "single_name_shadow_only",
            "status": shadow_expansion.get("expansion_verdict"),
            "blocker": "same_rule_shadow_expansion_not_ready",
            "next_step": list(shadow_peer_scan.get("next_actions") or list(shadow_expansion.get("next_actions") or [""]))[0],
            "evidence": {
                "target_case_count": shadow_expansion.get("target_case_count"),
                "threshold_only_candidate_count": dict(shadow_expansion.get("frontier_uniqueness") or {}).get("threshold_only_candidate_count"),
                "same_rule_expansion_ready": dict(shadow_expansion.get("frontier_uniqueness") or {}).get("same_rule_expansion_ready"),
                "same_rule_peer_ticker_count": len(list(shadow_peer_scan.get("same_rule_peer_rows") or [])),
            },
        },
        {
            "ticker": "002015",
            "governance_tier": "recurring_shadow_close_candidate",
            "status": "ready_for_shadow_lane_validation",
            "blocker": "penalty_coupled_not_threshold_only",
            "next_step": dict(recurring_shadow_runbook.get("close_candidate") or {}).get("next_step") or (recurring_rows[0]["next_step"] if recurring_rows else ""),
            "evidence": {
                "target_case_count": recurring_rows[0].get("target_case_count") if recurring_rows else None,
                "next_close_positive_rate": recurring_rows[0].get("next_close_positive_rate") if recurring_rows else None,
                "next_close_return_mean": recurring_rows[0].get("next_close_return_mean") if recurring_rows else None,
            },
        },
        {
            "ticker": "600821",
            "governance_tier": "recurring_intraday_control",
            "status": "ready_for_shadow_control_validation",
            "blocker": "close_continuation_weaker_than_002015",
            "next_step": dict(recurring_shadow_runbook.get("intraday_control") or {}).get("next_step") or (recurring_rows[1]["next_step"] if len(recurring_rows) > 1 else ""),
            "evidence": {
                "target_case_count": recurring_rows[1].get("target_case_count") if len(recurring_rows) > 1 else None,
                "next_high_return_mean": recurring_rows[1].get("next_high_return_mean") if len(recurring_rows) > 1 else None,
                "next_close_positive_rate": recurring_rows[1].get("next_close_positive_rate") if len(recurring_rows) > 1 else None,
            },
        },
        {
            "ticker": "300724",
            "governance_tier": "structural_shadow_hold_only",
            "status": structural_shadow_runbook.get("lane_status") or structural_row.get("action_tier"),
            "blocker": "post_release_quality_negative",
            "next_step": structural_shadow_runbook.get("next_step") or structural_row.get("next_step"),
            "evidence": {
                "freeze_verdict": structural_shadow_runbook.get("freeze_verdict"),
                "window_blocked_case_count": structural_shadow_runbook.get("window_blocked_case_count"),
                "window_near_miss_rescuable_count": structural_shadow_runbook.get("window_near_miss_rescuable_count"),
                "next_close_return_mean": structural_shadow_runbook.get("next_close_return_mean") or structural_row.get("next_close_return_mean"),
                "next_close_positive_rate": structural_shadow_runbook.get("next_close_positive_rate") or structural_row.get("next_close_positive_rate"),
            },
        },
    ]

    next_3_tasks = [
        {
            "task_id": "001309_independent_window_validation",
            "title": "补 001309 独立窗口证据",
            "why_now": "这是当前唯一 primary lane，但仍缺跨窗口稳定复现。",
            "next_step": governance_rows[0]["next_step"],
        },
        {
            "task_id": "002015_recurring_shadow_validation",
            "title": "推进 002015 recurring shadow 验证",
            "why_now": "300383 的同规则扩样被封住后，002015 是最合适的 close-continuation recurring shadow 候选。",
            "next_step": governance_rows[2]["next_step"],
        },
        {
            "task_id": "600821_intraday_control_validation",
            "title": "保留 600821 intraday control 验证",
            "why_now": "需要一个 recurring intraday 控制样本，防止把 shadow 扩展误判成 close-continuation 规则。",
            "next_step": governance_rows[3]["next_step"],
        },
    ]

    recommendation = (
        "当前 rollout 治理应分成三条清晰车道：001309 只做 primary roll-forward；300383 只做单票 shadow；"
        "若要继续扩 shadow lane，应优先转向 002015/600821 的 recurring frontier 组合，而不是复制 300383。"
    )

    return {
        "generated_on": action_board.get("generated_on"),
        "source_reports": {
            "action_board": str(Path(action_board_path).expanduser().resolve()),
            "primary_roll_forward": str(Path(primary_roll_forward_path).expanduser().resolve()),
            "shadow_expansion": str(Path(shadow_expansion_path).expanduser().resolve()),
            "shadow_lane_priority": str(Path(shadow_lane_priority_path).expanduser().resolve()),
            "primary_window_gap": str(Path(primary_window_gap_path).expanduser().resolve()),
            "recurring_shadow_runbook": str(Path(recurring_shadow_runbook_path).expanduser().resolve()),
            "primary_window_validation_runbook": str(Path(primary_window_validation_runbook_path).expanduser().resolve()),
            "shadow_peer_scan": str(Path(shadow_peer_scan_path).expanduser().resolve()),
            "structural_shadow_runbook": str(Path(structural_shadow_runbook_path).expanduser().resolve()),
        },
        "governance_rows": governance_rows,
        "next_3_tasks": next_3_tasks,
        "recommendation": recommendation,
    }


def render_btst_rollout_governance_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Rollout Governance Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Governance Rows")
    for row in analysis["governance_rows"]:
        lines.append(
            f"- ticker={row['ticker']} governance_tier={row['governance_tier']} status={row['status']} blocker={row['blocker']}"
        )
        lines.append(f"  next_step: {row['next_step']}")
    lines.append("")
    lines.append("## Immediate Next 3")
    for task in analysis["next_3_tasks"]:
        lines.append(f"- {task['task_id']}: {task['title']}")
        lines.append(f"  why_now: {task['why_now']}")
        lines.append(f"  next_step: {task['next_step']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a unified rollout governance board for BTST primary, shadow, recurring-shadow, and structural lanes.")
    parser.add_argument("--action-board", default=str(DEFAULT_ACTION_BOARD_PATH))
    parser.add_argument("--primary-roll-forward", default=str(DEFAULT_PRIMARY_ROLL_FORWARD_PATH))
    parser.add_argument("--shadow-expansion", default=str(DEFAULT_SHADOW_EXPANSION_PATH))
    parser.add_argument("--shadow-lane-priority", default=str(DEFAULT_SHADOW_LANE_PRIORITY_PATH))
    parser.add_argument("--primary-window-gap", default=str(DEFAULT_PRIMARY_WINDOW_GAP_PATH))
    parser.add_argument("--recurring-shadow-runbook", default=str(DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--primary-window-validation-runbook", default=str(DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH))
    parser.add_argument("--shadow-peer-scan", default=str(DEFAULT_SHADOW_PEER_SCAN_PATH))
    parser.add_argument("--structural-shadow-runbook", default=str(DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_rollout_governance_board(
        args.action_board,
        primary_roll_forward_path=args.primary_roll_forward,
        shadow_expansion_path=args.shadow_expansion,
        shadow_lane_priority_path=args.shadow_lane_priority,
        primary_window_gap_path=args.primary_window_gap,
        recurring_shadow_runbook_path=args.recurring_shadow_runbook,
        primary_window_validation_runbook_path=args.primary_window_validation_runbook,
        shadow_peer_scan_path=args.shadow_peer_scan,
        structural_shadow_runbook_path=args.structural_shadow_runbook,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_rollout_governance_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()