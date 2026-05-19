from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.run_btst_candidate_pool_corridor_shadow_pack import analyze_btst_candidate_pool_corridor_shadow_pack
from scripts.run_btst_candidate_pool_corridor_uplift_runbook import analyze_btst_candidate_pool_corridor_uplift_runbook
from scripts.run_btst_candidate_pool_lane_pair_board import analyze_btst_candidate_pool_lane_pair_board
from scripts.run_btst_candidate_pool_upstream_handoff_board import analyze_btst_candidate_pool_upstream_handoff_board
from scripts.run_btst_candidate_pool_corridor_validation_pack import analyze_btst_candidate_pool_corridor_validation_pack
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import analyze_btst_candidate_pool_rebucket_comparison_bundle


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_rebucket_comparison_bundle_reports_parallel_ready(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    rebucket_shadow_pack_path = tmp_path / "btst_candidate_pool_rebucket_shadow_pack_latest.json"
    rebucket_validation_path = tmp_path / "btst_candidate_pool_rebucket_objective_validation_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 2}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "objective_priority_rank": 1,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9961,
                    "mean_t_plus_2_return": 0.0804,
                    "t_plus_2_return_hit_rate_at_target": 0.72,
                    "t_plus_2_positive_rate": 0.79,
                },
                {
                    "priority_handoff": "post_gate_liquidity_competition",
                    "objective_priority_rank": 2,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9827,
                    "mean_t_plus_2_return": 0.1098,
                    "t_plus_2_return_hit_rate_at_target": 0.69,
                    "t_plus_2_positive_rate": 0.77,
                },
            ]
        },
    )
    _write_json(
        branch_priority_path,
        {
            "priority_alignment_status": "divergent_top_lane",
            "branch_rows": [
                {
                    "priority_handoff": "post_gate_liquidity_competition",
                    "execution_priority_rank": 1,
                    "prototype_readiness": "ready_for_shadow",
                },
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "execution_priority_rank": 2,
                    "prototype_readiness": "parallel_probe",
                },
            ],
        },
    )
    _write_json(rebucket_shadow_pack_path, {"experiment": {"priority_handoff": "post_gate_liquidity_competition", "tickers": ["301292"]}})
    _write_json(
        rebucket_validation_path,
        {
            "validation_status": "advance_shadow_replay_comparison",
            "recommendation": "start comparison",
            "branch_objective_row": {
                "priority_handoff": "post_gate_liquidity_competition",
                "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                "closed_cycle_count": 13,
                "objective_fit_score": 0.9827,
                "mean_t_plus_2_return": 0.1098,
                "t_plus_2_return_hit_rate_at_target": 0.69,
                "t_plus_2_positive_rate": 0.77,
            },
        },
    )

    analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        rebucket_shadow_pack_path=rebucket_shadow_pack_path,
        rebucket_objective_validation_path=rebucket_validation_path,
    )

    assert analysis["bundle_status"] == "ready_for_parallel_comparison"
    assert analysis["priority_alignment_status"] == "divergent_top_lane"
    assert analysis["structural_leader"]["priority_handoff"] == "post_gate_liquidity_competition"
    assert analysis["objective_leader"]["priority_handoff"] == "layer_a_liquidity_corridor"


def test_rebucket_comparison_bundle_skips_inactive_rebucket_lane(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    rebucket_shadow_pack_path = tmp_path / "btst_candidate_pool_rebucket_shadow_pack_latest.json"
    rebucket_validation_path = tmp_path / "btst_candidate_pool_rebucket_objective_validation_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 1}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "objective_priority_rank": 1,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9961,
                    "mean_t_plus_2_return": 0.0804,
                },
                {
                    "priority_handoff": "post_gate_liquidity_competition",
                    "objective_priority_rank": 2,
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "objective_fit_score": 0.9827,
                    "mean_t_plus_2_return": 0.1098,
                },
            ]
        },
    )
    _write_json(
        branch_priority_path,
        {
            "priority_alignment_status": "divergent_top_lane",
            "branch_rows": [
                {"priority_handoff": "post_gate_liquidity_competition", "execution_priority_rank": 1, "prototype_readiness": "ready_for_shadow"},
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 2, "prototype_readiness": "parallel_probe"},
            ],
        },
    )
    _write_json(rebucket_shadow_pack_path, {"shadow_status": "persistence_diagnostics_only", "experiment": {"tickers": ["301292"]}})
    _write_json(
        rebucket_validation_path,
        {
            "validation_status": "advance_shadow_replay_comparison",
            "branch_objective_row": {
                "priority_handoff": "post_gate_liquidity_competition",
                "ticker": "301292",
                "objective_fit_score": 0.9827,
                "mean_t_plus_2_return": 0.1098,
            },
        },
    )

    analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        rebucket_shadow_pack_path=rebucket_shadow_pack_path,
        rebucket_objective_validation_path=rebucket_validation_path,
    )

    assert analysis["bundle_status"] == "skipped_no_rebucket_lane"
    assert analysis["rebucket_objective_row"] == {}
    assert analysis["next_step"].startswith("当前没有 active rebucket challenger")


def test_corridor_validation_pack_reports_parallel_probe_ready(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 3}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 29,
                    "objective_fit_score": 0.9961,
                    "mean_t_plus_2_return": 0.0804,
                }
            ],
            "ticker_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "ticker": "300720",
                    "mean_t_plus_2_return": 0.0841,
                    "objective_fit_score": 0.997,
                },
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "ticker": "003036",
                    "mean_t_plus_2_return": 0.0788,
                    "objective_fit_score": 0.991,
                },
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300720", "corridor_priority_rank": 1, "tractability_tier": "primary", "uplift_to_cutoff_multiple_mean": 1.2},
                {"ticker": "003036", "corridor_priority_rank": 2, "tractability_tier": "parallel", "uplift_to_cutoff_multiple_mean": 1.1},
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
    )

    assert analysis["pack_status"] == "parallel_probe_ready"
    assert analysis["focus_ticker"] == "300720"
    assert analysis["promotion_readiness_status"] == "corridor_shadow_probe_ready"
    assert analysis["primary_validation_ticker"]["ticker"] == "300720"
    assert analysis["strict_release_tickers"] == ["300720"]
    assert [row["ticker"] for row in analysis["parallel_watch_tickers"]] == []


def test_corridor_validation_pack_promotes_strong_corridor_candidate_readiness(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 2}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 12,
                    "objective_fit_score": 0.9971,
                    "mean_t_plus_2_return": 0.1005,
                }
            ],
            "ticker_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "ticker": "300683",
                    "mean_t_plus_2_return": 0.1005,
                    "objective_fit_score": 1.0,
                    "t_plus_2_return_hit_rate_at_target": 0.875,
                    "t_plus_2_positive_rate": 1.0,
                    "closed_cycle_count": 8,
                }
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300683", "corridor_priority_rank": 1, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 6.4382}
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
    )

    assert analysis["pack_status"] == "parallel_probe_ready"
    assert analysis["promotion_readiness_status"] == "corridor_promotion_candidate_ready"
    assert "promotion-candidate" in analysis["recommendation"]


def test_corridor_validation_pack_excludes_low_gate_tail_without_backfilling_new_parallel(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    narrow_probe_path = tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 4}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 16,
                    "objective_fit_score": 0.9913,
                    "mean_t_plus_2_return": 0.1258,
                }
            ],
            "ticker_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "300683", "mean_t_plus_2_return": 0.1051, "objective_fit_score": 1.0},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688796", "mean_t_plus_2_return": 0.1333, "objective_fit_score": 0.98},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "301188", "mean_t_plus_2_return": 0.1214, "objective_fit_score": 0.975},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688383", "mean_t_plus_2_return": 0.1188, "objective_fit_score": 0.972},
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300683", "corridor_priority_rank": 1, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 6.3291},
                {"ticker": "688796", "corridor_priority_rank": 2, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 8.9123},
                {"ticker": "301188", "corridor_priority_rank": 3, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.3502},
                {"ticker": "688383", "corridor_priority_rank": 4, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.9812},
            ],
        },
    )
    _write_json(
        narrow_probe_path,
        {
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        corridor_narrow_probe_path=narrow_probe_path,
    )

    assert analysis["primary_validation_ticker"]["ticker"] == "300683"
    assert analysis["strict_release_tickers"] == ["300683"]
    assert [row["ticker"] for row in analysis["parallel_watch_tickers"]] == []
    assert analysis["excluded_low_gate_tail_tickers"] == ["688796"]


def test_corridor_validation_pack_emits_strict_release_contract_for_retained_corridor_focus(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    narrow_probe_path = tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 4}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 16,
                    "objective_fit_score": 0.9913,
                    "mean_t_plus_2_return": 0.1258,
                }
            ],
            "ticker_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "300683", "mean_t_plus_2_return": 0.1051, "objective_fit_score": 1.0},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688796", "mean_t_plus_2_return": 0.1333, "objective_fit_score": 0.98},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "301188", "mean_t_plus_2_return": 0.1214, "objective_fit_score": 0.975},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688383", "mean_t_plus_2_return": 0.1188, "objective_fit_score": 0.972},
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300683", "corridor_priority_rank": 1, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 6.3291},
                {"ticker": "688796", "corridor_priority_rank": 2, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 8.9123},
                {"ticker": "301188", "corridor_priority_rank": 3, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.3502},
                {"ticker": "688383", "corridor_priority_rank": 4, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.9812},
            ],
        },
    )
    _write_json(
        narrow_probe_path,
        {
            "deepest_corridor_focus_tickers": ["301188"],
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        corridor_narrow_probe_path=narrow_probe_path,
    )

    assert analysis["strict_release_status"] == "strict_release_ready"
    assert [row["ticker"] for row in analysis["strict_release_candidates"]] == ["300683", "301188"]
    assert analysis["strict_release_tickers"] == ["300683", "301188"]
    assert [row["ticker"] for row in analysis["validation_only_rows"]] == ["688796"]
    assert analysis["validation_only_tickers"] == ["688796"]


def test_corridor_validation_pack_uses_deepest_focus_truth_outside_top_parallel_slice(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    narrow_probe_path = tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 5}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 18,
                    "objective_fit_score": 0.9924,
                    "mean_t_plus_2_return": 0.1311,
                }
            ],
            "ticker_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "300683", "mean_t_plus_2_return": 0.1051, "objective_fit_score": 1.0},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688796", "mean_t_plus_2_return": 0.1333, "objective_fit_score": 0.98},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "301188", "mean_t_plus_2_return": 0.1214, "objective_fit_score": 0.975},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688383", "mean_t_plus_2_return": 0.1188, "objective_fit_score": 0.972},
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300683", "corridor_priority_rank": 1, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 6.3291},
                {"ticker": "688796", "corridor_priority_rank": 2, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 8.9123},
                {"ticker": "301188", "corridor_priority_rank": 3, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.3502},
                {"ticker": "688383", "corridor_priority_rank": 4, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.9812},
            ],
        },
    )
    _write_json(
        narrow_probe_path,
        {
            "deepest_corridor_focus_tickers": ["688383"],
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        corridor_narrow_probe_path=narrow_probe_path,
    )

    assert analysis["strict_release_tickers"] == ["300683", "688383"]
    assert [row["ticker"] for row in analysis["parallel_watch_tickers"]] == ["688383"]
    assert [row["ticker"] for row in analysis["validation_only_rows"]] == ["688796"]
    assert "301188" not in analysis["strict_release_tickers"]


def test_corridor_validation_pack_does_not_backfill_parallel_strict_release_without_deepest_focus_truth(tmp_path: Path) -> None:
    dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    branch_priority_path = tmp_path / "btst_candidate_pool_branch_priority_board_latest.json"
    narrow_probe_path = tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json"

    _write_json(dossier_path, {"priority_stage_counts": {"candidate_pool_truncated_after_filters": 4}})
    _write_json(
        lane_support_path,
        {
            "branch_rows": [
                {
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 18,
                    "objective_fit_score": 0.9924,
                    "mean_t_plus_2_return": 0.1311,
                }
            ],
            "ticker_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "300683", "mean_t_plus_2_return": 0.1051, "objective_fit_score": 1.0},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688796", "mean_t_plus_2_return": 0.1333, "objective_fit_score": 0.98},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "301188", "mean_t_plus_2_return": 0.1214, "objective_fit_score": 0.975},
                {"priority_handoff": "layer_a_liquidity_corridor", "ticker": "688383", "mean_t_plus_2_return": 0.1188, "objective_fit_score": 0.972},
            ],
        },
    )
    _write_json(
        branch_priority_path,
        {
            "branch_rows": [
                {"priority_handoff": "layer_a_liquidity_corridor", "execution_priority_rank": 1, "prototype_readiness": "parallel_probe"}
            ],
            "corridor_ticker_rows": [
                {"ticker": "300683", "corridor_priority_rank": 1, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 6.3291},
                {"ticker": "688796", "corridor_priority_rank": 2, "tractability_tier": "second_shadow_probe", "uplift_to_cutoff_multiple_mean": 8.9123},
                {"ticker": "301188", "corridor_priority_rank": 3, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.3502},
                {"ticker": "688383", "corridor_priority_rank": 4, "tractability_tier": "parallel_probe", "uplift_to_cutoff_multiple_mean": 6.9812},
            ],
        },
    )
    _write_json(
        narrow_probe_path,
        {
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        dossier_path,
        lane_objective_support_path=lane_support_path,
        branch_priority_board_path=branch_priority_path,
        corridor_narrow_probe_path=narrow_probe_path,
    )

    assert analysis["strict_release_tickers"] == ["300683"]
    assert analysis["parallel_watch_tickers"] == []
    assert [row["ticker"] for row in analysis["validation_only_rows"]] == ["688796"]
    assert "301188" not in analysis["strict_release_tickers"]


def test_corridor_shadow_pack_promotes_primary_shadow_replay(tmp_path: Path) -> None:
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300720",
                "validation_priority_rank": 1,
                "tractability_tier": "second_shadow_probe",
                "corridor_priority_rank": 1,
                "closed_cycle_count": 15,
                "mean_t_plus_2_return": 0.0787,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "objective_fit_score": 1.0,
                "uplift_to_cutoff_multiple_mean": 6.6541,
                "profile_summary": "primary corridor ticker",
            },
            "parallel_watch_tickers": [
                {
                    "ticker": "003036",
                    "validation_priority_rank": 2,
                    "tractability_tier": "upstream_research_only",
                    "corridor_priority_rank": 2,
                    "closed_cycle_count": 14,
                    "mean_t_plus_2_return": 0.0823,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.992,
                    "uplift_to_cutoff_multiple_mean": 10.691,
                    "profile_summary": "parallel corridor ticker",
                }
            ],
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300720",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                    "closed_cycle_count": 15,
                    "mean_t_plus_2_return": 0.0787,
                    "t_plus_2_return_hit_rate_at_target": 0.8,
                    "t_plus_2_positive_rate": 0.8667,
                    "objective_fit_score": 1.0,
                    "uplift_to_cutoff_multiple_mean": 6.6541,
                    "profile_summary": "primary corridor ticker",
                },
                {
                    "ticker": "003036",
                    "validation_priority_rank": 2,
                    "tractability_tier": "upstream_research_only",
                    "corridor_priority_rank": 2,
                    "closed_cycle_count": 14,
                    "mean_t_plus_2_return": 0.0823,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.992,
                    "uplift_to_cutoff_multiple_mean": 10.691,
                    "profile_summary": "parallel corridor ticker",
                },
            ],
            "strict_release_tickers": ["300720", "003036"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert analysis["shadow_status"] == "ready_for_primary_shadow_replay"
    assert analysis["primary_shadow_replay"]["ticker"] == "300720"
    assert [row["ticker"] for row in analysis["parallel_watch_lanes"]] == ["003036"]
    assert any("run_btst_candidate_pool_corridor_shadow_pack.py" in command for command in analysis["refresh_commands"])
    assert any("parallel_watch=003036" in command for command in analysis["shadow_replay_commands"])


def test_corridor_shadow_pack_surfaces_excluded_low_gate_tail(tmp_path: Path) -> None:
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300683",
                "validation_priority_rank": 1,
                "tractability_tier": "second_shadow_probe",
                "corridor_priority_rank": 1,
                "closed_cycle_count": 4,
                "mean_t_plus_2_return": 0.1051,
                "t_plus_2_return_hit_rate_at_target": 1.0,
                "t_plus_2_positive_rate": 1.0,
                "objective_fit_score": 1.0,
                "uplift_to_cutoff_multiple_mean": 6.3291,
                "profile_summary": "primary corridor ticker",
            },
            "parallel_watch_tickers": [
                {
                    "ticker": "301188",
                    "validation_priority_rank": 3,
                    "tractability_tier": "parallel_probe",
                    "corridor_priority_rank": 3,
                    "closed_cycle_count": 6,
                    "mean_t_plus_2_return": 0.1214,
                    "t_plus_2_return_hit_rate_at_target": 1.0,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.975,
                    "uplift_to_cutoff_multiple_mean": 6.3502,
                    "profile_summary": "parallel corridor ticker",
                }
            ],
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                },
                {
                    "ticker": "301188",
                    "validation_priority_rank": 3,
                    "tractability_tier": "parallel_probe",
                    "corridor_priority_rank": 3,
                },
            ],
            "strict_release_tickers": ["300683", "301188"],
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert [row["ticker"] for row in analysis["parallel_watch_lanes"]] == ["301188"]
    assert analysis["excluded_low_gate_tail_tickers"] == ["688796"]
    assert "688796" in analysis["recommendation"]


def test_corridor_shadow_pack_preserves_strict_release_contract_and_validation_only_tail(tmp_path: Path) -> None:
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300683",
                "validation_priority_rank": 1,
                "tractability_tier": "second_shadow_probe",
                "corridor_priority_rank": 1,
                "closed_cycle_count": 4,
                "mean_t_plus_2_return": 0.1051,
                "t_plus_2_return_hit_rate_at_target": 1.0,
                "t_plus_2_positive_rate": 1.0,
                "objective_fit_score": 1.0,
                "uplift_to_cutoff_multiple_mean": 6.3291,
                "profile_summary": "primary corridor ticker",
            },
            "parallel_watch_tickers": [
                {
                    "ticker": "301188",
                    "validation_priority_rank": 3,
                    "tractability_tier": "parallel_probe",
                    "corridor_priority_rank": 3,
                    "closed_cycle_count": 6,
                    "mean_t_plus_2_return": 0.1214,
                    "t_plus_2_return_hit_rate_at_target": 1.0,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.975,
                    "uplift_to_cutoff_multiple_mean": 6.3502,
                    "profile_summary": "parallel corridor ticker",
                }
            ],
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                },
                {
                    "ticker": "301188",
                    "validation_priority_rank": 3,
                    "tractability_tier": "parallel_probe",
                    "corridor_priority_rank": 3,
                },
            ],
            "strict_release_tickers": ["300683", "301188"],
            "validation_only_rows": [
                {
                    "ticker": "688796",
                    "validation_priority_rank": 2,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 2,
                }
            ],
            "validation_only_tickers": ["688796"],
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert analysis["shadow_status"] == "ready_for_primary_shadow_replay"
    assert analysis["strict_release_tickers"] == ["300683", "301188"]
    assert analysis["primary_shadow_replay"]["ticker"] == "300683"
    assert [row["ticker"] for row in analysis["parallel_watch_lanes"]] == ["301188"]
    assert analysis["validation_only_tickers"] == ["688796"]


def test_corridor_shadow_pack_does_not_backfill_strict_release_from_primary_parallel(tmp_path: Path) -> None:
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "primary_validation_ticker": {
                "ticker": "300683",
                "validation_priority_rank": 1,
                "tractability_tier": "second_shadow_probe",
                "corridor_priority_rank": 1,
            },
            "parallel_watch_tickers": [
                {
                    "ticker": "301188",
                    "validation_priority_rank": 3,
                    "tractability_tier": "parallel_probe",
                    "corridor_priority_rank": 3,
                }
            ],
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert analysis["strict_release_status"] == "strict_release_unavailable"
    assert analysis["strict_release_tickers"] == []
    assert analysis["primary_shadow_replay"] == {}
    assert analysis["parallel_watch_lanes"] == []
    assert analysis["validation_only_tickers"] == []
    assert analysis["shadow_status"] != "ready_for_primary_shadow_replay"


def test_lane_pair_board_keeps_corridor_primary_first(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    governance_synthesis_path = tmp_path / "btst_governance_synthesis_latest.json"
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {
                "ticker": "300720",
                "mean_t_plus_2_return": 0.0787,
                "objective_fit_score": 1.0,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "tractability_tier": "second_shadow_probe",
            },
            "parallel_watch_lanes": [
                {
                    "ticker": "003036",
                    "mean_t_plus_2_return": 0.0823,
                    "objective_fit_score": 0.992,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "tractability_tier": "upstream_research_only",
                }
            ],
        },
    )
    _write_json(
        rebucket_comparison_bundle_path,
        {
            "priority_alignment_status": "divergent_top_lane",
            "rebucket_objective_row": {
                "ticker": "301292",
                "tickers": ["301292"],
                "mean_t_plus_2_return": 0.1098,
                "objective_fit_score": 0.9827,
                "t_plus_2_return_hit_rate_at_target": 0.7692,
                "t_plus_2_positive_rate": 0.9231,
                "prototype_readiness": "shadow_ready_rebucket_signal",
            },
        },
    )
    _write_json(
        governance_synthesis_path,
        {
            "execution_surface_constraints": [
                {
                    "constraint_id": "post_gate_shadow_observation_only",
                    "focus_tickers": ["300720"],
                    "status": "continuation_only_confirm_then_review",
                    "blocker": "no_selected_persistence_or_independent_edge",
                    "recommendation": "Keep post-gate shadow names in observation / continuation review until a selected row persists across independent windows.",
                },
                {
                    "constraint_id": "shadow_profitability_cliff_execution_block",
                    "focus_tickers": ["301292"],
                    "status": "shadow_recall_not_execution_ready",
                    "blocker": "profitability_hard_cliff_and_score_gap",
                    "recommendation": "Do not promote shadow recall names with profitability hard-cliff evidence into execution lanes; keep them in replay-input / shadow-governance diagnostics.",
                },
            ],
            "evidence_btst_followups": [
                {
                    "entries": [
                        {
                            "ticker": "300720",
                            "decision": "selected",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.88",
                                "confirmed_breakout",
                            ],
                            "historical_next_close_positive_rate": 0.0,
                            "historical_execution_quality_label": "intraday_only",
                            "historical_entry_timing_bias": "confirm_then_reduce",
                        },
                        {
                            "ticker": "003036",
                            "decision": "near_miss",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.86",
                                "profitability_hard_cliff",
                            ],
                            "historical_sample_count": 8,
                            "historical_next_close_positive_rate": 0.125,
                            "historical_next_close_return_mean": -0.0313,
                        },
                        {
                            "ticker": "301292",
                            "decision": "rejected",
                            "candidate_source": "post_gate_liquidity_competition_shadow",
                            "top_reasons": [
                                "trend_acceleration=0.81",
                                "profitability_hard_cliff",
                            ],
                            "historical_next_close_positive_rate": None,
                        },
                    ]
                }
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
        governance_synthesis_path=governance_synthesis_path,
    )

    assert analysis["pair_status"] == "ready_for_ranked_comparison"
    assert analysis["board_leader"]["ticker"] == "300720"
    assert analysis["board_leader"]["lane_family"] == "corridor"
    rows_by_ticker = {row["ticker"]: row for row in analysis["candidates"]}
    assert rows_by_ticker["300720"]["governance_status"] == "continuation_confirm_only_intraday_bias"
    assert rows_by_ticker["300720"]["governance_blocker"] == "weak_overnight_follow_through_after_shadow_recall"
    assert rows_by_ticker["300720"]["governance_execution_quality_label"] == "intraday_only"
    assert rows_by_ticker["300720"]["governance_entry_timing_bias"] == "confirm_then_reduce"
    assert rows_by_ticker["003036"]["governance_status"] == "parallel_watch_only_not_default_ready"
    assert "samples=8" in rows_by_ticker["003036"]["governance_summary"]
    assert "next_close_positive_rate=0.125" in rows_by_ticker["003036"]["governance_summary"]
    assert rows_by_ticker["301292"]["lane_family"] == "rebucket"
    assert rows_by_ticker["301292"]["governance_status"] == "shadow_recall_not_execution_ready"


def test_lane_pair_board_avoids_fake_rebucket_challenger_when_inactive(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    governance_synthesis_path = tmp_path / "btst_governance_synthesis_latest.json"
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {
                "ticker": "300720",
                "mean_t_plus_2_return": 0.0787,
                "objective_fit_score": 1.0,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "tractability_tier": "second_shadow_probe",
            },
            "parallel_watch_lanes": [],
        },
    )
    _write_json(
        rebucket_comparison_bundle_path,
        {
            "priority_alignment_status": "aligned_top_lane",
            "rebucket_objective_row": {},
        },
    )
    _write_json(governance_synthesis_path, {"execution_surface_constraints": [], "evidence_btst_followups": []})

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
        governance_synthesis_path=governance_synthesis_path,
    )

    assert analysis["comparison"]["rebucket_ticker"] is None
    assert "没有 active rebucket challenger" in analysis["recommendation"]
    assert any("没有 active rebucket challenger" in item for item in analysis["next_actions"])


def test_lane_pair_board_uses_upstream_handoff_overlay_when_governance_synthesis_is_unrelated(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    governance_synthesis_path = tmp_path / "btst_governance_synthesis_latest.json"
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {
                "ticker": "300720",
                "mean_t_plus_2_return": 0.0787,
                "objective_fit_score": 1.0,
                "t_plus_2_return_hit_rate_at_target": 0.8,
                "t_plus_2_positive_rate": 0.8667,
                "tractability_tier": "second_shadow_probe",
            },
            "parallel_watch_lanes": [
                {
                    "ticker": "003036",
                    "mean_t_plus_2_return": 0.0823,
                    "objective_fit_score": 0.992,
                    "t_plus_2_return_hit_rate_at_target": 0.7857,
                    "t_plus_2_positive_rate": 1.0,
                    "tractability_tier": "second_shadow_probe",
                }
            ],
        },
    )
    _write_json(
        rebucket_comparison_bundle_path,
        {
            "priority_alignment_status": "aligned_top_lane",
            "rebucket_objective_row": {},
        },
    )
    _write_json(governance_synthesis_path, {"execution_surface_constraints": [], "evidence_btst_followups": []})
    _write_json(
        upstream_handoff_board_path,
        {
            "board_rows": [
                {
                    "ticker": "300720",
                    "latest_followup_decision": "selected",
                    "latest_followup_candidate_source": "upstream_liquidity_corridor_shadow",
                    "latest_followup_historical_execution_quality_label": "intraday_only",
                    "latest_followup_historical_entry_timing_bias": "confirm_then_reduce",
                    "downstream_followup_status": "continuation_confirm_only_intraday_bias",
                    "downstream_followup_blocker": "weak_overnight_follow_through_after_shadow_recall",
                    "downstream_followup_summary": "300720 只适合作为 confirmation-only 的 intraday 机会，不应直接当成标准隔夜 BTST 持有。",
                },
                {
                    "ticker": "003036",
                    "latest_followup_decision": "near_miss",
                    "latest_followup_candidate_source": "upstream_liquidity_corridor_shadow",
                    "latest_followup_historical_sample_count": 8,
                    "latest_followup_historical_next_close_positive_rate": 0.125,
                    "latest_followup_historical_next_close_return_mean": -0.0313,
                    "downstream_followup_status": "parallel_watch_only_not_default_ready",
                    "downstream_followup_blocker": "profitability_hard_cliff_and_weak_same_source_payoff",
                    "downstream_followup_summary": "003036 只适合作为 corridor parallel watch，不应升格为默认 BTST promotion 语义。",
                },
            ]
        },
    )

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
        governance_synthesis_path=governance_synthesis_path,
        upstream_handoff_board_path=upstream_handoff_board_path,
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["candidates"]}
    assert rows_by_ticker["300720"]["governance_status"] == "continuation_confirm_only_intraday_bias"
    assert rows_by_ticker["300720"]["governance_execution_quality_label"] == "intraday_only"
    assert rows_by_ticker["300720"]["governance_entry_timing_bias"] == "confirm_then_reduce"
    assert rows_by_ticker["003036"]["governance_status"] == "parallel_watch_only_not_default_ready"
    assert "samples=8" in rows_by_ticker["003036"]["governance_summary"]
    assert "next_close_positive_rate=0.125" in rows_by_ticker["003036"]["governance_summary"]


def test_lane_pair_board_upgrades_corridor_primary_governance_when_shadow_recall_not_persistent(tmp_path: Path) -> None:
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    rebucket_comparison_bundle_path = tmp_path / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
    governance_synthesis_path = tmp_path / "btst_governance_synthesis_latest.json"
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "diagnostic_primary_shadow_replay_only",
            "primary_shadow_replay": {
                "ticker": "300683",
                "mean_t_plus_2_return": 0.1051,
                "objective_fit_score": 1.0,
                "t_plus_2_return_hit_rate_at_target": 0.75,
                "t_plus_2_positive_rate": 1.0,
                "tractability_tier": "second_shadow_probe",
            },
            "parallel_watch_lanes": [],
        },
    )
    _write_json(
        rebucket_comparison_bundle_path,
        {
            "priority_alignment_status": "aligned_top_lane",
            "rebucket_objective_row": {},
        },
    )
    _write_json(governance_synthesis_path, {"execution_surface_constraints": [], "evidence_btst_followups": []})
    _write_json(
        upstream_handoff_board_path,
        {
            "board_rows": [
                {
                    "ticker": "300683",
                    "latest_followup_decision": "rejected",
                    "latest_followup_candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_followup_status": "transient_probe_only",
                    "downstream_followup_blocker": "shadow_recall_not_persistent",
                    "downstream_followup_summary": "300683 的 shadow recall 不够持续，尚未达到第二个独立选中窗口。",
                },
            ]
        },
    )

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        corridor_shadow_pack_path,
        rebucket_comparison_bundle_path,
        governance_synthesis_path=governance_synthesis_path,
        upstream_handoff_board_path=upstream_handoff_board_path,
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["candidates"]}
    assert rows_by_ticker["300683"]["governance_blocker"] == "shadow_recall_not_persistent", (
        "governance_blocker should remain shadow_recall_not_persistent so corridor persistence dossier handles it correctly"
    )
    assert rows_by_ticker["300683"]["governance_status"] != "transient_probe_only", (
        "active corridor primary should not show transient_probe_only; expected corridor_primary_active_replay_pending"
    )
    assert rows_by_ticker["300683"]["governance_status"] == "corridor_primary_active_replay_pending", (
        "active corridor primary with shadow_recall_not_persistent history should be upgraded to corridor_primary_active_replay_pending"
    )


def test_upstream_handoff_board_prioritizes_watchlist_break_before_lane_probe(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        failure_dossier_path,
        {
            "top_upstream_absence_tickers": ["300720", "301292"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "300720",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_a",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
                {
                    "ticker": "301292",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_b",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
            ],
        },
    )
    _write_json(
        watchlist_dossier_path,
        {
            "focus_tickers": ["300720", "301292"],
            "priority_ticker_dossiers": [
                {"ticker": "300720", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "301292", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
            ],
        },
    )
    _write_json(
        recall_dossier_path,
        {
            "focus_tickers": ["300720", "301292"],
            "action_queue": [
                {
                    "ticker": "300720",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 878,
                        "avg_amount_share_of_cutoff_mean": 0.1573,
                        "avg_amount_share_of_min_gate_mean": 5.2437,
                        "profile_summary": "corridor profile",
                    },
                },
                {
                    "ticker": "301292",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "post_gate_liquidity_competition",
                        "min_rank_gap_to_cutoff": 309,
                        "avg_amount_share_of_cutoff_mean": 0.4421,
                        "avg_amount_share_of_min_gate_mean": 14.736,
                        "profile_summary": "rebucket profile",
                    },
                },
            ],
            "priority_handoff_branch_experiment_queue": [
                {"task_id": "corridor_probe", "tickers": ["300720"], "prototype_readiness": "shadow_ready_large_gap", "prototype_type": "upstream_base_liquidity_uplift_probe"},
                {
                    "task_id": "rebucket_probe",
                    "tickers": ["301292"],
                    "prototype_readiness": "shadow_ready_rebucket_signal",
                    "prototype_type": "post_gate_competition_rebucket_probe",
                    "selective_exemption_readiness": "shadow_only_large_remaining_rank_gap",
                    "selective_exemption_summary": "rebucket 后剩余 rank gap 仍高于 300，只保留 shadow probe，不进入 selective exemption review。",
                },
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    assert analysis["board_status"] == "ready_for_upstream_handoff_execution"
    assert analysis["board_rows"][0]["ticker"] == "300720"
    assert analysis["board_rows"][0]["first_broken_handoff"] == "absent_from_watchlist"
    assert analysis["board_rows"][0]["corridor_uplift_bucket"] == "standard_corridor_uplift"
    assert analysis["board_rows"][0]["prototype_task_id"] == "corridor_probe"
    assert any("run_btst_candidate_pool_corridor_uplift_runbook.py" in command for command in analysis["board_rows"][0]["recommended_commands"])
    assert any("run_btst_candidate_pool_rebucket_shadow_pack.py" in command for command in analysis["board_rows"][1]["recommended_commands"])
    assert analysis["board_rows"][1]["selective_exemption_readiness"] == "shadow_only_large_remaining_rank_gap"


def test_upstream_handoff_board_overlays_latest_shadow_followup_validation(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"

    _write_json(
        failure_dossier_path,
        {
            "top_upstream_absence_tickers": ["300720", "003036", "301292"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "300720",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_a",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
                {
                    "ticker": "003036",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_b",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
                {
                    "ticker": "301292",
                    "primary_failure_class": "upstream_absent_from_replay_inputs",
                    "handoff_stage": "absent_from_watchlist",
                    "primary_report_dir": "report_c",
                    "replay_input_visible_report_count": 0,
                    "watchlist_visible_report_count": 0,
                    "failure_reason": "missing before watchlist",
                    "next_step": "trace replay input",
                },
            ],
        },
    )
    _write_json(
        watchlist_dossier_path,
        {
            "focus_tickers": ["300720", "003036", "301292"],
            "priority_ticker_dossiers": [
                {"ticker": "300720", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "003036", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "301292", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
            ],
        },
    )
    _write_json(
        recall_dossier_path,
        {
            "focus_tickers": ["300720", "003036", "301292"],
            "action_queue": [
                {
                    "ticker": "300720",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 878,
                        "avg_amount_share_of_cutoff_mean": 0.1573,
                        "avg_amount_share_of_min_gate_mean": 5.2437,
                        "profile_summary": "corridor profile",
                    },
                },
                {
                    "ticker": "003036",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 644,
                        "avg_amount_share_of_cutoff_mean": 0.2214,
                        "avg_amount_share_of_min_gate_mean": 4.8831,
                        "profile_summary": "corridor profile",
                    },
                },
                {
                    "ticker": "301292",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "post_gate_liquidity_competition",
                        "min_rank_gap_to_cutoff": 309,
                        "avg_amount_share_of_cutoff_mean": 0.4421,
                        "avg_amount_share_of_min_gate_mean": 14.736,
                        "profile_summary": "rebucket profile",
                    },
                },
            ],
            "priority_handoff_branch_experiment_queue": [
                {"task_id": "corridor_probe", "tickers": ["300720", "003036"], "prototype_readiness": "shadow_ready_large_gap", "prototype_type": "upstream_base_liquidity_uplift_probe"},
                {
                    "task_id": "rebucket_probe",
                    "tickers": ["301292"],
                    "prototype_readiness": "shadow_ready_rebucket_signal",
                    "prototype_type": "post_gate_competition_rebucket_probe",
                    "selective_exemption_readiness": "shadow_only_large_remaining_rank_gap",
                    "selective_exemption_summary": "rebucket 后剩余 rank gap 仍高于 300，只保留 shadow probe，不进入 selective exemption review。",
                },
            ],
        },
    )

    followup_report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only_shadow_followup"
    followup_report_dir.mkdir(parents=True, exist_ok=True)
    followup_brief_path = followup_report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        followup_brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720", "003036"]},
            "priority_rows": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_catalyst_relief_applied"],
                    "top_reasons": ["upstream_shadow_catalyst_relief"],
                },
                {
                    "ticker": "003036",
                    "decision": "rejected",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "top_reasons": ["profitability_hard_cliff"],
                    "historical_prior": {
                        "sample_count": 8,
                        "next_close_positive_rate": 0.125,
                        "next_close_return_mean": -0.0313,
                    },
                },
            ],
        },
    )
    _write_json(
        followup_report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-31",
                "brief_json": str(followup_brief_path.resolve()),
            },
        },
    )

    rebucket_report_dir = tmp_path / "paper_trading_20260324_20260326_live_m2_7_short_trade_only_rebucket_shadow_301292"
    rebucket_report_dir.mkdir(parents=True, exist_ok=True)
    rebucket_brief_path = rebucket_report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        rebucket_brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["301292"]},
            "priority_rows": [
                {
                    "ticker": "301292",
                    "decision": "rejected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_release_candidate"],
                    "top_reasons": ["profitability_hard_cliff", "score_short_below_threshold"],
                }
            ],
        },
    )
    _write_json(
        rebucket_report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-24",
                "brief_json": str(rebucket_brief_path.resolve()),
            },
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["board_rows"]}
    assert analysis["board_status"] == "mixed_upstream_and_post_recall_followup"
    assert rows_by_ticker["300720"]["board_phase"] == "post_recall_downstream_followup"
    assert rows_by_ticker["300720"]["first_broken_handoff"] == "downstream_validated_after_shadow_recall"
    assert rows_by_ticker["300720"]["latest_followup_decision"] == "near_miss"
    assert rows_by_ticker["300720"]["downstream_followup_lane"] == "t_plus_2_continuation_review"
    assert rows_by_ticker["300720"]["downstream_followup_status"] == "continuation_confirm_then_review"
    assert rows_by_ticker["003036"]["latest_followup_downstream_bottleneck"] == "profitability_hard_cliff"
    assert rows_by_ticker["003036"]["latest_followup_historical_sample_count"] == 8
    assert rows_by_ticker["003036"]["latest_followup_historical_next_close_positive_rate"] == 0.125
    assert rows_by_ticker["003036"]["latest_followup_historical_next_close_return_mean"] == -0.0313
    assert rows_by_ticker["003036"]["downstream_followup_lane"] == "shadow_profitability_diagnostics"
    assert rows_by_ticker["301292"]["board_phase"] == "historical_shadow_probe_gap"
    assert rows_by_ticker["301292"]["first_broken_handoff"] == "transient_shadow_recall_without_persistence"
    assert rows_by_ticker["301292"]["latest_followup_decision"] == "rejected"
    assert rows_by_ticker["301292"]["downstream_followup_lane"] == "rebucket_persistence_diagnostics"
    assert rows_by_ticker["301292"]["downstream_followup_status"] == "transient_probe_only"
    assert rows_by_ticker["301292"]["downstream_followup_blocker"] == "shadow_recall_not_persistent"
    assert rows_by_ticker["301292"]["selective_exemption_readiness"] == "shadow_only_large_remaining_rank_gap"
    assert "不进入 selective exemption review" in rows_by_ticker["301292"]["next_step"]
    assert "301292" in analysis["recommendation"]


def test_analyze_btst_candidate_pool_upstream_handoff_board_respects_corridor_split_buckets(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    _write_json(
        failure_dossier_path,
        {
            "top_upstream_absence_tickers": ["301188", "300683", "688796"],
            "priority_ticker_dossiers": [
                {"ticker": "301188", "handoff_stage": "absent_from_watchlist", "primary_failure_class": "upstream_absent_from_replay_inputs", "replay_input_visible_report_count": 0, "watchlist_visible_report_count": 0},
                {"ticker": "300683", "handoff_stage": "absent_from_watchlist", "primary_failure_class": "upstream_absent_from_replay_inputs", "replay_input_visible_report_count": 0, "watchlist_visible_report_count": 0},
                {"ticker": "688796", "handoff_stage": "absent_from_watchlist", "primary_failure_class": "upstream_absent_from_replay_inputs", "replay_input_visible_report_count": 0, "watchlist_visible_report_count": 0},
            ],
        },
    )
    _write_json(
        watchlist_dossier_path,
        {
            "focus_tickers": ["301188", "300683", "688796"],
            "priority_ticker_dossiers": [
                {"ticker": "301188", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "300683", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
                {"ticker": "688796", "dominant_recall_stage": "absent_from_candidate_pool", "candidate_pool_visible_count": 0, "layer_b_visible_count": 0},
            ],
        },
    )
    _write_json(
        recall_dossier_path,
        {
            "focus_tickers": ["301188", "300683", "688796"],
            "action_queue": [
                {
                    "ticker": "301188",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 2809,
                        "avg_amount_share_of_cutoff_mean": 0.0709,
                        "avg_amount_share_of_min_gate_mean": 2.6,
                        "profile_summary": "deepest corridor",
                    },
                },
                {
                    "ticker": "300683",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 1599,
                        "avg_amount_share_of_cutoff_mean": 0.1519,
                        "avg_amount_share_of_min_gate_mean": 5.0386,
                        "profile_summary": "standard corridor",
                    },
                },
                {
                    "ticker": "688796",
                    "dominant_blocking_stage": "candidate_pool_truncated_after_filters",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "min_rank_gap_to_cutoff": 2561,
                        "avg_amount_share_of_cutoff_mean": 0.0789,
                        "avg_amount_share_of_min_gate_mean": 2.6142,
                        "profile_summary": "excluded low-gate tail",
                    },
                },
            ],
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "corridor_probe",
                    "tickers": ["301188", "300683", "688796"],
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "prototype_summary": "corridor uplift summary",
                }
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["board_rows"]}
    assert rows_by_ticker["301188"]["corridor_uplift_bucket"] == "deepest_corridor_focus"
    assert rows_by_ticker["300683"]["corridor_uplift_bucket"] == "standard_corridor_uplift"
    assert rows_by_ticker["688796"]["corridor_uplift_bucket"] == "excluded_low_gate_tail"
    assert any("run_btst_candidate_pool_corridor_uplift_runbook.py" in command for command in rows_by_ticker["301188"]["recommended_commands"])
    assert any("run_btst_candidate_pool_corridor_uplift_runbook.py" in command for command in rows_by_ticker["300683"]["recommended_commands"])
    assert not any("run_btst_candidate_pool_corridor_uplift_runbook.py" in command for command in rows_by_ticker["688796"]["recommended_commands"])
    assert "不进入 retained deepest corridor shadow pack" in rows_by_ticker["688796"]["next_step"]


def test_analyze_btst_candidate_pool_upstream_handoff_board_keeps_selected_post_recall_followup_in_continuation_lane(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    _write_json(
        failure_dossier_path,
        {
            "focus_tickers": ["300720"],
            "failure_rows": [
                {
                    "ticker": "300720",
                    "first_broken_handoff": "absent_from_watchlist",
                    "watchlist_recall_stage": "absent_from_candidate_pool",
                    "candidate_pool_blocking_stage": "candidate_pool_truncated_after_filters",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "primary_report_dir": "paper_trading_20260302_20260313_btst_research_replay",
                    "candidate_pool_rank_gap_min": 878,
                    "avg_amount_share_of_cutoff_mean": 0.1573,
                    "avg_amount_share_of_min_gate_mean": 5.2437,
                    "profile_summary": "corridor profile",
                }
            ],
            "priority_handoff_branch_experiment_queue": [],
        },
    )
    _write_json(watchlist_dossier_path, {"reports_root": str(tmp_path), "focus_tickers": ["300720"], "recall_rows": []})
    _write_json(recall_dossier_path, {"reports_root": str(tmp_path), "focus_tickers": ["300720"], "recall_rows": []})

    report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only_selected_300720"
    report_dir.mkdir(parents=True, exist_ok=True)
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720"]},
            "priority_rows": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "top_reasons": ["upstream_shadow_catalyst_relief", "confirmed_breakout"],
                    "score_target": 0.4584,
                }
            ],
        },
    )
    _write_json(
        report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-03-31",
                "brief_json": str(brief_path.resolve()),
            },
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    row = next(item for item in analysis["board_rows"] if item["ticker"] == "300720")
    assert row["latest_followup_decision"] == "selected"
    assert row["downstream_followup_lane"] == "t_plus_2_continuation_review"
    assert row["downstream_followup_status"] == "continuation_only_confirm_then_review"
    assert row["downstream_followup_blocker"] == "no_selected_persistence_or_independent_edge"


def test_analyze_btst_candidate_pool_upstream_handoff_board_maps_blocked_shadow_followup_to_formal_execution_removal(tmp_path: Path) -> None:
    failure_dossier_path = tmp_path / "btst_no_candidate_entry_failure_dossier_latest.json"
    watchlist_dossier_path = tmp_path / "btst_watchlist_recall_dossier_latest.json"
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    _write_json(
        failure_dossier_path,
        {
            "focus_tickers": ["300720"],
            "failure_rows": [
                {
                    "ticker": "300720",
                    "first_broken_handoff": "absent_from_watchlist",
                    "watchlist_recall_stage": "absent_from_candidate_pool",
                    "candidate_pool_blocking_stage": "candidate_pool_truncated_after_filters",
                    "priority_handoff": "post_gate_liquidity_competition",
                    "prototype_task_id": "post_gate_liquidity_competition_shadow_probe",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "shadow_probe",
                    "primary_report_dir": "paper_trading_20260429_blocked_truth",
                    "candidate_pool_rank_gap_min": 8,
                    "avg_amount_share_of_cutoff_mean": 0.91,
                    "avg_amount_share_of_min_gate_mean": 1.12,
                    "profile_summary": "shadow recall gap still visible before blocked truth lands.",
                }
            ],
            "priority_handoff_branch_experiment_queue": [],
        },
    )
    _write_json(watchlist_dossier_path, {"reports_root": str(tmp_path), "focus_tickers": ["300720"], "recall_rows": []})
    _write_json(recall_dossier_path, {"reports_root": str(tmp_path), "focus_tickers": ["300720"], "recall_rows": []})

    report_dir = tmp_path / "paper_trading_20260429_blocked_truth"
    report_dir.mkdir(parents=True, exist_ok=True)
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        brief_path,
        {
            "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720"]},
            "priority_rows": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "positive_tags": ["upstream_shadow_release_candidate"],
                    "top_reasons": ["halt_gate_active"],
                    "p2_execution_blocked": True,
                }
            ],
        },
    )
    _write_json(
        report_dir / "session_summary.json",
        {
            "plan_generation": {"selection_target": "short_trade_only"},
            "btst_followup": {
                "trade_date": "2026-04-29",
                "brief_json": str(brief_path.resolve()),
            },
        },
    )

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        failure_dossier_path,
        watchlist_recall_dossier_path=watchlist_dossier_path,
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    row = next(item for item in analysis["board_rows"] if item["ticker"] == "300720")
    assert row["board_phase"] == "post_recall_downstream_followup"
    assert row["first_broken_handoff"] == "downstream_validated_after_shadow_recall"
    assert row["latest_followup_decision"] == "blocked"
    assert row["downstream_followup_lane"] == "formal_execution_removal"
    assert row["downstream_followup_status"] == "remove_from_formal_execution"
    assert row["downstream_followup_blocker"] == "blocked_truth_halt_block_prior_gate"
    assert "formal execution 名单移除" in row["downstream_followup_summary"]
    assert "不再重复 upstream recall probe" in row["next_step"]


def test_corridor_uplift_runbook_keeps_corridor_first_and_parallel_confirmatory(tmp_path: Path) -> None:
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                    "uplift_to_cutoff_multiple_min": 3.4211,
                    "target_cutoff_avg_amount_20d_mean": 166904.4837,
                    "prototype_summary": "run uplift probe",
                    "evaluation_summary": "measure uplift before cutoff tuning",
                    "guardrail_summary": "do not rewrite as cutoff tuning",
                    "why_now": "large liquidity wall remains",
                    "success_signal": "compress nearest frontier multiple",
                }
            ]
        },
    )
    _write_json(
        corridor_shadow_pack_path,
        {
            "primary_shadow_replay": {"ticker": "300720"},
            "parallel_watch_lanes": [{"ticker": "003036"}],
            "success_criteria": ["keep primary above tradeable surface"],
            "guardrails": ["no default cutoff tuning"],
        },
    )
    _write_json(
        lane_pair_board_path,
        {
            "board_leader": {"ticker": "300720", "lane_family": "corridor"},
        },
    )
    _write_json(
        tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json",
        {
            "excluded_low_gate_tail_tickers": ["688796"],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
        corridor_narrow_probe_path=tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json",
    )

    assert analysis["runbook_status"] == "ready_for_upstream_uplift_probe"
    assert analysis["primary_shadow_replay"] == "300720"
    assert analysis["parallel_watch_tickers"] == ["003036"]
    assert analysis["excluded_low_gate_tail_tickers"] == ["688796"]
    assert analysis["leader_lane_family"] == "corridor"
    assert any("run_btst_candidate_pool_lane_pair_board.py" in command for command in analysis["execution_commands"])
    paper_trading_commands = [command for command in analysis["execution_commands"] if "run_paper_trading.py" in command]
    assert paper_trading_commands
    assert "--candidate-pool-shadow-focus-tickers 300720,003036" in paper_trading_commands[0]
    assert "--candidate-pool-shadow-corridor-focus-tickers 300720,003036" in paper_trading_commands[0]
    assert any("excluded low-gate tail" in step for step in analysis["execution_steps"])


def test_corridor_uplift_runbook_upgrades_to_promotion_candidate_when_validation_pack_is_ready(tmp_path: Path) -> None:
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 4.103,
                    "uplift_to_cutoff_multiple_min": 2.4211,
                    "target_cutoff_avg_amount_20d_mean": 166904.4837,
                    "prototype_summary": "run uplift probe",
                    "evaluation_summary": "measure uplift before cutoff tuning",
                    "guardrail_summary": "do not rewrite as cutoff tuning",
                    "why_now": "closed-cycle evidence improved",
                    "success_signal": "compress nearest frontier multiple",
                }
            ]
        },
    )
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "promotion_readiness_status": "corridor_promotion_candidate_ready",
            "recommendation": "300720 已进入 promotion-candidate 强证据区间。",
        },
    )
    _write_json(
        corridor_shadow_pack_path,
        {
            "primary_shadow_replay": {"ticker": "300720"},
            "parallel_watch_lanes": [{"ticker": "003036"}],
            "success_criteria": ["keep primary above tradeable surface"],
            "guardrails": ["no default cutoff tuning"],
        },
    )
    _write_json(
        lane_pair_board_path,
        {
            "board_leader": {"ticker": "300720", "lane_family": "corridor"},
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_validation_pack_path=corridor_validation_pack_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    assert analysis["runbook_status"] == "ready_for_corridor_promotion_candidate"
    assert analysis["promotion_readiness_status"] == "corridor_promotion_candidate_ready"
    assert any("promotion-candidate review" in step for step in analysis["execution_steps"])
    assert any("promotion-candidate review" in criterion for criterion in analysis["success_criteria"])
    assert any("promotion-candidate review" in guardrail for guardrail in analysis["guardrails"])


def test_corridor_uplift_runbook_keeps_evidence_only_when_validation_pack_is_not_ready(tmp_path: Path) -> None:
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                    "uplift_to_cutoff_multiple_min": 3.4211,
                    "target_cutoff_avg_amount_20d_mean": 166904.4837,
                    "prototype_summary": "run uplift probe",
                    "evaluation_summary": "measure uplift before cutoff tuning",
                    "guardrail_summary": "do not rewrite as cutoff tuning",
                    "why_now": "large liquidity wall remains",
                    "success_signal": "compress nearest frontier multiple",
                }
            ]
        },
    )
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "accumulate_more_corridor_evidence",
            "promotion_readiness_status": "corridor_shadow_probe_ready",
            "recommendation": "corridor lane 仍需更多 closed-cycle 支持。",
        },
    )
    _write_json(
        corridor_shadow_pack_path,
        {
            "primary_shadow_replay": {"ticker": "300720"},
            "parallel_watch_lanes": [{"ticker": "003036"}],
            "success_criteria": ["keep primary above tradeable surface"],
            "guardrails": ["no default cutoff tuning"],
        },
    )
    _write_json(
        lane_pair_board_path,
        {
            "board_leader": {"ticker": "300720", "lane_family": "corridor"},
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_validation_pack_path=corridor_validation_pack_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    assert analysis["runbook_status"] == "accumulate_more_corridor_evidence"
    assert analysis["promotion_readiness_status"] == "corridor_shadow_probe_ready"
    assert any("closed-cycle accumulation" in step for step in analysis["execution_steps"])


def test_corridor_shadow_pack_keeps_diagnostic_primary_replay_when_dossier_shows_recall_not_persistent(tmp_path: Path) -> None:
    """Persistence blocker should still hard-gate strict release, but keep the active primary in diagnostic replay."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                    "closed_cycle_count": 4,
                    "mean_t_plus_2_return": 0.0577,
                    "t_plus_2_return_hit_rate_at_target": 0.75,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.9719,
                    "uplift_to_cutoff_multiple_mean": 6.4288,
                }
            ],
            "strict_release_tickers": ["300683"],
        },
    )
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {
                "governance_status": "transient_probe_only",
                "governance_blocker": "shadow_recall_not_persistent",
                "current_decision": "rejected",
            },
            "verdict": "await_second_independent_selected_window",
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    # The persistence gate must override the validation pack's optimistic strict-release status,
    # while preserving the active primary for diagnostic shadow replay.
    assert analysis["strict_release_status"] == "strict_release_blocked_by_persistence", (
        f"Expected strict_release_blocked_by_persistence but got {analysis['strict_release_status']!r}"
    )
    assert analysis["shadow_status"] == "diagnostic_primary_shadow_replay_only", (
        f"Expected diagnostic_primary_shadow_replay_only but got {analysis['shadow_status']!r}"
    )
    assert analysis.get("strict_release_tickers", []) == [], (
        f"strict_release_tickers must be empty when persistence gate fires, got {analysis.get('strict_release_tickers', [])!r}"
    )
    assert analysis["primary_shadow_replay"].get("ticker") == "300683", (
        "300683 should remain the diagnostic primary shadow replay while persistence is still under-sampled"
    )
    assert analysis["shadow_replay_commands"], "diagnostic replay should still emit shadow replay refresh commands"
    assert any("run_btst_candidate_pool_corridor_shadow_pack.py" in command for command in analysis["shadow_replay_commands"]), (
        f"Expected a shadow-pack refresh command in shadow_replay_commands, got {analysis['shadow_replay_commands']!r}"
    )


def test_corridor_shadow_pack_not_blocked_by_persistence_gate_when_dossier_verdict_is_merge_ready(tmp_path: Path) -> None:
    """If persistence dossier says corridor_merge_review_probe_ready, strict_release_status must pass through unchanged."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                    "closed_cycle_count": 8,
                    "mean_t_plus_2_return": 0.0577,
                    "t_plus_2_return_hit_rate_at_target": 0.75,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.9719,
                    "uplift_to_cutoff_multiple_mean": 6.4288,
                }
            ],
            "strict_release_tickers": ["300683"],
        },
    )
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {
                "governance_status": "continuation_only_confirm_then_review",
                "governance_blocker": None,
                "current_decision": "selected",
            },
            "verdict": "corridor_merge_review_probe_ready",
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    # No persistence blocker — status must pass through from validation pack.
    assert analysis["strict_release_status"] == "strict_release_ready", (
        f"Expected strict_release_ready but got {analysis['strict_release_status']!r}"
    )


def test_corridor_shadow_pack_refresh_commands_include_persistence_dossier_path(tmp_path: Path) -> None:
    """refresh_commands must carry --persistence-dossier-path so re-running the shadow pack cannot bypass the gate."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(corridor_validation_pack_path, {"pack_status": "parallel_probe_ready"})
    _write_json(persistence_dossier_path, {"focus_ticker": "300683", "verdict": "corridor_merge_review_probe_ready"})

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    shadow_pack_cmds = [cmd for cmd in analysis["refresh_commands"] if "run_btst_candidate_pool_corridor_shadow_pack.py" in cmd]
    assert shadow_pack_cmds, "No shadow pack refresh command found in refresh_commands"
    assert any("--persistence-dossier-path" in cmd for cmd in shadow_pack_cmds), (
        f"Expected --persistence-dossier-path in shadow pack refresh command, got: {shadow_pack_cmds}"
    )


def test_corridor_shadow_pack_shadow_replay_commands_include_persistence_dossier_path(tmp_path: Path) -> None:
    """shadow_replay_commands must carry --persistence-dossier-path so replays cannot bypass the gate."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_candidates": [
                {"ticker": "300683", "tractability_tier": "second_shadow_probe"},
                {"ticker": "300720", "tractability_tier": "second_shadow_probe"},
            ],
        },
    )
    _write_json(persistence_dossier_path, {"focus_ticker": "300683", "verdict": "corridor_merge_review_probe_ready"})

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    assert analysis["shadow_replay_commands"], "Expected non-empty shadow_replay_commands"
    assert any("--persistence-dossier-path" in cmd for cmd in analysis["shadow_replay_commands"]), (
        f"Expected --persistence-dossier-path in shadow_replay_commands, got: {analysis['shadow_replay_commands']}"
    )


def test_corridor_shadow_pack_cli_accepts_and_passes_persistence_dossier_path(tmp_path: Path) -> None:
    """The script CLI must accept --persistence-dossier-path and wire it to the analysis function."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
    output_json = tmp_path / "output.json"
    output_md = tmp_path / "output.md"

    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {"ticker": "300683", "tractability_tier": "second_shadow_probe", "corridor_priority_rank": 1}
            ],
            "strict_release_tickers": ["300683"],
        },
    )
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {"governance_blocker": "shadow_recall_not_persistent"},
            "verdict": "await_second_independent_selected_window",
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_btst_candidate_pool_corridor_shadow_pack.py",
            "--corridor-validation-pack-path", str(corridor_validation_pack_path),
            "--persistence-dossier-path", str(persistence_dossier_path),
            "--output-json", str(output_json),
            "--output-md", str(output_md),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0, f"CLI exited non-zero: {result.stderr}"
    analysis = json.loads(output_json.read_text())
    assert analysis["strict_release_status"] == "strict_release_blocked_by_persistence", (
        f"Persistence gate must fire via CLI --persistence-dossier-path, got: {analysis['strict_release_status']!r}"
    )


def test_corridor_uplift_runbook_execution_commands_include_persistence_dossier_path(tmp_path: Path) -> None:
    """execution_commands emitted by the uplift runbook must include --persistence-dossier-path in the shadow pack step."""
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(corridor_shadow_pack_path, {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []})
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})
    _write_json(persistence_dossier_path, {"focus_ticker": "300720", "verdict": "corridor_merge_review_probe_ready"})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    shadow_pack_cmds = [cmd for cmd in analysis["execution_commands"] if "run_btst_candidate_pool_corridor_shadow_pack.py" in cmd]
    assert shadow_pack_cmds, "No shadow pack command found in execution_commands"
    assert any("--persistence-dossier-path" in cmd for cmd in shadow_pack_cmds), (
        f"Expected --persistence-dossier-path in shadow pack execution command, got: {shadow_pack_cmds}"
    )


def test_corridor_uplift_runbook_execution_commands_uplift_runbook_step_includes_persistence_dossier_path(tmp_path: Path) -> None:
    """The uplift-runbook step in execution_commands must carry --persistence-dossier-path so re-running it cannot bypass the gate."""
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(corridor_shadow_pack_path, {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []})
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})
    _write_json(persistence_dossier_path, {"focus_ticker": "300720", "verdict": "corridor_merge_review_probe_ready"})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    uplift_cmds = [cmd for cmd in analysis["execution_commands"] if "run_btst_candidate_pool_corridor_uplift_runbook.py" in cmd]
    assert uplift_cmds, "No uplift runbook command found in execution_commands"
    assert any("--persistence-dossier-path" in cmd for cmd in uplift_cmds), (
        f"Expected --persistence-dossier-path in uplift runbook execution command, got: {uplift_cmds}"
    )


def test_corridor_uplift_runbook_fallback_shadow_pack_passes_persistence_dossier_path(tmp_path: Path) -> None:
    """When corridor_shadow_pack_path is missing/empty and the fallback regeneration runs,
    it must pass persistence_dossier_path to analyze_btst_candidate_pool_corridor_shadow_pack."""
    import unittest.mock

    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
    # corridor_shadow_pack_path intentionally omitted so fallback triggers

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})
    _write_json(persistence_dossier_path, {"focus_ticker": "300720", "verdict": "corridor_merge_review_probe_ready"})

    fake_shadow_pack = {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []}

    with unittest.mock.patch(
        "scripts.run_btst_candidate_pool_corridor_uplift_runbook.analyze_btst_candidate_pool_corridor_shadow_pack",
        return_value=fake_shadow_pack,
    ) as mock_shadow_pack:
        analyze_btst_candidate_pool_corridor_uplift_runbook(
            recall_dossier_path,
            corridor_shadow_pack_path=None,
            lane_pair_board_path=lane_pair_board_path,
            persistence_dossier_path=persistence_dossier_path,
        )

    assert mock_shadow_pack.called, "analyze_btst_candidate_pool_corridor_shadow_pack was not called (fallback not triggered)"
    _, call_kwargs = mock_shadow_pack.call_args
    assert "persistence_dossier_path" in call_kwargs, (
        f"Fallback call to analyze_btst_candidate_pool_corridor_shadow_pack must pass persistence_dossier_path, "
        f"got kwargs: {call_kwargs}"
    )
    assert call_kwargs["persistence_dossier_path"] == persistence_dossier_path, (
        f"persistence_dossier_path passed to fallback must match the one provided to the runbook, "
        f"got: {call_kwargs['persistence_dossier_path']!r}"
    )


def test_corridor_shadow_pack_script_has_sys_path_bootstrap_for_direct_cli_execution() -> None:
    """The script must self-bootstrap sys.path so 'python scripts/run_btst_candidate_pool_corridor_shadow_pack.py'
    works from repo root without relying on the editable-install .pth in site-packages.

    Regression: without sys.path.insert the script crashes at import time with
    ModuleNotFoundError: No module named 'scripts.run_btst_candidate_pool_corridor_validation_pack'
    when invoked via any Python that lacks the editable-install .pth (system Python, CI, etc.).
    """
    source = Path("scripts/run_btst_candidate_pool_corridor_shadow_pack.py").read_text()
    assert "sys.path.insert" in source, (
        "Script is missing sys.path.insert bootstrap. "
        "Direct CLI execution 'python scripts/run_btst_candidate_pool_corridor_shadow_pack.py' "
        "fails with ModuleNotFoundError on any Python without the venv editable-install .pth. "
        "Add: sys.path.insert(0, str(Path(__file__).resolve().parent.parent)) "
        "before any 'from scripts.' import."
    )


def test_corridor_shadow_pack_script_direct_cli_execution_works() -> None:
    """The shadow-pack script must self-bootstrap sys.path so
    'python scripts/run_btst_candidate_pool_corridor_shadow_pack.py --help'
    succeeds without relying on the venv's editable-install .pth file.

    Regression: without sys.path.insert the script crashes at import time with
    ModuleNotFoundError when invoked directly (e.g., via the command emitted in refresh_commands).

    The test simulates a no-.pth environment by passing -S (skip site-packages / .pth files)
    and providing the venv site-packages directory via PYTHONPATH so that third-party
    dependencies are still available.  Under these conditions only the script's own
    sys.path.insert can resolve the 'scripts.*' / 'src.*' package roots, so a missing
    bootstrap will produce ModuleNotFoundError and a non-zero exit code.
    """
    import os

    repo_root = Path(__file__).resolve().parent.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
    venv_site = repo_root / ".venv" / "lib"
    site_dirs = sorted(venv_site.glob("python3.*/site-packages")) if venv_site.exists() else []
    env = {**os.environ, "PYTHONPATH": str(site_dirs[0]) if site_dirs else ""}

    result = subprocess.run(
        [str(venv_python), "-S", "scripts/run_btst_candidate_pool_corridor_shadow_pack.py", "--help"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Direct CLI execution of scripts/run_btst_candidate_pool_corridor_shadow_pack.py --help "
        "failed in a no-.pth environment.  This usually means the sys.path bootstrap is missing or broken.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower(), (
        "Expected argparse usage text in output of --help invocation, "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_corridor_shadow_pack_persistence_gate_with_multiple_candidates_keeps_blocked_primary_as_diagnostic_replay(tmp_path: Path) -> None:
    """Persistence gating must keep the blocked primary as diagnostic replay without promoting the secondary."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    # Two strict-release candidates: primary=300683 (will be blocked), secondary=300720.
    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                    "closed_cycle_count": 4,
                    "mean_t_plus_2_return": 0.057,
                    "t_plus_2_return_hit_rate_at_target": 0.75,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.97,
                    "uplift_to_cutoff_multiple_mean": 6.4,
                },
                {
                    "ticker": "300720",
                    "validation_priority_rank": 2,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 2,
                    "closed_cycle_count": 3,
                    "mean_t_plus_2_return": 0.045,
                    "t_plus_2_return_hit_rate_at_target": 0.67,
                    "t_plus_2_positive_rate": 0.9,
                    "objective_fit_score": 0.88,
                    "uplift_to_cutoff_multiple_mean": 5.1,
                },
            ],
            "strict_release_tickers": ["300683", "300720"],
        },
    )
    # Persistence dossier gates 300683 (the active primary).
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {
                "governance_status": "transient_probe_only",
                "governance_blocker": "shadow_recall_not_persistent",
                "current_decision": "rejected",
            },
            "verdict": "await_second_independent_selected_window",
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    assert analysis["strict_release_status"] == "strict_release_blocked_by_persistence", (
        f"Expected strict_release_blocked_by_persistence but got {analysis['strict_release_status']!r}"
    )
    assert analysis["shadow_status"] == "diagnostic_primary_shadow_replay_only", (
        f"Expected diagnostic_primary_shadow_replay_only but got {analysis['shadow_status']!r}"
    )
    assert analysis["primary_shadow_replay"].get("ticker") == "300683", (
        "300683 should remain the diagnostic primary shadow replay when persistence is still under-sampled"
    )
    assert analysis["shadow_replay_commands"], "diagnostic replay should still emit replay refresh commands"
    assert "300720" not in json.dumps(analysis["primary_shadow_replay"], ensure_ascii=False), (
        f"300720 must NOT be silently promoted as secondary-becomes-primary, got {analysis['primary_shadow_replay']!r}"
    )


def test_corridor_shadow_pack_diagnostic_primary_replay_next_step_mentions_replay_but_keeps_release_blocked(tmp_path: Path) -> None:
    """Diagnostic replay next_step should keep replay guidance while stating strict release remains blocked."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        corridor_validation_pack_path,
        {
            "pack_status": "parallel_probe_ready",
            "strict_release_status": "strict_release_ready",
            "strict_release_candidates": [
                {
                    "ticker": "300683",
                    "validation_priority_rank": 1,
                    "tractability_tier": "second_shadow_probe",
                    "corridor_priority_rank": 1,
                    "closed_cycle_count": 4,
                    "mean_t_plus_2_return": 0.0577,
                    "t_plus_2_return_hit_rate_at_target": 0.75,
                    "t_plus_2_positive_rate": 1.0,
                    "objective_fit_score": 0.9719,
                    "uplift_to_cutoff_multiple_mean": 6.4288,
                }
            ],
            "strict_release_tickers": ["300683"],
        },
    )
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {
                "governance_status": "transient_probe_only",
                "governance_blocker": "shadow_recall_not_persistent",
                "current_decision": "rejected",
            },
            "verdict": "await_second_independent_selected_window",
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(
        corridor_validation_pack_path,
        persistence_dossier_path=persistence_dossier_path,
    )

    assert analysis["shadow_status"] == "diagnostic_primary_shadow_replay_only"
    next_step = analysis.get("next_step") or ""
    assert "保持" in next_step and "shadow replay" in next_step.lower(), (
        f"next_step should preserve active replay guidance for diagnostic sampling, got: {next_step!r}"
    )
    assert "strict release" in next_step.lower() or "paper-trading" in next_step.lower() or "阻断" in next_step, (
        f"next_step must still reference the persistence block on strict release/paper trading, got: {next_step!r}"
    )


def test_corridor_shadow_pack_no_active_primary_next_step_is_noop(tmp_path: Path) -> None:
    """Regression: when there is no active primary (skipped_no_corridor_lane),
    next_step must NOT emit replay-oriented guidance but instead a no-op/skip message."""
    corridor_validation_pack_path = tmp_path / "btst_candidate_pool_corridor_validation_pack_latest.json"

    _write_json(corridor_validation_pack_path, {"pack_status": "skipped_no_corridor_lane"})

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(corridor_validation_pack_path)

    assert analysis["shadow_status"] == "skipped_no_corridor_lane"
    next_step = analysis.get("next_step") or ""
    assert "shadow replay" not in next_step.lower(), (
        f"next_step must NOT contain replay-oriented guidance when there is no active primary, "
        f"got: {next_step!r}"
    )


def test_corridor_uplift_runbook_blocked_shadow_pack_suppresses_paper_trading_commands(tmp_path: Path) -> None:
    """Regression: when the corridor shadow pack is blocked by persistence gate (no active primary),
    execution_commands must NOT include run_paper_trading.py commands.
    Emitting replay/paper-trading commands in a blocked state violates fail-closed semantics."""
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    # Blocked shadow pack: persistence gate fired, no active primary
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "blocked_by_persistence_gate",
            "strict_release_status": "strict_release_blocked_by_persistence",
            "primary_shadow_replay": {},
            "parallel_watch_lanes": [],
            "shadow_replay_commands": [],
            "success_criteria": [],
            "guardrails": [],
        },
    )
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300683", "lane_family": "corridor"}})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    paper_trading_cmds = [cmd for cmd in analysis["execution_commands"] if "run_paper_trading.py" in cmd]
    assert paper_trading_cmds == [], (
        f"execution_commands must NOT include run_paper_trading.py when shadow pack is blocked, "
        f"got: {paper_trading_cmds}"
    )


def test_corridor_uplift_runbook_diagnostic_primary_replay_only_suppresses_paper_trading_commands(tmp_path: Path) -> None:
    """Diagnostic primary replay should preserve shadow governance commands but still suppress paper trading."""
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "diagnostic_primary_shadow_replay_only",
            "strict_release_status": "strict_release_blocked_by_persistence",
            "primary_shadow_replay": {"ticker": "300683"},
            "parallel_watch_lanes": [],
            "shadow_replay_commands": [
                "python scripts/run_btst_candidate_pool_corridor_shadow_pack.py --corridor-validation-pack-path /tmp/pack.json"
            ],
            "success_criteria": [],
            "guardrails": [],
        },
    )
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300683", "lane_family": "corridor"}})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    paper_trading_cmds = [cmd for cmd in analysis["execution_commands"] if "run_paper_trading.py" in cmd]
    assert paper_trading_cmds == [], (
        "execution_commands must NOT include run_paper_trading.py when strict release is blocked by persistence, "
        f"got: {paper_trading_cmds}"
    )


def test_corridor_uplift_runbook_blocked_shadow_pack_next_step_is_not_replay_oriented(tmp_path: Path) -> None:
    """Regression: when the corridor shadow pack is blocked (no active primary),
    the runbook next_step must NOT be replay-oriented (e.g. 'primary shadow replay 槽位' language)."""
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(recall_dossier_path, {"priority_handoff_branch_experiment_queue": []})
    _write_json(
        corridor_shadow_pack_path,
        {
            "shadow_status": "blocked_by_persistence_gate",
            "strict_release_status": "strict_release_blocked_by_persistence",
            "primary_shadow_replay": {},
            "parallel_watch_lanes": [],
            "shadow_replay_commands": [],
            "success_criteria": [],
            "guardrails": [],
        },
    )
    _write_json(lane_pair_board_path, {"board_leader": {}})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    next_step = analysis.get("next_step") or ""
    assert "primary shadow replay 槽位" not in next_step, (
        f"next_step must NOT be replay-oriented when shadow pack is blocked, got: {next_step!r}"
    )


def test_corridor_uplift_runbook_execution_commands_preserve_custom_corridor_validation_pack_path(tmp_path: Path) -> None:
    """Regression: execution_commands must carry the custom --corridor-validation-pack-path in the
    shadow-pack step so re-running those commands operates on the exact same inputs.

    Previously _build_corridor_uplift_commands hardcoded the default path, silently dropping
    any custom corridor_validation_pack_path that was passed to the runbook.
    """
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    # Deliberately non-default name to make the assertion unambiguous.
    corridor_validation_pack_path = tmp_path / "custom_corridor_validation_pack.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(corridor_validation_pack_path, {"pack_status": "parallel_probe_ready"})
    _write_json(corridor_shadow_pack_path, {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []})
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_validation_pack_path=corridor_validation_pack_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    shadow_pack_cmds = [cmd for cmd in analysis["execution_commands"] if "run_btst_candidate_pool_corridor_shadow_pack.py" in cmd]
    assert shadow_pack_cmds, "No shadow pack command found in execution_commands"
    resolved_cvp = str(corridor_validation_pack_path.resolve())
    assert any(resolved_cvp in cmd for cmd in shadow_pack_cmds), (
        f"Custom corridor_validation_pack_path {resolved_cvp!r} must appear in the shadow-pack "
        f"execution_command so re-running it operates on the same inputs. "
        f"Got: {shadow_pack_cmds}"
    )


def test_corridor_uplift_runbook_fallback_shadow_pack_uses_custom_corridor_validation_pack_path(tmp_path: Path) -> None:
    """Regression: when corridor_shadow_pack_path is missing/empty and fallback regeneration runs,
    the fallback call to analyze_btst_candidate_pool_corridor_shadow_pack must use the
    corridor_validation_pack_path that was passed to the runbook, not the hardcoded default.
    """
    import unittest.mock

    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_validation_pack_path = tmp_path / "custom_corridor_validation_pack.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"
    # corridor_shadow_pack_path intentionally omitted so fallback triggers.

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(corridor_validation_pack_path, {"pack_status": "parallel_probe_ready"})
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})

    fake_shadow_pack = {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []}

    with unittest.mock.patch(
        "scripts.run_btst_candidate_pool_corridor_uplift_runbook.analyze_btst_candidate_pool_corridor_shadow_pack",
        return_value=fake_shadow_pack,
    ) as mock_shadow_pack:
        analyze_btst_candidate_pool_corridor_uplift_runbook(
            recall_dossier_path,
            corridor_validation_pack_path=corridor_validation_pack_path,
            corridor_shadow_pack_path=None,
            lane_pair_board_path=lane_pair_board_path,
        )

    assert mock_shadow_pack.called, "Fallback analyze_btst_candidate_pool_corridor_shadow_pack was not called"
    call_args = mock_shadow_pack.call_args
    # First positional arg must be our custom validation pack path (resolved or as-is)
    used_path = Path(call_args[0][0]).resolve() if call_args[0] else None
    expected_path = corridor_validation_pack_path.resolve()
    assert used_path == expected_path, (
        f"Fallback must pass the custom corridor_validation_pack_path to shadow pack regeneration. "
        f"Expected {expected_path!r}, got {used_path!r}"
    )


def test_corridor_uplift_runbook_script_direct_cli_execution_works() -> None:
    """The uplift runbook script must self-bootstrap sys.path so
    'python scripts/run_btst_candidate_pool_corridor_uplift_runbook.py --help'
    succeeds without relying on the venv's editable-install .pth file.

    Regression: without sys.path.insert the script crashes at import time with
    ModuleNotFoundError when invoked directly (e.g., via the command emitted in execution_commands).

    The test simulates a no-.pth environment by passing -S (skip site-packages / .pth files)
    and providing the venv site-packages directory via PYTHONPATH so that third-party
    dependencies are still available.  Under these conditions only the script's own
    sys.path.insert can resolve the 'scripts.*' / 'src.*' package roots, so a missing
    bootstrap will produce ModuleNotFoundError and a non-zero exit code.
    """
    import os

    repo_root = Path(__file__).resolve().parent.parent
    # Use the venv's own interpreter to guarantee it matches the site-packages we put on PYTHONPATH.
    # sys.executable can be a different Python version (e.g. the system Python) which would cause
    # stdlib/site-packages mismatches and make this test flaky.
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
    venv_site = repo_root / ".venv" / "lib"
    site_dirs = sorted(venv_site.glob("python3.*/site-packages")) if venv_site.exists() else []
    env = {**os.environ, "PYTHONPATH": str(site_dirs[0]) if site_dirs else ""}

    result = subprocess.run(
        [str(venv_python), "-S", "scripts/run_btst_candidate_pool_corridor_uplift_runbook.py", "--help"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Direct CLI execution of scripts/run_btst_candidate_pool_corridor_uplift_runbook.py --help "
        "failed in a no-.pth environment.  This usually means the sys.path bootstrap is missing or broken.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower(), (
        "Expected argparse usage text in output of --help invocation, "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_corridor_uplift_runbook_self_rerun_command_includes_corridor_validation_pack_path(tmp_path: Path) -> None:
    """Regression: the self-rerun command for run_btst_candidate_pool_corridor_uplift_runbook.py
    emitted in execution_commands must include --corridor-validation-pack-path so that re-running
    the runbook cannot silently switch back to the default validation pack.
    """
    recall_dossier_path = tmp_path / "btst_candidate_pool_recall_dossier_latest.json"
    corridor_validation_pack_path = tmp_path / "custom_validation_pack.json"
    corridor_shadow_pack_path = tmp_path / "btst_candidate_pool_corridor_shadow_pack_latest.json"
    lane_pair_board_path = tmp_path / "btst_candidate_pool_lane_pair_board_latest.json"

    _write_json(
        recall_dossier_path,
        {
            "priority_handoff_branch_experiment_queue": [
                {
                    "task_id": "layer_a_liquidity_corridor_upstream_base_liquidity_uplift_probe",
                    "priority_handoff": "layer_a_liquidity_corridor",
                    "prototype_readiness": "shadow_ready_large_gap",
                    "prototype_type": "upstream_base_liquidity_uplift_probe",
                    "uplift_to_cutoff_multiple_mean": 8.603,
                }
            ]
        },
    )
    _write_json(corridor_validation_pack_path, {"pack_status": "parallel_probe_ready"})
    _write_json(corridor_shadow_pack_path, {"primary_shadow_replay": {"ticker": "300720"}, "parallel_watch_lanes": [], "success_criteria": [], "guardrails": []})
    _write_json(lane_pair_board_path, {"board_leader": {"ticker": "300720", "lane_family": "corridor"}})

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        recall_dossier_path,
        corridor_validation_pack_path=corridor_validation_pack_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        lane_pair_board_path=lane_pair_board_path,
    )

    uplift_cmds = [cmd for cmd in analysis["execution_commands"] if "run_btst_candidate_pool_corridor_uplift_runbook.py" in cmd]
    assert uplift_cmds, "No uplift runbook self-rerun command found in execution_commands"
    resolved_pack_path = str(corridor_validation_pack_path.expanduser().resolve())
    assert any(f"--corridor-validation-pack-path {resolved_pack_path}" in cmd for cmd in uplift_cmds), (
        f"Expected '--corridor-validation-pack-path {resolved_pack_path}' in uplift runbook self-rerun command, "
        f"got: {uplift_cmds}"
    )


def test_lane_pair_board_fallback_passes_persistence_dossier_path(tmp_path: Path) -> None:
    """regression: when corridor_shadow_pack_path cannot be loaded and the fallback inside
    analyze_btst_candidate_pool_lane_pair_board recomputes the shadow pack, it must forward
    persistence_dossier_path to analyze_btst_candidate_pool_corridor_shadow_pack so the
    persistence gate is honoured.  Without the fix the fallback call omits
    persistence_dossier_path, bypassing the gate and producing a false ready state."""
    from unittest.mock import patch

    # A path that does not exist triggers the fallback branch at line ~401
    corridor_shadow_pack_path = tmp_path / "missing_shadow_pack.json"
    rebucket_path = tmp_path / "rebucket.json"
    persistence_dossier_path = tmp_path / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(rebucket_path, {"bundle_status": "skipped_no_rebucket_lane", "rebucket_objective_row": {}, "priority_alignment_status": ""})
    _write_json(
        persistence_dossier_path,
        {
            "focus_ticker": "300683",
            "verdict": "await_second_independent_selected_window",
            "continuation_readiness": {"governance_blocker": ""},
        },
    )

    captured: list[dict] = []

    def fake_shadow_pack(validation_pack_path, **kwargs):
        captured.append({"path": validation_pack_path, "kwargs": kwargs})
        return {"shadow_status": "skipped_no_corridor_lane", "primary_shadow_replay": {}, "parallel_watch_lanes": []}

    with patch(
        "scripts.run_btst_candidate_pool_lane_pair_board.analyze_btst_candidate_pool_corridor_shadow_pack",
        side_effect=fake_shadow_pack,
    ):
        analyze_btst_candidate_pool_lane_pair_board(
            str(corridor_shadow_pack_path),
            str(rebucket_path),
            persistence_dossier_path=str(persistence_dossier_path),
        )

    assert len(captured) == 1, "fallback should have called analyze_btst_candidate_pool_corridor_shadow_pack"
    assert "persistence_dossier_path" in captured[0]["kwargs"], (
        "fallback must forward persistence_dossier_path to preserve fail-closed semantics; "
        f"got kwargs: {captured[0]['kwargs']}"
    )
