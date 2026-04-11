from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


BuildBtstOpenReadyDeltaPayload = Callable[..., dict[str, Any]]
ListChangedDeltaSections = Callable[[dict[str, Any]], list[str]]
SelectPreviousBtstReportSnapshot = Callable[..., dict[str, Any]]


def build_material_change_anchor(
    current_payload: dict[str, Any],
    *,
    reports_root: str | Path,
    current_nightly_json_path: str | Path,
    historical_payload_candidates: list[tuple[dict[str, Any], str | None]],
    build_btst_open_ready_delta_payload: BuildBtstOpenReadyDeltaPayload,
    list_changed_delta_sections: ListChangedDeltaSections,
) -> dict[str, Any]:
    skipped_snapshot_count = 0
    for candidate_payload, candidate_path in historical_payload_candidates:
        anchor_delta = build_btst_open_ready_delta_payload(
            current_payload,
            reports_root=reports_root,
            current_nightly_json_path=current_nightly_json_path,
            previous_payload=candidate_payload,
            previous_payload_path=candidate_path,
            historical_payload_candidates=None,
            enable_material_anchor=False,
        )
        changed_sections = list_changed_delta_sections(anchor_delta)
        if not changed_sections and anchor_delta.get("comparison_scope") == "same_report_rerun" and anchor_delta.get("overall_delta_verdict") == "stable":
            skipped_snapshot_count += 1
            continue
        return {
            "reference_generated_at": candidate_payload.get("generated_at"),
            "reference_report_dir": dict(candidate_payload.get("latest_btst_run") or {}).get("report_dir"),
            "reference_snapshot_path": candidate_path,
            "comparison_basis": anchor_delta.get("comparison_basis"),
            "comparison_scope": anchor_delta.get("comparison_scope"),
            "overall_delta_verdict": anchor_delta.get("overall_delta_verdict"),
            "changed_sections": changed_sections,
            "operator_focus": list(anchor_delta.get("operator_focus") or [])[:4],
            "skipped_snapshot_count": skipped_snapshot_count,
        }
    return {}


def resolve_open_ready_previous_context(
    *,
    latest_btst_run: dict[str, Any],
    previous_payload: dict[str, Any],
    reports_root: str | Path,
    select_previous_btst_report_snapshot: SelectPreviousBtstReportSnapshot,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    previous_report_snapshot = {} if previous_payload else select_previous_btst_report_snapshot(
        reports_root,
        current_report_dir=latest_btst_run.get("report_dir_abs"),
        selection_target=latest_btst_run.get("selection_target"),
    )
    if previous_payload:
        previous_priority_board = dict(previous_payload.get("latest_priority_board_snapshot") or {})
        previous_reference = dict(previous_payload.get("latest_btst_run") or {})
        previous_reference["generated_at"] = previous_payload.get("generated_at")
        previous_reference["reference_kind"] = "nightly_history"
        return previous_report_snapshot, previous_priority_board, "nightly_history", previous_reference
    if previous_report_snapshot:
        return (
            previous_report_snapshot,
            dict(previous_report_snapshot.get("priority_board") or {}),
            "previous_btst_report",
            {
                "report_dir": previous_report_snapshot.get("report_dir"),
                "report_dir_abs": previous_report_snapshot.get("report_dir_abs"),
                "selection_target": previous_report_snapshot.get("selection_target"),
                "trade_date": previous_report_snapshot.get("trade_date"),
                "next_trade_date": previous_report_snapshot.get("next_trade_date"),
                "generated_at": None,
                "reference_kind": "previous_btst_report",
            },
        )
    return previous_report_snapshot, {}, "baseline_captured", {}


def resolve_open_ready_comparison_scope(comparison_basis: str, previous_reference: dict[str, Any], latest_btst_run: dict[str, Any]) -> str:
    if comparison_basis == "nightly_history":
        if str(previous_reference.get("report_dir") or "") == str(latest_btst_run.get("report_dir") or ""):
            return "same_report_rerun"
        return "report_rollforward"
    if comparison_basis == "previous_btst_report":
        return "previous_btst_report"
    return "baseline_captured"
