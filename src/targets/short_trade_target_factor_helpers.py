from __future__ import annotations


def compute_trend_continuation_strength_adjustment(
    *,
    trend_continuation: float,
    close_strength: float,
    volume_expansion_quality: float,
    continuation_weight: float,
    close_support_floor: float,
    volume_support_floor: float,
    weak_close_penalty: float,
) -> float:
    base_uplift = max(0.0, trend_continuation) * max(0.0, continuation_weight)
    close_support = max(0.0, close_strength - close_support_floor)
    volume_support = max(0.0, volume_expansion_quality - volume_support_floor)
    weak_close_drag = max(0.0, close_support_floor - close_strength) * weak_close_penalty if base_uplift > 0.0 else 0.0
    return round(base_uplift * (1.0 + close_support + volume_support) - weak_close_drag, 4)
