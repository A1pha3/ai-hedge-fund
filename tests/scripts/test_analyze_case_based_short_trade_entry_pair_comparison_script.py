from __future__ import annotations

import json

from scripts.analyze_case_based_short_trade_entry_pair_comparison import analyze_case_based_short_trade_entry_pair_comparison


def test_analyze_case_based_short_trade_entry_pair_comparison_prioritizes_001309_over_300383(tmp_path):
    left = tmp_path / "001309.json"
    right = tmp_path / "300383.json"

    left.write_text(
        json.dumps(
            {
                "ticker": "001309",
                "adjustment_cost": 0.02,
                "target_case_count": 2,
                "next_high_return_mean": 0.051,
                "next_close_return_mean": 0.0414,
                "next_close_positive_rate": 1.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    right.write_text(
        json.dumps(
            {
                "ticker": "300383",
                "adjustment_cost": 0.04,
                "target_case_count": 1,
                "next_high_return_mean": 0.0527,
                "next_close_return_mean": 0.0146,
                "next_close_positive_rate": 1.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_case_based_short_trade_entry_pair_comparison(left, right)

    assert analysis["comparison"]["adjustment_cost_delta"] == -0.02
    assert "001309" in analysis["recommendation"]
