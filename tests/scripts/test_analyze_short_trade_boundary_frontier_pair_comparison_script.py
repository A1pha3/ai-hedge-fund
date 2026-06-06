from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_frontier_pair_comparison import analyze_short_trade_boundary_frontier_pair_comparison


def test_analyze_short_trade_boundary_frontier_pair_comparison_compares_two_tickers(tmp_path):
    dossier_report = tmp_path / "dossiers.json"
    dossier_report.write_text(
        json.dumps(
            {
                "dossiers": [
                    {"ticker": "600821", "priority_rank": 1, "minimal_adjustment_cost": 0.1, "next_high_return_mean": 0.0503, "next_close_return_mean": -0.002, "next_close_positive_rate": 0.3333, "pattern_label": "recurring frontier with intraday upside"},
                    {"ticker": "002015", "priority_rank": 2, "minimal_adjustment_cost": 0.12, "next_high_return_mean": 0.0339, "next_close_return_mean": -0.0057, "next_close_positive_rate": 0.6667, "pattern_label": "recurring frontier with intraday upside"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_boundary_frontier_pair_comparison(
        dossier_report,
        left_ticker="600821",
        right_ticker="002015",
    )

    assert analysis["comparison"]["minimal_adjustment_cost_delta"] == -0.02
    assert analysis["comparison"]["next_high_return_mean_delta"] == 0.0164
    assert "600821" in analysis["recommendation"]