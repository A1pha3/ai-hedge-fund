"""TDD red test: falsy-zero `or` bug in _parse_upstream_shadow_catalyst_relief_config.

Reproduces the R68/R69/R96 falsy-zero `or` family residue on the short-trade
upstream-shadow catalyst relief config parsing path. The module itself already
documents the trap (line 308 NOTE on next_open_to_close_return_mean), but the
near_miss_threshold / selected_threshold / carryover count parsers still use
`get(key, base) or base`, which silently overrides an explicit 0.0 override
with the base value.

0.0 is a legitimate "no threshold / accept-all-relief" value for an upstream
shadow catalyst relief override. A user (or shadow strategy) explicitly setting
near_miss_threshold=0.0 to maximize relief gets silently overridden back to
the base threshold — corrupting the relief decision (R69 same-class).
"""
from __future__ import annotations

from src.targets.short_trade_target_relief_helpers import (
    _parse_upstream_shadow_catalyst_relief_config,
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
