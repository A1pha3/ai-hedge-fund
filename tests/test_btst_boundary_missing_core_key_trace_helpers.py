from scripts.btst_boundary_missing_core_key_trace_helpers import (
    BOUNDARY_TRACE_KEYS,
    classify_boundary_key_trace_status,
    summarize_boundary_key_trace_statuses,
)


def test_classify_boundary_key_trace_status_marks_missing_at_source() -> None:
    assert classify_boundary_key_trace_status(
        key="breakout_freshness",
        source_payload={},
        attached_target={},
        snapshot_target={},
    ) == "missing_at_source"


def test_classify_boundary_key_trace_status_marks_dropped_before_snapshot() -> None:
    assert classify_boundary_key_trace_status(
        key="trend_acceleration",
        source_payload={"trend_acceleration": 0.8},
        attached_target={},
        snapshot_target={},
    ) == "dropped_before_snapshot"


def test_classify_boundary_key_trace_status_marks_dropped_during_snapshot_serialization() -> None:
    assert classify_boundary_key_trace_status(
        key="volume_expansion_quality",
        source_payload={"volume_expansion_quality": 0.7},
        attached_target={"volume_expansion_quality": 0.7},
        snapshot_target={},
    ) == "dropped_during_snapshot_serialization"


def test_summarize_boundary_key_trace_statuses_counts_present_end_to_end() -> None:
    summary = summarize_boundary_key_trace_statuses(
        source_payload={"t0_tail_strength": 0.9},
        attached_target={"t0_tail_strength": 0.9},
        snapshot_target={"t0_tail_strength": 0.9},
    )

    assert summary["key_trace_statuses"]["t0_tail_strength"] == "present_end_to_end"
    assert summary["status_counts"]["present_end_to_end"] == 1
    assert set(summary["key_trace_statuses"]) == set(BOUNDARY_TRACE_KEYS)


# New tests to assert that falsy-but-valid values like 0.0 are treated as present
# (repository semantics: None means missing; numeric zero counts as present).

def test_zero_value_counts_as_present_end_to_end() -> None:
    # 0.0 is a valid numeric value and should be treated as present end-to-end
    summary = summarize_boundary_key_trace_statuses(
        source_payload={"t0_tail_strength": 0.0},
        attached_target={"t0_tail_strength": 0.0},
        snapshot_target={"t0_tail_strength": 0.0},
    )

    assert summary["key_trace_statuses"]["t0_tail_strength"] == "present_end_to_end"
    assert summary["status_counts"]["present_end_to_end"] == 1


def test_zero_value_dropped_before_snapshot_is_detected() -> None:
    # 0.0 present at source but missing downstream should be detected as dropped
    assert classify_boundary_key_trace_status(
        key="trend_acceleration",
        source_payload={"trend_acceleration": 0.0},
        attached_target={},
        snapshot_target={},
    ) == "dropped_before_snapshot"
