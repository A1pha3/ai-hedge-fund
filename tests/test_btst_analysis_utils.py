from __future__ import annotations

import pandas as pd

from scripts.btst_analysis_utils import build_surface_summary, compare_reports, summarize_distribution, extract_btst_price_outcome


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
                "next_close_payoff_ratio": 1.2400,
                "next_close_profit_factor": 1.1200,
                "next_close_expectancy": 0.0041,
                "t_plus_2_close_payoff_ratio": 1.1800,
                "t_plus_2_close_profit_factor": 1.0400,
                "t_plus_2_close_expectancy": 0.0025,
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
                "next_close_payoff_ratio": 1.5000,
                "next_close_profit_factor": 1.3100,
                "next_close_expectancy": 0.0062,
                "t_plus_2_close_payoff_ratio": 1.2900,
                "t_plus_2_close_profit_factor": 1.1100,
                "t_plus_2_close_expectancy": 0.0033,
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
    assert comparison["tradeable_surface_delta"]["next_close_payoff_ratio"] == 0.26
    assert comparison["tradeable_surface_delta"]["next_close_profit_factor"] == 0.19
    assert comparison["tradeable_surface_delta"]["next_close_expectancy"] == 0.0021
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_payoff_ratio"] == 0.11
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_profit_factor"] == 0.07
    assert comparison["tradeable_surface_delta"]["t_plus_2_close_expectancy"] == 0.0008


def test_build_surface_summary_includes_payoff_and_expectancy_metrics() -> None:
    rows = [
        {"next_close_return": 0.04, "next_open_return": 0.01, "next_high_return": 0.05, "next_open_to_close_return": 0.03, "t_plus_2_close_return": 0.06},
        {"next_close_return": -0.02, "next_open_return": -0.01, "next_high_return": 0.01, "next_open_to_close_return": -0.01, "t_plus_2_close_return": -0.03},
        {"next_close_return": 0.01, "next_open_return": 0.0, "next_high_return": 0.02, "next_open_to_close_return": 0.01, "t_plus_2_close_return": 0.02},
    ]

    summary = build_surface_summary(rows, next_high_hit_threshold=0.02)

    assert summary["next_close_positive_count"] == 2
    assert summary["next_close_negative_count"] == 1
    assert summary["next_close_average_win"] == 0.025
    assert summary["next_close_average_loss_abs"] == 0.02
    assert summary["next_close_payoff_ratio"] == 1.25
    assert summary["next_close_profit_factor"] == 2.5
    assert summary["next_close_expectancy"] == 0.01


def test_extract_btst_price_outcome_includes_t_plus_5_and_runner_fields(monkeypatch):
    frame = pd.DataFrame(
        [
            {"date": "2026-05-12", "open": 10.0, "high": 10.4, "close": 10.0},
            {"date": "2026-05-13", "open": 10.1, "high": 10.8, "close": 10.5},
            {"date": "2026-05-14", "open": 10.6, "high": 11.4, "close": 11.0},
            {"date": "2026-05-15", "open": 11.0, "high": 12.4, "close": 12.1},
            {"date": "2026-05-18", "open": 12.2, "high": 12.3, "close": 11.9},
            {"date": "2026-05-19", "open": 11.8, "high": 12.5, "close": 12.4},
        ]
    ).assign(date=lambda df: pd.to_datetime(df["date"])) .set_index("date")
    monkeypatch.setattr("scripts.btst_analysis_utils.fetch_price_frame", lambda ticker, trade_date, cache: frame)

    payload = extract_btst_price_outcome("000001", "2026-05-12", {})

    assert payload["t_plus_5_trade_date"] == "2026-05-19"
    assert payload["t_plus_5_close_return"] == 0.24
    assert payload["max_future_high_return_2_5d"] == 0.25
    assert payload["max_future_high_trade_date_2_5d"] == "2026-05-19"
    assert payload["time_to_hit_20pct"] == 3
    assert payload["future_high_hit_20pct_2_5d"] is True


def test_build_surface_summary_includes_runner_metrics() -> None:
    rows = [
        {"next_close_return": 0.03, "next_high_return": 0.05, "next_open_return": 0.01, "next_open_to_close_return": 0.02, "t_plus_2_close_return": 0.08, "t_plus_3_close_return": 0.12, "t_plus_5_close_return": 0.16, "max_future_high_return_2_5d": 0.23, "future_high_hit_20pct_2_5d": True, "time_to_hit_20pct": 2},
        {"next_close_return": -0.01, "next_high_return": 0.02, "next_open_return": 0.0, "next_open_to_close_return": -0.01, "t_plus_2_close_return": 0.01, "t_plus_3_close_return": 0.00, "t_plus_5_close_return": 0.04, "max_future_high_return_2_5d": 0.08, "future_high_hit_20pct_2_5d": False, "time_to_hit_20pct": None},
    ]

    summary = build_surface_summary(rows, next_high_hit_threshold=0.02)

    assert summary["runner_capture_count"] == 1
    assert summary["max_future_high_return_2_5d_hit_rate_at_20pct"] == 0.5
    assert summary["max_future_high_return_2_5d_distribution"]["max"] == 0.23
    assert summary["time_to_hit_20pct_median"] == 2.0
