from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_pool_corridor_window_command_board import (
    analyze_btst_candidate_pool_corridor_window_command_board,
    render_btst_candidate_pool_corridor_window_command_board_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_snapshot(report_dir: Path, trade_date: str, rows: list[dict]) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / trade_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trade_date": trade_date.replace("-", ""),
        "rows": [{**row, "trade_date": trade_date.replace("-", "")} for row in rows],
    }
    (snapshot_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_window_command_board_prioritizes_near_miss_then_visibility_gap(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    manifest_path = reports_root / "report_manifest_latest.json"
    persistence_path = reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
    candidate_dossier_path = reports_root / "btst_tplus2_candidate_dossier_300720_latest.json"

    _write_json(
        manifest_path,
        {
            "continuation_promotion_ready_summary": {
                "focus_ticker": "300720",
                "combined_merge_ready_evidence_trade_dates": ["2026-03-31"],
                "combined_evidence_trade_dates": ["2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visible_trade_dates": ["2026-03-23", "2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visibility_gap_trade_dates": ["2026-03-27"],
            }
        },
    )
    _write_json(
        persistence_path,
        {
            "focus_ticker": "300720",
            "continuation_readiness": {"missing_independent_sample_count": 1},
        },
    )
    _write_json(
        candidate_dossier_path,
        {
            "recent_window_summaries": [
                {
                    "report_label": "2026-03-31",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "score_target": 0.4583,
                    "report_dir": "/tmp/selected",
                    "downstream_bottleneck": "selected",
                },
                {
                    "report_label": "2026-04-06",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4555,
                    "report_dir": "/tmp/nearmiss",
                    "downstream_bottleneck": "catalyst_relief_validated",
                },
            ]
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_window_command_board(
        manifest_path=manifest_path,
        persistence_dossier_path=persistence_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["confirmed_selected_trade_dates"] == ["2026-03-31"]
    assert analysis["next_target_trade_dates"][:2] == ["2026-04-06", "2026-03-27"]
    assert analysis["action_rows"][0]["action_tier"] == "upgrade_near_miss_window"
    assert analysis["action_rows"][1]["action_tier"] == "recover_visibility_gap_window"

    markdown = render_btst_candidate_pool_corridor_window_command_board_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Window Command Board" in markdown
    assert "collect_one_more_selected_window" in markdown


def test_analyze_btst_candidate_pool_corridor_window_command_board_handles_missing_candidate_dossier(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    manifest_path = reports_root / "report_manifest_latest.json"
    persistence_path = reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        manifest_path,
        {
            "continuation_promotion_ready_summary": {
                "focus_ticker": "300683",
                "combined_merge_ready_evidence_trade_dates": [],
                "combined_evidence_trade_dates": ["2026-04-15"],
                "candidate_dossier_current_plan_visible_trade_dates": [],
                "candidate_dossier_current_plan_visibility_gap_trade_dates": ["2026-04-15"],
            }
        },
    )
    _write_json(
        persistence_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {"missing_independent_sample_count": 1},
        },
    )

    analysis = analyze_btst_candidate_pool_corridor_window_command_board(
        manifest_path=manifest_path,
        persistence_dossier_path=persistence_path,
    )

    assert analysis["focus_ticker"] == "300683"
    assert analysis["verdict"] == "missing_candidate_dossier"
    assert analysis["next_target_trade_dates"] == ["2026-04-15"]
    assert analysis["action_rows"][0]["action_tier"] == "recover_visibility_gap_window"


def test_analyze_btst_candidate_pool_corridor_window_command_board_falls_back_to_broad_scope_shadow_windows(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    manifest_path = reports_root / "report_manifest_latest.json"
    persistence_path = reports_root / "btst_candidate_pool_corridor_persistence_dossier_latest.json"

    _write_json(
        manifest_path,
        {
            "continuation_promotion_ready_summary": {
                "focus_ticker": "300720",
                "combined_merge_ready_evidence_trade_dates": ["2026-03-31"],
                "combined_evidence_trade_dates": ["2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visible_trade_dates": ["2026-03-23", "2026-03-31", "2026-04-06"],
                "candidate_dossier_current_plan_visibility_gap_trade_dates": ["2026-03-27"],
            }
        },
    )
    _write_json(
        persistence_path,
        {
            "focus_ticker": "300683",
            "continuation_readiness": {"missing_independent_sample_count": 1},
        },
    )

    report_a = reports_root / "paper_trading_20260326_20260331_live_m2_7_short_trade_only_20260415_corridor_probe_300683_301188"
    report_b = reports_root / "paper_trading_2026-04-06_2026-04-10_live_m2_7_short_trade_only_20260413_core6_today_btst"
    _write_snapshot(
        report_a,
        "2026-03-27",
        [
            {"ticker": "300683", "candidate_source": "upstream_liquidity_corridor_shadow", "short_trade": {"decision": "near_miss", "score_target": 0.3882}},
        ],
    )
    _write_snapshot(
        report_b,
        "2026-04-06",
        [
            {"ticker": "300683", "candidate_source": "upstream_liquidity_corridor_shadow", "short_trade": {"decision": "near_miss", "score_target": 0.3752}},
        ],
    )

    analysis = analyze_btst_candidate_pool_corridor_window_command_board(
        manifest_path=manifest_path,
        persistence_dossier_path=persistence_path,
    )

    assert analysis["focus_ticker"] == "300683"
    assert analysis["verdict"] == "missing_candidate_dossier"
    assert analysis["exploratory_trade_dates"] == ["2026-03-27", "2026-04-06"]
    assert analysis["next_target_trade_dates"] == ["2026-03-27", "2026-04-06"]
    assert analysis["action_rows"][0]["trade_date"] == "2026-03-27"
    assert analysis["action_rows"][0]["decision"] == "near_miss"
    assert analysis["action_rows"][1]["trade_date"] == "2026-04-06"
