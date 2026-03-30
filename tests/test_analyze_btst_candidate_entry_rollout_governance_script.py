from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_entry_rollout_governance import analyze_btst_candidate_entry_rollout_governance


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_analyze_btst_candidate_entry_rollout_governance_shadow_only(tmp_path: Path) -> None:
    frontier_path = _write_json(
        tmp_path / "btst_candidate_entry_frontier.json",
        {
            "best_variant": {
                "variant_name": "weak_structure_triplet",
                "filtered_candidate_entry_count": 1,
                "focus_filtered_tickers": ["300502"],
                "preserve_filtered_tickers": [],
                "filtered_next_high_hit_rate_at_threshold": 0.0,
                "filtered_next_close_positive_rate": 0.0,
                "evidence_tier": "window_verified_selective_rule",
                "selection_basis": "candidate_entry_frontier_priority",
            }
        },
    )
    structural_path = _write_json(
        tmp_path / "structural_validation.json",
        {
            "rows": [
                {
                    "structural_variant": "exclude_watchlist_avoid_weak_structure_entries",
                    "decision_mismatch_count": 1,
                    "released_from_blocked": ["300502"],
                    "blocked_to_near_miss": [],
                    "blocked_to_selected": [],
                    "analysis": {
                        "filtered_candidate_entry_counts": {"watchlist_avoid_boundary_weak_structure_entry": 1},
                        "candidate_entry_filter_observability": {"watchlist_avoid_boundary_weak_structure_entry": {"precondition_match_count": 3, "metric_data_pass_count": 3, "metric_threshold_match_count": 1}},
                    },
                }
            ]
        },
    )
    window_scan_path = _write_json(
        tmp_path / "window_scan.json",
        {
            "report_count": 2,
            "filtered_report_count": 1,
            "focus_hit_report_count": 1,
            "preserve_misfire_report_count": 0,
            "distinct_window_count_with_filtered_entries": 1,
            "rollout_readiness": "shadow_only_until_second_window",
            "filtered_ticker_counts": {"300502": 1},
        },
    )
    score_frontier_path = _write_json(
        tmp_path / "score_frontier.json",
        {
            "ranked_variants": [
                {"variant_name": "prepared_breakout_balance", "closed_cycle_tradeable_count": 0},
                {"variant_name": "catalyst_volume_balance", "closed_cycle_tradeable_count": 0},
            ]
        },
    )

    analysis = analyze_btst_candidate_entry_rollout_governance(
        frontier_path,
        structural_validation_path=structural_path,
        window_scan_path=window_scan_path,
        score_frontier_path=score_frontier_path,
    )

    assert analysis["candidate_entry_rule"] == "weak_structure_triplet"
    assert analysis["recommended_structural_variant"] == "exclude_watchlist_avoid_weak_structure_entries"
    assert analysis["lane_status"] == "shadow_only_until_second_window"
    assert analysis["default_upgrade_status"] == "blocked_by_single_window_candidate_entry_signal"
    assert analysis["score_frontier_all_zero"] is True
    assert analysis["main_chain_validation"]["released_from_blocked"] == ["300502"]
    assert analysis["window_scan_summary"]["distinct_window_count_with_filtered_entries"] == 1
