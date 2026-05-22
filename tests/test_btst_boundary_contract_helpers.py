from __future__ import annotations

from scripts.btst_boundary_contract_helpers import (
    classify_boundary_contract_verdict,
    recommend_boundary_contract_action,
    summarize_boundary_contract_group,
)


def test_summarize_boundary_contract_group_reports_metadata_only_boundary_contract() -> None:
    rows = [
        {
            "candidate_source": "short_trade_boundary",
            "decision": "near_miss",
            "metadata_keys": ["breakout_stage", "target_profile", "replay_context"],
            "core_explainability_key_count": 0,
        },
        {
            "candidate_source": "short_trade_boundary",
            "decision": "rejected",
            "metadata_keys": ["breakout_stage", "layer_c_decision", "replay_context"],
            "core_explainability_key_count": 0,
        },
    ]

    summary = summarize_boundary_contract_group(rows)

    assert summary["row_count"] == 2
    assert summary["metadata_only_rate"] == 1.0
    assert summary["top_metadata_keys"][:2] == ["breakout_stage", "replay_context"]
    assert classify_boundary_contract_verdict(summary) == "metadata_only_boundary_contract"


def test_recommend_boundary_contract_action_requests_fix_for_metadata_only_boundary_contract() -> None:
    summary = {
        "contract_verdict": "metadata_only_boundary_contract",
        "row_count": 5,
    }

    assert recommend_boundary_contract_action(summary) == "fix_candidate_source_contract"
