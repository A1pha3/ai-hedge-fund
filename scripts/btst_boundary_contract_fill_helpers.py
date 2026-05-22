from __future__ import annotations

from typing import Any

from scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression import CORE_EXPLAINABILITY_KEYS

BOUNDARY_REQUIRED_CORE_KEYS = tuple(sorted(CORE_EXPLAINABILITY_KEYS))


def classify_boundary_repair_status(missing_required_keys: list[str], recovered_key_count: int) -> str:
    total = len(BOUNDARY_REQUIRED_CORE_KEYS)
    if not missing_required_keys and recovered_key_count == total:
        return "fully_repaired_boundary_contract"
    # Any recovery (non-zero recovered_key_count) counts as partial repair.
    if recovered_key_count > 0:
        return "partially_repaired_boundary_contract"
    return "irrecoverable_boundary_contract"


def repair_boundary_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    boundary_context = dict(row.get("boundary_context") or {})
    recovered_core_payload: dict[str, Any] = {}
    fill_provenance: dict[str, str] = {}
    missing_required_keys: list[str] = []

    for key in BOUNDARY_REQUIRED_CORE_KEYS:
        if key in boundary_context:
            recovered_core_payload[key] = boundary_context[key]
            fill_provenance[key] = f"boundary_context.{key}"
        else:
            missing_required_keys.append(key)

    repair_status = classify_boundary_repair_status(missing_required_keys, len(recovered_core_payload))
    return {
        **row,
        "recovered_core_payload": recovered_core_payload,
        "fill_provenance": fill_provenance,
        "missing_required_keys": missing_required_keys,
        "repair_status": repair_status,
    }


def recommend_boundary_repair_action(summary: dict[str, Any]) -> str:
    if int(summary.get("irrecoverable_row_count") or 0) > 0:
        return "quarantine_boundary_surface"
    if int(summary.get("partially_repaired_row_count") or 0) > 0:
        return "hold_boundary_repair_until_more_context"
    return "allow_repaired_boundary_surface_for_offline_research"
