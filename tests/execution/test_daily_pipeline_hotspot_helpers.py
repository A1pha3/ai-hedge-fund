"""Unit tests for src/execution/daily_pipeline_hotspot_helpers.py

Covers the pure functions in the historical-support and catalyst-relief
pipeline: label deltas, historical rate support adjustments, sparse-weak
history detection, suppress-release decision, support verdict, full
summarize_shadow_release_historical_support, catalyst-relief threshold
resolver, selected-threshold resolver, and relief payload builder.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.execution.daily_pipeline_hotspot_helpers import (
    _apply_historical_rate_support,
    _execution_quality_support_delta,
    _is_sparse_weak_history,
    _should_suppress_shadow_release,
    _support_verdict,
    build_upstream_shadow_catalyst_relief_payload,
    resolve_catalyst_relief_thresholds,
    resolve_selected_threshold,
    summarize_shadow_release_historical_support,
)

# ---------------------------------------------------------------------------
# _execution_quality_support_delta
# ---------------------------------------------------------------------------


def test_execution_quality_delta_known_labels() -> None:
    assert _execution_quality_support_delta("close_continuation") == 0.10
    assert _execution_quality_support_delta("gap_chase_risk") == 0.08
    assert _execution_quality_support_delta("balanced_confirmation") == 0.05
    assert _execution_quality_support_delta("intraday_only") == -0.08
    assert _execution_quality_support_delta("zero_follow_through") == -0.12


def test_execution_quality_delta_unknown_label_zero() -> None:
    assert _execution_quality_support_delta("unknown") == 0.0
    assert _execution_quality_support_delta("") == 0.0


# ---------------------------------------------------------------------------
# _apply_historical_rate_support
# ---------------------------------------------------------------------------


def test_apply_rate_support_low_evaluable_skipped() -> None:
    """evaluable_count < 3 → no adjustment."""
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=2, next_close_positive_rate=0.7, next_high_hit_rate=0.7
    )
    assert score == 0.0


def test_apply_rate_support_high_close_positive_boosts() -> None:
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=0.6, next_high_hit_rate=None
    )
    assert score == pytest.approx(0.04)


def test_apply_rate_support_low_close_positive_dampens() -> None:
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=0.0, next_high_hit_rate=None
    )
    assert score == pytest.approx(-0.04)


def test_apply_rate_support_close_neutral_no_change() -> None:
    """0.0 < next_close < 0.5 (e.g. 0.3) → no change."""
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=0.3, next_high_hit_rate=None
    )
    assert score == 0.0


def test_apply_rate_support_high_hit_boosts() -> None:
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=None, next_high_hit_rate=0.6
    )
    assert score == pytest.approx(0.04)


def test_apply_rate_support_low_hit_dampens() -> None:
    """next_high_hit_rate < 0.25 → -0.02."""
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=None, next_high_hit_rate=0.1
    )
    assert score == pytest.approx(-0.02)


def test_apply_rate_support_hit_neutral_no_change() -> None:
    """0.25 <= next_high_hit_rate < 0.5 (e.g. 0.3) → no change."""
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=None, next_high_hit_rate=0.3
    )
    assert score == 0.0


def test_apply_rate_support_combined_close_and_hit() -> None:
    score = _apply_historical_rate_support(
        support_score=0.0, evaluable_count=3, next_close_positive_rate=0.6, next_high_hit_rate=0.6
    )
    assert score == pytest.approx(0.08)


# ---------------------------------------------------------------------------
# _is_sparse_weak_history
# ---------------------------------------------------------------------------


def test_sparse_weak_history_true() -> None:
    assert (
        _is_sparse_weak_history(evaluable_count=2, next_close_positive_rate=0.0, next_high_hit_rate=0.0)
        is True
    )


def test_sparse_weak_history_false_evaluable_zero() -> None:
    """evaluable_count=0 → fails `0 < evaluable_count` check → False."""
    assert (
        _is_sparse_weak_history(evaluable_count=0, next_close_positive_rate=0.0, next_high_hit_rate=0.0)
        is False
    )


def test_sparse_weak_history_false_evaluable_three() -> None:
    """evaluable_count >= 3 → not sparse."""
    assert (
        _is_sparse_weak_history(evaluable_count=3, next_close_positive_rate=0.0, next_high_hit_rate=0.0)
        is False
    )


def test_sparse_weak_history_false_positive_close() -> None:
    """next_close > 0 → not weak."""
    assert (
        _is_sparse_weak_history(evaluable_count=2, next_close_positive_rate=0.1, next_high_hit_rate=0.0)
        is False
    )


def test_sparse_weak_history_false_positive_hit() -> None:
    """next_high > 0 → not weak."""
    assert (
        _is_sparse_weak_history(evaluable_count=2, next_close_positive_rate=0.0, next_high_hit_rate=0.1)
        is False
    )


def test_sparse_weak_history_false_missing_rates() -> None:
    assert (
        _is_sparse_weak_history(evaluable_count=2, next_close_positive_rate=None, next_high_hit_rate=None)
        is False
    )


# ---------------------------------------------------------------------------
# _should_suppress_shadow_release
# ---------------------------------------------------------------------------


def test_suppress_pruned_with_zero_follow_through() -> None:
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="balanced_confirmation",
            evaluable_count=3,
            next_close_positive_rate=0.6,
            pruned_from_opportunity_pool=True,
            prune_reason="historical_zero_follow_through",
        )
        is True
    )


def test_suppress_pruned_but_different_reason() -> None:
    """prune_reason matters: only zero_follow_through triggers this branch."""
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="balanced_confirmation",
            evaluable_count=3,
            next_close_positive_rate=0.6,
            pruned_from_opportunity_pool=True,
            prune_reason="other",
        )
        is False
    )


def test_suppress_zero_follow_through_at_evaluable_3() -> None:
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="zero_follow_through",
            evaluable_count=3,
            next_close_positive_rate=None,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is True
    )


def test_suppress_intraday_only_with_low_close() -> None:
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="intraday_only",
            evaluable_count=3,
            next_close_positive_rate=0.0,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is True
    )


def test_suppress_intraday_only_with_positive_close_not_suppressed() -> None:
    """intraday_only + positive close → NOT suppressed."""
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="intraday_only",
            evaluable_count=3,
            next_close_positive_rate=0.5,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is False
    )


def test_suppress_same_ticker_intraday_low_close() -> None:
    """applied_scope == 'same_ticker' + intraday_only + low close → suppress."""
    assert (
        _should_suppress_shadow_release(
            applied_scope="same_ticker",
            execution_quality_label="intraday_only",
            evaluable_count=3,
            next_close_positive_rate=0.0,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is True
    )


def test_suppress_evaluable_below_3_not_suppressed() -> None:
    """evaluable_count < 3 → even zero_follow_through NOT suppressed here (sparse handled separately)."""
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="zero_follow_through",
            evaluable_count=2,
            next_close_positive_rate=None,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is False
    )


def test_suppress_balanced_confirmation_not_suppressed() -> None:
    assert (
        _should_suppress_shadow_release(
            applied_scope="candidate_source",
            execution_quality_label="balanced_confirmation",
            evaluable_count=3,
            next_close_positive_rate=0.6,
            pruned_from_opportunity_pool=False,
            prune_reason="",
        )
        is False
    )


# ---------------------------------------------------------------------------
# _support_verdict
# ---------------------------------------------------------------------------


def test_support_verdict_suppress() -> None:
    assert _support_verdict(suppress_release=True, support_score=0.5) == "suppress_release"


def test_support_verdict_supportive() -> None:
    assert _support_verdict(suppress_release=False, support_score=0.05) == "supportive"


def test_support_verdict_caution() -> None:
    assert _support_verdict(suppress_release=False, support_score=-0.05) == "caution"


def test_support_verdict_neutral_zero() -> None:
    assert _support_verdict(suppress_release=False, support_score=0.0) == "neutral"


# ---------------------------------------------------------------------------
# summarize_shadow_release_historical_support (full integration of the helpers)
# ---------------------------------------------------------------------------


def test_summarize_supportive_balanced() -> None:
    result = summarize_shadow_release_historical_support(
        execution_quality_label="balanced_confirmation",
        applied_scope="candidate_source",
        evaluable_count=5,
        next_close_positive_rate=0.6,
        next_high_hit_rate=0.6,
    )
    # 0.05 (label) + 0.04 (close) + 0.04 (hit) = 0.13
    assert result["support_score"] == 0.13
    assert result["verdict"] == "supportive"
    assert result["suppress_release"] is False
    assert result["sparse_weak_history"] is False


def test_summarize_suppress_zero_follow_through() -> None:
    result = summarize_shadow_release_historical_support(
        execution_quality_label="zero_follow_through",
        applied_scope="candidate_source",
        evaluable_count=5,
        next_close_positive_rate=None,
        next_high_hit_rate=None,
    )
    assert result["verdict"] == "suppress_release"
    assert result["suppress_release"] is True


def test_summarize_sparse_weak_caps_score() -> None:
    """sparse_weak → score floored at -0.01 (even if helper gives > -0.01)."""
    result = summarize_shadow_release_historical_support(
        execution_quality_label="balanced_confirmation",  # +0.05
        applied_scope="candidate_source",
        evaluable_count=2,  # sparse
        next_close_positive_rate=0.0,  # weak
        next_high_hit_rate=0.0,  # weak
    )
    assert result["sparse_weak_history"] is True
    assert result["support_score"] == -0.01  # capped at -0.01
    assert result["verdict"] == "caution"  # negative → caution


def test_summarize_neutral_zero_label_neutral_rates() -> None:
    result = summarize_shadow_release_historical_support(
        execution_quality_label="unknown",
        applied_scope="candidate_source",
        evaluable_count=3,
        next_close_positive_rate=None,
        next_high_hit_rate=None,
    )
    assert result["support_score"] == 0.0
    assert result["verdict"] == "neutral"


# ---------------------------------------------------------------------------
# resolve_catalyst_relief_thresholds
# ---------------------------------------------------------------------------


def _relief_kwargs(**overrides: Any) -> dict:
    base: dict[str, Any] = dict(
        candidate_pool_lane="layer_a_liquidity_corridor",
        profitability_hard_cliff=False,
        historical_next_close_positive_rate=None,
        candidate_score_min=0.5,
        trend_acceleration_min=0.2,
        close_strength_min=0.3,
        near_miss_threshold=0.45,
        post_gate_history_next_close_min=0.5,
        post_gate_hard_cliff_candidate_score_min=0.4,
        post_gate_hard_cliff_trend_min=0.15,
        post_gate_hard_cliff_close_min=0.25,
        post_gate_hard_cliff_near_miss_threshold=0.4,
    )
    base.update(overrides)
    return base


def test_relief_thresholds_non_post_gate_returns_base() -> None:
    result = resolve_catalyst_relief_thresholds(**_relief_kwargs())
    assert result == {"candidate_score_min": 0.5, "trend_acceleration_min": 0.2, "close_strength_min": 0.3, "near_miss_threshold": 0.45}


def test_relief_thresholds_post_gate_no_history_returns_base() -> None:
    result = resolve_catalyst_relief_thresholds(
        **_relief_kwargs(candidate_pool_lane="post_gate_liquidity_competition", historical_next_close_positive_rate=None)
    )
    assert result["candidate_score_min"] == 0.5


def test_relief_thresholds_post_gate_history_below_min_returns_none() -> None:
    assert resolve_catalyst_relief_thresholds(
        **_relief_kwargs(
            candidate_pool_lane="post_gate_liquidity_competition",
            historical_next_close_positive_rate=0.3,
        )
    ) is None


def test_relief_thresholds_post_gate_hard_cliff_relaxes_thresholds() -> None:
    """hard_cliff path takes min() of each base and post_gate_hard_cliff_*."""
    result = resolve_catalyst_relief_thresholds(
        **_relief_kwargs(
            candidate_pool_lane="post_gate_liquidity_competition",
            profitability_hard_cliff=True,
            historical_next_close_positive_rate=0.6,
        )
    )
    assert result["candidate_score_min"] == 0.4  # min(0.5, 0.4)
    assert result["trend_acceleration_min"] == 0.15  # min(0.2, 0.15)
    assert result["close_strength_min"] == 0.25
    assert result["near_miss_threshold"] == 0.4


def test_relief_thresholds_post_gate_hard_cliff_history_below_min_returns_none() -> None:
    """hard_cliff + history below min → None."""
    assert resolve_catalyst_relief_thresholds(
        **_relief_kwargs(
            candidate_pool_lane="post_gate_liquidity_competition",
            profitability_hard_cliff=True,
            historical_next_close_positive_rate=0.3,  # < 0.5
        )
    ) is None


# ---------------------------------------------------------------------------
# resolve_selected_threshold
# ---------------------------------------------------------------------------


def test_resolve_selected_threshold_post_gate_enabled() -> None:
    enabled, threshold = resolve_selected_threshold(
        candidate_pool_lane="post_gate_liquidity_competition",
        profitability_hard_cliff=False,
        shadow_visibility_gap_selected=False,
        post_gate_selected_threshold=0.5,
        post_gate_hard_cliff_selected_threshold=0.4,
    )
    assert enabled is True
    assert threshold == 0.5


def test_resolve_selected_threshold_post_gate_hard_cliff() -> None:
    enabled, threshold = resolve_selected_threshold(
        candidate_pool_lane="post_gate_liquidity_competition",
        profitability_hard_cliff=True,
        shadow_visibility_gap_selected=False,
        post_gate_selected_threshold=0.5,
        post_gate_hard_cliff_selected_threshold=0.4,
    )
    assert enabled is True
    assert threshold == 0.4  # min(0.5, 0.4)


def test_resolve_selected_threshold_corridor_with_visibility_gap() -> None:
    enabled, threshold = resolve_selected_threshold(
        candidate_pool_lane="layer_a_liquidity_corridor",
        profitability_hard_cliff=False,
        shadow_visibility_gap_selected=True,
        post_gate_selected_threshold=0.5,
        post_gate_hard_cliff_selected_threshold=0.4,
    )
    assert enabled is True
    assert threshold == 0.5  # not post_gate → no min() adjustment


def test_resolve_selected_threshold_corridor_no_visibility_gap_disabled() -> None:
    enabled, threshold = resolve_selected_threshold(
        candidate_pool_lane="layer_a_liquidity_corridor",
        profitability_hard_cliff=False,
        shadow_visibility_gap_selected=False,
        post_gate_selected_threshold=0.5,
        post_gate_hard_cliff_selected_threshold=0.4,
    )
    assert enabled is False


# ---------------------------------------------------------------------------
# build_upstream_shadow_catalyst_relief_payload
# ---------------------------------------------------------------------------


def test_relief_payload_basic() -> None:
    payload = build_upstream_shadow_catalyst_relief_payload(
        near_miss_threshold=0.45,
        selected_threshold_override_enabled=False,
        selected_threshold=0.5,
        breakout_freshness_min=0.8,
        trend_acceleration_min=0.2,
        close_strength_min=0.3,
        require_no_profitability_hard_cliff=True,
        required_execution_quality_labels={"close_continuation", "balanced_confirmation"},
        min_historical_evaluable_count=2,
        min_historical_next_close_positive_rate=0.5,
        min_historical_next_open_to_close_return_mean=0.0,
        catalyst_freshness_floor=1.0,
    )
    assert payload["enabled"] is True
    assert payload["reason"] == "upstream_shadow_catalyst_relief"
    assert "selected_threshold" not in payload  # override disabled
    assert payload["require_no_profitability_hard_cliff"] is True
    assert payload["required_execution_quality_labels"] == ["balanced_confirmation", "close_continuation"]  # sorted
    assert payload["min_historical_evaluable_count"] == 2


def test_relief_payload_with_selected_threshold_override() -> None:
    payload = build_upstream_shadow_catalyst_relief_payload(
        near_miss_threshold=0.45,
        selected_threshold_override_enabled=True,
        selected_threshold=0.4,
        breakout_freshness_min=0.8,
        trend_acceleration_min=0.2,
        close_strength_min=0.3,
        require_no_profitability_hard_cliff=False,
        required_execution_quality_labels=set(),
        min_historical_evaluable_count=3,
        min_historical_next_close_positive_rate=0.5,
        min_historical_next_open_to_close_return_mean=0.1,
        catalyst_freshness_floor=1.5,
    )
    assert payload["selected_threshold"] == 0.4
    assert payload["required_execution_quality_labels"] == []  # empty sorted
