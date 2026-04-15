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
    near_miss_breakout_freshness_min: float = 0.0
    near_miss_trend_acceleration_min: float = 0.0
    breakout_freshness_weight: float = 0.22
    trend_acceleration_weight: float = 0.18
    volume_expansion_quality_weight: float = 0.16
    close_strength_weight: float = 0.14
    sector_resonance_weight: float = 0.12
    catalyst_freshness_weight: float = 0.08
    layer_c_alignment_weight: float = 0.10
    momentum_strength_weight: float = 0.0
    short_term_reversal_weight: float = 0.0
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


SHORT_TRADE_TARGET_PROFILES: dict[str, ShortTradeTargetProfile] = {
    "default": ShortTradeTargetProfile(
        name="default",
        select_threshold=0.40,
        near_miss_threshold=0.34,
        breakout_freshness_weight=0.22,
        trend_acceleration_weight=0.16,
        volume_expansion_quality_weight=0.14,
        close_strength_weight=0.10,
        sector_resonance_weight=0.10,
        catalyst_freshness_weight=0.10,
        layer_c_alignment_weight=0.08,
        momentum_strength_weight=0.10,
        stale_score_penalty_weight=0.09,
        overhead_score_penalty_weight=0.07,
        extension_score_penalty_weight=0.06,
        layer_c_avoid_penalty=0.09,
        stale_penalty_block_threshold=0.78,
        overhead_penalty_block_threshold=0.74,
        extension_penalty_block_threshold=0.80,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.30,
        profitability_relief_catalyst_freshness_min=0.30,
        profitability_relief_sector_resonance_min=0.30,
        profitability_relief_avoid_penalty=0.04,
        profitability_hard_cliff_boundary_relief_enabled=True,
        profitability_hard_cliff_boundary_relief_breakout_freshness_min=0.30,
        profitability_hard_cliff_boundary_relief_trend_acceleration_min=0.45,
        profitability_hard_cliff_boundary_relief_catalyst_freshness_min=0.10,
        profitability_hard_cliff_boundary_relief_sector_resonance_min=0.125,
        profitability_hard_cliff_boundary_relief_close_strength_min=0.35,
        profitability_hard_cliff_boundary_relief_stale_penalty_max=0.47,
        profitability_hard_cliff_boundary_relief_extension_penalty_max=0.55,
        profitability_hard_cliff_boundary_relief_near_miss_threshold=0.28,
        visibility_gap_continuation_relief_enabled=True,
        visibility_gap_continuation_breakout_freshness_min=0.24,
        visibility_gap_continuation_trend_acceleration_min=0.60,
        visibility_gap_continuation_close_strength_min=0.75,
        visibility_gap_continuation_catalyst_freshness_floor=0.25,
        visibility_gap_continuation_near_miss_threshold=0.34,
        visibility_gap_continuation_require_relaxed_band=True,
        merge_approved_continuation_relief_enabled=True,
        merge_approved_continuation_select_threshold=0.48,
        merge_approved_continuation_near_miss_threshold=0.34,
        merge_approved_continuation_breakout_freshness_min=0.18,
        merge_approved_continuation_trend_acceleration_min=0.25,
        merge_approved_continuation_close_strength_min=0.45,
        merge_approved_continuation_require_no_profitability_hard_cliff=True,
        historical_execution_relief_near_miss_threshold=0.32,
        historical_execution_relief_select_threshold=0.38,
        historical_execution_relief_strong_close_continuation_select_threshold=0.37,
        historical_execution_relief_allow_strong_close_continuation_without_profitability_hard_cliff=True,
        prepared_breakout_penalty_relief_enabled=True,
        prepared_breakout_catalyst_relief_enabled=True,
        prepared_breakout_volume_relief_enabled=True,
        prepared_breakout_continuation_relief_enabled=True,
        prepared_breakout_selected_catalyst_relief_enabled=True,
    ),
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
        select_threshold=0.36,
        near_miss_threshold=0.26,
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
    "watchlist_zero_catalyst_guard_relief": ShortTradeTargetProfile(
        name="watchlist_zero_catalyst_guard_relief",
        select_threshold=0.40,
        near_miss_threshold=0.40,
        layer_c_avoid_penalty=0.06,
        stale_score_penalty_weight=0.06,
        overhead_score_penalty_weight=0.05,
        extension_score_penalty_weight=0.04,
        watchlist_zero_catalyst_penalty=0.12,
        watchlist_zero_catalyst_catalyst_freshness_max=0.05,
        watchlist_zero_catalyst_close_strength_min=0.92,
        watchlist_zero_catalyst_layer_c_alignment_min=0.72,
        watchlist_zero_catalyst_sector_resonance_min=0.35,
        watchlist_zero_catalyst_crowded_penalty=0.06,
        watchlist_zero_catalyst_crowded_catalyst_freshness_max=0.05,
        watchlist_zero_catalyst_crowded_close_strength_min=0.938,
        watchlist_zero_catalyst_crowded_layer_c_alignment_min=0.78,
        watchlist_zero_catalyst_crowded_sector_resonance_min=0.42,
        watchlist_zero_catalyst_flat_trend_penalty=0.03,
        watchlist_zero_catalyst_flat_trend_catalyst_freshness_max=0.05,
        watchlist_zero_catalyst_flat_trend_close_strength_min=0.945,
        watchlist_zero_catalyst_flat_trend_layer_c_alignment_min=0.75,
        watchlist_zero_catalyst_flat_trend_sector_resonance_min=0.388,
        watchlist_zero_catalyst_flat_trend_trend_acceleration_max=0.66,
        t_plus_2_continuation_enabled=True,
        t_plus_2_continuation_catalyst_freshness_max=0.08,
        t_plus_2_continuation_breakout_freshness_min=0.30,
        t_plus_2_continuation_trend_acceleration_min=0.38,
        t_plus_2_continuation_trend_acceleration_max=0.60,
        t_plus_2_continuation_layer_c_alignment_min=0.45,
        t_plus_2_continuation_layer_c_alignment_max=0.60,
        t_plus_2_continuation_close_strength_max=0.90,
        t_plus_2_continuation_sector_resonance_max=0.20,
        hard_block_bearish_conflicts=frozenset(),
        overhead_conflict_penalty_conflicts=frozenset(),
    ),
    "btst_conversion_relief": ShortTradeTargetProfile(
        name="btst_conversion_relief",
        select_threshold=0.40,
        near_miss_threshold=0.34,
        layer_c_avoid_penalty=0.07,
        stale_score_penalty_weight=0.07,
        overhead_score_penalty_weight=0.06,
        extension_score_penalty_weight=0.05,
        watchlist_zero_catalyst_penalty=0.10,
        watchlist_zero_catalyst_catalyst_freshness_max=0.06,
        watchlist_zero_catalyst_close_strength_min=0.90,
        watchlist_zero_catalyst_layer_c_alignment_min=0.70,
        watchlist_zero_catalyst_sector_resonance_min=0.33,
        watchlist_zero_catalyst_crowded_penalty=0.05,
        watchlist_zero_catalyst_crowded_catalyst_freshness_max=0.05,
        watchlist_zero_catalyst_crowded_close_strength_min=0.93,
        watchlist_zero_catalyst_crowded_layer_c_alignment_min=0.76,
        watchlist_zero_catalyst_crowded_sector_resonance_min=0.40,
        watchlist_zero_catalyst_flat_trend_penalty=0.02,
        watchlist_zero_catalyst_flat_trend_catalyst_freshness_max=0.05,
        watchlist_zero_catalyst_flat_trend_close_strength_min=0.94,
        watchlist_zero_catalyst_flat_trend_layer_c_alignment_min=0.74,
        watchlist_zero_catalyst_flat_trend_sector_resonance_min=0.37,
        watchlist_zero_catalyst_flat_trend_trend_acceleration_max=0.66,
        t_plus_2_continuation_enabled=True,
        t_plus_2_continuation_catalyst_freshness_max=0.10,
        t_plus_2_continuation_breakout_freshness_min=0.26,
        t_plus_2_continuation_trend_acceleration_min=0.36,
        t_plus_2_continuation_trend_acceleration_max=0.62,
        t_plus_2_continuation_layer_c_alignment_min=0.42,
        t_plus_2_continuation_layer_c_alignment_max=0.62,
        t_plus_2_continuation_close_strength_max=0.92,
        t_plus_2_continuation_sector_resonance_max=0.22,
    ),
    "ic_optimized": ShortTradeTargetProfile(
        name="ic_optimized",
        select_threshold=0.40,
        near_miss_threshold=0.28,
        breakout_freshness_weight=0.06,
        trend_acceleration_weight=0.06,
        volume_expansion_quality_weight=0.16,
        close_strength_weight=0.26,
        sector_resonance_weight=0.14,
        catalyst_freshness_weight=0.18,
        layer_c_alignment_weight=0.14,
        momentum_strength_weight=0.10,
        short_term_reversal_weight=0.08,
        stale_score_penalty_weight=0.06,
        overhead_score_penalty_weight=0.05,
        extension_score_penalty_weight=0.07,
        layer_c_avoid_penalty=0.07,
        stale_penalty_block_threshold=0.82,
        overhead_penalty_block_threshold=0.78,
        extension_penalty_block_threshold=0.84,
        selected_breakout_freshness_min=0.20,
        selected_trend_acceleration_min=0.20,
        near_miss_breakout_freshness_min=0.0,
        near_miss_trend_acceleration_min=0.0,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.15,
        profitability_relief_catalyst_freshness_min=0.20,
        profitability_relief_sector_resonance_min=0.20,
        profitability_relief_avoid_penalty=0.03,
        profitability_hard_cliff_boundary_relief_enabled=True,
        profitability_hard_cliff_boundary_relief_breakout_freshness_min=0.15,
        profitability_hard_cliff_boundary_relief_trend_acceleration_min=0.30,
        profitability_hard_cliff_boundary_relief_catalyst_freshness_min=0.05,
        profitability_hard_cliff_boundary_relief_sector_resonance_min=0.05,
        profitability_hard_cliff_boundary_relief_close_strength_min=0.30,
        profitability_hard_cliff_boundary_relief_stale_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_extension_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_near_miss_threshold=0.24,
        prepared_breakout_penalty_relief_enabled=True,
        prepared_breakout_catalyst_relief_enabled=True,
        prepared_breakout_volume_relief_enabled=True,
        prepared_breakout_continuation_relief_enabled=True,
        prepared_breakout_selected_catalyst_relief_enabled=True,
        visibility_gap_continuation_relief_enabled=True,
        visibility_gap_continuation_breakout_freshness_min=0.12,
        visibility_gap_continuation_trend_acceleration_min=0.35,
        visibility_gap_continuation_close_strength_min=0.50,
        visibility_gap_continuation_catalyst_freshness_floor=0.15,
        visibility_gap_continuation_near_miss_threshold=0.26,
        visibility_gap_continuation_require_relaxed_band=True,
        merge_approved_continuation_relief_enabled=True,
        merge_approved_continuation_select_threshold=0.40,
        merge_approved_continuation_near_miss_threshold=0.28,
        merge_approved_continuation_breakout_freshness_min=0.10,
        merge_approved_continuation_trend_acceleration_min=0.15,
        merge_approved_continuation_close_strength_min=0.35,
        merge_approved_continuation_require_no_profitability_hard_cliff=True,
        historical_execution_relief_near_miss_threshold=0.26,
        historical_execution_relief_select_threshold=0.32,
        historical_execution_relief_strong_close_continuation_select_threshold=0.30,
        historical_execution_relief_allow_strong_close_continuation_without_profitability_hard_cliff=True,
        hard_block_bearish_conflicts=frozenset({"b_strong_buy_c_negative"}),
        overhead_conflict_penalty_conflicts=frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"}),
    ),
    "momentum_optimized": ShortTradeTargetProfile(
        name="momentum_optimized",
        select_threshold=0.46,
        near_miss_threshold=0.32,
        breakout_freshness_weight=0.14,
        trend_acceleration_weight=0.24,
        volume_expansion_quality_weight=0.18,
        close_strength_weight=0.14,
        sector_resonance_weight=0.10,
        catalyst_freshness_weight=0.10,
        layer_c_alignment_weight=0.10,
        stale_score_penalty_weight=0.07,
        overhead_score_penalty_weight=0.06,
        extension_score_penalty_weight=0.04,
        layer_c_avoid_penalty=0.08,
        stale_penalty_block_threshold=0.80,
        overhead_penalty_block_threshold=0.76,
        extension_penalty_block_threshold=0.82,
        selected_breakout_freshness_min=0.28,
        selected_trend_acceleration_min=0.30,
        near_miss_breakout_freshness_min=0.0,
        near_miss_trend_acceleration_min=0.0,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.25,
        profitability_relief_catalyst_freshness_min=0.25,
        profitability_relief_sector_resonance_min=0.25,
        profitability_relief_avoid_penalty=0.03,
        profitability_hard_cliff_boundary_relief_enabled=True,
        profitability_hard_cliff_boundary_relief_breakout_freshness_min=0.25,
        profitability_hard_cliff_boundary_relief_trend_acceleration_min=0.40,
        profitability_hard_cliff_boundary_relief_catalyst_freshness_min=0.08,
        profitability_hard_cliff_boundary_relief_sector_resonance_min=0.08,
        profitability_hard_cliff_boundary_relief_close_strength_min=0.50,
        profitability_hard_cliff_boundary_relief_stale_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_extension_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_near_miss_threshold=0.28,
        prepared_breakout_penalty_relief_enabled=True,
        prepared_breakout_catalyst_relief_enabled=True,
        prepared_breakout_volume_relief_enabled=True,
        prepared_breakout_continuation_relief_enabled=True,
        prepared_breakout_selected_catalyst_relief_enabled=True,
        visibility_gap_continuation_relief_enabled=True,
        visibility_gap_continuation_breakout_freshness_min=0.20,
        visibility_gap_continuation_trend_acceleration_min=0.50,
        visibility_gap_continuation_close_strength_min=0.65,
        visibility_gap_continuation_catalyst_freshness_floor=0.20,
        visibility_gap_continuation_near_miss_threshold=0.30,
        visibility_gap_continuation_require_relaxed_band=True,
        merge_approved_continuation_relief_enabled=True,
        merge_approved_continuation_select_threshold=0.44,
        merge_approved_continuation_near_miss_threshold=0.30,
        merge_approved_continuation_breakout_freshness_min=0.15,
        merge_approved_continuation_trend_acceleration_min=0.20,
        merge_approved_continuation_close_strength_min=0.40,
        merge_approved_continuation_require_no_profitability_hard_cliff=True,
        hard_block_bearish_conflicts=frozenset({"b_strong_buy_c_negative"}),
        overhead_conflict_penalty_conflicts=frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"}),
    ),
    "btst_precision_v1": ShortTradeTargetProfile(
        name="btst_precision_v1",
        select_threshold=0.40,
        near_miss_threshold=0.30,
        selected_rank_cap_ratio=0.08,
        near_miss_rank_cap_ratio=0.16,
        breakout_freshness_weight=0.001,
        trend_acceleration_weight=0.40,
        volume_expansion_quality_weight=0.027,
        close_strength_weight=0.060,
        sector_resonance_weight=0.042,
        catalyst_freshness_weight=0.136,
        layer_c_alignment_weight=0.023,
        momentum_strength_weight=0.005,
        short_term_reversal_weight=0.307,
        stale_score_penalty_weight=0.06,
        overhead_score_penalty_weight=0.05,
        extension_score_penalty_weight=0.04,
        layer_c_avoid_penalty=0.06,
        stale_penalty_block_threshold=0.82,
        overhead_penalty_block_threshold=0.78,
        extension_penalty_block_threshold=0.84,
        selected_breakout_freshness_min=0.12,
        selected_trend_acceleration_min=0.18,
        near_miss_breakout_freshness_min=0.0,
        near_miss_trend_acceleration_min=0.0,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.15,
        profitability_relief_catalyst_freshness_min=0.20,
        profitability_relief_sector_resonance_min=0.20,
        profitability_relief_avoid_penalty=0.03,
        profitability_hard_cliff_boundary_relief_enabled=True,
        profitability_hard_cliff_boundary_relief_breakout_freshness_min=0.15,
        profitability_hard_cliff_boundary_relief_trend_acceleration_min=0.30,
        profitability_hard_cliff_boundary_relief_catalyst_freshness_min=0.05,
        profitability_hard_cliff_boundary_relief_sector_resonance_min=0.05,
        profitability_hard_cliff_boundary_relief_close_strength_min=0.30,
        profitability_hard_cliff_boundary_relief_stale_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_extension_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_near_miss_threshold=0.24,
        prepared_breakout_penalty_relief_enabled=True,
        prepared_breakout_catalyst_relief_enabled=True,
        prepared_breakout_volume_relief_enabled=True,
        prepared_breakout_continuation_relief_enabled=True,
        prepared_breakout_selected_catalyst_relief_enabled=True,
        visibility_gap_continuation_relief_enabled=True,
        visibility_gap_continuation_breakout_freshness_min=0.12,
        visibility_gap_continuation_trend_acceleration_min=0.35,
        visibility_gap_continuation_close_strength_min=0.50,
        visibility_gap_continuation_catalyst_freshness_floor=0.15,
        visibility_gap_continuation_near_miss_threshold=0.28,
        visibility_gap_continuation_require_relaxed_band=True,
        merge_approved_continuation_relief_enabled=True,
        merge_approved_continuation_select_threshold=0.40,
        merge_approved_continuation_near_miss_threshold=0.30,
        merge_approved_continuation_breakout_freshness_min=0.10,
        merge_approved_continuation_trend_acceleration_min=0.15,
        merge_approved_continuation_close_strength_min=0.35,
        merge_approved_continuation_require_no_profitability_hard_cliff=True,
        historical_execution_relief_near_miss_threshold=0.28,
        historical_execution_relief_select_threshold=0.34,
        historical_execution_relief_strong_close_continuation_select_threshold=0.32,
        historical_execution_relief_allow_strong_close_continuation_without_profitability_hard_cliff=True,
        hard_block_bearish_conflicts=frozenset({"b_strong_buy_c_negative"}),
        overhead_conflict_penalty_conflicts=frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"}),
    ),
    "btst_precision_v2": ShortTradeTargetProfile(
        name="btst_precision_v2",
        select_threshold=0.34,
        near_miss_threshold=0.26,
        selected_rank_cap_ratio=0.16,
        near_miss_rank_cap_ratio=0.32,
        selected_rank_cap_relief_rank_buffer_ratio=0.003,
        selected_rank_cap_relief_require_confirmed_breakout=True,
        selected_rank_cap_relief_allow_risk_off=True,
        selected_rank_cap_relief_allow_crisis=False,
        breakout_freshness_weight=0.123,
        trend_acceleration_weight=0.345,
        volume_expansion_quality_weight=0.014,
        close_strength_weight=0.051,
        sector_resonance_weight=0.040,
        catalyst_freshness_weight=0.044,
        layer_c_alignment_weight=0.007,
        momentum_strength_weight=0.027,
        short_term_reversal_weight=0.350,
        stale_score_penalty_weight=0.06,
        overhead_score_penalty_weight=0.05,
        extension_score_penalty_weight=0.04,
        layer_c_avoid_penalty=0.06,
        stale_penalty_block_threshold=0.82,
        overhead_penalty_block_threshold=0.78,
        extension_penalty_block_threshold=0.84,
        selected_breakout_freshness_min=0.10,
        selected_trend_acceleration_min=0.16,
        near_miss_breakout_freshness_min=0.0,
        near_miss_trend_acceleration_min=0.0,
        profitability_relief_enabled=True,
        profitability_relief_breakout_freshness_min=0.12,
        profitability_relief_catalyst_freshness_min=0.18,
        profitability_relief_sector_resonance_min=0.18,
        profitability_relief_avoid_penalty=0.03,
        profitability_hard_cliff_boundary_relief_enabled=True,
        profitability_hard_cliff_boundary_relief_breakout_freshness_min=0.12,
        profitability_hard_cliff_boundary_relief_trend_acceleration_min=0.28,
        profitability_hard_cliff_boundary_relief_catalyst_freshness_min=0.05,
        profitability_hard_cliff_boundary_relief_sector_resonance_min=0.05,
        profitability_hard_cliff_boundary_relief_close_strength_min=0.28,
        profitability_hard_cliff_boundary_relief_stale_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_extension_penalty_max=0.60,
        profitability_hard_cliff_boundary_relief_near_miss_threshold=0.22,
        prepared_breakout_penalty_relief_enabled=True,
        prepared_breakout_catalyst_relief_enabled=True,
        prepared_breakout_volume_relief_enabled=True,
        prepared_breakout_continuation_relief_enabled=True,
        prepared_breakout_selected_catalyst_relief_enabled=True,
        visibility_gap_continuation_relief_enabled=True,
        visibility_gap_continuation_breakout_freshness_min=0.10,
        visibility_gap_continuation_trend_acceleration_min=0.32,
        visibility_gap_continuation_close_strength_min=0.48,
        visibility_gap_continuation_catalyst_freshness_floor=0.14,
        visibility_gap_continuation_near_miss_threshold=0.24,
        visibility_gap_continuation_require_relaxed_band=True,
        merge_approved_continuation_relief_enabled=True,
        merge_approved_continuation_select_threshold=0.34,
        merge_approved_continuation_near_miss_threshold=0.26,
        merge_approved_continuation_breakout_freshness_min=0.08,
        merge_approved_continuation_trend_acceleration_min=0.14,
        merge_approved_continuation_close_strength_min=0.32,
        merge_approved_continuation_require_no_profitability_hard_cliff=True,
        historical_execution_relief_near_miss_threshold=0.24,
        historical_execution_relief_select_threshold=0.30,
        historical_execution_relief_strong_close_continuation_select_threshold=0.28,
        historical_execution_relief_allow_strong_close_continuation_without_profitability_hard_cliff=True,
        hard_block_bearish_conflicts=frozenset({"b_strong_buy_c_negative"}),
        overhead_conflict_penalty_conflicts=frozenset({"b_positive_c_strong_bearish", "b_strong_buy_c_negative"}),
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
