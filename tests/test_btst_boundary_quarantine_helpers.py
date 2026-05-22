from scripts.btst_boundary_quarantine_helpers import (
    classify_boundary_quarantine_decision,
    is_boundary_without_explainability_target,
    summarize_boundary_quarantine_rows,
)


def test_is_boundary_without_explainability_target_accepts_only_target_bucket() -> None:
    assert is_boundary_without_explainability_target(
        {
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "candidate_source": "short_trade_boundary",
        }
    ) is True
    assert is_boundary_without_explainability_target(
        {
            "root_cause": "diagnostic_probe_without_core_features",
            "bucket": "missing_all_core_features",
            "candidate_source": "watchlist_filter_diagnostics",
        }
    ) is False


def test_classify_boundary_quarantine_decision_marks_target_rows_quarantine() -> None:
    decision = classify_boundary_quarantine_decision(
        {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {"t0_tail_strength": 0.61},
        }
    )

    assert decision["research_surface_disposition"] == "quarantine"
    assert decision["governance_action"] == "inspect_candidate_source_contract"
    assert decision["factor_surface_allowed"] is False


def test_classify_boundary_quarantine_decision_fails_closed_for_ambiguous_rows() -> None:
    decision = classify_boundary_quarantine_decision(
        {
            "ticker": "300111",
            "candidate_source": "",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {},
        }
    )

    assert decision["research_surface_disposition"] == "separate_surface"
    assert decision["governance_action"] == "split_into_separate_research_surface"
    assert decision["factor_surface_allowed"] is False


def test_summarize_boundary_quarantine_rows_builds_disposition_counts() -> None:
    summary = summarize_boundary_quarantine_rows(
        [
            {"candidate_source": "short_trade_boundary", "research_surface_disposition": "quarantine", "governance_action": "inspect_candidate_source_contract"},
            {"candidate_source": "layer_b_boundary", "research_surface_disposition": "quarantine", "governance_action": "inspect_candidate_source_contract"},
            {"candidate_source": "layer_b_boundary", "research_surface_disposition": "separate_surface", "governance_action": "split_into_separate_research_surface"},
        ]
    )

    assert summary["disposition_counts"] == {
        "allow": 0,
        "quarantine": 2,
        "separate_surface": 1,
    }
    assert summary["source_summary_board"][0]["candidate_source"] == "layer_b_boundary"
