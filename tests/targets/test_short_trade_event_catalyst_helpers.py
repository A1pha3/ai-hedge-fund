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


def test_build_event_catalyst_assessment_disabled_mode_returns_zeroed_assessment() -> None:
    """Test that disabled mode returns a zero assessment regardless of input."""
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": False})

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.95,
            "sector_resonance": 0.88,
            "volume_expansion_quality": 0.92,
            "close_strength": 0.90,
            "trend_acceleration": 0.85,
            "extension_without_room_penalty": 0.02,
            "stale_trend_repair_penalty": 0.01,
            "overhead_supply_penalty": 0.01,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.score == 0.0
    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.near_miss_threshold_relief == 0.0
    assert assessment.gate_hits == {}
    assert assessment.component_scores == {}


def test_build_event_catalyst_assessment_near_miss_only_relief_band() -> None:
    """Test score that qualifies for near-miss relief but not selected uplift."""
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_min_score_for_selected_uplift": 0.75,
            "event_catalyst_min_score_for_near_miss_retain": 0.60,
            "event_catalyst_selected_uplift": 0.03,
            "event_catalyst_near_miss_threshold_relief": 0.02,
        },
    )

    # Craft snapshot to score between 0.60 and 0.75
    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.70,
            "sector_resonance": 0.65,
            "volume_expansion_quality": 0.68,
            "close_strength": 0.62,
            "trend_acceleration": 0.60,
            "extension_without_room_penalty": 0.10,
            "stale_trend_repair_penalty": 0.08,
            "overhead_supply_penalty": 0.07,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is True
    assert assessment.selected_uplift == 0.0  # Below 0.75
    assert assessment.near_miss_threshold_relief == pytest.approx(0.02)  # Above 0.60
    assert 0.60 <= assessment.score < 0.75


def test_build_event_catalyst_assessment_source_ineligibility() -> None:
    """Test that non-whitelisted candidate sources are rejected."""
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_candidate_sources": frozenset({"catalyst_theme"}),
        },
    )

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.90,
            "sector_resonance": 0.85,
            "volume_expansion_quality": 0.88,
            "close_strength": 0.84,
            "trend_acceleration": 0.78,
            "extension_without_room_penalty": 0.05,
            "stale_trend_repair_penalty": 0.03,
            "overhead_supply_penalty": 0.02,
        },
        profile=profile,
        candidate_source="liquidity_shadow",  # Not in allowed sources
        candidate_reason_codes={"liquidity_shadow_candidate"},
    )

    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.near_miss_threshold_relief == 0.0
    assert assessment.gate_hits["eligible_source"] is False


def test_build_event_catalyst_assessment_stale_penalty_gate() -> None:
    """Test that stale penalty above threshold blocks eligibility."""
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_stale_penalty_max": 0.40,
        },
    )

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.88,
            "sector_resonance": 0.82,
            "volume_expansion_quality": 0.80,
            "close_strength": 0.78,
            "trend_acceleration": 0.75,
            "extension_without_room_penalty": 0.10,
            "stale_trend_repair_penalty": 0.65,  # Above max
            "overhead_supply_penalty": 0.05,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.gate_hits["stale_ok"] is False


def test_build_event_catalyst_assessment_overhead_penalty_gate() -> None:
    """Test that overhead penalty above threshold blocks eligibility."""
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_overhead_penalty_max": 0.45,
        },
    )

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.88,
            "sector_resonance": 0.82,
            "volume_expansion_quality": 0.80,
            "close_strength": 0.78,
            "trend_acceleration": 0.75,
            "extension_without_room_penalty": 0.10,
            "stale_trend_repair_penalty": 0.05,
            "overhead_supply_penalty": 0.72,  # Above max
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.gate_hits["overhead_ok"] is False


def test_build_event_catalyst_assessment_component_scores_captured() -> None:
    """Test that component scores are properly captured and normalized."""
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": True})

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.91,
            "sector_resonance": 0.77,
            "volume_expansion_quality": 0.83,
            "close_strength": 0.69,
            "trend_acceleration": 0.74,
            "extension_without_room_penalty": 0.12,
            "stale_trend_repair_penalty": 0.08,
            "overhead_supply_penalty": 0.06,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.component_scores["freshness"] == pytest.approx(0.91)
    assert assessment.component_scores["resonance"] == pytest.approx(0.77)
    assert assessment.component_scores["volume"] == pytest.approx(0.83)
    assert assessment.component_scores["close"] == pytest.approx(0.69)
    assert assessment.component_scores["trend"] == pytest.approx(0.74)


def test_build_event_catalyst_assessment_handles_none_and_missing_values() -> None:
    """Test that None and missing snapshot values default to 0.0."""
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": True})

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": None,
            # sector_resonance missing entirely
            "volume_expansion_quality": 0.80,
            "close_strength": None,
            "trend_acceleration": 0.70,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes=set(),
    )

    assert assessment.component_scores["freshness"] == 0.0
    assert assessment.component_scores["resonance"] == 0.0
    assert assessment.component_scores["close"] == 0.0


def test_build_event_catalyst_assessment_captures_reason_codes() -> None:
    """Test that candidate_reason_codes are captured in the assessment."""
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": True})
    reason_codes = {"catalyst_theme_candidate_score_ranked", "fresh_breakout_support"}

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.85,
            "sector_resonance": 0.75,
            "volume_expansion_quality": 0.80,
            "close_strength": 0.70,
            "trend_acceleration": 0.72,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes=reason_codes,
    )

    # Assessment should capture the reason codes
    assert hasattr(assessment, "candidate_reason_codes")
    assert assessment.candidate_reason_codes == reason_codes
