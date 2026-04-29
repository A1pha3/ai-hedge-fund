import pytest

from src.targets.profiles import build_short_trade_target_profile
from src.targets.short_trade_event_catalyst_helpers import build_event_catalyst_assessment


def test_build_event_catalyst_assessment_scores_fresh_supported_event() -> None:
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_min_score_for_selected_uplift": 0.72,
            "event_catalyst_selected_uplift": 0.03,
        },
    )
    snapshot = {
        "catalyst_freshness": 0.88,
        "sector_resonance": 0.72,
        "volume_expansion_quality": 0.76,
        "close_strength": 0.74,
        "trend_acceleration": 0.68,
        "extension_without_room_penalty": 0.05,
        "stale_trend_repair_penalty": 0.04,
        "overhead_supply_penalty": 0.03,
    }

    assessment = build_event_catalyst_assessment(
        snapshot=snapshot,
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is True
    assert assessment.selected_uplift == pytest.approx(0.03)
    assert assessment.score >= 0.72


def test_build_event_catalyst_assessment_blocks_extended_candidate() -> None:
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": True})

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.92,
            "sector_resonance": 0.76,
            "volume_expansion_quality": 0.80,
            "close_strength": 0.82,
            "trend_acceleration": 0.70,
            "extension_without_room_penalty": 0.88,
            "stale_trend_repair_penalty": 0.06,
            "overhead_supply_penalty": 0.04,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.near_miss_threshold_relief == 0.0
