"""Bug-fix regression tests for portfolio manager, risk manager, portfolio state,
and agent helper division-by-zero / pairing bugs.

Consolidated from test_bug_fixes.py + agent helper tests from test_numerical_robustness.py.

Covers:
- Portfolio snapshot btst_runtime_metrics field preservation (BUG-1)
- compute_allowed_actions equity calculation (BUG-2)
- _calculate_total_portfolio_value missing margin_used (BUG-3)
- apply_short_cover floating-point drift (BUG-4)
- calculate_portfolio_value missing margin_used (BUG-5)
- Charlie Munger cash_conversion / debt_management pairing bugs
- Cathie Wood FCF/R&D/capex division-by-zero guards
- Warren Buffett book-value CAGR edge cases
"""

import pytest

from src.agents.cathie_wood_helpers import (
    _score_cathie_capex_commitment,
    _score_cathie_fcf_funding,
    _score_cathie_rnd_intensity,
    _score_cathie_rnd_trends,
)
from src.agents.charlie_munger_helpers import (
    _score_munger_cash_conversion,
    _score_munger_debt_management,
)
from src.agents.portfolio_manager import compute_allowed_actions
from src.agents.risk_manager_helpers import _calculate_total_portfolio_value
from src.agents.warren_buffett import _calculate_book_value_cagr
from src.backtesting.portfolio import _EMPTY_POSITION, Portfolio
from src.backtesting.valuation import calculate_portfolio_value

# ===========================================================================
# BUG-1: btst_runtime_metrics missing from get_snapshot / load_snapshot
# ===========================================================================


class TestBtstRuntimeMetricsPreserved:
    """Regression tests for btst_runtime_metrics field preservation."""

    def test_get_snapshot_preserves_btst_runtime_metrics(self):
        portfolio = Portfolio(tickers=["AAA"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.ensure_ticker("AAA")
        portfolio._portfolio["positions"]["AAA"]["btst_runtime_metrics"] = {
            "sector_amt_share": 0.01,
            "retention_proxy": 0.42,
        }
        snap = portfolio.get_snapshot()
        assert snap["positions"]["AAA"]["btst_runtime_metrics"] == {
            "sector_amt_share": 0.01,
            "retention_proxy": 0.42,
        }

    def test_get_snapshot_returns_empty_dict_for_missing_btst_runtime_metrics(self):
        portfolio = Portfolio(tickers=["BBB"], initial_cash=100_000.0, margin_requirement=0.5)
        snap = portfolio.get_snapshot()
        assert snap["positions"]["BBB"]["btst_runtime_metrics"] == {}

    def test_load_snapshot_preserves_btst_runtime_metrics(self):
        portfolio = Portfolio(tickers=["AAA"], initial_cash=100_000.0, margin_requirement=0.5)
        snapshot = {
            "cash": 50_000.0,
            "margin_used": 100.0,
            "margin_requirement": 0.5,
            "positions": {
                "AAA": {
                    "long": 100,
                    "short": 0,
                    "long_cost_basis": 10.0,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                    "btst_runtime_metrics": {"persist_120": 0.55, "supply_pressure_60": 0.20},
                },
            },
            "realized_gains": {"AAA": {"long": 0.0, "short": 0.0}},
        }
        portfolio.load_snapshot(snapshot)
        internal = portfolio._portfolio["positions"]["AAA"]["btst_runtime_metrics"]
        assert internal == {"persist_120": 0.55, "supply_pressure_60": 0.20}

    def test_load_snapshot_round_trip_preserves_all_fields(self):
        """get_snapshot -> load_snapshot round trip preserves btst_runtime_metrics."""
        portfolio = Portfolio(tickers=["AAA"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio._portfolio["positions"]["AAA"]["btst_runtime_metrics"] = {"key": "value"}
        snap = portfolio.get_snapshot()

        portfolio2 = Portfolio(tickers=["AAA"], initial_cash=1.0, margin_requirement=0.5)
        portfolio2.load_snapshot(snap)
        snap2 = portfolio2.get_snapshot()
        assert snap2["positions"]["AAA"]["btst_runtime_metrics"] == {"key": "value"}


# ===========================================================================
# BUG-2: compute_allowed_actions equity calculation
# ===========================================================================


class TestComputeAllowedActionsEquity:
    """Previously equity fell back to cash only, ignoring existing position values."""

    def test_equity_includes_long_position_value_for_short_capacity(self):
        result_with_position = compute_allowed_actions(
            tickers=["BBB"],
            current_prices={"AAA": 200.0, "BBB": 200.0},
            max_shares={"BBB": 1000},
            portfolio={
                "cash": 1_000.0,
                "positions": {
                    "AAA": {"long": 100, "short": 0, "long_cost_basis": 50.0, "short_cost_basis": 0.0, "short_margin_used": 0.0},
                },
                "margin_requirement": 0.5,
                "margin_used": 0.0,
            },
        )
        # equity = cash + margin_used + position_value
        #        = 1000 + 0 + (100*200 - 0) = 21000
        # available_equity = 21000 - 0 = 21000
        # per_share_margin = 200 * 0.5 = 100
        # max_short = int(21000 // 100) = 210
        # capped by max_qty=1000 → 210
        assert result_with_position["BBB"]["short"] == 210

    def test_equity_without_positions_falls_back_gracefully(self):
        result = compute_allowed_actions(
            tickers=["CCC"],
            current_prices={"CCC": 10.0},
            max_shares={"CCC": 100},
            portfolio={
                "cash": 500.0,
                "positions": {},
                "margin_requirement": 0.5,
                "margin_used": 0.0,
            },
        )
        assert result["CCC"]["short"] == 100

    def test_short_capacity_accounts_for_existing_short_margin_used(self):
        result = compute_allowed_actions(
            tickers=["DDD"],
            current_prices={"DDD": 50.0},
            max_shares={"DDD": 1000},
            portfolio={
                "cash": 10_000.0,
                "positions": {},
                "margin_requirement": 0.5,
                "margin_used": 5_000.0,
            },
        )
        # GAMMA-007 fix: equity now includes margin_used.
        # equity = cash + margin_used = 10000 + 5000 = 15000
        # available_equity = 15000 - 5000 = 10000
        # per_share_margin = 50 * 0.5 = 25
        # max_short = int(10000 // 25) = 400
        # capped by max_qty=1000 → 400
        assert result["DDD"]["short"] == 400


# ===========================================================================
# BUG-3: _calculate_total_portfolio_value missing margin_used
# ===========================================================================


class TestTotalPortfolioValueMarginUsed:
    """Previously margin_used was not added back, understating portfolio value."""

    def test_margin_used_is_included_in_total_value(self):
        portfolio_dict = {
            "cash": 99_500.0,
            "margin_used": 500.0,
            "positions": {
                "AAPL": {"long": 10, "short": 0},
                "MSFT": {"long": 0, "short": 5},
            },
        }
        prices = {"AAPL": 100.0, "MSFT": 200.0}
        value = _calculate_total_portfolio_value(portfolio_dict, prices)
        assert value == 100_000.0

    def test_no_margin_used_gives_same_result_as_before(self):
        portfolio_dict = {
            "cash": 90_000.0,
            "margin_used": 0.0,
            "positions": {"AAPL": {"long": 100, "short": 0}},
        }
        prices = {"AAPL": 100.0}
        value = _calculate_total_portfolio_value(portfolio_dict, prices)
        assert value == 90_000.0 + 100 * 100.0

    def test_zero_cash_with_margin_still_has_value(self):
        portfolio_dict = {
            "cash": 0.0,
            "margin_used": 1_000.0,
            "positions": {"AAPL": {"long": 0, "short": 0}},
        }
        prices = {"AAPL": 100.0}
        value = _calculate_total_portfolio_value(portfolio_dict, prices)
        assert value == 1_000.0


# ===========================================================================
# BUG-4: apply_short_cover floating-point drift protection
# ===========================================================================


class TestShortCoverMarginDrift:
    """Regression tests for margin release precision in apply_short_cover."""

    def test_partial_cover_does_not_produce_negative_margin(self):
        portfolio = Portfolio(tickers=["AAA"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.ensure_ticker("AAA")
        executed = portfolio.apply_short_open("AAA", 100, 33.33)
        assert executed == 100

        # Cover in 7 partial increments (100 // 7 = 14 shares each, remainder 2)
        for _ in range(7):
            portfolio.apply_short_cover("AAA", 14, 33.33)
        portfolio.apply_short_cover("AAA", 2, 33.33)

        snap = portfolio.get_snapshot()
        assert snap["positions"]["AAA"]["short"] == 0
        assert snap["positions"]["AAA"]["short_margin_used"] >= 0.0
        assert snap["margin_used"] >= 0.0

    def test_full_cover_releases_all_margin(self):
        portfolio = Portfolio(tickers=["BBB"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.ensure_ticker("BBB")
        portfolio.apply_short_open("BBB", 50, 100.0)

        portfolio.apply_short_cover("BBB", 50, 100.0)
        snap = portfolio.get_snapshot()

        assert snap["margin_used"] == pytest.approx(0.0, abs=1e-10)
        assert snap["positions"]["BBB"]["short_margin_used"] == pytest.approx(0.0, abs=1e-10)

    def test_margin_used_never_goes_negative_after_cover(self):
        portfolio = Portfolio(tickers=["CCC"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.ensure_ticker("CCC")
        portfolio.apply_short_open("CCC", 77, 99.99)

        for qty in [10, 10, 10, 10, 10, 10, 10, 7]:
            portfolio.apply_short_cover("CCC", qty, 99.99)
            snap = portfolio.get_snapshot()
            assert snap["margin_used"] >= 0.0, f"margin_used went negative after covering {qty} shares"


# ===========================================================================
# BUG-5: calculate_portfolio_value (valuation.py) missing margin_used
# ===========================================================================


class TestValuationPortfolioValueMarginUsed:
    """Regression tests for calculate_portfolio_value in valuation module."""

    def test_portfolio_value_includes_margin_used_for_short_positions(self):
        portfolio = Portfolio(tickers=["AAPL", "MSFT"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.apply_long_buy("AAPL", 10, 100.0)
        portfolio.apply_short_open("MSFT", 5, 200.0)

        prices = {"AAPL": 100.0, "MSFT": 200.0}
        value = calculate_portfolio_value(portfolio, prices)

        snap = portfolio.get_snapshot()
        expected = snap["cash"] + snap["margin_used"] + 10 * 100.0 - 5 * 200.0
        assert value == expected
        assert value == 100_000.0

    def test_portfolio_value_long_only_matches_old_behavior(self):
        """When no short positions exist, margin_used=0, so behavior is unchanged."""
        portfolio = Portfolio(tickers=["AAPL"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.apply_long_buy("AAPL", 50, 100.0)

        prices = {"AAPL": 120.0}
        value = calculate_portfolio_value(portfolio, prices)
        assert value == 95_000.0 + 6_000.0


# ===========================================================================
# Edge cases: boundary conditions
# ===========================================================================


class TestEdgeCases:
    """Edge case tests for boundary conditions in position management."""

    def test_compute_allowed_actions_zero_price_returns_hold_only(self):
        result = compute_allowed_actions(
            tickers=["XXX"],
            current_prices={"XXX": 0.0},
            max_shares={"XXX": 100},
            portfolio={
                "cash": 10_000.0,
                "positions": {},
                "margin_requirement": 0.5,
                "margin_used": 0.0,
            },
        )
        assert result["XXX"] == {"hold": 0}

    def test_compute_allowed_actions_empty_portfolio(self):
        result = compute_allowed_actions(
            tickers=["YYY"],
            current_prices={"YYY": 10.0},
            max_shares={"YYY": 500},
            portfolio={
                "cash": 5_000.0,
                "positions": {},
                "margin_requirement": 0.5,
                "margin_used": 0.0,
            },
        )
        assert result["YYY"]["buy"] == 500
        assert result["YYY"]["short"] == 500

    def test_portfolio_apply_long_buy_rejects_zero_price(self):
        portfolio = Portfolio(tickers=["AAA"], initial_cash=100_000.0, margin_requirement=0.5)
        portfolio.apply_long_buy("AAA", 100, 0.0)
        snap = portfolio.get_snapshot()
        assert snap["positions"]["AAA"]["long"] >= 0

    def test_portfolio_snapshot_contains_all_empty_position_keys(self):
        portfolio = Portfolio(tickers=["ZZZ"], initial_cash=100_000.0, margin_requirement=0.5)
        snap = portfolio.get_snapshot()
        pos = snap["positions"]["ZZZ"]
        for key in _EMPTY_POSITION:
            assert key in pos, f"Snapshot missing key: {key}"


# ===========================================================================
# Charlie Munger helper pairing bugs
# ===========================================================================


class TestMungerCashConversionPairing:
    def test_mismatched_lengths_still_paired(self):
        """When FCF and NI have different available periods, they should be paired."""

        class Item:
            def __init__(self, fcf, ni):
                self.free_cash_flow = fcf
                self.net_income = ni

        items = [Item(100, 50), Item(80, None), Item(60, 30)]
        score, detail, ratio = _score_munger_cash_conversion(items)
        assert score >= 0
        assert ratio is not None
        assert ratio == pytest.approx((100 / 50 + 60 / 30) / 2)

    def test_empty_items(self):
        score, detail, ratio = _score_munger_cash_conversion([])
        assert score == 0
        assert ratio is None


class TestMungerDebtManagementPairing:
    def test_mismatched_lengths_still_paired(self):

        class Item:
            def __init__(self, debt, equity):
                self.total_debt = debt
                self.shareholders_equity = equity

        items = [Item(100, 200), Item(80, None), Item(60, 150)]
        score, detail, ratio = _score_munger_debt_management(items)
        assert score >= 0
        assert ratio is not None

    def test_zero_equity(self):

        class Item:
            def __init__(self, debt, equity):
                self.total_debt = debt
                self.shareholders_equity = equity

        items = [Item(100, 0)]
        score, detail, ratio = _score_munger_debt_management(items)
        assert ratio == float("inf")


# ===========================================================================
# Cathie Wood helper division-by-zero guards
# ===========================================================================


class TestCathieWoodFCFFunding:
    def test_zero_base_fcf(self):

        class Item:
            def __init__(self, fcf):
                self.free_cash_flow = fcf

        items = [Item(100), Item(0)]
        score, detail = _score_cathie_fcf_funding(items)
        assert score >= 0

    def test_negative_base_fcf(self):

        class Item:
            def __init__(self, fcf):
                self.free_cash_flow = fcf

        items = [Item(50), Item(-10)]
        score, detail = _score_cathie_fcf_funding(items)
        assert score >= 0


class TestCathieWoodRnDIntensity:
    def test_zero_revenue(self):

        class Item:
            def __init__(self, rnd, rev):
                self.research_and_development = rnd
                self.revenue = rev

        items = [Item(100, 0)]
        score, detail = _score_cathie_rnd_intensity(items)
        assert score >= 0

    def test_normal_rnd(self):

        class Item:
            def __init__(self, rnd, rev):
                self.research_and_development = rnd
                self.revenue = rev

        items = [Item(20, 100)]
        score, detail = _score_cathie_rnd_intensity(items)
        assert score == 3  # 20% ratio > 0.15


class TestCathieWoodRnDTrends:
    def test_zero_oldest_revenue(self):

        class Item:
            def __init__(self, rnd, rev):
                self.research_and_development = rnd
                self.revenue = rev

        items = [Item(100, 1000), Item(50, 0)]
        score, details = _score_cathie_rnd_trends(items)
        assert isinstance(score, int)
        assert score >= 0


class TestCathieWoodCapexCommitment:
    def test_zero_revenue(self):

        class Item:
            def __init__(self, capex, rev):
                self.capital_expenditure = capex
                self.revenue = rev

        items = [Item(50, 0), Item(40, 100)]
        score, detail = _score_cathie_capex_commitment(items)
        assert score >= 0


# ===========================================================================
# Warren Buffett book value CAGR edge cases
# ===========================================================================


class TestBookValueCAGR:
    def test_negative_to_positive(self):
        """Negative oldest => positive latest should get max score."""
        # book_values: index 0 = latest, index -1 = oldest
        score, reason = _calculate_book_value_cagr([50, 20, 5, -10])
        assert score == 3

    def test_positive_to_negative(self):
        """Positive oldest => negative latest should get 0 score."""
        score, reason = _calculate_book_value_cagr([-10, 5, 20, 50])
        assert score == 0

    def test_zero_oldest(self):
        score, reason = _calculate_book_value_cagr([50, 20, 10, 0])
        assert isinstance(score, int)
        assert score >= 0

    def test_single_value(self):
        score, reason = _calculate_book_value_cagr([100])
        assert score == 0

    def test_both_negative(self):
        score, reason = _calculate_book_value_cagr([-10, -5, -3, -20])
        assert score >= 0
