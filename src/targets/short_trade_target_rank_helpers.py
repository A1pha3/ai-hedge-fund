"""Rank-based threshold tightening and decision cap logic.

Extracted from short_trade_target_evaluation_helpers.py to reduce file
size and isolate the rank-cap decision tree (~300 lines).
"""

from __future__ import annotations

import math
from typing import Any

_UNSET_RANK_CAP = object()
_UNSET_RANK_CAP_RATIO = object()


# ---------------------------------------------------------------------------
# Rank threshold tightening constants
# ---------------------------------------------------------------------------

RANK_THRESHOLD_TIGHTENING_START_RANK = 12
RANK_THRESHOLD_TIGHTENING_STEP = 6
RANK_THRESHOLD_TIGHTENING_SELECT_INCREMENT = 0.01
RANK_THRESHOLD_TIGHTENING_NEAR_MISS_INCREMENT = 0.01
RANK_THRESHOLD_TIGHTENING_MAX_INCREMENT = 0.05


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_rank_cap(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _resolve_rank_cap_override_allow_zero(value: Any) -> int | None | object:
    if value is None:
        return _UNSET_RANK_CAP
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return _UNSET_RANK_CAP
    if normalized < 0:
        return _UNSET_RANK_CAP
    return normalized


def _normalize_rank_cap_ratio(value: Any) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0.0:
        return None
    return normalized


def _resolve_rank_cap_ratio_override(value: Any) -> float | None | object:
    if value is None:
        return _UNSET_RANK_CAP_RATIO
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return _UNSET_RANK_CAP_RATIO
    if normalized < 0.0:
        return _UNSET_RANK_CAP_RATIO
    if normalized == 0.0:
        return None
    return normalized


def _resolve_effective_rank_cap(*, hard_cap: int | None, cap_ratio: float | None, rank_population: int | None) -> int | None:
    dynamic_cap: int | None = None
    if cap_ratio is not None and rank_population is not None and rank_population > 0:
        dynamic_cap = max(1, int(math.ceil(float(rank_population) * float(cap_ratio))))
    if dynamic_cap is None:
        return hard_cap
    if hard_cap is None:
        return dynamic_cap
    return max(hard_cap, dynamic_cap)


# ---------------------------------------------------------------------------
# Threshold tightening
# ---------------------------------------------------------------------------


def _resolve_rank_threshold_tightening(rank_hint: int | None) -> dict[str, Any]:
    normalized_rank = int(rank_hint or 0)
    if normalized_rank <= RANK_THRESHOLD_TIGHTENING_START_RANK:
        return {
            "enabled": False,
            "rank_hint": rank_hint,
            "start_rank": RANK_THRESHOLD_TIGHTENING_START_RANK,
            "step": RANK_THRESHOLD_TIGHTENING_STEP,
            "select_threshold_lift": 0.0,
            "near_miss_threshold_lift": 0.0,
        }
    tiers = ((normalized_rank - RANK_THRESHOLD_TIGHTENING_START_RANK - 1) // RANK_THRESHOLD_TIGHTENING_STEP) + 1
    select_lift = min(RANK_THRESHOLD_TIGHTENING_MAX_INCREMENT, tiers * RANK_THRESHOLD_TIGHTENING_SELECT_INCREMENT)
    near_miss_lift = min(RANK_THRESHOLD_TIGHTENING_MAX_INCREMENT, tiers * RANK_THRESHOLD_TIGHTENING_NEAR_MISS_INCREMENT)
    return {
        "enabled": select_lift > 0.0 or near_miss_lift > 0.0,
        "rank_hint": normalized_rank,
        "start_rank": RANK_THRESHOLD_TIGHTENING_START_RANK,
        "step": RANK_THRESHOLD_TIGHTENING_STEP,
        "tiers": tiers,
        "select_threshold_lift": round(select_lift, 4),
        "near_miss_threshold_lift": round(near_miss_lift, 4),
    }


def _apply_rank_based_threshold_tightening(snapshot: dict[str, Any], *, rank_hint: int | None) -> dict[str, Any]:
    adjusted = dict(snapshot)
    tightening = _resolve_rank_threshold_tightening(rank_hint)
    tightening = _apply_regime_admission_recovery(snapshot, tightening=tightening)
    if not bool(tightening["enabled"]):
        adjusted["rank_threshold_tightening"] = tightening
        return adjusted

    base_select = float(snapshot["effective_select_threshold"])
    base_near_miss = float(snapshot["effective_near_miss_threshold"])
    select_lift = float(tightening["select_threshold_lift"])
    near_miss_lift = float(tightening["near_miss_threshold_lift"])
    effective_select = min(0.95, base_select + select_lift)
    effective_near_miss = min(effective_select, base_near_miss + near_miss_lift)

    adjusted["effective_select_threshold"] = effective_select
    adjusted["effective_near_miss_threshold"] = effective_near_miss
    adjusted["rank_threshold_tightening"] = {
        **tightening,
        "base_select_threshold": round(base_select, 4),
        "base_near_miss_threshold": round(base_near_miss, 4),
        "effective_select_threshold": round(effective_select, 4),
        "effective_near_miss_threshold": round(effective_near_miss, 4),
    }
    return adjusted


def _apply_regime_admission_recovery(snapshot: dict[str, Any], *, tightening: dict[str, Any]) -> dict[str, Any]:
    adjusted_tightening = dict(tightening)
    profile = snapshot.get("profile")
    historical_prior = dict(snapshot.get("historical_prior") or {})
    btst_regime_gate = str(historical_prior.get("btst_regime_gate") or "normal_trade").strip().lower() or "normal_trade"
    adjusted_tightening["btst_regime_gate"] = btst_regime_gate
    adjusted_tightening["regime_admission_recovery_applied"] = False
    adjusted_tightening["regime_admission_recovery_relief"] = 0.0
    if not bool(adjusted_tightening.get("enabled")) or profile is None or not bool(getattr(profile, "regime_admission_recovery_enabled", False)):
        return adjusted_tightening

    max_relief = min(0.02, max(0.0, float(getattr(profile, "regime_admission_recovery_max_relief", 0.0) or 0.0)))
    if max_relief <= 0.0:
        return adjusted_tightening
    if btst_regime_gate == "aggressive_trade":
        configured_relief = float(getattr(profile, "regime_admission_recovery_aggressive_trade_relief", 0.0) or 0.0)
    elif btst_regime_gate == "normal_trade":
        configured_relief = float(getattr(profile, "regime_admission_recovery_normal_trade_relief", 0.0) or 0.0)
    else:
        configured_relief = 0.0
    relief = min(
        max_relief,
        max(0.0, configured_relief),
        float(adjusted_tightening.get("select_threshold_lift") or 0.0),
        float(adjusted_tightening.get("near_miss_threshold_lift") or 0.0),
    )
    if relief <= 0.0:
        return adjusted_tightening

    adjusted_tightening["select_threshold_lift"] = round(max(0.0, float(adjusted_tightening["select_threshold_lift"]) - relief), 4)
    adjusted_tightening["near_miss_threshold_lift"] = round(max(0.0, float(adjusted_tightening["near_miss_threshold_lift"]) - relief), 4)
    adjusted_tightening["enabled"] = bool(adjusted_tightening["select_threshold_lift"] > 0.0 or adjusted_tightening["near_miss_threshold_lift"] > 0.0)
    adjusted_tightening["regime_admission_recovery_applied"] = True
    adjusted_tightening["regime_admission_recovery_relief"] = round(relief, 4)
    return adjusted_tightening


# ---------------------------------------------------------------------------
# Rank decision cap
# ---------------------------------------------------------------------------


def _resolve_rank_decision_cap(
    snapshot: dict[str, Any],
    *,
    rank_hint: int | None,
    rank_population: int | None,
    candidate_source: str | None = None,
    candidate_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    normalized_rank = int(rank_hint or 0)
    normalized_population = int(rank_population or 0) or None
    profile = snapshot.get("profile")
    normalized_candidate_source = str(candidate_source or "").strip().lower()
    normalized_reason_codes = {str(code or "").strip().lower() for code in list(candidate_reason_codes or []) if str(code or "").strip()}
    breakout_freshness = float(snapshot.get("breakout_freshness") or 0.0)
    trend_acceleration = float(snapshot.get("trend_acceleration") or 0.0)
    sector_resonance = float(snapshot.get("sector_resonance") or 0.0)
    close_strength = float(snapshot.get("close_strength") or 0.0)
    catalyst_freshness = float(snapshot.get("catalyst_freshness") or 0.0)
    upstream_shadow_catalyst_relief_applied = bool(snapshot.get("upstream_shadow_catalyst_relief_applied"))
    catalyst_theme_source_specific_rank_cap_trend_acceleration_min = max(
        0.0,
        float(getattr(profile, "catalyst_theme_source_specific_rank_cap_trend_acceleration_min", 0.0) or 0.0),
    )
    catalyst_theme_source_specific_rank_cap_sector_resonance_min = max(
        0.0,
        float(getattr(profile, "catalyst_theme_source_specific_rank_cap_sector_resonance_min", 0.0) or 0.0),
    )
    catalyst_theme_source_specific_rank_cap_close_strength_min = max(
        0.0,
        float(getattr(profile, "catalyst_theme_source_specific_rank_cap_close_strength_min", 0.0) or 0.0),
    )
    catalyst_theme_source_specific_rank_cap_guard_active = normalized_candidate_source == "catalyst_theme" and "catalyst_theme_short_trade_carryover_candidate" not in normalized_reason_codes
    catalyst_theme_source_specific_rank_cap_trend_acceleration_pass = trend_acceleration >= catalyst_theme_source_specific_rank_cap_trend_acceleration_min
    catalyst_theme_source_specific_rank_cap_sector_resonance_pass = sector_resonance >= catalyst_theme_source_specific_rank_cap_sector_resonance_min
    catalyst_theme_source_specific_rank_cap_close_strength_pass = close_strength >= catalyst_theme_source_specific_rank_cap_close_strength_min
    catalyst_theme_source_specific_caps_enabled = catalyst_theme_source_specific_rank_cap_guard_active and catalyst_theme_source_specific_rank_cap_trend_acceleration_pass and catalyst_theme_source_specific_rank_cap_sector_resonance_pass and catalyst_theme_source_specific_rank_cap_close_strength_pass
    layer_c_watchlist_source_specific_cap_guard_active = normalized_candidate_source == "layer_c_watchlist"
    layer_c_watchlist_selected_rank_cap = _resolve_rank_cap_override_allow_zero(getattr(profile, "layer_c_watchlist_selected_rank_cap", None))
    layer_c_watchlist_near_miss_rank_cap = _resolve_rank_cap_override_allow_zero(getattr(profile, "layer_c_watchlist_near_miss_rank_cap", None))
    layer_c_watchlist_source_specific_cap_has_override = layer_c_watchlist_selected_rank_cap is not _UNSET_RANK_CAP or layer_c_watchlist_near_miss_rank_cap is not _UNSET_RANK_CAP
    selected_rank_cap_hard = _normalize_rank_cap(getattr(profile, "selected_rank_cap", 0))
    near_miss_rank_cap_hard = _normalize_rank_cap(getattr(profile, "near_miss_rank_cap", 0))
    selected_rank_cap_ratio = _normalize_rank_cap_ratio(getattr(profile, "selected_rank_cap_ratio", 0.0))
    near_miss_rank_cap_ratio = _normalize_rank_cap_ratio(getattr(profile, "near_miss_rank_cap_ratio", 0.0))
    liquidity_shadow_selected_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "liquidity_shadow_selected_rank_cap_ratio", None))
    liquidity_shadow_near_miss_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "liquidity_shadow_near_miss_rank_cap_ratio", None))
    liquidity_shadow_source_specific_rank_cap_require_relief_applied = bool(getattr(profile, "liquidity_shadow_source_specific_rank_cap_require_relief_applied", True))
    upstream_shadow_source_specific_rank_cap_trend_acceleration_min = max(
        0.0,
        float(getattr(profile, "upstream_shadow_source_specific_rank_cap_trend_acceleration_min", 0.0) or 0.0),
    )
    upstream_shadow_source_specific_rank_cap_close_strength_min = max(
        0.0,
        float(getattr(profile, "upstream_shadow_source_specific_rank_cap_close_strength_min", 0.0) or 0.0),
    )
    shadow_source_specific_rank_cap_guard_active = normalized_candidate_source in {"upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"} and "upstream_shadow_release_candidate" in normalized_reason_codes
    shadow_source_specific_rank_cap_relief_applied = upstream_shadow_catalyst_relief_applied
    upstream_shadow_source_specific_rank_cap_trend_acceleration_pass = trend_acceleration >= upstream_shadow_source_specific_rank_cap_trend_acceleration_min
    upstream_shadow_source_specific_rank_cap_close_strength_pass = close_strength >= upstream_shadow_source_specific_rank_cap_close_strength_min
    upstream_shadow_source_specific_rank_cap_support_pass = upstream_shadow_source_specific_rank_cap_trend_acceleration_pass and upstream_shadow_source_specific_rank_cap_close_strength_pass
    shadow_source_specific_rank_cap_has_override = liquidity_shadow_selected_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO or liquidity_shadow_near_miss_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO
    shadow_source_specific_caps_enabled = shadow_source_specific_rank_cap_guard_active and shadow_source_specific_rank_cap_has_override and upstream_shadow_source_specific_rank_cap_support_pass and (shadow_source_specific_rank_cap_relief_applied or not liquidity_shadow_source_specific_rank_cap_require_relief_applied)
    if shadow_source_specific_caps_enabled:
        if liquidity_shadow_selected_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            selected_rank_cap_ratio = liquidity_shadow_selected_rank_cap_ratio
        if liquidity_shadow_near_miss_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            near_miss_rank_cap_ratio = liquidity_shadow_near_miss_rank_cap_ratio
    if catalyst_theme_source_specific_caps_enabled:
        catalyst_theme_selected_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "catalyst_theme_selected_rank_cap_ratio", None))
        if catalyst_theme_selected_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            selected_rank_cap_ratio = catalyst_theme_selected_rank_cap_ratio
        catalyst_theme_near_miss_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "catalyst_theme_near_miss_rank_cap_ratio", None))
        if catalyst_theme_near_miss_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            near_miss_rank_cap_ratio = catalyst_theme_near_miss_rank_cap_ratio
    if layer_c_watchlist_source_specific_cap_guard_active:
        if layer_c_watchlist_selected_rank_cap is not _UNSET_RANK_CAP:
            selected_rank_cap_hard = layer_c_watchlist_selected_rank_cap
            selected_rank_cap_ratio = None
        if layer_c_watchlist_near_miss_rank_cap is not _UNSET_RANK_CAP:
            near_miss_rank_cap_hard = layer_c_watchlist_near_miss_rank_cap
            near_miss_rank_cap_ratio = None
    selected_rank_cap = _resolve_effective_rank_cap(
        hard_cap=selected_rank_cap_hard,
        cap_ratio=selected_rank_cap_ratio,
        rank_population=normalized_population,
    )
    near_miss_rank_cap = _resolve_effective_rank_cap(
        hard_cap=near_miss_rank_cap_hard,
        cap_ratio=near_miss_rank_cap_ratio,
        rank_population=normalized_population,
    )
    selected_cap_exceeded_raw = bool(selected_rank_cap is not None and normalized_rank > selected_rank_cap)
    near_miss_cap_exceeded = bool(near_miss_rank_cap is not None and normalized_rank > near_miss_rank_cap)

    selected_rank_cap_relief_score_margin_min = max(0.0, float(getattr(profile, "selected_rank_cap_relief_score_margin_min", 0.0) or 0.0))
    selected_rank_cap_relief_rank_buffer_hard = _normalize_rank_cap(getattr(profile, "selected_rank_cap_relief_rank_buffer", 0))
    selected_rank_cap_relief_rank_buffer_ratio = _normalize_rank_cap_ratio(getattr(profile, "selected_rank_cap_relief_rank_buffer_ratio", 0.0))
    selected_rank_cap_relief_rank_buffer = _resolve_effective_rank_cap(
        hard_cap=selected_rank_cap_relief_rank_buffer_hard,
        cap_ratio=selected_rank_cap_relief_rank_buffer_ratio,
        rank_population=normalized_population,
    )
    selected_rank_cap_relief_sector_resonance_min = max(0.0, float(getattr(profile, "selected_rank_cap_relief_sector_resonance_min", 0.0) or 0.0))
    selected_rank_cap_relief_close_strength_max = min(
        1.0,
        max(0.0, float(getattr(profile, "selected_rank_cap_relief_close_strength_max", 1.0) if getattr(profile, "selected_rank_cap_relief_close_strength_max", 1.0) is not None else 1.0)),
    )
    selected_rank_cap_relief_require_confirmed_breakout = bool(getattr(profile, "selected_rank_cap_relief_require_confirmed_breakout", False))
    selected_rank_cap_relief_require_t_plus_2_candidate = bool(getattr(profile, "selected_rank_cap_relief_require_t_plus_2_candidate", False))
    selected_rank_cap_relief_allow_risk_off = bool(getattr(profile, "selected_rank_cap_relief_allow_risk_off", True))
    selected_rank_cap_relief_allow_crisis = bool(getattr(profile, "selected_rank_cap_relief_allow_crisis", True))
    selected_rank_cap_relief_catalyst_theme_carryover_support_enabled = bool(getattr(profile, "selected_rank_cap_relief_catalyst_theme_carryover_support_enabled", False))
    selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count = max(
        0,
        int(getattr(profile, "selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count", 0) or 0),
    )
    selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min = max(
        0.0,
        float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min", 0.0) or 0.0),
    )

    selected_rank_cap_relief_cap: int | None = None
    if selected_rank_cap is not None and selected_rank_cap_relief_rank_buffer is not None:
        selected_rank_cap_relief_cap = int(selected_rank_cap + selected_rank_cap_relief_rank_buffer)

    score_target = float(snapshot.get("score_target") or 0.0)
    effective_select_threshold = float(snapshot.get("effective_select_threshold") or 0.0)
    selected_rank_cap_relief_score_margin = round(score_target - effective_select_threshold, 4)
    selected_rank_cap_relief_score_pass = selected_rank_cap_relief_score_margin >= selected_rank_cap_relief_score_margin_min

    selected_breakout_gate_pass = breakout_freshness >= float(getattr(profile, "selected_breakout_freshness_min", 0.0)) and trend_acceleration >= float(getattr(profile, "selected_trend_acceleration_min", 0.0))
    selected_rank_cap_relief_breakout_pass = (not selected_rank_cap_relief_require_confirmed_breakout) or selected_breakout_gate_pass

    selected_rank_cap_relief_sector_resonance_pass = sector_resonance >= selected_rank_cap_relief_sector_resonance_min

    selected_rank_cap_relief_close_strength_pass = close_strength <= selected_rank_cap_relief_close_strength_max

    t_plus_2_continuation_candidate = dict(snapshot.get("t_plus_2_continuation_candidate") or {})
    selected_rank_cap_relief_t_plus_2_support_applied = bool(t_plus_2_continuation_candidate.get("applied"))
    selected_rank_cap_relief_t_plus_2_pass = (not selected_rank_cap_relief_require_t_plus_2_candidate) or bool(t_plus_2_continuation_candidate.get("applied"))

    market_state_threshold_adjustment = dict(snapshot.get("market_state_threshold_adjustment") or {})
    selected_rank_cap_relief_market_risk_source = "market_state_threshold_adjustment"
    selected_rank_cap_relief_market_risk_level = str(market_state_threshold_adjustment.get("risk_level") or "unknown").strip().lower()
    volatility_regime = float(snapshot.get("volatility_regime") or 0.0)
    atr_ratio = float(snapshot.get("atr_ratio") or 0.0)
    if selected_rank_cap_relief_market_risk_level not in {"normal", "risk_off", "crisis"}:
        selected_rank_cap_relief_market_risk_source = "volatility_fallback"
        if volatility_regime >= 1.35 or atr_ratio >= 0.11:
            selected_rank_cap_relief_market_risk_level = "crisis"
        elif volatility_regime >= 1.15 or atr_ratio >= 0.085:
            selected_rank_cap_relief_market_risk_level = "risk_off"
        elif volatility_regime > 0.0 or atr_ratio > 0.0:
            selected_rank_cap_relief_market_risk_level = "normal"
        else:
            selected_rank_cap_relief_market_risk_level = "unknown"
            selected_rank_cap_relief_market_risk_source = "unknown"
    selected_rank_cap_relief_market_risk_pass = not ((selected_rank_cap_relief_market_risk_level == "risk_off" and not selected_rank_cap_relief_allow_risk_off) or (selected_rank_cap_relief_market_risk_level == "crisis" and not selected_rank_cap_relief_allow_crisis))

    profitability_hard_cliff_boundary_relief = dict(snapshot.get("profitability_hard_cliff_boundary_relief") or {})
    profitability_hard_cliff_boundary_gate_hits = dict(profitability_hard_cliff_boundary_relief.get("gate_hits") or {})
    selected_rank_cap_relief_boundary_guard_active = normalized_candidate_source == "short_trade_boundary" and bool(profitability_hard_cliff_boundary_relief.get("enabled")) and bool(profitability_hard_cliff_boundary_gate_hits.get("profitability_hard_cliff"))
    selected_rank_cap_relief_boundary_pass = (not selected_rank_cap_relief_boundary_guard_active) or bool(profitability_hard_cliff_boundary_relief.get("applied"))

    historical_prior = dict(snapshot.get("historical_prior") or {})
    selected_rank_cap_relief_catalyst_theme_carryover_candidate = normalized_candidate_source == "catalyst_theme" and "catalyst_theme_short_trade_carryover_candidate" in normalized_reason_codes
    selected_rank_cap_relief_catalyst_theme_carryover_guard_active = selected_rank_cap_relief_catalyst_theme_carryover_support_enabled and selected_rank_cap_relief_catalyst_theme_carryover_candidate
    selected_rank_cap_relief_catalyst_theme_carryover_historical_evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    selected_rank_cap_relief_catalyst_theme_carryover_historical_support_pass = selected_rank_cap_relief_catalyst_theme_carryover_historical_evaluable_count >= selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count
    selected_rank_cap_relief_catalyst_theme_carryover_catalyst_support_pass = catalyst_freshness >= selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min
    selected_rank_cap_relief_catalyst_theme_carryover_t_plus_2_support_pass = selected_rank_cap_relief_t_plus_2_support_applied
    selected_rank_cap_relief_catalyst_theme_carryover_support_pass = (not selected_rank_cap_relief_catalyst_theme_carryover_guard_active) or selected_rank_cap_relief_catalyst_theme_carryover_historical_support_pass or selected_rank_cap_relief_catalyst_theme_carryover_catalyst_support_pass or selected_rank_cap_relief_catalyst_theme_carryover_t_plus_2_support_pass
    selected_rank_cap_relief_catalyst_theme_research_enabled = bool(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_enabled", False))
    selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min = max(
        0.0,
        float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min", 0.0) or 0.0),
    )
    selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min = max(
        0.0,
        float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min", 0.0) or 0.0),
    )
    selected_rank_cap_relief_catalyst_theme_research_close_strength_max = min(
        1.0,
        max(0.0, float(getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_close_strength_max", 1.0) if getattr(profile, "selected_rank_cap_relief_catalyst_theme_research_close_strength_max", 1.0) is not None else 1.0)),
    )
    selected_rank_cap_relief_catalyst_theme_research_candidate = normalized_candidate_source == "catalyst_theme" and "catalyst_theme_research_candidate" in normalized_reason_codes and "catalyst_theme_short_trade_carryover_candidate" not in normalized_reason_codes
    selected_rank_cap_relief_catalyst_theme_research_guard_active = selected_rank_cap_relief_catalyst_theme_research_enabled and selected_rank_cap_relief_catalyst_theme_research_candidate
    selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_pass = trend_acceleration >= selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min
    selected_rank_cap_relief_catalyst_theme_research_sector_resonance_pass = sector_resonance >= selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min
    selected_rank_cap_relief_catalyst_theme_research_close_strength_pass = close_strength <= selected_rank_cap_relief_catalyst_theme_research_close_strength_max
    selected_rank_cap_relief_catalyst_theme_research_support_pass = (not selected_rank_cap_relief_catalyst_theme_research_guard_active) or (selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_pass and selected_rank_cap_relief_catalyst_theme_research_sector_resonance_pass and selected_rank_cap_relief_catalyst_theme_research_close_strength_pass)

    selected_rank_cap_relief_within_buffer = bool(selected_rank_cap_relief_cap is not None and normalized_rank > 0 and normalized_rank <= selected_rank_cap_relief_cap)
    selected_cap_soft_relief_applied = bool(
        selected_cap_exceeded_raw
        and selected_rank_cap_relief_within_buffer
        and selected_rank_cap_relief_score_pass
        and selected_rank_cap_relief_breakout_pass
        and selected_rank_cap_relief_sector_resonance_pass
        and selected_rank_cap_relief_close_strength_pass
        and selected_rank_cap_relief_t_plus_2_pass
        and selected_rank_cap_relief_market_risk_pass
        and selected_rank_cap_relief_boundary_pass
        and selected_rank_cap_relief_catalyst_theme_carryover_support_pass
        and selected_rank_cap_relief_catalyst_theme_research_support_pass
    )
    selected_cap_exceeded_effective = bool(selected_cap_exceeded_raw and not selected_cap_soft_relief_applied)

    return {
        "enabled": bool(selected_rank_cap is not None or near_miss_rank_cap is not None or selected_rank_cap_ratio is not None or near_miss_rank_cap_ratio is not None),
        "candidate_source": normalized_candidate_source or None,
        "liquidity_shadow_selected_rank_cap_ratio": None if liquidity_shadow_selected_rank_cap_ratio is _UNSET_RANK_CAP_RATIO else liquidity_shadow_selected_rank_cap_ratio,
        "liquidity_shadow_near_miss_rank_cap_ratio": None if liquidity_shadow_near_miss_rank_cap_ratio is _UNSET_RANK_CAP_RATIO else liquidity_shadow_near_miss_rank_cap_ratio,
        "liquidity_shadow_source_specific_rank_cap_require_relief_applied": liquidity_shadow_source_specific_rank_cap_require_relief_applied,
        "shadow_source_specific_rank_cap_guard_active": shadow_source_specific_rank_cap_guard_active,
        "shadow_source_specific_rank_cap_has_override": shadow_source_specific_rank_cap_has_override,
        "shadow_source_specific_rank_cap_relief_applied": shadow_source_specific_rank_cap_relief_applied,
        "upstream_shadow_source_specific_rank_cap_trend_acceleration_min": round(upstream_shadow_source_specific_rank_cap_trend_acceleration_min, 4),
        "upstream_shadow_source_specific_rank_cap_close_strength_min": round(upstream_shadow_source_specific_rank_cap_close_strength_min, 4),
        "upstream_shadow_source_specific_rank_cap_trend_acceleration_pass": upstream_shadow_source_specific_rank_cap_trend_acceleration_pass,
        "upstream_shadow_source_specific_rank_cap_close_strength_pass": upstream_shadow_source_specific_rank_cap_close_strength_pass,
        "upstream_shadow_source_specific_rank_cap_support_pass": upstream_shadow_source_specific_rank_cap_support_pass,
        "shadow_source_specific_caps_enabled": shadow_source_specific_caps_enabled,
        "catalyst_theme_source_specific_rank_cap_guard_active": catalyst_theme_source_specific_rank_cap_guard_active,
        "catalyst_theme_source_specific_rank_cap_trend_acceleration_min": round(catalyst_theme_source_specific_rank_cap_trend_acceleration_min, 4),
        "catalyst_theme_source_specific_rank_cap_sector_resonance_min": round(catalyst_theme_source_specific_rank_cap_sector_resonance_min, 4),
        "catalyst_theme_source_specific_rank_cap_close_strength_min": round(catalyst_theme_source_specific_rank_cap_close_strength_min, 4),
        "catalyst_theme_source_specific_rank_cap_trend_acceleration_pass": catalyst_theme_source_specific_rank_cap_trend_acceleration_pass,
        "catalyst_theme_source_specific_rank_cap_sector_resonance_pass": catalyst_theme_source_specific_rank_cap_sector_resonance_pass,
        "catalyst_theme_source_specific_rank_cap_close_strength_pass": catalyst_theme_source_specific_rank_cap_close_strength_pass,
        "catalyst_theme_source_specific_caps_enabled": catalyst_theme_source_specific_caps_enabled,
        "layer_c_watchlist_source_specific_cap_guard_active": layer_c_watchlist_source_specific_cap_guard_active,
        "layer_c_watchlist_source_specific_cap_has_override": layer_c_watchlist_source_specific_cap_has_override,
        "layer_c_watchlist_selected_rank_cap": None if layer_c_watchlist_selected_rank_cap is _UNSET_RANK_CAP else layer_c_watchlist_selected_rank_cap,
        "layer_c_watchlist_near_miss_rank_cap": None if layer_c_watchlist_near_miss_rank_cap is _UNSET_RANK_CAP else layer_c_watchlist_near_miss_rank_cap,
        "rank_hint": normalized_rank if normalized_rank > 0 else None,
        "rank_population": normalized_population,
        "selected_rank_cap_hard": selected_rank_cap_hard,
        "near_miss_rank_cap_hard": near_miss_rank_cap_hard,
        "selected_rank_cap_ratio": selected_rank_cap_ratio,
        "near_miss_rank_cap_ratio": near_miss_rank_cap_ratio,
        "selected_rank_cap": selected_rank_cap,
        "near_miss_rank_cap": near_miss_rank_cap,
        "selected_cap_exceeded": selected_cap_exceeded_raw,
        "selected_cap_exceeded_effective": selected_cap_exceeded_effective,
        "near_miss_cap_exceeded": near_miss_cap_exceeded,
        "selected_cap_soft_relief_applied": selected_cap_soft_relief_applied,
        "selected_rank_cap_relief_score_margin_min": round(selected_rank_cap_relief_score_margin_min, 4),
        "selected_rank_cap_relief_score_margin": selected_rank_cap_relief_score_margin,
        "selected_rank_cap_relief_rank_buffer_hard": selected_rank_cap_relief_rank_buffer_hard,
        "selected_rank_cap_relief_rank_buffer_ratio": selected_rank_cap_relief_rank_buffer_ratio,
        "selected_rank_cap_relief_rank_buffer": selected_rank_cap_relief_rank_buffer,
        "selected_rank_cap_relief_sector_resonance_min": round(selected_rank_cap_relief_sector_resonance_min, 4),
        "selected_rank_cap_relief_close_strength_max": round(selected_rank_cap_relief_close_strength_max, 4),
        "selected_rank_cap_relief_cap": selected_rank_cap_relief_cap,
        "selected_rank_cap_relief_within_buffer": selected_rank_cap_relief_within_buffer,
        "selected_rank_cap_relief_score_pass": selected_rank_cap_relief_score_pass,
        "selected_rank_cap_relief_require_confirmed_breakout": selected_rank_cap_relief_require_confirmed_breakout,
        "selected_rank_cap_relief_breakout_pass": selected_rank_cap_relief_breakout_pass,
        "selected_rank_cap_relief_sector_resonance_pass": selected_rank_cap_relief_sector_resonance_pass,
        "selected_rank_cap_relief_close_strength_pass": selected_rank_cap_relief_close_strength_pass,
        "selected_rank_cap_relief_require_t_plus_2_candidate": selected_rank_cap_relief_require_t_plus_2_candidate,
        "selected_rank_cap_relief_t_plus_2_pass": selected_rank_cap_relief_t_plus_2_pass,
        "selected_rank_cap_relief_t_plus_2_support_applied": selected_rank_cap_relief_t_plus_2_support_applied,
        "selected_rank_cap_relief_allow_risk_off": selected_rank_cap_relief_allow_risk_off,
        "selected_rank_cap_relief_allow_crisis": selected_rank_cap_relief_allow_crisis,
        "selected_rank_cap_relief_market_risk_source": selected_rank_cap_relief_market_risk_source,
        "selected_rank_cap_relief_market_risk_level": selected_rank_cap_relief_market_risk_level,
        "selected_rank_cap_relief_market_risk_pass": selected_rank_cap_relief_market_risk_pass,
        "selected_rank_cap_relief_boundary_guard_active": selected_rank_cap_relief_boundary_guard_active,
        "selected_rank_cap_relief_boundary_pass": selected_rank_cap_relief_boundary_pass,
        "selected_rank_cap_relief_catalyst_theme_carryover_support_enabled": selected_rank_cap_relief_catalyst_theme_carryover_support_enabled,
        "selected_rank_cap_relief_catalyst_theme_carryover_guard_active": selected_rank_cap_relief_catalyst_theme_carryover_guard_active,
        "selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count": selected_rank_cap_relief_catalyst_theme_carryover_min_evaluable_count,
        "selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min": round(selected_rank_cap_relief_catalyst_theme_carryover_catalyst_freshness_min, 4),
        "selected_rank_cap_relief_catalyst_theme_carryover_historical_evaluable_count": selected_rank_cap_relief_catalyst_theme_carryover_historical_evaluable_count,
        "selected_rank_cap_relief_catalyst_theme_carryover_historical_support_pass": selected_rank_cap_relief_catalyst_theme_carryover_historical_support_pass,
        "selected_rank_cap_relief_catalyst_theme_carryover_catalyst_support_pass": selected_rank_cap_relief_catalyst_theme_carryover_catalyst_support_pass,
        "selected_rank_cap_relief_catalyst_theme_carryover_t_plus_2_support_pass": selected_rank_cap_relief_catalyst_theme_carryover_t_plus_2_support_pass,
        "selected_rank_cap_relief_catalyst_theme_carryover_support_pass": selected_rank_cap_relief_catalyst_theme_carryover_support_pass,
        "selected_rank_cap_relief_catalyst_theme_research_enabled": selected_rank_cap_relief_catalyst_theme_research_enabled,
        "selected_rank_cap_relief_catalyst_theme_research_guard_active": selected_rank_cap_relief_catalyst_theme_research_guard_active,
        "selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min": round(selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_min, 4),
        "selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min": round(selected_rank_cap_relief_catalyst_theme_research_sector_resonance_min, 4),
        "selected_rank_cap_relief_catalyst_theme_research_close_strength_max": round(selected_rank_cap_relief_catalyst_theme_research_close_strength_max, 4),
        "selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_pass": selected_rank_cap_relief_catalyst_theme_research_trend_acceleration_pass,
        "selected_rank_cap_relief_catalyst_theme_research_sector_resonance_pass": selected_rank_cap_relief_catalyst_theme_research_sector_resonance_pass,
        "selected_rank_cap_relief_catalyst_theme_research_close_strength_pass": selected_rank_cap_relief_catalyst_theme_research_close_strength_pass,
        "selected_rank_cap_relief_catalyst_theme_research_support_pass": selected_rank_cap_relief_catalyst_theme_research_support_pass,
    }


def _apply_rank_based_decision_cap(
    snapshot: dict[str, Any],
    *,
    rank_hint: int | None,
    rank_population: int | None,
    candidate_source: str | None = None,
    candidate_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    adjusted = dict(snapshot)
    adjusted["rank_decision_cap"] = _resolve_rank_decision_cap(
        snapshot,
        rank_hint=rank_hint,
        rank_population=rank_population,
        candidate_source=candidate_source,
        candidate_reason_codes=candidate_reason_codes,
    )
    return adjusted


# ---------------------------------------------------------------------------
# Runner composite score
# ---------------------------------------------------------------------------

# Task T (Round 9): Sector resonance phase constants for non-linear "主升浪" amplification.
# Stocks with strong sector alignment (> PHASE_BOOST_THRESHOLD) receive a convex bonus that
# rewards "主升浪" participants; stocks below PHASE_PENALTY_THRESHOLD are penalised more
# aggressively than the neutral 0.5 default to avoid contra-sector stale moves.
_SECTOR_PHASE_BOOST_THRESHOLD: float = 0.65  # convex amplification begins above this
_SECTOR_PHASE_PENALTY_THRESHOLD: float = 0.35  # progressive penalty below this
_SECTOR_PHASE_BOOST_GAIN: float = 0.40  # additional gain at sector_resonance == 1.0
_SECTOR_PHASE_PENALTY_FACTOR: float = 0.60  # multiplier applied in the penalty zone


def compute_sector_resonance_phase_score(raw_sector: float) -> float:
    """Return a phase-amplified sector resonance score in [0.0, 1.0].

    Unlike the raw linear mapping used previously, this function applies a non-linear
    transform that reflects the qualitative difference between a stock in a confirmed
    "主升浪" (strong rally phase) versus one with weak or ambiguous sector alignment:

    * ``raw_sector > _SECTOR_PHASE_BOOST_THRESHOLD``: convex amplification — each
      additional point of sector resonance yields a larger contribution, rewarding
      stocks deep inside a sector rally.
    * ``raw_sector < _SECTOR_PHASE_PENALTY_THRESHOLD``: progressive penalty — scores
      are compressed further toward 0.0 to avoid contra-sector noise entering the
      composite.
    * Otherwise: linear pass-through identical to the legacy behaviour.

    Args:
        raw_sector: Raw sector resonance value from the snapshot in [0.0, 1.0].

    Returns:
        Phase-amplified score in [0.0, 1.0].
    """
    s = min(max(raw_sector, 0.0), 1.0)
    if s > _SECTOR_PHASE_BOOST_THRESHOLD:
        # Convex boost: linear base + quadratic amplification above threshold.
        above = s - _SECTOR_PHASE_BOOST_THRESHOLD
        span = 1.0 - _SECTOR_PHASE_BOOST_THRESHOLD
        boost = _SECTOR_PHASE_BOOST_GAIN * (above / span) ** 2
        phase_score = min(s + boost, 1.0)
    elif s < _SECTOR_PHASE_PENALTY_THRESHOLD:
        # Progressive penalty: scale down toward 0 as resonance weakens.
        phase_score = s * _SECTOR_PHASE_PENALTY_FACTOR
    else:
        phase_score = s
    return round(phase_score, 4)


def compute_runner_composite_score(snapshot: dict[str, Any], profile: Any = None) -> float:
    """Runner-priority composite score combining key runner signals.

    Weights are read from the profile when provided (fields: runner_composite_score_breakout_weight,
    runner_composite_score_trend_weight, runner_composite_score_volume_weight,
    runner_composite_score_catalyst_weight, runner_composite_score_close_strength_weight,
    runner_composite_score_volatility_regime_weight, runner_composite_score_sector_resonance_weight,
    runner_composite_score_quiet_breakout_weight, runner_composite_score_net_inflow_weight,
    runner_composite_score_volume_price_divergence_weight, runner_composite_score_t0_tail_weight,
    runner_composite_score_momentum_alignment_weight,
    runner_composite_score_momentum_confirmation_weight, runner_composite_score_volume_momentum_weight,
    runner_composite_score_rs_sector_rank_weight).
    Falls back to defaults when profile is absent:
      breakout_freshness=0.40, trend_acceleration=0.30,
      volume_expansion_quality=0.20, catalyst_freshness=0.10, close_strength=0.10,
      volatility_regime=0.0 (disabled by default), sector_resonance=0.0 (disabled by default),
      quiet_breakout=0.0 (disabled by default).

    Weights are automatically normalized by their sum so the score is always in [0.0, 1.0]
    regardless of whether the provided weights happen to sum to 1.0.  This makes grid-search
    combinations safe even when individual weight axes do not sum to a fixed total.

    Returns a float in [0.0, 1.0] representing relative runner quality.
    Higher scores indicate stronger multi-day runner potential.
    ``close_strength`` captures intraday buying pressure (close / day-high ratio) — stocks
    closing within the top of their daily range show meaningfully higher next-day gap-up rates.
    ``volatility_regime_score`` penalizes high-volatility environments: score=1.0 at normal
    regime (volatility_regime ≤ 1.0, atr_ratio ≤ 0.065), decaying to 0.0 at crisis thresholds
    (volatility_regime ≥ 1.35, atr_ratio ≥ 0.11).  Neutral 0.5 when no volatility data present.
    ``sector_resonance_score`` rewards sector-aligned runners via phase-amplified scoring
    (Task T, Round 9): stocks in a confirmed 主升浪 phase (sector_resonance > 0.65) receive a
    convex bonus; stocks in a contra-sector phase (<0.35) are penalised more aggressively.
    Neutral 0.5 when no sector data present.
    ``quiet_breakout_score`` (Task 5, Round 10): cross-product of breakout freshness and calm
    volatility — breakout_freshness × (1 − volatility_risk_factor).  High-momentum + low-volatility
    "安静突破" setups that empirically show the highest BTST success rates.  Degrades to raw
    breakout_freshness when volatility data is absent so it never penalises the composite score.
    """
    breakout = float(snapshot.get("breakout_freshness") or 0.0)
    trend = float(snapshot.get("trend_acceleration") or 0.0)
    volume = float(snapshot.get("volume_expansion_quality") or 0.0)
    catalyst = float(snapshot.get("catalyst_freshness") or 0.0)
    close_str = float(snapshot.get("close_strength") or 0.0)
    volatility_regime = float(snapshot.get("volatility_regime") or 0.0)
    atr_ratio = float(snapshot.get("atr_ratio") or 0.0)
    if volatility_regime <= 0.0 and atr_ratio <= 0.0:
        volatility_regime_score = 0.5
        volatility_risk_factor = 0.0  # neutral — no data; cross-term defaults to raw breakout
    else:
        vr_risk = max((volatility_regime - 1.0) / 0.35, 0.0) if volatility_regime > 0 else 0.0
        atr_risk = max((atr_ratio - 0.065) / 0.045, 0.0) if atr_ratio > 0 else 0.0
        volatility_risk_factor = min(max(vr_risk, atr_risk), 1.0)
        volatility_regime_score = round(1.0 - volatility_risk_factor, 4)
    # Task 5 (Round 10): "quiet breakout" cross-factor — breakout freshness amplified by low
    # volatility.  Formula: breakout × (1 − volatility_risk_factor), clipped to [0, 1].
    # When volatility data is absent (risk_factor=0) the score degrades to raw breakout_freshness,
    # so it is always a non-negative contribution and never penalises the composite score.
    quiet_breakout_score = round(breakout * (1.0 - volatility_risk_factor), 4)
    raw_sector = float(snapshot.get("sector_resonance") or 0.0)
    # Task T (Round 9): use phase-amplified score instead of raw linear mapping.
    sector_resonance_score = compute_sector_resonance_phase_score(raw_sector) if raw_sector > 0.0 else 0.5
    # NOTE: 0.0 是合法权重 (禁用某因子), 不能用 `or W` 静默覆盖。
    w_b = float(getattr(profile, "runner_composite_score_breakout_weight", 0.40) if getattr(profile, "runner_composite_score_breakout_weight", 0.40) is not None else 0.40)
    w_t = float(getattr(profile, "runner_composite_score_trend_weight", 0.30) if getattr(profile, "runner_composite_score_trend_weight", 0.30) is not None else 0.30)
    w_v = float(getattr(profile, "runner_composite_score_volume_weight", 0.20) if getattr(profile, "runner_composite_score_volume_weight", 0.20) is not None else 0.20)
    w_c = float(getattr(profile, "runner_composite_score_catalyst_weight", 0.10) if getattr(profile, "runner_composite_score_catalyst_weight", 0.10) is not None else 0.10)
    w_cs = float(getattr(profile, "runner_composite_score_close_strength_weight", 0.10) if getattr(profile, "runner_composite_score_close_strength_weight", 0.10) is not None else 0.10)
    w_vr = float(getattr(profile, "runner_composite_score_volatility_regime_weight", 0.0) or 0.0)
    w_sr = float(getattr(profile, "runner_composite_score_sector_resonance_weight", 0.0) or 0.0)
    w_qb = float(getattr(profile, "runner_composite_score_quiet_breakout_weight", 0.0) or 0.0)
    # Task 1 (Round 18): R16/R17 new-factor weights.
    w_ni = float(getattr(profile, "runner_composite_score_net_inflow_weight", 0.0) or 0.0)
    w_vp = float(getattr(profile, "runner_composite_score_volume_price_divergence_weight", 0.0) or 0.0)
    w_ts = float(getattr(profile, "runner_composite_score_t0_tail_weight", 0.0) or 0.0)
    # Task 2 (Round 19): multi-period momentum alignment weight.
    w_ma = float(getattr(profile, "runner_composite_score_momentum_alignment_weight", 0.0) or 0.0)
    # Task 1 (Round 26, Alpha): cross-factor F11/F12 weights.
    w_mc = float(getattr(profile, "runner_composite_score_momentum_confirmation_weight", 0.0) or 0.0)
    w_vm = float(getattr(profile, "runner_composite_score_volume_momentum_weight", 0.0) or 0.0)
    # Task 3 (Round 31, Beta): F13 — relative sector strength rank weight.
    w_rs = float(getattr(profile, "runner_composite_score_rs_sector_rank_weight", 0.0) or 0.0)
    # net_inflow_ratio is in [-1, +1]; map to [0, 1]: buying pressure score = (val + 1) / 2.
    # Absent / None → neutral 0.5 (no information, doesn't penalise).
    raw_ni = snapshot.get("t0_estimated_net_inflow_ratio")
    net_inflow_score: float = (float(raw_ni) + 1.0) / 2.0 if raw_ni is not None else 0.5
    net_inflow_score = round(max(0.0, min(1.0, net_inflow_score)), 4)
    # volume_price_divergence_score is in [0, 1] where HIGH = distribution risk.
    # For composite score we want LOW risk → HIGH quality: quality = 1 − divergence_score.
    raw_vp = snapshot.get("volume_price_divergence_score")
    vp_quality_score: float = 1.0 - float(raw_vp) if raw_vp is not None else 0.5
    vp_quality_score = round(max(0.0, min(1.0, vp_quality_score)), 4)
    # t0_tail_strength is in (0, 1]; already a quality proxy — use directly.
    raw_ts = snapshot.get("t0_tail_strength")
    t0_tail_score: float = float(raw_ts) if raw_ts is not None else 0.5
    t0_tail_score = round(max(0.0, min(1.0, t0_tail_score)), 4)
    # Task 2 (Round 19): multi_period_alignment_score ∈ [0, 1]; window-level metric attached to
    # each snapshot by the evaluation pipeline.  Neutral 0.5 when absent (no penalty applied).
    raw_ma = snapshot.get("multi_period_alignment_score")
    momentum_alignment_score: float = float(raw_ma) if raw_ma is not None else 0.5
    momentum_alignment_score = round(max(0.0, min(1.0, momentum_alignment_score)), 4)
    # Task 1 (Round 26, Alpha): cross-factor F11 — momentum_confirmation_score.
    # breakout_freshness × close_strength; neutral 0.25 (=0.5×0.5) when primary factors absent.
    raw_bf = snapshot.get("breakout_freshness")
    raw_cs_raw = snapshot.get("close_strength")
    momentum_confirmation_score: float = (float(raw_bf) if raw_bf is not None else 0.5) * (float(raw_cs_raw) if raw_cs_raw is not None else 0.5)
    momentum_confirmation_score = round(max(0.0, min(1.0, momentum_confirmation_score)), 4)
    # Task 1 (Round 26, Alpha): cross-factor F12 — volume_momentum_score.
    # volume_expansion_quality × t0_tail_strength; neutral 0.25 when primary factors absent.
    raw_veq = snapshot.get("volume_expansion_quality")
    raw_ts2 = snapshot.get("t0_tail_strength")
    volume_momentum_score: float = (float(raw_veq) if raw_veq is not None else 0.5) * (float(raw_ts2) if raw_ts2 is not None else 0.5)
    volume_momentum_score = round(max(0.0, min(1.0, volume_momentum_score)), 4)
    # Task 3 (Round 31, Beta): F13 — rs_sector_rank = (sector_resonance + close_strength) / 2.
    # Measures individual stock's relative strength within its sector.  Neutral 0.5 when data absent.
    raw_sr_f13 = snapshot.get("sector_resonance")
    raw_cs_f13 = snapshot.get("close_strength")
    if raw_sr_f13 is not None and raw_cs_f13 is not None:
        rs_sector_rank_score: float = (float(raw_sr_f13) + float(raw_cs_f13)) / 2.0
    elif snapshot.get("rs_sector_rank") is not None:
        rs_sector_rank_score = float(snapshot["rs_sector_rank"])
    else:
        rs_sector_rank_score = 0.5
    rs_sector_rank_score = round(max(0.0, min(1.0, rs_sector_rank_score)), 4)
    total_weight = w_b + w_t + w_v + w_c + w_cs + w_vr + w_sr + w_qb + w_ni + w_vp + w_ts + w_ma + w_mc + w_vm + w_rs
    if total_weight <= 0.0:
        return 0.0
    raw = w_b * breakout + w_t * trend + w_v * volume + w_c * catalyst + w_cs * close_str + w_vr * volatility_regime_score + w_sr * sector_resonance_score + w_qb * quiet_breakout_score + w_ni * net_inflow_score + w_vp * vp_quality_score + w_ts * t0_tail_score + w_ma * momentum_alignment_score + w_mc * momentum_confirmation_score + w_vm * volume_momentum_score + w_rs * rs_sector_rank_score
    return round(raw / total_weight, 4)
