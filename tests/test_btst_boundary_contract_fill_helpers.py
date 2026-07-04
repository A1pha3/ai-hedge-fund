from scripts.btst_boundary_contract_fill_helpers import (
    BOUNDARY_REQUIRED_CORE_KEYS,
    classify_boundary_repair_status,
    recommend_boundary_repair_action,
    repair_boundary_contract_row,
)


def test_repair_boundary_contract_row_fully_repairs_with_provenance() -> None:
    row = {
        "candidate_source": "short_trade_boundary",
        "boundary_context": {
            "breakout_freshness": 0.9,
            "trend_acceleration": 0.8,
            "volume_expansion_quality": 0.7,
            "close_strength": 0.6,
            "t0_tail_strength": 0.5,
            "trend_continuation": 0.4,
            "short_term_reversal": 0.3,
        },
        "metadata_keys": ["candidate_source", "layer_c_decision", "replay_context"],
    }

    repaired = repair_boundary_contract_row(row)

    assert repaired["repair_status"] == "fully_repaired_boundary_contract"
    assert repaired["missing_required_keys"] == []
    assert set(repaired["recovered_core_payload"]) == set(BOUNDARY_REQUIRED_CORE_KEYS)
    assert repaired["fill_provenance"]["trend_acceleration"] == "boundary_context.trend_acceleration"


def test_repair_boundary_contract_row_marks_irrecoverable_keys_explicitly() -> None:
    row = {
        "candidate_source": "layer_b_boundary",
        "boundary_context": {
            "breakout_freshness": 0.9,
            "close_strength": 0.4,
        },
        "metadata_keys": ["candidate_source", "layer_c_decision"],
    }

    repaired = repair_boundary_contract_row(row)

    # even with many missing keys, if we recovered any payload it should be "partially repaired"
    assert repaired["repair_status"] == "partially_repaired_boundary_contract"
    assert "trend_acceleration" in repaired["missing_required_keys"]
    assert "trend_acceleration" not in repaired["recovered_core_payload"]
    assert repaired["fill_provenance"]["breakout_freshness"] == "boundary_context.breakout_freshness"


def test_recommend_boundary_repair_action_only_allows_fully_repaired_rows_back() -> None:
    assert classify_boundary_repair_status([], 7) == "fully_repaired_boundary_contract"
    assert classify_boundary_repair_status(["trend_acceleration"], 6) == "partially_repaired_boundary_contract"
    # also ensure multiple missing keys but non-zero recovery is still partial
    assert classify_boundary_repair_status(["trend_acceleration", "volume_expansion_quality"], 5) == "partially_repaired_boundary_contract"
    assert (
        recommend_boundary_repair_action(
            {
                "fully_repaired_row_count": 1,
                "partially_repaired_row_count": 2,
                "irrecoverable_row_count": 3,
            }
        )
        == "quarantine_boundary_surface"
    )


def test_repair_boundary_contract_row_with_no_boundary_context_is_irrecoverable() -> None:
    row = {
        "candidate_source": "layer_b_boundary",
        # missing boundary_context entirely
        "metadata_keys": ["candidate_source", "layer_c_decision"],
    }

    repaired = repair_boundary_contract_row(row)

    assert repaired["recovered_core_payload"] == {}
    assert set(repaired["missing_required_keys"]) == set(BOUNDARY_REQUIRED_CORE_KEYS)
    assert repaired["repair_status"] == "irrecoverable_boundary_contract"


def test_recommend_boundary_repair_action_handles_partial_and_fully_repaired_branches() -> None:
    # partial-only summary => hold until more context
    summary_partial = {
        "fully_repaired_row_count": 0,
        "partially_repaired_row_count": 1,
        "irrecoverable_row_count": 0,
    }
    assert recommend_boundary_repair_action(summary_partial) == "hold_boundary_repair_until_more_context"

    # fully-repaired-only summary => allow repaired rows for offline research
    summary_full = {
        "fully_repaired_row_count": 1,
        "partially_repaired_row_count": 0,
        "irrecoverable_row_count": 0,
    }
    assert recommend_boundary_repair_action(summary_full) == "allow_repaired_boundary_surface_for_offline_research"
