from __future__ import annotations

import json

from scripts.analyze_short_trade_boundary_expansion_cases import analyze_short_trade_boundary_expansion_cases


def test_analyze_short_trade_boundary_expansion_cases_classifies_added_cases(tmp_path):
    targeted_report = tmp_path / "targeted.json"
    filtered_report = tmp_path / "filtered.json"
    targeted_report.write_text(
        json.dumps(
            {
                "recommended_variant": {
                    "variant_name": "candidate_0.24_breakout_0.18_trend_0.22_volume_0.15_catalyst_0.00",
                    "thresholds": {"catalyst_freshness_min": 0.0},
                    "top_selected_rows": [
                        {"trade_date": "2026-03-25", "ticker": "300308", "score_b": 0.31, "candidate_score": 0.42, "next_high_return": 0.0264, "next_close_return": -0.0226},
                        {"trade_date": "2026-03-24", "ticker": "300274", "score_b": 0.35, "candidate_score": 0.34, "next_high_return": 0.0231, "next_close_return": 0.0146},
                    ],
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    filtered_report.write_text(
        json.dumps(
            {
                "rows": [
                    {"trade_date": "2026-03-25", "ticker": "300308", "failed_thresholds": {"catalyst_freshness": 0.12}, "failed_threshold_count": 1, "primary_reason": "catalyst_freshness_below_short_trade_boundary_floor"},
                    {"trade_date": "2026-03-24", "ticker": "300274", "failed_thresholds": {"volume_expansion_quality": 0.0001, "catalyst_freshness": 0.12}, "failed_threshold_count": 2, "primary_reason": "volume_expansion_below_short_trade_boundary_floor"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_boundary_expansion_cases(targeted_report, filtered_report)

    assert analysis["added_case_count"] == 2
    assert analysis["added_cases"][0]["release_trigger"] == "catalyst_floor_only"
    assert analysis["added_cases"][1]["release_trigger"] == "catalyst_plus_other_floors"
