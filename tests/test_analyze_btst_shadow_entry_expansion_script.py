from __future__ import annotations

import json

from scripts.analyze_btst_shadow_entry_expansion import analyze_btst_shadow_entry_expansion


def test_analyze_btst_shadow_entry_expansion_flags_unique_threshold_only_case(tmp_path):
    execution_summary = tmp_path / "execution_summary.json"
    frontier_report = tmp_path / "frontier_report.json"
    scoreboard_report = tmp_path / "scoreboard_report.json"

    execution_summary.write_text(
        json.dumps(
            {
                "generated_on": "2026-03-30",
                "experiments": [
                    {
                        "ticker": "300383",
                        "action_tier": "shadow_keep",
                        "target_case_count": 1,
                        "next_high_return_mean": 0.0527,
                        "next_close_return_mean": 0.0146,
                        "next_close_positive_rate": 1.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    frontier_report.write_text(
        json.dumps(
            {
                "minimal_near_miss_rows": [
                    {
                        "trade_date": "2026-03-26",
                        "ticker": "300383",
                        "near_miss_threshold": 0.42,
                        "stale_weight": 0.12,
                        "extension_weight": 0.08,
                        "adjustment_cost": 0.04,
                    },
                    {
                        "trade_date": "2026-03-23",
                        "ticker": "600821",
                        "near_miss_threshold": 0.38,
                        "stale_weight": 0.1,
                        "extension_weight": 0.08,
                        "adjustment_cost": 0.1,
                    },
                    {
                        "trade_date": "2026-03-25",
                        "ticker": "002015",
                        "near_miss_threshold": 0.38,
                        "stale_weight": 0.12,
                        "extension_weight": 0.04,
                        "adjustment_cost": 0.12,
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    scoreboard_report.write_text(
        json.dumps(
            {
                "entries": [
                    {"ticker": "300383", "priority_rank": 2, "lane_type": "targeted_boundary_release"},
                    {"ticker": "002015", "priority_rank": 3, "lane_type": "recurring_frontier_release"},
                    {"ticker": "600821", "priority_rank": 4, "lane_type": "recurring_frontier_release"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_shadow_entry_expansion(
        execution_summary,
        frontier_report_path=frontier_report,
        scoreboard_report_path=scoreboard_report,
        ticker="300383",
    )

    assert analysis["frontier_uniqueness"]["current_shadow_is_unique_threshold_only"] is True
    assert analysis["frontier_uniqueness"]["same_rule_expansion_ready"] is False
    assert analysis["expansion_verdict"] == "hold_shadow_only_no_same_rule_expansion"
    assert analysis["priority_peer_rows"][0]["ticker"] in {"002015", "600821"}
