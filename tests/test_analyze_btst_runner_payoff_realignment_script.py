from __future__ import annotations

import json
from pathlib import Path

from scripts import analyze_btst_runner_payoff_realignment as runner_payoff_realignment


def test_analyze_btst_runner_payoff_realignment_reports_recommended_staged_path(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "selected_summary": {"hit_rate_15pct": 0.20},
                "near_miss_summary": {"hit_rate_15pct": 0.4507},
                "formal_source_summary": {
                    "layer_c_watchlist": {"count": 2, "hit_rate_15pct": 0.0},
                    "short_trade_boundary": {"count": 3, "hit_rate_15pct": 0.0},
                },
                "runner_recall_summary": {
                    "watchlist_filter_diagnostics_false_negatives": 6,
                    "hit_rate_15pct": 0.6667,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=weekly_validation_json,
    )

    assert report["diagnosis"]["primary_problem"] == "formal_selected_target_misalignment"
    assert report["diagnosis"]["selected_hit_rate_15pct"] == 0.2
    assert report["diagnosis"]["near_miss_hit_rate_15pct"] == 0.4507
    assert report["diagnosis"]["payoff_gap_vs_near_miss_15pct"] == 0.2507
    assert report["diagnosis"]["runner_recall_hit_rate_15pct"] == 0.6667
    assert report["diagnosis"]["formal_source_drag_count"] == 2
    assert report["recommendation"]["status"] == "staged_formal_shrink_plus_runner_recall"
    assert report["recommendation"]["next_steps"] == [
        "formal_source_shadow",
        "payoff_first_runner_recall",
    ]
    assert report["diagnosis"]["watchlist_filter_diagnostics_false_negatives"] == 6


def test_analyze_btst_runner_payoff_realignment_avoids_staged_path_without_recall_edge(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation_negative.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "selected_summary": {"hit_rate_15pct": 0.42},
                "near_miss_summary": {"hit_rate_15pct": 0.18},
                "formal_source_summary": {
                    "layer_c_watchlist": {"count": 1, "hit_rate_15pct": 0.4},
                    "short_trade_boundary": {"count": 2, "hit_rate_15pct": 0.25},
                },
                "runner_recall_summary": {
                    "watchlist_filter_diagnostics_false_negatives": 0,
                    "hit_rate_15pct": 0.0,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=weekly_validation_json,
    )

    assert report["diagnosis"]["selected_hit_rate_15pct"] == 0.42
    assert report["diagnosis"]["near_miss_hit_rate_15pct"] == 0.18
    assert report["diagnosis"]["payoff_gap_vs_near_miss_15pct"] == -0.24
    assert report["diagnosis"]["runner_recall_hit_rate_15pct"] == 0.0
    assert report["diagnosis"]["formal_source_drag_count"] == 2
    assert report["diagnosis"]["watchlist_filter_diagnostics_false_negatives"] == 0
    assert report["diagnosis"]["primary_problem"] != "formal_selected_target_misalignment"
    assert report["recommendation"]["status"] != "staged_formal_shrink_plus_runner_recall"
    assert report["recommendation"]["next_steps"] != [
        "formal_source_shadow",
        "payoff_first_runner_recall",
    ]
    assert report["recommendation"] == {
        "status": "hold_current_path",
        "next_steps": ["monitor_next_window"],
    }


def test_analyze_btst_runner_payoff_realignment_reads_real_weekly_validation_schema(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation_real_schema.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "weekly_surface_summaries": {
                    "selected": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.2,
                    },
                    "near_miss": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.4507,
                    },
                },
                "selected_candidate_source_breakdown": [
                    {
                        "candidate_source": "layer_c_watchlist",
                        "count": 2,
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.0,
                    },
                    {
                        "candidate_source": "short_trade_boundary",
                        "count": 3,
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.0,
                    },
                ],
                "runner_false_negative_summary": {
                    "candidate_source_counts": {
                        "watchlist_filter_diagnostics": 6,
                    },
                    "surface_metrics": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 1.0,
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=weekly_validation_json,
    )

    assert report["diagnosis"]["primary_problem"] == "formal_selected_target_misalignment"
    assert report["diagnosis"]["selected_hit_rate_15pct"] == 0.2
    assert report["diagnosis"]["near_miss_hit_rate_15pct"] == 0.4507
    assert report["diagnosis"]["runner_recall_hit_rate_15pct"] == 1.0
    assert report["diagnosis"]["watchlist_filter_diagnostics_false_negatives"] == 6
    assert report["diagnosis"]["formal_source_drag_count"] == 2
    assert report["recommendation"]["status"] == "staged_formal_shrink_plus_runner_recall"


def test_analyze_btst_runner_payoff_realignment_respects_explicit_empty_drag_source_list(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation_empty_drag_sources.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "weekly_surface_summaries": {
                    "selected": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.2,
                    },
                    "near_miss": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.4507,
                    },
                },
                "selected_candidate_source_breakdown": [
                    {
                        "candidate_source": "layer_c_watchlist",
                        "count": 2,
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.0,
                    },
                ],
                "selected_payoff_drag_candidate_sources": [],
                "runner_false_negative_summary": {
                    "candidate_source_counts": {
                        "watchlist_filter_diagnostics": 6,
                    },
                    "surface_metrics": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 1.0,
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=weekly_validation_json,
    )

    assert report["diagnosis"]["formal_source_drag_count"] == 0
