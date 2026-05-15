from __future__ import annotations

from src.utils.numeric import clamp_unit_interval


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
    continuation_component = clamp_unit_interval(trend_continuation) * float(continuation_weight)
    close_support_component = max(0.0, float(close_strength) - float(close_support_floor)) * float(continuation_weight)
    volume_support_component = max(0.0, float(volume_expansion_quality) - float(volume_support_floor)) * float(continuation_weight)
    weak_close_shortfall = max(0.0, float(close_support_floor) - float(close_strength))
    weak_close_component = 0.0 if weak_close_shortfall <= 0.0 else float(weak_close_penalty) + weak_close_shortfall
    return continuation_component + close_support_component + volume_support_component - weak_close_component
