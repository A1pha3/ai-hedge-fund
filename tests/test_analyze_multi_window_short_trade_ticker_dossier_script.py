from __future__ import annotations

import json

from scripts.analyze_multi_window_short_trade_ticker_dossier import analyze_multi_window_short_trade_ticker_dossier


def test_analyze_multi_window_short_trade_ticker_dossier_extracts_near_miss_candidate(tmp_path):
    candidate_report = tmp_path / "candidates.json"
    outcome_report = tmp_path / "outcomes.json"
    candidate_report.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "001309",
                        "short_trade_trade_date_count": 3,
                        "distinct_window_count": 1,
                        "distinct_report_count": 2,
                        "role_counts": {"layer_b_pool_below_fast_score_threshold": 10, "short_trade_boundary_near_miss": 3},
                        "transition_locality": "emergent_local_baseline",
                    }
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
                    {"ticker": "001309", "data_status": "ok", "next_open_return": 0.01, "next_high_return": 0.05, "next_close_return": 0.03},
                    {"ticker": "001309", "data_status": "ok", "next_open_return": -0.01, "next_high_return": 0.04, "next_close_return": 0.01},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_multi_window_short_trade_ticker_dossier(candidate_report, outcome_report, ticker="001309")

    assert analysis["dossier"]["ticker"] == "001309"
    assert analysis["dossier"]["pattern_label"] == "emergent near-miss with close continuation"
