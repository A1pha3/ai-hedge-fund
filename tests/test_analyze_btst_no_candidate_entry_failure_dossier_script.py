from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_no_candidate_entry_failure_dossier import analyze_btst_no_candidate_entry_failure_dossier


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_replay_input(report_dir: Path, *, trade_date: str, rejected_tickers: list[str]) -> None:
    payload = {
        "artifact_version": "v1",
        "trade_date": trade_date,
        "target_mode": "dual_target",
        "watchlist": [],
        "rejected_entries": [
            {
                "ticker": ticker,
                "candidate_source": "watchlist_filter_diagnostics",
                "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
                "reason": "decision_avoid",
            }
            for ticker in rejected_tickers
        ],
        "supplemental_short_trade_entries": [],
        "selection_targets": {
            ticker: {"short_trade": {"decision": "rejected"}}
            for ticker in rejected_tickers
        },
        "buy_order_tickers": [],
    }
    selection_dir = report_dir / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / "selection_target_replay_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_absent_replay_input(report_dir: Path, *, trade_date: str) -> None:
    payload = {
        "artifact_version": "v1",
        "trade_date": trade_date,
        "target_mode": "dual_target",
        "watchlist": [],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "selection_targets": {},
        "buy_order_tickers": [],
    }
    selection_dir = report_dir / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / "selection_target_replay_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_analyze_btst_no_candidate_entry_failure_dossier_distinguishes_absence_and_semantic_miss(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    absent_report = reports_root / "paper_trading_20260302_20260313_btst_research_replay"
    semantic_miss_report = reports_root / "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"
    _write_replay_input(absent_report, trade_date="2026-03-23", rejected_tickers=["300394"])
    _write_replay_input(semantic_miss_report, trade_date="2026-03-25", rejected_tickers=["300394", "003036"])

    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "rows": [
                {
                    "trade_date": "2026-03-23",
                    "ticker": "300720",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": absent_report.name,
                    "strict_btst_goal_case": True,
                },
                {
                    "trade_date": "2026-03-25",
                    "ticker": "003036",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": semantic_miss_report.name,
                    "strict_btst_goal_case": False,
                },
            ],
            "no_candidate_entry_summary": {
                "top_ticker_rows": [
                    {"ticker": "300720", "occurrence_count": 1, "strict_goal_case_count": 1},
                    {"ticker": "003036", "occurrence_count": 1, "strict_goal_case_count": 0},
                ]
            },
        },
    )
    action_board_path = _write_json(
        reports_root / "btst_no_candidate_entry_action_board_latest.json",
        {
            "reports_root": str(reports_root.resolve()),
            "priority_queue": [
                {"priority_rank": 1, "ticker": "300720", "primary_report_dir": absent_report.name},
                {"priority_rank": 2, "ticker": "003036", "primary_report_dir": semantic_miss_report.name},
            ],
            "window_hotspot_rows": [
                {"priority_rank": 1, "report_dir": semantic_miss_report.name, "top_focus_tickers": ["003036"]},
            ],
        },
    )
    replay_bundle_path = _write_json(
        reports_root / "btst_no_candidate_entry_replay_bundle_latest.json",
        {
            "priority_replay_rows": [
                {
                    "ticker": "300720",
                    "candidate_entry_status": "no_candidate_entries_filtered",
                    "best_variant_name": "weak_structure_triplet",
                    "viable_recall_probe": False,
                    "comparison_note": "ticker absent from filtered candidate-entry rows",
                },
                {
                    "ticker": "003036",
                    "candidate_entry_status": "misses_focus_tickers",
                    "best_variant_name": "weak_structure_triplet",
                    "viable_recall_probe": False,
                    "comparison_note": "filtered candidate-entry rows exist but focus ticker missed",
                },
            ],
            "hotspot_replay_rows": [
                {
                    "report_dir": semantic_miss_report.name,
                    "candidate_entry_status": "misses_focus_tickers",
                    "best_variant_name": "weak_structure_triplet",
                    "viable_recall_probe": False,
                    "comparison_note": "window hotspot misses focus ticker",
                }
            ],
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "priority_ticker_dossiers": [
                {"ticker": "300720", "dominant_recall_stage": "absent_from_candidate_pool"},
                {"ticker": "003036", "dominant_recall_stage": "watchlist_visible_but_missing_candidate_entry"},
            ]
        },
    )

    analysis = analyze_btst_no_candidate_entry_failure_dossier(
        tradeable_pool_path,
        action_board_path=action_board_path,
        replay_bundle_path=replay_bundle_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
        priority_limit=2,
        hotspot_limit=1,
    )

    assert analysis["priority_failure_class_counts"] == {
        "upstream_absent_from_replay_inputs": 1,
        "candidate_entry_semantic_miss": 1,
    }
    assert analysis["priority_handoff_stage_counts"] == {
        "absent_from_watchlist": 1,
        "candidate_entry_visible_and_selection_target_attached": 1,
    }
    assert analysis["hotspot_failure_class_counts"] == {
        "hotspot_candidate_entry_semantic_miss": 1,
    }
    assert analysis["top_upstream_absence_tickers"] == ["300720"]
    assert analysis["top_absent_from_watchlist_tickers"] == ["300720"]
    assert analysis["top_absent_from_candidate_pool_breakpoint_tickers"] == ["300720"]
    assert analysis["top_candidate_entry_semantic_miss_tickers"] == ["003036"]
    assert "candidate_pool snapshot 都没有进入" in analysis["recommendation"]
    assert analysis["priority_handoff_action_queue"][0]["task_id"] == "300720_absent_from_watchlist"
    assert analysis["next_actions"][0] == "先补 ['300720'] 的 Layer A candidate_pool 召回观测，确认它们为何连 candidate_pool snapshot 都没进入。"

    dossiers_by_ticker = {row["ticker"]: row for row in analysis["priority_ticker_dossiers"]}
    assert dossiers_by_ticker["300720"]["primary_failure_class"] == "upstream_absent_from_replay_inputs"
    assert dossiers_by_ticker["300720"]["handoff_stage"] == "absent_from_watchlist"
    assert dossiers_by_ticker["300720"]["watchlist_recall_stage"] == "absent_from_candidate_pool"
    assert dossiers_by_ticker["300720"]["replay_input_visible_report_count"] == 0
    assert dossiers_by_ticker["003036"]["primary_failure_class"] == "candidate_entry_semantic_miss"
    assert dossiers_by_ticker["003036"]["handoff_stage"] == "candidate_entry_visible_and_selection_target_attached"
    assert dossiers_by_ticker["003036"]["watchlist_recall_stage"] == "watchlist_visible_but_missing_candidate_entry"
    assert dossiers_by_ticker["003036"]["candidate_entry_visible_report_count"] == 1

    hotspot_dossier = analysis["hotspot_report_dossiers"][0]
    assert hotspot_dossier["primary_failure_class"] == "hotspot_candidate_entry_semantic_miss"
    assert hotspot_dossier["focus_ticker_evidence"][0]["ticker"] == "003036"
    assert hotspot_dossier["dominant_handoff_stage"] == "candidate_entry_visible_and_selection_target_attached"


def test_analyze_btst_no_candidate_entry_failure_dossier_promotes_corridor_primary_shadow_ticker(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    first_report = reports_root / "paper_trading_a"
    second_report = reports_root / "paper_trading_b"
    _write_absent_replay_input(first_report, trade_date="2026-03-23")
    _write_absent_replay_input(second_report, trade_date="2026-03-23")

    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "rows": [
                {
                    "trade_date": "2026-03-23",
                    "ticker": "688796",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": first_report.name,
                    "strict_btst_goal_case": True,
                },
                {
                    "trade_date": "2026-03-23",
                    "ticker": "300683",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": second_report.name,
                    "strict_btst_goal_case": True,
                },
            ],
            "no_candidate_entry_summary": {
                "top_ticker_rows": [
                    {"ticker": "688796", "occurrence_count": 1, "strict_goal_case_count": 1},
                    {"ticker": "300683", "occurrence_count": 1, "strict_goal_case_count": 1},
                ]
            },
        },
    )
    action_board_path = _write_json(
        reports_root / "btst_no_candidate_entry_action_board_latest.json",
        {
            "reports_root": str(reports_root.resolve()),
            "priority_queue": [
                {"priority_rank": 1, "ticker": "688796", "primary_report_dir": first_report.name},
                {"priority_rank": 2, "ticker": "300683", "primary_report_dir": second_report.name},
            ],
            "window_hotspot_rows": [],
        },
    )
    replay_bundle_path = _write_json(
        reports_root / "btst_no_candidate_entry_replay_bundle_latest.json",
        {"priority_replay_rows": [], "hotspot_replay_rows": []},
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "priority_ticker_dossiers": [
                {"ticker": "688796", "dominant_recall_stage": "absent_from_candidate_pool"},
                {"ticker": "300683", "dominant_recall_stage": "absent_from_candidate_pool"},
            ]
        },
    )
    corridor_shadow_pack_path = _write_json(
        reports_root / "btst_candidate_pool_corridor_shadow_pack_latest.json",
        {
            "shadow_status": "ready_for_primary_shadow_replay",
            "primary_shadow_replay": {"ticker": "300683"},
        },
    )

    analysis = analyze_btst_no_candidate_entry_failure_dossier(
        tradeable_pool_path,
        action_board_path=action_board_path,
        replay_bundle_path=replay_bundle_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
        corridor_shadow_pack_path=corridor_shadow_pack_path,
        priority_limit=2,
        hotspot_limit=0,
    )

    assert analysis["corridor_primary_shadow_ticker"] == "300683"
    assert analysis["top_absent_from_watchlist_tickers"][:2] == ["300683", "688796"]
    assert analysis["priority_handoff_action_queue"][0]["task_id"] == "300683_absent_from_watchlist"
    assert analysis["priority_ticker_dossiers"][0]["ticker"] == "300683"
    assert analysis["priority_ticker_dossiers"][0]["priority_rank"] == 1
