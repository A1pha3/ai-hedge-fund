from __future__ import annotations

from scripts.btst_analysis_utils import compare_reports, summarize_distribution


def test_summarize_distribution_includes_profit_aware_percentiles() -> None:
    summary = summarize_distribution([-0.05, -0.01, 0.02, 0.06, 0.10])

    assert summary == {
        "count": 5,
        "min": -0.05,
        "max": 0.10,
        "mean": 0.024,
        "median": 0.02,
        "p10": -0.034,
        "p25": -0.01,
        "p75": 0.06,
        "p90": 0.084,
    }


def test_compare_reports_includes_profit_aware_tradeable_tail_deltas() -> None:
    baseline = {
        "label": "baseline",
        "surface_summaries": {
            "tradeable": {
                "total_count": 5,
                "closed_cycle_count": 5,
                "next_high_hit_rate_at_threshold": 0.80,
                "next_close_positive_rate": 0.80,
                "t_plus_2_close_positive_rate": 0.80,
                "next_high_return_distribution": {"mean": 0.0549},
                "next_close_return_distribution": {"mean": 0.0215, "median": 0.0267, "p10": -0.0295},
                "t_plus_2_close_return_distribution": {"mean": 0.0221, "median": 0.0152, "p10": -0.0036},
            }
        },
        "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
    }
    variant = {
        "label": "variant",
        "surface_summaries": {
            "tradeable": {
                "total_count": 6,
                "closed_cycle_count": 6,
                "next_high_hit_rate_at_threshold": 0.6667,
                "next_close_positive_rate": 0.6667,
                "t_plus_2_close_positive_rate": 0.8333,
                "next_high_return_distribution": {"mean": 0.0473},
                "next_close_return_distribution": {"mean": 0.0135, "median": 0.0183, "p10": -0.0282},
                "t_plus_2_close_return_distribution": {"mean": 0.0248, "median": 0.0239, "p10": -0.0036},
            }
        },
        "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
    }

    comparison = compare_reports(
        baseline,
        variant,
        guardrail_next_high_hit_rate=0.5217,
        guardrail_next_close_positive_rate=0.5652,
    )

    assert comparison["tradeable_surface_delta"]["next_close_return_mean"] == -0.008
    assert comparison["tradeable_surface_delta"]["next_close_return_median"] == -0.0084
    assert comparison["tradeable_surface_delta"]["next_close_return_p10"] == 0.0013
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_return_mean"] == 0.0027
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_return_median"] == 0.0087
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_return_p10"] == 0.0
