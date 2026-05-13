import pytest

from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.profiles import get_short_trade_target_profile
from src.targets.short_trade_target_committee_helpers import _flow_raw_score
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


def test_auto_profiles_use_strategy_doc_thresholds() -> None:
    ignition_breakout = get_short_trade_target_profile("ignition_breakout")
    retention_follow = get_short_trade_target_profile("retention_follow")

    assert ignition_breakout.select_threshold == pytest.approx(0.42)
    assert ignition_breakout.near_miss_threshold == pytest.approx(0.32)
    assert ignition_breakout.committee_alpha_min_aggressive_trade == pytest.approx(72.0)
    assert ignition_breakout.committee_beta_min_aggressive_trade == pytest.approx(58.0)
    assert ignition_breakout.committee_gamma_min_aggressive_trade == pytest.approx(55.0)
    assert ignition_breakout.committee_score_min_aggressive_trade == pytest.approx(68.0)

    assert retention_follow.select_threshold == pytest.approx(0.46)
    assert retention_follow.near_miss_threshold == pytest.approx(0.35)
    assert retention_follow.committee_alpha_min_normal_trade == pytest.approx(68.0)
    assert retention_follow.committee_beta_min_normal_trade == pytest.approx(62.0)
    assert retention_follow.committee_gamma_min_normal_trade == pytest.approx(58.0)
    assert retention_follow.committee_score_min_normal_trade == pytest.approx(66.0)


def test_committee_profiles_enable_fragile_breakout_risk_only_for_btst_profiles() -> None:
    default_profile = get_short_trade_target_profile("default")
    ignition_breakout = get_short_trade_target_profile("ignition_breakout")
    retention_follow = get_short_trade_target_profile("retention_follow")

    assert default_profile.committee_fragile_breakout_risk_enabled is False
    assert ignition_breakout.committee_fragile_breakout_risk_enabled is True
    assert retention_follow.committee_fragile_breakout_risk_enabled is True


def test_committee_fragile_breakout_risk_penalizes_crowded_weak_breakout_more_than_healthy_leader() -> None:
    healthy_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.060,
                "flow_60": 0.12,
                "persist_120": 0.72,
                "close_support_30": 0.12,
                "retention_proxy": 0.82,
                "attention_composite": 0.92,
                "turnover_ratio_20": 1.10,
                "limit_up_memory_259": 0.18,
                "candidate_pool_avg_amount_share_of_cutoff": 1.35,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    weak_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.025,
                "flow_60": 0.00,
                "persist_120": 0.36,
                "close_support_30": 0.01,
                "retention_proxy": 0.48,
                "attention_composite": 0.88,
                "turnover_ratio_20": 2.60,
                "limit_up_memory_259": 0.90,
                "candidate_pool_avg_amount_share_of_cutoff": 0.88,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert healthy_snapshot["committee_components"]["fragile_breakout_risk_raw_100"] < 35.0
    assert weak_snapshot["committee_components"]["fragile_breakout_risk_raw_100"] > 65.0
    assert weak_snapshot["committee_components"]["fragile_breakout_quality_raw_100"] < healthy_snapshot["committee_components"]["fragile_breakout_quality_raw_100"]
    assert weak_snapshot["alpha_edge_score"] < healthy_snapshot["alpha_edge_score"]


def test_committee_fragile_breakout_risk_keeps_output_when_some_raw_inputs_are_missing() -> None:
    entry = _make_committee_entry(
        metrics={
            "retention_proxy": 0.78,
            "close_support_30": 0.04,
        }
    )
    entry["historical_prior"]["btst_regime_gate"] = "normal_trade"
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=entry,
        profile_name="retention_follow",
        profile_overrides=_base_profile_overrides(),
    )

    assert "fragile_breakout_activation_raw_100" in snapshot["committee_components"]
    assert "fragile_breakout_fragility_raw_100" in snapshot["committee_components"]
    assert snapshot["committee_component_sources"]["fragile_breakout_risk_raw_100"] == "derived:fragile_breakout_formula"


def test_evaluate_short_trade_rejected_target_surfaces_fragile_breakout_committee_components() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.025,
                "flow_60": 0.00,
                "persist_120": 0.36,
                "close_support_30": 0.01,
                "retention_proxy": 0.48,
                "attention_composite": 0.88,
                "turnover_ratio_20": 2.60,
                "limit_up_memory_259": 0.90,
                "candidate_pool_avg_amount_share_of_cutoff": 0.88,
            }
        ),
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert "fragile_breakout_risk_raw_100" in result.metrics_payload["committee"]["components"]
    assert result.metrics_payload["committee"]["component_sources"]["fragile_breakout_risk_raw_100"] == "derived:fragile_breakout_formula"


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


def test_metrics_payload_exposes_prior_retention_score_alias() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_committee_entry(),
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert result.metrics_payload["prior_retention_score"] == pytest.approx(round(result.metrics_payload["historical_continuation_prior_score"]["score"], 4))


def test_retention_group_uses_failed_breakout_metric_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "retention_proxy": 0.78,
                "supply_pressure_60": 0.08,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    degraded_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "retention_proxy": 0.78,
                "supply_pressure_60": 0.08,
                "failed_breakout_10": 3,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_component_sources"]["retention_raw_100"] == "raw:retention_metrics"
    assert degraded_snapshot["committee_component_sources"]["retention_raw_100"] == "raw:retention_metrics"
    assert degraded_snapshot["committee_components"]["retention_raw_100"] < baseline_snapshot["committee_components"]["retention_raw_100"]


def test_retention_group_shrinks_historical_prior_support_when_evidence_is_thin() -> None:
    low_evidence_entry = _make_committee_entry()
    low_evidence_entry["metrics"] = {}
    low_evidence_entry["historical_prior"].update(
        {
            "evaluable_count": 2,
            "next_close_positive_rate": 0.68,
            "next_high_hit_rate_at_threshold": 0.72,
            "next_open_to_close_return_mean": 0.019,
        }
    )
    high_evidence_entry = _make_committee_entry()
    high_evidence_entry["metrics"] = {}
    high_evidence_entry["historical_prior"].update(
        {
            "evaluable_count": 12,
            "next_close_positive_rate": 0.68,
            "next_high_hit_rate_at_threshold": 0.72,
            "next_open_to_close_return_mean": 0.019,
        }
    )

    low_evidence_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=low_evidence_entry,
        profile_overrides=_base_profile_overrides(),
    )
    high_evidence_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=high_evidence_entry,
        profile_overrides=_base_profile_overrides(),
    )

    assert low_evidence_snapshot["committee_component_sources"]["retention_raw_100"] == "raw:retention_metrics"
    assert high_evidence_snapshot["committee_component_sources"]["retention_raw_100"] == "raw:retention_metrics"
    assert low_evidence_snapshot["historical_continuation_prior_score"]["score"] < high_evidence_snapshot["historical_continuation_prior_score"]["score"]
    assert low_evidence_snapshot["committee_components"]["retention_raw_100"] < high_evidence_snapshot["committee_components"]["retention_raw_100"]


def test_retention_group_penalizes_negative_payoff_continuation_history() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "retention_proxy": 0.78,
                "supply_pressure_60": 0.08,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    adverse_entry = _make_committee_entry(
        metrics={
            "retention_proxy": 0.78,
            "supply_pressure_60": 0.08,
        }
    )
    adverse_entry["historical_prior"].update(
        {
            "evaluable_count": 9,
            "next_close_positive_rate": 0.56,
            "next_high_hit_rate_at_threshold": 0.78,
            "next_open_to_close_return_mean": -0.006,
        }
    )
    adverse_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=adverse_entry,
        profile_overrides=_base_profile_overrides(),
    )

    assert adverse_snapshot["committee_components"]["retention_raw_100"] < baseline_snapshot["committee_components"]["retention_raw_100"]
    assert adverse_snapshot["beta_execution_score"] < baseline_snapshot["beta_execution_score"]
    assert adverse_snapshot["committee_component_sources"]["retention_raw_100"] == "raw:retention_metrics"


def test_flow_group_uses_persist_metric_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "flow_60": 0.04,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    improved_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "flow_60": 0.04,
                "persist_120": 0.70,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_components"]["flow_raw_100"] == pytest.approx(60.0)
    assert improved_snapshot["committee_components"]["flow_raw_100"] > baseline_snapshot["committee_components"]["flow_raw_100"]


def test_flow_group_uses_close_support_metric_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "flow_60": 0.04,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    improved_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "flow_60": 0.04,
                "close_support_30": 0.10,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_components"]["flow_raw_100"] == pytest.approx(60.0)
    assert improved_snapshot["committee_component_sources"]["flow_raw_100"] == "raw:flow_metrics"
    assert improved_snapshot["committee_components"]["flow_raw_100"] > baseline_snapshot["committee_components"]["flow_raw_100"]


def test_flow_raw_score_uses_source_aware_bar_proxy_thresholds_for_persist_120() -> None:
    exact_tick_score, source = _flow_raw_score(
        {},
        {
            "flow_60": 0.04,
            "persist_120": 0.50,
            "persist_120_source": "exact_tick",
        },
    )
    bar_proxy_score, _ = _flow_raw_score(
        {},
        {
            "flow_60": 0.04,
            "persist_120": 0.50,
            "persist_120_source": "bar_proxy",
        },
    )

    assert source == "raw:flow_metrics"
    assert exact_tick_score == pytest.approx(51.4286, abs=1e-4)
    assert bar_proxy_score == pytest.approx(60.0, abs=1e-4)


def test_flow_raw_score_keeps_exact_tick_persist_thresholds_unchanged() -> None:
    score, source = _flow_raw_score(
        {},
        {
            "flow_60": 0.04,
            "persist_120": 0.60,
            "persist_120_source": "exact_tick",
        },
    )

    assert source == "raw:flow_metrics"
    assert score == pytest.approx(66.4286, abs=1e-4)


def test_flow_raw_score_relaxes_bar_proxy_midband_for_realistic_persist_120_values() -> None:
    score, source = _flow_raw_score(
        {},
        {
            "flow_60": 0.04,
            "persist_120": 0.4333,
            "persist_120_source": "bar_proxy",
        },
    )

    assert source == "raw:flow_metrics"
    assert score == pytest.approx(60.0, abs=1e-4)


def test_sector_group_uses_breadth_follow_and_catalyst_metrics_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.025,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    improved_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.025,
                "sector_breadth_3": 0.35,
                "follow_ratio_2": 0.30,
                "catalyst_freshness": 0.70,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_components"]["sector_raw_100"] == pytest.approx(60.0)
    assert improved_snapshot["committee_component_sources"]["sector_raw_100"] == "raw:sector_metrics"
    assert improved_snapshot["committee_components"]["sector_raw_100"] > baseline_snapshot["committee_components"]["sector_raw_100"]


def test_attention_group_uses_dragon_tiger_bonus_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "attention_composite": 0.50,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    improved_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "attention_composite": 0.50,
                "dragon_tiger_bonus": 1.0,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_components"]["attention_raw_100"] == pytest.approx(60.0)
    assert improved_snapshot["committee_components"]["attention_raw_100"] > baseline_snapshot["committee_components"]["attention_raw_100"]


def test_attention_group_uses_turnover_and_limit_up_memory_when_present() -> None:
    baseline_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "attention_composite": 0.50,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )
    improved_snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "attention_composite": 0.50,
                "turnover_ratio_20": 2.20,
                "limit_up_memory_259": 0.80,
            }
        ),
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_snapshot["committee_components"]["attention_raw_100"] == pytest.approx(60.0)
    assert improved_snapshot["committee_component_sources"]["attention_raw_100"] == "raw:attention_metrics"
    assert improved_snapshot["committee_components"]["attention_raw_100"] > baseline_snapshot["committee_components"]["attention_raw_100"]


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


def test_market_state_auto_profile_switch_overrides_historical_prior_gate() -> None:
    entry = _make_committee_entry()
    entry["historical_prior"]["btst_regime_gate"] = "shadow_only"
    entry["market_state"] = {
        "breadth_ratio": 0.67,
        "daily_return": -0.003,
        "style_dispersion": 0.18,
        "regime_flip_risk": 0.09,
        "regime_gate_level": "normal",
        "btst_regime_gate": {
            "gate": "shadow_only",
            "profile_hint": "conservative",
            "reason_codes": ["profile_conservative"],
            "metrics": {
                "breadth_ratio": 0.41,
                "daily_return": 0.012,
                "style_dispersion": 0.55,
                "regime_flip_risk": 0.60,
                "regime_gate_level": "normal",
            },
        },
    }

    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=entry,
    )

    assert snapshot["profile"].name == "ignition_breakout"
    assert snapshot["committee_profile"] == "ignition_breakout"
    assert snapshot["committee_gate"] == "aggressive_trade"


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


def test_committee_isolated_attention_veto_uses_direct_flow_60_threshold() -> None:
    entry = _make_committee_entry(
        metrics={
            "attention_composite": 0.88,
            "sector_amt_share": 0.010,
            "flow_60": 0.00,
            "persist_120": 0.70,
            "close_support_30": 0.10,
        }
    )

    vetoed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert vetoed_result.decision == "rejected"
    assert "committee_isolated_attention_veto" in vetoed_result.blockers
    assert "committee_isolated_attention_veto" in vetoed_result.committee_vetoes


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


def test_committee_gap_to_limit_veto_rejects_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "gap_to_limit": 0.005,
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
    assert "committee_gap_to_limit_veto" in vetoed_result.blockers
    assert "committee_gap_to_limit_veto" in vetoed_result.committee_vetoes
    assert vetoed_result.gate_status["committee"] == "veto"


def test_committee_failed_breakout_history_veto_rejects_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "close_structure": 0.30,
            "close_support_30": 0.05,
        }
    )
    entry["historical_prior"]["execution_quality_label"] = "gap_chase_risk"

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
    assert "committee_failed_breakout_history_veto" in vetoed_result.blockers
    assert "committee_failed_breakout_history_veto" in vetoed_result.committee_vetoes
    assert vetoed_result.gate_status["committee"] == "veto"


def test_committee_failed_breakout_metric_veto_rejects_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "supply_pressure_60": 0.08,
            "close_structure": 0.30,
            "close_support_30": 0.05,
            "failed_breakout_10": 3,
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
    assert "committee_failed_breakout_metric_veto" in vetoed_result.blockers
    assert "committee_failed_breakout_metric_veto" in vetoed_result.committee_vetoes
    assert vetoed_result.gate_status["committee"] == "veto"


def test_committee_uses_short_trade_boundary_metrics_when_entry_metrics_missing() -> None:
    entry = _make_committee_entry(metrics={})
    entry["short_trade_boundary_metrics"] = {
        "sector_amt_share": 0.060,
        "flow_60": 0.12,
        "retention_proxy": 0.78,
        "supply_pressure_60": 0.08,
        "close_structure": 0.30,
        "close_support_30": 0.05,
        "failed_breakout_10": 3,
    }

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
    assert "committee_failed_breakout_metric_veto" in vetoed_result.blockers


def test_committee_sector_hard_gate_blocks_formal_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.010,
            "flow_60": 0.08,
            "retention_proxy": 0.72,
            "attention_composite": 0.52,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_sector_hard_gate_failed" in governed_result.downgrade_reasons
    assert "committee_negative_sector_or_flow_block" in governed_result.downgrade_reasons


def test_committee_penalty_total_blocks_formal_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "amount_ratio_5": 2.10,
            "turnover_ratio_20": 2.60,
            "limit_up_memory_259": 0.85,
            "close_structure": 0.48,
            "close_support_30": 0.03,
            "supply_pressure_60": 0.30,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_penalty_total_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["components"]["penalty_total"] > 0.12


def test_committee_kill_switch_downgrades_aggressive_gate_to_normal_profile() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.060,
                "flow_60": 0.12,
                "retention_proxy": 0.78,
                "rolling_8_trade_close_win_rate": 0.30,
            }
        ),
    )

    assert snapshot["committee_gate"] == "aggressive_trade"
    assert snapshot["committee_effective_gate"] == "normal_trade"
    assert snapshot["committee_profile"] == "retention_follow"
    assert snapshot["committee_kill_switch"]["active"] is True
    assert "rolling_8_trade_close_win_rate" in snapshot["committee_kill_switch"]["triggered_metrics"]


def test_committee_kill_switch_blocks_normal_trade_formal_selection() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "rolling_shadow_minus_formal_close_rate": 0.10,
        }
    )
    entry["historical_prior"]["btst_regime_gate"] = "normal_trade"

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "blocked"
    assert "committee_kill_switch_active" in governed_result.blockers
    assert governed_result.metrics_payload["committee"]["kill_switch"]["effective_gate"] == "shadow_only"


def test_committee_kill_switch_recovery_window_keeps_normal_trade_blocked() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "kill_switch_recovery_trade_count": 5.0,
            "kill_switch_recovery_day_count": 7.0,
        }
    )
    entry["historical_prior"]["btst_regime_gate"] = "normal_trade"

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "blocked"
    assert "committee_kill_switch_active" in governed_result.blockers
    assert governed_result.metrics_payload["committee"]["kill_switch"]["active"] is True
    assert governed_result.metrics_payload["committee"]["kill_switch"]["recovery_pending"] is True
    assert governed_result.metrics_payload["committee"]["kill_switch"]["effective_gate"] == "shadow_only"


def test_committee_theme_exposure_cap_blocks_formal_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "projected_theme_exposure": 0.26,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_theme_exposure_cap_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["thresholds"]["theme_exposure_cap"] == pytest.approx(0.25)


def test_committee_theme_exposure_cap_allows_candidate_exactly_at_default_total_exposure_cap() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "projected_theme_exposure": 0.25,
        }
    )

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "selected"
    assert "committee_theme_exposure_cap_exceeded" not in governed_result.downgrade_reasons


def test_committee_incremental_theme_exposure_cap_blocks_formal_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "incremental_theme_exposure": 0.19,
        }
    )

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "near_miss"
    assert "committee_incremental_theme_exposure_cap_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["thresholds"]["incremental_theme_exposure_cap"] == pytest.approx(0.18)
    assert governed_result.metrics_payload["committee"]["components"]["incremental_theme_exposure"] == pytest.approx(0.19)


def test_committee_incremental_theme_exposure_cap_allows_candidate_exactly_at_cap() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "incremental_theme_exposure": 0.18,
        }
    )

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "selected"
    assert "committee_incremental_theme_exposure_cap_exceeded" not in governed_result.downgrade_reasons


def test_committee_isolated_theme_direction_blocks_formal_selected_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "theme_direction_peer_count": 1,
            "theme_direction_rank": 2,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_isolated_theme_direction_block" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["components"]["theme_direction_peer_count"] == pytest.approx(1.0)


def test_committee_theme_direction_rank_cap_blocks_sixth_theme_candidate() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "theme_direction_peer_count": 2,
            "theme_direction_rank": 6,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_theme_direction_rank_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["components"]["theme_direction_rank"] == pytest.approx(6.0)


def test_committee_gap_risk_cap_blocks_formal_selected_candidate_between_veto_and_rollout_bands() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "gap_to_limit": 0.015,
        }
    )

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
        profile_overrides=_base_profile_overrides(),
    )

    assert baseline_result.decision == "selected"
    assert governed_result.decision == "near_miss"
    assert "committee_gap_risk_cap_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["components"]["gap_risk_raw_100"] == pytest.approx(80.0)


def test_committee_gap_risk_cap_leaves_disabled_committee_payload_selected() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.060,
                "flow_60": 0.12,
                "retention_proxy": 0.78,
                "gap_to_limit": 0.015,
            }
        ),
        profile_overrides={**_base_profile_overrides(), "committee_enabled": False},
    )

    assert snapshot["committee_enabled"] is False
    assert snapshot["committee_selected_pass"] is True
    assert snapshot["committee_gate_status"]["formal_selected"] == "pass"
    assert "committee_gap_risk_cap_exceeded" not in snapshot["committee_fail_reasons"]


def test_committee_gap_risk_cap_allows_candidate_exactly_at_rollout_safe_boundary() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "gap_to_limit": 0.02,
        }
    )

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "selected"
    assert "committee_gap_risk_cap_exceeded" not in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["components"]["gap_risk_raw_100"] == pytest.approx(60.0)


def test_committee_gap_risk_cap_blocks_advisory_continuation_lane_selection() -> None:
    entry = _make_committee_entry(
        metrics={
            "sector_amt_share": 0.060,
            "flow_60": 0.12,
            "retention_proxy": 0.78,
            "gap_to_limit": 0.015,
        }
    )
    entry["candidate_source"] = "catalyst_theme"
    entry["historical_prior"]["execution_quality_label"] = "close_continuation"
    entry["historical_prior"]["entry_timing_bias"] = "confirm_then_hold"

    governed_result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        rank_hint=1,
        profile_overrides=_base_profile_overrides(),
    )

    assert governed_result.decision == "near_miss"
    assert "committee_gap_risk_cap_exceeded" in governed_result.downgrade_reasons
    assert governed_result.metrics_payload["committee"]["thresholds"]["selected_enforced"] is False
    assert "catalyst_theme_continuation_lane" in governed_result.metrics_payload["committee"]["advisory_reasons"]
    assert governed_result.metrics_payload["committee"]["selected_pass"] is False
    assert governed_result.metrics_payload["committee"]["gate_status"]["formal_selected"] == "fail"


def test_runner_escape_promotes_high_upside_candidate_without_broadly_relaxing_committee() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.07,
                "flow_60": 0.20,
                "persist_120": 0.82,
                "close_support_30": 0.18,
                "retention_proxy": 0.86,
                "candidate_pool_avg_amount_share_of_cutoff": 1.30,
                "projected_theme_exposure": 0.22,
                "gap_risk_raw_100": 36.0,
            }
        ),
        profile_name="btst_runner_probe",
    )

    assert snapshot["committee_gate_status"]["runner_escape"] == "pass"
    assert snapshot["committee_gate_status"]["formal_selected"] in {"pass", "advisory"}


def test_runner_escape_rejects_gap_risky_or_illiquid_candidate() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.07,
                "flow_60": 0.18,
                "persist_120": 0.80,
                "close_support_30": 0.16,
                "retention_proxy": 0.82,
                "candidate_pool_avg_amount_share_of_cutoff": 0.70,
                "projected_theme_exposure": 0.38,
                "gap_risk_raw_100": 72.0,
            }
        ),
        profile_name="btst_runner_probe",
    )

    assert snapshot["committee_gate_status"]["runner_escape"] == "fail"


def test_runner_composite_score_present_in_committee_output() -> None:
    snapshot = build_short_trade_target_snapshot_from_entry(
        trade_date="20260328",
        entry=_make_committee_entry(
            metrics={
                "sector_amt_share": 0.07,
                "flow_60": 0.20,
                "persist_120": 0.82,
                "close_support_30": 0.18,
                "retention_proxy": 0.86,
                "candidate_pool_avg_amount_share_of_cutoff": 1.30,
                "projected_theme_exposure": 0.22,
                "gap_risk_raw_100": 36.0,
            }
        ),
        profile_name="btst_runner_probe",
    )
    assert "runner_composite_score" in snapshot
    score = snapshot["runner_composite_score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_runner_composite_score_zero_when_signals_absent() -> None:
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    assert compute_runner_composite_score({}) == 0.0
    assert compute_runner_composite_score({"breakout_freshness": None}) == 0.0


def test_runner_composite_score_direct_computation() -> None:
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    score = compute_runner_composite_score({
        "breakout_freshness": 0.80,
        "trend_acceleration": 0.70,
        "volume_expansion_quality": 0.60,
        "catalyst_freshness": 0.50,
    })
    # 0.40*0.80 + 0.30*0.70 + 0.20*0.60 + 0.10*0.50 = 0.32+0.21+0.12+0.05 = 0.70
    assert abs(score - 0.70) < 0.001


def test_runner_composite_score_uses_profile_weights() -> None:
    """compute_runner_composite_score reads weight fields from profile when provided."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    class FakeProfile:
        runner_composite_score_breakout_weight = 0.50
        runner_composite_score_trend_weight = 0.25
        runner_composite_score_volume_weight = 0.15
        runner_composite_score_catalyst_weight = 0.10

    snapshot = {
        "breakout_freshness": 0.80,
        "trend_acceleration": 0.70,
        "volume_expansion_quality": 0.60,
        "catalyst_freshness": 0.50,
    }
    # default weights: 0.40*0.80+0.30*0.70+0.20*0.60+0.10*0.50 = 0.70
    default_score = compute_runner_composite_score(snapshot)
    assert abs(default_score - 0.70) < 0.001

    # custom profile weights: 0.50*0.80+0.25*0.70+0.15*0.60+0.10*0.50 = 0.40+0.175+0.09+0.05 = 0.715
    profile_score = compute_runner_composite_score(snapshot, profile=FakeProfile())
    assert abs(profile_score - 0.715) < 0.001
    assert abs(profile_score - default_score) > 0.001  # must differ from default
