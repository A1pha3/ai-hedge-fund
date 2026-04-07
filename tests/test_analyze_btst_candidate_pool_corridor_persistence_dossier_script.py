from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_corridor_persistence_dossier import (
    analyze_btst_candidate_pool_corridor_persistence_dossier,
    render_btst_candidate_pool_corridor_persistence_dossier_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_persistence_dossier_flags_300720_waiting_for_second_window(tmp_path: Path) -> None:
    corridor_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"
    objective_monitor_path = tmp_path / "btst_tplus1_tplus2_objective_monitor_latest.json"

    _write_json(
        corridor_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300720",
                "objective_fit_score": 1.0,
                "mean_t_plus_2_return": 0.0787,
                "t_plus_2_positive_rate": 0.8667,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "positive_rate_delta_vs_tradeable_surface": 0.3961,
                "mean_return_delta_vs_tradeable_surface": 0.0844,
                "return_hit_rate_delta_vs_tradeable_surface": 0.6824,
            },
        },
    )
    _write_json(
        lane_pair_board_path,
        {
            "pair_status": "ready_for_ranked_comparison",
            "board_leader": {
                "ticker": "300720",
                "lane_family": "corridor",
                "governance_status": "continuation_only_confirm_then_review",
                "governance_blocker": "no_selected_persistence_or_independent_edge",
                "governance_summary": "still waiting for another independent selected window",
                "current_decision": "selected",
                "current_candidate_source": "post_gate_liquidity_competition_shadow",
                "governance_same_source_sample_count": 1,
                "governance_same_source_next_close_positive_rate": 0.0,
                "governance_same_source_next_close_return_mean": -0.0246,
            },
            "candidates": [
                {
                    "ticker": "300720",
                    "lane_family": "corridor",
                    "role": "primary_shadow_replay",
                    "objective_fit_score": 1.0,
                    "mean_t_plus_2_return": 0.0787,
                    "governance_status": "continuation_only_confirm_then_review",
                    "governance_blocker": "no_selected_persistence_or_independent_edge",
                    "governance_same_source_sample_count": 1,
                    "governance_same_source_next_close_positive_rate": 0.0,
                    "governance_same_source_next_close_return_mean": -0.0246,
                    "current_decision": "selected",
                    "current_candidate_source": "post_gate_liquidity_competition_shadow",
                },
                {
                    "ticker": "003036",
                    "role": "parallel_watch",
                    "governance_status": "transient_probe_only",
                    "governance_blocker": "shadow_recall_not_persistent",
                    "governance_same_source_sample_count": 8,
                    "governance_same_source_next_close_positive_rate": 0.125,
                    "governance_same_source_next_close_return_mean": -0.0313,
                    "objective_fit_score": 0.992,
                    "mean_t_plus_2_return": 0.0823,
                },
            ],
        },
    )
    _write_json(
        objective_monitor_path,
        {
            "tradeable_surface": {
                "objective_fit_score": 0.2492,
                "t_plus_2_positive_rate": 0.4706,
                "t_plus_2_return_hit_rate_at_target": 0.1176,
                "mean_t_plus_2_return": -0.0057,
            }
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_persistence_dossier(
        corridor_pack_path,
        lane_pair_board_path=lane_pair_board_path,
        objective_monitor_path=objective_monitor_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["verdict"] == "await_second_independent_selected_window"
    assert analysis["continuation_readiness"]["missing_independent_sample_count"] == 1
    assert analysis["parallel_watch_summary"]["ticker"] == "003036"
    assert analysis["objective_edge"]["positive_rate_delta_vs_tradeable_surface"] == 0.3961

    markdown = render_btst_candidate_pool_corridor_persistence_dossier_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Persistence Dossier" in markdown
    assert "300720" in markdown
    assert "await_second_independent_selected_window" in markdown
