from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping


@dataclass(frozen=True)
class ShortTradeTargetProfile:
    name: str
    select_threshold: float = 0.58
    near_miss_threshold: float = 0.46
    selected_breakout_freshness_min: float = 0.35
    selected_trend_acceleration_min: float = 0.38
    near_miss_breakout_freshness_min: float = 0.0
    near_miss_trend_acceleration_min: float = 0.0
    breakout_freshness_weight: float = 0.22
    trend_acceleration_weight: float = 0.18
    volume_expansion_quality_weight: float = 0.16
    close_strength_weight: float = 0.14
    sector_resonance_weight: float = 0.12
    catalyst_freshness_weight: float = 0.08
    layer_c_alignment_weight: float = 0.10
    stale_penalty_block_threshold: float = 0.72
    overhead_penalty_block_threshold: float = 0.68
    extension_penalty_block_threshold: float = 0.74
    layer_c_avoid_penalty: float = 0.12
    profitability_relief_enabled: bool = False
    profitability_relief_breakout_freshness_min: float = 0.42
    profitability_relief_catalyst_freshness_min: float = 0.45
    profitability_relief_sector_resonance_min: float = 0.45
    profitability_relief_avoid_penalty: float = 0.04
    stale_score_penalty_weight: float = 0.12
    overhead_score_penalty_weight: float = 0.10
    extension_score_penalty_weight: float = 0.08
    watchlist_zero_catalyst_penalty: float = 0.0
    watchlist_zero_catalyst_catalyst_freshness_max: float = 0.0
    watchlist_zero_catalyst_close_strength_min: float = 1.0
    watchlist_zero_catalyst_layer_c_alignment_min: float = 1.0
    watchlist_zero_catalyst_sector_resonance_min: float = 1.0
    hard_block_bearish_conflicts: frozenset[str] = frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"})
    overhead_conflict_penalty_conflicts: frozenset[str] = frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"})

    @property
    def strong_bearish_conflicts(self) -> frozenset[str]:
        return self.hard_block_bearish_conflicts


SHORT_TRADE_TARGET_PROFILES: dict[str, ShortTradeTargetProfile] = {
    "default": ShortTradeTargetProfile(name="default"),
    "conservative": ShortTradeTargetProfile(
        name="conservative",
        select_threshold=0.62,
        near_miss_threshold=0.50,
        selected_breakout_freshness_min=0.38,
        selected_trend_acceleration_min=0.41,
        near_miss_breakout_freshness_min=0.22,
        near_miss_trend_acceleration_min=0.26,
        stale_penalty_block_threshold=0.68,
        overhead_penalty_block_threshold=0.64,
        extension_penalty_block_threshold=0.70,
        layer_c_avoid_penalty=0.14,
        stale_score_penalty_weight=0.13,
        overhead_score_penalty_weight=0.11,
        extension_score_penalty_weight=0.09,
    ),
    "aggressive": ShortTradeTargetProfile(
        name="aggressive",
        select_threshold=0.54,
        near_miss_threshold=0.42,
        selected_breakout_freshness_min=0.30,
        selected_trend_acceleration_min=0.33,
        near_miss_breakout_freshness_min=0.16,
        near_miss_trend_acceleration_min=0.20,
        stale_penalty_block_threshold=0.78,
        overhead_penalty_block_threshold=0.74,
        extension_penalty_block_threshold=0.80,
        layer_c_avoid_penalty=0.08,
        stale_score_penalty_weight=0.08,
        overhead_score_penalty_weight=0.07,
        extension_score_penalty_weight=0.05,
    ),
    "staged_breakout": ShortTradeTargetProfile(
        name="staged_breakout",
        select_threshold=0.58,
        near_miss_threshold=0.42,
        selected_breakout_freshness_min=0.35,
        selected_trend_acceleration_min=0.38,
        near_miss_breakout_freshness_min=0.18,
        near_miss_trend_acceleration_min=0.22,
    ),
    "staged_breakout_profitability_relief": ShortTradeTargetProfile(
        name="staged_breakout_profitability_relief",
        select_threshold=0.58,
        near_miss_threshold=0.42,
        selected_breakout_freshness_min=0.35,
        selected_trend_acceleration_min=0.38,
        near_miss_breakout_freshness_min=0.18,
        near_miss_trend_acceleration_min=0.22,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.42,
        profitability_relief_catalyst_freshness_min=0.45,
        profitability_relief_sector_resonance_min=0.45,
        profitability_relief_avoid_penalty=0.04,
    ),
}

_ACTIVE_SHORT_TRADE_TARGET_PROFILE: ContextVar[ShortTradeTargetProfile] = ContextVar(
    "active_short_trade_target_profile",
    default=SHORT_TRADE_TARGET_PROFILES["default"],
)


def get_short_trade_target_profile(name: str = "default") -> ShortTradeTargetProfile:
    profile = SHORT_TRADE_TARGET_PROFILES.get(str(name or "default"))
    if profile is None:
        available = ", ".join(sorted(SHORT_TRADE_TARGET_PROFILES))
        raise ValueError(f"Unknown short trade target profile: {name}. Available: {available}")
    return profile


def get_active_short_trade_target_profile() -> ShortTradeTargetProfile:
    return _ACTIVE_SHORT_TRADE_TARGET_PROFILE.get()


def build_short_trade_target_profile(name: str = "default", overrides: Mapping[str, Any] | None = None) -> ShortTradeTargetProfile:
    profile = get_short_trade_target_profile(name)
    if not overrides:
        return profile
    normalized_overrides = dict(overrides)
    if "strong_bearish_conflicts" in normalized_overrides and normalized_overrides["strong_bearish_conflicts"] is not None:
        shared_conflicts = frozenset(str(value) for value in normalized_overrides.pop("strong_bearish_conflicts"))
        normalized_overrides.setdefault("hard_block_bearish_conflicts", shared_conflicts)
        normalized_overrides.setdefault("overhead_conflict_penalty_conflicts", shared_conflicts)
    if "hard_block_bearish_conflicts" in normalized_overrides and normalized_overrides["hard_block_bearish_conflicts"] is not None:
        normalized_overrides["hard_block_bearish_conflicts"] = frozenset(str(value) for value in normalized_overrides["hard_block_bearish_conflicts"])
    if "overhead_conflict_penalty_conflicts" in normalized_overrides and normalized_overrides["overhead_conflict_penalty_conflicts"] is not None:
        normalized_overrides["overhead_conflict_penalty_conflicts"] = frozenset(str(value) for value in normalized_overrides["overhead_conflict_penalty_conflicts"])
    return replace(profile, **normalized_overrides)


@contextmanager
def use_short_trade_target_profile(*, profile_name: str = "default", overrides: Mapping[str, Any] | None = None) -> Iterator[ShortTradeTargetProfile]:
    profile = build_short_trade_target_profile(profile_name, overrides)
    token = _ACTIVE_SHORT_TRADE_TARGET_PROFILE.set(profile)
    try:
        yield profile
    finally:
        _ACTIVE_SHORT_TRADE_TARGET_PROFILE.reset(token)
