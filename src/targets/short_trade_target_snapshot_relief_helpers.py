"""Short trade target snapshot relief helpers — back-compat re-export.

This module used to host the entire snapshot relief pipeline (~1545 lines).
The R20.15 refactor split it into two cohesive siblings:

* :mod:`src.targets.short_trade_target_snapshot_relief_criteria_helpers`
    Criterion-level resolvers (market state, selected close retention,
    breakout trap guard, event catalyst adjustments).
* :mod:`src.targets.short_trade_target_snapshot_relief_resolution_helpers`
    Resolution orchestration (dataclasses, snapshot signal state, prepared
    breakout reliefs, watchlist / score penalty states, final payload).

External callers (e.g. :mod:`src.targets.short_trade_target`,
:mod:`tests.targets.test_target_models`) import the public
:func:`resolve_short_trade_snapshot_reliefs_impl` and the helper
:func:`_apply_ticker_historical_prior_boost` from this module. We re-export
them here so existing imports keep working unchanged.
"""

from __future__ import annotations

# Re-export criterion-level helpers (still used by some orchestration code
# paths and tests; kept here for back-compat).
from src.targets.short_trade_target_snapshot_relief_criteria_helpers import (
    _apply_event_catalyst_threshold_adjustments,
    _build_market_state_threshold_adjustment,
    _build_selected_close_retention_adjustment,
    _build_selected_close_retention_penalty,
    _normalized_reason_codes,
    _resolve_breakout_trap_guard,
    _resolve_market_state_regime_context,
    _resolve_market_state_threshold_adjustment,
    _resolve_selected_close_retention_adjustment,
    _resolve_selected_close_retention_penalty,
    _safe_float,
    _safe_reason_codes,
    BREAKOUT_TRAP_BLOCK_THRESHOLD,
    BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD,
    BREAKOUT_TRAP_PENALTY_WEIGHT,
)
from src.targets.short_trade_target_snapshot_relief_resolution_helpers import (
    _apply_ticker_historical_prior_boost,
    _build_short_trade_snapshot_reliefs_payload,
    _build_short_trade_snapshot_resolution_core_state,
    _build_snapshot_score_payload,
    _build_snapshot_signal_state,
    _finalize_short_trade_snapshot_relief_resolution,
    _finalize_snapshot_threshold_state,
    _resolve_prepared_breakout_reliefs,
    _resolve_score_penalty_state,
    _resolve_short_trade_snapshot_relief_resolution,
    _resolve_snapshot_core_reliefs,
    _resolve_snapshot_threshold_state,
    _resolve_watchlist_penalty_state,
    PreparedBreakoutReliefs,
    resolve_short_trade_snapshot_reliefs_impl,
    ScorePenaltyState,
    SnapshotCoreReliefs,
    SnapshotReliefResolution,
    SnapshotResolutionCoreState,
    SnapshotSignalState,
    SnapshotThresholdState,
    WatchlistPenaltyState,
)

__all__ = [
    # Resolution dataclasses
    "PreparedBreakoutReliefs",
    "ScorePenaltyState",
    "SnapshotCoreReliefs",
    "SnapshotReliefResolution",
    "SnapshotResolutionCoreState",
    "SnapshotSignalState",
    "SnapshotThresholdState",
    "WatchlistPenaltyState",
    # Resolution orchestration helpers
    "_apply_ticker_historical_prior_boost",
    "_build_short_trade_snapshot_reliefs_payload",
    "_build_short_trade_snapshot_resolution_core_state",
    "_build_snapshot_score_payload",
    "_build_snapshot_signal_state",
    "_finalize_short_trade_snapshot_relief_resolution",
    "_finalize_snapshot_threshold_state",
    "_resolve_prepared_breakout_reliefs",
    "_resolve_score_penalty_state",
    "_resolve_short_trade_snapshot_relief_resolution",
    "_resolve_snapshot_core_reliefs",
    "_resolve_snapshot_threshold_state",
    "_resolve_watchlist_penalty_state",
    "resolve_short_trade_snapshot_reliefs_impl",
    # Criterion-level helpers
    "BREAKOUT_TRAP_BLOCK_THRESHOLD",
    "BREAKOUT_TRAP_EXECUTION_BLOCK_THRESHOLD",
    "BREAKOUT_TRAP_PENALTY_WEIGHT",
    "_apply_event_catalyst_threshold_adjustments",
    "_build_market_state_threshold_adjustment",
    "_build_selected_close_retention_adjustment",
    "_build_selected_close_retention_penalty",
    "_normalized_reason_codes",
    "_resolve_breakout_trap_guard",
    "_resolve_market_state_regime_context",
    "_resolve_market_state_threshold_adjustment",
    "_resolve_selected_close_retention_adjustment",
    "_resolve_selected_close_retention_penalty",
    "_safe_float",
    "_safe_reason_codes",
]
