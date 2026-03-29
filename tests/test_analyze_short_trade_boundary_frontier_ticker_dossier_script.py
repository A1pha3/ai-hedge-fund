from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_frontier_ticker_dossier import analyze_short_trade_boundary_frontier_ticker_dossier


def test_analyze_short_trade_boundary_frontier_ticker_dossier_extracts_single_ticker(tmp_path):
    dossier_report = tmp_path / "dossiers.json"
    dossier_report.write_text(
        json.dumps(
            {
                "dossiers": [
                    {"ticker": "600821", "priority_rank": 1, "occurrence_count": 3, "trade_dates": ["2026-03-23"], "minimal_adjustment_cost": 0.1, "max_adjustment_cost": 0.12, "gap_to_near_miss_mean": 0.0931, "dominant_pattern": {}, "next_open_return_mean": -0.0092, "next_high_return_mean": 0.0503, "next_close_return_mean": -0.002, "next_high_hit_rate_at_threshold": 0.6667, "next_close_positive_rate": 0.3333, "pattern_label": "recurring frontier with intraday upside", "top_outcome_case": {"ticker": "600821"}, "worst_close_case": {"ticker": "600821"}},
                    {"ticker": "002015", "priority_rank": 2, "occurrence_count": 3, "trade_dates": ["2026-03-23"], "minimal_adjustment_cost": 0.12, "max_adjustment_cost": 0.14, "gap_to_near_miss_mean": 0.0985, "dominant_pattern": {}, "next_open_return_mean": -0.001, "next_high_return_mean": 0.0339, "next_close_return_mean": -0.0057, "next_high_hit_rate_at_threshold": 0.6667, "next_close_positive_rate": 0.6667, "pattern_label": "recurring frontier with intraday upside", "top_outcome_case": {"ticker": "002015"}, "worst_close_case": {"ticker": "002015"}},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_boundary_frontier_ticker_dossier(dossier_report, ticker="600821")

    assert analysis["dossier"]["ticker"] == "600821"
    assert "intraday frontier" in analysis["recommendation"]


def test_analyze_short_trade_boundary_frontier_ticker_dossier_marks_close_continuation_control(tmp_path):
    dossier_report = tmp_path / "dossiers.json"
    dossier_report.write_text(
        json.dumps(
            {
                "dossiers": [
                    {"ticker": "002015", "priority_rank": 2, "occurrence_count": 3, "trade_dates": ["2026-03-23"], "minimal_adjustment_cost": 0.12, "max_adjustment_cost": 0.14, "gap_to_near_miss_mean": 0.0985, "dominant_pattern": {}, "next_open_return_mean": -0.001, "next_high_return_mean": 0.0339, "next_close_return_mean": -0.0057, "next_high_hit_rate_at_threshold": 0.6667, "next_close_positive_rate": 0.6667, "pattern_label": "recurring frontier with intraday upside", "top_outcome_case": {"ticker": "002015"}, "worst_close_case": {"ticker": "002015"}},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_boundary_frontier_ticker_dossier(dossier_report, ticker="002015")

    assert analysis["dossier"]["ticker"] == "002015"
    assert "close continuation 对照样本" in analysis["recommendation"]
