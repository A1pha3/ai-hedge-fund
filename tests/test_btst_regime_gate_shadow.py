from __future__ import annotations

from src.execution.daily_pipeline import _resolve_effective_short_trade_target_profile_name
from src.execution.daily_pipeline import _attach_btst_regime_gate_shadow
from src.execution.models import ExecutionPlan
from src.screening.market_state_helpers import classify_btst_regime_gate
from src.screening.models import MarketState


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

    assert effective_profile_name == "conservative"


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
