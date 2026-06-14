"""Tests for market_state_helpers.py — market gating, regime detection, profile recommendation.

This module has ZERO test coverage despite being critical: it determines
market regime gates, position scaling, and BTST trading profiles.
"""

from __future__ import annotations

from src.screening.market_state_helpers import (
    _compute_regime_flip_risk,
    _compute_style_dispersion,
    _compute_total_volume,
    _resolve_regime_gate,
    build_market_state_from_metrics,
    classify_btst_regime_gate,
    classify_btst_regime_gate_from_market_state,
    MarketStateMetrics,
    recommend_short_trade_profile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics(
    *,
    breadth_ratio: float = 0.50,
    daily_return: float = 0.0,
    adx: float = 25.0,
    atr_ratio: float = 0.02,
    style_dispersion: float = 0.20,
    regime_flip_risk: float = 0.30,
    northbound_flow_days: int = 0,
    total_volume: float = 10000.0,
    limit_up_count: int = 30,
    limit_down_count: int = 5,
    is_low_volume: bool | None = None,
) -> MarketStateMetrics:
    is_low_volume = is_low_volume if is_low_volume is not None else total_volume < 5000.0
    return MarketStateMetrics(
        adx=adx,
        atr_ratio=atr_ratio,
        daily_return=daily_return,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        limit_ratio=limit_up_count / limit_down_count if limit_down_count > 0 else float(limit_up_count > 0),
        breadth_ratio=breadth_ratio,
        total_volume=total_volume,
        northbound_flow_days=northbound_flow_days,
        is_low_volume=is_low_volume,
        breadth_is_weak=breadth_ratio <= 0.42,
        breadth_is_strong=breadth_ratio >= 0.58,
        style_dispersion=style_dispersion,
        regime_flip_risk=regime_flip_risk,
    )


# ---------------------------------------------------------------------------
# recommend_short_trade_profile
# ---------------------------------------------------------------------------


class TestRecommendShortTradeProfile:
    def test_bounce_regime_returns_v2(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=-0.02, limit_ratio=5.0, adx=25.0,
        ) == "btst_precision_v2"

    def test_slight_drop_returns_v2(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=-0.005, limit_ratio=3.0, adx=25.0,
        ) == "btst_precision_v2"

    def test_euphoria_returns_conservative(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=0.02, limit_ratio=3.0, adx=25.0,
        ) == "conservative"

    def test_neutral_returns_v2(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=0.005, limit_ratio=3.0, adx=25.0,
        ) == "btst_precision_v2"

    def test_regime_gate_crisis_overrides(self) -> None:
        """Even with bounce signal, crisis gate forces conservative."""
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=-0.02, limit_ratio=5.0, adx=25.0,
            regime_gate_level="crisis",
        ) == "conservative"

    def test_regime_gate_risk_off_overrides(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=-0.02, limit_ratio=5.0, adx=25.0,
            regime_gate_level="risk_off",
        ) == "conservative"

    def test_high_regime_flip_risk_returns_conservative(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=0.0, limit_ratio=3.0, adx=25.0,
            regime_flip_risk=0.60,
        ) == "conservative"

    def test_high_style_dispersion_returns_conservative(self) -> None:
        assert recommend_short_trade_profile(
            breadth_ratio=0.50, daily_return=0.0, limit_ratio=3.0, adx=25.0,
            style_dispersion=0.60,
        ) == "conservative"

    def test_weak_breadth_returns_conservative(self) -> None:
        """Breadth ≤ 0.35 forces conservative even in neutral regime."""
        assert recommend_short_trade_profile(
            breadth_ratio=0.30, daily_return=0.0, limit_ratio=3.0, adx=25.0,
        ) == "conservative"


# ---------------------------------------------------------------------------
# _resolve_regime_gate
# ---------------------------------------------------------------------------


class TestResolveRegimeGate:
    def test_crisis_on_extreme_breadth(self) -> None:
        metrics = _metrics(breadth_ratio=0.30, daily_return=-0.03)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=1.0)
        assert gate == "crisis"
        assert "breadth_weak" in reasons

    def test_crisis_on_extreme_position_scale(self) -> None:
        metrics = _metrics(breadth_ratio=0.50)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=0.50)
        assert gate == "crisis"

    def test_crisis_on_regime_and_dispersion(self) -> None:
        metrics = _metrics(regime_flip_risk=0.85, style_dispersion=0.60)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=1.0)
        assert gate == "crisis"

    def test_risk_off_on_weak_breadth(self) -> None:
        metrics = _metrics(breadth_ratio=0.40)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=1.0)
        assert gate in {"risk_off", "crisis"}

    def test_normal_on_healthy_market(self) -> None:
        metrics = _metrics(breadth_ratio=0.55, style_dispersion=0.20, regime_flip_risk=0.30)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=1.0)
        assert gate == "normal"
        assert len(reasons) == 0

    def test_low_volume_flagged(self) -> None:
        metrics = _metrics(total_volume=3000.0, is_low_volume=True)
        gate, reasons = _resolve_regime_gate(metrics=metrics, position_scale=1.0)
        assert "low_volume" in reasons


# ---------------------------------------------------------------------------
# classify_btst_regime_gate
# ---------------------------------------------------------------------------


class TestClassifyBtstRegimeGate:
    def test_halt_on_crisis_gate(self) -> None:
        result = classify_btst_regime_gate(
            breadth_ratio=0.30, daily_return=-0.03,
            style_dispersion=0.60, regime_flip_risk=0.80,
            regime_gate_level="crisis",
        )
        assert result["gate"] == "halt"
        assert result["profile_hint"] == "conservative"

    def test_shadow_only_on_conservative_profile(self) -> None:
        result = classify_btst_regime_gate(
            breadth_ratio=0.50, daily_return=0.02,
            style_dispersion=0.20, regime_flip_risk=0.30,
        )
        assert result["gate"] == "shadow_only"
        assert result["profile_hint"] == "conservative"

    def test_aggressive_trade_on_ideal_conditions(self) -> None:
        result = classify_btst_regime_gate(
            breadth_ratio=0.65, daily_return=-0.005,
            style_dispersion=0.15, regime_flip_risk=0.10,
        )
        assert result["gate"] == "aggressive_trade"
        assert result["profile_hint"] == "btst_precision_v2"

    def test_normal_trade_typical(self) -> None:
        result = classify_btst_regime_gate(
            breadth_ratio=0.50, daily_return=-0.002,
            style_dispersion=0.25, regime_flip_risk=0.25,
        )
        assert result["gate"] == "normal_trade"

    def test_result_has_metrics(self) -> None:
        result = classify_btst_regime_gate(
            breadth_ratio=0.50, daily_return=0.0,
            style_dispersion=0.20, regime_flip_risk=0.30,
        )
        assert "metrics" in result
        assert "breadth_ratio" in result["metrics"]
        assert "daily_return" in result["metrics"]


class TestClassifyBtstRegimeGateFromMarketState:
    def test_none_returns_none(self) -> None:
        assert classify_btst_regime_gate_from_market_state(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert classify_btst_regime_gate_from_market_state({}) is None

    def test_dict_with_data_returns_gate(self) -> None:
        state = {
            "breadth_ratio": 0.55,
            "daily_return": -0.002,
            "style_dispersion": 0.20,
            "regime_flip_risk": 0.30,
        }
        result = classify_btst_regime_gate_from_market_state(state)
        assert result is not None
        assert "gate" in result


# ---------------------------------------------------------------------------
# _compute_style_dispersion
# ---------------------------------------------------------------------------


class TestComputeStyleDispersion:
    def test_healthy_market_low_dispersion(self) -> None:
        disp = _compute_style_dispersion(breadth_ratio=0.60, daily_return=0.002, limit_ratio=2.0)
        assert 0.0 <= disp <= 1.0
        assert disp < 0.5  # Healthy market should have low dispersion

    def test_extreme_values_bounded(self) -> None:
        disp = _compute_style_dispersion(breadth_ratio=0.20, daily_return=-0.05, limit_ratio=0.1)
        assert 0.0 <= disp <= 1.0


# ---------------------------------------------------------------------------
# _compute_regime_flip_risk
# ---------------------------------------------------------------------------


class TestComputeRegimeFlipRisk:
    def test_stable_market_low_risk(self) -> None:
        risk = _compute_regime_flip_risk(
            breadth_ratio=0.60, daily_return=0.001,
            northbound_flow_days=3, style_dispersion=0.15,
        )
        assert 0.0 <= risk <= 1.0
        assert risk < 0.5

    def test_negative_northbound_flow_increases_risk(self) -> None:
        risk_good = _compute_regime_flip_risk(
            breadth_ratio=0.50, daily_return=0.0,
            northbound_flow_days=3, style_dispersion=0.20,
        )
        risk_bad = _compute_regime_flip_risk(
            breadth_ratio=0.50, daily_return=0.0,
            northbound_flow_days=-5, style_dispersion=0.20,
        )
        assert risk_bad > risk_good

    def test_extreme_severe_northbound_flow(self) -> None:
        risk = _compute_regime_flip_risk(
            breadth_ratio=0.40, daily_return=-0.01,
            northbound_flow_days=-5, style_dispersion=0.50,
        )
        assert risk > 0.3  # Extreme conditions should elevate risk


# ---------------------------------------------------------------------------
# _compute_total_volume
# ---------------------------------------------------------------------------


class TestComputeTotalVolume:
    def test_none_returns_zero(self) -> None:
        assert _compute_total_volume(None) == 0.0

    def test_empty_df_returns_zero(self) -> None:
        import pandas as pd
        assert _compute_total_volume(pd.DataFrame()) == 0.0

    def test_valid_df_returns_volume(self) -> None:
        import pandas as pd
        df = pd.DataFrame({
            "circ_mv": [100000.0, 200000.0],
            "turnover_rate": [5.0, 3.0],
        })
        vol = _compute_total_volume(df)
        assert vol > 0


# ---------------------------------------------------------------------------
# build_market_state_from_metrics
# ---------------------------------------------------------------------------


class TestBuildMarketStateFromMetrics:
    def test_builds_market_state(self) -> None:
        metrics = _metrics()
        state = build_market_state_from_metrics(
            metrics=metrics,
            normalize_weights=lambda w: w,
        )
        assert state.adx == 25.0
        assert state.breadth_ratio == 0.50
        assert 0.0 <= state.position_scale <= 1.0
        assert state.regime_gate_level in {"normal", "risk_off", "crisis"}

    def test_low_volume_reduces_position_scale(self) -> None:
        metrics = _metrics(total_volume=3000.0, is_low_volume=True)
        state = build_market_state_from_metrics(
            metrics=metrics,
            normalize_weights=lambda w: w,
        )
        assert state.position_scale <= 0.5  # Low volume should reduce scale
