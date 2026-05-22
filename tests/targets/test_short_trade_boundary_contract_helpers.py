from src.targets.short_trade_boundary_contract_helpers import (
    BOUNDARY_CONTRACT_CORE_KEYS,
    build_boundary_contract_core_payload,
    merge_boundary_contract_core_payload,
)
from src.targets.models import TargetEvaluationInput
from src.targets.short_trade_target_evaluation_helpers import (
    ShortTradeEvaluationContext,
    ShortTradeThresholdState,
    ShortTradeVerdict,
    build_short_trade_target_result,
)
import src.targets.short_trade_target_evaluation_helpers as short_trade_target_evaluation_helpers


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


def test_source_style_boundary_contract_payload_can_be_merged_into_explainability() -> None:
    metrics_payload = {
        "trend_continuation": 0.57,
        "short_term_reversal": 0.21,
    }
    explicit_values = {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
    }

    core_payload = build_boundary_contract_core_payload(
        explicit_values=explicit_values,
        metrics_payload=metrics_payload,
    )
    explainability_payload = merge_boundary_contract_core_payload(
        explainability_payload={"committee": {"enabled": True}},
        core_payload=core_payload,
    )

    assert explainability_payload["breakout_freshness"] == 0.71
    assert explainability_payload["trend_continuation"] == 0.57
    assert explainability_payload["short_term_reversal"] == 0.21


def test_build_short_trade_target_result_emits_boundary_contract_core_keys_into_explainability(monkeypatch) -> None:
    monkeypatch.setattr(
        short_trade_target_evaluation_helpers,
        "_build_short_trade_metrics_payload",
        lambda **_: {
            "trend_continuation": 0.57,
            "short_term_reversal": 0.21,
        },
    )
    monkeypatch.setattr(
        short_trade_target_evaluation_helpers,
        "_build_short_trade_explainability_state",
        lambda snapshot: snapshot,
    )
    monkeypatch.setattr(
        short_trade_target_evaluation_helpers,
        "_build_short_trade_explainability_payload",
        lambda **_: {"committee": {"enabled": True}},
    )

    result = build_short_trade_target_result(
        context=ShortTradeEvaluationContext(
            snapshot={
                "profile": "demo-profile",
                "score_target": 0.82,
                "volume_expansion_quality": 0.63,
                "close_strength": 0.68,
                "sector_resonance": 0.31,
                "raw_catalyst_freshness": 0.29,
                "layer_c_alignment": 0.44,
                "trend_continuation": 0.57,
                "short_term_reversal": 0.21,
                "historical_prior": {},
                "weighted_positive_contributions": {},
                "weighted_negative_contributions": {},
            },
            carryover_evidence_deficiency={},
            selected_historical_proof_deficiency={},
        ),
        thresholds=ShortTradeThresholdState(
            breakout_freshness=0.71,
            trend_acceleration=0.66,
            effective_near_miss_threshold=0.55,
            effective_select_threshold=0.65,
            selected_score_tolerance=0.0,
            breakout_stage="fresh",
            selected_breakout_gate_pass=True,
            near_miss_breakout_gate_pass=True,
        ),
        verdict=ShortTradeVerdict(
            decision="selected",
            confidence=0.88,
            positive_tags=[],
            negative_tags=[],
            blockers=[],
            gate_status={},
            top_reasons=[],
            rejection_reasons=[],
            downgrade_reasons=[],
        ),
        input_data=TargetEvaluationInput(
            trade_date="2026-05-22",
            ticker="300620",
            replay_context={"source": "paper"},
        ),
        rank_hint=1,
    )

    assert result.explainability_payload["committee"] == {"enabled": True}
    assert result.explainability_payload["breakout_freshness"] == 0.71
    assert result.explainability_payload["trend_acceleration"] == 0.66
    assert result.explainability_payload["volume_expansion_quality"] == 0.63
    assert result.explainability_payload["close_strength"] == 0.68
    assert result.explainability_payload["trend_continuation"] == 0.57
    assert result.explainability_payload["short_term_reversal"] == 0.21
