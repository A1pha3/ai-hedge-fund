from __future__ import annotations

from typing import Any


SUPPORTED_FRONTIER_FAMILIES = frozenset(
    {
        "upstream_liquidity_corridor_shadow",
        "post_gate_liquidity_competition_shadow",
    }
)


def classify_candidate_pool_frontier_source_family(entry: dict[str, Any]) -> str | None:
    candidate_source = str(entry.get("candidate_source") or "").strip()
    if candidate_source in SUPPORTED_FRONTIER_FAMILIES:
        return candidate_source

    lane = str(entry.get("candidate_pool_lane") or "").strip()
    if lane == "layer_a_liquidity_corridor":
        return "upstream_liquidity_corridor_shadow"
    if lane == "post_gate_liquidity_competition":
        return "post_gate_liquidity_competition_shadow"
    return None


def _record_field_issue(bucket: dict[str, Any], *, issue_kind: str, field_name: str) -> None:
    counter_key = "missing_field_counts" if issue_kind == "missing" else "invalid_field_counts"
    counter = dict(bucket.get(counter_key) or {})
    counter[field_name] = int(counter.get(field_name, 0) or 0) + 1
    bucket[counter_key] = counter


def _coerce_numeric(raw_value: Any, *, integer: bool = False) -> tuple[int | float | None, str | None]:
    if raw_value is None:
        return None, "missing"
    if isinstance(raw_value, bool):
        return None, "invalid"
    if isinstance(raw_value, (int, float)):
        return (int(raw_value) if integer else float(raw_value)), None

    normalized = str(raw_value or "").strip()
    if not normalized:
        return None, "missing"
    try:
        parsed = float(normalized)
    except ValueError:
        return None, "invalid"
    return (int(parsed) if integer else parsed), None


def _priority_number(raw_value: Any, *, integer: bool = False) -> int | float:
    parsed, issue_kind = _coerce_numeric(raw_value, integer=integer)
    if issue_kind is not None or parsed is None:
        return 999999999 if integer else 0.0
    return parsed


def _meets_frontier_gate(entry: dict[str, Any], *, source_family: str, bucket: dict[str, Any]) -> bool:
    metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    parsed_fields = {
        "candidate_pool_rank": _coerce_numeric(entry.get("candidate_pool_rank"), integer=True),
        "candidate_pool_avg_amount_share_of_cutoff": _coerce_numeric(entry.get("candidate_pool_avg_amount_share_of_cutoff")),
        "candidate_pool_avg_amount_share_of_min_gate": _coerce_numeric(entry.get("candidate_pool_avg_amount_share_of_min_gate")),
        "trend_acceleration": _coerce_numeric(metrics.get("trend_acceleration")),
        "close_strength": _coerce_numeric(metrics.get("close_strength")),
    }
    for field_name, (_, issue_kind) in parsed_fields.items():
        if issue_kind is not None:
            _record_field_issue(bucket, issue_kind=issue_kind, field_name=field_name)
    if any(issue_kind is not None for _, issue_kind in parsed_fields.values()):
        return False

    rank = int(parsed_fields["candidate_pool_rank"][0] or 0)
    cutoff_share = float(parsed_fields["candidate_pool_avg_amount_share_of_cutoff"][0] or 0.0)
    min_gate_share = float(parsed_fields["candidate_pool_avg_amount_share_of_min_gate"][0] or 0.0)
    trend_acceleration = float(parsed_fields["trend_acceleration"][0] or 0.0)
    close_strength = float(parsed_fields["close_strength"][0] or 0.0)

    # These corridor/post-gate thresholds are intentionally asymmetric: the
    # validation-first BTST frontier widens only when liquidity, rank, and
    # boundary-strength signals are strong enough to limit noisy expansion.
    # The tighter gates keep frontier growth controlled while preserving the
    # distinct risk profile of each source family.
    if source_family == "upstream_liquidity_corridor_shadow":
        return (
            rank > 0
            and rank <= 1500
            and min_gate_share >= 4.0
            and cutoff_share >= 0.20
            and trend_acceleration >= 0.70
            and close_strength >= 0.85
        )
    if source_family == "post_gate_liquidity_competition_shadow":
        return (
            rank > 0
            and rank <= 1500
            and min_gate_share >= 3.0
            and cutoff_share >= 0.18
            and trend_acceleration >= 0.75
            and close_strength >= 0.88
        )
    return False


def _frontier_entry_priority(entry: dict[str, Any], *, source_family: str, promoted: bool) -> tuple[Any, ...]:
    metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    candidate_score = float(_priority_number(metrics.get("candidate_score", entry.get("score_final", entry.get("score_b", 0.0)))))
    min_gate_share = float(_priority_number(entry.get("candidate_pool_avg_amount_share_of_min_gate")))
    cutoff_share = float(_priority_number(entry.get("candidate_pool_avg_amount_share_of_cutoff")))
    rank = int(_priority_number(entry.get("candidate_pool_rank"), integer=True))
    return (
        1 if promoted else 0,
        candidate_score,
        min_gate_share,
        cutoff_share,
        -rank,
        source_family,
    )


def build_candidate_pool_frontier_entries(
    *,
    released_shadow_entries: list[dict[str, Any]],
    shadow_observation_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(released_shadow_entries, list):
        raise TypeError("released_shadow_entries must be a list")
    if not isinstance(shadow_observation_entries, list):
        raise TypeError("shadow_observation_entries must be a list")

    frontier_entry_states: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, Any] = {
        "source_family_counts": {},
        "promoted_count": 0,
        "rejected_count": 0,
        "unclassified_count": 0,
    }

    for source_name, entries in (
        ("released_shadow_entries", released_shadow_entries),
        ("shadow_observation_entries", shadow_observation_entries),
    ):
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise TypeError(f"{source_name}[{index}] must be a dict")

            current = dict(entry)
            source_family = classify_candidate_pool_frontier_source_family(current)
            if source_family is None:
                diagnostics["unclassified_count"] += 1
                continue

            ticker = str(current.get("ticker") or "").strip() or f"__{source_name}:{index}"
            bucket = diagnostics["source_family_counts"].setdefault(source_family, {"promoted_count": 0, "rejected_count": 0})
            meets_gate = _meets_frontier_gate(current, source_family=source_family, bucket=bucket)
            entry_priority = _frontier_entry_priority(current, source_family=source_family, promoted=meets_gate)
            existing_state = frontier_entry_states.get(ticker)
            if existing_state is None:
                frontier_entry_states[ticker] = {
                    "source_family": source_family,
                    "entry": current,
                    "promoted": meets_gate,
                    "priority": entry_priority,
                }
                continue

            if entry_priority > tuple(existing_state.get("priority") or ()):
                existing_state["entry"] = current
                existing_state["source_family"] = source_family
                existing_state["promoted"] = meets_gate
                existing_state["priority"] = entry_priority

    promoted_entries: list[dict[str, Any]] = []
    for frontier_entry_state in frontier_entry_states.values():
        source_family = str(frontier_entry_state.get("source_family") or "")
        bucket = diagnostics["source_family_counts"].setdefault(source_family, {"promoted_count": 0, "rejected_count": 0})
        if not bool(frontier_entry_state.get("promoted")):
            bucket["rejected_count"] += 1
            diagnostics["rejected_count"] += 1
            continue

        current = dict(frontier_entry_state.get("entry") or {})
        promoted_entries.append(
            {
                **current,
                "frontier_expansion_enabled": True,
                "frontier_expansion_source_family": source_family,
                "frontier_expansion_reason": "candidate_pool_frontier_expanded",
            }
        )
        bucket["promoted_count"] += 1
        diagnostics["promoted_count"] += 1

    return promoted_entries, diagnostics
