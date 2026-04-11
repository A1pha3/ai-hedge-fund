from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_report_utils import load_json as _load_json, safe_load_json as _safe_load_json
from scripts.validate_btst_governance_consistency_helpers import (
    build_governance_check_context,
    collect_governance_checks,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "p3_top3_post_execution_action_board_20260401.json"
DEFAULT_ROLLOUT_GOVERNANCE_PATH = REPORTS_DIR / "p5_btst_rollout_governance_board_20260401.json"
DEFAULT_PRIMARY_WINDOW_GAP_PATH = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p6_recurring_shadow_runbook_20260401.json"
DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.json"
DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.json"
DEFAULT_CANDIDATE_ENTRY_GOVERNANCE_PATH = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.json"
DEFAULT_GOVERNANCE_SYNTHESIS_PATH = REPORTS_DIR / "btst_governance_synthesis_latest.json"
DEFAULT_NIGHTLY_CONTROL_TOWER_PATH = REPORTS_DIR / "btst_nightly_control_tower_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_governance_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_governance_validation_latest.md"


def _collect_governance_checks(
    *,
    action_board: dict[str, Any],
    rollout_governance: dict[str, Any],
    primary_window_gap: dict[str, Any],
    recurring_shadow_runbook: dict[str, Any],
    primary_window_validation_runbook: dict[str, Any],
    structural_shadow_runbook: dict[str, Any],
    candidate_entry_governance: dict[str, Any],
    governance_synthesis: dict[str, Any],
    nightly_control_tower: dict[str, Any],
) -> list[dict[str, Any]]:
    context = build_governance_check_context(
        action_board=action_board,
        rollout_governance=rollout_governance,
        primary_window_gap=primary_window_gap,
        recurring_shadow_runbook=recurring_shadow_runbook,
        primary_window_validation_runbook=primary_window_validation_runbook,
        structural_shadow_runbook=structural_shadow_runbook,
        candidate_entry_governance=candidate_entry_governance,
        governance_synthesis=governance_synthesis,
        nightly_control_tower=nightly_control_tower,
    )
    return collect_governance_checks(context)


def _build_governance_validation_analysis(
    *,
    checks: list[dict[str, Any]],
    action_board_path: str | Path,
    rollout_governance_path: str | Path,
    primary_window_gap_path: str | Path,
    recurring_shadow_runbook_path: str | Path,
    primary_window_validation_runbook_path: str | Path,
    structural_shadow_runbook_path: str | Path,
    candidate_entry_governance_path: str | Path,
    governance_synthesis_path: str | Path | None,
    nightly_control_tower_path: str | Path | None,
) -> dict[str, Any]:
    fail_count = sum(1 for check in checks if check["status"] == "fail")
    warn_count = sum(1 for check in checks if check["status"] == "warn")
    pass_count = sum(1 for check in checks if check["status"] == "pass")
    overall_verdict = "fail" if fail_count > 0 else "pass_with_warnings" if warn_count > 0 else "pass"
    return {
        "overall_verdict": overall_verdict,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "checks": checks,
        "source_reports": {
            "action_board": str(Path(action_board_path).expanduser().resolve()),
            "rollout_governance": str(Path(rollout_governance_path).expanduser().resolve()),
            "primary_window_gap": str(Path(primary_window_gap_path).expanduser().resolve()),
            "recurring_shadow_runbook": str(Path(recurring_shadow_runbook_path).expanduser().resolve()),
            "primary_window_validation_runbook": str(Path(primary_window_validation_runbook_path).expanduser().resolve()),
            "structural_shadow_runbook": str(Path(structural_shadow_runbook_path).expanduser().resolve()),
            "candidate_entry_governance": str(Path(candidate_entry_governance_path).expanduser().resolve()),
            "governance_synthesis": str(Path(governance_synthesis_path).expanduser().resolve()) if governance_synthesis_path else None,
            "nightly_control_tower": str(Path(nightly_control_tower_path).expanduser().resolve()) if nightly_control_tower_path else None,
        },
    }


def validate_btst_governance_consistency(
    *,
    action_board_path: str | Path,
    rollout_governance_path: str | Path,
    primary_window_gap_path: str | Path,
    recurring_shadow_runbook_path: str | Path,
    primary_window_validation_runbook_path: str | Path,
    structural_shadow_runbook_path: str | Path,
    candidate_entry_governance_path: str | Path,
    governance_synthesis_path: str | Path | None = None,
    nightly_control_tower_path: str | Path | None = None,
) -> dict[str, Any]:
    action_board = _load_json(action_board_path)
    rollout_governance = _load_json(rollout_governance_path)
    primary_window_gap = _load_json(primary_window_gap_path)
    recurring_shadow_runbook = _load_json(recurring_shadow_runbook_path)
    primary_window_validation_runbook = _load_json(primary_window_validation_runbook_path)
    structural_shadow_runbook = _load_json(structural_shadow_runbook_path)
    candidate_entry_governance = _load_json(candidate_entry_governance_path)
    governance_synthesis = _safe_load_json(governance_synthesis_path)
    nightly_control_tower = _safe_load_json(nightly_control_tower_path)
    checks = _collect_governance_checks(
        action_board=action_board,
        rollout_governance=rollout_governance,
        primary_window_gap=primary_window_gap,
        recurring_shadow_runbook=recurring_shadow_runbook,
        primary_window_validation_runbook=primary_window_validation_runbook,
        structural_shadow_runbook=structural_shadow_runbook,
        candidate_entry_governance=candidate_entry_governance,
        governance_synthesis=governance_synthesis,
        nightly_control_tower=nightly_control_tower,
    )
    return _build_governance_validation_analysis(
        checks=checks,
        action_board_path=action_board_path,
        rollout_governance_path=rollout_governance_path,
        primary_window_gap_path=primary_window_gap_path,
        recurring_shadow_runbook_path=recurring_shadow_runbook_path,
        primary_window_validation_runbook_path=primary_window_validation_runbook_path,
        structural_shadow_runbook_path=structural_shadow_runbook_path,
        candidate_entry_governance_path=candidate_entry_governance_path,
        governance_synthesis_path=governance_synthesis_path,
        nightly_control_tower_path=nightly_control_tower_path,
    )


def render_btst_governance_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Governance Validation")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- overall_verdict: {analysis.get('overall_verdict')}")
    lines.append(f"- pass_count: {analysis.get('pass_count')}")
    lines.append(f"- warn_count: {analysis.get('warn_count')}")
    lines.append(f"- fail_count: {analysis.get('fail_count')}")
    lines.append("")
    lines.append("## Checks")
    for check in list(analysis.get("checks") or []):
        lines.append(f"- {check.get('check_id')}: {check.get('status')} | {check.get('summary')}")
        details = dict(check.get("details") or {})
        for key, value in details.items():
            lines.append(f"  {key}: {value}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate whether current BTST governance artifacts are logically aligned across p3/p5/p6/p7/p8/p9.")
    parser.add_argument("--action-board", default=str(DEFAULT_ACTION_BOARD_PATH))
    parser.add_argument("--rollout-governance", default=str(DEFAULT_ROLLOUT_GOVERNANCE_PATH))
    parser.add_argument("--primary-window-gap", default=str(DEFAULT_PRIMARY_WINDOW_GAP_PATH))
    parser.add_argument("--recurring-shadow-runbook", default=str(DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--primary-window-validation-runbook", default=str(DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH))
    parser.add_argument("--structural-shadow-runbook", default=str(DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--candidate-entry-governance", default=str(DEFAULT_CANDIDATE_ENTRY_GOVERNANCE_PATH))
    parser.add_argument("--governance-synthesis", default=str(DEFAULT_GOVERNANCE_SYNTHESIS_PATH))
    parser.add_argument("--nightly-control-tower", default=str(DEFAULT_NIGHTLY_CONTROL_TOWER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = validate_btst_governance_consistency(
        action_board_path=args.action_board,
        rollout_governance_path=args.rollout_governance,
        primary_window_gap_path=args.primary_window_gap,
        recurring_shadow_runbook_path=args.recurring_shadow_runbook,
        primary_window_validation_runbook_path=args.primary_window_validation_runbook,
        structural_shadow_runbook_path=args.structural_shadow_runbook,
        candidate_entry_governance_path=args.candidate_entry_governance,
        governance_synthesis_path=args.governance_synthesis or None,
        nightly_control_tower_path=args.nightly_control_tower or None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_governance_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
