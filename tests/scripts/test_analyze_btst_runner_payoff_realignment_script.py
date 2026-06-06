from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert report["source_diagnosis"]["formal_payoff_drag_candidate_sources"] == [
        "layer_c_watchlist",
        "short_trade_boundary",
    ]


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
    assert report["source_diagnosis"]["formal_payoff_drag_candidate_sources"] == [
        "layer_c_watchlist",
        "short_trade_boundary",
    ]


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
    assert report["source_diagnosis"]["formal_payoff_drag_candidate_sources"] == []


def test_analyze_btst_runner_payoff_realignment_accepts_existing_artifactized_report_payload(tmp_path: Path) -> None:
    artifact_json = tmp_path / "runner_payoff_realignment_artifact.json"
    artifact_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.3077,
                    "near_miss_hit_rate_15pct": 0.3564,
                    "payoff_gap_vs_near_miss_15pct": 0.0487,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 13,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=artifact_json,
    )

    assert report["diagnosis"]["primary_problem"] == "formal_selected_target_misalignment"
    assert report["diagnosis"]["selected_hit_rate_15pct"] == 0.3077
    assert report["diagnosis"]["formal_source_drag_count"] == 1
    assert report["recommendation"]["status"] == "staged_formal_shrink_plus_runner_recall"
    assert report["source_diagnosis"]["formal_payoff_drag_candidate_sources"] == ["layer_c_watchlist"]


def test_analyze_btst_runner_payoff_realignment_rejects_artifactized_report_without_source_diagnosis(tmp_path: Path) -> None:
    artifact_json = tmp_path / "runner_payoff_realignment_artifact_missing_source.json"
    artifact_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.3077,
                    "near_miss_hit_rate_15pct": 0.3564,
                    "payoff_gap_vs_near_miss_15pct": 0.0487,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 13,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_diagnosis"):
        runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
            weekly_validation_json=artifact_json,
        )


def test_analyze_btst_runner_payoff_realignment_rejects_legacy_top_level_sources_in_artifactized_report(tmp_path: Path) -> None:
    artifact_json = tmp_path / "runner_payoff_realignment_artifact_legacy_sources.json"
    artifact_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.3077,
                    "near_miss_hit_rate_15pct": 0.3564,
                    "payoff_gap_vs_near_miss_15pct": 0.0487,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 13,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
                "selected_payoff_drag_candidate_sources": ["layer_c_watchlist"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="selected_payoff_drag_candidate_sources"):
        runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
            weekly_validation_json=artifact_json,
        )


def test_analyze_btst_runner_payoff_realignment_rejects_mixed_new_and_legacy_artifact_schema(tmp_path: Path) -> None:
    artifact_json = tmp_path / "runner_payoff_realignment_artifact_mixed_schema.json"
    artifact_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.3077,
                    "near_miss_hit_rate_15pct": 0.3564,
                    "payoff_gap_vs_near_miss_15pct": 0.0487,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 13,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
                "selected_payoff_drag_candidate_sources": ["layer_c_watchlist"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="legacy"):
        runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
            weekly_validation_json=artifact_json,
        )


def test_compare_btst_runner_payoff_realignment_windows_marks_layer_c_stable_and_boundary_conditional(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation_week.json"
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
                "selected_payoff_drag_candidate_sources": ["layer_c_watchlist", "short_trade_boundary"],
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
    expanded_validation_json = tmp_path / "weekly_validation_expanded.json"
    expanded_validation_json.write_text(
        json.dumps(
            {
                "weekly_surface_summaries": {
                    "selected": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.3077,
                    },
                    "near_miss": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.3564,
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
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.3333,
                    },
                ],
                "selected_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                "runner_false_negative_summary": {
                    "candidate_source_counts": {
                        "watchlist_filter_diagnostics": 13,
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

    comparison = runner_payoff_realignment.compare_btst_runner_payoff_realignment_windows(
        weekly_validation_jsons=[weekly_validation_json, expanded_validation_json],
    )

    assert comparison["overall_recommendation_status"] == "staged_formal_shrink_plus_runner_recall"
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_lane"] == "layer_c_watchlist"
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_sources"] == ["layer_c_watchlist"]
    assert comparison["source_lane_recommendation"]["conditional_formal_shrink_sources"] == ["short_trade_boundary"]
    assert comparison["source_lane_recommendation"]["layer_c_watchlist_policy"] == "stable_formal_shrink_lane"
    assert comparison["source_lane_recommendation"]["short_trade_boundary_policy"] == "conditional_only"


def test_compare_btst_runner_payoff_realignment_windows_does_not_promote_lane_when_window_verdicts_are_mixed(tmp_path: Path) -> None:
    staged_report_json = tmp_path / "staged_report.json"
    staged_report_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.2,
                    "near_miss_hit_rate_15pct": 0.4507,
                    "payoff_gap_vs_near_miss_15pct": 0.2507,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 6,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    hold_report_json = tmp_path / "hold_report.json"
    hold_report_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "selected_payoff_not_underperforming_near_miss",
                    "selected_hit_rate_15pct": 0.42,
                    "near_miss_hit_rate_15pct": 0.18,
                    "payoff_gap_vs_near_miss_15pct": -0.24,
                    "runner_recall_hit_rate_15pct": 0.0,
                    "watchlist_filter_diagnostics_false_negatives": 0,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "hold_current_path",
                    "next_steps": ["monitor_next_window"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    comparison = runner_payoff_realignment.compare_btst_runner_payoff_realignment_windows(
        weekly_validation_jsons=[staged_report_json, hold_report_json],
    )

    assert comparison["overall_recommendation_status"] == "mixed"
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_lane"] is None
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_sources"] == []
    assert comparison["source_lane_recommendation"]["conditional_formal_shrink_sources"] == []
    assert comparison["source_lane_recommendation"]["layer_c_watchlist_policy"] == "hold_current_path"
    assert comparison["source_lane_recommendation"]["short_trade_boundary_policy"] == "hold_current_path"


def test_compare_btst_runner_payoff_realignment_windows_keeps_lane_verdict_when_all_windows_support_shrink(tmp_path: Path) -> None:
    staged_report_json = tmp_path / "staged_report.json"
    staged_report_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_target_misalignment",
                    "selected_hit_rate_15pct": 0.2,
                    "near_miss_hit_rate_15pct": 0.4507,
                    "payoff_gap_vs_near_miss_15pct": 0.2507,
                    "runner_recall_hit_rate_15pct": 1.0,
                    "watchlist_filter_diagnostics_false_negatives": 6,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "staged_formal_shrink_plus_runner_recall",
                    "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shrink_only_report_json = tmp_path / "shrink_only_report.json"
    shrink_only_report_json.write_text(
        json.dumps(
            {
                "diagnosis": {
                    "primary_problem": "formal_selected_payoff_drag_without_runner_recall_confirmation",
                    "selected_hit_rate_15pct": 0.28,
                    "near_miss_hit_rate_15pct": 0.31,
                    "payoff_gap_vs_near_miss_15pct": 0.03,
                    "runner_recall_hit_rate_15pct": 0.0,
                    "watchlist_filter_diagnostics_false_negatives": 0,
                    "formal_source_drag_count": 1,
                },
                "recommendation": {
                    "status": "formal_shrink_only",
                    "next_steps": ["formal_source_shadow"],
                },
                "source_diagnosis": {
                    "formal_payoff_drag_candidate_sources": ["layer_c_watchlist"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    comparison = runner_payoff_realignment.compare_btst_runner_payoff_realignment_windows(
        weekly_validation_jsons=[staged_report_json, shrink_only_report_json],
    )

    assert comparison["overall_recommendation_status"] == "mixed"
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_lane"] == "layer_c_watchlist"
    assert comparison["source_lane_recommendation"]["stable_formal_shrink_sources"] == ["layer_c_watchlist"]
    assert comparison["source_lane_recommendation"]["conditional_formal_shrink_sources"] == []
    assert comparison["source_lane_recommendation"]["layer_c_watchlist_policy"] == "stable_formal_shrink_lane"
