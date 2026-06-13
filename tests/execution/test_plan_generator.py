"""Unit tests for src/execution/plan_generator.py

Verifies default-coercion logic (None → empty collections / default profile)
and that strategy_weights is derived from market_state.adjusted_weights.
"""

from __future__ import annotations

from src.execution.models import ExecutionPlan
from src.execution.plan_generator import generate_execution_plan
from src.screening.models import MarketState
from src.targets.models import DualTargetSummary


def _market_state() -> MarketState:
    return MarketState(adjusted_weights={"trend": 0.4, "fundamental": 0.6})


def test_generate_plan_coerces_none_defaults() -> None:
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=_market_state(),
        watchlist=[],
        logic_scores={},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={},
        risk_alerts=None,
        risk_metrics=None,
        selection_targets=None,
        dual_target_summary=None,
        short_trade_target_profile_name=None,
        short_trade_target_profile_config=None,
    )
    assert isinstance(plan, ExecutionPlan)
    assert plan.date == "20260613"
    assert plan.risk_alerts == []
    assert plan.risk_metrics == {}
    assert plan.selection_targets == {}
    assert isinstance(plan.dual_target_summary, DualTargetSummary)
    assert plan.short_trade_target_profile_name == "default"
    assert plan.short_trade_target_profile_config == {}


def test_generate_plan_strategy_weights_from_market_state() -> None:
    ms = _market_state()
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=ms,
        watchlist=[],
        logic_scores={},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={},
    )
    assert plan.strategy_weights == {"trend": 0.4, "fundamental": 0.6}


def test_generate_plan_preserves_provided_values() -> None:
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=_market_state(),
        watchlist=[],
        logic_scores={"trend": 0.5},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={"cash": 100000},
        risk_alerts=["high_volatility"],
        risk_metrics={"sharpe": 1.2},
        layer_a_count=5,
        layer_b_count=3,
        layer_c_count=2,
        short_trade_target_profile_name="aggressive",
        short_trade_target_profile_config={"stop": 0.05},
    )
    assert plan.logic_scores == {"trend": 0.5}
    assert plan.portfolio_snapshot == {"cash": 100000}
    assert plan.risk_alerts == ["high_volatility"]
    assert plan.risk_metrics == {"sharpe": 1.2}
    assert plan.layer_a_count == 5
    assert plan.layer_b_count == 3
    assert plan.layer_c_count == 2
    assert plan.short_trade_target_profile_name == "aggressive"
    assert plan.short_trade_target_profile_config == {"stop": 0.05}


def test_generate_plan_default_layer_counts_zero() -> None:
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=_market_state(),
        watchlist=[],
        logic_scores={},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={},
    )
    assert plan.layer_a_count == 0
    assert plan.layer_b_count == 0
    assert plan.layer_c_count == 0
    assert plan.watchlist == []


def test_generate_plan_target_mode_default() -> None:
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=_market_state(),
        watchlist=[],
        logic_scores={},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={},
    )
    assert plan.target_mode == "research_only"


def test_generate_plan_empty_string_profile_name_becomes_default() -> None:
    plan = generate_execution_plan(
        trade_date="20260613",
        market_state=_market_state(),
        watchlist=[],
        logic_scores={},
        buy_orders=[],
        sell_orders=[],
        portfolio_snapshot={},
        short_trade_target_profile_name="",
    )
    assert plan.short_trade_target_profile_name == "default"
