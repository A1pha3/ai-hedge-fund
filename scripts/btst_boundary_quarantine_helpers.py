from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from scripts.btst_missing_core_features_noise_helpers import suggest_missing_core_compression_action

TARGET_BOUNDARY_SOURCES = {"short_trade_boundary", "layer_b_boundary"}


def is_boundary_without_explainability_target(row: dict[str, Any]) -> bool:
    return (
        str(row.get("root_cause") or "") == "boundary_without_explainability"
        and str(row.get("bucket") or "") == "missing_all_core_features"
        and str(row.get("candidate_source") or "") in TARGET_BOUNDARY_SOURCES
    )


def classify_boundary_quarantine_decision(row: dict[str, Any]) -> dict[str, Any]:
    candidate_source = str(row.get("candidate_source") or "")
    boundary_context = dict(row.get("boundary_context") or {})

    if not candidate_source or not is_boundary_without_explainability_target(row):
        disposition = "separate_surface"
        governance_action = "split_into_separate_research_surface"
    elif not boundary_context:
        disposition = "separate_surface"
        governance_action = "split_into_separate_research_surface"
    else:
        governance_action = suggest_missing_core_compression_action(row)
        if governance_action == "inspect_candidate_source_contract":
            disposition = "quarantine"
        else:
            disposition = "separate_surface"

    return {
        **row,
        "governance_action": governance_action,
        "research_surface_disposition": disposition,
        "factor_surface_allowed": disposition == "allow",
    }


def summarize_boundary_quarantine_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    disposition_counts = Counter(str(row.get("research_surface_disposition") or "unknown") for row in rows)
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)

    source_summary_board = []
    for candidate_source, source_rows in source_groups.items():
        source_summary_board.append(
            {
                "candidate_source": candidate_source,
                "row_count": len(source_rows),
                "quarantine_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "quarantine"),
                "separate_surface_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "separate_surface"),
                "allow_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "allow"),
            }
        )
    source_summary_board.sort(key=lambda row: (-int(row["row_count"]), str(row["candidate_source"])))

    return {
        "disposition_counts": {
            "allow": disposition_counts.get("allow", 0),
            "quarantine": disposition_counts.get("quarantine", 0),
            "separate_surface": disposition_counts.get("separate_surface", 0),
        },
        "source_summary_board": source_summary_board,
    }
