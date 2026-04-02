from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_watchlist_recall_dossier import analyze_btst_watchlist_recall_dossier


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_analyze_btst_watchlist_recall_dossier_splits_candidate_pool_and_watchlist_gaps(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    snapshots_root = tmp_path / "data" / "snapshots"
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-23",
                    "ticker": "300720",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_a",
                    "report_mode": "live_pipeline",
                    "system_seen_stage": None,
                    "candidate_source": None,
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.08,
                    "t_plus_2_close_return": 0.09,
                },
                {
                    "trade_date": "2026-03-24",
                    "ticker": "003036",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_b",
                    "report_mode": "live_pipeline",
                    "system_seen_stage": "boundary",
                    "candidate_source": "layer_b_boundary",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.07,
                    "t_plus_2_close_return": 0.08,
                },
                {
                    "trade_date": "2026-03-25",
                    "ticker": "301292",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_c",
                    "report_mode": "live_pipeline",
                    "system_seen_stage": None,
                    "candidate_source": None,
                    "strict_btst_goal_case": False,
                    "next_high_return": 0.06,
                    "t_plus_2_close_return": 0.02,
                },
            ],
            "no_candidate_entry_summary": {
                "top_ticker_rows": [
                    {"ticker": "300720"},
                    {"ticker": "003036"},
                    {"ticker": "301292"},
                ]
            },
        },
    )
    _write_json(
        reports_root / "btst_no_candidate_entry_failure_dossier_latest.json",
        {
            "top_absent_from_watchlist_tickers": ["300720", "003036", "301292"],
        },
    )
    _write_json(snapshots_root / "candidate_pool_20260323_top300.json", [{"ticker": "300394"}])
    _write_json(
        snapshots_root / "candidate_pool_20260324_top300.json",
        [
            {"ticker": "003036"},
            {"ticker": "300394"},
        ],
    )

    analysis = analyze_btst_watchlist_recall_dossier(
        tradeable_pool_path,
        failure_dossier_path=reports_root / "btst_no_candidate_entry_failure_dossier_latest.json",
        priority_limit=3,
    )

    assert analysis["priority_recall_stage_counts"] == {
        "missing_candidate_pool_snapshot": 1,
        "absent_from_candidate_pool": 1,
        "layer_b_visible_but_missing_watchlist": 1,
    }
    assert analysis["top_absent_from_candidate_pool_tickers"] == ["300720"]
    assert analysis["top_layer_b_visible_but_missing_watchlist_tickers"] == ["003036"]
    assert analysis["focus_tickers"] == ["300720", "003036", "301292"]
    assert analysis["action_queue"][0]["task_id"] == "300720_absent_from_candidate_pool"
    dossiers_by_ticker = {row["ticker"]: row for row in analysis["priority_ticker_dossiers"]}
    assert dossiers_by_ticker["300720"]["dominant_recall_stage"] == "absent_from_candidate_pool"
    assert dossiers_by_ticker["003036"]["dominant_recall_stage"] == "layer_b_visible_but_missing_watchlist"
    assert dossiers_by_ticker["301292"]["dominant_recall_stage"] == "missing_candidate_pool_snapshot"
    assert "candidate_pool snapshot 都没有进入" in analysis["recommendation"]