from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.execution.daily_pipeline import (
    _enforce_btst_prior_quality_p3,
    BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV,
)
from src.execution.models import ExecutionPlan, LayerCResult
from src.research.artifacts import FileSelectionArtifactWriter
from src.targets.models import (
    DualTargetEvaluation,
    DualTargetSummary,
    TargetEvaluationResult,
)
from src.targets.profiles import use_short_trade_target_profile
from src.targets.short_trade_target import evaluate_short_trade_rejected_target
from src.targets.short_trade_target_prior_helpers import (
    calibrate_short_trade_historical_prior,
)


@pytest.fixture
def shrinkage_prior() -> dict[str, object]:
    return {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.04,
    }


@pytest.fixture
def catalyst_theme_entry() -> dict[str, object]:
    return {
        "ticker": "300724",
        "score_b": 0.0,
        "score_c": 0.0,
        "score_final": 0.0,
        "quality_score": 0.6,
        "decision": "watch",
        "reason": "catalyst_theme_candidate_score_ranked",
        "candidate_source": "catalyst_theme",
        "candidate_reason_codes": ["catalyst_theme_candidate_score_ranked"],
        "metrics": {
            "breakout_freshness": 1.0,
            "trend_acceleration": 1.0,
            "volume_expansion_quality": 1.0,
            "close_strength": 1.0,
            "sector_resonance": 1.0,
            "catalyst_freshness": 1.0,
        },
        "strategy_signals": {
            "trend": {
                "direction": 1,
                "confidence": 80.0,
                "completeness": 1.0,
                "sub_factors": {
                    "momentum": {"direction": 1, "confidence": 80.0, "completeness": 1.0, "metrics": {"momentum_1m": 0.2, "momentum_3m": 0.8, "momentum_6m": 0.8, "volume_momentum": 0.8}},
                    "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 50.0, "completeness": 1.0, "metrics": {"volatility_regime": 0.6, "atr_ratio": 0.08}},
                    "long_trend_alignment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            },
            "event_sentiment": {
                "direction": 1,
                "confidence": 80.0,
                "completeness": 1.0,
                "sub_factors": {
                    "event_freshness": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            },
            "fundamental": {"direction": 1, "confidence": 60.0, "completeness": 1.0, "sub_factors": {}},
            "mean_reversion": {"direction": 0, "confidence": 0.0, "completeness": 1.0, "sub_factors": {}},
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 2,
            "same_ticker_sample_count": 2,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.04,
        },
    }


class TestPriorShrinkageMath:
    def test_sample_reliability_and_shrunk_rates_are_more_conservative_for_low_samples(self, shrinkage_prior: dict[str, object]) -> None:
        low_sample = calibrate_short_trade_historical_prior({**shrinkage_prior, "evaluable_count": 2, "same_ticker_sample_count": 2})
        high_sample = calibrate_short_trade_historical_prior({**shrinkage_prior, "evaluable_count": 18, "same_ticker_sample_count": 18})

        assert low_sample["sample_reliability"] < high_sample["sample_reliability"]
        assert low_sample["shrunk_high_hit_rate"] < high_sample["shrunk_high_hit_rate"] < low_sample["raw_next_high_hit_rate_at_threshold"]
        assert low_sample["shrunk_close_positive_rate"] < high_sample["shrunk_close_positive_rate"] < low_sample["raw_next_close_positive_rate"]

    def test_profile_override_controls_shrinkage_strength(self, catalyst_theme_entry: dict[str, object]) -> None:
        with use_short_trade_target_profile(
            profile_name="default",
            overrides={
                "select_threshold": 0.8,
                "near_miss_threshold": 0.65,
                "selected_breakout_freshness_min": 0.0,
                "selected_trend_acceleration_min": 0.0,
                "near_miss_breakout_freshness_min": 0.0,
                "near_miss_trend_acceleration_min": 0.0,
                "breakout_freshness_weight": 0.0,
                "trend_acceleration_weight": 0.0,
                "volume_expansion_quality_weight": 0.0,
                "close_strength_weight": 0.0,
                "sector_resonance_weight": 0.0,
                "catalyst_freshness_weight": 0.0,
                "layer_c_alignment_weight": 0.0,
                "historical_continuation_score_weight": 1.0,
                "stale_score_penalty_weight": 0.0,
                "overhead_score_penalty_weight": 0.0,
                "extension_score_penalty_weight": 0.0,
                "layer_c_avoid_penalty": 0.0,
                "p4_prior_shrinkage_k": 2.0,
            },
        ):
            light_shrink = evaluate_short_trade_rejected_target(trade_date="20260422", entry=catalyst_theme_entry)

        with use_short_trade_target_profile(
            profile_name="default",
            overrides={
                "select_threshold": 0.8,
                "near_miss_threshold": 0.65,
                "selected_breakout_freshness_min": 0.0,
                "selected_trend_acceleration_min": 0.0,
                "near_miss_breakout_freshness_min": 0.0,
                "near_miss_trend_acceleration_min": 0.0,
                "breakout_freshness_weight": 0.0,
                "trend_acceleration_weight": 0.0,
                "volume_expansion_quality_weight": 0.0,
                "close_strength_weight": 0.0,
                "sector_resonance_weight": 0.0,
                "catalyst_freshness_weight": 0.0,
                "layer_c_alignment_weight": 0.0,
                "historical_continuation_score_weight": 1.0,
                "stale_score_penalty_weight": 0.0,
                "overhead_score_penalty_weight": 0.0,
                "extension_score_penalty_weight": 0.0,
                "layer_c_avoid_penalty": 0.0,
                "p4_prior_shrinkage_k": 20.0,
            },
        ):
            heavy_shrink = evaluate_short_trade_rejected_target(trade_date="20260422", entry=catalyst_theme_entry)

        light_prior = light_shrink.explainability_payload["historical_prior"]
        heavy_prior = heavy_shrink.explainability_payload["historical_prior"]
        assert heavy_prior["sample_reliability"] < light_prior["sample_reliability"]
        assert heavy_prior["shrunk_close_positive_rate"] < light_prior["shrunk_close_positive_rate"]


class TestP4DecisionPath:
    def test_p4_enforce_prefers_shrunk_prior_rates_in_decision_path(self, monkeypatch: pytest.MonkeyPatch, catalyst_theme_entry: dict[str, object]) -> None:
        monkeypatch.delenv(BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV, raising=False)
        profile_overrides = {
            "select_threshold": 0.8,
            "near_miss_threshold": 0.65,
            "selected_breakout_freshness_min": 0.0,
            "selected_trend_acceleration_min": 0.0,
            "near_miss_breakout_freshness_min": 0.0,
            "near_miss_trend_acceleration_min": 0.0,
            "breakout_freshness_weight": 0.0,
            "trend_acceleration_weight": 0.0,
            "volume_expansion_quality_weight": 0.0,
            "close_strength_weight": 0.0,
            "sector_resonance_weight": 0.0,
            "catalyst_freshness_weight": 0.0,
            "layer_c_alignment_weight": 0.0,
            "historical_continuation_score_weight": 1.0,
            "stale_score_penalty_weight": 0.0,
            "overhead_score_penalty_weight": 0.0,
            "extension_score_penalty_weight": 0.0,
            "layer_c_avoid_penalty": 0.0,
            "p4_prior_shrinkage_k": 20.0,
        }
        with use_short_trade_target_profile(profile_name="default", overrides=profile_overrides):
            baseline_result = evaluate_short_trade_rejected_target(trade_date="20260422", entry=catalyst_theme_entry)

        monkeypatch.setenv(BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV, "enforce")
        with use_short_trade_target_profile(profile_name="default", overrides=profile_overrides):
            shrunk_result = evaluate_short_trade_rejected_target(trade_date="20260422", entry=catalyst_theme_entry)

        assert baseline_result.decision == "selected"
        assert shrunk_result.decision == "near_miss"
        assert shrunk_result.score_target < baseline_result.score_target
        assert shrunk_result.metrics_payload["historical_continuation_prior_score"]["next_close_positive_rate"] == pytest.approx(shrunk_result.explainability_payload["historical_prior"]["shrunk_close_positive_rate"])

    def test_p4_enforce_can_keep_calibrated_rates_when_profile_disables_shrunk_prior_usage(self, monkeypatch: pytest.MonkeyPatch, catalyst_theme_entry: dict[str, object]) -> None:
        monkeypatch.setenv(BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV, "enforce")
        profile_overrides = {
            "select_threshold": 0.8,
            "near_miss_threshold": 0.65,
            "selected_breakout_freshness_min": 0.0,
            "selected_trend_acceleration_min": 0.0,
            "near_miss_breakout_freshness_min": 0.0,
            "near_miss_trend_acceleration_min": 0.0,
            "breakout_freshness_weight": 0.0,
            "trend_acceleration_weight": 0.0,
            "volume_expansion_quality_weight": 0.0,
            "close_strength_weight": 0.0,
            "sector_resonance_weight": 0.0,
            "catalyst_freshness_weight": 0.0,
            "layer_c_alignment_weight": 0.0,
            "historical_continuation_score_weight": 1.0,
            "stale_score_penalty_weight": 0.0,
            "overhead_score_penalty_weight": 0.0,
            "extension_score_penalty_weight": 0.0,
            "layer_c_avoid_penalty": 0.0,
            "p4_prior_shrinkage_k": 20.0,
            "selected_use_shrunk_prior_rates": False,
        }

        with use_short_trade_target_profile(profile_name="default", overrides=profile_overrides):
            result = evaluate_short_trade_rejected_target(trade_date="20260422", entry=catalyst_theme_entry)

        assert result.decision == "selected"
        assert result.explainability_payload["historical_prior"]["effective_prior_rate_source"] == "calibrated"
        assert result.metrics_payload["historical_continuation_prior_score"]["next_close_positive_rate"] == pytest.approx(
            result.explainability_payload["historical_prior"]["calibrated_next_close_positive_rate"]
        )

    def test_p3_hard_reject_still_wins_when_p4_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV, "enforce")
        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        evaluation = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            short_trade=TargetEvaluationResult(target_type="short_trade", decision="selected"),
        )
        plan = ExecutionPlan(
            date="20260422",
            portfolio_snapshot={"cash": 100000.0, "positions": {}},
            risk_metrics={"counts": {"buy_order_count": 0}, "funnel_diagnostics": {}},
        )
        plan.selection_targets = {"000001": evaluation}

        result = _enforce_btst_prior_quality_p3(
            plan,
            prior_by_ticker={
                "000001": {
                    "evaluable_count": 2,
                    "next_high_hit_rate_at_threshold": 0.0,
                    "next_close_positive_rate": 1.0,
                }
            },
        )

        assert result.selection_targets["000001"].p3_execution_blocked is True
        assert result.selection_targets["000001"].p3_prior_quality_label == "reject"


class TestArtifactObservability:
    def test_p4_baseline_becomes_gate_aware_for_same_quality_bucket(self) -> None:
        common_prior = {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 2,
            "same_ticker_sample_count": 2,
            "next_high_hit_rate_at_threshold": 0.55,
            "next_close_positive_rate": 0.55,
            "next_open_to_close_return_mean": 0.01,
        }

        aggressive_prior = calibrate_short_trade_historical_prior({**common_prior, "btst_regime_gate": "aggressive_trade"})
        halt_prior = calibrate_short_trade_historical_prior({**common_prior, "btst_regime_gate": "halt"})

        assert aggressive_prior["prior_baseline_next_close_positive_rate"] > halt_prior["prior_baseline_next_close_positive_rate"]
        assert aggressive_prior["prior_baseline_next_high_hit_rate_at_threshold"] > halt_prior["prior_baseline_next_high_hit_rate_at_threshold"]

    def test_selection_artifact_surfaces_raw_and_shrunk_prior_metrics(self, tmp_path: Path) -> None:
        writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_p4_meta")
        short_trade = TargetEvaluationResult(
            target_type="short_trade",
            decision="selected",
            metrics_payload={
                "historical_prior": {
                    "raw_next_high_hit_rate_at_threshold": 1.0,
                    "raw_next_close_positive_rate": 1.0,
                    "sample_reliability": 0.2,
                    "shrunk_high_hit_rate": 0.72,
                    "shrunk_close_positive_rate": 0.66,
                }
            },
        )
        evaluation = DualTargetEvaluation(
            ticker="300724",
            trade_date="20260422",
            short_trade=short_trade,
        )
        plan = ExecutionPlan(
            date="20260422",
            portfolio_snapshot={"cash": 100000.0, "positions": {}},
            risk_metrics={"counts": {"layer_a_count": 1, "layer_b_count": 1, "watchlist_count": 1, "buy_order_count": 0}},
            watchlist=[
                LayerCResult(
                    ticker="300724",
                    score_b=0.7,
                    score_c=0.6,
                    score_final=0.65,
                    quality_score=0.7,
                    decision="watch",
                )
            ],
            selection_targets={"300724": evaluation},
            target_mode="short_trade_only",
            dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1),
            buy_orders=[],
        )

        result = writer.write_for_plan(plan=plan, trade_date="20260422", pipeline=None, selected_analysts=None)

        assert result.write_status == "success"
        snapshot = json.loads((tmp_path / "2026-04-22" / "selection_snapshot.json").read_text(encoding="utf-8"))
        entry = next(candidate for candidate in snapshot["selected"] if candidate["symbol"] == "300724")
        target_context = entry["target_context"]
        assert target_context["raw_next_high_hit_rate_at_threshold"] == 1.0
        assert target_context["sample_reliability"] == 0.2
        assert target_context["shrunk_high_hit_rate"] == 0.72
        assert target_context["shrunk_close_positive_rate"] == 0.66
