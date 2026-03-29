from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_recurring_frontier_dossiers import analyze_short_trade_boundary_recurring_frontier_dossiers


def test_analyze_short_trade_boundary_recurring_frontier_dossiers_joins_outcomes(tmp_path):
    recurring_report = tmp_path / "recurring.json"
    outcome_report = tmp_path / "outcome.json"

    recurring_report.write_text(
        json.dumps(
            {
                "priority_queue": [
                    {
                        "ticker": "600821",
                        "occurrence_count": 3,
                        "trade_dates": ["2026-03-23", "2026-03-25", "2026-03-26"],
                        "baseline_score_mean": 0.3669,
                        "gap_to_near_miss_mean": 0.0931,
                        "minimal_adjustment_cost": 0.1,
                        "max_adjustment_cost": 0.12,
                        "threshold_only_rescue_count": 0,
                        "dominant_pattern": {"near_miss_thresholds": [0.38]},
                    },
                    {
                        "ticker": "002015",
                        "occurrence_count": 3,
                        "trade_dates": ["2026-03-23", "2026-03-24", "2026-03-25"],
                        "baseline_score_mean": 0.3615,
                        "gap_to_near_miss_mean": 0.0985,
                        "minimal_adjustment_cost": 0.12,
                        "max_adjustment_cost": 0.14,
                        "threshold_only_rescue_count": 0,
                        "dominant_pattern": {"near_miss_thresholds": [0.38]},
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    outcome_report.write_text(
        json.dumps(
            {
                "next_high_hit_threshold": 0.02,
                "rows": [
                    {"trade_date": "2026-03-23", "ticker": "600821", "data_status": "ok", "next_open_return": 0.01, "next_high_return": 0.10, "next_close_return": 0.10},
                    {"trade_date": "2026-03-25", "ticker": "600821", "data_status": "ok", "next_open_return": -0.03, "next_high_return": 0.04, "next_close_return": -0.07},
                    {"trade_date": "2026-03-26", "ticker": "600821", "data_status": "ok", "next_open_return": -0.01, "next_high_return": 0.01, "next_close_return": -0.03},
                    {"trade_date": "2026-03-23", "ticker": "002015", "data_status": "ok", "next_open_return": 0.03, "next_high_return": 0.06, "next_close_return": 0.04},
                    {"trade_date": "2026-03-24", "ticker": "002015", "data_status": "ok", "next_open_return": -0.01, "next_high_return": 0.057, "next_close_return": 0.011},
                    {"trade_date": "2026-03-25", "ticker": "002015", "data_status": "ok", "next_open_return": -0.019, "next_high_return": -0.016, "next_close_return": -0.0704},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_boundary_recurring_frontier_dossiers(recurring_report, outcome_report)

    assert analysis["ticker_count"] == 2
    assert analysis["dossiers"][0]["ticker"] == "600821"
    assert analysis["dossiers"][0]["pattern_label"] == "recurring frontier with intraday upside"
    assert analysis["dossiers"][1]["ticker"] == "002015"
    assert analysis["dossiers"][1]["next_close_positive_rate"] == 0.6667
