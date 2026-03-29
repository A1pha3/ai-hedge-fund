from __future__ import annotations

import json

from scripts.analyze_recurring_frontier_release_pair_comparison import analyze_recurring_frontier_release_pair_comparison


def test_analyze_recurring_frontier_release_pair_comparison_separates_intraday_and_control_roles(tmp_path):
    left_report = tmp_path / "left.json"
    right_report = tmp_path / "right.json"

    left_report.write_text(
        json.dumps(
            {
                "ticker": "600821",
                "promoted_target_case_count": 3,
                "next_high_return_mean": 0.0503,
                "next_close_return_mean": -0.002,
                "next_high_hit_rate_at_threshold": 0.6667,
                "next_close_positive_rate": 0.3333,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    right_report.write_text(
        json.dumps(
            {
                "ticker": "002015",
                "promoted_target_case_count": 3,
                "next_high_return_mean": 0.0339,
                "next_close_return_mean": -0.0057,
                "next_high_hit_rate_at_threshold": 0.6667,
                "next_close_positive_rate": 0.6667,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_recurring_frontier_release_pair_comparison(left_report, right_report)

    assert analysis["comparison"]["next_high_return_mean_delta"] == 0.0164
    assert analysis["comparison"]["next_close_positive_rate_delta"] == -0.3334
    assert "intraday 主样本" in analysis["recommendation"]