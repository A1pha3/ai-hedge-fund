"""Tests for simplified Brinson return attribution model.

Covers: single ticker, multi-ticker, short positions, zero positions,
empty data, attribution identity check (allocation + selection + residual ~ total return),
custom benchmarks, and snapshot-based convenience wrapper.
"""

import math

import pytest

from src.portfolio.return_attribution import (
    AttributionResult,
    brinson_attribution,
    brinson_attribution_from_snapshots,
    compute_benchmark_returns_from_equal_weight,
    compute_equal_weight_benchmark,
    compute_portfolio_weights,
    TickerAttribution,
)


# ---------------------------------------------------------------------------
# Helper: assert two floats are close (handles inf, nan)
# ---------------------------------------------------------------------------
def _assert_close(a: float, b: float, tol: float = 1e-9) -> None:
    if math.isinf(a) and math.isinf(b):
        assert a == b
        return
    assert abs(a - b) < tol, f"{a} != {b} (tol={tol})"


# ===========================================================================
# 1. compute_portfolio_weights
# ===========================================================================
class TestComputePortfolioWeights:
    def test_basic_weights(self) -> None:
        """Weights should sum to 1.0 for positive market values."""
        weights = compute_portfolio_weights({"AAPL": 600.0, "MSFT": 400.0}, 1000.0)
        _assert_close(weights["AAPL"], 0.6)
        _assert_close(weights["MSFT"], 0.4)

    def test_zero_total_value(self) -> None:
        """Zero portfolio value -> all weights zero."""
        weights = compute_portfolio_weights({"AAPL": 100.0}, 0.0)
        assert weights["AAPL"] == 0.0

    def test_short_negative_weight(self) -> None:
        """Short positions have negative market value and negative weight."""
        weights = compute_portfolio_weights({"AAPL": 1000.0, "MSFT": -500.0}, 500.0)
        _assert_close(weights["AAPL"], 2.0)
        _assert_close(weights["MSFT"], -1.0)


# ===========================================================================
# 2. compute_equal_weight_benchmark
# ===========================================================================
class TestEqualWeightBenchmark:
    def test_equal_weights(self) -> None:
        bw = compute_equal_weight_benchmark(["A", "B", "C"], {"A": 0.1, "B": 0.2, "C": 0.3})
        _assert_close(bw["A"], 1.0 / 3)
        _assert_close(bw["B"], 1.0 / 3)
        _assert_close(bw["C"], 1.0 / 3)

    def test_ticker_without_return_gets_zero(self) -> None:
        bw = compute_equal_weight_benchmark(["A", "B", "C"], {"A": 0.1})
        _assert_close(bw["A"], 1.0)
        _assert_close(bw["B"], 0.0)
        _assert_close(bw["C"], 0.0)

    def test_empty_returns(self) -> None:
        bw = compute_equal_weight_benchmark(["A", "B"], {})
        assert bw["A"] == 0.0
        assert bw["B"] == 0.0


# ===========================================================================
# 3. compute_benchmark_returns_from_equal_weight
# ===========================================================================
class TestBenchmarkReturnsFromEqualWeight:
    def test_total_return(self) -> None:
        bw = {"A": 0.5, "B": 0.5}
        tr = {"A": 0.10, "B": 0.20}
        result = compute_benchmark_returns_from_equal_weight(tr, bw)
        _assert_close(result, 0.15)


# ===========================================================================
# 4. brinson_attribution — core tests
# ===========================================================================
class TestBrinsonAttribution:
    def test_empty_ticker_returns(self) -> None:
        """Empty returns -> empty result."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={},
            ticker_market_values={},
            total_portfolio_value=100_000.0,
        )
        assert result.tickers == []
        assert result.total_portfolio_return == 0.0

    def test_zero_portfolio_value(self) -> None:
        """Zero portfolio value -> empty result."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.05},
            ticker_market_values={"AAPL": 1000.0},
            total_portfolio_value=0.0,
        )
        assert result.tickers == []

    def test_single_ticker_equal_weight(self) -> None:
        """Single ticker with 100% weight. Allocation=0, Selection=0 (no benchmark diff)."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10},
            ticker_market_values={"AAPL": 100_000.0},
            total_portfolio_value=100_000.0,
        )
        assert len(result.tickers) == 1
        t = result.tickers[0]
        _assert_close(t.portfolio_weight, 1.0)
        _assert_close(t.benchmark_weight, 1.0)  # equal-weight default
        _assert_close(t.portfolio_return, 0.10)
        _assert_close(t.benchmark_return, 0.10)  # default = same returns
        _assert_close(t.allocation_contribution, 0.0)
        _assert_close(t.selection_contribution, 0.0)
        _assert_close(result.total_portfolio_return, 0.10)

    def test_two_tickers_overweight_winner(self) -> None:
        """Overweight a ticker that outperforms -> positive allocation contribution."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.20, "MSFT": 0.05},
            ticker_market_values={"AAPL": 80_000.0, "MSFT": 20_000.0},
            total_portfolio_value=100_000.0,
        )
        assert len(result.tickers) == 2

        aapl = next(t for t in result.tickers if t.ticker == "AAPL")
        msft = next(t for t in result.tickers if t.ticker == "MSFT")

        # Equal-weight benchmark: w_b = 0.5 each, r_b = r_p (no external benchmark)
        # AAPL: alloc = (0.8 - 0.5) * 0.20 = 0.06
        # MSFT: alloc = (0.2 - 0.5) * 0.05 = -0.015
        _assert_close(aapl.allocation_contribution, 0.06)
        _assert_close(msft.allocation_contribution, -0.015)

        # Selection: w_p * (r_p - r_b). Since r_b = r_p by default, selection = 0
        _assert_close(aapl.selection_contribution, 0.0)
        _assert_close(msft.selection_contribution, 0.0)

        # Total portfolio return = 0.8*0.2 + 0.2*0.05 = 0.17
        _assert_close(result.total_portfolio_return, 0.17)

    def test_selection_contribution_with_custom_benchmark_returns(self) -> None:
        """When benchmark returns differ from portfolio returns, selection != 0."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.15, "MSFT": 0.05},
            ticker_market_values={"AAPL": 50_000.0, "MSFT": 50_000.0},
            total_portfolio_value=100_000.0,
            benchmark_returns={"AAPL": 0.10, "MSFT": 0.08},
        )
        aapl = next(t for t in result.tickers if t.ticker == "AAPL")
        msft = next(t for t in result.tickers if t.ticker == "MSFT")

        # AAPL selection = 0.5 * (0.15 - 0.10) = 0.025
        _assert_close(aapl.selection_contribution, 0.025)
        # MSFT selection = 0.5 * (0.05 - 0.08) = -0.015
        _assert_close(msft.selection_contribution, -0.015)

    def test_custom_benchmark_weights(self) -> None:
        """Explicit benchmark weights override equal-weight default."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10},
            ticker_market_values={"AAPL": 100_000.0},
            total_portfolio_value=100_000.0,
            benchmark_weights={"AAPL": 0.3},
            benchmark_returns={"AAPL": 0.05},
        )
        t = result.tickers[0]
        # alloc = (1.0 - 0.3) * 0.05 = 0.035
        _assert_close(t.allocation_contribution, 0.035)
        # select = 1.0 * (0.10 - 0.05) = 0.05
        _assert_close(t.selection_contribution, 0.05)

    def test_attribution_identity_no_residual_default_benchmark(self) -> None:
        """With default benchmark (r_b = r_p), allocation + selection + residual = total return."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.15, "MSFT": 0.05, "NVDA": 0.30},
            ticker_market_values={"AAPL": 50_000.0, "MSFT": 30_000.0, "NVDA": 20_000.0},
            total_portfolio_value=100_000.0,
        )
        total = result.total_allocation_contribution + result.total_selection_contribution + result.total_residual
        _assert_close(total, result.total_portfolio_return)

    def test_attribution_identity_with_external_benchmark(self) -> None:
        """With external benchmark, allocation + selection + residual = total return."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.12, "MSFT": 0.04},
            ticker_market_values={"AAPL": 60_000.0, "MSFT": 40_000.0},
            total_portfolio_value=100_000.0,
            benchmark_weights={"AAPL": 0.5, "MSFT": 0.5},
            benchmark_returns={"AAPL": 0.10, "MSFT": 0.06},
        )
        total = result.total_allocation_contribution + result.total_selection_contribution + result.total_residual
        _assert_close(total, result.total_portfolio_return)

    def test_short_position_attribution(self) -> None:
        """Short position with negative market value and weight."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10, "MSFT": -0.05},
            ticker_market_values={"AAPL": 120_000.0, "MSFT": -20_000.0},
            total_portfolio_value=100_000.0,
        )
        aapl = next(t for t in result.tickers if t.ticker == "AAPL")
        msft = next(t for t in result.tickers if t.ticker == "MSFT")

        _assert_close(aapl.portfolio_weight, 1.2)
        _assert_close(msft.portfolio_weight, -0.2)

        # total return = 1.2*0.10 + (-0.2)*(-0.05) = 0.12 + 0.01 = 0.13
        _assert_close(result.total_portfolio_return, 0.13)

    def test_zero_position_ticker(self) -> None:
        """Ticker with zero market value gets zero weight but may have allocation
        contribution from the benchmark side (underweight penalty)."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10, "CASH_EQUIV": 0.02},
            ticker_market_values={"AAPL": 100_000.0, "CASH_EQUIV": 0.0},
            total_portfolio_value=100_000.0,
        )
        cash_eq = next(t for t in result.tickers if t.ticker == "CASH_EQUIV")
        _assert_close(cash_eq.portfolio_weight, 0.0)
        # With equal-weight benchmark, CASH_EQUIV gets w_b=0.5, r_b=r_p=0.02
        # allocation = (0 - 0.5) * 0.02 = -0.01
        # This is the underweight penalty — correct behavior
        _assert_close(cash_eq.allocation_contribution, -0.01)
        # selection = 0 * (0.02 - 0.02) = 0
        _assert_close(cash_eq.selection_contribution, 0.0)

    def test_all_tickers_negative_returns(self) -> None:
        """All negative returns -> negative total return."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": -0.10, "MSFT": -0.05},
            ticker_market_values={"AAPL": 50_000.0, "MSFT": 50_000.0},
            total_portfolio_value=100_000.0,
        )
        assert result.total_portfolio_return < 0
        # Total = 0.5*(-0.10) + 0.5*(-0.05) = -0.075
        _assert_close(result.total_portfolio_return, -0.075)


# ===========================================================================
# 5. AttributionResult.to_dict
# ===========================================================================
class TestAttributionResultToDict:
    def test_to_dict_sorted_by_total_contribution(self) -> None:
        """to_dict sorts tickers by total_contribution descending.
        AAPL: w=0.7, r=0.10, w_b=0.5, r_b=0.10 => alloc=(0.7-0.5)*0.10=0.02, select=0
        MSFT: w=0.3, r=0.30, w_b=0.5, r_b=0.30 => alloc=(0.3-0.5)*0.30=-0.06, select=0
        So AAPL has higher total contribution (0.02 > -0.06).
        """
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10, "MSFT": 0.30},
            ticker_market_values={"AAPL": 70_000.0, "MSFT": 30_000.0},
            total_portfolio_value=100_000.0,
            benchmark_weights={"AAPL": 0.5, "MSFT": 0.5},
        )
        d = result.to_dict()
        # AAPL: alloc = (0.7-0.5)*0.10 = 0.02 (positive, from overweighting)
        # MSFT: alloc = (0.3-0.5)*0.30 = -0.06 (negative, from underweighting)
        # So AAPL ranks first
        assert d["tickers"][0]["ticker"] == "AAPL"
        assert d["start_date"] == "2026-01-01"
        assert d["end_date"] == "2026-01-31"

    def test_to_dict_empty_result(self) -> None:
        result = AttributionResult(start_date="2026-01-01", end_date="2026-01-31")
        d = result.to_dict()
        assert d["tickers"] == []
        assert d["total_portfolio_return"] == 0.0


# ===========================================================================
# 6. brinson_attribution_from_snapshots
# ===========================================================================
class TestBrinsonAttributionFromSnapshots:
    def _make_position(self, long: int = 0, short: int = 0) -> dict:
        return {
            "long": long,
            "short": short,
            "long_cost_basis": 0.0,
            "short_cost_basis": 0.0,
            "short_margin_used": 0.0,
        }

    def test_basic_snapshot_attribution(self) -> None:
        """Two-snapshot attribution: buy 100 AAPL at $100, price goes to $110."""
        start_snap = {
            "cash": 90_000.0,
            "margin_used": 0.0,
            "positions": {"AAPL": self._make_position(long=100)},
        }
        end_snap = {
            "cash": 90_000.0,
            "margin_used": 0.0,
            "positions": {"AAPL": self._make_position(long=100)},
        }
        start_prices = {"AAPL": 100.0}
        end_prices = {"AAPL": 110.0}

        result = brinson_attribution_from_snapshots(
            start_date="2026-01-01",
            end_date="2026-01-31",
            portfolio_snapshots=[start_snap, end_snap],
            price_snapshots=[start_prices, end_prices],
        )
        assert len(result.tickers) == 1
        t = result.tickers[0]
        _assert_close(t.portfolio_return, 0.10)  # 110/100 - 1
        _assert_close(t.portfolio_weight, 10_000.0 / 100_000.0)

    def test_insufficient_snapshots(self) -> None:
        """Less than 2 snapshots -> empty result."""
        result = brinson_attribution_from_snapshots(
            start_date="2026-01-01",
            end_date="2026-01-31",
            portfolio_snapshots=[{"positions": {}}],
            price_snapshots=[{"AAPL": 100.0}],
        )
        assert result.tickers == []

    def test_new_position_entered_mid_period(self) -> None:
        """Ticker not in start but present in end -> return = 0."""
        start_snap = {
            "cash": 100_000.0,
            "margin_used": 0.0,
            "positions": {},
        }
        end_snap = {
            "cash": 90_000.0,
            "margin_used": 0.0,
            "positions": {"MSFT": self._make_position(long=50)},
        }
        start_prices = {"MSFT": 200.0}
        end_prices = {"MSFT": 220.0}

        result = brinson_attribution_from_snapshots(
            start_date="2026-01-01",
            end_date="2026-01-31",
            portfolio_snapshots=[start_snap, end_snap],
            price_snapshots=[start_prices, end_prices],
        )
        # MSFT has no position at start, so it appears with return=0
        if result.tickers:
            msft = result.tickers[0]
            _assert_close(msft.portfolio_return, 0.0)

    def test_short_position_in_snapshots(self) -> None:
        """Short position at start -> negative market value."""
        start_snap = {
            "cash": 110_000.0,
            "margin_used": 0.0,
            "positions": {"AAPL": self._make_position(long=0, short=100)},
        }
        end_snap = {
            "cash": 110_000.0,
            "margin_used": 0.0,
            "positions": {"AAPL": self._make_position(long=0, short=100)},
        }
        start_prices = {"AAPL": 100.0}
        end_prices = {"AAPL": 90.0}

        result = brinson_attribution_from_snapshots(
            start_date="2026-01-01",
            end_date="2026-01-31",
            portfolio_snapshots=[start_snap, end_snap],
            price_snapshots=[start_prices, end_prices],
        )
        assert len(result.tickers) == 1
        t = result.tickers[0]
        # Market value = (0 - 100) * 100 = -10000
        _assert_close(t.portfolio_weight, -10_000.0 / 100_000.0)
        # Price return = 90/100 - 1 = -0.10
        _assert_close(t.portfolio_return, -0.10)


# ===========================================================================
# 7. Ranking and contribution ordering
# ===========================================================================
class TestRanking:
    def test_tickers_ranked_by_contribution(self) -> None:
        """to_dict sorts tickers by total_contribution descending.
        A: w=0.4, r=0.05 => alloc=(0.4-1/3)*0.05, select=0
        B: w=0.4, r=0.10 => alloc=(0.4-1/3)*0.10, select=0
        C: w=0.2, r=-0.03 => alloc=(0.2-1/3)*(-0.03), select=0
        B has the largest allocation contribution.
        """
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"A": 0.05, "B": 0.10, "C": -0.03},
            ticker_market_values={"A": 40_000.0, "B": 40_000.0, "C": 20_000.0},
            total_portfolio_value=100_000.0,
            benchmark_weights={"A": 1.0 / 3, "B": 1.0 / 3, "C": 1.0 / 3},
        )
        d = result.to_dict()
        tickers_ranked = [t["ticker"] for t in d["tickers"]]
        # B has highest return with above-benchmark weight -> highest contribution
        assert tickers_ranked[0] == "B"

    def test_ranking_with_negative_total(self) -> None:
        """Negative contributors rank last."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"WINNER": 0.20, "LOSER": -0.15},
            ticker_market_values={"WINNER": 50_000.0, "LOSER": 50_000.0},
            total_portfolio_value=100_000.0,
            benchmark_weights={"WINNER": 0.5, "LOSER": 0.5},
            benchmark_returns={"WINNER": 0.10, "LOSER": 0.05},
        )
        d = result.to_dict()
        assert d["tickers"][0]["ticker"] == "WINNER"
        assert d["tickers"][-1]["ticker"] == "LOSER"
        assert d["tickers"][-1]["total_contribution"] < 0


# ===========================================================================
# 8. NaN / Inf input guards (regression for v0 audit)
# ===========================================================================
class TestNonFiniteInputGuards:
    """Brinson attribution must reject non-finite (NaN/Inf) inputs instead of
    silently propagating them into all per-ticker / aggregate fields.  Without
    these guards, a single corrupt input would yield ``total_portfolio_return
    = NaN`` and crash downstream JSON consumers (frontend, dashboards)."""

    def test_nan_return_rejected(self) -> None:
        with pytest.raises(ValueError, match="ticker_returns"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": float("nan"), "MSFT": 0.05},
                ticker_market_values={"AAPL": 50_000.0, "MSFT": 50_000.0},
                total_portfolio_value=100_000.0,
            )

    def test_inf_return_rejected(self) -> None:
        with pytest.raises(ValueError, match="ticker_returns"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": float("inf")},
                ticker_market_values={"AAPL": 100_000.0},
                total_portfolio_value=100_000.0,
            )

    def test_nan_market_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="ticker_market_values"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": 0.10},
                ticker_market_values={"AAPL": float("nan")},
                total_portfolio_value=100_000.0,
            )

    def test_inf_total_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="total_portfolio_value"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": 0.10},
                ticker_market_values={"AAPL": 50_000.0},
                total_portfolio_value=float("inf"),
            )

    def test_nan_benchmark_weight_rejected(self) -> None:
        with pytest.raises(ValueError, match="benchmark_weights"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": 0.10},
                ticker_market_values={"AAPL": 100_000.0},
                total_portfolio_value=100_000.0,
                benchmark_weights={"AAPL": float("nan")},
            )

    def test_nan_benchmark_return_rejected(self) -> None:
        with pytest.raises(ValueError, match="benchmark_returns"):
            brinson_attribution(
                start_date="2026-01-01",
                end_date="2026-01-31",
                ticker_returns={"AAPL": 0.10},
                ticker_market_values={"AAPL": 100_000.0},
                total_portfolio_value=100_000.0,
                benchmark_returns={"AAPL": float("nan")},
            )

    def test_normal_inputs_unaffected(self) -> None:
        """The NaN/Inf guard must not change the well-defined result."""
        result = brinson_attribution(
            start_date="2026-01-01",
            end_date="2026-01-31",
            ticker_returns={"AAPL": 0.10},
            ticker_market_values={"AAPL": 100_000.0},
            total_portfolio_value=100_000.0,
        )
        _assert_close(result.total_portfolio_return, 0.10)
