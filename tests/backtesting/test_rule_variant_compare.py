from __future__ import annotations

import json
from pathlib import Path

from src.backtesting.rule_variant_compare import build_rule_variants, summarize_portfolio_values, summarize_timing_log


def test_build_rule_variants_supports_expected_names():
    variants = build_rule_variants(["baseline", "profitability_inactive", "neutral_mean_reversion_partial_third_dual_leg_034_no_hard_cliff"])

    assert [variant.name for variant in variants] == [
        "baseline",
        "profitability_inactive",
        "neutral_mean_reversion_partial_third_dual_leg_034_no_hard_cliff",
    ]
    assert variants[1].env["LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE"] == "inactive"
    assert variants[2].env["LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE"] == "partial_mr_third_dual_leg_034_no_hard_cliff"


def test_summarize_portfolio_values_computes_total_return():
    summary = summarize_portfolio_values(
        [
            {"Portfolio Value": 100000.0},
            {"Portfolio Value": 103500.0},
        ]
    )

    assert summary["start_value"] == 100000.0
    assert summary["end_value"] == 103500.0
    assert summary["total_return_pct"] == 3.5
    assert summary["portfolio_value_points"] == 2


def test_summarize_timing_log_aggregates_pipeline_day_events(tmp_path: Path):
    timing_log_path = tmp_path / "variant.timings.jsonl"
    events = [
        {
            "event": "prefetch_complete",
            "timing_seconds": {"prefetch": 1.2},
        },
        {
            "event": "pipeline_day_timing",
            "executed_order_count": 1,
            "timing_seconds": {"total_day": 10.0, "post_market": 7.0},
            "current_plan": {
                "counts": {
                    "layer_a_count": 120,
                    "layer_b_count": 2,
                    "layer_c_count": 2,
                    "watchlist_count": 1,
                    "buy_order_count": 1,
                    "sell_order_count": 0,
                }
            },
        },
        {
            "event": "pipeline_day_timing",
            "executed_order_count": 0,
            "timing_seconds": {"total_day": 14.0, "post_market": 9.0},
            "current_plan": {
                "counts": {
                    "layer_a_count": 100,
                    "layer_b_count": 0,
                    "layer_c_count": 0,
                    "watchlist_count": 0,
                    "buy_order_count": 0,
                    "sell_order_count": 1,
                }
            },
        },
    ]
    timing_log_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    summary = summarize_timing_log(timing_log_path)

    assert summary["pipeline_days"] == 2
    assert summary["avg_total_day_seconds"] == 12.0
    assert summary["avg_post_market_seconds"] == 8.0
    assert summary["avg_layer_a_count"] == 110.0
    assert summary["avg_layer_b_count"] == 1.0
    assert summary["avg_buy_order_count"] == 0.5
    assert summary["nonzero_layer_b_days"] == 1
    assert summary["nonzero_buy_order_days"] == 1
    assert summary["executed_order_days"] == 1