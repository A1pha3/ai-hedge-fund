from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


ResolvePreviousContext = Callable[..., tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]]
ResolveComparisonScope = Callable[[str, dict[str, Any], dict[str, Any]], str]
BuildOpenReadyDeltas = Callable[..., dict[str, Any]]
BuildOperatorFocus = Callable[[str, str, dict[str, Any]], list[str]]
ResolveOverallDeltaVerdict = Callable[[str, dict[str, Any]], str]
BuildMaterialChangeAnchor = Callable[..., dict[str, Any]]


def build_open_ready_delta_context(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
    reports_root: str | Path,
    resolve_previous_context: ResolvePreviousContext,
) -> dict[str, Any]:
    latest_btst_run = dict(current_payload.get("latest_btst_run") or {})
    current_priority_snapshot = dict(current_payload.get("latest_priority_board_snapshot") or {})
    normalized_previous_payload = dict(previous_payload or {})
    previous_report_snapshot, previous_priority_board, comparison_basis, previous_reference = resolve_previous_context(
        latest_btst_run=latest_btst_run,
        previous_payload=normalized_previous_payload,
        reports_root=reports_root,
    )
    return {
        "latest_btst_run": latest_btst_run,
        "current_priority_snapshot": current_priority_snapshot,
        "previous_payload": normalized_previous_payload,
        "previous_report_snapshot": previous_report_snapshot,
        "previous_priority_board": previous_priority_board,
        "comparison_basis": comparison_basis,
        "previous_reference": previous_reference,
    }


def _build_current_open_ready_source_paths(latest_btst_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_priority_board_json": latest_btst_snapshot.get("priority_board_json_path"),
        "current_catalyst_theme_frontier_markdown": latest_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
        "current_score_fail_frontier_markdown": latest_btst_snapshot.get("score_fail_frontier_markdown_path"),
        "current_score_fail_recurring_markdown": latest_btst_snapshot.get("score_fail_recurring_markdown_path"),
    }


def _build_previous_open_ready_source_paths(
    previous_payload: dict[str, Any],
    previous_btst_snapshot: dict[str, Any],
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if previous_payload:
        return {
            "previous_priority_board_json": previous_btst_snapshot.get("priority_board_json_path"),
            "previous_catalyst_theme_frontier_markdown": previous_btst_snapshot.get("catalyst_theme_frontier_markdown_path"),
            "previous_score_fail_frontier_markdown": previous_btst_snapshot.get("score_fail_frontier_markdown_path"),
            "previous_score_fail_recurring_markdown": previous_btst_snapshot.get("score_fail_recurring_markdown_path"),
        }
    return {
        "previous_priority_board_json": previous_report_snapshot.get("priority_board_json_path"),
        "previous_catalyst_theme_frontier_markdown": previous_report_snapshot.get("catalyst_theme_frontier_markdown_path"),
        "previous_score_fail_frontier_markdown": None,
        "previous_score_fail_recurring_markdown": None,
    }


def build_open_ready_source_paths(
    *,
    current_payload: dict[str, Any],
    current_nightly_json_path: str | Path,
    previous_payload: dict[str, Any],
    previous_payload_path: str | None,
    previous_report_snapshot: dict[str, Any],
) -> dict[str, Any]:
    latest_btst_snapshot = dict(current_payload.get("latest_btst_snapshot") or {})
    previous_btst_snapshot = dict(previous_payload.get("latest_btst_snapshot") or {})
    return {
        "current_nightly_control_tower_json": str(Path(current_nightly_json_path).expanduser().resolve()),
        "previous_nightly_control_tower_json": previous_payload_path,
        **_build_current_open_ready_source_paths(latest_btst_snapshot),
        **_build_previous_open_ready_source_paths(previous_payload, previous_btst_snapshot, previous_report_snapshot),
        "report_manifest_json": dict(current_payload.get("source_paths") or {}).get("report_manifest_json"),
        "report_manifest_markdown": dict(current_payload.get("source_paths") or {}).get("report_manifest_markdown"),
    }


def build_open_ready_delta_analysis(
    *,
    current_payload: dict[str, Any],
    latest_btst_run: dict[str, Any],
    previous_reference: dict[str, Any],
    comparison_basis: str,
    comparison_scope: str,
    overall_delta_verdict: str,
    operator_focus: list[str],
    delta_sections: dict[str, Any],
    material_change_anchor: dict[str, Any],
    source_paths: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": current_payload.get("generated_at"),
        "comparison_basis": comparison_basis,
        "comparison_scope": comparison_scope,
        "overall_delta_verdict": overall_delta_verdict,
        "current_reference": latest_btst_run,
        "previous_reference": previous_reference,
        "operator_focus": operator_focus[:6],
        "priority_delta": delta_sections["priority_delta"],
        "catalyst_frontier_delta": delta_sections["catalyst_frontier_delta"],
        "score_fail_frontier_delta": delta_sections["score_fail_frontier_delta"],
        "top_priority_action_delta": delta_sections["top_priority_action_delta"],
        "selected_outcome_contract_delta": delta_sections["selected_outcome_contract_delta"],
        "carryover_peer_proof_delta": delta_sections["carryover_peer_proof_delta"],
        "carryover_promotion_gate_delta": delta_sections["carryover_promotion_gate_delta"],
        "governance_delta": delta_sections["governance_delta"],
        "replay_delta": delta_sections["replay_delta"],
        "material_change_anchor": material_change_anchor,
        "source_paths": source_paths,
    }


def build_btst_open_ready_delta_payload(
    current_payload: dict[str, Any],
    *,
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    previous_payload: dict[str, Any] | None = None,
    previous_payload_path: str | None = None,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]] | None = None,
    enable_material_anchor: bool = True,
    build_open_ready_delta_context: Callable[..., dict[str, Any]],
    resolve_open_ready_comparison_scope: ResolveComparisonScope,
    build_open_ready_deltas: BuildOpenReadyDeltas,
    build_open_ready_operator_focus: BuildOperatorFocus,
    resolve_open_ready_overall_delta_verdict: ResolveOverallDeltaVerdict,
    build_open_ready_material_change_anchor: BuildMaterialChangeAnchor,
    build_open_ready_source_paths: Callable[..., dict[str, Any]],
    build_open_ready_delta_analysis: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    context = build_open_ready_delta_context(
        current_payload=current_payload,
        previous_payload=previous_payload,
        reports_root=reports_root,
    )
    comparison_scope = resolve_open_ready_comparison_scope(
        context["comparison_basis"],
        context["previous_reference"],
        context["latest_btst_run"],
    )
    delta_sections = build_open_ready_deltas(
        current_payload=current_payload,
        previous_payload=context["previous_payload"],
        previous_report_snapshot=context["previous_report_snapshot"],
        current_priority_snapshot=context["current_priority_snapshot"],
        previous_priority_board=context["previous_priority_board"],
    )
    operator_focus = build_open_ready_operator_focus(context["comparison_basis"], comparison_scope, delta_sections)
    overall_delta_verdict = resolve_open_ready_overall_delta_verdict(context["comparison_basis"], delta_sections)
    material_change_anchor = build_open_ready_material_change_anchor(
        current_payload=current_payload,
        reports_root=reports_root,
        current_nightly_json_path=current_nightly_json_path,
        historical_payload_candidates=historical_payload_candidates,
        enable_material_anchor=enable_material_anchor,
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
    )
    source_paths = build_open_ready_source_paths(
        current_payload=current_payload,
        current_nightly_json_path=current_nightly_json_path,
        previous_payload=context["previous_payload"],
        previous_payload_path=previous_payload_path,
        previous_report_snapshot=context["previous_report_snapshot"],
    )
    return build_open_ready_delta_analysis(
        current_payload=current_payload,
        latest_btst_run=context["latest_btst_run"],
        previous_reference=context["previous_reference"],
        comparison_basis=context["comparison_basis"],
        comparison_scope=comparison_scope,
        overall_delta_verdict=overall_delta_verdict,
        operator_focus=operator_focus,
        delta_sections=delta_sections,
        material_change_anchor=material_change_anchor,
        source_paths=source_paths,
    )
