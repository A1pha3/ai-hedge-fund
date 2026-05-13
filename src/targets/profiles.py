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
    catalyst_theme_selected_rank_cap_ratio: float | None = None
    catalyst_theme_near_miss_rank_cap_ratio: float | None = None
    catalyst_theme_source_specific_rank_cap_trend_acceleration_min: float = 0.0
    catalyst_theme_source_specific_rank_cap_sector_resonance_min: float = 0.0
    catalyst_theme_source_specific_rank_cap_close_strength_min: float = 0.0
    liquidity_shadow_selected_rank_cap_ratio: float | None = None
    liquidity_shadow_near_miss_rank_cap_ratio: float | None = None
    liquidity_shadow_source_specific_rank_cap_require_relief_applied: bool = True
    selected_rank_cap_relief_score_margin_min: float = 0.0
    selected_rank_cap_relief_rank_buffer: int = 0
    selected_rank_cap_relief_rank_buffer_ratio: float = 0.0
    selected_rank_cap_relief_sector_resonance_min: float = 0.0
    selected_rank_cap_relief_close_strength_max: float = 1.0
    selected_rank_cap_relief_require_confirmed_breakout: bool = False
    selected_rank_cap_relief_require_t_plus_2_candidate: bool = False
    selected_rank_cap_relief_allow_risk_off: bool = True
    selected_rank_cap_relief_allow_crisis: bool = True
    regime_admission_recovery_enabled: bool = False
    regime_admission_recovery_normal_trade_relief: float = 0.0
    regime_admission_recovery_aggressive_trade_relief: float = 0.0
    regime_admission_recovery_max_relief: float = 0.0
    selected_rank_cap_relief_catalyst_theme_carryover_support_enabled: bool = False
    selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count: int = 0
    selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min: float = 0.0
    selected_rank_cap_relief_catalyst_theme_research_enabled: bool = False
    selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min: float = 0.0
    selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min: float = 0.0
    selected_rank_cap_relief_catalyst_theme_research_close_strength_max: float = 1.0
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
    catalyst_theme_penalty: float = 0.0
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
    watchlist_filter_diagnostics_flat_trend_penalty: float = 0.0
    watchlist_filter_diagnostics_flat_trend_catalyst_freshness_max: float = 0.0
    watchlist_filter_diagnostics_flat_trend_close_strength_min: float = 1.0
    watchlist_filter_diagnostics_flat_trend_trend_acceleration_max: float = 1.0
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
    hard_block_conflict_score_b_relief_min: float | None = 0.50
    hard_block_conflict_score_c_relief_min: float | None = -0.08
    # P3 prior quality hard-gate thresholds (config for profile-level overrides; defaults match spec)
    p3_prior_quality_min_n_selected: int = 5  # n < this → selected blocked
    p3_prior_quality_min_n_near_miss: int = 3  # n < this → near_miss blocked
    p3_prior_quality_close_positive_min: float = 0.50  # close+ < this → downgrade to watch_only
    p3_prior_quality_high_hit_reject_threshold: float = 0.0  # high_hit_rate <= this → reject
    # P4 prior shrinkage controls
    p4_prior_shrinkage_k: float = 8.0
    selected_use_shrunk_prior_rates: bool = True
    adaptive_prior_shrinkage_enabled: bool = False
    adaptive_prior_shrinkage_low_sample_max_evaluable_count: int = 3
    adaptive_prior_shrinkage_close_continuation_normal_trade_k: float = 8.0
    adaptive_prior_shrinkage_close_continuation_aggressive_trade_k: float = 8.0
    # Event catalyst assessment controls
    event_catalyst_enabled: bool = False
    event_catalyst_candidate_sources: frozenset[str] = frozenset({"catalyst_theme", "short_trade_boundary"})
    event_catalyst_catalyst_freshness_weight: float = 0.30
    event_catalyst_sector_resonance_weight: float = 0.22
    event_catalyst_volume_expansion_weight: float = 0.18
    event_catalyst_close_strength_weight: float = 0.18
    event_catalyst_trend_acceleration_weight: float = 0.12
    event_catalyst_min_score_for_selected_uplift: float = 0.72
    event_catalyst_min_score_for_near_miss_retain: float = 0.58
    event_catalyst_selected_uplift: float = 0.03
    event_catalyst_near_miss_threshold_relief: float = 0.02
    event_catalyst_extension_penalty_max: float = 0.55
    event_catalyst_stale_penalty_max: float = 0.50
    event_catalyst_overhead_penalty_max: float = 0.50
    committee_enabled: bool = False
    committee_alpha_weight: float = 0.55
    committee_beta_weight: float = 0.25
    committee_gamma_weight: float = 0.20
    committee_fragile_breakout_risk_enabled: bool = False
    committee_fragile_breakout_alpha_weight: float = 0.10
    committee_fragile_breakout_activation_floor: float = 60.0
    committee_fragile_breakout_fragility_floor: float = 55.0
    committee_fragile_breakout_risk_cap: float = 85.0
    committee_alpha_min_aggressive_trade: float = 0.0
    committee_beta_min_aggressive_trade: float = 0.0
    committee_gamma_min_aggressive_trade: float = 0.0
    committee_score_min_aggressive_trade: float = 0.0
    committee_alpha_min_normal_trade: float = 0.0
    committee_beta_min_normal_trade: float = 0.0
    committee_gamma_min_normal_trade: float = 0.0
    committee_score_min_normal_trade: float = 0.0
    committee_sector_group_score_min_aggressive_trade: float = 0.05
    committee_flow_group_score_min_aggressive_trade: float = 0.08
    committee_retention_group_score_min_aggressive_trade: float = 0.0
    committee_sector_group_score_min_normal_trade: float = 0.05
    committee_flow_group_score_min_normal_trade: float = 0.05
    committee_retention_group_score_min_normal_trade: float = 0.05
    committee_penalty_total_max: float = 0.12
    committee_theme_exposure_cap: float = 0.25
    committee_incremental_theme_exposure_cap: float = 0.18
    committee_isolated_theme_direction_enabled: bool = True
    committee_isolated_theme_peer_count_min: float = 2.0
    committee_theme_direction_rank_enabled: bool = True
    committee_theme_direction_rank_max: float = 5.0
    committee_isolated_attention_veto_enabled: bool = True
    committee_isolated_attention_min: float = 80.0
    committee_isolated_attention_sector_max: float = 60.0
    committee_isolated_attention_flow_max: float = 60.0
    committee_weak_close_veto_enabled: bool = True
    committee_weak_close_flow_min: float = 75.0
    committee_weak_close_structure_max: float = 45.0
    committee_weak_close_close_support_max: float = 60.0
    committee_gap_to_limit_veto_enabled: bool = True
    committee_gap_to_limit_max: float = 0.01
    committee_failed_breakout_history_veto_enabled: bool = True
    committee_failed_breakout_history_min: float = 1.0
    committee_failed_breakout_metric_veto_enabled: bool = True
    committee_failed_breakout_metric_min: float = 3.0
    committee_shadow_only_blocks_selected: bool = True
    runner_escape_enabled: bool = False
    runner_escape_breakout_freshness_min: float = 0.0
    runner_escape_trend_acceleration_min: float = 0.0
    runner_escape_volume_expansion_quality_min: float = 0.0
    runner_escape_gap_risk_raw_100_max: float = 0.0
    runner_escape_projected_theme_exposure_max: float = 0.0
    runner_escape_candidate_pool_avg_amount_share_of_cutoff_min: float = 0.0
    runner_escape_composite_score_min: float = 0.0
    runner_composite_score_breakout_weight: float = 0.40
    runner_composite_score_trend_weight: float = 0.30
    runner_composite_score_volume_weight: float = 0.20
    runner_composite_score_catalyst_weight: float = 0.10
    runner_composite_score_close_strength_weight: float = 0.10
    runner_composite_score_volatility_regime_weight: float = 0.0
    runner_composite_score_sector_resonance_weight: float = 0.0
    # Task 5 (Round 10): quiet breakout cross-factor — high momentum × low volatility synergy.
    # Captures "安静突破" setups where breakout freshness is amplified by a calm volatility regime.
    runner_composite_score_quiet_breakout_weight: float = 0.0

    @property
    def strong_bearish_conflicts(self) -> frozenset[str]:
        return self.hard_block_bearish_conflicts


from src.targets.short_trade_target_profile_data import (  # noqa: E402
    SHORT_TRADE_TARGET_PROFILES,
)

_ACTIVE_SHORT_TRADE_TARGET_PROFILE: ContextVar[ShortTradeTargetProfile] = ContextVar(
    "active_short_trade_target_profile",
    default=SHORT_TRADE_TARGET_PROFILES["default"],
)
_SHORT_TRADE_TARGET_PROFILE_CONTEXT_ACTIVE: ContextVar[bool] = ContextVar(
    "short_trade_target_profile_context_active",
    default=False,
)


def get_short_trade_target_profile(name: str = "default") -> ShortTradeTargetProfile:
    profile = SHORT_TRADE_TARGET_PROFILES.get(str(name or "default"))
    if profile is None:
        available = ", ".join(sorted(SHORT_TRADE_TARGET_PROFILES))
        raise ValueError(f"Unknown short trade target profile: {name}. Available: {available}")
    return profile


def get_active_short_trade_target_profile() -> ShortTradeTargetProfile:
    return _ACTIVE_SHORT_TRADE_TARGET_PROFILE.get()


def is_short_trade_target_profile_context_active() -> bool:
    return _SHORT_TRADE_TARGET_PROFILE_CONTEXT_ACTIVE.get()


def build_short_trade_target_profile(name: str = "default", overrides: Mapping[str, Any] | None = None) -> ShortTradeTargetProfile:
    profile = get_short_trade_target_profile(name)
    if not overrides:
        return profile
    normalized_overrides = dict(overrides)
    if "strong_bearish_conflicts" in normalized_overrides and normalized_overrides["strong_bearish_conflicts"] is not None:
        shared_conflicts = frozenset(str(value) for value in normalized_overrides.pop("strong_bearish_conflicts"))
        normalized_overrides["hard_block_bearish_conflicts"] = shared_conflicts
        normalized_overrides["overhead_conflict_penalty_conflicts"] = shared_conflicts
    if "hard_block_bearish_conflicts" in normalized_overrides and normalized_overrides["hard_block_bearish_conflicts"] is not None:
        normalized_overrides["hard_block_bearish_conflicts"] = frozenset(str(value) for value in normalized_overrides["hard_block_bearish_conflicts"])
    if "overhead_conflict_penalty_conflicts" in normalized_overrides and normalized_overrides["overhead_conflict_penalty_conflicts"] is not None:
        normalized_overrides["overhead_conflict_penalty_conflicts"] = frozenset(str(value) for value in normalized_overrides["overhead_conflict_penalty_conflicts"])
    return replace(profile, **normalized_overrides)


@contextmanager
def use_short_trade_target_profile(*, profile_name: str = "default", overrides: Mapping[str, Any] | None = None) -> Iterator[ShortTradeTargetProfile]:
    profile = build_short_trade_target_profile(profile_name, overrides)
    token = _ACTIVE_SHORT_TRADE_TARGET_PROFILE.set(profile)
    context_token = _SHORT_TRADE_TARGET_PROFILE_CONTEXT_ACTIVE.set(True)
    try:
        yield profile
    finally:
        _SHORT_TRADE_TARGET_PROFILE_CONTEXT_ACTIVE.reset(context_token)
        _ACTIVE_SHORT_TRADE_TARGET_PROFILE.reset(token)
