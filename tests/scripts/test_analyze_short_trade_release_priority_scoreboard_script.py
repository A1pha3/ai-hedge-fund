from __future__ import annotations

import json

from scripts.analyze_short_trade_release_priority_scoreboard import analyze_short_trade_release_priority_scoreboard


def test_analyze_short_trade_release_priority_scoreboard_ranks_lower_cost_stronger_close_first(tmp_path):
    first = tmp_path / "001309.json"
    second = tmp_path / "300383.json"
    third = tmp_path / "600821.json"

    first.write_text(
        json.dumps(
            {
                "ticker": "001309",
                "select_threshold": 0.56,
                "target_case_count": 2,
                "promoted_target_case_count": 2,
                "next_high_return_mean": 0.051,
                "next_close_return_mean": 0.0414,
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "target_case_count": 1,
                "promoted_target_case_count": 1,
                "target_cases": [
                    {
                        "ticker": "300383",
                        "near_miss_threshold": 0.42,
                        "next_high_return": 0.0527,
                        "next_close_return": 0.0146,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    third.write_text(
        json.dumps(
            {
                "ticker": "600821",
                "target_case_count": 3,
                "promoted_target_case_count": 3,
                "next_high_return_mean": 0.0503,
                "next_close_return_mean": -0.002,
                "next_high_hit_rate_at_threshold": 0.6667,
                "next_close_positive_rate": 0.3333,
                "target_cases": [
                    {"adjustment_cost": 0.1},
                    {"adjustment_cost": 0.12},
                    {"adjustment_cost": 0.12},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_release_priority_scoreboard([str(second), str(first), str(third)])

    assert analysis["entries"][0]["ticker"] == "001309"
    assert analysis["entries"][1]["ticker"] == "300383"
