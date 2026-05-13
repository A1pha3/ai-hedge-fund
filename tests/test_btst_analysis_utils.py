from __future__ import annotations

import pandas as pd
import pytest

from scripts.btst_analysis_utils import (
    BTST_FACTOR_NAMES,
    build_surface_summary,
    compare_reports,
    compute_all_factor_ics,
    compute_factor_ic,
    summarize_distribution,
    extract_btst_price_outcome,
)


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
    ).assign(date=lambda df: pd.to_datetime(df["date"])).set_index("date")
    monkeypatch.setattr("scripts.btst_analysis_utils.fetch_price_frame", lambda ticker, trade_date, cache: frame)

    payload = extract_btst_price_outcome("000001", "2026-05-12", {})

    assert payload["t_plus_5_trade_date"] == "2026-05-19"
    assert payload["t_plus_5_close_return"] == 0.24
    assert payload["max_future_high_return_2_5d"] == 0.25
    assert payload["max_future_high_trade_date_2_5d"] == "2026-05-19"
    assert payload["time_to_hit_20pct"] == 3
    assert payload["future_high_hit_20pct_2_5d"] is True


def test_time_to_hit_20pct_cross_year(monkeypatch) -> None:
    frame = pd.DataFrame(
        [
            {"date": "2025-12-30", "open": 10.0, "high": 10.0, "close": 10.0},
            {"date": "2025-12-31", "open": 10.1, "high": 11.0, "close": 10.5},
            {"date": "2026-01-01", "open": 10.6, "high": 11.5, "close": 11.0},
            {"date": "2026-01-02", "open": 11.0, "high": 12.4, "close": 12.1},
        ]
    ).assign(date=lambda df: pd.to_datetime(df["date"])).set_index("date")
    monkeypatch.setattr("scripts.btst_analysis_utils.fetch_price_frame", lambda ticker, trade_date, cache: frame)

    payload = extract_btst_price_outcome("000001", "2025-12-30", {})

    assert payload["future_high_hit_20pct_2_5d"] is True
    assert payload["time_to_hit_20pct"] == 3


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


# ---------------------------------------------------------------------------
# Round 10 Task 1 — Factor IC validation
# ---------------------------------------------------------------------------


def test_btst_factor_names_contains_seven_factors() -> None:
    """BTST_FACTOR_NAMES must list exactly the seven primary scoring factors."""
    assert len(BTST_FACTOR_NAMES) == 7
    expected = {"breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength", "volatility_regime", "sector_resonance"}
    assert set(BTST_FACTOR_NAMES) == expected


def test_compute_factor_ic_perfect_positive_correlation() -> None:
    """Perfectly correlated factor and return should give IC = 1.0."""
    rows = [{"breakout_freshness": float(i) / 10, "next_close_return": float(i) / 10} for i in range(10)]
    ic = compute_factor_ic(rows, "breakout_freshness", "next_close_return")
    assert ic is not None
    assert ic == pytest.approx(1.0, abs=1e-4)


def test_compute_factor_ic_perfect_negative_correlation() -> None:
    """Perfectly anti-correlated factor and return should give IC = -1.0."""
    rows = [{"breakout_freshness": float(i), "next_close_return": float(-i)} for i in range(10)]
    ic = compute_factor_ic(rows, "breakout_freshness", "next_close_return")
    assert ic is not None
    assert ic == pytest.approx(-1.0, abs=1e-4)


def test_compute_factor_ic_returns_none_when_too_few_rows() -> None:
    """IC must return None when fewer than 5 paired observations are available."""
    rows = [{"breakout_freshness": 0.5, "next_close_return": 0.02}] * 4
    ic = compute_factor_ic(rows, "breakout_freshness", "next_close_return")
    assert ic is None


def test_compute_factor_ic_skips_missing_values() -> None:
    """Rows missing either factor or return should be silently excluded."""
    rows = [
        {"breakout_freshness": 0.1, "next_close_return": 0.01},
        {"breakout_freshness": 0.2, "next_close_return": 0.02},
        {"breakout_freshness": 0.3},                                 # missing return
        {"next_close_return": 0.03},                                 # missing factor
        {"breakout_freshness": 0.4, "next_close_return": 0.04},
        {"breakout_freshness": 0.5, "next_close_return": 0.05},
        {"breakout_freshness": 0.6, "next_close_return": 0.06},
    ]
    ic = compute_factor_ic(rows, "breakout_freshness", "next_close_return")
    assert ic is not None
    assert ic == pytest.approx(1.0, abs=1e-4)  # remaining 5 rows are perfectly correlated


def test_compute_all_factor_ics_returns_dict_with_all_factors() -> None:
    """compute_all_factor_ics should return a dict keyed by all BTST_FACTOR_NAMES."""
    rows: list[dict] = []
    result = compute_all_factor_ics(rows)
    assert set(result.keys()) == set(BTST_FACTOR_NAMES)
    # All None because no rows
    assert all(v is None for v in result.values())


def test_compute_all_factor_ics_nonzero_for_sufficient_data() -> None:
    """compute_all_factor_ics returns numeric ICs when all factors have sufficient data."""
    import random
    random.seed(42)
    rows = [
        {
            "breakout_freshness": random.random(),
            "trend_acceleration": random.random(),
            "volume_expansion_quality": random.random(),
            "catalyst_freshness": random.random(),
            "close_strength": random.random(),
            "volatility_regime": random.random(),
            "sector_resonance": random.random(),
            "next_close_return": random.uniform(-0.05, 0.1),
        }
        for _ in range(20)
    ]
    ics = compute_all_factor_ics(rows)
    # All 7 factors have data → all ICs should be float, not None
    assert all(isinstance(v, float) for v in ics.values()), f"Some ICs were None: {ics}"
    assert all(-1.0 <= v <= 1.0 for v in ics.values())


def test_build_surface_summary_includes_ic_sub_dicts() -> None:
    """build_surface_summary should include factor_ic_next_close, factor_ic_t_plus_2, factor_ic_t_plus_3."""
    rows = [
        {
            "next_close_return": float(i) / 10,
            "next_open_return": float(i) / 12,
            "next_high_return": float(i) / 8,
            "next_open_to_close_return": float(i) / 11,
            "t_plus_2_close_return": float(i) / 9,
            "t_plus_3_close_return": float(i) / 8,
            "breakout_freshness": float(i) / 10,
            "trend_acceleration": float(i) / 10,
            "volume_expansion_quality": float(i) / 10,
            "catalyst_freshness": float(i) / 10,
            "close_strength": float(i) / 10,
            "volatility_regime": float(i) / 10,
            "sector_resonance": float(i) / 10,
        }
        for i in range(1, 11)  # 10 rows
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert "factor_ic_next_close" in summary
    assert "factor_ic_t_plus_2" in summary
    assert "factor_ic_t_plus_3" in summary

    ic_nc = summary["factor_ic_next_close"]
    assert isinstance(ic_nc, dict)
    assert set(ic_nc.keys()) == set(BTST_FACTOR_NAMES)
    # All factors are perfectly correlated with next_close_return in this synthetic data
    assert all(v == pytest.approx(1.0, abs=1e-4) for v in ic_nc.values()), f"Expected IC≈1.0: {ic_nc}"
