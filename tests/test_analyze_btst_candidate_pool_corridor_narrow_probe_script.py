from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_corridor_narrow_probe import (
    analyze_btst_candidate_pool_corridor_narrow_probe,
    render_btst_candidate_pool_corridor_narrow_probe_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_daily_event(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_narrow_probe_surfaces_threshold_override_gap(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    candidate_dossier_path = reports_root / "btst_tplus2_candidate_dossier_300720_latest.json"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"
    selected_report_dir = reports_root / "selected"
    near_miss_report_dir = reports_root / "near_miss"
    visibility_gap_dir = reports_root / "gap_probe"

    _write_json(
        candidate_dossier_path,
        {
            "candidate_ticker": "300720",
            "per_window_summaries": [
                {
                    "report_label": "20260331",
                    "report_dir": str(selected_report_dir),
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "downstream_bottleneck": "selected",
                    "score_target": 0.4584,
                },
                {
                    "report_label": "20260406",
                    "report_dir": str(near_miss_report_dir),
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_bottleneck": "catalyst_relief_validated",
                    "score_target": 0.4555,
                },
            ],
            "current_plan_visibility_summary": {
                "current_plan_visibility_gap_report_dirs": [str(visibility_gap_dir)],
            },
        },
    )
    _write_json(
        command_board_path,
        {
            "focus_ticker": "300720",
            "confirmed_selected_trade_dates": ["2026-03-31"],
            "next_target_trade_dates": ["2026-04-06", "2026-03-27"],
            "visibility_gap_trade_dates": ["2026-03-27"],
        },
    )
    _write_json(
        selected_report_dir / "selection_artifacts" / "2026-03-31" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300720": {
                    "short_trade": {
                        "decision": "selected",
                        "score_target": 0.4584,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.8814,
                            "close_strength": 0.8902,
                            "volume_expansion_quality": 0.25,
                            "upstream_shadow_catalyst_relief_applied": True,
                            "thresholds": {"effective_select_threshold": 0.45, "select_threshold": 0.58, "near_miss_threshold": 0.45},
                        },
                    }
                }
            }
        },
    )
    _write_json(
        near_miss_report_dir / "selection_artifacts" / "2026-04-06" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300720": {
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.4555,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.8507,
                            "close_strength": 0.9092,
                            "volume_expansion_quality": 0.25,
                            "upstream_shadow_catalyst_relief_applied": True,
                            "thresholds": {"effective_select_threshold": 0.58, "select_threshold": 0.58, "near_miss_threshold": 0.45},
                        },
                    }
                }
            }
        },
    )
    _write_daily_event(
        visibility_gap_dir / "daily_events.jsonl",
        {
            "current_plan": {
                "watchlist": [],
                "selection_targets": {},
                "risk_metrics": {"artifact_path": "contains_300720_only_in_nonsemantic_area"},
            }
        },
    )
    _write_json(
        visibility_gap_dir / "selection_artifacts" / "2026-03-27" / "selection_target_replay_input.json",
        {
            "selection_targets": {"300720": {"short_trade": {"decision": "near_miss"}}}
        },
    )
    _write_json(
        visibility_gap_dir / "selection_artifacts" / "2026-03-27" / "selection_snapshot.json",
        {
            "near_miss_entries": [{"ticker": "300720"}]
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_dossier_path=candidate_dossier_path,
        command_board_path=command_board_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["verdict"] == "lane_specific_select_threshold_override_gap"
    assert analysis["threshold_override_gap_vs_anchor"] == 0.13
    assert analysis["target_gap_to_selected"] == 0.1245

    markdown = render_btst_candidate_pool_corridor_narrow_probe_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Narrow Probe" in markdown
    assert "lane_specific_select_threshold_override_gap" in markdown


def test_analyze_btst_candidate_pool_corridor_narrow_probe_surfaces_deepest_corridor_split(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    recall_dossier_path = reports_root / "btst_candidate_pool_recall_dossier_latest.json"
    _write_json(
        recall_dossier_path,
        {
            "priority_ticker_dossiers": [
                {
                    "ticker": "300683",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "avg_amount_share_of_cutoff_mean": 0.1519,
                        "avg_amount_share_of_min_gate_mean": 4.53,
                    },
                },
                {
                    "ticker": "688796",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "avg_amount_share_of_cutoff_mean": 0.0821,
                        "avg_amount_share_of_min_gate_mean": 2.46,
                    },
                },
                {
                    "ticker": "301188",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "avg_amount_share_of_cutoff_mean": 0.074,
                        "avg_amount_share_of_min_gate_mean": 2.5,
                    },
                },
                {
                    "ticker": "688383",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "layer_a_liquidity_corridor",
                        "avg_amount_share_of_cutoff_mean": 0.0584,
                        "avg_amount_share_of_min_gate_mean": 2.31,
                    },
                },
                {
                    "ticker": "301292",
                    "truncation_liquidity_profile": {
                        "priority_handoff": "post_gate_liquidity_competition",
                        "avg_amount_share_of_cutoff_mean": 0.091,
                        "avg_amount_share_of_min_gate_mean": 2.7,
                    },
                },
            ]
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    assert analysis["verdict"] == "deepest_corridor_split_ready"
    assert analysis["deepest_corridor_focus_tickers"] == ["301188"]
    assert analysis["excluded_low_gate_tail_tickers"] == []
    assert set(analysis["standard_corridor_tickers"]) == {"300683", "688796", "688383"}

    markdown = render_btst_candidate_pool_corridor_narrow_probe_markdown(analysis)
    assert "deepest_corridor_focus_tickers" in markdown
    assert "688796" in markdown


def test_analyze_btst_candidate_pool_corridor_narrow_probe_stays_scoped_to_custom_recall_dossier(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    recall_dossier_path = reports_root / "btst_candidate_pool_recall_dossier_latest.json"
    _write_json(
        recall_dossier_path,
        {
            "priority_stage_counts": {"candidate_pool_truncated_after_filters": 2},
            "priority_ticker_dossiers": [],
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_pool_recall_dossier_path=recall_dossier_path,
    )

    assert analysis["verdict"] == "insufficient_corridor_recall_inputs"
    assert analysis["deepest_corridor_focus_tickers"] == []
    assert analysis["excluded_low_gate_tail_tickers"] == []
