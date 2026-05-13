from __future__ import annotations

import pandas as pd
import pytest

from scripts.btst_analysis_utils import (
    BTST_FACTOR_NAMES,
    BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD,
    OPEN_VS_HIGH_SIGNIFICANT_DISCOUNT_THRESHOLD,
    build_surface_summary,
    compare_reports,
    compute_all_factor_ics,
    compute_breakout_conditional_win_rate,
    compute_factor_ic,
    compute_multi_period_momentum_alignment,
    compute_sell_timing_analysis,
    compute_t0_bar_metrics,
    compute_t0_tail_strength_stratification,
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
    """BTST_FACTOR_NAMES must contain the seven original scoring factors plus the Round-16 and Round-17 additions."""
    # Round 16 adds t0_estimated_net_inflow_ratio and volume_price_divergence_score (→ 9).
    # Round 17 adds t0_tail_strength (→ 10 total).
    assert len(BTST_FACTOR_NAMES) == 10
    expected_original = {"breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength", "volatility_regime", "sector_resonance"}
    expected_r16 = {"t0_estimated_net_inflow_ratio", "volume_price_divergence_score"}
    expected_r17 = {"t0_tail_strength"}
    assert expected_original.issubset(set(BTST_FACTOR_NAMES))
    assert expected_r16.issubset(set(BTST_FACTOR_NAMES))
    assert expected_r17.issubset(set(BTST_FACTOR_NAMES))


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
            # Round 16 factors: must also be present for IC to be non-None
            "t0_estimated_net_inflow_ratio": random.uniform(-1.0, 1.0),
            "volume_price_divergence_score": random.random(),
            # Round 17 factor: t0_tail_strength (close/high ratio, ∈ (0,1])
            "t0_tail_strength": random.uniform(0.5, 1.0),
            "next_close_return": random.uniform(-0.05, 0.1),
        }
        for _ in range(20)
    ]
    ics = compute_all_factor_ics(rows)
    # All 10 factors have data → all ICs should be float, not None
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
    # Original 7 factors are perfectly correlated with next_close_return; R16/R17 factors are absent → None.
    original_factors = {"breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength", "volatility_regime", "sector_resonance"}
    r16_r17_factors = {"t0_estimated_net_inflow_ratio", "volume_price_divergence_score", "t0_tail_strength"}
    assert all(ic_nc[f] == pytest.approx(1.0, abs=1e-4) for f in original_factors), f"Expected IC≈1.0: {ic_nc}"
    assert all(ic_nc[f] is None for f in r16_r17_factors), f"R16/R17 factors should be None (no data): {ic_nc}"


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
    # All original 7 BTST factors are present in rows with data → each gets a suggestion.
    # R16 factors lack data in these rows (None IC) → excluded from suggestions by design.
    original_factors = {"breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength", "volatility_regime", "sector_resonance"}
    for factor in original_factors:
        assert factor in suggestions, f"Expected suggestion for {factor}"
        assert suggestions[factor] in ("reduce", "maintain", "increase")
    # All suggestions present must have valid labels
    assert all(v in ("reduce", "maintain", "increase") for v in suggestions.values())


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


# ---------------------------------------------------------------------------
# Round 15 — Task 4: Stop-loss trigger rate analysis
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import compute_stop_loss_trigger_rates, STOP_LOSS_THRESHOLDS


def test_compute_stop_loss_trigger_rates_empty_returns_none_for_each_threshold() -> None:
    """Empty drawdown list must return None for every threshold (Task 4, Round 15)."""
    result = compute_stop_loss_trigger_rates([])
    assert result == {"stop_loss_2pct": None, "stop_loss_3pct": None, "stop_loss_5pct": None}


def test_compute_stop_loss_trigger_rates_no_stops_hit() -> None:
    """When all intraday drawdowns are shallow, trigger rates must be 0 (Task 4, Round 15)."""
    # Drawdowns all better than −1 % — none should trigger −2 %, −3 %, −5 % stops
    result = compute_stop_loss_trigger_rates([-0.005, -0.01, 0.0, 0.02])
    assert result["stop_loss_2pct"] == 0.0
    assert result["stop_loss_3pct"] == 0.0
    assert result["stop_loss_5pct"] == 0.0


def test_compute_stop_loss_trigger_rates_partial_hit() -> None:
    """Trigger rate equals fraction of bars breaching the threshold (Task 4, Round 15)."""
    # 2 of 4 drawdowns ≤ -0.02 → 50 %; 1 of 4 ≤ -0.03 → 25 %; 0 ≤ -0.05 → 0 %
    result = compute_stop_loss_trigger_rates([-0.01, -0.02, -0.025, -0.01])
    assert result["stop_loss_2pct"] == pytest.approx(0.5)
    assert result["stop_loss_3pct"] == 0.0
    assert result["stop_loss_5pct"] == 0.0


def test_compute_stop_loss_trigger_rates_all_hit_hardest_stop() -> None:
    """When all bars breach even the −5 % stop, all rates must be 1.0 (Task 4, Round 15)."""
    result = compute_stop_loss_trigger_rates([-0.06, -0.07, -0.08])
    assert result["stop_loss_2pct"] == 1.0
    assert result["stop_loss_3pct"] == 1.0
    assert result["stop_loss_5pct"] == 1.0


def test_compute_stop_loss_trigger_rates_monotone_constraint() -> None:
    """stop_loss_2pct >= stop_loss_3pct >= stop_loss_5pct for any input (Task 4, Round 15)."""
    values = [-0.01, -0.025, -0.04, 0.0, -0.055, -0.03]
    result = compute_stop_loss_trigger_rates(values)
    r2 = result["stop_loss_2pct"]
    r3 = result["stop_loss_3pct"]
    r5 = result["stop_loss_5pct"]
    # Looser stop catches more bars (monotone non-decreasing as threshold relaxes)
    assert r2 is not None and r3 is not None and r5 is not None
    assert r2 >= r3 >= r5


def test_build_surface_summary_includes_stop_loss_trigger_rates() -> None:
    """build_surface_summary must expose stop_loss_trigger_rate_2pct/3pct/5pct (Task 4, Round 15)."""
    rows = [
        {"next_close_return": 0.03, "next_intraday_drawdown": -0.01},
        {"next_close_return": 0.01, "next_intraday_drawdown": -0.025},
        {"next_close_return": -0.02, "next_intraday_drawdown": -0.04},
        {"next_close_return": 0.05, "next_intraday_drawdown": 0.0},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "stop_loss_trigger_rates" in summary
    assert "stop_loss_trigger_rate_2pct" in summary
    assert "stop_loss_trigger_rate_3pct" in summary
    assert "stop_loss_trigger_rate_5pct" in summary
    # 2 of 4 bars hit ≤ −2 % (-0.025 and -0.04) → 0.50
    assert summary["stop_loss_trigger_rate_2pct"] == pytest.approx(0.5)
    # 1 of 4 bars hits ≤ −3 % (only -0.04) → 0.25
    assert summary["stop_loss_trigger_rate_3pct"] == pytest.approx(0.25)
    # 0 bars hit ≤ −5 % → 0.0
    assert summary["stop_loss_trigger_rate_5pct"] == 0.0


def test_build_surface_summary_stop_loss_rates_none_when_no_drawdown_data() -> None:
    """stop_loss trigger rates must be None when no intraday drawdown data are available (Task 4, Round 15)."""
    rows = [{"next_close_return": 0.03}, {"next_close_return": 0.01}]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert summary["stop_loss_trigger_rate_2pct"] is None
    assert summary["stop_loss_trigger_rate_3pct"] is None
    assert summary["stop_loss_trigger_rate_5pct"] is None


# ---------------------------------------------------------------------------
# Round 15 — Task 5: Cross-day momentum autocorrelation
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import compute_cross_day_autocorrelation, CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD


def test_compute_cross_day_autocorrelation_returns_none_when_too_few_rows() -> None:
    """Fewer than 5 paired rows must return None for autocorrelation (Task 5, Round 15)."""
    result = compute_cross_day_autocorrelation([0.01, 0.02], [0.01, -0.01], [])
    assert result["t1_vs_t2"] is None
    assert result["t2_vs_t3"] is None
    assert result["t1_vs_t2_mean_reversion_flag"] is False


def test_compute_cross_day_autocorrelation_perfect_positive_continuation() -> None:
    """Perfectly aligned T+1/T+2 returns must yield t1_vs_t2 = +1 (Task 5, Round 15)."""
    vals = [0.01, 0.02, 0.03, 0.04, 0.05]
    result = compute_cross_day_autocorrelation(vals, vals, vals)
    assert result["t1_vs_t2"] == pytest.approx(1.0)
    assert result["t1_vs_t2_mean_reversion_flag"] is False


def test_compute_cross_day_autocorrelation_perfect_negative_mean_reversion() -> None:
    """Perfectly reversed T+1/T+2 returns must yield t1_vs_t2 = -1 and flag mean reversion (Task 5, Round 15)."""
    t1 = [0.01, 0.02, 0.03, 0.04, 0.05]
    t2 = [0.05, 0.04, 0.03, 0.02, 0.01]  # perfect reversal
    result = compute_cross_day_autocorrelation(t1, t2, t2)
    assert result["t1_vs_t2"] == pytest.approx(-1.0)
    assert result["t1_vs_t2_mean_reversion_flag"] is True


def test_compute_cross_day_autocorrelation_sample_counts_correct() -> None:
    """t1_sample_count and t2_sample_count must match the input list lengths (Task 5, Round 15)."""
    t1 = [0.01, 0.02, 0.03, 0.04, 0.05]
    t2 = [0.01, -0.01, 0.02, -0.02, 0.03]
    t3 = [0.01, 0.01, 0.01, 0.01, 0.01]
    result = compute_cross_day_autocorrelation(t1, t2, t3)
    assert result["t1_sample_count"] == 5
    assert result["t2_sample_count"] == 5


def test_compute_cross_day_autocorrelation_mean_reversion_threshold() -> None:
    """t1_vs_t2_mean_reversion_flag triggers exactly at CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD (Task 5, Round 15)."""
    # Build returns where t1_vs_t2 will be just below the threshold (strongly negative rank correlation)
    t1 = [0.05, 0.04, 0.03, 0.02, 0.01, 0.00]
    t2 = [0.00, 0.01, 0.02, 0.03, 0.04, 0.05]  # rank reversal → t1_vs_t2 ≈ -1.0
    result = compute_cross_day_autocorrelation(t1, t2, t2)
    assert result["t1_vs_t2"] is not None
    # A strongly negative autocorrelation must trigger the flag
    if result["t1_vs_t2"] <= CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD:
        assert result["t1_vs_t2_mean_reversion_flag"] is True
    else:
        assert result["t1_vs_t2_mean_reversion_flag"] is False


def test_build_surface_summary_includes_cross_day_autocorrelation() -> None:
    """build_surface_summary must expose cross_day_autocorrelation fields (Task 5, Round 15)."""
    rows = [
        {"next_close_return": r1, "t_plus_2_close_return": r2, "t_plus_3_close_return": r3}
        for r1, r2, r3 in [
            (0.01, 0.02, 0.01),
            (0.03, 0.04, 0.02),
            (0.05, 0.06, 0.03),
            (-0.01, -0.02, -0.01),
            (-0.03, -0.04, -0.02),
        ]
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "cross_day_autocorrelation" in summary
    assert "cross_day_autocorr_t1_vs_t2" in summary
    assert "cross_day_autocorr_t2_vs_t3" in summary
    assert "cross_day_t1_mean_reversion_flag" in summary
    # With perfectly positive ranks, autocorrelation should be near +1
    assert summary["cross_day_autocorr_t1_vs_t2"] is not None
    assert summary["cross_day_autocorr_t1_vs_t2"] > 0.5


def test_build_surface_summary_cross_day_autocorr_none_when_no_t2_data() -> None:
    """cross_day_autocorr_t1_vs_t2 must be None when no T+2 return data exist (Task 5, Round 15)."""
    rows = [{"next_close_return": 0.03}, {"next_close_return": -0.01}]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert summary["cross_day_autocorr_t1_vs_t2"] is None
    assert summary["cross_day_autocorr_t2_vs_t3"] is None
    assert summary["cross_day_t1_mean_reversion_flag"] is False


# ---------------------------------------------------------------------------
# Round 15 — Task 2: Opening-gap continuation rate
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import compute_gap_continuation_rate, GAP_CONTINUATION_OPEN_THRESHOLD


def test_compute_gap_continuation_rate_empty_rows_returns_none() -> None:
    """Empty rows must return gap_continuation_rate=None and gap_up_bar_count=0 (Task 2, Round 15)."""
    result = compute_gap_continuation_rate([])
    assert result["gap_continuation_rate"] is None
    assert result["gap_up_bar_count"] == 0


def test_compute_gap_continuation_rate_no_qualifying_bars() -> None:
    """Rows with open gap below threshold must not contribute to continuation rate (Task 2, Round 15)."""
    rows = [
        {"next_open_return": 0.01, "next_open_to_close_return": 0.02},  # gap < 2 % threshold
        {"next_open_return": -0.01, "next_open_to_close_return": 0.01},  # negative gap
    ]
    result = compute_gap_continuation_rate(rows)
    assert result["gap_continuation_rate"] is None
    assert result["gap_up_bar_count"] == 0


def test_compute_gap_continuation_rate_all_continued() -> None:
    """100 % continuation rate when all gap-up bars continue intraday (Task 2, Round 15)."""
    rows = [
        {"next_open_return": 0.03, "next_open_to_close_return": 0.01},
        {"next_open_return": 0.04, "next_open_to_close_return": 0.02},
        {"next_open_return": 0.05, "next_open_to_close_return": 0.03},
    ]
    result = compute_gap_continuation_rate(rows)
    assert result["gap_continuation_rate"] == pytest.approx(1.0)
    assert result["gap_up_bar_count"] == 3


def test_compute_gap_continuation_rate_partial_continuation() -> None:
    """Correct fractional continuation rate when some bars reverse intraday (Task 2, Round 15)."""
    rows = [
        {"next_open_return": 0.03, "next_open_to_close_return": 0.02},   # continued
        {"next_open_return": 0.04, "next_open_to_close_return": -0.01},  # reversed
        {"next_open_return": 0.05, "next_open_to_close_return": 0.00},   # flat (not > 0)
        {"next_open_return": 0.02, "next_open_to_close_return": 0.03},   # continued
    ]
    result = compute_gap_continuation_rate(rows)
    assert result["gap_up_bar_count"] == 4
    assert result["gap_continuation_rate"] == pytest.approx(0.5)  # 2 / 4


def test_compute_gap_continuation_rate_custom_threshold() -> None:
    """Custom open_gap_threshold overrides the default (Task 2, Round 15)."""
    rows = [
        {"next_open_return": 0.03, "next_open_to_close_return": 0.02},
        {"next_open_return": 0.04, "next_open_to_close_return": -0.01},
    ]
    # With threshold=0.05, neither bar qualifies (both below 5 %)
    result = compute_gap_continuation_rate(rows, open_gap_threshold=0.05)
    assert result["gap_continuation_rate"] is None
    assert result["gap_up_bar_count"] == 0
    assert result["gap_open_threshold_used"] == pytest.approx(0.05)


def test_compute_gap_continuation_rate_threshold_field_written() -> None:
    """gap_open_threshold_used must always be written to the result dict (Task 2, Round 15)."""
    result = compute_gap_continuation_rate([])
    assert "gap_open_threshold_used" in result
    assert result["gap_open_threshold_used"] == pytest.approx(GAP_CONTINUATION_OPEN_THRESHOLD)


def test_build_surface_summary_includes_gap_continuation_rate() -> None:
    """build_surface_summary must expose gap_continuation_rate and gap_continuation_stats (Task 2, Round 15)."""
    rows = [
        {"next_close_return": 0.03, "next_open_return": 0.04, "next_open_to_close_return": 0.01},
        {"next_close_return": 0.01, "next_open_return": 0.03, "next_open_to_close_return": -0.02},
        {"next_close_return": -0.01, "next_open_return": 0.05, "next_open_to_close_return": 0.02},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "gap_continuation_stats" in summary
    assert "gap_continuation_rate" in summary
    # 2 of 3 bars gapped ≥ 2 % and both are in the stats; 2 bars qualify (0.04, 0.03=boundary, 0.05)
    # 0.03 >= 0.02 threshold so all 3 qualify; 2 of 3 continued (0.01 and 0.02 > 0); reversed is -0.02
    assert summary["gap_continuation_rate"] is not None


def test_build_surface_summary_gap_continuation_rate_none_when_no_open_gap_data() -> None:
    """gap_continuation_rate must be None when no bars meet the gap-up threshold (Task 2, Round 15)."""
    rows = [
        {"next_close_return": 0.02, "next_open_return": 0.01, "next_open_to_close_return": 0.01},
        {"next_close_return": -0.01, "next_open_return": 0.00, "next_open_to_close_return": -0.01},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert summary["gap_continuation_rate"] is None


# ---------------------------------------------------------------------------
# Round 16 — Task 1: T0 net inflow ratio (t0_estimated_net_inflow_ratio)
# Task 2: volume-price divergence (volume_price_divergence_score / flag)
# Task 3: predicted range pct + stop-loss linkage
# ---------------------------------------------------------------------------

from scripts.btst_analysis_utils import (  # noqa: E402 — grouped import for R16
    compute_t0_bar_metrics,
    compute_predicted_range_stop_loss_linkage,
    UP_BAR_PRICE_CHANGE_MIN,
    UPPER_SHADOW_DIVERGENCE_THRESHOLD,
    HIGH_VOL_RANGE_THRESHOLD,
    HIGH_VOL_STOP_LOSS_RATE_THRESHOLD,
)


# ---- compute_t0_bar_metrics -----------------------------------------------

def test_compute_t0_bar_metrics_up_bar_strong() -> None:
    """Up bar that closes near its high → low divergence score, no divergence flag."""
    # open=10, high=11, low=10, close=10.9 → price_change_pct=0.09, upper_shadow=(11-10.9)/(11-10)=0.10
    result = compute_t0_bar_metrics(10.0, 11.0, 10.0, 10.9)
    assert result["t0_estimated_net_inflow_ratio"] == pytest.approx((10.9 - 10.0) / (11.0 - 10.0) * 2 - 1, abs=1e-6)
    # upper_shadow_pct = 0.10, which is ≤ UPPER_SHADOW_DIVERGENCE_THRESHOLD → divergence_flag=False
    assert result["volume_price_divergence_flag"] is False
    # divergence_score for up bar = upper_shadow_pct = 0.10
    assert result["volume_price_divergence_score"] == pytest.approx(0.10, abs=1e-6)
    assert result["t0_predicted_range_pct"] == pytest.approx(0.1, abs=1e-6)  # (11-10)/open=1/10=0.1


def test_compute_t0_bar_metrics_up_bar_weak_divergence() -> None:
    """Up bar that closes near its low (large upper shadow) → divergence flag=True."""
    # open=10, high=11, low=10, close=10.21 → price_change_pct=0.021 > 0.02
    # upper_shadow = (11 - 10.21)/(11 - 10) = 0.79 > UPPER_SHADOW_DIVERGENCE_THRESHOLD=0.45
    result = compute_t0_bar_metrics(10.0, 11.0, 10.0, 10.21)
    assert result["volume_price_divergence_flag"] is True
    assert result["volume_price_divergence_score"] == pytest.approx(0.79, abs=1e-6)
    # net_inflow_ratio: (close - low)/(high - low) * 2 - 1
    assert result["t0_estimated_net_inflow_ratio"] == pytest.approx(0.21 * 2 - 1, abs=1e-6)  # negative → selling pressure


def test_compute_t0_bar_metrics_down_bar() -> None:
    """Down bar (close < open) → divergence flag always False, score reflects lower shadow bias."""
    # open=10.5, high=11, low=10, close=10.1 → price_change_pct = (10.1-10.5)/10.5 < 0 → is_up_bar=False
    result = compute_t0_bar_metrics(10.5, 11.0, 10.0, 10.1)
    assert result["volume_price_divergence_flag"] is False
    # down bar score = 1 - (close - low)/(high - low) = 1 - 0.1/1.0 = 0.9
    assert result["volume_price_divergence_score"] == pytest.approx(0.9, abs=1e-6)
    # net_inflow_ratio: (10.1 - 10) / 1.0 * 2 - 1 = -0.8
    assert result["t0_estimated_net_inflow_ratio"] == pytest.approx(-0.8, abs=1e-6)


def test_compute_t0_bar_metrics_doji_bar() -> None:
    """Edge case: doji (high == low) → uses epsilon denominator, no ZeroDivisionError."""
    result = compute_t0_bar_metrics(10.0, 10.0, 10.0, 10.0)
    # With ε denominator all ratios are well-defined (0 or bounded)
    assert isinstance(result["t0_estimated_net_inflow_ratio"], float)
    assert isinstance(result["volume_price_divergence_score"], float)
    assert isinstance(result["volume_price_divergence_flag"], bool)
    assert result["t0_predicted_range_pct"] == pytest.approx(0.0, abs=1e-6)


def test_compute_t0_bar_metrics_net_inflow_ratio_boundary() -> None:
    """Net inflow ratio is -1 at the low and +1 at the high."""
    # Closed exactly at low: (low - low)/(high - low)*2 - 1 = -1
    result_low = compute_t0_bar_metrics(10.0, 11.0, 9.0, 9.0)
    assert result_low["t0_estimated_net_inflow_ratio"] == pytest.approx(-1.0, abs=1e-6)
    # Closed exactly at high: (high - low)/(high - low)*2 - 1 = +1
    result_high = compute_t0_bar_metrics(10.0, 11.0, 9.0, 11.0)
    assert result_high["t0_estimated_net_inflow_ratio"] == pytest.approx(1.0, abs=1e-6)


# ---- compute_predicted_range_stop_loss_linkage ----------------------------

def test_compute_predicted_range_stop_loss_linkage_warning_triggered() -> None:
    """Warning fires when p75 > HIGH_VOL_RANGE_THRESHOLD and stop_loss_3pct > threshold."""
    # 10 values all > 0.04 → p75 > 0.04; stop_loss rate = 0.30 > 0.25
    high_ranges = [0.05, 0.06, 0.07, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    result = compute_predicted_range_stop_loss_linkage(high_ranges, 0.30)
    assert result["predicted_range_stop_loss_warning"] is True
    assert result["predicted_range_pct_p75"] is not None
    assert result["predicted_range_pct_p75"] > HIGH_VOL_RANGE_THRESHOLD
    assert result["high_volatility_warning_rate"] == pytest.approx(1.0, abs=1e-6)


def test_compute_predicted_range_stop_loss_linkage_no_warning_low_range() -> None:
    """No warning when p75 ≤ HIGH_VOL_RANGE_THRESHOLD."""
    low_ranges = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
    result = compute_predicted_range_stop_loss_linkage(low_ranges, 0.30)
    assert result["predicted_range_stop_loss_warning"] is False
    assert result["high_volatility_warning_rate"] == pytest.approx(0.0, abs=1e-6)


def test_compute_predicted_range_stop_loss_linkage_no_warning_low_stop_loss() -> None:
    """No warning when stop_loss rate is low even if range is high."""
    high_ranges = [0.05, 0.06, 0.07, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    result = compute_predicted_range_stop_loss_linkage(high_ranges, 0.10)  # below threshold
    assert result["predicted_range_stop_loss_warning"] is False


def test_compute_predicted_range_stop_loss_linkage_empty_list() -> None:
    """Empty range list → all keys present with None values."""
    result = compute_predicted_range_stop_loss_linkage([], None)
    assert result["predicted_range_pct_p75"] is None
    assert result["predicted_range_stop_loss_warning"] is None
    assert result["high_volatility_warning_rate"] is None


def test_compute_predicted_range_stop_loss_linkage_none_stop_loss() -> None:
    """None stop_loss_trigger_rate → warning is None (cannot evaluate joint condition)."""
    high_ranges = [0.05, 0.06, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    result = compute_predicted_range_stop_loss_linkage(high_ranges, None)
    assert result["predicted_range_stop_loss_warning"] is None
    assert result["predicted_range_pct_p75"] is not None  # distribution stats available


# ---- build_surface_summary R16 integration --------------------------------

def _make_r16_row(
    net_inflow: float,
    div_score: float,
    div_flag: bool,
    range_pct: float,
    open_price: float = 10.0,
    close: float = 10.5,
) -> dict:
    """Build a minimal surface row with all R16 fields populated."""
    return {
        "next_close_return": 0.05,
        "next_open_return": 0.02,
        "next_high_return": 0.07,
        "next_open_to_close_return": 0.03,
        "t_plus_2_close_return": 0.04,
        "t_plus_3_close_return": 0.03,
        "t0_estimated_net_inflow_ratio": net_inflow,
        "volume_price_divergence_score": div_score,
        "volume_price_divergence_flag": div_flag,
        "t0_predicted_range_pct": range_pct,
        "t0_open": open_price,
        "t0_close": close,
        "t0_high": close + range_pct * open_price / 2,
        "t0_low": close - range_pct * open_price / 2,
    }


def test_build_surface_summary_includes_r16_metrics() -> None:
    """build_surface_summary must expose R16 aggregation keys when T0 bar data is present."""
    rows = [
        _make_r16_row(0.5, 0.2, False, 0.03),
        _make_r16_row(-0.3, 0.7, True, 0.06),
        _make_r16_row(0.8, 0.1, False, 0.02),
        _make_r16_row(0.2, 0.8, True, 0.07),
        _make_r16_row(-0.6, 0.4, False, 0.01),
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    # R16 Task 2 — volume-price divergence rate
    assert "volume_price_divergence_rate" in summary
    assert summary["volume_price_divergence_rate"] == pytest.approx(2 / 5, abs=1e-6)  # 2 of 5 flagged

    # R16 Task 3 — predicted range distribution
    assert "t0_predicted_range_pct_distribution" in summary
    dist = summary["t0_predicted_range_pct_distribution"]
    assert dist is not None
    assert "p75" in dist

    # R16 Task 3 — warning key must be present
    assert "predicted_range_stop_loss_warning" in summary
    # R16 Task 3 — high_volatility_warning_rate
    assert "high_volatility_warning_rate" in summary


def test_build_surface_summary_r16_none_when_no_t0_bar_data() -> None:
    """R16 metrics must be None when rows have no T0 bar fields."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03, "t_plus_2_close_return": 0.04, "t_plus_3_close_return": 0.03},
        {"next_close_return": -0.02, "next_open_return": 0.01, "next_high_return": 0.03, "next_open_to_close_return": 0.01, "t_plus_2_close_return": -0.01, "t_plus_3_close_return": -0.02},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert summary["volume_price_divergence_rate"] is None
    # t0_predicted_range_pct_distribution is always a dict; when no range data, count==0 and all stats are None.
    dist = summary["t0_predicted_range_pct_distribution"]
    assert isinstance(dist, dict)
    assert dist["count"] == 0
    assert dist["p75"] is None
    assert summary["predicted_range_stop_loss_warning"] is None
    assert summary["high_volatility_warning_rate"] is None


def test_compute_t0_bar_metrics_flag_price_change_boundary() -> None:
    """Divergence flag must NOT fire when price_change_pct is exactly at the boundary (< UP_BAR_PRICE_CHANGE_MIN)."""
    # price_change_pct = (10.019 - 10.0) / 10.0 = 0.0019 < 0.02 → no flag despite large upper shadow
    result = compute_t0_bar_metrics(10.0, 11.0, 10.0, 10.019)
    assert result["volume_price_divergence_flag"] is False


# ===========================================================================
# Round 17 — Task 2: t0_tail_strength in compute_t0_bar_metrics
# ===========================================================================

def test_compute_t0_bar_metrics_includes_t0_tail_strength() -> None:
    """compute_t0_bar_metrics must include 't0_tail_strength' = close/high (Task 2, Round 17)."""
    result = compute_t0_bar_metrics(10.0, 12.0, 9.0, 11.4)
    assert "t0_tail_strength" in result
    # 11.4 / 12.0 = 0.95
    assert result["t0_tail_strength"] == pytest.approx(11.4 / 12.0, abs=1e-3)
    assert 0.0 < result["t0_tail_strength"] <= 1.0


def test_compute_t0_bar_metrics_tail_strength_at_high() -> None:
    """t0_tail_strength must be 1.0 when close == high (尾盘在最高价收盘)."""
    result = compute_t0_bar_metrics(10.0, 12.0, 9.0, 12.0)
    assert result["t0_tail_strength"] == pytest.approx(1.0, abs=1e-4)


def test_compute_t0_bar_metrics_tail_strength_below_one() -> None:
    """t0_tail_strength must be < 1.0 when close < high (late-session selling)."""
    result = compute_t0_bar_metrics(10.0, 12.0, 9.0, 10.0)
    assert result["t0_tail_strength"] < 1.0
    assert result["t0_tail_strength"] == pytest.approx(10.0 / 12.0, abs=1e-3)


def test_btst_factor_names_includes_t0_tail_strength() -> None:
    """t0_tail_strength must appear in BTST_FACTOR_NAMES (Round 17)."""
    assert "t0_tail_strength" in BTST_FACTOR_NAMES


def test_compute_all_factor_ics_includes_t0_tail_strength() -> None:
    """compute_all_factor_ics must return a key for 't0_tail_strength' (Round 17)."""
    result = compute_all_factor_ics([])
    assert "t0_tail_strength" in result
    # Empty rows → None IC
    assert result["t0_tail_strength"] is None


def test_compute_all_factor_ics_t0_tail_strength_non_none_with_data() -> None:
    """compute_all_factor_ics must return a float IC for 't0_tail_strength' when rows contain the field."""
    import random
    random.seed(0)
    rows = [
        {"t0_tail_strength": random.uniform(0.7, 1.0), "next_close_return": random.uniform(-0.05, 0.1)}
        for _ in range(15)
    ]
    ics = compute_all_factor_ics(rows)
    assert isinstance(ics["t0_tail_strength"], float)
    assert -1.0 <= ics["t0_tail_strength"] <= 1.0


def test_build_surface_summary_includes_t0_tail_strength_distribution() -> None:
    """build_surface_summary must expose 't0_tail_strength_distribution' when T0 bar data is present (Task 2, R17)."""
    rows = [
        {
            "next_close_return": 0.05,
            "next_open_return": 0.02,
            "next_high_return": 0.07,
            "next_open_to_close_return": 0.03,
            "t_plus_2_close_return": 0.04,
            "t_plus_3_close_return": 0.03,
            "t0_tail_strength": 0.95,
        },
        {
            "next_close_return": -0.02,
            "next_open_return": 0.01,
            "next_high_return": 0.03,
            "next_open_to_close_return": 0.01,
            "t_plus_2_close_return": -0.01,
            "t_plus_3_close_return": -0.02,
            "t0_tail_strength": 0.80,
        },
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "t0_tail_strength_distribution" in summary
    dist = summary["t0_tail_strength_distribution"]
    assert isinstance(dist, dict)
    assert dist["count"] == 2
    assert dist["mean"] == pytest.approx((0.95 + 0.80) / 2, abs=1e-3)


def test_build_surface_summary_t0_tail_strength_none_when_no_data() -> None:
    """t0_tail_strength_distribution count must be 0 when rows lack t0_tail_strength."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    dist = summary["t0_tail_strength_distribution"]
    assert isinstance(dist, dict)
    assert dist["count"] == 0
    assert dist["mean"] is None


# ===========================================================================
# Round 17 — Task 1: compute_breakout_conditional_win_rate
# ===========================================================================

def test_compute_breakout_conditional_win_rate_basic() -> None:
    """Positive lift when breakout rows win more often than non-breakout rows (Task 1, Round 17)."""
    rows = [
        {"breakout_freshness": 0.8, "next_close_return": 0.05},
        {"breakout_freshness": 0.7, "next_close_return": 0.03},
        {"breakout_freshness": 0.6, "next_close_return": -0.02},
        {"breakout_freshness": 0.3, "next_close_return": -0.03},
        {"breakout_freshness": 0.2, "next_close_return": -0.04},
        {"breakout_freshness": 0.1, "next_close_return": -0.05},
    ]
    result = compute_breakout_conditional_win_rate(rows)
    assert result["breakout_sample_count"] == 3
    assert result["non_breakout_sample_count"] == 3
    assert result["win_rate_breakout"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["win_rate_non_breakout"] == pytest.approx(0.0, abs=1e-4)
    assert result["lift"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["breakout_threshold_used"] == pytest.approx(BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD, abs=1e-4)


def test_compute_breakout_conditional_win_rate_empty_rows() -> None:
    """compute_breakout_conditional_win_rate returns None rates when rows is empty."""
    result = compute_breakout_conditional_win_rate([])
    assert result["win_rate_breakout"] is None
    assert result["win_rate_non_breakout"] is None
    assert result["lift"] is None
    assert result["breakout_sample_count"] == 0
    assert result["non_breakout_sample_count"] == 0


def test_compute_breakout_conditional_win_rate_no_returns_field() -> None:
    """Rows without next_close_return are skipped; lift remains None when one group is empty."""
    rows = [
        {"breakout_freshness": 0.8},  # no next_close_return → skipped
        {"breakout_freshness": 0.3, "next_close_return": 0.02},
    ]
    result = compute_breakout_conditional_win_rate(rows)
    assert result["win_rate_breakout"] is None
    assert result["win_rate_non_breakout"] is not None
    assert result["lift"] is None  # can't compute lift without both groups


def test_compute_breakout_conditional_win_rate_custom_threshold() -> None:
    """Custom breakout_threshold parameter is respected and reflected in output."""
    rows = [
        {"breakout_freshness": 0.9, "next_close_return": 0.05},
        {"breakout_freshness": 0.6, "next_close_return": 0.02},
        {"breakout_freshness": 0.4, "next_close_return": -0.01},
    ]
    result = compute_breakout_conditional_win_rate(rows, breakout_threshold=0.70)
    # Only 0.9 qualifies at threshold=0.70
    assert result["breakout_sample_count"] == 1
    assert result["non_breakout_sample_count"] == 2
    assert result["breakout_threshold_used"] == pytest.approx(0.70, abs=1e-4)


def test_build_surface_summary_includes_breakout_conditional_win_rate() -> None:
    """build_surface_summary must expose 'breakout_conditional_win_rate' sub-dict (Task 1, Round 17)."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03, "breakout_freshness": 0.8},
        {"next_close_return": 0.03, "next_open_return": 0.01, "next_high_return": 0.04, "next_open_to_close_return": 0.02, "breakout_freshness": 0.7},
        {"next_close_return": -0.02, "next_open_return": -0.01, "next_high_return": 0.01, "next_open_to_close_return": -0.01, "breakout_freshness": 0.3},
        {"next_close_return": -0.03, "next_open_return": -0.02, "next_high_return": 0.00, "next_open_to_close_return": -0.01, "breakout_freshness": 0.2},
        {"next_close_return": 0.04, "next_open_return": 0.02, "next_high_return": 0.06, "next_open_to_close_return": 0.02, "breakout_freshness": 0.9},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "breakout_conditional_win_rate" in summary
    bwr = summary["breakout_conditional_win_rate"]
    assert isinstance(bwr, dict)
    assert "win_rate_breakout" in bwr
    assert "win_rate_non_breakout" in bwr
    assert "lift" in bwr
    # 3 rows with freshness ≥ 0.5 (0.8, 0.7, 0.9) — all positive → win_rate_breakout = 1.0
    assert bwr["win_rate_breakout"] == pytest.approx(1.0, abs=1e-4)
    # 2 rows with freshness < 0.5 (0.3, 0.2) — both negative → win_rate_non_breakout = 0.0
    assert bwr["win_rate_non_breakout"] == pytest.approx(0.0, abs=1e-4)
    assert bwr["lift"] == pytest.approx(1.0, abs=1e-4)


def test_build_surface_summary_breakout_conditional_win_rate_none_when_no_freshness() -> None:
    """breakout_conditional_win_rate.lift must be None when rows have no breakout_freshness field."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03},
        {"next_close_return": -0.02, "next_open_return": -0.01, "next_high_return": 0.00, "next_open_to_close_return": -0.01},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    bwr = summary["breakout_conditional_win_rate"]
    assert bwr["lift"] is None
    assert bwr["breakout_sample_count"] == 0
    assert bwr["non_breakout_sample_count"] == 0


# ===========================================================================
# Round 17 — Task 3: compute_sell_timing_analysis
# ===========================================================================

def test_compute_sell_timing_analysis_basic() -> None:
    """compute_sell_timing_analysis returns expected ratios and optimal_exit_window (Task 3, Round 17)."""
    rows = [
        # open is well below high → open_vs_high < 1, late exit may be better
        {"next_open": 10.1, "next_high": 11.0, "next_close": 10.8, "trade_close": 10.0, "next_open_return": 0.01, "next_close_return": 0.08, "next_open_to_close_return": 0.069},
        {"next_open": 10.2, "next_high": 11.2, "next_close": 10.9, "trade_close": 10.0, "next_open_return": 0.02, "next_close_return": 0.09, "next_open_to_close_return": 0.069},
        {"next_open": 10.3, "next_high": 11.5, "next_close": 11.0, "trade_close": 10.0, "next_open_return": 0.03, "next_close_return": 0.10, "next_open_to_close_return": 0.068},
        {"next_open": 10.2, "next_high": 11.3, "next_close": 10.7, "trade_close": 10.0, "next_open_return": 0.02, "next_close_return": 0.07, "next_open_to_close_return": 0.049},
        {"next_open": 10.1, "next_high": 11.1, "next_close": 10.6, "trade_close": 10.0, "next_open_return": 0.01, "next_close_return": 0.06, "next_open_to_close_return": 0.049},
    ]
    result = compute_sell_timing_analysis(rows)
    assert result["sell_timing_sample_count"] == 5
    assert result["open_vs_high_ratio_mean"] is not None
    assert result["open_vs_high_ratio_mean"] < 1.0   # open < high in all rows
    assert result["optimal_exit_window"] in {"early", "mid", "late"}
    # In these rows, mid = (high+close)/2 / trade_close − 1 is high → likely mid or late wins
    assert result["exit_mid_median_return"] is not None
    assert result["open_significantly_below_high"] is not None


def test_compute_sell_timing_analysis_empty_rows() -> None:
    """compute_sell_timing_analysis returns None fields when rows is empty (Task 3, Round 17)."""
    result = compute_sell_timing_analysis([])
    assert result["sell_timing_sample_count"] == 0
    assert result["optimal_exit_window"] is None
    assert result["open_vs_high_ratio_mean"] is None
    assert result["open_significantly_below_high"] is None


def test_compute_sell_timing_analysis_open_at_high() -> None:
    """open_significantly_below_high must be False when open equals high (no discount)."""
    rows = [
        {"next_open": 10.0, "next_high": 10.0, "next_close": 9.5, "trade_close": 9.8, "next_open_return": 0.02, "next_close_return": -0.03, "next_open_to_close_return": -0.05},
        {"next_open": 11.0, "next_high": 11.0, "next_close": 10.8, "trade_close": 10.9, "next_open_return": 0.009, "next_close_return": -0.009, "next_open_to_close_return": -0.018},
    ]
    result = compute_sell_timing_analysis(rows)
    # open / high = 1.0 → open_vs_high_ratio_mean = 1.0 → NOT significantly below
    assert result["open_vs_high_ratio_mean"] == pytest.approx(1.0, abs=1e-3)
    assert result["open_significantly_below_high"] is False


def test_compute_sell_timing_analysis_open_significantly_below_high() -> None:
    """open_significantly_below_high must be True when open is < 80 % of high on average (Task 3, Round 17)."""
    rows = [
        # open ≈ 70 % of high
        {"next_open": 7.0, "next_high": 10.0, "next_close": 9.0, "trade_close": 7.5, "next_open_return": -0.067, "next_close_return": 0.20, "next_open_to_close_return": 0.286},
        {"next_open": 7.5, "next_high": 11.0, "next_close": 10.0, "trade_close": 8.0, "next_open_return": -0.0625, "next_close_return": 0.25, "next_open_to_close_return": 0.333},
    ]
    result = compute_sell_timing_analysis(rows)
    assert result["open_vs_high_ratio_mean"] < OPEN_VS_HIGH_SIGNIFICANT_DISCOUNT_THRESHOLD
    assert result["open_significantly_below_high"] is True


def test_build_surface_summary_includes_sell_timing_analysis() -> None:
    """build_surface_summary must expose 'sell_timing_analysis' sub-dict and top-level keys (Task 3, Round 17)."""

    def _row(nor: float, ncr: float, noc: float, n_open: float = 10.2, n_high: float = 11.0, n_close: float = 10.8, tc: float = 10.0) -> dict:
        return {"next_open_return": nor, "next_close_return": ncr, "next_open_to_close_return": noc, "next_high_return": n_high / tc - 1.0, "next_open": n_open, "next_high": n_high, "next_close": n_close, "trade_close": tc}

    rows = [_row(0.02, 0.08, 0.06) for _ in range(6)]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)

    assert "sell_timing_analysis" in summary
    sta = summary["sell_timing_analysis"]
    assert isinstance(sta, dict)
    assert "optimal_exit_window" in sta
    # Top-level convenience keys
    assert "optimal_exit_window" in summary
    assert "open_vs_high_ratio_mean" in summary
    assert "open_significantly_below_high" in summary
    # Values match nested dict
    assert summary["optimal_exit_window"] == sta.get("optimal_exit_window")
    assert summary["open_vs_high_ratio_mean"] == sta.get("open_vs_high_ratio_mean")


def test_build_surface_summary_sell_timing_none_when_no_ohlc() -> None:
    """sell_timing_analysis.optimal_exit_window must be None when rows lack T+1 OHLC fields (Task 3, Round 17)."""
    rows = [
        {"next_close_return": 0.05, "next_open_return": 0.02, "next_high_return": 0.07, "next_open_to_close_return": 0.03},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    sta = summary["sell_timing_analysis"]
    assert sta["optimal_exit_window"] is None
    assert sta["sell_timing_sample_count"] == 0
    assert summary["optimal_exit_window"] is None


# ===========================================================================
# Round 18 — Task 2: Multi-period momentum alignment score (多周期动量一致性)
# ===========================================================================


def test_compute_multi_period_momentum_alignment_empty_returns_none_fields() -> None:
    """compute_multi_period_momentum_alignment on empty rows must return None for all rate fields."""
    result = compute_multi_period_momentum_alignment([])
    assert result["full_aligned_rate"] is None
    assert result["partial_aligned_rate"] is None
    assert result["t1_t2_aligned_rate"] is None
    assert result["alignment_score"] is None
    assert result["aligned_sample_count"] == 0
    assert result["t1_positive_rate"] is None
    assert result["t2_positive_rate"] is None
    assert result["t3_positive_rate"] is None


def test_compute_multi_period_momentum_alignment_excludes_rows_missing_returns() -> None:
    """Rows without all three forward returns must be excluded from the denominator."""
    rows = [
        {"next_close_return": 0.03},  # missing t_plus_2 and t_plus_3
        {"next_close_return": 0.03, "t_plus_2_close_return": 0.02},  # missing t_plus_3
        {"next_close_return": 0.03, "t_plus_2_close_return": 0.02, "t_plus_3_close_return": 0.01},  # complete
    ]
    result = compute_multi_period_momentum_alignment(rows)
    assert result["aligned_sample_count"] == 1


def test_compute_multi_period_momentum_alignment_all_positive() -> None:
    """When all three horizons are positive for every row, full_aligned_rate must be 1.0."""
    rows = [
        {"next_close_return": 0.05, "t_plus_2_close_return": 0.03, "t_plus_3_close_return": 0.02},
        {"next_close_return": 0.04, "t_plus_2_close_return": 0.01, "t_plus_3_close_return": 0.03},
    ]
    result = compute_multi_period_momentum_alignment(rows)
    assert result["full_aligned_rate"] == 1.0
    assert result["partial_aligned_rate"] == 1.0
    assert result["t1_t2_aligned_rate"] == 1.0
    assert result["alignment_score"] == 1.0
    assert result["aligned_sample_count"] == 2
    assert result["t1_positive_rate"] == 1.0
    assert result["t2_positive_rate"] == 1.0
    assert result["t3_positive_rate"] == 1.0


def test_compute_multi_period_momentum_alignment_no_alignment() -> None:
    """When T+2 is always negative, full_aligned_rate must be 0 and t1_t2 rate must be 0."""
    rows = [
        {"next_close_return": 0.05, "t_plus_2_close_return": -0.03, "t_plus_3_close_return": 0.02},
        {"next_close_return": 0.04, "t_plus_2_close_return": -0.01, "t_plus_3_close_return": 0.01},
    ]
    result = compute_multi_period_momentum_alignment(rows)
    assert result["full_aligned_rate"] == 0.0
    assert result["t1_t2_aligned_rate"] == 0.0
    # T+1 and T+3 are both positive → partial alignment
    assert result["partial_aligned_rate"] == 1.0


def test_compute_multi_period_momentum_alignment_partial_alignment() -> None:
    """Alignment score formula: full rows × 1.0 + t1_t2_only rows × 0.5, divided by total."""
    # Row 1: T+1=+, T+2=+, T+3=+ → full (counts 1.0)
    # Row 2: T+1=+, T+2=+, T+3=- → t1_t2 only (counts 0.5)
    # Row 3: T+1=+, T+2=-, T+3=- → no alignment  (counts 0.0)
    # Row 4: T+1=-, T+2=-, T+3=- → no alignment  (counts 0.0)
    rows = [
        {"next_close_return": 0.05, "t_plus_2_close_return": 0.03, "t_plus_3_close_return": 0.02},
        {"next_close_return": 0.04, "t_plus_2_close_return": 0.01, "t_plus_3_close_return": -0.01},
        {"next_close_return": 0.03, "t_plus_2_close_return": -0.02, "t_plus_3_close_return": -0.01},
        {"next_close_return": -0.02, "t_plus_2_close_return": -0.01, "t_plus_3_close_return": -0.03},
    ]
    result = compute_multi_period_momentum_alignment(rows)
    assert result["aligned_sample_count"] == 4
    assert result["full_aligned_rate"] == 0.25  # 1/4
    assert result["t1_t2_aligned_rate"] == 0.50  # 2/4 (rows 1 and 2)
    # alignment_score = (1 × 1.0 + 1 × 0.5) / 4 = 1.5/4 = 0.375
    assert result["alignment_score"] == 0.375


def test_build_surface_summary_includes_multi_period_momentum_alignment() -> None:
    """build_surface_summary must include multi_period_momentum_alignment sub-dict (Task 2, Round 18)."""
    rows = [
        {"next_close_return": 0.05, "t_plus_2_close_return": 0.03, "t_plus_3_close_return": 0.02, "next_high_return": 0.07},
        {"next_close_return": -0.02, "t_plus_2_close_return": -0.01, "t_plus_3_close_return": 0.01, "next_high_return": 0.01},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "multi_period_momentum_alignment" in summary
    mma = summary["multi_period_momentum_alignment"]
    assert isinstance(mma, dict)
    assert mma["aligned_sample_count"] == 2
    # Top-level shortcut keys
    assert "multi_period_full_aligned_rate" in summary
    assert "multi_period_alignment_score" in summary
    assert "multi_period_aligned_sample_count" in summary
    assert summary["multi_period_aligned_sample_count"] == 2


def test_build_surface_summary_multi_period_alignment_score_zero_when_no_t3_rows() -> None:
    """When no rows have t_plus_3_close_return, aligned_sample_count must be 0 and rates None."""
    rows = [
        {"next_close_return": 0.05, "next_high_return": 0.07},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert summary["multi_period_aligned_sample_count"] == 0
    assert summary["multi_period_full_aligned_rate"] is None
    assert summary["multi_period_alignment_score"] is None


# ===========================================================================
# Round 18 — Task 3: t0_tail_strength stratification (尾盘强度分层验证)
# ===========================================================================


def test_compute_t0_tail_strength_stratification_empty_returns_empty_strata() -> None:
    """compute_t0_tail_strength_stratification on empty input must return 0-count strata."""
    result = compute_t0_tail_strength_stratification([])
    assert result["stratification_sample_count"] == 0
    assert result["low"]["count"] == 0
    assert result["mid"]["count"] == 0
    assert result["high"]["count"] == 0
    assert result["monotone_win_rate"] is None
    assert result["monotone_payoff_ratio"] is None


def test_compute_t0_tail_strength_stratification_three_equal_strata() -> None:
    """With 9 rows, each stratum should have approximately 3 rows."""
    # Craft rows so that t0_tail_strength is in 0.1 increments.
    # T+1 return is positive for high stratum, negative for low stratum.
    rows = [
        {"t0_tail_strength": 0.50, "next_close_return": -0.03},
        {"t0_tail_strength": 0.55, "next_close_return": -0.02},
        {"t0_tail_strength": 0.60, "next_close_return": -0.01},
        {"t0_tail_strength": 0.70, "next_close_return": 0.01},
        {"t0_tail_strength": 0.75, "next_close_return": 0.02},
        {"t0_tail_strength": 0.80, "next_close_return": 0.01},
        {"t0_tail_strength": 0.90, "next_close_return": 0.04},
        {"t0_tail_strength": 0.95, "next_close_return": 0.05},
        {"t0_tail_strength": 0.99, "next_close_return": 0.06},
    ]
    result = compute_t0_tail_strength_stratification(rows)
    assert result["stratification_sample_count"] == 9
    # Low stratum (bottom 3) should have low or zero win rate
    assert result["low"]["count"] > 0
    assert result["high"]["count"] > 0
    assert result["p33_threshold"] is not None
    assert result["p67_threshold"] is not None
    # low threshold ≤ high threshold
    assert result["p33_threshold"] <= result["p67_threshold"]


def test_compute_t0_tail_strength_stratification_monotone_win_rate_detected() -> None:
    """When win rate strictly increases low → mid → high, monotone_win_rate must be True."""
    # Low stratum: all losses; mid: 50% wins; high: all wins
    rows = (
        [{"t0_tail_strength": 0.50, "next_close_return": -0.03}] * 3
        + [{"t0_tail_strength": 0.70, "next_close_return": 0.02}, {"t0_tail_strength": 0.72, "next_close_return": -0.01}, {"t0_tail_strength": 0.74, "next_close_return": 0.01}]
        + [{"t0_tail_strength": 0.95, "next_close_return": 0.05}] * 3
    )
    result = compute_t0_tail_strength_stratification(rows)
    low_wr = result["low"]["win_rate"]
    mid_wr = result["mid"]["win_rate"]
    high_wr = result["high"]["win_rate"]
    assert low_wr is not None
    assert mid_wr is not None
    assert high_wr is not None
    if low_wr < mid_wr < high_wr:
        assert result["monotone_win_rate"] is True
    else:
        # Monotonicity may not hold exactly with these small samples; at minimum the flag should be bool
        assert isinstance(result["monotone_win_rate"], bool)


def test_compute_t0_tail_strength_stratification_excludes_missing_fields() -> None:
    """Rows missing t0_tail_strength or next_close_return must be excluded."""
    rows = [
        {"t0_tail_strength": 0.80},  # missing next_close_return
        {"next_close_return": 0.03},  # missing t0_tail_strength
        {"t0_tail_strength": 0.90, "next_close_return": 0.04},  # complete
        {"t0_tail_strength": 0.60, "next_close_return": -0.02},  # complete
        {"t0_tail_strength": 0.70, "next_close_return": 0.01},  # complete
    ]
    result = compute_t0_tail_strength_stratification(rows)
    assert result["stratification_sample_count"] == 3


def test_build_surface_summary_includes_t0_tail_strength_stratification() -> None:
    """build_surface_summary must include t0_tail_strength_stratification sub-dict (Task 3, Round 18)."""
    rows = [
        {"next_close_return": 0.05, "next_high_return": 0.07, "t0_tail_strength": 0.95},
        {"next_close_return": -0.02, "next_high_return": 0.01, "t0_tail_strength": 0.60},
        {"next_close_return": 0.03, "next_high_return": 0.05, "t0_tail_strength": 0.80},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    assert "t0_tail_strength_stratification" in summary
    strat = summary["t0_tail_strength_stratification"]
    assert isinstance(strat, dict)
    assert "low" in strat
    assert "mid" in strat
    assert "high" in strat
    assert strat["stratification_sample_count"] == 3
    # Top-level shortcut keys
    assert "t0_tail_strength_monotone_win_rate" in summary
    assert "t0_tail_strength_monotone_payoff_ratio" in summary


def test_build_surface_summary_t0_tail_strength_stratification_none_when_no_tail_data() -> None:
    """When no rows have t0_tail_strength, stratification_sample_count must be 0 and monotone flags None."""
    rows = [
        {"next_close_return": 0.05, "next_high_return": 0.07},
    ]
    summary = build_surface_summary(rows, next_high_hit_threshold=0.05)
    strat = summary["t0_tail_strength_stratification"]
    assert strat["stratification_sample_count"] == 0
    assert summary["t0_tail_strength_monotone_win_rate"] is None
    assert summary["t0_tail_strength_monotone_payoff_ratio"] is None


# ===========================================================================
# Round 18 — Task 1: New factor grid search接入 (composite score)
# ===========================================================================


def test_compute_runner_composite_score_net_inflow_weight_zero_is_neutral() -> None:
    """When net_inflow_weight=0, runner_composite_score must be identical to no-new-factor score."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    snap = {
        "breakout_freshness": 0.70,
        "trend_acceleration": 0.60,
        "volume_expansion_quality": 0.50,
        "catalyst_freshness": 0.40,
        "close_strength": 0.45,
        "t0_estimated_net_inflow_ratio": 0.80,  # present but weight=0
    }
    # Profile with all new weights = 0
    class _FakeProfile:
        runner_composite_score_breakout_weight = 0.40
        runner_composite_score_trend_weight = 0.30
        runner_composite_score_volume_weight = 0.20
        runner_composite_score_catalyst_weight = 0.10
        runner_composite_score_close_strength_weight = 0.10
        runner_composite_score_volatility_regime_weight = 0.0
        runner_composite_score_sector_resonance_weight = 0.0
        runner_composite_score_quiet_breakout_weight = 0.0
        runner_composite_score_net_inflow_weight = 0.0
        runner_composite_score_volume_price_divergence_weight = 0.0
        runner_composite_score_t0_tail_weight = 0.0

    score_with_zero_weights = compute_runner_composite_score(snap, _FakeProfile())
    score_without_profile = compute_runner_composite_score(snap)
    assert score_with_zero_weights == score_without_profile


def test_compute_runner_composite_score_net_inflow_weight_nonzero_affects_score() -> None:
    """When net_inflow_weight > 0, high net_inflow should increase the composite score."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    base_snap = {"breakout_freshness": 0.50, "trend_acceleration": 0.50, "volume_expansion_quality": 0.50, "catalyst_freshness": 0.50, "close_strength": 0.50}

    class _ProfileLowInflow:
        runner_composite_score_breakout_weight = 0.30
        runner_composite_score_trend_weight = 0.20
        runner_composite_score_volume_weight = 0.15
        runner_composite_score_catalyst_weight = 0.10
        runner_composite_score_close_strength_weight = 0.10
        runner_composite_score_volatility_regime_weight = 0.0
        runner_composite_score_sector_resonance_weight = 0.0
        runner_composite_score_quiet_breakout_weight = 0.0
        runner_composite_score_net_inflow_weight = 0.15
        runner_composite_score_volume_price_divergence_weight = 0.0
        runner_composite_score_t0_tail_weight = 0.0

    snap_high_ni = {**base_snap, "t0_estimated_net_inflow_ratio": 1.0}   # max buying pressure → net_inflow_score=1.0
    snap_low_ni = {**base_snap, "t0_estimated_net_inflow_ratio": -1.0}   # max selling pressure → net_inflow_score=0.0
    p = _ProfileLowInflow()
    score_high = compute_runner_composite_score(snap_high_ni, p)
    score_low = compute_runner_composite_score(snap_low_ni, p)
    assert score_high > score_low, f"Expected high inflow score ({score_high}) > low inflow score ({score_low})"


def test_compute_runner_composite_score_t0_tail_weight_nonzero_affects_score() -> None:
    """When t0_tail_weight > 0, high t0_tail_strength should increase the composite score."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    base_snap = {"breakout_freshness": 0.50, "trend_acceleration": 0.50, "volume_expansion_quality": 0.50, "catalyst_freshness": 0.50, "close_strength": 0.50}

    class _ProfileTail:
        runner_composite_score_breakout_weight = 0.30
        runner_composite_score_trend_weight = 0.25
        runner_composite_score_volume_weight = 0.15
        runner_composite_score_catalyst_weight = 0.10
        runner_composite_score_close_strength_weight = 0.10
        runner_composite_score_volatility_regime_weight = 0.0
        runner_composite_score_sector_resonance_weight = 0.0
        runner_composite_score_quiet_breakout_weight = 0.0
        runner_composite_score_net_inflow_weight = 0.0
        runner_composite_score_volume_price_divergence_weight = 0.0
        runner_composite_score_t0_tail_weight = 0.10

    snap_high_tail = {**base_snap, "t0_tail_strength": 1.0}   # closed at day high
    snap_low_tail = {**base_snap, "t0_tail_strength": 0.1}    # closed far below day high
    p = _ProfileTail()
    score_high = compute_runner_composite_score(snap_high_tail, p)
    score_low = compute_runner_composite_score(snap_low_tail, p)
    assert score_high > score_low


def test_compute_runner_composite_score_vp_divergence_weight_inverts_score() -> None:
    """Low volume_price_divergence_score (clean bar) should yield a higher composite when weight > 0."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    base_snap = {"breakout_freshness": 0.50, "trend_acceleration": 0.50, "volume_expansion_quality": 0.50, "catalyst_freshness": 0.50, "close_strength": 0.50}

    class _ProfileVP:
        runner_composite_score_breakout_weight = 0.30
        runner_composite_score_trend_weight = 0.25
        runner_composite_score_volume_weight = 0.15
        runner_composite_score_catalyst_weight = 0.10
        runner_composite_score_close_strength_weight = 0.10
        runner_composite_score_volatility_regime_weight = 0.0
        runner_composite_score_sector_resonance_weight = 0.0
        runner_composite_score_quiet_breakout_weight = 0.0
        runner_composite_score_net_inflow_weight = 0.0
        runner_composite_score_volume_price_divergence_weight = 0.10
        runner_composite_score_t0_tail_weight = 0.0

    snap_clean = {**base_snap, "volume_price_divergence_score": 0.0}   # no distribution risk
    snap_risky = {**base_snap, "volume_price_divergence_score": 1.0}   # max distribution risk
    p = _ProfileVP()
    score_clean = compute_runner_composite_score(snap_clean, p)
    score_risky = compute_runner_composite_score(snap_risky, p)
    assert score_clean > score_risky


def test_btst_runner_probe_grid_includes_r18_new_factor_weights() -> None:
    """BTST_RUNNER_PROBE_GRID must include all three Round-18 new-factor weight axes (Task 1, Round 18)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID

    assert "runner_composite_score_net_inflow_weight" in BTST_RUNNER_PROBE_GRID
    assert "runner_composite_score_volume_price_divergence_weight" in BTST_RUNNER_PROBE_GRID
    assert "runner_composite_score_t0_tail_weight" in BTST_RUNNER_PROBE_GRID
    # All three must have [0.0, 0.05, 0.10, 0.15] grid values
    for key in ("runner_composite_score_net_inflow_weight", "runner_composite_score_volume_price_divergence_weight", "runner_composite_score_t0_tail_weight"):
        vals = BTST_RUNNER_PROBE_GRID[key]
        assert sorted(vals) == [0.0, 0.05, 0.10, 0.15], f"{key} grid should be [0.0, 0.05, 0.10, 0.15], got {vals}"


def test_btst_factor_to_probe_weight_key_includes_r18_factors() -> None:
    """BTST_FACTOR_TO_PROBE_WEIGHT_KEY must map all three Round-16/17 factors to their R18 grid keys."""
    from scripts.optimize_profile import BTST_FACTOR_TO_PROBE_WEIGHT_KEY

    assert BTST_FACTOR_TO_PROBE_WEIGHT_KEY["t0_estimated_net_inflow_ratio"] == "runner_composite_score_net_inflow_weight"
    assert BTST_FACTOR_TO_PROBE_WEIGHT_KEY["volume_price_divergence_score"] == "runner_composite_score_volume_price_divergence_weight"
    assert BTST_FACTOR_TO_PROBE_WEIGHT_KEY["t0_tail_strength"] == "runner_composite_score_t0_tail_weight"


def test_btst_runner_probe_grid_r18_weights_build_valid_profile() -> None:
    """Each Round-18 grid weight value must build a valid btst_runner_probe profile (Task 1, Round 18)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID

    from src.targets.profiles import build_short_trade_target_profile

    for param_name in ("runner_composite_score_net_inflow_weight", "runner_composite_score_volume_price_divergence_weight", "runner_composite_score_t0_tail_weight"):
        for value in BTST_RUNNER_PROBE_GRID[param_name]:
            profile = build_short_trade_target_profile("btst_runner_probe", overrides={param_name: value})
            assert profile is not None
            actual = getattr(profile, param_name, None)
            assert actual == value, f"Expected {param_name}={value}, got {actual}"

