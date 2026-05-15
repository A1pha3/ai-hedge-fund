from __future__ import annotations

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

    assert adjustment == 0.1397


def test_trend_continuation_strength_penalizes_weak_close_retention() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.84,
        close_strength=0.28,
        volume_expansion_quality=0.63,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.08,
    )

    assert adjustment == 0.0973
