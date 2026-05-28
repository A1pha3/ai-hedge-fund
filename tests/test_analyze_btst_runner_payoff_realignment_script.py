from __future__ import annotations

import json
from pathlib import Path

from scripts import analyze_btst_runner_payoff_realignment as runner_payoff_realignment


def test_analyze_btst_runner_payoff_realignment_reports_recommended_staged_path(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "selected_summary": {"hit_rate_15pct": 0.20},
                "near_miss_summary": {"hit_rate_15pct": 0.4507},
                "formal_source_summary": {
                    "layer_c_watchlist": {"count": 2, "hit_rate_15pct": 0.0},
                    "short_trade_boundary": {"count": 3, "hit_rate_15pct": 0.0},
                },
                "runner_recall_summary": {
                    "watchlist_filter_diagnostics_false_negatives": 6,
                    "hit_rate_15pct": 0.6667,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner_payoff_realignment.analyze_btst_runner_payoff_realignment(
        weekly_validation_json=weekly_validation_json,
    )

    assert report["diagnosis"]["primary_problem"] == "formal_selected_target_misalignment"
    assert report["recommendation"]["status"] == "staged_formal_shrink_plus_runner_recall"
    assert report["recommendation"]["next_steps"] == [
        "formal_source_shadow",
        "payoff_first_runner_recall",
    ]
