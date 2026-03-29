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
    stale_penalty_block_threshold: float = 0.72
    overhead_penalty_block_threshold: float = 0.68
    extension_penalty_block_threshold: float = 0.74
    layer_c_avoid_penalty: float = 0.12
    stale_score_penalty_weight: float = 0.12
    overhead_score_penalty_weight: float = 0.10
    extension_score_penalty_weight: float = 0.08
    strong_bearish_conflicts: frozenset[str] = frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"})


SHORT_TRADE_TARGET_PROFILES: dict[str, ShortTradeTargetProfile] = {
    "default": ShortTradeTargetProfile(name="default"),
    "conservative": ShortTradeTargetProfile(
        name="conservative",
        select_threshold=0.62,
        near_miss_threshold=0.50,
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
        stale_penalty_block_threshold=0.78,
        overhead_penalty_block_threshold=0.74,
        extension_penalty_block_threshold=0.80,
        layer_c_avoid_penalty=0.08,
        stale_score_penalty_weight=0.08,
        overhead_score_penalty_weight=0.07,
        extension_score_penalty_weight=0.05,
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
        normalized_overrides["strong_bearish_conflicts"] = frozenset(str(value) for value in normalized_overrides["strong_bearish_conflicts"])
    return replace(profile, **normalized_overrides)


@contextmanager
def use_short_trade_target_profile(*, profile_name: str = "default", overrides: Mapping[str, Any] | None = None) -> Iterator[ShortTradeTargetProfile]:
    profile = build_short_trade_target_profile(profile_name, overrides)
    token = _ACTIVE_SHORT_TRADE_TARGET_PROFILE.set(profile)
    try:
        yield profile
    finally:
        _ACTIVE_SHORT_TRADE_TARGET_PROFILE.reset(token)
