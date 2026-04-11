from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.analyze_btst_candidate_entry_rollout_governance import derive_candidate_entry_shadow_state


@dataclass(frozen=True)
class GovernanceCheckContext:
    action_board: dict[str, Any]
    rollout_governance: dict[str, Any]
    primary_window_gap: dict[str, Any]
    recurring_shadow_runbook: dict[str, Any]
    primary_window_validation_runbook: dict[str, Any]
    structural_shadow_runbook: dict[str, Any]
    candidate_entry_governance: dict[str, Any]
    governance_synthesis: dict[str, Any]
    nightly_control_tower: dict[str, Any]
    board_rows: list[dict[str, Any]]
    governance_rows: list[dict[str, Any]]
    primary_board: dict[str, Any]
    primary_governance: dict[str, Any]
    structural_board: dict[str, Any]
    structural_governance: dict[str, Any]
    recurring_close: dict[str, Any]
    recurring_intraday: dict[str, Any]
    recurring_close_governance: dict[str, Any]
    recurring_intraday_governance: dict[str, Any]
    candidate_window_scan_summary: dict[str, Any]
    candidate_shadow_state: dict[str, Any]
    candidate_synthesis_lane: dict[str, Any]
    rollout_closed_frontiers: list[dict[str, Any]]
    synthesis_closed_frontiers: list[dict[str, Any]]
    nightly_closed_frontiers: list[dict[str, Any]]


def build_governance_check_context(
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
) -> GovernanceCheckContext:
    board_rows = [dict(row or {}) for row in list(action_board.get("board_rows") or [])]
    governance_rows = [dict(row or {}) for row in list(rollout_governance.get("governance_rows") or [])]
    recurring_close = dict(recurring_shadow_runbook.get("close_candidate") or {})
    recurring_intraday = dict(recurring_shadow_runbook.get("intraday_control") or {})
    recurring_close_ticker = str(recurring_close.get("ticker") or "300113")
    recurring_intraday_ticker = str(recurring_intraday.get("ticker") or "600821")
    candidate_window_scan_summary = dict(candidate_entry_governance.get("window_scan_summary") or {})
    candidate_shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=str(candidate_window_scan_summary.get("rollout_readiness") or candidate_entry_governance.get("lane_status") or "unknown"),
        preserve_misfire_report_count=int(candidate_window_scan_summary.get("preserve_misfire_report_count") or 0),
        distinct_window_count_with_filtered_entries=int(candidate_window_scan_summary.get("distinct_window_count_with_filtered_entries") or 0),
        target_window_count=int(candidate_entry_governance.get("target_window_count") or 2),
    )
    return GovernanceCheckContext(
        action_board=action_board,
        rollout_governance=rollout_governance,
        primary_window_gap=primary_window_gap,
        recurring_shadow_runbook=recurring_shadow_runbook,
        primary_window_validation_runbook=primary_window_validation_runbook,
        structural_shadow_runbook=structural_shadow_runbook,
        candidate_entry_governance=candidate_entry_governance,
        governance_synthesis=governance_synthesis,
        nightly_control_tower=nightly_control_tower,
        board_rows=board_rows,
        governance_rows=governance_rows,
        primary_board=_find_row(board_rows, "001309"),
        primary_governance=_find_row(governance_rows, "001309"),
        structural_board=_find_row(board_rows, "300724"),
        structural_governance=_find_row(governance_rows, "300724"),
        recurring_close=recurring_close,
        recurring_intraday=recurring_intraday,
        recurring_close_governance=_resolve_recurring_lane_row(governance_rows, recurring_close_ticker, "recurring_shadow_close_candidate"),
        recurring_intraday_governance=_resolve_recurring_lane_row(governance_rows, recurring_intraday_ticker, "recurring_intraday_control"),
        candidate_window_scan_summary=candidate_window_scan_summary,
        candidate_shadow_state=candidate_shadow_state,
        candidate_synthesis_lane=_find_lane_row(list(governance_synthesis.get("lane_matrix") or []), "candidate_entry_shadow"),
        rollout_closed_frontiers=_closed_frontiers([dict(row or {}) for row in list(rollout_governance.get("frontier_constraints") or [])]),
        synthesis_closed_frontiers=_closed_frontiers([dict(row or {}) for row in list(governance_synthesis.get("closed_frontiers") or [])]),
        nightly_closed_frontiers=_closed_frontiers([dict(row or {}) for row in list(dict(nightly_control_tower.get("control_tower_snapshot") or {}).get("closed_frontiers") or [])]),
    )


def collect_governance_checks(context: GovernanceCheckContext) -> list[dict[str, Any]]:
    return [
        build_primary_lane_alignment_check(context),
        build_recurring_shadow_alignment_check(context),
        build_structural_shadow_alignment_check(context),
        build_candidate_entry_shadow_alignment_check(context),
        build_topline_recommendation_alignment_check(context),
        build_closed_frontier_alignment_check(context),
    ]


def build_primary_lane_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    if _missing(context.primary_board, context.primary_governance, context.primary_window_gap, context.primary_window_validation_runbook):
        return _build_check("primary_lane_alignment", "warn", "primary lane 缺少足够输入，无法完成一致性校验。")

    missing_window_count = context.primary_window_gap.get("missing_window_count")
    validation_verdict = context.primary_window_validation_runbook.get("validation_verdict")
    blocker = context.primary_governance.get("blocker")
    is_aligned = blocker == "cross_window_stability_missing" and validation_verdict == "await_new_independent_window_data" and int(missing_window_count or 0) > 0
    return _build_check(
        "primary_lane_alignment",
        "pass" if is_aligned else "fail",
        "001309 primary lane 的 blocker、window gap 与 validation verdict 一致。" if is_aligned else "001309 primary lane 在 p5 / p6 / p7 之间存在不一致。",
        details={
            "blocker": blocker,
            "missing_window_count": missing_window_count,
            "validation_verdict": validation_verdict,
            "action_tier": context.primary_board.get("action_tier"),
        },
    )


def build_recurring_shadow_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    if _missing(context.recurring_close_governance, context.recurring_intraday_governance, context.recurring_close, context.recurring_intraday):
        return _build_check("recurring_shadow_alignment", "warn", "recurring shadow lane 缺少足够输入，无法完成一致性校验。")

    close_aligned = context.recurring_close_governance.get("status") == context.recurring_close.get("lane_status") and context.recurring_close.get("validation_verdict") == "await_new_independent_window_data"
    intraday_aligned = context.recurring_intraday_governance.get("status") == context.recurring_intraday.get("lane_status") and context.recurring_intraday.get("validation_verdict") == "await_new_independent_window_data"
    global_verdict = context.recurring_shadow_runbook.get("global_validation_verdict")
    is_aligned = close_aligned and intraday_aligned and global_verdict == "await_new_recurring_window_evidence"
    return _build_check(
        "recurring_shadow_alignment",
        "pass" if is_aligned else "fail",
        "recurring shadow 的 close / intraday 双车道与全局 verdict 一致。" if is_aligned else "recurring shadow lane 在 p5 / p6 之间存在不一致。",
        details={
            "close_status": context.recurring_close_governance.get("status"),
            "close_lane_status": context.recurring_close.get("lane_status"),
            "intraday_status": context.recurring_intraday_governance.get("status"),
            "intraday_lane_status": context.recurring_intraday.get("lane_status"),
            "global_validation_verdict": global_verdict,
        },
    )


def build_structural_shadow_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    if _missing(context.structural_board, context.structural_governance, context.structural_shadow_runbook):
        return _build_check("structural_shadow_alignment", "warn", "structural shadow lane 缺少足够输入，无法完成一致性校验。")

    structural_lane_status = context.structural_shadow_runbook.get("lane_status")
    structural_action_tier = context.structural_board.get("action_tier")
    governance_status = context.structural_governance.get("status")
    is_aligned = structural_lane_status == "structural_shadow_hold_only" and governance_status == structural_lane_status and structural_action_tier == "structural_shadow_hold"
    return _build_check(
        "structural_shadow_alignment",
        "pass" if is_aligned else "fail",
        "300724 structural shadow hold 在 p3 / p5 / p8 之间一致。" if is_aligned else "300724 structural shadow hold 在 p3 / p5 / p8 之间存在不一致。",
        details={
            "action_tier": structural_action_tier,
            "governance_status": governance_status,
            "lane_status": structural_lane_status,
        },
    )


def build_candidate_entry_shadow_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    candidate_lane_status = context.candidate_entry_governance.get("lane_status")
    candidate_default_status = context.candidate_entry_governance.get("default_upgrade_status")
    if _missing(candidate_lane_status, candidate_default_status, context.candidate_window_scan_summary):
        return _build_check("candidate_entry_shadow_alignment", "warn", "candidate-entry governance 缺少足够输入，无法完成一致性校验。")

    expected_missing_window_count = int(context.candidate_shadow_state.get("missing_window_count") or 0)
    reported_missing_window_count = context.candidate_entry_governance.get("missing_window_count")
    if reported_missing_window_count is None:
        reported_missing_window_count = expected_missing_window_count

    preserve_misfire_report_count = int(context.candidate_window_scan_summary.get("preserve_misfire_report_count") or 0)
    distinct_window_count = int(context.candidate_window_scan_summary.get("distinct_window_count_with_filtered_entries") or 0)
    synthesis_projection_aligned = True
    if context.governance_synthesis:
        synthesis_projection_aligned = (
            bool(context.candidate_synthesis_lane)
            and context.candidate_synthesis_lane.get("lane_status") == candidate_lane_status
            and context.candidate_synthesis_lane.get("blocker") == candidate_default_status
            and int(context.candidate_synthesis_lane.get("missing_window_count") or 0) == expected_missing_window_count
            and int(context.candidate_synthesis_lane.get("preserve_misfire_report_count") or 0) == preserve_misfire_report_count
            and int(context.candidate_synthesis_lane.get("distinct_window_count_with_filtered_entries") or 0) == distinct_window_count
        )

    is_aligned = (
        candidate_lane_status == context.candidate_shadow_state.get("lane_status")
        and candidate_default_status == context.candidate_shadow_state.get("default_upgrade_status")
        and int(reported_missing_window_count or 0) == expected_missing_window_count
        and synthesis_projection_aligned
    )
    return _build_check(
        "candidate_entry_shadow_alignment",
        "pass" if is_aligned else "fail",
        "candidate-entry lane 与 window-scan 证据、missing-window 缺口和 synthesis 投影保持一致。" if is_aligned else "candidate-entry lane 与 window-scan 证据或 synthesis 投影不一致，需先修复 shadow 治理链后再继续使用。",
        details={
            "lane_status": candidate_lane_status,
            "default_upgrade_status": candidate_default_status,
            "rollout_readiness": context.candidate_window_scan_summary.get("rollout_readiness"),
            "target_window_count": context.candidate_shadow_state.get("target_window_count"),
            "missing_window_count": int(reported_missing_window_count or 0),
            "expected_missing_window_count": expected_missing_window_count,
            "distinct_window_count_with_filtered_entries": distinct_window_count,
            "preserve_misfire_report_count": preserve_misfire_report_count,
            "upgrade_gap": context.candidate_shadow_state.get("upgrade_gap"),
            "synthesis_projection_aligned": synthesis_projection_aligned,
            "recommended_structural_variant": context.candidate_entry_governance.get("recommended_structural_variant"),
        },
    )


def build_topline_recommendation_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    recommendation_text = str(context.rollout_governance.get("recommendation") or "")
    action_recommendation = str(context.action_board.get("recommendation") or "")
    if _missing(recommendation_text, action_recommendation):
        return _build_check("topline_recommendation_alignment", "warn", "缺少 recommendation 文本，无法校验当前主线叙事是否一致。")

    shared_signal = (
        "001309" in recommendation_text
        and "300383" in recommendation_text
        and "300724" in recommendation_text
        and "001309" in action_recommendation
        and "300383" in action_recommendation
        and "300724" in action_recommendation
    )
    return _build_check(
        "topline_recommendation_alignment",
        "pass" if shared_signal else "warn",
        "p3 与 p5 的 recommendation 都指向 001309 主推进、300383 shadow、300724 structural hold。" if shared_signal else "p3 与 p5 的 recommendation 需要人工复核是否仍然指向同一条主线。",
        details={
            "action_board_recommendation": action_recommendation,
            "rollout_recommendation": recommendation_text,
        },
    )


def build_closed_frontier_alignment_check(context: GovernanceCheckContext) -> dict[str, Any]:
    if not context.governance_synthesis:
        return _build_check(
            "closed_frontier_alignment",
            "warn",
            "缺少 governance synthesis，无法校验 closed_frontiers 是否已从 p5 正确传导。",
            details={
                "rollout_closed_frontiers": context.rollout_closed_frontiers,
                "synthesis_available": False,
                "nightly_available": bool(context.nightly_control_tower),
            },
        )
    if not context.nightly_control_tower:
        return _build_check(
            "closed_frontier_alignment",
            "warn",
            "governance synthesis 已存在，但 nightly control tower 尚未生成，暂时无法完成 p5 / synthesis / nightly 三方闭环校验。",
            details={
                "rollout_closed_frontiers": context.rollout_closed_frontiers,
                "synthesis_closed_frontiers": context.synthesis_closed_frontiers,
                "nightly_available": False,
            },
        )

    is_aligned = context.rollout_closed_frontiers == context.synthesis_closed_frontiers == context.nightly_closed_frontiers
    return _build_check(
        "closed_frontier_alignment",
        "pass" if is_aligned else "fail",
        "closed_frontiers 在 p5 / synthesis / nightly 三处保持一致。" if is_aligned else "closed_frontiers 在 p5 / synthesis / nightly 之间存在漂移，需先修复治理链路再继续使用。",
        details={
            "rollout_closed_frontiers": context.rollout_closed_frontiers,
            "synthesis_closed_frontiers": context.synthesis_closed_frontiers,
            "nightly_closed_frontiers": context.nightly_closed_frontiers,
        },
    )


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
