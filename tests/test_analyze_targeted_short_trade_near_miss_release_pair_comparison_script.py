from __future__ import annotations

import json

from scripts.analyze_targeted_short_trade_near_miss_release_pair_comparison import analyze_targeted_short_trade_near_miss_release_pair_comparison


def test_analyze_targeted_short_trade_near_miss_release_pair_comparison_prioritizes_lower_cost_close_continuation(tmp_path):
    left_report = tmp_path / "left.json"
    right_report = tmp_path / "right.json"

    left_report.write_text(
        json.dumps(
            {
                "ticker": "001309",
                "select_threshold": 0.56,
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
    right_report.write_text(
        json.dumps(
            {
                "ticker": "300620",
                "select_threshold": 0.53,
                "next_high_return_mean": 0.0479,
                "next_close_return_mean": -0.0014,
                "next_high_hit_rate_at_threshold": 0.5,
                "next_close_positive_rate": 0.5,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_targeted_short_trade_near_miss_release_pair_comparison(left_report, right_report)

    assert analysis["comparison"]["select_threshold_delta"] == 0.03
    assert "001309" in analysis["recommendation"]
