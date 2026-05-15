from __future__ import annotations

from src.targets import build_short_trade_target_profile
from src.targets.short_trade_target_factor_helpers import compute_trend_continuation_strength_adjustment


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

    assert profile.trend_continuation_weight > 0.0
    assert profile.short_term_reversal_weight == 0.0
    assert profile.reversal_2d_weight == 0.0
    assert profile.selected_close_retention_penalty_weight > 0.0
    assert profile.trend_continuation_strength_weight > 0.0
