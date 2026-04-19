from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ShortTradeTargetProfile:
    name: str
    select_threshold: float = 0.58
    near_miss_threshold: float = 0.46
    selected_rank_cap: int = 0
    near_miss_rank_cap: int = 0
    selected_rank_cap_ratio: float = 0.0
    near_miss_rank_cap_ratio: float = 0.0
    selected_rank_cap_relief_score_margin_min: float = 0.0
    selected_rank_cap_relief_rank_buffer: int = 0
    selected_rank_cap_relief_rank_buffer_ratio: float = 0.0
    selected_rank_cap_relief_sector_resonance_min: float = 0.0
    selected_rank_cap_relief_close_strength_max: float = 1.0
    selected_rank_cap_relief_require_confirmed_breakout: bool = False
    selected_rank_cap_relief_require_t_plus_2_candidate: bool = False
    selected_rank_cap_relief_allow_risk_off: bool = True
    selected_rank_cap_relief_allow_crisis: bool = True
    selected_breakout_freshness_min: float = 0.35
    selected_trend_acceleration_min: float = 0.38
    selected_close_retention_min: float = 0.0
    selected_close_retention_threshold_lift: float = 0.0
    selected_breakout_close_gap_max: float = 1.0
    selected_breakout_close_gap_threshold_lift: float = 0.0
    selected_close_retention_penalty_weight: float = 0.0
    near_miss_breakout_freshness_min: float = 0.0
    near_miss_trend_acceleration_min: float = 0.0
    breakout_freshness_weight: float = 0.22
    trend_acceleration_weight: float = 0.18
    volume_expansion_quality_weight: float = 0.16
    close_strength_weight: float = 0.14
    sector_resonance_weight: float = 0.12
    catalyst_freshness_weight: float = 0.08
    layer_c_alignment_weight: float = 0.10
    historical_continuation_score_weight: float = 0.0
    momentum_strength_weight: float = 0.0
    short_term_reversal_weight: float = 0.0
    intraday_strength_weight: float = 0.0
    reversal_2d_weight: float = 0.0
    stale_penalty_block_threshold: float = 0.72
    overhead_penalty_block_threshold: float = 0.68
    extension_penalty_block_threshold: float = 0.74
    layer_c_avoid_penalty: float = 0.12
    profitability_relief_enabled: bool = False
    profitability_relief_breakout_freshness_min: float = 0.42
    profitability_relief_catalyst_freshness_min: float = 0.45
    profitability_relief_sector_resonance_min: float = 0.45
    profitability_relief_avoid_penalty: float = 0.04
    profitability_hard_cliff_boundary_relief_enabled: bool = False
    profitability_hard_cliff_boundary_relief_breakout_freshness_min: float = 0.45
    profitability_hard_cliff_boundary_relief_trend_acceleration_min: float = 0.63
    profitability_hard_cliff_boundary_relief_catalyst_freshness_min: float = 0.17
    profitability_hard_cliff_boundary_relief_sector_resonance_min: float = 0.14
    profitability_hard_cliff_boundary_relief_close_strength_min: float = 0.85
    profitability_hard_cliff_boundary_relief_stale_penalty_max: float = 0.46
    profitability_hard_cliff_boundary_relief_extension_penalty_max: float = 0.46
    profitability_hard_cliff_boundary_relief_near_miss_threshold: float = 0.40
    prepared_breakout_penalty_relief_enabled: bool = False
    prepared_breakout_penalty_relief_breakout_freshness_max: float = 0.12
    prepared_breakout_penalty_relief_trend_acceleration_min: float = 0.32
    prepared_breakout_penalty_relief_close_strength_min: float = 0.66
    prepared_breakout_penalty_relief_sector_resonance_min: float = 0.28
    prepared_breakout_penalty_relief_layer_c_alignment_min: float = 0.60
    prepared_breakout_penalty_relief_catalyst_freshness_max: float = 0.05
    prepared_breakout_penalty_relief_long_trend_strength_min: float = 0.95
    prepared_breakout_penalty_relief_mean_reversion_strength_max: float = 0.20
    prepared_breakout_penalty_relief_breakout_freshness_weight: float = 0.08
    prepared_breakout_penalty_relief_trend_acceleration_weight: float = 0.20
    prepared_breakout_penalty_relief_volume_expansion_quality_weight: float = 0.20
    prepared_breakout_penalty_relief_close_strength_weight: float = 0.06
    prepared_breakout_penalty_relief_sector_resonance_weight: float = 0.04
    prepared_breakout_penalty_relief_catalyst_freshness_weight: float = 0.20
    prepared_breakout_penalty_relief_layer_c_alignment_weight: float = 0.22
    prepared_breakout_penalty_relief_stale_score_penalty_weight: float = 0.06
    prepared_breakout_penalty_relief_extension_score_penalty_weight: float = 0.04
    prepared_breakout_catalyst_relief_enabled: bool = False
    prepared_breakout_catalyst_relief_breakout_freshness_max: float = 0.12
    prepared_breakout_catalyst_relief_trend_acceleration_min: float = 0.32
    prepared_breakout_catalyst_relief_close_strength_min: float = 0.66
    prepared_breakout_catalyst_relief_sector_resonance_min: float = 0.28
    prepared_breakout_catalyst_relief_layer_c_alignment_min: float = 0.60
    prepared_breakout_catalyst_relief_catalyst_freshness_max: float = 0.05
    prepared_breakout_catalyst_relief_long_trend_strength_min: float = 0.95
    prepared_breakout_catalyst_relief_mean_reversion_strength_max: float = 0.20
    prepared_breakout_catalyst_relief_catalyst_freshness_floor: float = 0.35
    prepared_breakout_volume_relief_enabled: bool = False
    prepared_breakout_volume_relief_breakout_freshness_max: float = 0.12
    prepared_breakout_volume_relief_trend_acceleration_min: float = 0.32
    prepared_breakout_volume_relief_close_strength_min: float = 0.66
    prepared_breakout_volume_relief_sector_resonance_min: float = 0.28
    prepared_breakout_volume_relief_layer_c_alignment_min: float = 0.60
    prepared_breakout_volume_relief_catalyst_freshness_max: float = 0.05
    prepared_breakout_volume_relief_long_trend_strength_min: float = 0.95
    prepared_breakout_volume_relief_mean_reversion_strength_max: float = 0.20
    prepared_breakout_volume_relief_volatility_strength_max: float = 0.05
    prepared_breakout_volume_relief_volatility_regime_min: float = 1.15
    prepared_breakout_volume_relief_atr_ratio_min: float = 0.085
    prepared_breakout_volume_relief_volume_expansion_quality_floor: float = 0.35
    prepared_breakout_continuation_relief_enabled: bool = False
    prepared_breakout_continuation_relief_breakout_freshness_max: float = 0.05
    prepared_breakout_continuation_relief_trend_acceleration_min: float = 0.32
    prepared_breakout_continuation_relief_trend_acceleration_max: float = 0.45
    prepared_breakout_continuation_relief_close_strength_min: float = 0.66
    prepared_breakout_continuation_relief_sector_resonance_min: float = 0.28
    prepared_breakout_continuation_relief_layer_c_alignment_min: float = 0.60
    prepared_breakout_continuation_relief_catalyst_freshness_max: float = 0.05
    prepared_breakout_continuation_relief_long_trend_strength_min: float = 0.95
    prepared_breakout_continuation_relief_mean_reversion_strength_max: float = 0.20
    prepared_breakout_continuation_relief_momentum_1m_max: float = 0.0
    prepared_breakout_continuation_relief_continuation_support_min: float = 0.44
    prepared_breakout_continuation_relief_breakout_freshness_floor: float = 0.24
    prepared_breakout_continuation_relief_trend_acceleration_floor: float = 0.78
    prepared_breakout_selected_catalyst_relief_enabled: bool = False
    prepared_breakout_selected_catalyst_relief_breakout_freshness_min: float = 0.24
    prepared_breakout_selected_catalyst_relief_trend_acceleration_min: float = 0.75
    prepared_breakout_selected_catalyst_relief_close_strength_min: float = 0.66
    prepared_breakout_selected_catalyst_relief_sector_resonance_min: float = 0.28
    prepared_breakout_selected_catalyst_relief_layer_c_alignment_min: float = 0.60
    prepared_breakout_selected_catalyst_relief_volume_expansion_quality_min: float = 0.35
    prepared_breakout_selected_catalyst_relief_catalyst_freshness_max: float = 0.35
    prepared_breakout_selected_catalyst_relief_long_trend_strength_min: float = 0.95
    prepared_breakout_selected_catalyst_relief_mean_reversion_strength_max: float = 0.20
    prepared_breakout_selected_catalyst_relief_selected_breakout_freshness_floor: float = 0.35
    prepared_breakout_selected_catalyst_relief_catalyst_freshness_floor: float = 1.0
    stale_score_penalty_weight: float = 0.12
    overhead_score_penalty_weight: float = 0.10
    extension_score_penalty_weight: float = 0.08
    overbought_momentum_penalty_weight: float = 0.0
    overbought_momentum_threshold: float = 1.0
    watchlist_zero_catalyst_penalty: float = 0.0
    watchlist_zero_catalyst_catalyst_freshness_max: float = 0.0
    watchlist_zero_catalyst_close_strength_min: float = 1.0
    watchlist_zero_catalyst_layer_c_alignment_min: float = 1.0
    watchlist_zero_catalyst_sector_resonance_min: float = 1.0
    watchlist_zero_catalyst_crowded_penalty: float = 0.0
    watchlist_zero_catalyst_crowded_catalyst_freshness_max: float = 0.0
    watchlist_zero_catalyst_crowded_close_strength_min: float = 1.0
    watchlist_zero_catalyst_crowded_layer_c_alignment_min: float = 1.0
    watchlist_zero_catalyst_crowded_sector_resonance_min: float = 1.0
    watchlist_zero_catalyst_flat_trend_penalty: float = 0.0
    watchlist_zero_catalyst_flat_trend_catalyst_freshness_max: float = 0.0
    watchlist_zero_catalyst_flat_trend_close_strength_min: float = 1.0
    watchlist_zero_catalyst_flat_trend_layer_c_alignment_min: float = 1.0
    watchlist_zero_catalyst_flat_trend_sector_resonance_min: float = 1.0
    watchlist_zero_catalyst_flat_trend_trend_acceleration_max: float = 1.0
    t_plus_2_continuation_enabled: bool = False
    t_plus_2_continuation_catalyst_freshness_max: float = 0.0
    t_plus_2_continuation_breakout_freshness_min: float = 1.0
    t_plus_2_continuation_trend_acceleration_min: float = 1.0
    t_plus_2_continuation_trend_acceleration_max: float = 1.0
    t_plus_2_continuation_layer_c_alignment_min: float = 1.0
    t_plus_2_continuation_layer_c_alignment_max: float = 0.0
    t_plus_2_continuation_close_strength_max: float = 1.0
    t_plus_2_continuation_sector_resonance_max: float = 0.0
    visibility_gap_continuation_relief_enabled: bool = False
    visibility_gap_continuation_breakout_freshness_min: float = 1.0
    visibility_gap_continuation_trend_acceleration_min: float = 1.0
    visibility_gap_continuation_close_strength_min: float = 1.0
    visibility_gap_continuation_catalyst_freshness_floor: float = 0.0
    visibility_gap_continuation_near_miss_threshold: float = 0.46
    visibility_gap_continuation_require_relaxed_band: bool = True
    merge_approved_continuation_relief_enabled: bool = False
    merge_approved_continuation_select_threshold: float = 0.58
    merge_approved_continuation_near_miss_threshold: float = 0.46
    merge_approved_continuation_breakout_freshness_min: float = 1.0
    merge_approved_continuation_trend_acceleration_min: float = 1.0
    merge_approved_continuation_close_strength_min: float = 1.0
    merge_approved_continuation_require_no_profitability_hard_cliff: bool = True
    historical_execution_relief_near_miss_threshold: float | None = None
    historical_execution_relief_select_threshold: float | None = None
    historical_execution_relief_strong_close_continuation_select_threshold: float | None = None
    historical_execution_relief_allow_strong_close_continuation_without_profitability_hard_cliff: bool = False
    hard_block_bearish_conflicts: frozenset[str] = frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"})
    overhead_conflict_penalty_conflicts: frozenset[str] = frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"})

    @property
    def strong_bearish_conflicts(self) -> frozenset[str]:
        return self.hard_block_bearish_conflicts


from src.targets.short_trade_target_profile_data import SHORT_TRADE_TARGET_PROFILES  # noqa: E402

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
