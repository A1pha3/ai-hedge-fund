from __future__ import annotations

import pytest

from src.screening.candidate_pool_frontier_helpers import (
    build_candidate_pool_frontier_entries,
    classify_candidate_pool_frontier_source_family,
)


def test_classify_candidate_pool_frontier_source_family_maps_corridor_and_post_gate() -> None:
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_source": "upstream_liquidity_corridor_shadow",
            "candidate_pool_lane": "layer_a_liquidity_corridor",
        }
    ) == "upstream_liquidity_corridor_shadow"
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_source": "post_gate_liquidity_competition_shadow",
            "candidate_pool_lane": "post_gate_liquidity_competition",
        }
    ) == "post_gate_liquidity_competition_shadow"


def test_classify_candidate_pool_frontier_source_family_falls_back_to_lane_when_source_missing_or_unknown() -> None:
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_pool_lane": "layer_a_liquidity_corridor",
        }
    ) == "upstream_liquidity_corridor_shadow"
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_source": "unknown_source",
            "candidate_pool_lane": "post_gate_liquidity_competition",
        }
    ) == "post_gate_liquidity_competition_shadow"


def test_classify_candidate_pool_frontier_source_family_returns_none_for_unknown_input() -> None:
    assert (
        classify_candidate_pool_frontier_source_family(
            {
                "candidate_source": "unknown_source",
                "candidate_pool_lane": "unknown_lane",
            }
        )
        is None
    )


def test_build_candidate_pool_frontier_entries_keeps_only_entries_that_meet_source_gates() -> None:
    promoted_entries, diagnostics = build_candidate_pool_frontier_entries(
        released_shadow_entries=[
            {
                "ticker": "300720",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_rank": 1131,
                "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
                "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.8507,
                    "close_strength": 0.9092,
                    "catalyst_freshness": 0.0,
                },
            },
            {
                "ticker": "301188",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_rank": 3179,
                "candidate_pool_avg_amount_share_of_cutoff": 0.0738,
                "candidate_pool_avg_amount_share_of_min_gate": 2.4069,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.0,
                    "close_strength": 0.068,
                    "catalyst_freshness": 0.0,
                },
            },
        ],
        shadow_observation_entries=[],
    )

    assert [entry["ticker"] for entry in promoted_entries] == ["300720"]
    assert promoted_entries[0]["frontier_expansion_enabled"] is True
    assert promoted_entries[0]["frontier_expansion_reason"] == "candidate_pool_frontier_expanded"
    assert promoted_entries[0]["frontier_expansion_source_family"] == "upstream_liquidity_corridor_shadow"
    assert diagnostics["source_family_counts"]["upstream_liquidity_corridor_shadow"]["promoted_count"] == 1
    assert diagnostics["source_family_counts"]["upstream_liquidity_corridor_shadow"]["rejected_count"] == 1
    assert diagnostics["promoted_count"] == 1
    assert diagnostics["rejected_count"] == 1


def test_build_candidate_pool_frontier_entries_applies_post_gate_thresholds() -> None:
    promoted_entries, diagnostics = build_candidate_pool_frontier_entries(
        released_shadow_entries=[],
        shadow_observation_entries=[
            {
                "ticker": "600001",
                "candidate_source": "post_gate_liquidity_competition_shadow",
                "candidate_pool_lane": "post_gate_liquidity_competition",
                "candidate_pool_rank": 1499,
                "candidate_pool_avg_amount_share_of_cutoff": 0.18,
                "candidate_pool_avg_amount_share_of_min_gate": 3.0,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.75,
                    "close_strength": 0.88,
                    "catalyst_freshness": 0.0,
                },
            },
            {
                "ticker": "600002",
                "candidate_source": "post_gate_liquidity_competition_shadow",
                "candidate_pool_lane": "post_gate_liquidity_competition",
                "candidate_pool_rank": 1499,
                "candidate_pool_avg_amount_share_of_cutoff": 0.1799,
                "candidate_pool_avg_amount_share_of_min_gate": 3.0,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.75,
                    "close_strength": 0.88,
                    "catalyst_freshness": 0.0,
                },
            },
        ],
    )

    assert [entry["ticker"] for entry in promoted_entries] == ["600001"]
    assert diagnostics["source_family_counts"]["post_gate_liquidity_competition_shadow"]["promoted_count"] == 1
    assert diagnostics["source_family_counts"]["post_gate_liquidity_competition_shadow"]["rejected_count"] == 1


def test_build_candidate_pool_frontier_entries_counts_unclassified_entries_without_promoting_them() -> None:
    promoted_entries, diagnostics = build_candidate_pool_frontier_entries(
        released_shadow_entries=[
            {
                "ticker": "999999",
                "candidate_source": "unknown_source",
                "candidate_pool_lane": "unknown_lane",
                "candidate_pool_rank": 1,
                "candidate_pool_avg_amount_share_of_cutoff": 1.0,
                "candidate_pool_avg_amount_share_of_min_gate": 1.0,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 1.0,
                    "close_strength": 1.0,
                    "catalyst_freshness": 0.0,
                },
            }
        ],
        shadow_observation_entries=[],
    )

    assert promoted_entries == []
    assert diagnostics["unclassified_count"] == 1
    assert diagnostics["promoted_count"] == 0
    assert diagnostics["rejected_count"] == 0


def test_build_candidate_pool_frontier_entries_rejects_non_list_inputs_with_clear_typeerror() -> None:
    with pytest.raises(TypeError, match="released_shadow_entries must be a list"):
        build_candidate_pool_frontier_entries(  # type: ignore[arg-type]
            released_shadow_entries={"ticker": "300720"},
            shadow_observation_entries=[],
        )

    with pytest.raises(TypeError, match="shadow_observation_entries must be a list"):
        build_candidate_pool_frontier_entries(  # type: ignore[arg-type]
            released_shadow_entries=[],
            shadow_observation_entries={"ticker": "300720"},
        )


def test_build_candidate_pool_frontier_entries_rejects_non_dict_entries_with_clear_typeerror() -> None:
    with pytest.raises(TypeError, match="released_shadow_entries\\[0\\] must be a dict"):
        build_candidate_pool_frontier_entries(
            released_shadow_entries=["bad-entry"],  # type: ignore[list-item]
            shadow_observation_entries=[],
        )

    with pytest.raises(TypeError, match="shadow_observation_entries\\[0\\] must be a dict"):
        build_candidate_pool_frontier_entries(
            released_shadow_entries=[],
            shadow_observation_entries=["bad-entry"],  # type: ignore[list-item]
        )
