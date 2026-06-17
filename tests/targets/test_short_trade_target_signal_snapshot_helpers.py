"""TDD guards for `_apply_explicit_metric_overrides`.

BH-035 (R68/BH-034 falsy-zero ``or`` family): the override applier previously used
``.get(key, default) or default``. For unit-interval scores where ``0.0`` is a
legitimate value (e.g. "no breakout freshness", "stale catalyst"), a falsy ``0.0``
override was silently discarded and replaced by the computed default — inflating
the candidate score. These guards lock the explicit presence-check fix.
"""

from __future__ import annotations

from src.targets.short_trade_target_signal_snapshot_helpers import (
    _apply_explicit_metric_overrides,
)


def _clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


_BASE_SCORES = {
    "breakout_freshness": 0.75,
    "trend_acceleration": 0.60,
    "volume_expansion_quality": 0.50,
    "close_strength": 0.65,
    "sector_resonance": 0.55,
    "raw_catalyst_freshness": 0.70,
}


def test_explicit_zero_breakout_freshness_override_is_respected() -> None:
    """A forced 0.0 breakout_freshness must not fall back to the computed default."""
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides={"breakout_freshness": 0.0},
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    assert result["breakout_freshness"] == 0.0


def test_explicit_zero_catalyst_freshness_override_is_respected() -> None:
    """A forced 0.0 catalyst_freshness (-> raw_catalyst_freshness) must hold."""
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides={"catalyst_freshness": 0.0},
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    assert result["raw_catalyst_freshness"] == 0.0


def test_explicit_zero_overrides_for_all_six_metric_fields_respected() -> None:
    """Every overridable unit-interval field must honour an explicit 0.0."""
    overrides = {
        "breakout_freshness": 0.0,
        "trend_acceleration": 0.0,
        "volume_expansion_quality": 0.0,
        "close_strength": 0.0,
        "sector_resonance": 0.0,
        "catalyst_freshness": 0.0,
    }
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides=overrides,
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    assert result["breakout_freshness"] == 0.0
    assert result["trend_acceleration"] == 0.0
    assert result["volume_expansion_quality"] == 0.0
    assert result["close_strength"] == 0.0
    assert result["sector_resonance"] == 0.0
    assert result["raw_catalyst_freshness"] == 0.0


def test_nonzero_override_still_applies() -> None:
    """A non-zero override continues to take effect (behavior preservation)."""
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides={"breakout_freshness": 0.42},
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    assert result["breakout_freshness"] == 0.42


def test_missing_override_keeps_computed_default() -> None:
    """When no override is supplied for a field, the computed default is kept."""
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides={"close_strength": 0.88},
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    # close_strength overridden, breakout_freshness untouched (keeps default)
    assert result["close_strength"] == 0.88
    assert result["breakout_freshness"] == 0.75


def test_empty_overrides_returns_scores_unchanged() -> None:
    """Empty override dict is a no-op (behavior preservation)."""
    result = _apply_explicit_metric_overrides(
        scores=dict(_BASE_SCORES),
        explicit_metric_overrides={},
        clamp_unit_interval_fn=_clamp_unit_interval,
    )
    assert result == _BASE_SCORES
