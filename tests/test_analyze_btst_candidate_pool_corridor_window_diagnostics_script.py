from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_corridor_window_diagnostics import (
    analyze_btst_candidate_pool_corridor_window_diagnostics,
    render_btst_candidate_pool_corridor_window_diagnostics_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_daily_event(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_window_diagnostics_flags_narrow_gap_and_recoverable_visibility(tmp_path: Path) -> None:
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
                },
                {
                    "report_label": "20260406",
                    "report_dir": str(near_miss_report_dir),
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_bottleneck": "catalyst_relief_validated",
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

    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        candidate_dossier_path=candidate_dossier_path,
        command_board_path=command_board_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["near_miss_upgrade_window"]["verdict"] == "narrow_selected_gap_candidate"
    assert analysis["visibility_gap_window"]["verdict"] == "recoverable_current_plan_visibility_gap"
    assert analysis["visibility_gap_window"]["recoverable_report_dir_count"] == 1
    assert analysis["selected_anchor_window"]["decision"] == "selected"
    assert analysis["near_miss_upgrade_window"]["delta_vs_selected"]["effective_select_threshold_delta"] is None

    markdown = render_btst_candidate_pool_corridor_window_diagnostics_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Window Diagnostics" in markdown
    assert "recoverable_current_plan_visibility_gap" in markdown
