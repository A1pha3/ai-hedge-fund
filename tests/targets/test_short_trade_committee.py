import pytest

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.short_trade_target import (
    build_short_trade_target_snapshot_from_entry,
    evaluate_short_trade_rejected_target,
)


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _make_committee_entry(*, metrics: dict | None = None) -> dict:
    return {
        "ticker": "300999",
        "score_b": 0.78,
        "score_c": 0.24,
        "score_final": 0.56,
        "quality_score": 0.70,
        "decision": "watch",
        "reason": "short_trade_candidate_score_ranked",
        "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "candidate_pool_rank": 2,
        "candidate_pool_avg_amount_share_of_cutoff": 1.22,
        "historical_prior": {
            "btst_regime_gate": "aggressive_trade",
            "evaluable_count": 6,
            "next_close_positive_rate": 0.68,
            "next_high_hit_rate_at_threshold": 0.72,
            "next_open_to_close_return_mean": 0.019,
        },
        "metrics": dict(metrics or {}),
        "strategy_signals": {
            "trend": _make_signal(
                1,
                85.0,
                sub_factors={
                    "momentum": {
                        "direction": 1,
                        "confidence": 88.0,
                        "completeness": 1.0,
                        "metrics": {"momentum_1m": 0.76, "momentum_3m": 0.72, "momentum_6m": 0.66, "volume_momentum": 0.62},
                    },
                    "adx_strength": {"direction": 1, "confidence": 76.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "volatility": {
                        "direction": 1,
                        "confidence": 65.0,
                        "completeness": 1.0,
                        "metrics": {"volatility_regime": 0.48, "atr_ratio": 0.09},
                    },
                    "long_trend_alignment": {"direction": 1, "confidence": 42.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                80.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 84.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "fundamental": _make_signal(1, 58.0).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.48, "investor": 0.32}},
    }


def _base_profile_overrides(**extra: float | bool) -> dict:
    return {
        "select_threshold": 0.30,
        "near_miss_threshold": 0.20,
        "selected_breakout_freshness_min": 0.10,
        "selected_trend_acceleration_min": 0.10,
        "committee_enabled": True,
        "committee_alpha_min_aggressive_trade": 0.0,
        "committee_beta_min_aggressive_trade": 0.0,
        "committee_gamma_min_aggressive_trade": 0.0,
        "committee_score_min_aggressive_trade": 0.0,
        **extra,
    }


def test_short_trade_snapshot_surfaces_committee_scores() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(),
        profile_overrides=_base_profile_overrides(),
    )

    assert snapshot["committee_enabled"] is True
    assert snapshot["committee_gate"] == "aggressive_trade"
    assert snapshot["committee_profile"] == "ignition_breakout"
    assert snapshot["alpha_edge_score"] > 0.0
    assert snapshot["beta_execution_score"] > 0.0
    assert snapshot["gamma_risk_score"] > 0.0
    assert snapshot["committee_score"] > 0.0
    assert snapshot["committee_components"]["sector_raw_100"] > 0.0
    assert snapshot["committee_gate_status"]["formal_selected"] in {"pass", "advisory"}


def test_short_trade_snapshot_auto_switches_to_ignition_breakout_profile() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(),
    )

    assert snapshot["profile"].name == "ignition_breakout"
    assert snapshot["committee_enabled"] is True
    assert snapshot["committee_profile"] == "ignition_breakout"


def test_explicit_default_profile_name_skips_auto_profile_switch() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(),
        profile_name="default",
    )

    assert snapshot["profile"].name == "default"
    assert snapshot["committee_enabled"] is False
    assert snapshot["committee_profile"] == "ignition_breakout"


def test_committee_thresholds_can_downgrade_selected_candidate() -> None:
    entry = _make_committee_entry()

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides={**_base_profile_overrides(), "committee_enabled": False},
    )
    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(committee_score_min_aggressive_trade=95.0),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert governed_result.committee_score is not None
    assert governed_result.committee_score < 95.0
    assert "committee_score_below_selected_min" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["gate"] == "aggressive_trade"
    assert governed_result.explainability_payload["committee"]["profile"] == "ignition_breakout"


def test_committee_isolated_attention_veto_rejects_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "attention_composite": 0.88,
            "sector_amt_share": 0.010,
            "flow_60": -0.01,
        }
    )

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides={**_base_profile_overrides(), "committee_enabled": False},
    )
    vetoed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert vetoed_result.decision == "rejected"
    assert "committee_isolated_attention_veto" in vetoed_result.blockers
    assert "committee_isolated_attention_veto" in vetoed_result.committee_vetoes
    assert vetoed_result.gate_status["committee"] == "veto"


def test_committee_weak_close_veto_downgrades_selected_candidate_to_near_miss() -> None:
    entry = _make_committee_entry(
        metrics={
            "flow_60": 0.10,
            "close_structure": 0.30,
            "close_support_30": 0.01,
        }
    )

    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides={**_base_profile_overrides(), "committee_enabled": False},
    )
    vetoed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert vetoed_result.decision == "near_miss"
    assert "committee_weak_close_execution_veto" in vetoed_result.downgrade_reasons
    assert "committee_weak_close_execution_veto" in vetoed_result.committee_vetoes
    assert vetoed_result.gate_status["committee"] == "veto"
    assert "committee_weak_close_execution_veto" not in vetoed_result.blockers