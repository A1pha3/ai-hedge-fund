from src.targets.short_trade_boundary_contract_helpers import (
    BOUNDARY_CONTRACT_CORE_KEYS,
    build_boundary_contract_core_payload,
    merge_boundary_contract_core_payload,
)


def test_build_boundary_contract_core_payload_prefers_explicit_values() -> None:
    payload = build_boundary_contract_core_payload(
        explicit_values={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
        },
        metrics_payload={
            "breakout_freshness": 0.11,
            "trend_acceleration": 0.22,
            "volume_expansion_quality": 0.33,
            "close_strength": 0.44,
            "trend_continuation": 0.57,
        },
    )

    assert payload == {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
        "trend_continuation": 0.57,
    }


def test_build_boundary_contract_core_payload_backfills_from_metrics_when_explicit_missing() -> None:
    payload = build_boundary_contract_core_payload(
        explicit_values={"breakout_freshness": 0.71},
        metrics_payload={
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "short_term_reversal": 0.21,
        },
    )

    assert payload == {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
        "short_term_reversal": 0.21,
    }


def test_merge_boundary_contract_core_payload_preserves_existing_explainability_values() -> None:
    merged = merge_boundary_contract_core_payload(
        explainability_payload={
            "breakout_freshness": 0.81,
            "committee": {"enabled": True},
        },
        core_payload={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
        },
    )

    assert merged["breakout_freshness"] == 0.81
    assert merged["trend_acceleration"] == 0.66
    assert merged["committee"] == {"enabled": True}


def test_boundary_contract_core_keys_are_the_expected_boundary_surface() -> None:
    assert BOUNDARY_CONTRACT_CORE_KEYS == (
        "breakout_freshness",
        "close_strength",
        "short_term_reversal",
        "trend_acceleration",
        "trend_continuation",
        "volume_expansion_quality",
    )
