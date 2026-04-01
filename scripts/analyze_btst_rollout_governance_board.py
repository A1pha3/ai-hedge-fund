from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "p3_top3_post_execution_action_board_20260401.json"
DEFAULT_PRIMARY_ROLL_FORWARD_PATH = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.json"
DEFAULT_SHADOW_EXPANSION_PATH = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.json"
DEFAULT_SHADOW_LANE_PRIORITY_PATH = REPORTS_DIR / "p4_shadow_lane_priority_board_20260401.json"
DEFAULT_PRIMARY_WINDOW_GAP_PATH = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p6_recurring_shadow_runbook_20260401.json"
DEFAULT_RECURRING_CLOSE_BUNDLE_PATH = REPORTS_DIR / "btst_recurring_shadow_close_bundle_300113_20260401.json"
DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.json"
DEFAULT_SHADOW_PEER_SCAN_PATH = REPORTS_DIR / "p7_shadow_peer_scan_300383_20260401.json"
DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.json"
DEFAULT_PENALTY_FRONTIER_PATH = REPORTS_DIR / "btst_penalty_frontier_current_window_20260331.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p5_btst_rollout_governance_board_20260401.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p5_btst_rollout_governance_board_20260401.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _extract_tradeable_tickers(case_keys: list[Any]) -> list[str]:
    tickers: list[str] = []
    for case_key in case_keys:
        parts = str(case_key or "").split(":")
        if len(parts) < 3:
            continue
        ticker = parts[1].strip()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _find_lane_row(rows: list[dict[str, Any]], lane_role: str) -> dict[str, Any]:
    normalized_lane_role = str(lane_role or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("lane_role") or "") == normalized_lane_role), {})


def _summarize_penalty_frontier(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}

    best_variant = dict(report.get("best_variant") or {})
    passing_variant_count = int(report.get("passing_variant_count") or 0)
    released_tickers = _extract_tradeable_tickers(list(best_variant.get("tradeable_cases") or []))
    focus_released_tickers = _extract_tradeable_tickers(list(best_variant.get("focus_tradeable_cases") or []))

    if passing_variant_count <= 0:
        status = "broad_penalty_route_closed_current_window"
        headline = "broad stale/extension penalty relief 在当前窗口没有形成任何通过 closed-tradeable guardrail 的 row。"
    else:
        status = "guardrail_passing_penalty_frontier_present"
        headline = f"当前 penalty frontier 已出现 {passing_variant_count} 个通过 guardrail 的 row，但在新增独立窗口前仍只适合 shadow/research。"

    return {
        "frontier_id": "broad_penalty_relief",
        "status": status,
        "headline": headline,
        "passing_variant_count": passing_variant_count,
        "best_variant_name": best_variant.get("variant_name"),
        "best_variant_family": best_variant.get("variant_family"),
        "best_variant_guardrail_status": best_variant.get("guardrail_status"),
        "best_variant_closed_cycle_tradeable_count": best_variant.get("closed_cycle_tradeable_count"),
        "best_variant_released_tickers": released_tickers,
        "best_variant_focus_released_tickers": focus_released_tickers,
        "focus_tickers": list(report.get("focus_tickers") or []),
        "recommendation": report.get("recommendation"),
    }


def analyze_btst_rollout_governance_board(
    action_board_path: str | Path,
    *,
    primary_roll_forward_path: str | Path,
    shadow_expansion_path: str | Path,
    shadow_lane_priority_path: str | Path,
    primary_window_gap_path: str | Path,
    recurring_shadow_runbook_path: str | Path,
    recurring_close_bundle_path: str | Path | None = None,
    primary_window_validation_runbook_path: str | Path,
    shadow_peer_scan_path: str | Path,
    structural_shadow_runbook_path: str | Path,
    penalty_frontier_path: str | Path | None = None,
) -> dict[str, Any]:
    action_board = _load_json(action_board_path)
    primary_roll = _load_json(primary_roll_forward_path)
    shadow_expansion = _load_json(shadow_expansion_path)
    shadow_lane_priority = _load_json(shadow_lane_priority_path)
    primary_window_gap = _load_json(primary_window_gap_path)
    recurring_shadow_runbook = _load_json(recurring_shadow_runbook_path)
    recurring_close_bundle = _safe_load_json(recurring_close_bundle_path)
    primary_window_validation_runbook = _load_json(primary_window_validation_runbook_path)
    shadow_peer_scan = _load_json(shadow_peer_scan_path)
    structural_shadow_runbook = _load_json(structural_shadow_runbook_path)
    penalty_frontier_summary = _summarize_penalty_frontier(_safe_load_json(penalty_frontier_path))
    recurring_close_candidate = dict(recurring_shadow_runbook.get("close_candidate") or {})
    recurring_intraday_control = dict(recurring_shadow_runbook.get("intraday_control") or {})
    recurring_close_ticker = str(recurring_close_candidate.get("ticker") or "close_candidate")
    recurring_intraday_ticker = str(recurring_intraday_control.get("ticker") or "intraday_control")

    structural_row = next(
        (row for row in list(action_board.get("board_rows") or []) if str(row.get("ticker") or "") == "300724"),
        {},
    )
    recurring_rows = list(shadow_lane_priority.get("lane_rows") or [])
    recurring_close_row = _find_lane_row(recurring_rows, "recurring_shadow_close_candidate")
    recurring_intraday_row = _find_lane_row(recurring_rows, "recurring_shadow_intraday_control")
    close_bundle_outcomes = dict(recurring_close_bundle.get("close_candidate_outcomes") or {})
    close_bundle_summary_path = str(Path(recurring_close_bundle_path).expanduser().resolve()) if recurring_close_bundle_path else None

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
            "ticker": recurring_close_ticker,
            "governance_tier": "recurring_shadow_close_candidate",
            "status": recurring_close_candidate.get("lane_status") or "ready_for_shadow_lane_validation",
            "blocker": "cross_window_stability_missing" if recurring_close_candidate.get("validation_verdict") != "independent_window_requirement_satisfied" else "shadow_lane_validation_ready",
            "next_step": recurring_close_bundle.get("next_step") or recurring_close_candidate.get("next_step") or recurring_close_row.get("next_step") or "",
            "evidence": {
                "target_case_count": recurring_close_row.get("target_case_count"),
                "next_close_positive_rate": close_bundle_outcomes.get("next_close_positive_rate") if close_bundle_outcomes else recurring_close_row.get("next_close_positive_rate"),
                "next_close_return_mean": close_bundle_outcomes.get("next_close_return_mean") if close_bundle_outcomes else recurring_close_row.get("next_close_return_mean"),
                "distinct_window_count": recurring_close_candidate.get("distinct_window_count"),
                "missing_window_count": recurring_close_candidate.get("missing_window_count"),
                "transition_locality": recurring_close_candidate.get("transition_locality"),
                "bundle_report": close_bundle_summary_path,
                "promoted_target_case_count": close_bundle_outcomes.get("promoted_target_case_count") or recurring_close_bundle.get("close_candidate_release", {}).get("promoted_target_case_count"),
            },
        },
        {
            "ticker": recurring_intraday_ticker,
            "governance_tier": "recurring_intraday_control",
            "status": recurring_intraday_control.get("lane_status") or "ready_for_shadow_control_validation",
            "blocker": "cross_window_stability_missing" if recurring_intraday_control.get("validation_verdict") != "independent_window_requirement_satisfied" else "intraday_control_only",
            "next_step": recurring_intraday_control.get("next_step") or recurring_intraday_row.get("next_step") or "",
            "evidence": {
                "target_case_count": recurring_intraday_row.get("target_case_count"),
                "next_high_return_mean": recurring_intraday_row.get("next_high_return_mean"),
                "next_close_positive_rate": recurring_intraday_row.get("next_close_positive_rate"),
                "distinct_window_count": recurring_intraday_control.get("distinct_window_count"),
                "missing_window_count": recurring_intraday_control.get("missing_window_count"),
                "transition_locality": recurring_intraday_control.get("transition_locality"),
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
            "task_id": f"{recurring_close_ticker}_recurring_shadow_validation",
            "title": f"推进 {recurring_close_ticker} recurring shadow 验证",
            "why_now": f"300383 的同规则扩样被封住后，{recurring_close_ticker} 是最合适的 close-continuation recurring shadow 候选。",
            "next_step": governance_rows[2]["next_step"],
        },
        {
            "task_id": f"{recurring_intraday_ticker}_intraday_control_validation",
            "title": f"保留 {recurring_intraday_ticker} intraday control 验证",
            "why_now": "需要一个 recurring intraday 控制样本，防止把 shadow 扩展误判成 close-continuation 规则。",
            "next_step": governance_rows[3]["next_step"],
        },
    ]

    recommendation = (
        "当前 rollout 治理应分成四条清晰车道：001309 只做 primary roll-forward；300383 只做单票 shadow；"
        f"{recurring_close_ticker}/{recurring_intraday_ticker} 组成 recurring frontier 的 close/intraday 双轨；"
        "300724 继续保持 structural shadow hold。"
        f" 若要继续扩 shadow lane，应优先转向 {recurring_close_ticker}/{recurring_intraday_ticker} 的 recurring frontier 组合，而不是复制 300383。"
        " 但在当前证据边界内，这条 recurring lane 同样仍缺第二个独立窗口，只能继续保留 shadow validation 准备态。"
    )
    if recurring_close_bundle:
        recommendation += f" {recurring_close_ticker} close-candidate 侧已经补成可直接复用的 bundle，应优先用 bundle 结果回接 governance，而不是手工拼 release/outcome/pair comparison。"
    if penalty_frontier_summary:
        if penalty_frontier_summary.get("status") == "broad_penalty_route_closed_current_window":
            recommendation += " 同时，broad stale/extension penalty relief 已在当前窗口被证伪，应从 nightly open path 中移除，不再作为广义放松路线继续追踪。"
        else:
            recommendation += " 同时，penalty frontier 虽已出现 guardrail-passing row，但在新增独立窗口前仍只能保留在 shadow/research lane。"

    return {
        "generated_on": action_board.get("generated_on"),
        "source_reports": {
            "action_board": str(Path(action_board_path).expanduser().resolve()),
            "primary_roll_forward": str(Path(primary_roll_forward_path).expanduser().resolve()),
            "shadow_expansion": str(Path(shadow_expansion_path).expanduser().resolve()),
            "shadow_lane_priority": str(Path(shadow_lane_priority_path).expanduser().resolve()),
            "primary_window_gap": str(Path(primary_window_gap_path).expanduser().resolve()),
            "recurring_shadow_runbook": str(Path(recurring_shadow_runbook_path).expanduser().resolve()),
            "recurring_close_bundle": close_bundle_summary_path,
            "primary_window_validation_runbook": str(Path(primary_window_validation_runbook_path).expanduser().resolve()),
            "shadow_peer_scan": str(Path(shadow_peer_scan_path).expanduser().resolve()),
            "structural_shadow_runbook": str(Path(structural_shadow_runbook_path).expanduser().resolve()),
            "penalty_frontier": str(Path(penalty_frontier_path).expanduser().resolve()) if penalty_frontier_path else None,
        },
        "frontier_constraints": [penalty_frontier_summary] if penalty_frontier_summary else [],
        "penalty_frontier_summary": penalty_frontier_summary,
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
    lines.append("## Frontier Constraints")
    frontier_constraints = list(analysis.get("frontier_constraints") or [])
    if not frontier_constraints:
        lines.append("- none")
    for row in frontier_constraints:
        lines.append(
            f"- frontier_id={row.get('frontier_id')} status={row.get('status')} passing_variant_count={row.get('passing_variant_count')} headline={row.get('headline')}"
        )
        lines.append(f"  best_variant: {row.get('best_variant_name')}")
        lines.append(f"  best_variant_released_tickers: {row.get('best_variant_released_tickers')}")
        lines.append(f"  best_variant_focus_released_tickers: {row.get('best_variant_focus_released_tickers')}")
        lines.append(f"  recommendation: {row.get('recommendation')}")
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
    parser.add_argument("--recurring-close-bundle", default=str(DEFAULT_RECURRING_CLOSE_BUNDLE_PATH))
    parser.add_argument("--primary-window-validation-runbook", default=str(DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH))
    parser.add_argument("--shadow-peer-scan", default=str(DEFAULT_SHADOW_PEER_SCAN_PATH))
    parser.add_argument("--structural-shadow-runbook", default=str(DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--penalty-frontier", default=str(DEFAULT_PENALTY_FRONTIER_PATH))
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
        recurring_close_bundle_path=args.recurring_close_bundle,
        primary_window_validation_runbook_path=args.primary_window_validation_runbook,
        shadow_peer_scan_path=args.shadow_peer_scan,
        structural_shadow_runbook_path=args.structural_shadow_runbook,
        penalty_frontier_path=args.penalty_frontier or None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_rollout_governance_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()