from __future__ import annotations

from collections import Counter
from typing import Any

# Deterministic ordering of boundary trace keys; includes t0_tail_strength per repo context
BOUNDARY_TRACE_KEYS = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "trend_continuation",
    "short_term_reversal",
    "t0_tail_strength",
)


def classify_boundary_key_trace_status(*, key: str, source_payload: dict[str, Any], attached_target: dict[str, Any], snapshot_target: dict[str, Any]) -> str:
    """Classify where a boundary trace key went missing (or present) in the pipeline.

    Returns one of:
    - "missing_at_source"
    - "dropped_before_snapshot"
    - "dropped_during_snapshot_serialization"
    - "present_end_to_end"

    Note: The presence checks intentionally use `is not None` semantics. Within this
    repository and the upstream inspection pipeline, None means "missing" while
    falsy-but-valid numeric values such as 0.0 are treated as present. This function
    therefore treats 0.0 (and other non-None values) as present and will only
    classify a key as missing/dropped when the value is None or absent.
    """
    source_has = source_payload.get(key) is not None
    attached_has = attached_target.get(key) is not None
    snapshot_has = snapshot_target.get(key) is not None

    if not source_has:
        return "missing_at_source"
    if not attached_has:
        return "dropped_before_snapshot"
    if not snapshot_has:
        return "dropped_during_snapshot_serialization"
    return "present_end_to_end"


def summarize_boundary_key_trace_statuses(*, source_payload: dict[str, Any], attached_target: dict[str, Any], snapshot_target: dict[str, Any]) -> dict[str, Any]:
    key_trace_statuses = {
        key: classify_boundary_key_trace_status(
            key=key,
            source_payload=source_payload,
            attached_target=attached_target,
            snapshot_target=snapshot_target,
        )
        for key in BOUNDARY_TRACE_KEYS
    }

    return {
        "key_trace_statuses": key_trace_statuses,
        "status_counts": dict(Counter(key_trace_statuses.values())),
    }
