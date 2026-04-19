"""Rank-based threshold tightening and decision cap logic.

Extracted from short_trade_target_evaluation_helpers.py to reduce file
size and isolate the rank-cap decision tree (~300 lines).
"""

from __future__ import annotations

import math
from typing import Any

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
    catalyst_theme_source_specific_caps_enabled = normalized_candidate_source == "catalyst_theme" and "catalyst_theme_short_trade_carryover_candidate" not in normalized_reason_codes
    selected_rank_cap_hard = _normalize_rank_cap(getattr(profile, "selected_rank_cap", 0))
    near_miss_rank_cap_hard = _normalize_rank_cap(getattr(profile, "near_miss_rank_cap", 0))
    selected_rank_cap_ratio = _normalize_rank_cap_ratio(getattr(profile, "selected_rank_cap_ratio", 0.0))
    near_miss_rank_cap_ratio = _normalize_rank_cap_ratio(getattr(profile, "near_miss_rank_cap_ratio", 0.0))
    if catalyst_theme_source_specific_caps_enabled:
        catalyst_theme_selected_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "catalyst_theme_selected_rank_cap_ratio", None))
        if catalyst_theme_selected_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            selected_rank_cap_ratio = catalyst_theme_selected_rank_cap_ratio
        catalyst_theme_near_miss_rank_cap_ratio = _resolve_rank_cap_ratio_override(getattr(profile, "catalyst_theme_near_miss_rank_cap_ratio", None))
        if catalyst_theme_near_miss_rank_cap_ratio is not _UNSET_RANK_CAP_RATIO:
            near_miss_rank_cap_ratio = catalyst_theme_near_miss_rank_cap_ratio
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
        max(0.0, float(getattr(profile, "selected_rank_cap_relief_close_strength_max", 1.0) or 1.0)),
    )
    selected_rank_cap_relief_require_confirmed_breakout = bool(getattr(profile, "selected_rank_cap_relief_require_confirmed_breakout", False))
    selected_rank_cap_relief_require_t_plus_2_candidate = bool(getattr(profile, "selected_rank_cap_relief_require_t_plus_2_candidate", False))
    selected_rank_cap_relief_allow_risk_off = bool(getattr(profile, "selected_rank_cap_relief_allow_risk_off", True))
    selected_rank_cap_relief_allow_crisis = bool(getattr(profile, "selected_rank_cap_relief_allow_crisis", True))

    selected_rank_cap_relief_cap: int | None = None
    if selected_rank_cap is not None and selected_rank_cap_relief_rank_buffer is not None:
        selected_rank_cap_relief_cap = int(selected_rank_cap + selected_rank_cap_relief_rank_buffer)

    score_target = float(snapshot.get("score_target") or 0.0)
    effective_select_threshold = float(snapshot.get("effective_select_threshold") or 0.0)
    selected_rank_cap_relief_score_margin = round(score_target - effective_select_threshold, 4)
    selected_rank_cap_relief_score_pass = selected_rank_cap_relief_score_margin >= selected_rank_cap_relief_score_margin_min

    breakout_freshness = float(snapshot.get("breakout_freshness") or 0.0)
    trend_acceleration = float(snapshot.get("trend_acceleration") or 0.0)
    selected_breakout_gate_pass = breakout_freshness >= float(getattr(profile, "selected_breakout_freshness_min", 0.0)) and trend_acceleration >= float(getattr(profile, "selected_trend_acceleration_min", 0.0))
    selected_rank_cap_relief_breakout_pass = (not selected_rank_cap_relief_require_confirmed_breakout) or selected_breakout_gate_pass

    sector_resonance = float(snapshot.get("sector_resonance") or 0.0)
    selected_rank_cap_relief_sector_resonance_pass = sector_resonance >= selected_rank_cap_relief_sector_resonance_min

    close_strength = float(snapshot.get("close_strength") or 0.0)
    selected_rank_cap_relief_close_strength_pass = close_strength <= selected_rank_cap_relief_close_strength_max

    t_plus_2_continuation_candidate = dict(snapshot.get("t_plus_2_continuation_candidate") or {})
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

    selected_rank_cap_relief_within_buffer = bool(selected_rank_cap_relief_cap is not None and normalized_rank > 0 and normalized_rank <= selected_rank_cap_relief_cap)
    selected_cap_soft_relief_applied = bool(selected_cap_exceeded_raw and selected_rank_cap_relief_within_buffer and selected_rank_cap_relief_score_pass and selected_rank_cap_relief_breakout_pass and selected_rank_cap_relief_sector_resonance_pass and selected_rank_cap_relief_close_strength_pass and selected_rank_cap_relief_t_plus_2_pass and selected_rank_cap_relief_market_risk_pass)
    selected_cap_exceeded_effective = bool(selected_cap_exceeded_raw and not selected_cap_soft_relief_applied)

    return {
        "enabled": bool(selected_rank_cap is not None or near_miss_rank_cap is not None or selected_rank_cap_ratio is not None or near_miss_rank_cap_ratio is not None),
        "candidate_source": normalized_candidate_source or None,
        "catalyst_theme_source_specific_caps_enabled": catalyst_theme_source_specific_caps_enabled,
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
        "selected_rank_cap_relief_allow_risk_off": selected_rank_cap_relief_allow_risk_off,
        "selected_rank_cap_relief_allow_crisis": selected_rank_cap_relief_allow_crisis,
        "selected_rank_cap_relief_market_risk_source": selected_rank_cap_relief_market_risk_source,
        "selected_rank_cap_relief_market_risk_level": selected_rank_cap_relief_market_risk_level,
        "selected_rank_cap_relief_market_risk_pass": selected_rank_cap_relief_market_risk_pass,
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
