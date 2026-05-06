from __future__ import annotations

from scripts.btst_profile_replay_utils import _summarize_rows_by_frontier_source_family


def test_summarize_rows_by_frontier_source_family_groups_tradeable_rows() -> None:
    rows = [
        {
            "decision": "selected",
            "candidate_source": "upstream_liquidity_corridor_shadow",
            "frontier_expansion_source_family": "upstream_liquidity_corridor_shadow",
            "next_close_return": 0.03,
            "next_high_return": 0.05,
            "cycle_status": "closed",
            "data_status": "complete",
        },
        {
            "decision": "near_miss",
            "candidate_source": "post_gate_liquidity_competition_shadow",
            "frontier_expansion_source_family": "post_gate_liquidity_competition_shadow",
            "next_close_return": -0.01,
            "next_high_return": 0.02,
            "cycle_status": "closed",
            "data_status": "complete",
        },
        {
            "decision": "blocked",
            "candidate_source": "watchlist_filter_diagnostics",
            "next_close_return": 0.0,
            "next_high_return": 0.0,
            "cycle_status": "open",
            "data_status": "pending",
        },
    ]

    summary = _summarize_rows_by_frontier_source_family(rows, next_high_hit_threshold=0.02)

    assert summary["upstream_liquidity_corridor_shadow"]["tradeable"]["total_count"] == 1
    assert summary["upstream_liquidity_corridor_shadow"]["selected"]["total_count"] == 1
    assert summary["post_gate_liquidity_competition_shadow"]["tradeable"]["total_count"] == 1
    assert summary["post_gate_liquidity_competition_shadow"]["near_miss"]["total_count"] == 1
    assert "watchlist_filter_diagnostics" not in summary
