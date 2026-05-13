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


# ---------------------------------------------------------------------------
# Round 12 Task 1 — T+1 intraday drawdown label and surface summary
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import compute_ic_weight_suggestions


def _base_row_with_drawdown(next_open: float, next_low: float, next_close: float) -> dict:
    """Build a minimal labeled row for drawdown tests."""
    next_intraday_drawdown = (next_low / next_open - 1.0) if next_open > 0 else None
    return {
        "date": "2026-03-20",
        "ticker": "000001",
        "next_close_return": next_close / next_open - 1.0 if next_open > 0 else None,
        "next_open_return": 0.0,
        "next_close": next_close,
        "next_open": next_open,
        "next_high": max(next_open, next_close),
        "next_low": next_low,
        "next_low_return": next_low / next_open - 1.0 if next_open > 0 else None,
        "next_intraday_drawdown": next_intraday_drawdown,
        "next_high_return": max(next_open, next_close) / next_open - 1.0 if next_open > 0 else None,
        "t_plus_2_close_return": 0.01,
        "t_plus_3_close_return": 0.01,
        "max_future_high_return_2_5d": 0.05,
    }


def test_build_surface_summary_exposes_t_plus_1_intraday_drawdown_p10() -> None:
    """build_surface_summary must compute t_plus_1_intraday_drawdown_p10 as the P10 of intraday drawdowns."""
    # 10 rows with known drawdowns: -0.01, -0.02, ..., -0.10
    rows = [_base_row_with_drawdown(10.0, 10.0 * (1.0 - i * 0.01), 10.05) for i in range(1, 11)]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert "t_plus_1_intraday_drawdown_p10" in summary
    val = summary["t_plus_1_intraday_drawdown_p10"]
    assert val is not None
    # P10 of [-0.01, -0.02, ..., -0.10] must be ≤ -0.01 (at the low end)
    assert isinstance(val, float)
    assert val < 0.0, f"P10 of negative drawdowns must be negative, got {val}"


def test_build_surface_summary_intraday_drawdown_p10_is_none_when_no_drawdown_data() -> None:
    """t_plus_1_intraday_drawdown_p10 must be None when rows lack next_intraday_drawdown."""
    rows = [
        {
            "date": "2026-03-20",
            "ticker": "000001",
            "next_close_return": 0.02,
            "next_open_return": 0.0,
            "next_close": 10.2,
            "next_open": 10.0,
            "next_high": 10.3,
            "next_low": None,
            "next_low_return": None,
            "next_intraday_drawdown": None,
            "next_high_return": 0.03,
            "t_plus_2_close_return": 0.01,
            "t_plus_3_close_return": 0.01,
            "max_future_high_return_2_5d": 0.05,
        }
        for _ in range(5)
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert summary.get("t_plus_1_intraday_drawdown_p10") is None


def test_build_surface_summary_includes_next_intraday_drawdown_distribution() -> None:
    """Surface summary must include next_intraday_drawdown_distribution key with valid stats."""
    rows = [_base_row_with_drawdown(10.0, 9.8, 10.1)] * 6
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert "next_intraday_drawdown_distribution" in summary
    dist = summary["next_intraday_drawdown_distribution"]
    assert isinstance(dist, dict)
    assert "p10" in dist
    assert dist["p10"] is not None


# ---------------------------------------------------------------------------
# Round 12 Task 3 — IC weight suggestions
# ---------------------------------------------------------------------------


def test_compute_ic_weight_suggestions_reduce_when_ic_below_downgrade_threshold() -> None:
    """Factors with IC < 0.02 must receive 'reduce' suggestion."""
    result = compute_ic_weight_suggestions({"breakout_freshness": 0.01})
    assert result["breakout_freshness"] == "reduce"


def test_compute_ic_weight_suggestions_increase_when_ic_above_upgrade_threshold() -> None:
    """Factors with IC >= 0.05 must receive 'increase' suggestion."""
    result = compute_ic_weight_suggestions({"trend_acceleration": 0.05})
    assert result["trend_acceleration"] == "increase"


def test_compute_ic_weight_suggestions_maintain_when_ic_in_middle_range() -> None:
    """Factors with IC in [0.02, 0.05) must receive 'maintain' suggestion."""
    result = compute_ic_weight_suggestions({"volume_expansion_quality": 0.03})
    assert result["volume_expansion_quality"] == "maintain"


def test_compute_ic_weight_suggestions_at_boundaries() -> None:
    """Boundary values: IC == 0.02 → maintain; IC == 0.049 → maintain; IC == 0.05 → increase."""
    result = compute_ic_weight_suggestions({
        "a": 0.02,    # >= downgrade threshold; < upgrade → maintain
        "b": 0.049,   # just below upgrade → maintain
        "c": 0.05,    # at upgrade → increase
        "d": 0.019,   # just below downgrade → reduce
    })
    assert result["a"] == "maintain"
    assert result["b"] == "maintain"
    assert result["c"] == "increase"
    assert result["d"] == "reduce"


def test_compute_ic_weight_suggestions_excludes_none_ic() -> None:
    """Factors with None IC must be excluded from the output dict."""
    result = compute_ic_weight_suggestions({
        "breakout_freshness": 0.06,
        "sector_resonance": None,
    })
    assert "sector_resonance" not in result
    assert "breakout_freshness" in result


def test_compute_ic_weight_suggestions_empty_input() -> None:
    """Empty input must return empty dict."""
    assert compute_ic_weight_suggestions({}) == {}


def test_build_surface_summary_includes_ic_weight_suggestions() -> None:
    """build_surface_summary must include 'ic_weight_suggestions' dict for factors with IC data."""
    # Factor values and next_close_return vary together (perfect positive correlation)
    # so Spearman IC ≈ 1.0, which is above IC_WEIGHT_UPGRADE_THRESHOLD (0.05) → "increase"
    rows = [
        {
            **_base_row_with_drawdown(10.0, 9.9, 10.0 + float(i) * 0.01),
            "next_close_return": float(i) * 0.01,   # override: varies 0.01 … 0.10
            "breakout_freshness": float(i) / 10,
            "trend_acceleration": float(i) / 10,
            "volume_expansion_quality": float(i) / 10,
            "catalyst_freshness": float(i) / 10,
            "close_strength": float(i) / 10,
            "volatility_regime": float(i) / 10,
            "sector_resonance": float(i) / 10,
        }
        for i in range(1, 11)
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert "ic_weight_suggestions" in summary
    suggestions = summary["ic_weight_suggestions"]
    assert isinstance(suggestions, dict)
    # All 7 BTST factors should have suggestions (IC ≈ 1.0 → "increase")
    for factor in BTST_FACTOR_NAMES:
        assert factor in suggestions
        assert suggestions[factor] in ("reduce", "maintain", "increase")


# ---------------------------------------------------------------------------
# Round 14 — Task 2: candidate_pool_size in build_surface_summary
# ---------------------------------------------------------------------------


def test_build_surface_summary_includes_candidate_pool_size() -> None:
    """build_surface_summary must expose 'candidate_pool_size' equal to total_count (Task 2, Round 14)."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03, "t_plus_2_close_return": 0.04, "t_plus_3_close_return": 0.03},
        {"next_close_return": -0.03, "next_open_return": -0.01, "next_high_return": 0.01, "next_open_to_close_return": -0.02, "t_plus_2_close_return": -0.02, "t_plus_3_close_return": -0.01},
        {"next_close_return": 0.08, "next_open_return": 0.03, "next_high_return": 0.09, "next_open_to_close_return": 0.05, "t_plus_2_close_return": 0.06, "t_plus_3_close_return": 0.05},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "candidate_pool_size" in summary, "candidate_pool_size must be present in surface summary"
    assert summary["candidate_pool_size"] == 3
    assert summary["candidate_pool_size"] == summary["total_count"]


def test_build_surface_summary_candidate_pool_size_empty() -> None:
    """build_surface_summary on empty rows must return candidate_pool_size=0 (Task 2, Round 14)."""
    summary = build_surface_summary([], next_high_hit_threshold=0.05)
    assert summary["candidate_pool_size"] == 0


# ---------------------------------------------------------------------------
# Round 14 — Task 5: Regime-conditional backtesting
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import build_regime_conditional_stats, REGIME_BULL_DAY_RETURN_THRESHOLD, REGIME_BEAR_DAY_RETURN_THRESHOLD


def test_build_regime_conditional_stats_empty_rows() -> None:
    """Empty rows must return zero-count regimes with no best regime (Task 5, Round 14)."""
    result = build_regime_conditional_stats([])
    for regime in ("bull", "bear", "sideways"):
        assert result[regime]["count"] == 0
        assert result[regime]["next_close_positive_rate"] is None
    assert result["regime_best_win_rate"] is None
    assert result["regime_best_payoff_ratio"] is None


def test_build_regime_conditional_stats_classifies_bull_days() -> None:
    """Days where avg next_close_return > REGIME_BULL_DAY_RETURN_THRESHOLD are classified as bull (Task 5, Round 14)."""
    rows = [
        {"trade_date": "2026-03-10", "next_close_return": 0.02},
        {"trade_date": "2026-03-10", "next_close_return": 0.01},
        {"trade_date": "2026-03-10", "next_close_return": 0.03},
    ]
    result = build_regime_conditional_stats(rows)
    # avg = (0.02+0.01+0.03)/3 = 0.02 > 0.003 → bull day
    assert result["bull"]["count"] == 3
    assert result["bear"]["count"] == 0
    assert result["sideways"]["count"] == 0


def test_build_regime_conditional_stats_classifies_bear_days() -> None:
    """Days where avg next_close_return < REGIME_BEAR_DAY_RETURN_THRESHOLD are classified as bear (Task 5, Round 14)."""
    rows = [
        {"trade_date": "2026-03-11", "next_close_return": -0.02},
        {"trade_date": "2026-03-11", "next_close_return": -0.01},
        {"trade_date": "2026-03-11", "next_close_return": -0.05},
    ]
    result = build_regime_conditional_stats(rows)
    # avg = -0.0267 < -0.003 → bear day
    assert result["bear"]["count"] == 3
    assert result["bull"]["count"] == 0
    assert result["sideways"]["count"] == 0


def test_build_regime_conditional_stats_classifies_sideways_days() -> None:
    """Days with small average return near zero are classified as sideways (Task 5, Round 14)."""
    rows = [
        {"trade_date": "2026-03-12", "next_close_return": 0.001},
        {"trade_date": "2026-03-12", "next_close_return": -0.001},
    ]
    result = build_regime_conditional_stats(rows)
    # avg = 0.0 → sideways
    assert result["sideways"]["count"] == 2
    assert result["bull"]["count"] == 0
    assert result["bear"]["count"] == 0


def test_build_regime_conditional_stats_mixed_days() -> None:
    """Mixed bull/bear/sideways days are correctly separated into different regime buckets (Task 5, Round 14)."""
    rows = [
        # Bull day: avg = 0.02
        {"trade_date": "2026-03-10", "next_close_return": 0.02},
        {"trade_date": "2026-03-10", "next_close_return": 0.02},
        # Bear day: avg = -0.02
        {"trade_date": "2026-03-11", "next_close_return": -0.02},
        {"trade_date": "2026-03-11", "next_close_return": -0.02},
        # Sideways day: avg = 0.001
        {"trade_date": "2026-03-12", "next_close_return": 0.001},
        {"trade_date": "2026-03-12", "next_close_return": 0.001},
    ]
    result = build_regime_conditional_stats(rows)
    assert result["bull"]["count"] == 2
    assert result["bear"]["count"] == 2
    assert result["sideways"]["count"] == 2


def test_build_regime_conditional_stats_win_rate_and_payoff() -> None:
    """Win rate and payoff ratio are correctly computed per regime (Task 5, Round 14)."""
    rows = [
        # Bull day: 2 winners (+5%, +10%), 1 loser (-2%)
        {"trade_date": "2026-03-10", "next_close_return": 0.05},
        {"trade_date": "2026-03-10", "next_close_return": 0.10},
        {"trade_date": "2026-03-10", "next_close_return": -0.02},
    ]
    result = build_regime_conditional_stats(rows)
    bull_stats = result["bull"]
    assert bull_stats["count"] == 3
    assert bull_stats["next_close_positive_rate"] == pytest.approx(2 / 3, abs=1e-4)
    # average_win = (0.05 + 0.10) / 2 = 0.075
    assert bull_stats["next_close_average_win"] == pytest.approx(0.075, abs=1e-4)
    # average_loss_abs = 0.02
    assert bull_stats["next_close_average_loss_abs"] == pytest.approx(0.02, abs=1e-4)
    # payoff_ratio = 0.075 / 0.02 = 3.75
    assert bull_stats["next_close_payoff_ratio"] == pytest.approx(3.75, abs=1e-3)


def test_build_regime_conditional_stats_best_win_rate_identified() -> None:
    """regime_best_win_rate correctly identifies the regime with highest win rate (Task 5, Round 14)."""
    rows = [
        # Bull day: win rate = 1.0 (all positive)
        {"trade_date": "2026-03-10", "next_close_return": 0.05},
        {"trade_date": "2026-03-10", "next_close_return": 0.08},
        # Bear day: win rate = 0.0 (all negative)
        {"trade_date": "2026-03-11", "next_close_return": -0.03},
        {"trade_date": "2026-03-11", "next_close_return": -0.02},
        # Sideways day: win rate = 0.5
        {"trade_date": "2026-03-12", "next_close_return": 0.001},
        {"trade_date": "2026-03-12", "next_close_return": -0.001},
    ]
    result = build_regime_conditional_stats(rows)
    assert result["regime_best_win_rate"] == "bull"


def test_build_surface_summary_includes_regime_conditional_stats() -> None:
    """build_surface_summary must include regime_conditional_stats dict (Task 5, Round 14)."""
    rows = [
        {"trade_date": "2026-03-10", "next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03, "t_plus_2_close_return": 0.04, "t_plus_3_close_return": 0.03},
        {"trade_date": "2026-03-11", "next_close_return": -0.03, "next_open_return": -0.01, "next_high_return": 0.01, "next_open_to_close_return": -0.02, "t_plus_2_close_return": -0.02, "t_plus_3_close_return": -0.01},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "regime_conditional_stats" in summary
    rcs = summary["regime_conditional_stats"]
    assert isinstance(rcs, dict)
    for key in ("bull", "bear", "sideways", "regime_best_win_rate", "regime_best_payoff_ratio"):
        assert key in rcs, f"Expected key '{key}' in regime_conditional_stats but got: {list(rcs.keys())}"


def test_build_regime_conditional_stats_rows_without_trade_date_skipped() -> None:
    """Rows missing trade_date or next_close_return do not crash the function (Task 5, Round 14)."""
    rows = [
        {"next_close_return": 0.05},  # no trade_date → unclassifiable, excluded from stats
        {"trade_date": "2026-03-10"},  # no next_close_return → excluded from date_returns
        {"trade_date": "2026-03-10", "next_close_return": None},
    ]
    result = build_regime_conditional_stats(rows)
    # All rows are either unclassifiable or lack return data → no crashes, all counts zero
    total = result["bull"]["count"] + result["bear"]["count"] + result["sideways"]["count"]
    assert total == 0
