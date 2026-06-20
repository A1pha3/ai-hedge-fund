"""TDD red test: falsy-zero `or` bug in relief config parsers.

Covers two sibling parsers in short_trade_target_relief_helpers that use the
falsy-zero ``or`` anti-pattern on a numeric override field where 0.0 is a
legitimate "accept-all-relief / no threshold" value.

1. ``_parse_upstream_shadow_catalyst_relief_config`` (R68/R69/R96/R107 family,
   dict-backed ``relief_config``): ``get(key, base) or base`` silently overrides
   an explicit 0.0 override with the base value.
2. ``_parse_visibility_gap_continuation_relief_config`` (same root cause, sibling
   parser the prior drain missed; dataclass-backed ``profile``): ``profile.X or
   base`` silently overrides an explicit 0.0 ``visibility_gap_continuation_near_miss_threshold``
   with ``base_near_miss_threshold``.

0.0 is a legitimate "no threshold / accept-all-relief" value for a relief
override. A user (or shadow strategy) explicitly setting the override to 0.0
to maximize relief gets silently overridden back to the base threshold —
corrupting the relief decision.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.targets.short_trade_target_relief_helpers import (
    _parse_upstream_shadow_catalyst_relief_config,
    _parse_visibility_gap_continuation_relief_config,
)


def test_explicit_zero_near_miss_threshold_is_not_overridden_by_base() -> None:
    """Explicit near_miss_threshold=0.0 must survive, not be replaced by base 0.42."""
    config = _parse_upstream_shadow_catalyst_relief_config(
        relief_config={"near_miss_threshold": 0.0},
        base_near_miss_threshold=0.42,
        base_select_threshold=0.55,
        strong_carryover_history_min_evaluable_count=3,
    )
    assert config["near_miss_threshold_override"] == 0.0, (
        f"explicit near_miss_threshold=0.0 must survive, got {config['near_miss_threshold_override']!r} "
        "(falsy-zero `or` silently overrode to base 0.42)"
    )


def test_explicit_zero_select_threshold_is_not_overridden_by_base() -> None:
    """Explicit selected_threshold=0.0 must survive, not be replaced by base 0.55."""
    config = _parse_upstream_shadow_catalyst_relief_config(
        relief_config={"selected_threshold": 0.0},
        base_near_miss_threshold=0.42,
        base_select_threshold=0.55,
        strong_carryover_history_min_evaluable_count=3,
    )
    assert config["select_threshold_override"] == 0.0, (
        f"explicit selected_threshold=0.0 must survive, got {config['select_threshold_override']!r} "
        "(falsy-zero `or` silently overrode to base 0.55)"
    )


def test_explicit_zero_min_evaluable_count_is_not_overridden_by_carryover_default() -> None:
    """Explicit min_historical_evaluable_count=0 must survive, not become carryover default 3."""
    config = _parse_upstream_shadow_catalyst_relief_config(
        relief_config={"min_historical_evaluable_count": 0},
        base_near_miss_threshold=0.42,
        base_select_threshold=0.55,
        strong_carryover_history_min_evaluable_count=3,
    )
    assert config["carryover_min_historical_evaluable_count"] == 0, (
        f"explicit min_historical_evaluable_count=0 must survive, got "
        f"{config['carryover_min_historical_evaluable_count']!r} "
        "(falsy-zero `or` silently overrode to carryover default 3)"
    )


def test_missing_keys_fall_back_to_base_defaults() -> None:
    """Missing keys still fall back to the documented base defaults (behavior preserved)."""
    config = _parse_upstream_shadow_catalyst_relief_config(
        relief_config={},
        base_near_miss_threshold=0.42,
        base_select_threshold=0.55,
        strong_carryover_history_min_evaluable_count=3,
    )
    assert config["near_miss_threshold_override"] == 0.42
    assert config["select_threshold_override"] == 0.55
    assert config["carryover_min_historical_evaluable_count"] == 3
    assert config["catalyst_freshness_floor"] == 0.0


def _vg_profile(**overrides) -> SimpleNamespace:
    """Build a profile stand-in with the visibility_gap_continuation_* fields.

    Defaults mirror the dataclass defaults (profiles.py:225-229) so only the
    overridden field differs. Uses SimpleNamespace because the parser only does
    ``profile.<field>`` attribute access.
    """
    base = dict(
        visibility_gap_continuation_require_relaxed_band=True,
        visibility_gap_continuation_breakout_freshness_min=1.0,
        visibility_gap_continuation_trend_acceleration_min=1.0,
        visibility_gap_continuation_close_strength_min=1.0,
        visibility_gap_continuation_catalyst_freshness_floor=0.0,
        visibility_gap_continuation_near_miss_threshold=0.46,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_vg_explicit_zero_near_miss_override_is_not_replaced_by_base() -> None:
    """Explicit visibility_gap_continuation_near_miss_threshold=0.0 must survive.

    0.0 means "override the base near-miss threshold down to 0 = accept-all-relief".
    The falsy ``profile.X or base`` anti-pattern silently substitutes the non-zero
    base (e.g. 0.46), ignoring the deliberate override (same root cause as the
    upstream-shadow parser fixed in the tests above; sibling the prior drain missed).
    """
    config = _parse_visibility_gap_continuation_relief_config(
        profile=_vg_profile(visibility_gap_continuation_near_miss_threshold=0.0),
        base_near_miss_threshold=0.46,
    )
    assert config["near_miss_threshold_override"] == 0.0, (
        f"explicit override 0.0 must survive, got {config['near_miss_threshold_override']!r} "
        "(falsy-zero `or` silently overrode to base 0.46)"
    )


def test_vg_nonzero_override_is_preserved() -> None:
    """A non-zero override is preserved (behavior unchanged for all current profiles)."""
    config = _parse_visibility_gap_continuation_relief_config(
        profile=_vg_profile(visibility_gap_continuation_near_miss_threshold=0.24),
        base_near_miss_threshold=0.46,
    )
    assert config["near_miss_threshold_override"] == 0.24
