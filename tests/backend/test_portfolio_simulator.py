"""Tests for POST /portfolio/simulate-adjustment (P2 2.3)."""

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.routes.portfolio_simulator import (
    _compute_risk_from_state,
    AdjustmentItem,
    apply_adjustments,
    DecisionInput,
    PositionInput,
    SimulateAdjustmentRequest,
    SimulateAdjustmentResponse,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_request() -> dict:
    """Return a representative simulation request payload."""
    return {
        "positions": {
            "AAPL": {"long": 100, "short": 0, "long_cost_basis": 180.0, "short_cost_basis": 0.0},
            "MSFT": {"long": 50, "short": 0, "long_cost_basis": 400.0, "short_cost_basis": 0.0},
            "NVDA": {"long": 0, "short": 30, "long_cost_basis": 0.0, "short_cost_basis": 500.0},
        },
        "current_prices": {"AAPL": 190.0, "MSFT": 420.0, "NVDA": 510.0},
        "decisions": {
            "AAPL": {"action": "hold", "quantity": 0},
            "MSFT": {"action": "buy", "quantity": 20},
            "NVDA": {"action": "cover", "quantity": 10},
        },
        "cash": 100000.0,
        "adjustments": [
            {"ticker": "MSFT", "operation": "cancel"},
            {"ticker": "AAPL", "operation": "reduce", "reduce_pct": 0.5},
        ],
    }


# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------


class TestComputeRiskFromState:
    """Tests for _compute_risk_from_state."""

    def test_single_position_hhi_is_one(self):
        positions = {"AAPL": {"long": 100, "short": 0}}
        prices = {"AAPL": 100.0}
        result = _compute_risk_from_state(positions, prices, cash=0.0)
        assert result.hhi == 1.0
        assert result.position_count == 1

    def test_two_equal_positions_hhi_is_half(self):
        positions = {
            "AAPL": {"long": 100, "short": 0},
            "MSFT": {"long": 100, "short": 0},
        }
        prices = {"AAPL": 100.0, "MSFT": 100.0}
        result = _compute_risk_from_state(positions, prices, cash=0.0)
        # Each weight = 0.5, HHI = 0.25 + 0.25 = 0.5
        assert result.hhi == 0.5
        assert result.position_count == 2

    def test_cash_included_in_nav(self):
        positions = {"AAPL": {"long": 100, "short": 0}}
        prices = {"AAPL": 100.0}
        result = _compute_risk_from_state(positions, prices, cash=10000.0)
        # NAV = 10000 + 100*100 = 20000
        assert result.total_nav == 20000.0
        # Weight = 10000 / 20000 = 0.5
        assert result.hhi == 0.25  # 0.5^2

    def test_empty_positions_returns_default(self):
        result = _compute_risk_from_state({}, {}, cash=5000.0)
        assert result.hhi == 0.0
        assert result.position_count == 0
        assert result.total_nav == 5000.0

    def test_short_ratio_computed_correctly(self):
        positions = {
            "AAPL": {"long": 100, "short": 0},
            "TSLA": {"long": 0, "short": 50},
        }
        prices = {"AAPL": 100.0, "TSLA": 200.0}
        result = _compute_risk_from_state(positions, prices, cash=0.0)
        # long = 10000, short = 10000, gross = 20000
        assert result.short_ratio == 0.5


class TestApplyAdjustments:
    """Tests for apply_adjustments."""

    def test_cancel_sets_action_to_hold(self):
        positions = {
            "AAPL": {"long": 100, "short": 0, "long_cost_basis": 180.0, "short_cost_basis": 0.0},
        }
        decisions = {"AAPL": DecisionInput(action="sell", quantity=50)}
        adjustments = [AdjustmentItem(ticker="AAPL", operation="cancel")]

        adj_pos, adj_dec, results, _ = apply_adjustments(
            positions,
            {"AAPL": 190.0},
            decisions,
            10000.0,
            adjustments,
        )

        assert results["AAPL"].simulated_action == "hold"
        assert results["AAPL"].operation_applied == "cancel"
        # Position should remain unchanged (cancel prevents the sell)
        assert adj_pos["AAPL"]["long"] == 100

    def test_reduce_sells_fraction_of_long(self):
        positions = {
            "MSFT": {"long": 100, "short": 0, "long_cost_basis": 400.0, "short_cost_basis": 0.0},
        }
        decisions = {"MSFT": DecisionInput(action="hold", quantity=0)}
        adjustments = [AdjustmentItem(ticker="MSFT", operation="reduce", reduce_pct=0.5)]

        adj_pos, _, results, adj_cash = apply_adjustments(
            positions,
            {"MSFT": 420.0},
            decisions,
            10000.0,
            adjustments,
        )

        assert results["MSFT"].simulated_action == "sell"
        assert results["MSFT"].simulated_quantity == 50  # 100 * 0.5
        assert adj_pos["MSFT"]["long"] == 50
        # Cash should increase by 50 * 420
        assert adj_cash == 10000.0 + 50 * 420.0

    def test_reduce_covers_fraction_of_short(self):
        positions = {
            "NVDA": {"long": 0, "short": 30, "long_cost_basis": 0.0, "short_cost_basis": 500.0},
        }
        decisions = {"NVDA": DecisionInput(action="hold", quantity=0)}
        adjustments = [AdjustmentItem(ticker="NVDA", operation="reduce", reduce_pct=0.5)]

        adj_pos, _, results, adj_cash = apply_adjustments(
            positions,
            {"NVDA": 510.0},
            decisions,
            10000.0,
            adjustments,
        )

        assert results["NVDA"].simulated_action == "cover"
        assert results["NVDA"].simulated_quantity == 15  # 30 * 0.5
        assert adj_pos["NVDA"]["short"] == 15

    def test_no_adjustments_leaves_positions_unchanged(self):
        positions = {
            "AAPL": {"long": 100, "short": 0, "long_cost_basis": 180.0, "short_cost_basis": 0.0},
        }
        decisions = {"AAPL": DecisionInput(action="hold", quantity=0)}

        adj_pos, _, results, _ = apply_adjustments(
            positions,
            {"AAPL": 190.0},
            decisions,
            10000.0,
            [],
        )

        assert results["AAPL"].operation_applied is None
        assert adj_pos["AAPL"]["long"] == 100

    def test_reduce_on_ticker_without_decision(self):
        """Adjustment on a ticker that has a position but no planned decision."""
        positions = {
            "TSLA": {"long": 200, "short": 0, "long_cost_basis": 250.0, "short_cost_basis": 0.0},
        }
        adjustments = [AdjustmentItem(ticker="TSLA", operation="reduce", reduce_pct=0.25)]

        adj_pos, _, results, adj_cash = apply_adjustments(
            positions,
            {"TSLA": 260.0},
            {},
            50000.0,
            adjustments,
        )

        assert results["TSLA"].simulated_action == "sell"
        assert results["TSLA"].simulated_quantity == 50  # 200 * 0.25
        assert adj_pos["TSLA"]["long"] == 150


# ---------------------------------------------------------------------------
# Integration tests — FastAPI TestClient
# ---------------------------------------------------------------------------


class TestSimulateAdjustmentEndpoint:
    """Integration tests for POST /portfolio/simulate-adjustment."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_full_simulation_returns_before_after_delta(self, client):
        resp = client.post("/portfolio/simulate-adjustment", json=_sample_request())
        assert resp.status_code == 200

        body = resp.json()
        assert "before" in body
        assert "after" in body
        assert "delta" in body
        assert "ticker_results" in body
        assert "adjusted_positions" in body

        # Before state should have valid risk metrics
        before = body["before"]
        assert before["total_nav"] > 0
        assert before["hhi"] > 0

        # Delta should be numeric
        delta = body["delta"]
        assert isinstance(delta["hhi"], (int, float))
        assert isinstance(delta["total_nav"], (int, float))

    def test_cancel_buy_reduces_nav(self, client):
        """Canceling a buy should result in lower total NAV vs. executing the buy."""
        payload = {
            "positions": {
                "AAPL": {"long": 100, "short": 0, "long_cost_basis": 180.0, "short_cost_basis": 0.0},
            },
            "current_prices": {"AAPL": 190.0},
            "decisions": {"AAPL": {"action": "buy", "quantity": 50}},
            "cash": 100000.0,
            "adjustments": [{"ticker": "AAPL", "operation": "cancel"}],
        }
        resp = client.post("/portfolio/simulate-adjustment", json=payload)
        assert resp.status_code == 200

        body = resp.json()
        # Before: buy executed -> 150 shares * 190 = 28500 long, cash = 100000
        # After: cancel -> 100 shares * 190 = 19000 long, cash = 100000
        assert body["before"]["total_long"] > body["after"]["total_long"]

    def test_empty_payload_returns_400(self, client):
        resp = client.post(
            "/portfolio/simulate-adjustment",
            json={
                "positions": {},
                "decisions": {},
            },
        )
        assert resp.status_code == 400

    def test_reduce_half_decreases_position_count_if_fully_sold(self, client):
        """Reducing 100% should remove the position from position_count."""
        payload = {
            "positions": {
                "AAPL": {"long": 10, "short": 0, "long_cost_basis": 180.0, "short_cost_basis": 0.0},
                "MSFT": {"long": 50, "short": 0, "long_cost_basis": 400.0, "short_cost_basis": 0.0},
            },
            "current_prices": {"AAPL": 190.0, "MSFT": 420.0},
            "decisions": {},
            "cash": 100000.0,
            "adjustments": [{"ticker": "AAPL", "operation": "reduce", "reduce_pct": 1.0}],
        }
        resp = client.post("/portfolio/simulate-adjustment", json=payload)
        assert resp.status_code == 200

        body = resp.json()
        # AAPL should be gone from active positions (100% sold)
        assert body["after"]["position_count"] < body["before"]["position_count"]

    def test_ticker_results_have_correct_operations(self, client):
        resp = client.post("/portfolio/simulate-adjustment", json=_sample_request())
        body = resp.json()

        results_by_ticker = {r["ticker"]: r for r in body["ticker_results"]}
        # MSFT was canceled
        assert results_by_ticker["MSFT"]["operation_applied"] == "cancel"
        assert results_by_ticker["MSFT"]["simulated_action"] == "hold"
        # AAPL was reduced 50%
        assert results_by_ticker["AAPL"]["operation_applied"] == "reduce"
        assert results_by_ticker["AAPL"]["reduce_pct"] == 0.5
