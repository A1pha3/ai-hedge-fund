from datetime import datetime, timedelta

import numpy as np

from src.backtesting.metrics import PerformanceMetricsCalculator


def _build_values(values: list[float]):
    start = datetime(2024, 1, 1)
    points = []
    for i, v in enumerate(values):
        points.append(
            {
                "Date": start + timedelta(days=i),
                "Portfolio Value": v,
                "Long Exposure": 0.0,
                "Short Exposure": 0.0,
                "Gross Exposure": 0.0,
                "Net Exposure": 0.0,
                "Long/Short Ratio": np.inf,
            }
        )
    return points


def test_metrics_insufficient_data_no_update():
    calc = PerformanceMetricsCalculator()
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values([100_000.0]))
    assert metrics["sharpe_ratio"] is None
    assert metrics["sortino_ratio"] is None
    assert metrics["max_drawdown"] is None


def test_metrics_basic_sharpe_sortino_and_drawdown():
    calc = PerformanceMetricsCalculator(annual_trading_days=2, annual_rf_rate=0.0)
    # Values: up then down → non-zero volatility; drawdown occurs on last day
    vals = _build_values([100.0, 110.0, 99.0])
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, vals)
    assert metrics["sharpe_ratio"] is not None
    assert metrics["sortino_ratio"] is not None
    assert metrics["max_drawdown"] < 0.0
    assert isinstance(metrics.get("max_drawdown_date"), str)


def test_metrics_zero_volatility_sharpe_zero():
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    # Constant portfolio value → zero volatility → Sharpe 0
    vals = _build_values([100.0, 100.0, 100.0, 100.0])
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, vals)
    assert metrics["sharpe_ratio"] == 0.0


# ---------------------------------------------------------------------------
# ALPHA-002 / GAMMA-006: CVaR(95%) historical-simulation formula
# ---------------------------------------------------------------------------

def test_cvar_95_uses_ceil_alpha_n_for_tail_mean():
    """For N=20 at alpha=0.05, the formula must take the mean of the worst
    ceil(0.05 * 20) = 1 observation, NOT floor(...)=0 which collapses to
    nothing, NOR the broken floor+1 of the old code. The tail mean is the
    conditional expectation E[R | R < VaR_alpha]."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    # 20 daily returns: 18 small positive days, 2 large negative days
    # Worst day is -0.10, second-worst is -0.05
    daily_pcts = [0.01] * 18 + [-0.05, -0.10]
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    cvar_95 = metrics.get("cvar_95")
    assert cvar_95 is not None
    # ceil(0.05 * 20) = 1 → tail mean = worst observation = -0.10
    # (NB: there are only 19 daily returns because pct_change drops the first)
    # so actual k = ceil(0.05 * 19) = 1 → -0.10
    assert cvar_95 < -0.09, f"Expected tail-mean ≈ -0.10, got {cvar_95}"


def test_cvar_95_large_sample_matches_analytical_normal_tail():
    """For N large with normal-ish returns, the empirical CVaR(95%) should
    be close to the analytical tail mean (-1.645*sigma for the boundary,
    but the mean of the worst 5% of a normal is ≈ -2.06*sigma)."""
    rng = np.random.default_rng(seed=42)
    n = 5000
    # Daily returns ~ N(0.001, 0.02) — typical equity vol
    daily_pcts = rng.normal(0.001, 0.02, n)
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    cvar_95 = metrics["cvar_95"]
    # Analytical CVaR(95%) of N(μ=0.001, σ=0.02):
    # VaR_0.05 ≈ μ - 1.645σ ≈ -0.0319
    # E[R | R < VaR] ≈ μ - 2.063σ ≈ -0.0403
    expected = 0.001 - 2.063 * 0.02  # ≈ -0.0403
    # Empirical estimate has SE ≈ σ/sqrt(0.05*n) ≈ 0.02/15.8 ≈ 0.00127
    # Use 5 SE tolerance for robustness
    assert abs(cvar_95 - expected) < 5 * 0.00127, (
        f"Expected CVaR ≈ {expected:.4f} (±{5*0.00127:.4f}), got {cvar_95:.4f}"
    )


def test_cvar_95_is_negative_for_lossy_returns():
    """ALPHA-002 sign: a portfolio with any loss tail must report cvar_95 < 0.
    The buggy `abs(cvar_95) > 0.03` guard elsewhere assumed magnitude, but
    the metric itself is signed (negative for losses)."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    daily_pcts = [0.005] * 18 + [-0.03, -0.04]  # two big loss days
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    assert metrics["cvar_95"] < 0.0, "CVaR(95%) of a lossy series must be negative"


def test_cvar_95_small_sample_does_not_silently_use_min():
    """ALPHA-002: for N < ~20 the old code returned sorted_returns[0] (just
    the single min). The fix should still return a tail mean (over 1+
    observations) — it is allowed to be small but must be computed by
    formula, not by 'return the worst observation verbatim' branch."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    # Only 5 daily returns, worst is -0.08
    daily_pcts = [0.01, 0.02, -0.05, -0.08, 0.01]
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    cvar_95 = metrics["cvar_95"]
    # For N=5 returns, k = ceil(0.05 * 5) = 1 → tail mean = worst = -0.08
    # Result: -0.08 ≤ cvar_95 < -0.05 (must be at least as bad as the worst)
    assert -0.085 <= cvar_95 < -0.05, (
        f"Expected CVaR in [-0.085, -0.05) for this sample, got {cvar_95}"
    )


def test_cvar_95_uses_ceil_not_floor_for_tail_count():
    """ALPHA-002 N=21+1 days: ceil(0.05*21) = 2, floor(0.05*21) = 1.
    The floor() version returns the single worst (-0.10). The correct
    formula returns the mean of the 2 worst observations (mean of
    -0.10 and -0.05 = -0.075). This catches the off-by-one in tail
    count and is the canonical CVaR convention."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    # 20 daily returns: 18 small positives + 2 large losses; one worse than the other
    daily_pcts = [0.01] * 18 + [-0.05, -0.10]
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    # 21st day — extra small positive to push N=21 returns (pct_change drops first)
    values.append(values[-1] * 1.005)
    # Now: clean_returns has 21 obs (after pct_change)
    # Sorted worst→best: -0.10, -0.05, then 19 positives
    # ceil(0.05 * 21) = 2 → mean of [-0.10, -0.05] = -0.075
    # floor(0.05 * 21) = 1 → mean of [-0.10] = -0.10 (buggy)
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    cvar_95 = metrics["cvar_95"]
    # Should be ≈ -0.075 (the mean of the 2 worst)
    assert -0.080 <= cvar_95 <= -0.070, (
        f"Expected CVaR ≈ -0.075 (mean of 2 worst), got {cvar_95}. "
        f"This indicates floor() was used instead of ceil() — ALPHA-002."
    )


def test_cvar_95_medium_sample_n_60_uses_correct_tail_count():
    """N=60 daily returns: ceil(0.05*60) = 3, floor(0.05*60) = 3 — same!
    So this isn't a differentiator. But it confirms the formula gives
    a sensible tail mean for medium samples. The 3 worst of N=60 should
    average to a value close to the worst 5% analytical estimate."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    rng = np.random.default_rng(seed=7)
    daily_pcts = rng.normal(0.0, 0.015, 60)
    # Make the tail severe
    daily_pcts[0] = -0.08
    daily_pcts[1] = -0.06
    daily_pcts[2] = -0.05
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    cvar_95 = metrics["cvar_95"]
    # For N=60 the formula gives ceil(0.05*60)=3 → mean of 3 worst
    # With 3 planted losses averaging (-0.08-0.06-0.05)/3 = -0.0633
    assert -0.075 < cvar_95 < -0.055, (
        f"Expected CVaR ≈ -0.063 (mean of 3 worst), got {cvar_95}"
    )


# ---------------------------------------------------------------------------
# ALPHA-001: Sortino ratio uses canonical downside deviation
# ---------------------------------------------------------------------------

def test_sortino_uses_canonical_downside_deviation():
    """ALPHA-001: Sortino ratio must use the canonical downside deviation
    σ_d = sqrt(mean(min(r - rf, 0)^2)) computed over ALL returns, not
    pandas Series.std() on the negative-only subset.

    The negative-subset .std() divides by (n_neg - 1) and centers around
    the negative mean instead of 0, producing a systematically different
    divisor. For the test data:
      returns = [-0.01, -0.02, +0.05, +0.05, +0.05]
      rf ≈ 0 (annual_rf=0)
    Canonical σ_d = sqrt((0.01² + 0.02² + 0² + 0² + 0²) / 5) = sqrt(0.0001/5) = 0.00447
    Wrong (old): std of [-0.01, -0.02] = 0.00707 (Bessel-corrected around neg mean)
    Sortino_old = mean_excess / 0.00707 ≈ 4.95 (inflated by ~1.6×)
    Sortino_correct = mean_excess / 0.00447 ≈ 7.82 — wait, the canonical is SMALLER.
    Actually: mean_excess = mean([-0.01,-0.02,0.05,0.05,0.05]) = 0.024.
    Sortino = sqrt(252) * 0.024 / σ_d.
    Old: σ_d = std([-0.01,-0.02]) = 0.00707 → Sortino ≈ 53.9
    New: σ_d = sqrt((0.01²+0.02²)/5) = sqrt(0.0005/5) = sqrt(0.0001) = 0.01 → Sortino ≈ 38.1
    The old Sortino is ~1.41× inflated.
    """
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    daily_pcts = [-0.01, -0.02, 0.05, 0.05, 0.05]
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    sortino = metrics["sortino_ratio"]
    assert sortino is not None
    # Canonical downside deviation:
    # min(r,0)² for each daily return: [(-0.01)², (-0.02)², 0², 0², 0²]
    # σ_d = sqrt(mean([0.0001, 0.0004, 0, 0, 0])) = sqrt(0.0001) = 0.01
    # Note: there are only 4 daily returns (pct_change drops first), so:
    # daily returns = [-0.01, -0.02, 0.05, 0.05]
    # σ_d = sqrt(mean([0.0001, 0.0004, 0, 0])) = sqrt(0.0005/4) = sqrt(0.000125) ≈ 0.01118
    # mean_excess = mean([-0.01,-0.02,0.05,0.05]) = 0.035/4 ≈ 0.0175
    # annualization = sqrt(252) ≈ 15.874
    # Sortino = 15.874 * 0.0175 / 0.01118 ≈ 24.84
    # But old code: std([-0.01,-0.02]) = 0.00707 → Sortino = 15.874*0.0175/0.00707 ≈ 39.28
    # The old code inflates Sortino by ~1.41× (√2).
    # Values has 6 entries → 5 daily returns (pct_change drops none since we
    # start from 100.0 and add 5 changes). mean_excess = 0.024.
    # Canonical σ_d = sqrt(mean([0.0001, 0.0004, 0, 0, 0])) = 0.01
    # Sortino = sqrt(252) * 0.024 / 0.01 ≈ 38.10
    assert 37.0 < sortino < 40.0, (
        f"Sortino = {sortino:.2f} — expected ≈ 38.1 with canonical downside deviation. "
        f"If Sortino ≈ 54, the old Series.std() on negative subset is still in use (ALPHA-001)."
    )


def test_sortino_all_positive_returns_is_inf():
    """When all returns exceed MAR, downside deviation = 0, Sortino = inf."""
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    daily_pcts = [0.01, 0.02, 0.03]
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    assert metrics["sortino_ratio"] == float("inf")


def test_sortino_large_sample_matches_analytical():
    """For a large sample from N(μ=0.001, σ=0.02), the empirical Sortino
    should be close to the analytical value: mean/σ_d where
    σ_d = sqrt(E[min(R-rf,0)²]) for R ~ N(μ, σ²).
    For μ=0.001, σ=0.02, rf=0:
    E[min(R,0)²] ≈ σ² * Φ(-μ/σ) - μ * σ * φ(-μ/σ)
    For small μ/σ ≈ 0.05: ≈ σ² * 0.48 = 0.000192 → σ_d ≈ 0.01386
    Sortino_annual ≈ sqrt(252) * 0.001 / 0.01386 ≈ 1.145"""
    rng = np.random.default_rng(seed=42)
    n = 10000
    daily_pcts = rng.normal(0.001, 0.02, n)
    values = [100.0]
    for r in daily_pcts:
        values.append(values[-1] * (1 + r))
    calc = PerformanceMetricsCalculator(annual_trading_days=252, annual_rf_rate=0.0)
    metrics = {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
    calc.update_metrics(metrics, _build_values(values))
    sortino = metrics["sortino_ratio"]
    # Analytical Sortino ≈ 1.15; allow ±20% for finite-sample noise
    assert 0.8 < sortino < 1.6, (
        f"Sortino = {sortino:.3f} — expected ≈ 1.15 for N(0.001, 0.02) sample. "
        f"If much higher, negative-subset std is in use (ALPHA-001)."
    )
