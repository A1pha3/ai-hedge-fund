from __future__ import annotations

import src.execution.daily_pipeline as daily_pipeline_module

from src.execution.daily_pipeline_post_market_helpers import build_plan_target_shell_inputs
from src.execution.daily_pipeline_post_market_helpers import build_selection_target_inputs
from src.execution.daily_pipeline import _resolve_effective_short_trade_target_profile_name
from src.execution.daily_pipeline import _attach_btst_regime_gate_shadow
from src.execution.daily_pipeline import _serialize_short_trade_target_profile
from src.execution.models import ExecutionPlan
from src.execution.models import LayerCResult
from src.screening.market_state_helpers import classify_btst_regime_gate
from src.screening.models import MarketState
from src.targets.profiles import build_short_trade_target_profile


def test_classify_btst_regime_gate_marks_risk_off_as_halt() -> None:
    gate = classify_btst_regime_gate(
        breadth_ratio=0.39,
        daily_return=-0.004,
        style_dispersion=0.49,
        regime_flip_risk=0.63,
        regime_gate_level="risk_off",
    )

    assert gate["gate"] == "halt"
    assert gate["profile_hint"] == "conservative"
    assert "regime_gate_level_risk_off" in gate["reason_codes"]


def test_classify_btst_regime_gate_marks_conservative_non_halt_as_shadow_only() -> None:
    gate = classify_btst_regime_gate(
        breadth_ratio=0.44,
        daily_return=0.012,
        style_dispersion=0.57,
        regime_flip_risk=0.41,
        regime_gate_level="normal",
    )

    assert gate["gate"] == "shadow_only"
    assert gate["profile_hint"] == "conservative"
    assert "profile_conservative" in gate["reason_codes"]


def test_classify_btst_regime_gate_marks_strong_conditions_as_aggressive_trade() -> None:
    gate = classify_btst_regime_gate(
        breadth_ratio=0.67,
        daily_return=-0.003,
        style_dispersion=0.18,
        regime_flip_risk=0.09,
        regime_gate_level="normal",
    )

    assert gate["gate"] == "aggressive_trade"
    assert gate["profile_hint"] == "btst_precision_v2"
    assert "breadth_strong" in gate["reason_codes"]


def test_classify_btst_regime_gate_defaults_to_normal_trade() -> None:
    gate = classify_btst_regime_gate(
        breadth_ratio=0.52,
        daily_return=0.001,
        style_dispersion=0.24,
        regime_flip_risk=0.22,
        regime_gate_level="normal",
    )

    assert gate["gate"] == "normal_trade"
    assert gate["profile_hint"] == "btst_precision_v2"


def test_resolve_effective_short_trade_target_profile_name_adapts_default_profile_for_risk_off() -> None:
    market_state = MarketState(
        breadth_ratio=0.377877,
        daily_return=-0.003543,
        limit_up_down_ratio=2.95,
        adx=35.5263,
        style_dispersion=0.21643,
        regime_flip_risk=0.234638,
        regime_gate_level="risk_off",
    )

    effective_profile_name = _resolve_effective_short_trade_target_profile_name(
        requested_profile_name="default",
        requested_profile_overrides={},
        market_state=market_state,
    )

    assert effective_profile_name == "shadow_research"


def test_resolve_effective_short_trade_target_profile_name_adapts_default_profile_for_normal_trade() -> None:
    market_state = MarketState(
        breadth_ratio=0.52,
        daily_return=0.001,
        limit_up_down_ratio=1.15,
        adx=24.0,
        style_dispersion=0.24,
        regime_flip_risk=0.22,
        regime_gate_level="normal",
    )

    effective_profile_name = _resolve_effective_short_trade_target_profile_name(
        requested_profile_name="default",
        requested_profile_overrides={},
        market_state=market_state,
    )

    assert effective_profile_name == "retention_follow"


def test_resolve_effective_short_trade_target_profile_name_adapts_default_profile_for_aggressive_trade() -> None:
    market_state = MarketState(
        breadth_ratio=0.67,
        daily_return=-0.003,
        limit_up_down_ratio=1.25,
        adx=27.0,
        style_dispersion=0.18,
        regime_flip_risk=0.09,
        regime_gate_level="normal",
    )

    effective_profile_name = _resolve_effective_short_trade_target_profile_name(
        requested_profile_name="default",
        requested_profile_overrides={},
        market_state=market_state,
    )

    assert effective_profile_name == "ignition_breakout"


def test_build_selection_target_inputs_overrides_entry_market_state_with_plan_market_state() -> None:
    stale_entry = {
        "ticker": "000807",
        "candidate_source": "watchlist_filter_diagnostics",
        "market_state": {
            "breadth_ratio": 0.44,
            "daily_return": 0.012,
            "style_dispersion": 0.57,
            "regime_flip_risk": 0.41,
            "regime_gate_level": "normal",
            "btst_regime_gate": {
                "gate": "shadow_only",
                "profile_hint": "conservative",
            },
        },
    }
    plan_market_state = MarketState(
        breadth_ratio=0.67,
        daily_return=-0.003,
        limit_up_down_ratio=1.25,
        adx=27.0,
        style_dispersion=0.18,
        regime_flip_risk=0.09,
        regime_gate_level="normal",
    )

    inputs = build_selection_target_inputs(
        trade_date="20260506",
        watchlist_filter_diagnostics={"tickers": [stale_entry]},
        short_trade_candidate_diagnostics={},
        catalyst_theme_candidate_diagnostics={},
        target_mode="short_trade_only",
        market_state=plan_market_state,
    )

    attached_market_state = inputs.rejected_entries[0]["market_state"]

    assert attached_market_state["breadth_ratio"] == 0.67
    assert attached_market_state["style_dispersion"] == 0.18
    assert "btst_regime_gate" not in attached_market_state


def test_ensure_plan_target_shells_clears_selection_targets_for_frozen_replay_even_when_profile_matches(monkeypatch) -> None:
    requested_profile = build_short_trade_target_profile("default")
    plan = ExecutionPlan.model_construct(
        date="20260506",
        selection_targets={"000807": {"short_trade": {"decision": "selected"}}},
        risk_metrics={"frozen_selection_target_replay_input": {"watchlist": []}},
        short_trade_target_profile_name="default",
        short_trade_target_profile_config=_serialize_short_trade_target_profile(requested_profile),
    )
    monkeypatch.setattr(daily_pipeline_module, "ensure_plan_target_shells_impl", lambda **kwargs: kwargs["plan"])

    updated = daily_pipeline_module._ensure_plan_target_shells(
        plan,
        target_mode="short_trade_only",
        short_trade_target_profile_name="default",
        short_trade_target_profile_overrides={},
    )

    assert updated.selection_targets == {}


def test_ensure_plan_target_shells_normalizes_watchlist_market_state_from_plan(monkeypatch) -> None:
    requested_profile = build_short_trade_target_profile("default")
    stale_watchlist_item = LayerCResult(
        ticker="000807",
        score_b=0.4316,
        score_c=0.2261,
        score_final=0.2775,
        quality_score=0.8083,
        decision="watch",
        strategy_signals={},
        agent_contribution_summary={},
        market_state={
            "breadth_ratio": 0.44,
            "daily_return": 0.012,
            "style_dispersion": 0.57,
            "regime_flip_risk": 0.41,
            "regime_gate_level": "normal",
            "btst_regime_gate": {"gate": "shadow_only", "profile_hint": "conservative"},
        },
    )
    plan = ExecutionPlan.model_construct(
        date="20260506",
        market_state=MarketState(
            breadth_ratio=0.67,
            daily_return=-0.003,
            limit_up_down_ratio=1.25,
            adx=27.0,
            style_dispersion=0.18,
            regime_flip_risk=0.09,
            regime_gate_level="normal",
        ),
        watchlist=[stale_watchlist_item],
        selection_targets={},
        risk_metrics={},
        short_trade_target_profile_name="default",
        short_trade_target_profile_config=_serialize_short_trade_target_profile(requested_profile),
    )
    monkeypatch.setattr(daily_pipeline_module, "ensure_plan_target_shells_impl", lambda **kwargs: kwargs["plan"])

    updated = daily_pipeline_module._ensure_plan_target_shells(
        plan,
        target_mode="short_trade_only",
        short_trade_target_profile_name="default",
        short_trade_target_profile_overrides={},
    )

    attached_market_state = updated.watchlist[0].market_state

    assert attached_market_state["breadth_ratio"] == 0.67
    assert attached_market_state["style_dispersion"] == 0.18
    assert "btst_regime_gate" not in attached_market_state


def test_build_plan_target_shell_inputs_attaches_plan_market_state_to_entries() -> None:
    plan_market_state = MarketState(
        breadth_ratio=0.67,
        daily_return=-0.003,
        limit_up_down_ratio=1.25,
        adx=27.0,
        style_dispersion=0.18,
        regime_flip_risk=0.09,
        regime_gate_level="normal",
    )
    plan = ExecutionPlan.model_construct(
        date="20260506",
        market_state=plan_market_state,
        watchlist=[],
        buy_orders=[],
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {
                        "tickers": [{"ticker": "300502"}],
                    },
                    "short_trade_candidates": {
                        "tickers": [{"ticker": "000338", "candidate_source": "short_trade_boundary"}],
                        "released_shadow_entries": [],
                    },
                    "catalyst_theme_candidates": {"tickers": []},
                }
            }
        },
    )

    def _attach_prior(entries, *, prior_by_ticker):
        return [
            {
                **dict(entry),
                "historical_prior": {"btst_regime_gate": "aggressive_trade"},
            }
            for entry in entries
        ]

    shell_inputs = build_plan_target_shell_inputs(
        plan=plan,
        target_mode="short_trade_only",
        historical_prior_by_ticker={},
        attach_historical_prior_to_entries_fn=_attach_prior,
        attach_historical_prior_to_watchlist_fn=lambda watchlist, *, prior_by_ticker: watchlist,
    )

    for entry in shell_inputs.rejected_entries + shell_inputs.supplemental_short_trade_entries:
        assert entry["market_state"]["breadth_ratio"] == 0.67
        assert entry["market_state"]["style_dispersion"] == 0.18
        assert entry["historical_prior"]["btst_regime_gate"] == "aggressive_trade"


def test_attach_btst_regime_gate_shadow_is_noop_when_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("BTST_0422_P1_REGIME_GATE_MODE", raising=False)
    plan = ExecutionPlan(
        date="20260406",
        market_state=MarketState(
            breadth_ratio=0.39,
            daily_return=-0.002,
            style_dispersion=0.51,
            regime_flip_risk=0.61,
            regime_gate_level="risk_off",
        ),
        buy_orders=[],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
    )

    updated = _attach_btst_regime_gate_shadow(plan)

    assert updated.risk_metrics == {}


def test_attach_btst_regime_gate_shadow_records_payload_without_changing_orders(monkeypatch) -> None:
    monkeypatch.setenv("BTST_0422_P1_REGIME_GATE_MODE", "shadow")
    plan = ExecutionPlan(
        date="20260406",
        market_state=MarketState(
            breadth_ratio=0.39,
            daily_return=-0.002,
            style_dispersion=0.51,
            regime_flip_risk=0.61,
            regime_gate_level="risk_off",
        ),
        buy_orders=[],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"buy_order_count": 0}},
    )

    updated = _attach_btst_regime_gate_shadow(plan)

    assert updated.buy_orders == []
    assert updated.risk_metrics["btst_regime_gate"]["mode"] == "shadow"
    assert updated.risk_metrics["btst_regime_gate"]["gate"] == "halt"
