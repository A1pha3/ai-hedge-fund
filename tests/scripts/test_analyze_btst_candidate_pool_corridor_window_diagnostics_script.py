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
        {"selection_targets": {"300720": {"short_trade": {"decision": "near_miss"}}}},
    )
    _write_json(
        visibility_gap_dir / "selection_artifacts" / "2026-03-27" / "selection_snapshot.json",
        {"near_miss_entries": [{"ticker": "300720"}]},
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


def test_diagnostics_auto_derives_dossier_for_actual_focus_ticker(tmp_path: Path) -> None:
    """When no explicit dossier path is given, diagnostics derives it from the command board focus ticker
    (e.g. 300683), not from the stale DEFAULT_CANDIDATE_DOSSIER_PATH anchored to 300720."""
    reports_root = tmp_path / "data" / "reports"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"
    near_miss_report_dir = reports_root / "near_miss_683"

    # Only create a dossier for 300683 — deliberately NO 300720 dossier
    dossier_683_path = reports_root / "btst_tplus2_candidate_dossier_300683_latest.json"
    _write_json(
        dossier_683_path,
        {
            "candidate_ticker": "300683",
            "per_window_summaries": [
                {
                    "report_label": "20260410",
                    "report_dir": str(near_miss_report_dir),
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_bottleneck": "catalyst_relief_validated",
                },
            ],
            "current_plan_visibility_summary": {
                "current_plan_visibility_gap_report_dirs": [],
            },
        },
    )
    _write_json(
        command_board_path,
        {
            "focus_ticker": "300683",
            "confirmed_selected_trade_dates": [],
            "next_target_trade_dates": ["2026-04-10"],
            "visibility_gap_trade_dates": [],
        },
    )
    _write_json(
        near_miss_report_dir / "selection_artifacts" / "2026-04-10" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300683": {
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.43,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.81,
                            "close_strength": 0.88,
                            "volume_expansion_quality": 0.20,
                            "upstream_shadow_catalyst_relief_applied": False,
                        },
                    }
                }
            }
        },
    )

    # Call without explicit dossier_path; function must auto-derive for 300683
    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        command_board_path=command_board_path,
        _reports_dir=reports_root,
    )

    assert analysis["focus_ticker"] == "300683", "Diagnostics must re-anchor to command board focus_ticker (300683), not stale 300720 default"
    # source_reports must point to the 300683 dossier, not 300720
    assert "300683" in analysis["source_reports"]["candidate_dossier"]
    assert "300720" not in analysis["source_reports"]["candidate_dossier"]


def test_diagnostics_degrades_gracefully_when_focus_ticker_has_no_dossier_file(tmp_path: Path) -> None:
    """When command board focus_ticker=300683 has no candidate dossier file,
    diagnostics must not crash (stale-anchor fallback to 300720 is forbidden)."""
    reports_root = tmp_path / "data" / "reports"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"

    _write_json(
        command_board_path,
        {
            "focus_ticker": "300683",
            "confirmed_selected_trade_dates": [],
            "next_target_trade_dates": ["2026-04-10"],
            "visibility_gap_trade_dates": [],
            "action_rows": [
                {
                    "trade_date": "2026-04-10",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.41,
                    "report_dir": None,
                    "action_tier": "upgrade_near_miss_window",
                }
            ],
        },
    )
    # Deliberately NO btst_tplus2_candidate_dossier_300683_latest.json file

    # Must not crash; must return valid structure anchored on 300683
    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        command_board_path=command_board_path,
        _reports_dir=reports_root,
    )

    assert analysis["focus_ticker"] == "300683", "Even with no dossier file, focus_ticker must be 300683 from command board"
    assert analysis["selected_anchor_window"] is not None
    assert analysis["near_miss_upgrade_window"] is not None
    assert analysis["visibility_gap_window"] is not None


def test_diagnostics_reanchors_when_stale_mismatch_dossier_path_provided(tmp_path: Path) -> None:
    """When an explicit dossier path clearly targets a different ticker than the command board
    focus (e.g. path has 300720 but focus is 300683), diagnostics should resolve the
    path dynamically for 300683 and not silently use the stale dossier."""
    reports_root = tmp_path / "data" / "reports"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"
    near_miss_report_dir = reports_root / "nm_683"

    # Create a STALE 300720 dossier (wrong ticker)
    stale_300720_path = reports_root / "btst_tplus2_candidate_dossier_300720_latest.json"
    _write_json(stale_300720_path, {"candidate_ticker": "300720", "per_window_summaries": []})

    # Create the CORRECT 300683 dossier
    dossier_683_path = reports_root / "btst_tplus2_candidate_dossier_300683_latest.json"
    _write_json(
        dossier_683_path,
        {
            "candidate_ticker": "300683",
            "per_window_summaries": [
                {
                    "report_label": "20260410",
                    "report_dir": str(near_miss_report_dir),
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_bottleneck": "catalyst_relief_validated",
                },
            ],
            "current_plan_visibility_summary": {"current_plan_visibility_gap_report_dirs": []},
        },
    )
    _write_json(
        command_board_path,
        {
            "focus_ticker": "300683",
            "confirmed_selected_trade_dates": [],
            "next_target_trade_dates": ["2026-04-10"],
            "visibility_gap_trade_dates": [],
        },
    )

    # Pass the stale 300720 path explicitly — function should detect the mismatch
    # (no replay input needed since the near_miss window will be found from the 683 dossier)
    _write_json(
        near_miss_report_dir / "selection_artifacts" / "2026-04-10" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300683": {
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.42,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.80,
                            "close_strength": 0.85,
                            "volume_expansion_quality": 0.22,
                            "upstream_shadow_catalyst_relief_applied": False,
                        },
                    }
                }
            }
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        candidate_dossier_path=stale_300720_path,
        command_board_path=command_board_path,
        _reports_dir=reports_root,
    )

    assert analysis["focus_ticker"] == "300683", "focus_ticker must still come from command board"
    assert "300683" in analysis["source_reports"]["candidate_dossier"], "Source dossier must be re-anchored to 300683, not the stale 300720 path"


def test_diagnostics_loads_dossier_next_to_custom_command_board_without_reports_dir_hook(tmp_path: Path) -> None:
    """PUBLIC-path regression: when a non-default command_board_path is given and no
    candidate_dossier_path or _reports_dir is supplied, the dossier must be resolved
    relative to command_board_path's parent — NOT relative to the module-level REPORTS_DIR."""
    # Use a completely unrelated directory to ensure REPORTS_DIR can't accidentally work
    board_dir = tmp_path / "custom_reports"
    board_dir.mkdir(parents=True)
    command_board_path = board_dir / "btst_candidate_pool_corridor_window_command_board_latest.json"
    near_miss_report_dir = board_dir / "nm_999"

    _write_json(
        board_dir / "btst_tplus2_candidate_dossier_300999_latest.json",
        {
            "candidate_ticker": "300999",
            "per_window_summaries": [
                {
                    "report_label": "20260415",
                    "report_dir": str(near_miss_report_dir),
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "downstream_bottleneck": "catalyst_relief_validated",
                }
            ],
            "current_plan_visibility_summary": {"current_plan_visibility_gap_report_dirs": []},
        },
    )
    _write_json(
        command_board_path,
        {
            "focus_ticker": "300999",
            "confirmed_selected_trade_dates": [],
            "next_target_trade_dates": ["2026-04-15"],
            "visibility_gap_trade_dates": [],
        },
    )
    _write_json(
        near_miss_report_dir / "selection_artifacts" / "2026-04-15" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300999": {
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.44,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.82,
                            "close_strength": 0.86,
                            "volume_expansion_quality": 0.21,
                            "upstream_shadow_catalyst_relief_applied": False,
                        },
                    }
                }
            }
        },
    )

    # Call with ONLY command_board_path — no candidate_dossier_path, no _reports_dir override.
    # The dossier lives next to the command board; function must find it via board parent, not REPORTS_DIR.
    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        command_board_path=command_board_path,
    )

    assert analysis["focus_ticker"] == "300999", "focus_ticker must come from the custom command board"
    # The dossier must have been resolved from board_dir, not from the module-level REPORTS_DIR.
    # Check that the resolved dossier path lives INSIDE board_dir, not under data/reports.
    assert str(board_dir) in analysis["source_reports"]["candidate_dossier"], "Dossier path must be resolved next to command_board_path, not under the module REPORTS_DIR"
    # Dossier was found and loaded (not fallen back to graceful-degradation empty skeleton):
    # the near-miss score_target must come from the real file, not be None.
    assert analysis["near_miss_upgrade_window"]["score_target"] == 0.44, "Near-miss score_target must be loaded from the actual dossier file beside the command board"


def test_diagnostics_uses_command_board_action_row_when_dossier_anchor_is_empty(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    candidate_dossier_path = reports_root / "btst_tplus2_candidate_dossier_300683_latest.json"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"
    near_miss_report_dir = reports_root / "corridor_probe_683"

    _write_json(
        candidate_dossier_path,
        {
            "candidate_ticker": "300683",
            "per_window_summaries": [
                {
                    "report_label": "20260327",
                    "report_dir": None,
                    "decision": None,
                    "candidate_source": None,
                    "downstream_bottleneck": None,
                }
            ],
            "current_plan_visibility_summary": {"current_plan_visibility_gap_report_dirs": []},
        },
    )
    _write_json(
        command_board_path,
        {
            "focus_ticker": "300683",
            "confirmed_selected_trade_dates": [],
            "next_target_trade_dates": ["2026-03-27"],
            "visibility_gap_trade_dates": [],
            "action_rows": [
                {
                    "trade_date": "2026-03-27",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.3882,
                    "report_dir": str(near_miss_report_dir),
                    "downstream_bottleneck": "broad_scope_shadow_role_history",
                    "action_tier": "upgrade_near_miss_window",
                }
            ],
        },
    )
    _write_json(
        near_miss_report_dir / "selection_artifacts" / "2026-03-27" / "selection_target_replay_input.json",
        {
            "selection_targets": {
                "300683": {
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.3882,
                        "metrics_payload": {
                            "breakout_stage": "confirmed_breakout",
                            "trend_acceleration": 0.78,
                            "close_strength": 0.83,
                            "volume_expansion_quality": 0.18,
                            "upstream_shadow_catalyst_relief_applied": False,
                        },
                    }
                }
            }
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        candidate_dossier_path=candidate_dossier_path,
        command_board_path=command_board_path,
    )

    assert analysis["near_miss_upgrade_window"]["trade_date"] == "2026-03-27"
    assert analysis["near_miss_upgrade_window"]["report_dir"] == str(near_miss_report_dir)
    assert analysis["near_miss_upgrade_window"]["decision"] == "near_miss"
    assert analysis["near_miss_upgrade_window"]["score_target"] == 0.3882
