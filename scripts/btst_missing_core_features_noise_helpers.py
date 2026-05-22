from __future__ import annotations

from typing import Any


def classify_missing_core_root_cause(row: dict[str, Any]) -> str:
    candidate_source = str(row.get("candidate_source") or "")
    decision = str(row.get("decision") or "")
    explainability_key_count = int(row.get("explainability_key_count") or 0)
    core_explainability_key_count = int(row.get("core_explainability_key_count") or 0)
    has_missing_core_pattern = core_explainability_key_count == 0 and explainability_key_count >= 0
    if candidate_source == "layer_c_watchlist" and has_missing_core_pattern:
        return "watchlist_empty_payload"
    if candidate_source in {"short_trade_boundary", "layer_b_boundary"} and has_missing_core_pattern:
        return "boundary_without_explainability"
    if candidate_source == "watchlist_filter_diagnostics" and has_missing_core_pattern:
        return "diagnostic_probe_without_core_features"
    if decision == "blocked" and has_missing_core_pattern:
        return "blocked_before_factor_evaluation"
    return "unknown_missing_core_contract"


def suggest_missing_core_compression_action(row: dict[str, Any]) -> str:
    root_cause = str(row.get("root_cause") or classify_missing_core_root_cause(row))
    if root_cause == "watchlist_empty_payload":
        return "ignore_observation_noise"
    if root_cause == "boundary_without_explainability":
        return "inspect_candidate_source_contract"
    if root_cause == "diagnostic_probe_without_core_features":
        return "exclude_from_factor_surface"
    if root_cause == "blocked_before_factor_evaluation":
        return "hold_until_more_context"
    return "split_into_separate_research_surface"
