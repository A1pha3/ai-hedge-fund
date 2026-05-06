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


def _meets_frontier_gate(entry: dict[str, Any], *, source_family: str) -> bool:
    metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    rank = int(entry.get("candidate_pool_rank") or 0)
    cutoff_share = float(entry.get("candidate_pool_avg_amount_share_of_cutoff") or 0.0)
    min_gate_share = float(entry.get("candidate_pool_avg_amount_share_of_min_gate") or 0.0)
    trend_acceleration = float(metrics.get("trend_acceleration") or 0.0)
    close_strength = float(metrics.get("close_strength") or 0.0)

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


def build_candidate_pool_frontier_entries(
    *,
    released_shadow_entries: list[dict[str, Any]],
    shadow_observation_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    promoted_entries: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"source_family_counts": {}}

    for entry in [*list(released_shadow_entries or []), *list(shadow_observation_entries or [])]:
        current = dict(entry or {})
        source_family = classify_candidate_pool_frontier_source_family(current)
        if source_family is None:
            continue

        bucket = diagnostics["source_family_counts"].setdefault(source_family, {"promoted_count": 0, "rejected_count": 0})
        if not _meets_frontier_gate(current, source_family=source_family):
            bucket["rejected_count"] += 1
            continue

        promoted_entries.append(
            {
                **current,
                "frontier_expansion_enabled": True,
                "frontier_expansion_source_family": source_family,
                "frontier_expansion_reason": "candidate_pool_frontier_expanded",
            }
        )
        bucket["promoted_count"] += 1

    return promoted_entries, diagnostics
