from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, Callable, Iterator

import pytest

from src.screening.models import StrategySignal
from src.targets import build_short_trade_target_profile
from src.targets.short_trade_target_factor_helpers import compute_trend_continuation_strength_adjustment


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _make_trend_continuation_strength_entry() -> dict:
    return {
        "ticker": "601869",
        "score_b": 0.20,
        "score_c": -0.40,
        "score_final": 0.05,
        "quality_score": 0.60,
        "decision": "watch",
        "reason": "short_trade_candidate_score_ranked",
        "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 73.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 64.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 56.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                60.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(-1, 20.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 85.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 4,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.0917,
            "execution_note": "历史上确认后继续收盘延续，属于强 continuation 子桶。",
        },
    }


@pytest.fixture()
def evaluate_short_trade_rejected_target_with_execution_model_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., Any]]:
    execution_models_module = ModuleType("src.execution.models")
    execution_models_module.LayerCResult = type("LayerCResult", (), {})
    execution_module = ModuleType("src.execution")
    execution_module.models = execution_models_module

    monkeypatch.setitem(sys.modules, "src.execution", execution_module)
    monkeypatch.setitem(sys.modules, "src.execution.models", execution_models_module)

    original_short_trade_target = sys.modules.pop("src.targets.short_trade_target", None)
    try:
        from src.targets.short_trade_target import evaluate_short_trade_rejected_target

        yield evaluate_short_trade_rejected_target
    finally:
        sys.modules.pop("src.targets.short_trade_target", None)
        if original_short_trade_target is not None:
            sys.modules["src.targets.short_trade_target"] = original_short_trade_target


def test_trend_continuation_strength_rewards_supported_continuation() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.82,
        close_strength=0.74,
        volume_expansion_quality=0.68,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.08,
    )

    assert adjustment > 0.0


def test_trend_continuation_strength_penalizes_weak_close_retention() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.84,
        close_strength=0.28,
        volume_expansion_quality=0.63,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.5,
    )

    assert adjustment < 0.0


def test_trend_continuation_strength_v2_profile_sets_new_factor_knobs() -> None:
    profile = build_short_trade_target_profile("trend_continuation_strength_v2")

    expected_overrides = {
        "trend_continuation_weight": 0.18,
        "trend_continuation_2d_weight": 0.10,
        "close_strength_weight": 0.12,
        "volume_expansion_quality_weight": 0.18,
        "selected_close_retention_penalty_weight": 0.06,
        "trend_continuation_strength_weight": 0.12,
        "trend_continuation_strength_close_support_floor": 0.55,
        "trend_continuation_strength_volume_support_floor": 0.45,
        "trend_continuation_strength_weak_close_penalty": 0.08,
        "short_term_reversal_weight": 0.0,
        "reversal_2d_weight": 0.0,
    }

    actual_overrides = {name: getattr(profile, name) for name in expected_overrides}

    assert actual_overrides == expected_overrides


def test_trend_continuation_strength_v2_surfaces_adjustment_in_score_payload_and_metrics(
    evaluate_short_trade_rejected_target_with_execution_model_shim: Callable[..., Any],
) -> None:
    entry = _make_trend_continuation_strength_entry()
    profile = build_short_trade_target_profile("trend_continuation_strength_v2")

    baseline_result = evaluate_short_trade_rejected_target_with_execution_model_shim(
        trade_date="20260328",
        entry=entry,
        profile_name="trend_continuation_strength_v2",
        profile_overrides={"trend_continuation_strength_weight": 0.0},
    )
    profiled_result = evaluate_short_trade_rejected_target_with_execution_model_shim(
        trade_date="20260328",
        entry=entry,
        profile_name="trend_continuation_strength_v2",
    )

    expected_adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=profiled_result.trend_acceleration or 0.0,
        close_strength=profiled_result.close_strength or 0.0,
        volume_expansion_quality=profiled_result.volume_expansion_quality or 0.0,
        continuation_weight=profile.trend_continuation_strength_weight,
        close_support_floor=profile.trend_continuation_strength_close_support_floor,
        volume_support_floor=profile.trend_continuation_strength_volume_support_floor,
        weak_close_penalty=profile.trend_continuation_strength_weak_close_penalty,
    )

    assert expected_adjustment > 0.0
    assert profiled_result.weighted_positive_contributions["trend_continuation_strength"] == pytest.approx(expected_adjustment)
    assert "trend_continuation_strength_penalty" not in profiled_result.weighted_negative_contributions
    assert profiled_result.metrics_payload["trend_continuation_strength_adjustment"] == pytest.approx(expected_adjustment)
    assert profiled_result.metrics_payload["weighted_positive_contributions"]["trend_continuation_strength"] == pytest.approx(expected_adjustment)
    assert profiled_result.metrics_payload["total_positive_contribution"] == pytest.approx(sum(profiled_result.weighted_positive_contributions.values()))
    assert profiled_result.metrics_payload["total_negative_contribution"] == pytest.approx(sum(profiled_result.weighted_negative_contributions.values()))
    assert profiled_result.metrics_payload["thresholds"]["trend_continuation_strength_weight"] == pytest.approx(profile.trend_continuation_strength_weight)
    assert profiled_result.score_target - baseline_result.score_target == pytest.approx(expected_adjustment)


def test_trend_continuation_strength_v2_routes_negative_adjustment_into_penalty_bucket(
    evaluate_short_trade_rejected_target_with_execution_model_shim: Callable[..., Any],
) -> None:
    entry = _make_trend_continuation_strength_entry()
    profile_overrides = {
        "trend_continuation_strength_close_support_floor": 1.0,
        "trend_continuation_strength_weak_close_penalty": 0.5,
    }

    profiled_result = evaluate_short_trade_rejected_target_with_execution_model_shim(
        trade_date="20260328",
        entry=entry,
        profile_name="trend_continuation_strength_v2",
        profile_overrides=profile_overrides,
    )

    expected_adjustment = profiled_result.metrics_payload["trend_continuation_strength_adjustment"]

    assert expected_adjustment < 0.0
    assert profiled_result.weighted_positive_contributions["trend_continuation_strength"] == pytest.approx(0.0)
    assert profiled_result.weighted_negative_contributions["trend_continuation_strength_penalty"] == pytest.approx(abs(expected_adjustment))
    assert profiled_result.metrics_payload["weighted_positive_contributions"]["trend_continuation_strength"] == pytest.approx(0.0)
    assert profiled_result.metrics_payload["weighted_negative_contributions"]["trend_continuation_strength_penalty"] == pytest.approx(abs(expected_adjustment))
    assert profiled_result.metrics_payload["total_positive_contribution"] == pytest.approx(sum(profiled_result.weighted_positive_contributions.values()))
    assert profiled_result.metrics_payload["total_negative_contribution"] == pytest.approx(sum(profiled_result.weighted_negative_contributions.values()))
