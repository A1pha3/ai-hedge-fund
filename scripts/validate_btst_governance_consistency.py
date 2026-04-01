from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_entry_rollout_governance import derive_candidate_entry_shadow_state
from scripts.btst_report_utils import load_json as _load_json, safe_load_json as _safe_load_json


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


def _find_row(rows: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    normalized_ticker = str(ticker or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("ticker") or "") == normalized_ticker), {})


def _find_row_by_tier(rows: list[dict[str, Any]], governance_tier: str) -> dict[str, Any]:
    normalized_tier = str(governance_tier or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("governance_tier") or "") == normalized_tier), {})


def _resolve_recurring_lane_row(rows: list[dict[str, Any]], ticker: str, governance_tier: str) -> dict[str, Any]:
    row = _find_row(rows, ticker)
    if row:
        return row
    return _find_row_by_tier(rows, governance_tier)


def _find_lane_row(rows: list[dict[str, Any]], lane_id: str) -> dict[str, Any]:
    normalized_lane_id = str(lane_id or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("lane_id") or "") == normalized_lane_id), {})


def _build_check(check_id: str, status: str, summary: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "summary": summary,
        "details": details or {},
    }


def _missing(*values: Any) -> bool:
    return all(value in (None, "", [], {}) for value in values)


def _normalize_frontier_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "frontier_id": row.get("frontier_id"),
        "status": row.get("status"),
        "headline": row.get("headline"),
        "passing_variant_count": row.get("passing_variant_count"),
        "best_variant_name": row.get("best_variant_name"),
        "best_variant_released_tickers": sorted(str(value) for value in list(row.get("best_variant_released_tickers") or []) if value),
        "best_variant_focus_released_tickers": sorted(str(value) for value in list(row.get("best_variant_focus_released_tickers") or []) if value),
    }


def _closed_frontiers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_frontier_row(dict(row or {})) for row in rows if "closed" in str((row or {}).get("status") or "")]
    normalized.sort(key=lambda row: (str(row.get("frontier_id") or ""), str(row.get("status") or ""), str(row.get("best_variant_name") or "")))
    return normalized


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

    board_rows = [dict(row or {}) for row in list(action_board.get("board_rows") or [])]
    governance_rows = [dict(row or {}) for row in list(rollout_governance.get("governance_rows") or [])]

    primary_board = _find_row(board_rows, "001309")
    primary_governance = _find_row(governance_rows, "001309")
    structural_board = _find_row(board_rows, "300724")
    structural_governance = _find_row(governance_rows, "300724")
    recurring_close = dict(recurring_shadow_runbook.get("close_candidate") or {})
    recurring_intraday = dict(recurring_shadow_runbook.get("intraday_control") or {})
    recurring_close_ticker = str(recurring_close.get("ticker") or "300113")
    recurring_intraday_ticker = str(recurring_intraday.get("ticker") or "600821")
    recurring_close_governance = _resolve_recurring_lane_row(governance_rows, recurring_close_ticker, "recurring_shadow_close_candidate")
    recurring_intraday_governance = _resolve_recurring_lane_row(governance_rows, recurring_intraday_ticker, "recurring_intraday_control")

    checks: list[dict[str, Any]] = []

    if _missing(primary_board, primary_governance, primary_window_gap, primary_window_validation_runbook):
        checks.append(_build_check("primary_lane_alignment", "warn", "primary lane 缺少足够输入，无法完成一致性校验。"))
    else:
        missing_window_count = primary_window_gap.get("missing_window_count")
        validation_verdict = primary_window_validation_runbook.get("validation_verdict")
        blocker = primary_governance.get("blocker")
        is_aligned = blocker == "cross_window_stability_missing" and validation_verdict == "await_new_independent_window_data" and int(missing_window_count or 0) > 0
        checks.append(
            _build_check(
                "primary_lane_alignment",
                "pass" if is_aligned else "fail",
                "001309 primary lane 的 blocker、window gap 与 validation verdict 一致。" if is_aligned else "001309 primary lane 在 p5 / p6 / p7 之间存在不一致。",
                details={
                    "blocker": blocker,
                    "missing_window_count": missing_window_count,
                    "validation_verdict": validation_verdict,
                    "action_tier": primary_board.get("action_tier"),
                },
            )
        )

    if _missing(recurring_close_governance, recurring_intraday_governance, recurring_close, recurring_intraday):
        checks.append(_build_check("recurring_shadow_alignment", "warn", "recurring shadow lane 缺少足够输入，无法完成一致性校验。"))
    else:
        close_aligned = recurring_close_governance.get("status") == recurring_close.get("lane_status") and recurring_close.get("validation_verdict") == "await_new_independent_window_data"
        intraday_aligned = recurring_intraday_governance.get("status") == recurring_intraday.get("lane_status") and recurring_intraday.get("validation_verdict") == "await_new_independent_window_data"
        global_verdict = recurring_shadow_runbook.get("global_validation_verdict")
        is_aligned = close_aligned and intraday_aligned and global_verdict == "await_new_recurring_window_evidence"
        checks.append(
            _build_check(
                "recurring_shadow_alignment",
                "pass" if is_aligned else "fail",
                "recurring shadow 的 close / intraday 双车道与全局 verdict 一致。" if is_aligned else "recurring shadow lane 在 p5 / p6 之间存在不一致。",
                details={
                    "close_status": recurring_close_governance.get("status"),
                    "close_lane_status": recurring_close.get("lane_status"),
                    "intraday_status": recurring_intraday_governance.get("status"),
                    "intraday_lane_status": recurring_intraday.get("lane_status"),
                    "global_validation_verdict": global_verdict,
                },
            )
        )

    if _missing(structural_board, structural_governance, structural_shadow_runbook):
        checks.append(_build_check("structural_shadow_alignment", "warn", "structural shadow lane 缺少足够输入，无法完成一致性校验。"))
    else:
        structural_lane_status = structural_shadow_runbook.get("lane_status")
        structural_action_tier = structural_board.get("action_tier")
        governance_status = structural_governance.get("status")
        is_aligned = structural_lane_status == "structural_shadow_hold_only" and governance_status == structural_lane_status and structural_action_tier == "structural_shadow_hold"
        checks.append(
            _build_check(
                "structural_shadow_alignment",
                "pass" if is_aligned else "fail",
                "300724 structural shadow hold 在 p3 / p5 / p8 之间一致。" if is_aligned else "300724 structural shadow hold 在 p3 / p5 / p8 之间存在不一致。",
                details={
                    "action_tier": structural_action_tier,
                    "governance_status": governance_status,
                    "lane_status": structural_lane_status,
                },
            )
        )

    candidate_window_scan_summary = dict(candidate_entry_governance.get("window_scan_summary") or {})
    candidate_shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=str(candidate_window_scan_summary.get("rollout_readiness") or candidate_entry_governance.get("lane_status") or "unknown"),
        preserve_misfire_report_count=int(candidate_window_scan_summary.get("preserve_misfire_report_count") or 0),
        distinct_window_count_with_filtered_entries=int(candidate_window_scan_summary.get("distinct_window_count_with_filtered_entries") or 0),
        target_window_count=int(candidate_entry_governance.get("target_window_count") or 2),
    )
    candidate_lane_status = candidate_entry_governance.get("lane_status")
    candidate_default_status = candidate_entry_governance.get("default_upgrade_status")
    candidate_synthesis_lane = _find_lane_row(list(governance_synthesis.get("lane_matrix") or []), "candidate_entry_shadow")
    if _missing(candidate_lane_status, candidate_default_status, candidate_window_scan_summary):
        checks.append(_build_check("candidate_entry_shadow_alignment", "warn", "candidate-entry governance 缺少足够输入，无法完成一致性校验。"))
    else:
        expected_missing_window_count = int(candidate_shadow_state.get("missing_window_count") or 0)
        reported_missing_window_count = candidate_entry_governance.get("missing_window_count")
        if reported_missing_window_count is None:
            reported_missing_window_count = expected_missing_window_count

        preserve_misfire_report_count = int(candidate_window_scan_summary.get("preserve_misfire_report_count") or 0)
        distinct_window_count = int(candidate_window_scan_summary.get("distinct_window_count_with_filtered_entries") or 0)
        synthesis_projection_aligned = True
        if governance_synthesis:
            synthesis_projection_aligned = bool(candidate_synthesis_lane) and candidate_synthesis_lane.get("lane_status") == candidate_lane_status and candidate_synthesis_lane.get("blocker") == candidate_default_status and int(candidate_synthesis_lane.get("missing_window_count") or 0) == expected_missing_window_count and int(candidate_synthesis_lane.get("preserve_misfire_report_count") or 0) == preserve_misfire_report_count and int(candidate_synthesis_lane.get("distinct_window_count_with_filtered_entries") or 0) == distinct_window_count

        is_aligned = candidate_lane_status == candidate_shadow_state.get("lane_status") and candidate_default_status == candidate_shadow_state.get("default_upgrade_status") and int(reported_missing_window_count or 0) == expected_missing_window_count and synthesis_projection_aligned
        checks.append(
            _build_check(
                "candidate_entry_shadow_alignment",
                "pass" if is_aligned else "fail",
                "candidate-entry lane 与 window-scan 证据、missing-window 缺口和 synthesis 投影保持一致。" if is_aligned else "candidate-entry lane 与 window-scan 证据或 synthesis 投影不一致，需先修复 shadow 治理链后再继续使用。",
                details={
                    "lane_status": candidate_lane_status,
                    "default_upgrade_status": candidate_default_status,
                    "rollout_readiness": candidate_window_scan_summary.get("rollout_readiness"),
                    "target_window_count": candidate_shadow_state.get("target_window_count"),
                    "missing_window_count": int(reported_missing_window_count or 0),
                    "expected_missing_window_count": expected_missing_window_count,
                    "distinct_window_count_with_filtered_entries": distinct_window_count,
                    "preserve_misfire_report_count": preserve_misfire_report_count,
                    "upgrade_gap": candidate_shadow_state.get("upgrade_gap"),
                    "synthesis_projection_aligned": synthesis_projection_aligned,
                    "recommended_structural_variant": candidate_entry_governance.get("recommended_structural_variant"),
                },
            )
        )

    recommendation_text = str(rollout_governance.get("recommendation") or "")
    action_recommendation = str(action_board.get("recommendation") or "")
    if _missing(recommendation_text, action_recommendation):
        checks.append(_build_check("topline_recommendation_alignment", "warn", "缺少 recommendation 文本，无法校验当前主线叙事是否一致。"))
    else:
        shared_signal = "001309" in recommendation_text and "300383" in recommendation_text and "300724" in recommendation_text and "001309" in action_recommendation and "300383" in action_recommendation and "300724" in action_recommendation
        checks.append(
            _build_check(
                "topline_recommendation_alignment",
                "pass" if shared_signal else "warn",
                "p3 与 p5 的 recommendation 都指向 001309 主推进、300383 shadow、300724 structural hold。" if shared_signal else "p3 与 p5 的 recommendation 需要人工复核是否仍然指向同一条主线。",
                details={
                    "action_board_recommendation": action_recommendation,
                    "rollout_recommendation": recommendation_text,
                },
            )
        )

    rollout_closed_frontiers = _closed_frontiers([dict(row or {}) for row in list(rollout_governance.get("frontier_constraints") or [])])
    synthesis_closed_frontiers = _closed_frontiers([dict(row or {}) for row in list(governance_synthesis.get("closed_frontiers") or [])])
    nightly_closed_frontiers = _closed_frontiers([dict(row or {}) for row in list(dict(nightly_control_tower.get("control_tower_snapshot") or {}).get("closed_frontiers") or [])])
    if not governance_synthesis:
        checks.append(
            _build_check(
                "closed_frontier_alignment",
                "warn",
                "缺少 governance synthesis，无法校验 closed_frontiers 是否已从 p5 正确传导。",
                details={
                    "rollout_closed_frontiers": rollout_closed_frontiers,
                    "synthesis_available": False,
                    "nightly_available": bool(nightly_control_tower),
                },
            )
        )
    elif not nightly_control_tower:
        checks.append(
            _build_check(
                "closed_frontier_alignment",
                "warn",
                "governance synthesis 已存在，但 nightly control tower 尚未生成，暂时无法完成 p5 / synthesis / nightly 三方闭环校验。",
                details={
                    "rollout_closed_frontiers": rollout_closed_frontiers,
                    "synthesis_closed_frontiers": synthesis_closed_frontiers,
                    "nightly_available": False,
                },
            )
        )
    else:
        is_aligned = rollout_closed_frontiers == synthesis_closed_frontiers == nightly_closed_frontiers
        checks.append(
            _build_check(
                "closed_frontier_alignment",
                "pass" if is_aligned else "fail",
                "closed_frontiers 在 p5 / synthesis / nightly 三处保持一致。" if is_aligned else "closed_frontiers 在 p5 / synthesis / nightly 之间存在漂移，需先修复治理链路再继续使用。",
                details={
                    "rollout_closed_frontiers": rollout_closed_frontiers,
                    "synthesis_closed_frontiers": synthesis_closed_frontiers,
                    "nightly_closed_frontiers": nightly_closed_frontiers,
                },
            )
        )

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