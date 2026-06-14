from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.execution.btst_shadow_promotion_helpers import (
    resolve_btst_shadow_promotion_payload,
)
from src.execution.daily_pipeline import _attach_btst_risk_budget_p6
from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    _enforce_btst_daily_trade_limit,
    _resolve_btst_daily_limit_priority,
    _resolve_btst_position_budget,
    build_buy_orders_with_diagnostics,
)
from src.execution.models import ExecutionPlan, LayerCResult
from src.portfolio.models import PositionPlan
from src.screening.models import CandidateStock
from src.targets.models import DualTargetEvaluation, TargetEvaluationResult


def _selection_target(
    *,
    gate: str,
    prior_quality_label: str,
    execution_eligible: bool = True,
    candidate_source: str = "layer_c_watchlist",
    projected_theme_exposure: float = 0.0,
    incremental_theme_exposure: float = 0.0,
    theme_exposure_cap: float = 0.25,
    incremental_theme_exposure_cap: float = 0.18,
    preferred_entry_mode: str | None = None,
    positive_tags: list[str] | None = None,
    historical_prior: dict[str, object] | None = None,
) -> DualTargetEvaluation:
    return DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        execution_eligible=execution_eligible,
        candidate_source=candidate_source,
        p3_prior_quality_label=prior_quality_label,
        historical_prior_quality_level=prior_quality_label,
        btst_regime_gate=gate,
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected" if execution_eligible else "near_miss",
            execution_eligible=execution_eligible,
            score_target=0.81,
            preferred_entry_mode=preferred_entry_mode,
            positive_tags=list(positive_tags or []),
            metrics_payload={
                "historical_prior": dict(historical_prior or {}),
                "thresholds": {
                    "market_state_threshold_adjustment": {
                        "enabled": True,
                        "regime_gate_level": gate,
                        "risk_level": gate,
                    }
                },
                "committee": {
                    "thresholds": {
                        "theme_exposure_cap": theme_exposure_cap,
                        "incremental_theme_exposure_cap": incremental_theme_exposure_cap,
                    },
                    "components": {
                        "projected_theme_exposure": projected_theme_exposure,
                        "incremental_theme_exposure": incremental_theme_exposure,
                    },
                },
            },
        ),
    )


def _selection_target_for_ticker(ticker: str, *, gate: str, prior_quality_label: str, execution_eligible: bool = True, candidate_source: str = "layer_c_watchlist") -> DualTargetEvaluation:
    target = _selection_target(
        gate=gate,
        prior_quality_label=prior_quality_label,
        execution_eligible=execution_eligible,
        candidate_source=candidate_source,
    )
    target.ticker = ticker
    return target


def _watchlist_item(*, score_final: float = 0.55, quality_score: float = 0.5) -> LayerCResult:
    return LayerCResult(ticker="300724", score_b=0.72, score_c=0.64, score_final=score_final, quality_score=quality_score, decision="watch")


def _watchlist_item_for_ticker(ticker: str, *, score_final: float = 0.55, quality_score: float = 0.5) -> LayerCResult:
    return LayerCResult(ticker=ticker, score_b=0.72, score_c=0.64, score_final=score_final, quality_score=quality_score, decision="watch")


def test_p6_risk_budget_matrix_zeroes_non_tradeable_cases(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    item = _watchlist_item()
    candidate = CandidateStock(ticker="300724", name="Test", industry_sw="电子")

    cases = [
        ("halt", "execution_ready"),
        ("shadow_only", "execution_ready"),
        ("normal_trade", "watch_only"),
    ]

    for gate, prior_quality_label in cases:
        budget = _resolve_btst_position_budget(
            item=item,
            selection_target=_selection_target(gate=gate, prior_quality_label=prior_quality_label, execution_eligible=prior_quality_label == "execution_ready" and gate == "normal_trade"),
            candidate=candidate,
            nav=100000.0,
        )
        assert budget["formal_risk_budget_ratio"] == 0.0
        assert budget["formal_exposure_bucket"] == "zero_budget"


def test_p6_risk_budget_matrix_respects_btst_gate_when_market_state_uses_risk_off(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    target = _selection_target(gate="halt", prior_quality_label="execution_ready", execution_eligible=True)
    target.short_trade.metrics_payload["thresholds"]["market_state_threshold_adjustment"]["regime_gate_level"] = "risk_off"
    target.short_trade.metrics_payload["thresholds"]["market_state_threshold_adjustment"]["risk_level"] = "risk_off"

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.88, quality_score=0.82),
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子"),
        nav=100000.0,
    )

    assert budget["risk_budget_gate"] == "halt"
    assert budget["formal_risk_budget_ratio"] == 0.0
    assert budget["formal_exposure_bucket"] == "zero_budget"


def test_p6_risk_budget_matrix_caps_lower_quality_execution_eligible_case(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.32, quality_score=0.52),
        selection_target=_selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子"),
        nav=100000.0,
    )

    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.6)
    assert budget["formal_exposure_bucket"] == "reduced"
    assert budget["execution_contract_bucket"] == "formal_capped"


def test_p6_risk_budget_caps_otherwise_full_budget_when_committee_liquidity_capacity_is_weak(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    target = _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)
    target.short_trade.metrics_payload["committee"] = {
        "components": {
            "liquidity_capacity_raw_100": 45.0,
        }
    }

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.88, quality_score=0.82),
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子"),
        nav=100000.0,
    )

    assert budget["execution_contract_bucket"] == "formal_capped"
    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.6)
    assert budget["formal_exposure_bucket"] == "reduced"


def test_p6_risk_budget_caps_otherwise_full_budget_when_committee_fragile_breakout_risk_is_elevated(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    target = _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)
    target.short_trade.metrics_payload["committee"] = {
        "components": {
            "liquidity_capacity_raw_100": 85.0,
            "fragile_breakout_risk_raw_100": 72.0,
            "gap_risk_raw_100": 35.0,
        }
    }

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.88, quality_score=0.82),
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0),
        nav=100000.0,
    )

    assert budget["execution_contract_bucket"] == "formal_capped"
    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.6)
    assert budget["formal_exposure_bucket"] == "reduced"


def test_p6_risk_budget_caps_otherwise_full_budget_when_candidate_liquidity_fallback_is_thin(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.88, quality_score=0.82),
        selection_target=_selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=9_000.0),
        nav=100000.0,
    )

    assert budget["execution_contract_bucket"] == "formal_capped"
    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.6)
    assert budget["formal_exposure_bucket"] == "reduced"


def test_build_buy_orders_with_diagnostics_applies_p6_overlay_to_position_sizing(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].shares == 600
    assert buy_orders[0].amount == pytest.approx(6000.0)
    assert buy_orders[0].risk_budget_ratio == pytest.approx(0.6)
    assert diagnostics["btst_risk_budget_overlay"]["formal_exposure_distribution"] == {"reduced": 1}


def test_btst_risk_budget_overlay_summary_emits_promotion_gate_inputs(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert len(buy_orders) == 1
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["mode"] == "enforce"
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["gate_distribution"] == {"normal_trade": 1}
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["suppressed_position_summary"] == {"zero_budget_count": 0, "reduced_budget_count": 1}


def test_btst_risk_budget_overlay_summary_emits_theme_exposure_maxima_for_promotion_gate(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {
        "300724": _selection_target(
            gate="normal_trade",
            prior_quality_label="execution_ready",
            execution_eligible=True,
            projected_theme_exposure=0.37,
            incremental_theme_exposure=0.19,
        )
    }

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert buy_orders == []
    assert diagnostics["tickers"][0]["reason"] == "blocked_by_incremental_theme_exposure_cap"
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["max_projected_theme_exposure"] == pytest.approx(0.37)
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["max_incremental_theme_exposure"] == pytest.approx(0.19)


def test_build_buy_orders_with_diagnostics_zeroes_watch_only_formal_exposure(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.7)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="watch_only", execution_eligible=False)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert buy_orders == []
    assert diagnostics["btst_risk_budget_overlay"]["suppressed_position_summary"]["zero_budget_count"] == 1
    assert diagnostics["tickers"][0]["reason"] == "position_blocked_risk_budget_overlay"


def test_p6_risk_budget_allows_reduced_shadow_promotion_budget(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.77, quality_score=0.72),
        selection_target=_selection_target(
            gate="shadow_only",
            prior_quality_label="watch_only",
            execution_eligible=True,
            preferred_entry_mode="confirm_then_hold_breakout",
            positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
            historical_prior={
                "execution_quality_label": "close_continuation",
                "evaluable_count": 6,
                "next_close_positive_rate": 0.59,
                "next_high_hit_rate_at_threshold": 0.66,
            },
        ),
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0),
        nav=100000.0,
    )

    assert budget["risk_budget_gate"] == "shadow_promotion"
    assert budget["execution_contract_bucket"] == "shadow_promoted"
    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.25)
    assert budget["formal_exposure_bucket"] == "reduced"


def test_shadow_promotion_daily_limit_priority_penalizes_robust_weak_five_day_history(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    item = _watchlist_item(score_final=0.77, quality_score=0.72)
    baseline_target = _selection_target(
        gate="shadow_only",
        prior_quality_label="watch_only",
        execution_eligible=True,
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
        historical_prior={
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.59,
            "next_high_hit_rate_at_threshold": 0.66,
        },
    )
    weak_five_day_target = _selection_target(
        gate="shadow_only",
        prior_quality_label="watch_only",
        execution_eligible=True,
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
        historical_prior={
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.59,
            "next_high_hit_rate_at_threshold": 0.66,
            "five_day_evaluable_count": 9,
            "five_day_hit_rate_at_15pct": 0.22,
            "five_day_mean_max_future_high_return_2_5d": 0.082,
        },
    )
    candidate = CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0)

    baseline_budget = _resolve_btst_position_budget(
        item=item,
        selection_target=baseline_target,
        candidate=candidate,
        nav=100000.0,
    )
    weak_five_day_budget = _resolve_btst_position_budget(
        item=item,
        selection_target=weak_five_day_target,
        candidate=candidate,
        nav=100000.0,
    )

    baseline_priority = _resolve_btst_daily_limit_priority(
        item=item,
        selection_target=baseline_target,
        budget=baseline_budget,
    )
    weak_five_day_priority = _resolve_btst_daily_limit_priority(
        item=item,
        selection_target=weak_five_day_target,
        budget=weak_five_day_budget,
    )
    weak_five_day_payload = resolve_btst_shadow_promotion_payload(evaluation=weak_five_day_target)

    assert baseline_budget["risk_budget_gate"] == "shadow_promotion"
    assert weak_five_day_budget["risk_budget_gate"] == "shadow_promotion"
    assert weak_five_day_payload["five_day_quality_label"] == "weak"
    assert weak_five_day_payload["five_day_quality_reason"] == "five_day_boundary_quality_insufficient"
    assert weak_five_day_payload["five_day_priority_penalty"] == pytest.approx(0.18)
    assert weak_five_day_priority < baseline_priority


def test_shadow_promotion_daily_limit_priority_falls_back_to_score_without_five_day_history(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    item = _watchlist_item(score_final=0.77, quality_score=0.72)
    target = _selection_target(
        gate="shadow_only",
        prior_quality_label="watch_only",
        execution_eligible=True,
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
        historical_prior={
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.59,
            "next_high_hit_rate_at_threshold": 0.66,
        },
    )
    budget = _resolve_btst_position_budget(
        item=item,
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0),
        nav=100000.0,
    )
    payload = resolve_btst_shadow_promotion_payload(evaluation=target)

    assert payload["five_day_quality_label"] == "insufficient"
    assert payload["five_day_quality_reason"] == ""
    assert _resolve_btst_daily_limit_priority(item=item, selection_target=target, budget=budget) == pytest.approx(item.score_final)


def test_p6_risk_budget_allows_reduced_halt_relief_budget(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.81, quality_score=0.76),
        selection_target=_selection_target(
            gate="halt",
            prior_quality_label="watch_only",
            execution_eligible=True,
            preferred_entry_mode="confirm_then_hold_breakout",
            positive_tags=["historical_execution_relief"],
        ),
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0),
        nav=100000.0,
    )
    target = _selection_target(
        gate="halt",
        prior_quality_label="watch_only",
        execution_eligible=True,
        preferred_entry_mode="confirm_then_hold_breakout",
        positive_tags=["historical_execution_relief", "fresh_catalyst_support"],
    )
    target.short_trade.explainability_payload = {
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.82,
            "next_high_hit_rate_at_threshold": 0.95,
        }
    }
    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.81, quality_score=0.76),
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0),
        nav=100000.0,
    )

    assert budget["risk_budget_gate"] == "halt_relief"
    assert budget["execution_contract_bucket"] == "halt_promoted"
    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.10)
    assert budget["formal_exposure_bucket"] == "reduced"


def test_btst_daily_trade_limit_caps_shadow_promotion_to_one_position(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    plans = [
        PositionPlan(ticker="300721", shares=100, amount=5000.0, score_final=0.88, risk_budget_gate="shadow_promotion"),
        PositionPlan(ticker="300722", shares=100, amount=5000.0, score_final=0.87, risk_budget_gate="shadow_promotion"),
    ]

    selected = _enforce_btst_daily_trade_limit(plans, 100000.0)

    assert [plan.ticker for plan in selected] == ["300721"]


def test_btst_daily_trade_limit_allows_two_halt_relief_positions(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    plans = [
        PositionPlan(ticker="300721", shares=100, amount=5000.0, score_final=0.88, risk_budget_gate="halt_relief"),
        PositionPlan(ticker="300722", shares=100, amount=5000.0, score_final=0.87, risk_budget_gate="halt_relief"),
        PositionPlan(ticker="300723", shares=100, amount=5000.0, score_final=0.86, risk_budget_gate="halt_relief"),
    ]

    selected = _enforce_btst_daily_trade_limit(plans, 100000.0)

    assert [plan.ticker for plan in selected] == ["300721", "300722"]


def test_btst_daily_trade_limit_ranks_halt_relief_by_historical_prior_before_score(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [
        _watchlist_item_for_ticker("300721", score_final=0.60, quality_score=0.90),
        _watchlist_item_for_ticker("300722", score_final=0.55, quality_score=0.80),
        _watchlist_item_for_ticker("300723", score_final=0.54, quality_score=0.79),
    ]
    selection_targets = {
        "300721": _selection_target_for_ticker(
            "300721",
            gate="halt",
            prior_quality_label="watch_only",
            execution_eligible=True,
        ),
        "300722": _selection_target_for_ticker(
            "300722",
            gate="halt",
            prior_quality_label="watch_only",
            execution_eligible=True,
        ),
        "300723": _selection_target_for_ticker(
            "300723",
            gate="halt",
            prior_quality_label="watch_only",
            execution_eligible=True,
        ),
    }
    for ticker, next_high_hit_rate, next_close_positive_rate, evaluable_count in [
        ("300721", 0.76, 0.65, 40),
        ("300722", 0.95, 0.90, 45),
        ("300723", 0.92, 0.88, 42),
    ]:
        selection_targets[ticker].short_trade.preferred_entry_mode = "confirm_then_hold_breakout"
        selection_targets[ticker].short_trade.positive_tags = ["historical_execution_relief", "fresh_catalyst_support"]
        selection_targets[ticker].short_trade.explainability_payload = {
            "historical_prior": {
                "execution_quality_label": "close_continuation",
                "evaluable_count": evaluable_count,
                "next_close_positive_rate": next_close_positive_rate,
                "next_high_hit_rate_at_threshold": next_high_hit_rate,
            }
        }

    candidate_by_ticker = {ticker: CandidateStock(ticker=ticker, name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0) for ticker in selection_targets}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker=candidate_by_ticker,
        price_map={ticker: 10.0 for ticker in selection_targets},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {entry["reason"]: sum(1 for row in entries if row["reason"] == entry["reason"]) for entry in entries}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=_enforce_btst_daily_trade_limit,
    )

    assert [order.ticker for order in buy_orders] == ["300722", "300723"]
    assert diagnostics["reason_counts"] == {"filtered_by_daily_trade_limit": 1}
    assert diagnostics["tickers"][0]["ticker"] == "300721"


def test_p6_off_preserves_existing_position_sizing(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "off")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].shares == 1000
    assert buy_orders[0].amount == pytest.approx(10000.0)
    assert diagnostics["btst_risk_budget_overlay"]["mode"] == "off"


def test_btst_daily_trade_limit_caps_normal_trade_to_two_positions(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [
        _watchlist_item_for_ticker("300721", score_final=0.57, quality_score=0.5),
        _watchlist_item_for_ticker("300722", score_final=0.56, quality_score=0.5),
        _watchlist_item_for_ticker("300723", score_final=0.55, quality_score=0.5),
    ]
    selection_targets = {
        "300721": _selection_target_for_ticker("300721", gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
        "300722": _selection_target_for_ticker("300722", gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
        "300723": _selection_target_for_ticker("300723", gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
    }
    candidate_by_ticker = {ticker: CandidateStock(ticker=ticker, name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0) for ticker in selection_targets}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker=candidate_by_ticker,
        price_map={ticker: 10.0 for ticker in selection_targets},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {entry["reason"]: sum(1 for row in entries if row["reason"] == entry["reason"]) for entry in entries}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=_enforce_btst_daily_trade_limit,
    )

    assert [order.ticker for order in buy_orders] == ["300721", "300722"]
    assert diagnostics["reason_counts"] == {"filtered_by_daily_trade_limit": 1}


def test_btst_daily_trade_limit_allows_three_aggressive_trade_positions(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [
        _watchlist_item_for_ticker("300731", score_final=0.58, quality_score=0.5),
        _watchlist_item_for_ticker("300732", score_final=0.57, quality_score=0.5),
        _watchlist_item_for_ticker("300733", score_final=0.56, quality_score=0.5),
        _watchlist_item_for_ticker("300734", score_final=0.55, quality_score=0.5),
    ]
    selection_targets = {ticker: _selection_target_for_ticker(ticker, gate="aggressive_trade", prior_quality_label="execution_ready", execution_eligible=True) for ticker in ["300731", "300732", "300733", "300734"]}
    candidate_by_ticker = {ticker: CandidateStock(ticker=ticker, name="Test", industry_sw="电子", avg_volume_20d=1_000_000.0) for ticker in selection_targets}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker=candidate_by_ticker,
        price_map={ticker: 10.0 for ticker in selection_targets},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {entry["reason"]: sum(1 for row in entries if row["reason"] == entry["reason"]) for entry in entries}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=_enforce_btst_daily_trade_limit,
    )

    assert [order.ticker for order in buy_orders] == ["300731", "300732", "300733"]
    assert diagnostics["reason_counts"] == {"filtered_by_daily_trade_limit": 1}


def test_btst_daily_trade_limit_uses_most_restrictive_gate_when_mixed(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    plans = [
        PositionPlan(ticker="300731", shares=700, amount=7000.0, score_final=0.58, execution_ratio=0.75, quality_score=0.5, risk_budget_gate="aggressive_trade"),
        PositionPlan(ticker="300732", shares=700, amount=7000.0, score_final=0.57, execution_ratio=0.75, quality_score=0.5, risk_budget_gate="shadow_only"),
    ]

    selected = _enforce_btst_daily_trade_limit(plans, portfolio_nav=100000.0)

    assert selected == []


def test_attach_btst_risk_budget_p6_off_does_not_annotate_plan(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "off")
    target = _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)
    plan = ExecutionPlan(
        date="2026-04-22",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        watchlist=[_watchlist_item(score_final=0.55, quality_score=0.5)],
        selection_targets={"300724": target},
        buy_orders=[PositionPlan(ticker="300724", shares=1000, amount=10000.0, score_final=0.55, execution_ratio=1.0, quality_score=0.5)],
        risk_metrics={},
    )

    updated = _attach_btst_risk_budget_p6(plan)

    assert "p6_risk_budget" not in updated.selection_targets["300724"].short_trade.metrics_payload
    assert "p6_risk_budget" not in updated.selection_targets["300724"].short_trade.explainability_payload
    assert "btst_risk_budget_p6_enforcement" not in updated.risk_metrics


def test_analyze_btst_risk_budget_overlay_eval_returns_required_shape(tmp_path: Path) -> None:
    from scripts.analyze_btst_risk_budget_overlay_eval import (
        _render_markdown,
        analyze_btst_risk_budget_overlay_eval,
    )

    report_dir = tmp_path / "paper_trading_window_sample"
    (report_dir / "selection_artifacts" / "2026-04-22").mkdir(parents=True)
    (report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "300724": {
                        "ticker": "300724",
                        "candidate_source": "layer_c_watchlist",
                        "execution_eligible": True,
                        "historical_prior_quality_level": "execution_ready",
                        "btst_regime_gate": "normal_trade",
                        "short_trade": {
                            "decision": "selected",
                            "metrics_payload": {
                                "p6_risk_budget": {
                                    "mode": "enforce",
                                    "risk_budget_ratio": 0.6,
                                    "formal_exposure_bucket": "reduced",
                                    "execution_contract_bucket": "formal_capped",
                                }
                            },
                        },
                    },
                    "688313": {
                        "ticker": "688313",
                        "candidate_source": "layer_c_watchlist",
                        "execution_eligible": False,
                        "historical_prior_quality_level": "watch_only",
                        "btst_regime_gate": "shadow_only",
                        "short_trade": {
                            "decision": "near_miss",
                            "metrics_payload": {
                                "p6_risk_budget": {
                                    "mode": "enforce",
                                    "risk_budget_ratio": 0.0,
                                    "formal_exposure_bucket": "zero_budget",
                                    "execution_contract_bucket": "watch_only",
                                }
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "btst_risk_budget_p6_summary": {
                    "gate_distribution": {"normal_trade": 1, "shadow_only": 1},
                    "formal_exposure_distribution": {"reduced": 1, "zero_budget": 1},
                    "suppressed_position_summary": {"zero_budget_count": 1, "reduced_budget_count": 1},
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_risk_budget_overlay_eval(report_dir)

    assert analysis["report_type"] == "p6_btst_risk_budget_overlay_eval"
    assert analysis["snapshot_count"] == 1
    assert "risk_budget_matrix" in analysis
    assert analysis["gate_distribution"] == {"normal_trade": 1, "shadow_only": 1}
    assert analysis["formal_exposure_distribution"] == {"reduced": 1, "zero_budget": 1}
    assert analysis["suppressed_position_summary"] == {"zero_budget_count": 1, "reduced_budget_count": 1}
    assert analysis["strong_day_retention_summary"] == {
        "strong_day_candidate_count": 1,
        "retained_formal_exposure_count": 1,
        "retained_formal_exposure_rate": 1.0,
    }
    markdown = _render_markdown(analysis)
    assert "风险预算矩阵说明" in markdown
    assert "强势日正式暴露保留" in markdown
    assert "normal_trade × execution_ready × formal_capped" in markdown
