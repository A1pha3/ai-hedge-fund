from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_no_candidate_entry_action_board import analyze_btst_no_candidate_entry_action_board


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_analyze_btst_no_candidate_entry_action_board_prioritizes_recurring_cross_window_tickers(tmp_path: Path) -> None:
    report_path = _write_json(
        tmp_path / "btst_tradeable_opportunity_pool_march.json",
        {
            "generated_at": "2026-04-02T12:00:00",
            "reports_root": str((tmp_path / "data" / "reports").resolve()),
            "tradeable_opportunity_pool_count": 10,
            "no_candidate_entry_summary": {
                "count": 6,
                "share_of_tradeable_pool": 0.6,
            },
            "rows": [
                {
                    "trade_date": "2026-03-23",
                    "ticker": "300720",
                    "industry": "电气设备",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.081,
                    "next_close_return": 0.043,
                    "t_plus_2_close_return": 0.092,
                    "report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "dual_target",
                },
                {
                    "trade_date": "2026-03-24",
                    "ticker": "300720",
                    "industry": "电气设备",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.076,
                    "next_close_return": 0.041,
                    "t_plus_2_close_return": 0.087,
                    "report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "dual_target",
                },
                {
                    "trade_date": "2026-03-31",
                    "ticker": "300720",
                    "industry": "电气设备",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.071,
                    "next_close_return": 0.038,
                    "t_plus_2_close_return": 0.082,
                    "report_dir": "paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260401_catalyst_shadow_llm_digest",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "short_trade_only",
                },
                {
                    "trade_date": "2026-03-23",
                    "ticker": "003036",
                    "industry": "纺织机械",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.068,
                    "next_close_return": 0.04,
                    "t_plus_2_close_return": 0.081,
                    "report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "dual_target",
                },
                {
                    "trade_date": "2026-03-25",
                    "ticker": "003036",
                    "industry": "纺织机械",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": False,
                    "next_high_return": 0.053,
                    "next_close_return": 0.015,
                    "t_plus_2_close_return": 0.019,
                    "report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "dual_target",
                },
                {
                    "trade_date": "2026-03-25",
                    "ticker": "301292",
                    "industry": "化工原料",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": False,
                    "next_high_return": 0.051,
                    "next_close_return": 0.014,
                    "t_plus_2_close_return": 0.018,
                    "report_dir": "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh",
                    "report_mode": "live_pipeline",
                    "report_selection_target": "dual_target",
                },
            ],
        },
    )

    analysis = analyze_btst_no_candidate_entry_action_board(report_path)

    assert analysis["no_candidate_entry_count"] == 6
    assert analysis["no_candidate_entry_share_of_tradeable_pool"] == 0.6
    assert analysis["top_priority_tickers"][:2] == ["300720", "003036"]
    assert analysis["priority_queue"][0]["action_tier"] == "cross_window_semantic_replay"
    assert analysis["priority_queue"][0]["distinct_report_count"] == 2
    assert analysis["priority_queue"][0]["frontier_command"] is not None
    assert "--focus-ticker 300720" in analysis["priority_queue"][0]["frontier_command"]
    assert "--preserve-ticker 300394" in analysis["priority_queue"][0]["frontier_command"]
    assert analysis["window_hotspot_rows"][0]["report_dir"] == "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"
    assert analysis["window_hotspot_rows"][0]["top_focus_tickers"] == ["300720", "003036", "301292"]
    assert analysis["next_3_tasks"][0]["task_id"] == "300720_no_candidate_entry_replay"
    assert analysis["next_3_tasks"][2]["task_id"].endswith("_no_candidate_entry_window_batch")
    assert analysis["window_scan_command"] is not None
    assert "--focus-tickers 300720,003036,301292" in analysis["window_scan_command"]