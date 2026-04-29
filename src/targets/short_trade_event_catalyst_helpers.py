"""Event catalyst assessment helpers for BTST short trade target scoring.

This module provides an isolated event/catalyst quality assessment that can
be used to selectively uplift or retain near-miss candidates when fresh,
supported events align with strong technical conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.utils.numeric import clamp_unit_interval


class EventCatalystProfile(Protocol):
    """Protocol defining the event catalyst configuration interface.
    
    This protocol ensures type safety for profile objects passed to
    event catalyst assessment builders without coupling to concrete types.
    """

    event_catalyst_enabled: bool
    event_catalyst_candidate_sources: frozenset[str]
    event_catalyst_catalyst_freshness_weight: float
    event_catalyst_sector_resonance_weight: float
    event_catalyst_volume_expansion_weight: float
    event_catalyst_close_strength_weight: float
    event_catalyst_trend_acceleration_weight: float
    event_catalyst_min_score_for_selected_uplift: float
    event_catalyst_min_score_for_near_miss_retain: float
    event_catalyst_selected_uplift: float
    event_catalyst_near_miss_threshold_relief: float
    event_catalyst_extension_penalty_max: float
    event_catalyst_stale_penalty_max: float
    event_catalyst_overhead_penalty_max: float


@dataclass(frozen=True)
class EventCatalystAssessment:
    """Assessment result for event catalyst quality and eligibility."""

    score: float
    eligible: bool
    selected_uplift: float
    near_miss_threshold_relief: float
    gate_hits: dict[str, bool]
    component_scores: dict[str, float]
    candidate_reason_codes: set[str]


def build_event_catalyst_assessment(
    *,
    snapshot: dict[str, Any],
    profile: EventCatalystProfile,
    candidate_source: str,
    candidate_reason_codes: set[str],
) -> EventCatalystAssessment:
    """Build event catalyst assessment from snapshot and profile configuration.

    Args:
        snapshot: Feature snapshot containing catalyst/event quality signals
        profile: Target profile with event_catalyst_* configuration fields
        candidate_source: Source of the candidate (e.g., "catalyst_theme")
        candidate_reason_codes: Set of reason codes for the candidate (captured for tracing)

    Returns:
        EventCatalystAssessment with score, eligibility, and potential uplifts
    """
    if not bool(getattr(profile, "event_catalyst_enabled", False)):
        return EventCatalystAssessment(0.0, False, 0.0, 0.0, {}, {}, candidate_reason_codes)

    # Extract core component signals (all normalized 0..1)
    freshness = clamp_unit_interval(float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
    resonance = clamp_unit_interval(float(snapshot.get("sector_resonance", 0.0) or 0.0))
    volume = clamp_unit_interval(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0))
    close = clamp_unit_interval(float(snapshot.get("close_strength", 0.0) or 0.0))
    trend = clamp_unit_interval(float(snapshot.get("trend_acceleration", 0.0) or 0.0))

    # Extract penalty signals
    extension_penalty = float(snapshot.get("extension_without_room_penalty", 0.0) or 0.0)
    stale_penalty = float(snapshot.get("stale_trend_repair_penalty", 0.0) or 0.0)
    overhead_penalty = float(snapshot.get("overhead_supply_penalty", 0.0) or 0.0)

    # Compute weighted score
    score_raw = (
        float(profile.event_catalyst_catalyst_freshness_weight) * freshness
        + float(profile.event_catalyst_sector_resonance_weight) * resonance
        + float(profile.event_catalyst_volume_expansion_weight) * volume
        + float(profile.event_catalyst_close_strength_weight) * close
        + float(profile.event_catalyst_trend_acceleration_weight) * trend
    )
    score = clamp_unit_interval(score_raw)

    # Check eligibility gates
    source_eligible = candidate_source in profile.event_catalyst_candidate_sources
    extension_ok = extension_penalty <= float(profile.event_catalyst_extension_penalty_max)
    stale_ok = stale_penalty <= float(profile.event_catalyst_stale_penalty_max)
    overhead_ok = overhead_penalty <= float(profile.event_catalyst_overhead_penalty_max)

    eligible = source_eligible and extension_ok and stale_ok and overhead_ok

    # Determine uplifts based on score thresholds
    selected_uplift = 0.0
    near_miss_threshold_relief = 0.0

    if eligible:
        if score >= float(profile.event_catalyst_min_score_for_selected_uplift):
            selected_uplift = float(profile.event_catalyst_selected_uplift)
        if score >= float(profile.event_catalyst_min_score_for_near_miss_retain):
            near_miss_threshold_relief = float(profile.event_catalyst_near_miss_threshold_relief)

    return EventCatalystAssessment(
        score=score,
        eligible=eligible,
        selected_uplift=selected_uplift,
        near_miss_threshold_relief=near_miss_threshold_relief,
        gate_hits={
            "eligible_source": source_eligible,
            "extension_ok": extension_ok,
            "stale_ok": stale_ok,
            "overhead_ok": overhead_ok,
        },
        component_scores={
            "freshness": freshness,
            "resonance": resonance,
            "volume": volume,
            "close": close,
            "trend": trend,
        },
        candidate_reason_codes=candidate_reason_codes,
    )
