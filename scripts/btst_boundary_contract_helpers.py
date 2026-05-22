from __future__ import annotations

from collections import Counter
from typing import Any

from scripts.btst_analysis_utils import round_or_none


def summarize_boundary_contract_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metadata_counter = Counter(key for row in rows for key in list(row.get("metadata_keys") or []))
    metadata_only_rate = round_or_none(sum(1 for row in rows if int(row.get("core_explainability_key_count") or 0) == 0) / len(rows)) if rows else None
    return {
        "row_count": len(rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in rows)),
        "metadata_only_rate": metadata_only_rate,
        "top_metadata_keys": [item[0] for item in metadata_counter.most_common(5)],
        "core_payload_empty_count": sum(1 for row in rows if int(row.get("core_explainability_key_count") or 0) == 0),
    }


def classify_boundary_contract_verdict(summary: dict[str, Any]) -> str:
    metadata_only_rate = float(summary.get("metadata_only_rate") or 0.0)
    if metadata_only_rate >= 0.95:
        return "metadata_only_boundary_contract"
    if metadata_only_rate <= 0.20:
        return "partial_factor_contract"
    return "mixed_boundary_contract"


def recommend_boundary_contract_action(summary: dict[str, Any]) -> str:
    verdict = str(summary.get("contract_verdict") or classify_boundary_contract_verdict(summary))
    if verdict == "metadata_only_boundary_contract":
        return "fix_candidate_source_contract"
    if verdict == "partial_factor_contract":
        return "hold_boundary_until_more_context"
    return "quarantine_boundary_surface"
