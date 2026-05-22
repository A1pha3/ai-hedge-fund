from __future__ import annotations

from scripts.btst_missing_core_features_noise_helpers import (
    classify_missing_core_root_cause,
    suggest_missing_core_compression_action,
)


def test_classify_missing_core_root_cause_marks_layer_c_watchlists_with_empty_payload_as_watchlist_noise() -> None:
    row = {
        "candidate_source": "layer_c_watchlist",
        "decision": "blocked",
        "explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "watchlist_empty_payload"


def test_classify_missing_core_root_cause_marks_layer_c_watchlists_with_metadata_only_payload_as_watchlist_noise() -> None:
    row = {
        "candidate_source": "layer_c_watchlist",
        "decision": "blocked",
        "explainability_key_count": 7,
        "core_explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "watchlist_empty_payload"


def test_classify_missing_core_root_cause_marks_boundary_rows_without_payload_as_contract_gap() -> None:
    row = {
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
        "explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "boundary_without_explainability"


def test_classify_missing_core_root_cause_marks_boundary_rows_with_metadata_only_payload_as_contract_gap() -> None:
    row = {
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
        "explainability_key_count": 10,
        "core_explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "boundary_without_explainability"


def test_suggest_missing_core_compression_action_inspects_boundary_contract_rows() -> None:
    row = {
        "root_cause": "boundary_without_explainability",
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
    }

    assert suggest_missing_core_compression_action(row) == "inspect_candidate_source_contract"
