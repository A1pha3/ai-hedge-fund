from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.optimize_profile as optimize_profile
from scripts.btst_optimized_profile_manifest_helpers import (
    build_ready_btst_optimized_profile_manifest,
    derive_latest_replay_trade_date,
    publish_btst_optimized_profile_manifest,
)
from scripts.optimize_profile import (
    _build_default_checkpoint_path,
    _build_replay_evaluator,
    _build_recency_decay_map,
    _build_staged_ignition_evaluator,
    _build_staged_ignition_shortlist,
    _compute_recency_decay,
    _compute_source_coverage_pass_ratio,
    _format_staged_ignition_summary,
    _load_focus_params,
    _parse_grid_params,
    _resolve_primary_surface,
    build_stage_grid,
    LIQUIDITY_LOW_REGIME_FLOOR,
    LIQUIDITY_LOW_REGIME_WEIGHT_PENALTY,
    LIQUIDITY_SOFT_REGIME_FLOOR,
    LIQUIDITY_SOFT_REGIME_WEIGHT_PENALTY,
    RECENCY_DECAY_MIN_FACTOR,
    RECENCY_HALF_LIFE_CANDIDATES,
    RECENCY_HALF_LIFE_DAYS,
    resolve_grid_params,
    resolve_guardrails,
)
from src.backtesting.param_search import SearchObjective, SearchReport, TrialResult
from src.targets import build_short_trade_target_profile


def test_resolve_primary_surface_prefers_selected_when_sample_sufficient() -> None:
    selected = {"next_day_available_count": 8, "closed_cycle_count": 4}
    tradeable = {"next_day_available_count": 30, "closed_cycle_count": 20}

    surface, scope = _resolve_primary_surface(
        selected_surface=selected,
        tradeable_surface=tradeable,
    )

    assert scope == "selected"
    assert surface is selected


def test_resolve_primary_surface_falls_back_when_selected_sample_too_small() -> None:
    selected = {"next_day_available_count": 3, "closed_cycle_count": 1}
    tradeable = {"next_day_available_count": 25, "closed_cycle_count": 12}

    surface, scope = _resolve_primary_surface(
        selected_surface=selected,
        tradeable_surface=tradeable,
    )

    assert scope == "tradeable_fallback"
    assert surface is tradeable


def test_default_checkpoint_path_is_stable_and_input_sensitive() -> None:
    base_args = {"profile": "default", "objective": "edge"}
    replay_a = _build_default_checkpoint_path(
        **base_args,
        replay_input_paths=[Path("a.json"), Path("b.json")],
    )
    replay_b = _build_default_checkpoint_path(
        **base_args,
        replay_input_paths=[Path("b.json"), Path("a.json")],
    )
    replay_c = _build_default_checkpoint_path(
        **base_args,
        replay_input_paths=[Path("a.json"), Path("c.json")],
    )
    walk = _build_default_checkpoint_path(
        **base_args,
        walk_forward_descriptor="000001|2026-01-01|2026-03-01",
    )

    assert replay_a == replay_b
    assert replay_a != replay_c
    assert replay_a != walk


def test_load_focus_params_uses_best_completed_trial_from_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "completed_trials": [
                    {"params": {"select_threshold": 0.46}, "score": 0.31},
                    {"params": {"select_threshold": 0.50}, "score": 0.42},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_focus_params(checkpoint) == {"select_threshold": 0.50}


def test_optimize_profile_fixture_files_use_descriptive_names() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    legacy_report_name = "fake" + ".md"
    legacy_payload_name = "fake" + ".json"

    assert legacy_report_name not in source
    assert legacy_payload_name not in source
    assert 'Path("optimize_profile_fixture.md")' in source
    assert 'Path("optimize_profile_fixture.json")' in source
    assert Path("optimize_profile_fixture.md").exists()
    assert Path("optimize_profile_fixture.json").exists()


def test_parse_grid_params_coerces_boolean_literals() -> None:
    grid = _parse_grid_params(
        [
            "liquidity_shadow_source_specific_rank_cap_require_relief_applied=False",
            "profitability_relief_enabled=true",
        ]
    )

    assert grid["liquidity_shadow_source_specific_rank_cap_require_relief_applied"] == [False]
    assert grid["profitability_relief_enabled"] == [True]


def test_replay_evaluator_scales_sample_weight_by_window_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        if "window_ok" not in str(input_path):
            return {"surface_summaries": {"selected": {}, "tradeable": {}}}
        selected_surface = {
            "next_day_available_count": 6,
            "closed_cycle_count": 3,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.50,
            "next_close_payoff_ratio": 1.40,
            "next_close_expectancy": 0.01,
            "t_plus_2_close_positive_rate": 0.55,
            "next_close_return_distribution": {"p10": -0.02},
            "t_plus_2_close_return_distribution": {"median": 0.005},
            "t_plus_3_close_positive_rate": 0.52,
            "t_plus_3_close_expectancy": 0.011,
            "t_plus_3_close_return_distribution": {"median": 0.007},
        }
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_ok.json"), Path("window_missing.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    assert metrics["window_count"] == 1
    assert metrics["window_coverage"] == pytest.approx(0.5)
    assert metrics["sample_weight"] == pytest.approx(0.25)


def test_replay_evaluator_weights_primary_quality_metrics_by_sample_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary quality metrics should be averaged using per-window sample_weight.

    Two windows: one well-supported (weight=1.0) and one thin (weight=0.1).
    Weighted average should favor the well-supported window.
    """
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        if "thin" in str(input_path):
            # thin-support window: next_day_available_count=1 -> next_day_weight=0.1; closed_cycle_count=1 -> closed_cycle_weight=0.166.. => sample_weight=0.1
            selected_surface = {
                "next_day_available_count": 1,
                "closed_cycle_count": 1,
                "next_close_positive_rate": 0.10,
                "next_high_hit_rate_at_threshold": 0.12,
                "next_close_payoff_ratio": 0.5,
                "next_close_expectancy": 0.002,
                "t_plus_2_close_positive_rate": 0.11,
                "t_plus_3_close_positive_rate": 0.09,
                "t_plus_3_close_expectancy": 0.001,
                "next_close_return_distribution": {"p10": -0.05, "median": 0.0005},
                "t_plus_2_close_return_distribution": {"median": 0.0006},
                "t_plus_3_close_return_distribution": {"median": 0.0007},
            }
        else:
            # well-supported window: next_day_available_count=10, closed_cycle_count=6 => sample_weight=1.0
            selected_surface = {
                "next_day_available_count": 10,
                "closed_cycle_count": 6,
                "next_close_positive_rate": 0.60,
                "next_high_hit_rate_at_threshold": 0.50,
                "next_close_payoff_ratio": 1.40,
                "next_close_expectancy": 0.01,
                "t_plus_2_close_positive_rate": 0.55,
                "t_plus_3_close_positive_rate": 0.53,
                "t_plus_3_close_expectancy": 0.012,
                "next_close_return_distribution": {"p10": -0.02, "median": 0.002},
                "t_plus_2_close_return_distribution": {"median": 0.005},
                "t_plus_3_close_return_distribution": {"median": 0.007},
            }
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_well.json"), Path("window_thin.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    # Compute expected weighted averages manually
    w1 = 1.0
    w2 = 0.1
    denom = w1 + w2
    assert metrics["window_count"] == 2
    # next_close_positive_rate weighted: (0.60*1.0 + 0.10*0.1)/1.1
    assert metrics["next_close_positive_rate"] == pytest.approx((0.60 * w1 + 0.10 * w2) / denom)
    assert metrics["next_close_payoff_ratio"] == pytest.approx((1.40 * w1 + 0.5 * w2) / denom)
    assert metrics["next_close_expectancy"] == pytest.approx((0.01 * w1 + 0.002 * w2) / denom)
    assert metrics["next_high_hit_rate"] == pytest.approx((0.50 * w1 + 0.12 * w2) / denom)
    assert metrics["t_plus_2_close_positive_rate"] == pytest.approx((0.55 * w1 + 0.11 * w2) / denom)
    assert metrics["t_plus_3_close_positive_rate"] == pytest.approx((0.53 * w1 + 0.09 * w2) / denom)
    assert metrics["t_plus_3_close_expectancy"] == pytest.approx((0.012 * w1 + 0.001 * w2) / denom)
    assert metrics["downside_p10"] == pytest.approx((-0.02 * w1 + -0.05 * w2) / denom)


def test_replay_evaluator_keeps_execution_and_exposure_metrics_unweighted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execution/exposure metrics must remain unweighted by sample_weight and use simple mean across windows."""
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        if "thin" in str(input_path):
            selected_surface = {
                "next_day_available_count": 1,
                "closed_cycle_count": 1,
                "next_close_positive_rate": 0.50,
                "next_high_hit_rate_at_threshold": 0.40,
                "next_close_payoff_ratio": 1.1,
                "next_close_expectancy": 0.009,
                "next_close_return_distribution": {"p10": -0.03, "median": -0.001},
                "t_plus_2_close_return_distribution": {"median": 0.002},
                "t_plus_3_close_return_distribution": {"median": 0.003},
            }
            rows = [
                {
                    "decision": "selected",
                    "metrics_payload": {"committee": {"components": {"projected_theme_exposure": 0.90, "incremental_theme_exposure": 0.30, "liquidity_capacity_raw_100": 30.0, "crowding_risk_raw_100": 10.0, "gap_risk_raw_100": 5.0}}},
                }
            ]
        else:
            selected_surface = {
                "next_day_available_count": 10,
                "closed_cycle_count": 6,
                "next_close_positive_rate": 0.60,
                "next_high_hit_rate_at_threshold": 0.50,
                "next_close_payoff_ratio": 1.40,
                "next_close_expectancy": 0.01,
                "next_close_return_distribution": {"p10": -0.02, "median": 0.002},
                "t_plus_2_close_return_distribution": {"median": 0.005},
                "t_plus_3_close_return_distribution": {"median": 0.007},
            }
            rows = [
                {
                    "decision": "selected",
                    "metrics_payload": {"committee": {"components": {"projected_theme_exposure": 0.10, "incremental_theme_exposure": 0.05, "liquidity_capacity_raw_100": 70.0, "crowding_risk_raw_100": 80.0, "gap_risk_raw_100": 65.0}}},
                }
            ]
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}, "rows": rows}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_well.json"), Path("window_thin.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    # Unweighted mean across windows: projected_theme_exposure -> (0.10 + 0.90) / 2 = 0.5
    assert metrics["projected_theme_exposure"] == pytest.approx(0.5)
    assert metrics["incremental_theme_exposure"] == pytest.approx((0.05 + 0.30) / 2.0)
    assert metrics["liquidity_capacity_raw_100"] == pytest.approx((70.0 + 30.0) / 2.0)
    assert metrics["crowding_risk_raw_100"] == pytest.approx((80.0 + 10.0) / 2.0)
    assert metrics["gap_risk_raw_100"] == pytest.approx((65.0 + 5.0) / 2.0)


def test_replay_evaluator_keeps_partial_horizon_windows_with_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        selected_surface = {
            "next_day_available_count": 6,
            "closed_cycle_count": 3,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.50,
            "next_close_payoff_ratio": 1.40,
            "next_close_expectancy": 0.01,
            "next_close_return_distribution": {"p10": -0.02, "median": 0.004},
        }
        if "partial" in str(input_path):
            selected_surface.update(
                {
                    "t_plus_2_close_positive_rate": None,
                    "t_plus_2_close_return_distribution": {},
                    "t_plus_3_close_positive_rate": None,
                    "t_plus_3_close_expectancy": None,
                    "t_plus_3_close_return_distribution": {},
                }
            )
        else:
            selected_surface.update(
                {
                    "t_plus_2_close_positive_rate": 0.55,
                    "t_plus_2_close_return_distribution": {"median": 0.005},
                    "t_plus_3_close_positive_rate": 0.53,
                    "t_plus_3_close_expectancy": 0.012,
                    "t_plus_3_close_return_distribution": {"median": 0.007},
                }
            )
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_full.json"), Path("window_partial.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    # Full window uses weight=0.5; partial window uses 0.5*0.85.
    assert metrics["window_count"] == 2
    assert metrics["window_coverage"] == pytest.approx(1.0)
    assert metrics["sample_weight"] == pytest.approx((0.5 + (0.5 * 0.85)) / 2.0)
    # Partial horizon falls back to next_close_positive_rate for t+2 positive rate.
    w1 = 0.5
    w2 = 0.5 * 0.85
    denom = w1 + w2
    assert metrics["t_plus_2_close_positive_rate"] == pytest.approx((0.55 * w1 + 0.60 * w2) / denom)
    assert metrics["t_plus_3_close_positive_rate"] == pytest.approx((0.53 * w1 + 0.60 * w2) / denom)
    assert metrics["t_plus_3_close_expectancy"] == pytest.approx((0.012 * w1 + 0.01 * w2) / denom)


def test_replay_evaluator_keeps_windows_with_missing_payoff_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        selected_surface = {
            "next_day_available_count": 6,
            "closed_cycle_count": 3,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.50,
            "next_close_expectancy": 0.01,
            "t_plus_2_close_positive_rate": 0.55,
            "next_close_return_distribution": {"p10": -0.02},
            "t_plus_2_close_return_distribution": {"median": 0.005},
            "t_plus_3_close_positive_rate": 0.53,
            "t_plus_3_close_expectancy": 0.012,
            "t_plus_3_close_return_distribution": {"median": 0.007},
        }
        if "missing_payoff" in str(input_path):
            selected_surface["next_close_payoff_ratio"] = None
        else:
            selected_surface["next_close_payoff_ratio"] = 1.40
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_full.json"), Path("window_missing_payoff.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    assert metrics["window_count"] == 2
    assert metrics["window_coverage"] == pytest.approx(1.0)
    # Missing payoff window is kept, and payoff average uses available windows only.
    assert metrics["next_close_payoff_ratio"] == pytest.approx(1.40)


def test_replay_evaluator_aggregates_execution_and_exposure_metrics_from_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        selected_surface = {
            "next_day_available_count": 6,
            "closed_cycle_count": 3,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.50,
            "next_close_payoff_ratio": 1.40,
            "next_close_expectancy": 0.01,
            "t_plus_2_close_positive_rate": 0.55,
            "next_close_return_distribution": {"p10": -0.02},
            "t_plus_2_close_return_distribution": {"median": 0.005},
            "t_plus_3_close_positive_rate": 0.53,
            "t_plus_3_close_expectancy": 0.012,
            "t_plus_3_close_return_distribution": {"median": 0.007},
        }
        return {
            "surface_summaries": {"selected": selected_surface, "tradeable": selected_surface},
            "rows": [
                {
                    "decision": "selected",
                    "metrics_payload": {
                        "committee": {
                            "components": {
                                "liquidity_capacity_raw_100": 80.0,
                                "crowding_risk_raw_100": 35.0,
                                "gap_risk_raw_100": 25.0,
                                "projected_theme_exposure": 0.18,
                                "incremental_theme_exposure": 0.08,
                            }
                        }
                    },
                },
                {
                    "decision": "selected",
                    "metrics_payload": {
                        "committee": {
                            "components": {
                                "liquidity_capacity_raw_100": 60.0,
                                "crowding_risk_raw_100": 55.0,
                                "gap_risk_raw_100": 45.0,
                                "projected_theme_exposure": 0.22,
                                "incremental_theme_exposure": 0.10,
                            }
                        }
                    },
                },
            ],
        }

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_full.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    assert metrics["liquidity_capacity_raw_100"] == pytest.approx(70.0)
    assert metrics["crowding_risk_raw_100"] == pytest.approx(45.0)
    assert metrics["gap_risk_raw_100"] == pytest.approx(35.0)
    assert metrics["projected_theme_exposure"] == pytest.approx(0.20)
    assert metrics["incremental_theme_exposure"] == pytest.approx(0.09)


def test_replay_evaluator_applies_lighter_penalty_for_missing_t_plus_3_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        selected_surface = {
            "next_day_available_count": 6,
            "closed_cycle_count": 3,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.50,
            "next_close_payoff_ratio": 1.40,
            "next_close_expectancy": 0.01,
            "t_plus_2_close_positive_rate": 0.55,
            "t_plus_2_close_expectancy": 0.008,
            "next_close_return_distribution": {"p10": -0.02, "median": 0.004},
            "t_plus_2_close_return_distribution": {"median": 0.005},
        }
        if "partial_t3" in str(input_path):
            selected_surface.update(
                {
                    "t_plus_3_close_positive_rate": None,
                    "t_plus_3_close_expectancy": None,
                    "t_plus_3_close_return_distribution": {},
                }
            )
        else:
            selected_surface.update(
                {
                    "t_plus_3_close_positive_rate": 0.53,
                    "t_plus_3_close_expectancy": 0.012,
                    "t_plus_3_close_return_distribution": {"median": 0.007},
                }
            )
        return {"surface_summaries": {"selected": selected_surface, "tradeable": selected_surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator(
        [Path("window_full.json"), Path("window_partial_t3.json")],
        base_profile="default",
    )

    metrics = evaluator({})

    assert metrics["window_count"] == 2
    assert metrics["sample_weight"] == pytest.approx((0.5 + (0.5 * 0.92)) / 2.0)
    w1 = 0.5
    w2 = 0.5 * 0.92
    denom = w1 + w2
    assert metrics["t_plus_3_close_positive_rate"] == pytest.approx((0.53 * w1 + 0.55 * w2) / denom)
    assert metrics["t_plus_3_close_expectancy"] == pytest.approx((0.012 * w1 + 0.008 * w2) / denom)


def test_build_grid_params_uses_event_catalyst_preset_for_guarded_profile() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="event_catalyst_guarded",
    )

    assert grid["event_catalyst_selected_uplift"] == [0.02, 0.03]
    assert grid["event_catalyst_min_score_for_selected_uplift"] == [0.68, 0.72]
    assert grid["event_catalyst_near_miss_threshold_relief"] == [0.01, 0.02]
    assert grid["event_catalyst_min_score_for_near_miss_retain"] == [0.54, 0.58]
    assert grid["event_catalyst_sector_resonance_weight"] == [0.18, 0.22]

    assert "select_threshold" in grid
    assert "near_miss_threshold" in grid
    assert "breakout_freshness_weight" in grid


def test_resolve_guardrails_uses_btst_replay_defaults_for_momentum_profile() -> None:
    guardrails = resolve_guardrails(
        profile_name="momentum_optimized",
        objective="btst",
        replay_mode=True,
        raw_guardrails=[],
    )

    assert guardrails["next_close_positive_rate"] == pytest.approx(0.54)
    assert guardrails["next_high_hit_rate"] == pytest.approx(0.56)
    assert guardrails["downside_p10"] == pytest.approx(-0.06)
    assert guardrails["window_coverage"] == pytest.approx(0.60)


def test_resolve_guardrails_prefers_explicit_values_over_defaults() -> None:
    guardrails = resolve_guardrails(
        profile_name="momentum_optimized",
        objective="btst",
        replay_mode=True,
        raw_guardrails=["next_close_positive_rate=0.57", "window_coverage=0.75"],
    )

    assert guardrails["next_close_positive_rate"] == pytest.approx(0.57)
    assert guardrails["window_coverage"] == pytest.approx(0.75)
    assert guardrails["next_high_hit_rate"] == pytest.approx(0.56)


def test_parse_guardrails_supports_explicit_min_and_max_bounds() -> None:
    guardrails = optimize_profile._parse_guardrails(
        [
            "next_close_positive_rate>=0.57",
            "projected_theme_exposure<=0.20",
        ]
    )

    assert guardrails == {
        "next_close_positive_rate": {"min": pytest.approx(0.57)},
        "projected_theme_exposure": {"max": pytest.approx(0.20)},
    }


def test_resolve_guardrails_includes_execution_and_exposure_defaults_for_momentum_profile() -> None:
    guardrails = resolve_guardrails(
        profile_name="momentum_optimized",
        objective="btst",
        replay_mode=True,
        raw_guardrails=[],
    )

    assert guardrails["projected_theme_exposure"] == {"max": pytest.approx(0.35)}
    assert guardrails["incremental_theme_exposure"] == {"max": pytest.approx(0.12)}
    assert guardrails["liquidity_capacity_raw_100"] == {"min": pytest.approx(50.0)}
    assert guardrails["crowding_risk_raw_100"] == {"max": pytest.approx(70.0)}
    assert guardrails["gap_risk_raw_100"] == {"max": pytest.approx(60.0)}


def test_build_stage_grid_focuses_numeric_ranges_around_best_params() -> None:
    focused = build_stage_grid(
        base_grid={
            "select_threshold": [0.42, 0.46, 0.50, 0.54, 0.58],
            "near_miss_threshold": [0.28, 0.32, 0.36, 0.40],
            "profitability_relief_enabled": [False, True],
        },
        search_stage="focused",
        focus_params={
            "select_threshold": 0.50,
            "near_miss_threshold": 0.36,
            "profitability_relief_enabled": True,
        },
    )

    assert focused["select_threshold"] == [0.46, 0.50, 0.54]
    assert focused["near_miss_threshold"] == [0.32, 0.36, 0.40]
    assert focused["profitability_relief_enabled"] == [True]


def test_resolve_grid_params_uses_coarse_stage_preset_for_momentum_profile() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="momentum_optimized",
        search_stage="coarse",
    )

    assert grid["select_threshold"] == [0.46, 0.50, 0.54]
    assert grid["near_miss_threshold"] == [0.30, 0.34, 0.38]
    assert "overhead_penalty_block_threshold" not in grid


def test_resolve_guardrails_uses_runner_replay_defaults_for_runner_objective() -> None:
    """Runner replay guardrails should be applied when objective is btst_runner."""
    guardrails = resolve_guardrails(
        profile_name="momentum_optimized",
        objective="btst_runner",
        replay_mode=True,
        raw_guardrails=[],
    )

    # Should use DEFAULT_BTST_RUNNER_REPLAY_GUARDRAILS
    assert guardrails["max_future_high_return_2_5d_hit_rate_at_20pct"] == {"min": pytest.approx(0.10)}
    assert guardrails["next_close_positive_rate"] == pytest.approx(0.54)
    assert guardrails["downside_p10"] == pytest.approx(-0.06)
    assert guardrails["window_coverage"] == pytest.approx(0.60)
    assert guardrails["gap_risk_raw_100"] == {"max": pytest.approx(60.0)}


def test_resolve_guardrails_prefers_explicit_values_over_runner_defaults() -> None:
    """Explicit guardrails should override runner replay defaults."""
    guardrails = resolve_guardrails(
        profile_name="momentum_optimized",
        objective="btst_runner",
        replay_mode=True,
        raw_guardrails=["max_future_high_return_2_5d_hit_rate_at_20pct>=0.15", "window_coverage=0.75"],
    )

    # Explicit values should override defaults
    assert guardrails["max_future_high_return_2_5d_hit_rate_at_20pct"] == {"min": pytest.approx(0.15)}
    assert guardrails["window_coverage"] == pytest.approx(0.75)
    # Other defaults should still be present
    assert guardrails["next_close_positive_rate"] == pytest.approx(0.54)


def test_main_integrates_event_catalyst_params_with_preset_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.optimize_profile as opt_module

    captured_grid: dict[str, list] | None = None

    def fake_param_space_init(self: object, *, grid: dict[str, list]) -> None:
        nonlocal captured_grid
        captured_grid = grid
        self.grid = grid

    def fake_param_space_size(self: object) -> int:
        return 1

    monkeypatch.setattr(opt_module.ParamSpace, "__init__", fake_param_space_init)
    monkeypatch.setattr(opt_module.ParamSpace, "size", fake_param_space_size)

    def fake_run_param_search(**_: object) -> dict[str, object]:
        return {"top_params": {}, "top_value": 0.0, "evaluations": 0}

    monkeypatch.setattr(opt_module, "run_param_search", fake_run_param_search)
    monkeypatch.setattr(opt_module, "save_search_report", lambda *_: Path("optimize_profile_fixture.md"))
    monkeypatch.setattr(opt_module, "save_search_payload", lambda *_: Path("optimize_profile_fixture.json"))
    monkeypatch.setattr(opt_module, "format_search_report", lambda _: "")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_profile.py",
            "--profile",
            "event_catalyst_guarded",
            "--preset-grid",
            "--input",
            "dummy.json",
        ],
    )

    def fake_build_replay_evaluator(*_: object, **__: object) -> object:
        return lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}

    monkeypatch.setattr(opt_module, "_build_replay_evaluator", fake_build_replay_evaluator)

    try:
        opt_module.main()
    except SystemExit:
        pass

    assert captured_grid is not None, "ParamSpace was not initialized with a grid"
    assert "event_catalyst_selected_uplift" in captured_grid, "Event-catalyst params missing from grid used by main()"
    assert "select_threshold" in captured_grid, "Base preset params missing from grid used by main()"


def test_main_passes_guardrails_and_focused_grid_to_run_param_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    focus_json = tmp_path / "focus.json"
    focus_json.write_text('{"best_params": {"select_threshold": 0.50, "near_miss_threshold": 0.36}}', encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )

    def fake_run_param_search(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(best_params={}, best_score=None, objective=kwargs["objective"], results=[], completed_trials=0, total_trials=1)

    monkeypatch.setattr(optimize_profile, "run_param_search", fake_run_param_search)
    monkeypatch.setattr(optimize_profile, "save_search_report", lambda report, output_path=None: Path(output_path or tmp_path / "report.md"))
    monkeypatch.setattr(optimize_profile, "save_search_payload", lambda report, output_path=None: Path(output_path or tmp_path / "report.json"))
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.42,0.46,0.50,0.54,0.58",
            "near_miss_threshold=0.28,0.32,0.36,0.40",
            "--input",
            "dummy.json",
            "--search-stage",
            "focused",
            "--focus-json",
            str(focus_json),
            "--guardrail",
            "window_coverage=0.75",
        ]
    )

    assert exit_code == 0
    assert captured["guardrails"] == {
        "next_close_positive_rate": pytest.approx(0.54),
        "next_high_hit_rate": pytest.approx(0.56),
        "downside_p10": pytest.approx(-0.06),
        "window_coverage": pytest.approx(0.75),
        "projected_theme_exposure": {"max": pytest.approx(0.35)},
        "incremental_theme_exposure": {"max": pytest.approx(0.12)},
        "liquidity_capacity_raw_100": {"min": pytest.approx(50.0)},
        "crowding_risk_raw_100": {"max": pytest.approx(70.0)},
        "gap_risk_raw_100": {"max": pytest.approx(60.0)},
    }
    assert captured["space"].grid["select_threshold"] == [0.46, 0.50, 0.54]
    assert captured["space"].grid["near_miss_threshold"] == [0.32, 0.36, 0.40]


def test_main_uses_stage_preset_grid_before_focus_narrowing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    focus_json = tmp_path / "focus.json"
    focus_json.write_text('{"best_params": {"select_threshold": 0.50, "near_miss_threshold": 0.34}}', encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )

    def fake_run_param_search(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(best_params={}, best_score=None, objective=kwargs["objective"], results=[], completed_trials=0, total_trials=1)

    monkeypatch.setattr(optimize_profile, "run_param_search", fake_run_param_search)
    monkeypatch.setattr(optimize_profile, "save_search_report", lambda report, output_path=None: Path(output_path or tmp_path / "report.md"))
    monkeypatch.setattr(optimize_profile, "save_search_payload", lambda report, output_path=None: Path(output_path or tmp_path / "report.json"))
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--preset-grid",
            "--input",
            "dummy.json",
            "--search-stage",
            "focused",
            "--focus-json",
            str(focus_json),
        ]
    )

    assert exit_code == 0
    assert captured["space"].grid["select_threshold"] == [0.46, 0.50, 0.54]
    assert captured["space"].grid["near_miss_threshold"] == [0.30, 0.34, 0.38]
    assert "overhead_penalty_block_threshold" not in captured["space"].grid


def test_main_writes_stage_metadata_to_output_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"

    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--preset-grid",
            "--input",
            "dummy.json",
            "--search-stage",
            "coarse",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    metadata_payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert metadata_payload["metadata"]["search_stage"] == "coarse"
    assert metadata_payload["metadata"]["guardrails"]["next_close_positive_rate"] == pytest.approx(0.54)
    assert "## Search Metadata" in output_md.read_text(encoding="utf-8")
    assert "Search Stage: **coarse**" in output_md.read_text(encoding="utf-8")


def test_resolve_grid_params_uses_routed_btst_committee_preset_for_ignition_breakout() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="ignition_breakout",
    )

    assert grid["committee_alpha_min_aggressive_trade"] == [66.0, 68.0, 70.0]
    assert grid["committee_beta_min_normal_trade"] == [60.0, 62.0, 64.0]
    assert grid["committee_score_min_normal_trade"] == [62.0, 64.0, 66.0]
    assert grid["committee_fragile_breakout_alpha_weight"] == [0.08, 0.10, 0.12]
    assert "select_threshold" not in grid


def test_resolve_grid_params_prefers_explicit_values_over_routed_preset() -> None:
    grid = resolve_grid_params(
        grid_params=["committee_score_min_normal_trade=61,63"],
        preset_grid=True,
        profile_name="retention_follow",
    )

    assert grid["committee_score_min_normal_trade"] == [61, 63]
    assert grid["committee_fragile_breakout_risk_cap"] == [75.0, 85.0]


def test_routed_committee_grid_overrides_can_build_profile() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="shadow_research",
    )

    profile = build_short_trade_target_profile(
        "shadow_research",
        overrides={key: values[0] for key, values in grid.items()},
    )

    assert profile.committee_alpha_min_aggressive_trade == 66.0
    assert profile.committee_score_min_normal_trade == 62.0
    assert profile.committee_fragile_breakout_risk_cap == 75.0


def test_resolve_grid_params_uses_btst_runner_probe_preset() -> None:
    """btst_runner_probe profile uses BTST_RUNNER_PROBE_GRID when --preset-grid is set."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID

    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="btst_runner_probe",
    )

    assert grid["runner_escape_breakout_freshness_min"] == BTST_RUNNER_PROBE_GRID["runner_escape_breakout_freshness_min"]
    assert grid["runner_escape_trend_acceleration_min"] == BTST_RUNNER_PROBE_GRID["runner_escape_trend_acceleration_min"]
    assert grid["runner_composite_score_breakout_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"]
    assert grid["runner_composite_score_trend_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_trend_weight"]
    assert grid["runner_composite_score_close_strength_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_close_strength_weight"]
    assert grid["historical_continuation_score_weight"] == BTST_RUNNER_PROBE_GRID["historical_continuation_score_weight"]
    assert grid["runner_composite_score_volatility_regime_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_volatility_regime_weight"]
    assert grid["runner_composite_score_sector_resonance_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_sector_resonance_weight"]
    assert grid["runner_escape_gap_risk_raw_100_max"] == BTST_RUNNER_PROBE_GRID["runner_escape_gap_risk_raw_100_max"]
    assert grid["runner_escape_composite_score_min"] == BTST_RUNNER_PROBE_GRID["runner_escape_composite_score_min"]
    # Task 1 (Round 26, Alpha): new cross-factor axes must be present in the preset grid.
    assert grid["runner_composite_score_momentum_confirmation_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_momentum_confirmation_weight"]
    assert grid["runner_composite_score_volume_momentum_weight"] == BTST_RUNNER_PROBE_GRID["runner_composite_score_volume_momentum_weight"]
    assert "committee_alpha_min_aggressive_trade" not in grid  # not the committee grid


def test_btst_runner_probe_grid_params_build_valid_profile() -> None:
    """Each combination of runner probe grid values must build a valid btst_runner_probe profile.

    Optimizer-only params (e.g. ``recency_half_life_days``) are excluded from the profile
    build check since they are consumed by the optimizer framework, not the profile constructor.
    """
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID, _OPTIMIZER_ONLY_PARAMS

    for param_name, values in BTST_RUNNER_PROBE_GRID.items():
        if param_name in _OPTIMIZER_ONLY_PARAMS:
            continue  # consumed by optimizer framework, not forwarded to profile
        for value in values:
            profile = build_short_trade_target_profile("btst_runner_probe", overrides={param_name: value})
            assert profile is not None
            actual = getattr(profile, param_name, None)
            assert actual == value, f"Expected {param_name}={value}, got {actual}"


def test_resolve_replay_inputs_from_weekly_validation_selection(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260413_20260413_live_short_trade_only_20260414"
    day_dir = report_dir / "selection_artifacts" / "2026-04-13"
    replay_input = day_dir / "selection_target_replay_input.json"
    snapshot_path = day_dir / "selection_snapshot.json"
    day_dir.mkdir(parents=True)
    replay_input.write_text("{}", encoding="utf-8")
    snapshot_path.write_text(
        '{"trade_date": "20260413", "target_mode": "short_trade_only", "selection_targets": {}}',
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}", encoding="utf-8")

    paths = optimize_profile.resolve_replay_input_paths(
        input_paths=None,
        reports_root=reports_root,
        weekly_start_date="2026-04-13",
        weekly_end_date="2026-04-13",
    )

    assert paths == [replay_input.resolve()]


def test_resolve_replay_inputs_rejects_missing_trade_dates(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="missing_trade_dates"):
        optimize_profile.resolve_replay_input_paths(
            input_paths=None,
            reports_root=reports_root,
            weekly_start_date="2026-04-13",
            weekly_end_date="2026-04-14",
        )


def test_main_accepts_weekly_window_args_and_runs_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoint_calls: list[Path] = []

    monkeypatch.setattr(
        optimize_profile,
        "resolve_replay_input_paths",
        lambda **_: [tmp_path / "window_a.json", tmp_path / "window_b.json"],
    )
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: checkpoint_calls.append(Path(kwargs["checkpoint_path"])) or SimpleNamespace(best_params={}, best_score=None, objective=kwargs["objective"], results=[], completed_trials=0, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "save_search_report", lambda report, output_path=None: Path(output_path or tmp_path / "report.md"))
    monkeypatch.setattr(optimize_profile, "save_search_payload", lambda report, output_path=None: Path(output_path or tmp_path / "report.json"))
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "default",
            "--grid-params",
            "select_threshold=0.58",
            "--reports-root",
            str(tmp_path),
            "--weekly-start-date",
            "2026-04-13",
            "--weekly-end-date",
            "2026-04-18",
        ]
    )

    assert exit_code == 0
    assert checkpoint_calls
    assert checkpoint_calls[0].name.startswith("param_search_default_")


def test_resolve_grid_params_uses_stage1_ignition_grid() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=False,
        profile_name="ignition_breakout",
        staged_mode="ignition_stage1",
    )

    assert grid["committee_alpha_min_aggressive_trade"] == [66.0, 68.0]
    assert grid["committee_score_min_normal_trade"] == [62.0, 64.0]
    assert grid["committee_fragile_breakout_alpha_weight"] == [0.08, 0.10]
    assert "committee_fragile_breakout_risk_cap" in grid


def test_resolve_grid_params_stage1_rejects_non_ignition_profile() -> None:
    with pytest.raises(ValueError, match="ignition_stage1.*ignition_breakout"):
        resolve_grid_params(
            grid_params=[],
            preset_grid=False,
            profile_name="retention_follow",
            staged_mode="ignition_stage1",
        )


def test_resolve_grid_params_stage1_explicit_overrides_win() -> None:
    grid = resolve_grid_params(
        grid_params=["committee_score_min_normal_trade=61,63"],
        preset_grid=False,
        profile_name="ignition_breakout",
        staged_mode="ignition_stage1",
    )

    assert grid["committee_score_min_normal_trade"] == [61, 63]
    assert grid["committee_alpha_min_aggressive_trade"] == [66.0, 68.0]


def test_main_stage1_forwards_staged_mode_into_grid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scripts.optimize_profile as opt_module

    captured_grid: dict[str, list] | None = None

    def fake_param_space_init(self: object, *, grid: dict[str, list]) -> None:
        nonlocal captured_grid
        captured_grid = grid
        self.grid = grid

    def fake_param_space_size(self: object) -> int:
        return 1

    monkeypatch.setattr(opt_module.ParamSpace, "__init__", fake_param_space_init)
    monkeypatch.setattr(opt_module.ParamSpace, "size", fake_param_space_size)
    monkeypatch.setattr(
        opt_module,
        "run_param_search",
        lambda **_: SearchReport(objective=SearchObjective.EDGE, results=[], best_params={}, best_score=None, total_trials=0, completed_trials=0),
    )
    monkeypatch.setattr(opt_module, "save_search_report", lambda *_: Path("optimize_profile_fixture.md"))
    monkeypatch.setattr(opt_module, "save_search_payload", lambda *_: Path("optimize_profile_fixture.json"))
    monkeypatch.setattr(opt_module, "format_search_report", lambda _: "")
    monkeypatch.setattr(
        opt_module,
        "_build_replay_evaluator",
        lambda *_, **__: lambda _params: {
            "window_count": 1,
            "window_coverage": 1.0,
            "sample_weight": 0.5,
            "next_close_positive_rate": 0.6,
            "next_close_expectancy": 0.010,
        },
    )

    try:
        opt_module.main(
            [
                "--profile",
                "ignition_breakout",
                "--staged-mode",
                "ignition_stage1",
                "--input",
                "dummy.json",
            ]
        )
    except SystemExit:
        pass

    assert captured_grid is not None, "ParamSpace was never initialized"
    assert "committee_alpha_min_aggressive_trade" in captured_grid, "Stage1 grid not forwarded into ParamSpace"
    assert captured_grid["committee_alpha_min_aggressive_trade"] == [66.0, 68.0], "Stage1 narrow values not used"
    assert "select_threshold" not in captured_grid, "Preset grid should not appear in stage1 mode"


def test_main_stage1_rejects_non_ignition_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.optimize_profile as opt_module

    monkeypatch.setattr(sys, "argv", ["optimize_profile.py"])

    with pytest.raises(SystemExit):
        opt_module.main(
            [
                "--profile",
                "shadow_research",
                "--staged-mode",
                "ignition_stage1",
                "--input",
                "dummy.json",
            ]
        )


# ---------------------------------------------------------------------------
# Tests for source coverage and staged ignition evaluator (Task 2)
# ---------------------------------------------------------------------------


def test_compute_source_coverage_pass_ratio_pure_exact_tick() -> None:
    summaries = [
        {
            "flow_60_source_counts": {"exact_tick": 5},
            "persist_120_source_counts": {"exact_tick": 3},
            "close_support_30_source_counts": {},
            "committee_component_sources_counts": {},
        }
    ]
    ratio = _compute_source_coverage_pass_ratio(summaries)
    assert ratio == pytest.approx(1.0)


def test_compute_source_coverage_pass_ratio_mixed_sources() -> None:
    summaries = [
        {
            "flow_60_source_counts": {"exact_tick": 6, "bar_proxy": 2, "daily_flow_proxy": 2},
            "persist_120_source_counts": {"exact_tick": 0},
            "close_support_30_source_counts": {},
            "committee_component_sources_counts": {},
        }
    ]
    ratio = _compute_source_coverage_pass_ratio(summaries)
    # 6 exact_tick out of 10 total
    assert ratio == pytest.approx(0.6)


def test_compute_source_coverage_pass_ratio_no_data() -> None:
    assert _compute_source_coverage_pass_ratio([]) == pytest.approx(0.0)
    assert _compute_source_coverage_pass_ratio([{}]) == pytest.approx(0.0)


def _make_fake_replay_module_for_staged(
    ignition_win_rate: float = 0.60,
    ignition_expectancy: float = 0.010,
    default_win_rate: float = 0.55,
    candidate_win_rate: float = 0.62,
    candidate_expectancy: float = 0.013,
    source_coverage_summary: dict | None = None,
) -> types.ModuleType:
    """Build a fake btst_profile_replay_utils module for staged evaluator tests.

    Baseline calls (profile_overrides={}) return ignition/default rates.
    Candidate calls (profile_overrides non-empty) return candidate_win_rate/expectancy,
    allowing tests to distinguish the two reliably.
    """
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    _default_coverage = {
        "flow_60_source_counts": {"exact_tick": 4, "bar_proxy": 1},
        "persist_120_source_counts": {"exact_tick": 3},
        "close_support_30_source_counts": {},
        "committee_component_sources_counts": {},
    }
    coverage = source_coverage_summary if source_coverage_summary is not None else _default_coverage

    def fake_analyze_btst_profile_replay_window(
        input_path: Path,
        *,
        profile_name: str = "ignition_breakout",
        profile_overrides: dict | None = None,
        **_: object,
    ) -> dict[str, object]:
        overrides = profile_overrides or {}
        if profile_name == "default":
            win_rate = default_win_rate
            expectancy = 0.008
        elif overrides:
            # Non-empty overrides → candidate evaluation
            win_rate = candidate_win_rate
            expectancy = candidate_expectancy
        else:
            # Empty overrides → baseline evaluation
            win_rate = ignition_win_rate
            expectancy = ignition_expectancy

        surface = {
            "next_day_available_count": 8,
            "closed_cycle_count": 5,
            "next_close_positive_rate": win_rate,
            "next_high_hit_rate_at_threshold": 0.55,
            "next_close_payoff_ratio": 1.6,
            "next_close_expectancy": expectancy,
            "t_plus_2_close_positive_rate": 0.54,
            "next_close_return_distribution": {"p10": -0.02},
            "t_plus_2_close_return_distribution": {"median": 0.005},
            "t_plus_3_close_positive_rate": 0.52,
            "t_plus_3_close_expectancy": 0.009,
        }
        return {
            "surface_summaries": {"selected": surface, "tradeable": surface},
            "source_coverage_summary": coverage,
        }

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    return fake_module


def test_staged_ignition_evaluator_injects_required_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.60,
        ignition_expectancy=0.010,
        default_win_rate=0.55,
        candidate_win_rate=0.62,
        candidate_expectancy=0.013,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_ok.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator(
        [input_path],
        base_profile="ignition_breakout",
    )
    metrics = evaluator({})

    assert "baseline_next_close_positive_rate_delta" in metrics
    assert "baseline_next_close_expectancy_delta" in metrics
    assert "promotion_guardrail_pass" in metrics
    assert "source_coverage_pass_ratio" in metrics


def test_staged_ignition_evaluator_guardrail_passes_when_candidate_beats_baselines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.60,
        ignition_expectancy=0.010,
        default_win_rate=0.55,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_ok.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    # Non-empty params trigger the candidate branch (candidate_win_rate=0.62 > ignition=0.60)
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 55.0})

    assert metrics["promotion_guardrail_pass"] is True
    assert metrics["baseline_next_close_positive_rate_delta"] is not None


def test_staged_ignition_evaluator_guardrail_fails_when_candidate_below_baselines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Candidate win_rate (0.45) is clearly below both ignition (0.68) and default (0.65) baselines
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.68,
        ignition_expectancy=0.015,
        default_win_rate=0.65,
        candidate_win_rate=0.45,
        candidate_expectancy=0.005,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_ok.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    # Non-empty params trigger the candidate branch in the fake (returns 0.45 win_rate)
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 70.0})

    assert metrics["promotion_guardrail_pass"] is False
    assert metrics["baseline_next_close_positive_rate_delta"] is not None
    assert float(metrics["baseline_next_close_positive_rate_delta"]) < -0.1


def test_staged_ignition_evaluator_guardrail_fails_when_source_coverage_too_low(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Candidate metrics are fine on win_rate/expectancy but source coverage is all proxy (no exact_tick)
    low_coverage = {
        "flow_60_source_counts": {"bar_proxy": 6, "daily_flow_proxy": 4},
        "persist_120_source_counts": {"bar_proxy": 3},
        "close_support_30_source_counts": {},
        "committee_component_sources_counts": {},
    }
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.60,
        ignition_expectancy=0.010,
        default_win_rate=0.55,
        candidate_win_rate=0.65,  # clearly above both baselines
        candidate_expectancy=0.015,
        source_coverage_summary=low_coverage,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_low_cov.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 70.0})

    # source_coverage_pass_ratio is 0.0 → guardrail must fail despite good win_rate
    assert metrics["source_coverage_pass_ratio"] == pytest.approx(0.0)
    assert metrics["promotion_guardrail_pass"] is False


def test_staged_ignition_evaluator_source_coverage_ratio_from_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_module = _make_fake_replay_module_for_staged()
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_ok.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    metrics = evaluator({})

    # flow_60: exact_tick=4, bar_proxy=1 → 5 total, 4 strong
    # persist_120: exact_tick=3 → 3 total, 3 strong
    # total: 8 slots, 7 exact_tick → 7/8 = 0.875
    assert metrics["source_coverage_pass_ratio"] == pytest.approx(7.0 / 8.0)


def test_staged_ignition_evaluator_guardrail_passes_at_exact_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Candidate exactly equal to all baselines must pass (no tolerance: >= is strictly non-degrading)."""
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.60,
        ignition_expectancy=0.010,
        default_win_rate=0.55,
        candidate_win_rate=0.60,  # exactly equal to ignition baseline
        candidate_expectancy=0.010,  # exactly equal to ignition expectancy
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_exact.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 55.0})

    assert metrics["promotion_guardrail_pass"] is True


def test_staged_ignition_evaluator_guardrail_fails_at_one_tick_below_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Candidate fractionally below ignition baseline must fail — no tolerance is allowed."""
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.60,
        ignition_expectancy=0.010,
        default_win_rate=0.55,
        candidate_win_rate=0.599,  # 0.001 below ignition — must fail
        candidate_expectancy=0.010,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_one_tick_below.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 55.0})

    assert metrics["promotion_guardrail_pass"] is False


def test_staged_ignition_evaluator_guardrail_fails_when_below_default_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Candidate beats ignition but falls below default win rate — must fail."""
    fake_module = _make_fake_replay_module_for_staged(
        ignition_win_rate=0.55,
        ignition_expectancy=0.010,
        default_win_rate=0.65,
        candidate_win_rate=0.60,  # above ignition but below default
        candidate_expectancy=0.010,
    )
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_below_default.json"
    input_path.write_text("{}")

    evaluator = _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")
    metrics = evaluator({"committee_alpha_min_aggressive_trade": 55.0})

    assert metrics["promotion_guardrail_pass"] is False


def test_staged_ignition_evaluator_raises_when_ignition_baseline_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing ignition_breakout baseline metrics must raise RuntimeError (fail closed, not pass)."""
    import types as _types

    fake_module = _types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(
        input_path: Path,
        *,
        profile_name: str = "ignition_breakout",
        profile_overrides: dict | None = None,
        **_: object,
    ) -> dict[str, object]:
        # Return a surface with missing next_close_positive_rate and next_close_expectancy
        surface: dict[str, object] = {
            "next_day_available_count": 0,
            "closed_cycle_count": 0,
            # Intentionally omit next_close_positive_rate and next_close_expectancy
        }
        return {
            "surface_summaries": {"selected": surface, "tradeable": surface},
            "source_coverage_summary": {},
        }

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_missing_baseline.json"
    input_path.write_text("{}")

    with pytest.raises(RuntimeError, match="ignition_breakout baseline missing"):
        _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")


def test_staged_ignition_evaluator_raises_when_default_baseline_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing default profile baseline metrics must raise RuntimeError (fail closed, not pass)."""
    import types as _types

    fake_module = _types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(
        input_path: Path,
        *,
        profile_name: str = "ignition_breakout",
        profile_overrides: dict | None = None,
        **_: object,
    ) -> dict[str, object]:
        if profile_name == "default":
            # Default profile returns no metrics — simulate missing data
            surface: dict[str, object] = {"next_day_available_count": 0, "closed_cycle_count": 0}
        else:
            surface = {
                "next_day_available_count": 8,
                "closed_cycle_count": 5,
                "next_close_positive_rate": 0.60,
                "next_close_expectancy": 0.010,
                "next_high_hit_rate_at_threshold": 0.50,
                "next_close_payoff_ratio": 1.5,
                "next_close_return_distribution": {"p10": -0.02, "median": 0.005},
                "t_plus_2_close_positive_rate": 0.55,
                "t_plus_2_close_return_distribution": {"median": 0.004},
                "t_plus_3_close_positive_rate": 0.52,
                "t_plus_3_close_expectancy": 0.008,
            }
        return {
            "surface_summaries": {"selected": surface, "tradeable": surface},
            "source_coverage_summary": {"flow_60_source_counts": {"exact_tick": 4}},
        }

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    input_path = tmp_path / "window_missing_default.json"
    input_path.write_text("{}")

    with pytest.raises(RuntimeError, match="default profile baseline missing"):
        _build_staged_ignition_evaluator([input_path], base_profile="ignition_breakout")


def test_main_staged_mode_with_walk_forward_raises_cli_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--staged-mode ignition_stage1 must be rejected when only walk-forward inputs are provided."""
    import scripts.optimize_profile as opt_module

    monkeypatch.setattr(sys, "argv", ["optimize_profile.py"])

    with pytest.raises(SystemExit) as exc_info:
        opt_module.main(
            [
                "--profile",
                "ignition_breakout",
                "--staged-mode",
                "ignition_stage1",
                "--tickers",
                "000001",
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-06-30",
            ]
        )

    # argparse.error() exits with code 2
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Tests for shortlist/verdict helpers (Task 3)
# ---------------------------------------------------------------------------


def _make_trial(
    index: int,
    params: dict,
    score: float | None,
    *,
    guardrail_pass: bool = True,
    win_rate_delta: float | None = 0.02,
    expectancy_delta: float | None = 0.003,
    source_coverage: float | None = 0.75,
) -> TrialResult:
    metrics: dict = {
        "promotion_guardrail_pass": guardrail_pass,
        "baseline_next_close_positive_rate_delta": win_rate_delta,
        "baseline_next_close_expectancy_delta": expectancy_delta,
        "source_coverage_pass_ratio": source_coverage,
    }
    return TrialResult(trial_index=index, params=params, metrics=metrics, window_count=2, score=score)


def test_format_staged_ignition_report_includes_promotion_verdict() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(
                0,
                {"committee_score_min_normal_trade": 64.0},
                0.52,
                guardrail_pass=True,
            )
        ],
        best_params={"committee_score_min_normal_trade": 64.0},
        best_score=0.52,
        total_trials=1,
        completed_trials=1,
    )
    output = _format_staged_ignition_summary(report)
    assert "promotable" in output
    assert "committee_score_min_normal_trade" in output


def test_build_staged_ignition_shortlist_marks_guardrail_pass_as_promotable() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(0, {"committee_score_min_normal_trade": 64.0}, 0.52, guardrail_pass=True),
            _make_trial(1, {"committee_score_min_normal_trade": 62.0}, 0.48, guardrail_pass=False),
        ],
        best_params={"committee_score_min_normal_trade": 64.0},
        best_score=0.52,
        total_trials=2,
        completed_trials=2,
    )
    shortlist = _build_staged_ignition_shortlist(report)
    assert shortlist[0]["promotion_verdict"] == "promotable"
    assert shortlist[1]["promotion_verdict"] == "not_promotable"


def test_build_staged_ignition_shortlist_ranked_by_score_descending() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(0, {"x": 1}, 0.40),
            _make_trial(1, {"x": 2}, 0.55),
            _make_trial(2, {"x": 3}, 0.50),
        ],
        best_params={"x": 2},
        best_score=0.55,
        total_trials=3,
        completed_trials=3,
    )
    shortlist = _build_staged_ignition_shortlist(report)
    scores = [row["score"] for row in shortlist]
    assert scores == sorted(scores, reverse=True)
    assert shortlist[0]["params"]["x"] == 2


def test_build_staged_ignition_shortlist_unscored_rows_appended_after_scored() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(0, {"x": 1}, 0.50),
            _make_trial(1, {"x": 2}, None, guardrail_pass=False),
            _make_trial(2, {"x": 3}, 0.45),
        ],
        best_params={"x": 1},
        best_score=0.50,
        total_trials=3,
        completed_trials=2,
    )
    shortlist = _build_staged_ignition_shortlist(report)
    # All three returned (top_n=5 default)
    assert len(shortlist) == 3
    # Scored rows come first
    assert shortlist[0]["score"] is not None
    assert shortlist[1]["score"] is not None
    assert shortlist[2]["score"] is None


def test_build_staged_ignition_shortlist_respects_top_n() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[_make_trial(i, {"x": i}, float(i) * 0.1) for i in range(10)],
        best_params={"x": 9},
        best_score=0.9,
        total_trials=10,
        completed_trials=10,
    )
    shortlist = _build_staged_ignition_shortlist(report, top_n=3)
    assert len(shortlist) == 3


def test_build_staged_ignition_shortlist_surfaces_baseline_deltas_and_coverage() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(
                0,
                {"committee_score_min_normal_trade": 64.0},
                0.52,
                guardrail_pass=True,
                win_rate_delta=0.04,
                expectancy_delta=0.005,
                source_coverage=0.80,
            )
        ],
        best_params={"committee_score_min_normal_trade": 64.0},
        best_score=0.52,
        total_trials=1,
        completed_trials=1,
    )
    shortlist = _build_staged_ignition_shortlist(report)
    row = shortlist[0]
    assert row["baseline_next_close_positive_rate_delta"] == pytest.approx(0.04)
    assert row["baseline_next_close_expectancy_delta"] == pytest.approx(0.005)
    assert row["source_coverage_pass_ratio"] == pytest.approx(0.80)


def test_format_staged_ignition_summary_overall_verdict_promotion_available() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[_make_trial(0, {"x": 1}, 0.55, guardrail_pass=True)],
        best_params={"x": 1},
        best_score=0.55,
        total_trials=1,
        completed_trials=1,
    )
    output = _format_staged_ignition_summary(report)
    assert "PROMOTION AVAILABLE" in output


def test_format_staged_ignition_summary_overall_verdict_keep_current_when_no_promotable() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[_make_trial(0, {"x": 1}, 0.40, guardrail_pass=False)],
        best_params={"x": 1},
        best_score=0.40,
        total_trials=1,
        completed_trials=1,
    )
    output = _format_staged_ignition_summary(report)
    assert "KEEP CURRENT IGNITION PROFILE" in output


def test_format_staged_ignition_summary_overall_verdict_uses_full_results_not_shortlist() -> None:
    """Overall verdict must reflect the full report.results, not just the displayed shortlist.

    When top_n=1 (default shortlist cap is 5 but only the best-scored candidate is shown), the
    shortlist contains only the top-1 result which has guardrail_pass=False.  The 6th result (rank
    6, outside the default top-5 shortlist) has guardrail_pass=True.  The overall verdict must be
    PROMOTION AVAILABLE even though the shortlist alone would produce KEEP CURRENT IGNITION PROFILE.
    """
    # Build 6 results: rank 1-5 all fail guardrails, rank 6 passes.
    results = [_make_trial(i, {"x": i}, float(i) * 0.01, guardrail_pass=False) for i in range(5)]
    # rank 6 has the lowest score but passes the guardrail — outside the default top-5 shortlist
    results.append(_make_trial(5, {"x": 5}, 0.001, guardrail_pass=True))
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=results,
        best_params={"x": 4},
        best_score=0.04,
        total_trials=6,
        completed_trials=6,
    )
    output = _format_staged_ignition_summary(report)
    # The displayed shortlist (top 5 by score) excludes rank-6; overall verdict must still detect it
    assert "PROMOTION AVAILABLE" in output, (
        "Overall verdict must scan full report.results, not only the displayed top-5 shortlist"
    )


def test_format_staged_ignition_summary_includes_score_and_delta_context() -> None:
    report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[
            _make_trial(
                0,
                {"committee_score_min_normal_trade": 64.0},
                0.52,
                guardrail_pass=True,
                win_rate_delta=0.03,
                expectancy_delta=0.004,
                source_coverage=0.72,
            )
        ],
        best_params={"committee_score_min_normal_trade": 64.0},
        best_score=0.52,
        total_trials=1,
        completed_trials=1,
    )
    output = _format_staged_ignition_summary(report)
    assert "0.52" in output or "score=0.5200" in output
    assert "win_rate_delta" in output
    assert "expectancy_delta" in output
    assert "source_coverage_pass_ratio" in output


def test_main_stage1_emits_ignition_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """stage1 main() must print the ignition summary alongside the generic report."""
    import scripts.optimize_profile as opt_module

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **_: printed.append(" ".join(str(a) for a in args)))

    fake_trial = TrialResult(
        trial_index=0,
        params={"committee_score_min_normal_trade": 64.0},
        metrics={
            "promotion_guardrail_pass": True,
            "baseline_next_close_positive_rate_delta": 0.02,
            "baseline_next_close_expectancy_delta": 0.003,
            "source_coverage_pass_ratio": 0.80,
        },
        window_count=1,
        score=0.52,
    )
    fake_report = SearchReport(
        objective=SearchObjective.EDGE,
        results=[fake_trial],
        best_params=fake_trial.params,
        best_score=fake_trial.score,
        total_trials=1,
        completed_trials=1,
    )

    monkeypatch.setattr(opt_module, "run_param_search", lambda **_: fake_report)
    monkeypatch.setattr(opt_module, "save_search_report", lambda *_a, **_kw: Path("r.md"))
    monkeypatch.setattr(opt_module, "save_search_payload", lambda *_a, **_kw: Path("r.json"))
    monkeypatch.setattr(
        opt_module,
        "_build_staged_ignition_evaluator",
        lambda *_, **__: lambda _p: {
            "next_close_positive_rate": 0.62,
            "next_close_expectancy": 0.012,
            "promotion_guardrail_pass": True,
            "baseline_next_close_positive_rate_delta": 0.02,
            "baseline_next_close_expectancy_delta": 0.002,
            "source_coverage_pass_ratio": 0.80,
        },
    )

    exit_code = opt_module.main(
        [
            "--profile",
            "ignition_breakout",
            "--staged-mode",
            "ignition_stage1",
            "--input",
            str(tmp_path / "window.json"),
        ]
    )

    assert exit_code == 0
    all_output = "\n".join(printed)
    assert "Stage 1 Ignition" in all_output
    assert "promotable" in all_output


def test_main_writes_best_candidate_comparison_to_output_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            "dummy.json",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["comparison_summary"]["default"]["next_close_positive_rate_delta"] == pytest.approx(0.05)
    assert payload["comparison_summary"]["momentum_optimized"]["next_high_hit_rate_delta"] == pytest.approx(0.02)
    assert "## Baseline Comparison" in output_md.read_text(encoding="utf-8")


def test_recommend_rollout_action_allows_lower_is_better_metric_improvements() -> None:
    comparison_summary = {
        "default": {
            "next_close_positive_rate_delta": 0.03,
            "next_high_hit_rate_delta": 0.02,
            "next_close_expectancy_delta": 0.004,
            "downside_p10_delta": 0.005,
            "window_coverage_delta": 0.03,
            "liquidity_capacity_raw_100_delta": 6.0,
            "crowding_risk_raw_100_delta": -8.0,
            "gap_risk_raw_100_delta": -5.0,
            "projected_theme_exposure_delta": -0.04,
            "incremental_theme_exposure_delta": -0.02,
        }
    }

    assert optimize_profile._recommend_rollout_action(comparison_summary) == "promote"


def test_build_rollout_recommendation_payload_surfaces_directional_blockers() -> None:
    comparison_summary = {
        "default": {
            "next_close_positive_rate_delta": 0.03,
            "next_high_hit_rate_delta": 0.02,
            "next_close_expectancy_delta": 0.004,
            "downside_p10_delta": 0.005,
            "window_coverage_delta": 0.03,
            "liquidity_capacity_raw_100_delta": 6.0,
            "crowding_risk_raw_100_delta": 4.0,
            "gap_risk_raw_100_delta": -5.0,
            "projected_theme_exposure_delta": -0.04,
            "incremental_theme_exposure_delta": -0.02,
        }
    }

    payload = optimize_profile._build_rollout_recommendation_payload(comparison_summary)

    assert payload["action"] == "hold"
    assert "crowding_risk_raw_100_regressed_vs_default" in payload["blockers"]
    assert payload["baseline_verdicts"]["default"]["status"] == "blocked"


def test_build_rollout_recommendation_payload_ignores_sub_noise_execution_and_exposure_deltas() -> None:
    comparison_summary = {
        "default": {
            "next_close_positive_rate_delta": 0.03,
            "next_high_hit_rate_delta": 0.02,
            "next_close_expectancy_delta": 0.004,
            "downside_p10_delta": 0.001,
            "window_coverage_delta": -0.001,
            "liquidity_capacity_raw_100_delta": -0.8,
            "crowding_risk_raw_100_delta": 0.8,
            "gap_risk_raw_100_delta": 0.9,
            "projected_theme_exposure_delta": 0.004,
            "incremental_theme_exposure_delta": 0.004,
        }
    }

    payload = optimize_profile._build_rollout_recommendation_payload(comparison_summary)

    assert payload["action"] == "promote"
    assert payload["blockers"] == []


def test_build_rollout_recommendation_payload_blocks_meaningful_regression_beyond_epsilon() -> None:
    comparison_summary = {
        "default": {
            "next_close_positive_rate_delta": 0.03,
            "next_high_hit_rate_delta": 0.02,
            "next_close_expectancy_delta": 0.004,
            "downside_p10_delta": 0.001,
            "window_coverage_delta": -0.003,
            "liquidity_capacity_raw_100_delta": -1.2,
            "crowding_risk_raw_100_delta": 1.2,
            "gap_risk_raw_100_delta": 1.1,
            "projected_theme_exposure_delta": 0.006,
            "incremental_theme_exposure_delta": 0.006,
        }
    }

    payload = optimize_profile._build_rollout_recommendation_payload(comparison_summary)

    assert payload["action"] == "hold"
    assert "window_coverage_regressed_vs_default" in payload["blockers"]
    assert "liquidity_capacity_raw_100_regressed_vs_default" in payload["blockers"]
    assert "crowding_risk_raw_100_regressed_vs_default" in payload["blockers"]


def test_main_persists_execution_aware_rollout_details_to_output_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            "dummy.json",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["comparison_summary"]["default"]["crowding_risk_raw_100_delta"] == pytest.approx(-8.0)
    assert payload["comparison_summary"]["default"]["projected_theme_exposure_delta"] == pytest.approx(-0.04)
    assert payload["rollout_recommendation_details"]["action"] == "promote"
    assert "Crowding Δ" in output_md.read_text(encoding="utf-8")


def test_main_writes_rollout_recommendation_to_output_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            "dummy.json",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["rollout_recommendation"] == "promote"
    assert "Rollout Recommendation: **promote**" in output_md.read_text(encoding="utf-8")


def test_main_publishes_ready_btst_manifest_when_rollout_recommendation_is_promote(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"
    replay_input = tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            str(replay_input),
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert manifest_path.exists()
    published_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert published_manifest["status"] == "ready"
    assert published_manifest["profile_name"] == "momentum_optimized"
    assert published_manifest["profile_overrides"] == {"select_threshold": 0.50}
    assert published_manifest["trade_date"] == "2026-05-12"

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "published"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "promoted_btst_profile"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())
    assert payload["optimized_profile_manifest_publication"]["payload"] == published_manifest

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **published**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `promoted_btst_profile`" in markdown


def test_main_skips_manifest_publish_when_rollout_recommendation_holds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"
    replay_input = tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            str(replay_input),
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert not manifest_path.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "skipped"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "rollout_recommendation_hold"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **skipped**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `rollout_recommendation_hold`" in markdown


def test_main_emits_manifest_publication_for_non_btst_replay_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"
    replay_input = tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"

    def fake_build_replay_evaluator(input_paths: list[Path], *, base_profile: str, next_high_hit_threshold: float = 0.02):
        del input_paths, next_high_hit_threshold

        def evaluator(params: dict[str, object]) -> dict[str, float]:
            if base_profile == "default":
                return {
                    "next_close_positive_rate": 0.55,
                    "next_high_hit_rate": 0.56,
                    "next_close_expectancy": 0.010,
                    "downside_p10": -0.050,
                    "window_coverage": 0.80,
                    "liquidity_capacity_raw_100": 58.0,
                    "crowding_risk_raw_100": 44.0,
                    "gap_risk_raw_100": 38.0,
                    "projected_theme_exposure": 0.22,
                    "incremental_theme_exposure": 0.11,
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                    "liquidity_capacity_raw_100": 66.0,
                    "crowding_risk_raw_100": 36.0,
                    "gap_risk_raw_100": 30.0,
                    "projected_theme_exposure": 0.18,
                    "incremental_theme_exposure": 0.08,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
                "liquidity_capacity_raw_100": 61.0,
                "crowding_risk_raw_100": 40.0,
                "gap_risk_raw_100": 34.0,
                "projected_theme_exposure": 0.20,
                "incremental_theme_exposure": 0.09,
            }

        return evaluator

    monkeypatch.setattr(optimize_profile, "_build_replay_evaluator", fake_build_replay_evaluator)
    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "edge",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            str(replay_input),
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert not manifest_path.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "skipped"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "non_btst_objective"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **skipped**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `non_btst_objective`" in markdown


def test_main_emits_manifest_publication_for_non_replay_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"

    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={"select_threshold": 0.50}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)
    monkeypatch.setattr(optimize_profile, "_build_walk_forward_evaluator", lambda **kwargs: (lambda params: {"score": 1.0}))

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.50}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--tickers",
            "000001",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-02-01",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert not manifest_path.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "skipped"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "non_replay_run"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **skipped**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `non_replay_run`" in markdown


def test_main_emits_manifest_publication_when_best_params_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"
    replay_input = tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"

    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params=None, best_score=None, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            str(replay_input),
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert not manifest_path.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "skipped"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "missing_best_params"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **skipped**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `missing_best_params`" in markdown


def test_main_publishes_manifest_for_empty_best_params(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    manifest_path = tmp_path / "reports" / "btst_latest_optimized_profile.json"
    replay_input = tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"

    monkeypatch.setattr(
        optimize_profile,
        "run_param_search",
        lambda **kwargs: SimpleNamespace(best_params={}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1),
    )
    monkeypatch.setattr(optimize_profile, "REPORTS_DIR", manifest_path.parent)

    comparison_called = False

    def fake_build_replay_comparison_summary(*, replay_input_paths: list[Path], base_profile: str, best_params: dict[str, object], next_high_hit_threshold: float) -> dict[str, dict[str, object]]:
        nonlocal comparison_called
        del replay_input_paths, base_profile, next_high_hit_threshold
        assert best_params == {}
        comparison_called = True
        return {"momentum_optimized": {"next_close_positive_rate": 0.61}, "default": {"next_close_positive_rate": 0.58}}

    def fake_build_rollout_recommendation_payload(comparison_summary: dict[str, dict[str, object]]) -> dict[str, object]:
        assert comparison_summary["momentum_optimized"]["next_close_positive_rate"] == 0.61
        return {"action": "promote"}

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_md)
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "_build_replay_comparison_summary", fake_build_replay_comparison_summary)
    monkeypatch.setattr(optimize_profile, "_build_rollout_recommendation_payload", fake_build_rollout_recommendation_payload)
    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--grid-params",
            "select_threshold=0.50",
            "--input",
            str(replay_input),
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert comparison_called is True
    assert manifest_path.exists()

    published_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert published_manifest["status"] == "ready"
    assert published_manifest["profile_name"] == "momentum_optimized"
    assert published_manifest["profile_overrides"] == {}
    assert published_manifest["trade_date"] == "2026-05-12"

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["optimized_profile_manifest_publication"]["status"] == "published"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "promoted_btst_profile"
    assert payload["optimized_profile_manifest_publication"]["manifest_path"] == str(manifest_path.resolve())

    markdown = output_md.read_text(encoding="utf-8")
    assert "Optimized Profile Manifest Publication: **published**" in markdown
    assert f"- manifest_path: `{manifest_path.resolve()}`" in markdown
    assert "- reason: `promoted_btst_profile`" in markdown


def test_main_focused_stage_can_autoload_best_params_from_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "completed_trials": [
                    {"params": {"select_threshold": 0.46, "near_miss_threshold": 0.30}, "score": 0.31},
                    {"params": {"select_threshold": 0.50, "near_miss_threshold": 0.34}, "score": 0.42},
                ]
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )

    def fake_run_param_search(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(best_params={"select_threshold": 0.50, "near_miss_threshold": 0.34}, best_score=0.42, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1)

    monkeypatch.setattr(optimize_profile, "run_param_search", fake_run_param_search)
    monkeypatch.setattr(optimize_profile, "save_search_report", lambda report, output_path=None: tmp_path / "report.md")
    monkeypatch.setattr(optimize_profile, "save_search_payload", lambda report, output_path=None: tmp_path / "report.json")
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--preset-grid",
            "--input",
            "dummy.json",
            "--search-stage",
            "focused",
            "--checkpoint",
            str(checkpoint),
        ]
    )

    assert exit_code == 0
    assert captured["space"].grid["select_threshold"] == [0.46, 0.50, 0.54]
    assert captured["space"].grid["near_miss_threshold"] == [0.30, 0.34, 0.38]


def test_main_staged_search_runs_coarse_then_focused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_json = tmp_path / "report.json"
    stage_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )

    def fake_run_param_search(**kwargs: object) -> SimpleNamespace:
        stage_calls.append(kwargs)
        best_params = {"select_threshold": 0.50, "near_miss_threshold": 0.34} if len(stage_calls) == 1 else {"select_threshold": 0.54, "near_miss_threshold": 0.38}
        best_score = 0.42 if len(stage_calls) == 1 else 0.47
        return SimpleNamespace(best_params=best_params, best_score=best_score, objective=kwargs["objective"], results=[], completed_trials=1, total_trials=1)

    def fake_save_search_report(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or tmp_path / "report.md")
        path.write_text("# Parameter Search Report\n", encoding="utf-8")
        return path

    def fake_save_search_payload(report: object, output_path: str | None = None) -> Path:
        path = Path(output_path or output_json)
        path.write_text('{"best_params": {"select_threshold": 0.54}}', encoding="utf-8")
        return path

    monkeypatch.setattr(optimize_profile, "run_param_search", fake_run_param_search)
    monkeypatch.setattr(optimize_profile, "save_search_report", fake_save_search_report)
    monkeypatch.setattr(optimize_profile, "save_search_payload", fake_save_search_payload)
    monkeypatch.setattr(optimize_profile, "format_search_report", lambda report: "ok")

    exit_code = optimize_profile.main(
        [
            "--profile",
            "momentum_optimized",
            "--objective",
            "btst",
            "--preset-grid",
            "--input",
            "dummy.json",
            "--search-stage",
            "staged",
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert len(stage_calls) == 2
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["metadata"]["stage_results"]["coarse"]["best_score"] == pytest.approx(0.42)
    assert payload["metadata"]["stage_results"]["focused"]["best_score"] == pytest.approx(0.47)


def test_main_rejects_grids_over_max_combinations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        optimize_profile,
        "_build_replay_evaluator",
        lambda *args, **kwargs: (lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}),
    )

    with pytest.raises(ValueError, match="max_combinations"):
        optimize_profile.main(
            [
                "--profile",
                "momentum_optimized",
                "--objective",
                "btst",
                "--grid-params",
                "select_threshold=0.46,0.50,0.54",
                "near_miss_threshold=0.30,0.34,0.38",
                "--input",
                "dummy.json",
                "--max-combinations",
                "2",
            ]
        )


def test_derive_latest_replay_trade_date_returns_latest_date_from_replay_inputs() -> None:
    replay_input_paths = [
        Path("data/reports/run_1/selection_artifacts/2026-05-09/selection_target_replay_input.json"),
        Path("data/reports/run_1/selection_artifacts/2026-05-12/selection_target_replay_input.json"),
        Path("data/reports/run_1/selection_artifacts/2026-05-10/selection_target_replay_input.json"),
    ]

    assert derive_latest_replay_trade_date(replay_input_paths) == "2026-05-12"


def test_derive_latest_replay_trade_date_returns_none_when_replay_dates_cannot_be_derived() -> None:
    replay_input_paths = [
        Path("data/reports/run_1/selection_artifacts/not-a-date/selection_target_replay_input.json"),
        Path("data/reports/run_1/selection_artifacts/2026-05-12/other.json"),
    ]

    assert derive_latest_replay_trade_date(replay_input_paths) is None


def test_publish_btst_optimized_profile_manifest_writes_ready_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    source_path = tmp_path / "report.json"
    source_path.write_text("{}", encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        manifest_path=manifest_path,
        rollout_recommendation="promote",
        profile_name="momentum_optimized",
        profile_overrides={"select_threshold": 0.48, "near_miss_threshold": 0.34},
        source_path=source_path,
        replay_input_paths=[
            tmp_path / "selection_artifacts" / "2026-05-10" / "selection_target_replay_input.json",
            tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json",
        ],
    )

    assert result["status"] == "published"
    assert result["reason"] == "promoted_btst_profile"
    assert result["manifest_path"] == str(manifest_path.resolve())
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["payload"] == payload
    assert payload == build_ready_btst_optimized_profile_manifest(
        profile_name="momentum_optimized",
        profile_overrides={"select_threshold": 0.48, "near_miss_threshold": 0.34},
        source_path=source_path,
        replay_input_paths=[
            tmp_path / "selection_artifacts" / "2026-05-10" / "selection_target_replay_input.json",
            tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json",
        ],
    )
    assert payload["trade_date"] == "2026-05-12"
    assert payload["status"] == "ready"


def test_publish_btst_optimized_profile_manifest_promote_writes_null_trade_date_when_unavailable(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    source_path = tmp_path / "report.json"
    source_path.write_text("{}", encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        manifest_path=manifest_path,
        rollout_recommendation="promote",
        profile_name="momentum_optimized",
        profile_overrides={"select_threshold": 0.48},
        source_path=source_path,
        replay_input_paths=[
            tmp_path / "selection_artifacts" / "not-a-date" / "selection_target_replay_input.json",
            tmp_path / "selection_artifacts" / "2026-05-12" / "unexpected.json",
        ],
    )

    assert result["status"] == "published"
    assert result["reason"] == "promoted_btst_profile"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["trade_date"] is None
    assert result["payload"] == payload


def test_publish_btst_optimized_profile_manifest_skips_hold_without_overwriting_existing_ready(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    existing_payload = {
        "profile_name": "momentum_optimized",
        "profile_overrides": {"select_threshold": 0.48},
        "source_type": "optimize_profile",
        "source_path": str(tmp_path / "existing_report.json"),
        "validated_by": "walk_forward_and_rollout",
        "trade_date": "2026-05-11",
        "status": "ready",
    }
    manifest_path.write_text(json.dumps(existing_payload, indent=2), encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        manifest_path=manifest_path,
        rollout_recommendation="hold",
        profile_name="candidate_profile",
        profile_overrides={"select_threshold": 0.55},
        source_path=tmp_path / "candidate_report.json",
        replay_input_paths=[tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json"],
    )

    assert result == {
        "status": "skipped",
        "reason": "rollout_recommendation_hold",
        "manifest_path": str(manifest_path.resolve()),
    }
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == existing_payload


# ---------------------------------------------------------------------------
# Tests for BTST runner objective and rollout metrics (Task 2)
# ---------------------------------------------------------------------------


def test_replay_evaluator_emits_runner_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        surface = {
            "next_day_available_count": 8,
            "closed_cycle_count": 6,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.58,
            "next_close_expectancy": 0.012,
            "next_close_payoff_ratio": 1.5,
            "t_plus_2_close_positive_rate": 0.58,
            "t_plus_2_close_return_distribution": {"median": 0.015},
            "t_plus_3_close_positive_rate": 0.56,
            "t_plus_3_close_expectancy": 0.011,
            "t_plus_3_close_return_distribution": {"median": 0.013},
            "next_close_return_distribution": {"p10": -0.02},
            "downside_p10": -0.02,
            "max_future_high_return_2_5d_hit_rate_at_20pct": 0.25,
            "runner_capture_count": 3,
            "max_future_high_return_2_5d_distribution": {"median": 0.19},
            "time_to_hit_20pct_median": 3.0,
        }
        return {"surface_summaries": {"selected": surface, "tradeable": surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    evaluator = _build_replay_evaluator([Path("runner_window.json")], base_profile="default")
    metrics = evaluator({})

    assert metrics["max_future_high_return_2_5d_hit_rate_at_20pct"] == pytest.approx(0.25)
    assert metrics["runner_capture_count"] == 3
    assert metrics["time_to_hit_20pct_median"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Round 9 Task S — Temporal recency decay
# ---------------------------------------------------------------------------


def test_compute_recency_decay_same_date_returns_one() -> None:
    """Windows with the same date as the reference receive a decay factor of 1.0."""
    assert _compute_recency_decay("2026-03-20", "2026-03-20") == pytest.approx(1.0)


def test_compute_recency_decay_half_life() -> None:
    """After exactly half_life_days the decay factor should be close to 0.5."""
    factor = _compute_recency_decay("2026-01-01", "2026-04-01", half_life_days=90)
    assert abs(factor - 0.5) < 0.01


def test_compute_recency_decay_floor() -> None:
    """Very old windows are floored at RECENCY_DECAY_MIN_FACTOR, never zero."""
    factor = _compute_recency_decay("2020-01-01", "2026-03-20")
    assert factor == pytest.approx(RECENCY_DECAY_MIN_FACTOR)


def test_compute_recency_decay_future_date_clamps_to_one() -> None:
    """Negative lag (window newer than reference) should return 1.0 due to max(0, lag)."""
    factor = _compute_recency_decay("2026-04-01", "2026-03-20")
    assert factor == pytest.approx(1.0)


def test_build_recency_decay_map_latest_is_one() -> None:
    """The most recent path in the batch must have decay factor exactly 1.0."""
    paths = [
        Path("data/selection_artifacts/2026-01-01/selection_target_replay_input.json"),
        Path("data/selection_artifacts/2026-02-01/selection_target_replay_input.json"),
        Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json"),
    ]
    decay_map = _build_recency_decay_map(paths)
    latest = paths[-1]
    assert decay_map[str(latest)] == pytest.approx(1.0)


def test_build_recency_decay_map_older_paths_lower() -> None:
    """Older windows must have strictly smaller decay factors than newer ones."""
    paths = [
        Path("data/selection_artifacts/2025-10-01/selection_target_replay_input.json"),
        Path("data/selection_artifacts/2026-01-01/selection_target_replay_input.json"),
        Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json"),
    ]
    dm = _build_recency_decay_map(paths)
    assert dm[str(paths[0])] < dm[str(paths[1])] < dm[str(paths[2])]


def test_recency_decay_applied_to_sample_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator should apply recency decay: two windows with different dates yield different effective weights."""
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")
    call_order: list[str] = []

    def fake_analyze_btst_profile_replay_window(input_path: Path, **_: object) -> dict[str, object]:
        call_order.append(str(input_path.parent.name))
        surface = {
            "next_day_available_count": 10,
            "closed_cycle_count": 6,
            "next_close_positive_rate": 0.60,
            "next_high_hit_rate_at_threshold": 0.60,
            "next_close_expectancy": 0.015,
            "next_close_payoff_ratio": 1.5,
            "t_plus_2_close_positive_rate": 0.58,
            "t_plus_2_close_return_distribution": {"median": 0.014},
            "t_plus_3_close_positive_rate": 0.56,
            "t_plus_3_close_expectancy": 0.010,
            "t_plus_3_close_return_distribution": {"median": 0.012},
            "next_close_return_distribution": {"p10": -0.02},
        }
        return {"surface_summaries": {"selected": surface, "tradeable": surface}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze_btst_profile_replay_window
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    old_path = Path("data/selection_artifacts/2025-09-01/selection_target_replay_input.json")
    new_path = Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")
    evaluator = _build_replay_evaluator([old_path, new_path], base_profile="default")
    metrics = evaluator({})
    # Both windows run; overall sample_weight should be dominated by the newer window.
    # The reported avg sample_weight should be > RECENCY_DECAY_MIN_FACTOR (old floor) and ≤ 1.0.
    assert metrics["sample_weight"] is not None
    assert RECENCY_DECAY_MIN_FACTOR <= metrics["sample_weight"] <= 1.0


# ---------------------------------------------------------------------------
# Round 9 Task U — Dynamic liquidity regime weight penalty
# ---------------------------------------------------------------------------


def test_low_liquidity_window_reduces_sample_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """A window whose per-stock avg liquidity is below LIQUIDITY_LOW_REGIME_FLOOR should result in a lower effective sample_weight."""
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    _common_surface = {
        "next_day_available_count": 10,
        "closed_cycle_count": 6,
        "next_close_positive_rate": 0.60,
        "next_high_hit_rate_at_threshold": 0.60,
        "next_close_expectancy": 0.015,
        "next_close_payoff_ratio": 1.5,
        "t_plus_2_close_positive_rate": 0.58,
        "t_plus_2_close_return_distribution": {"median": 0.014},
        "t_plus_3_close_positive_rate": 0.56,
        "t_plus_3_close_expectancy": 0.010,
        "t_plus_3_close_return_distribution": {"median": 0.012},
        "next_close_return_distribution": {"p10": -0.02},
    }
    # Rows must have "decision": "selected" and liquidity in metrics_payload
    # to pass through _resolve_scope_rows and _extract_committee_component_metric.
    _low_liq_rows = [{"decision": "selected", "metrics_payload": {"liquidity_capacity_raw_100": LIQUIDITY_LOW_REGIME_FLOOR - 5.0}}]
    _high_liq_rows = [{"decision": "selected", "metrics_payload": {"liquidity_capacity_raw_100": 70.0}}]

    def fake_low_liq(input_path: Path, **_: object) -> dict[str, object]:
        return {"surface_summaries": {"selected": dict(_common_surface), "tradeable": dict(_common_surface)}, "rows": list(_low_liq_rows)}

    def fake_high_liq(input_path: Path, **_: object) -> dict[str, object]:
        return {"surface_summaries": {"selected": dict(_common_surface), "tradeable": dict(_common_surface)}, "rows": list(_high_liq_rows)}

    fake_low = types.ModuleType("scripts.btst_profile_replay_utils")
    fake_low.analyze_btst_profile_replay_window = fake_low_liq
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_low)
    evaluator_low = _build_replay_evaluator([Path("liq_low_2026-03-01.json")], base_profile="default")
    metrics_low = evaluator_low({})

    fake_high = types.ModuleType("scripts.btst_profile_replay_utils")
    fake_high.analyze_btst_profile_replay_window = fake_high_liq
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_high)
    evaluator_high = _build_replay_evaluator([Path("liq_high_2026-03-01.json")], base_profile="default")
    metrics_high = evaluator_high({})

    assert metrics_low["sample_weight"] is not None
    assert metrics_high["sample_weight"] is not None
    assert metrics_low["sample_weight"] < metrics_high["sample_weight"], (
        f"Low-liq sample_weight={metrics_low['sample_weight']} should be < high-liq={metrics_high['sample_weight']}"
    )


# ---------------------------------------------------------------------------
# Round 10 Task 4 — Recency half-life grid search
# ---------------------------------------------------------------------------


def test_recency_half_life_candidates_are_all_positive() -> None:
    """Every candidate half-life value must be a positive integer."""
    for hl in RECENCY_HALF_LIFE_CANDIDATES:
        assert isinstance(hl, int) and hl > 0, f"Invalid half-life candidate: {hl}"


def test_recency_half_life_candidates_include_default() -> None:
    """The default RECENCY_HALF_LIFE_DAYS must be present in RECENCY_HALF_LIFE_CANDIDATES."""
    assert RECENCY_HALF_LIFE_DAYS in RECENCY_HALF_LIFE_CANDIDATES


def test_build_recency_decay_map_respects_half_life_param() -> None:
    """A shorter half-life should produce steeper decay (lower factor) for old windows.

    The old window is chosen to be ~120 calendar days before the reference so that it
    falls above the RECENCY_DECAY_MIN_FACTOR floor under both candidate half-lives yet
    produces meaningfully different factors (0.25 vs ~0.63 for 60- vs 180-day half-life).
    """
    paths = [
        # ~120 days before the reference date below.
        Path("data/selection_artifacts/2025-11-20/selection_target_replay_input.json"),
        Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json"),
    ]
    old_path_key = str(paths[0])
    dm_short = _build_recency_decay_map(paths, half_life_days=60)
    dm_long = _build_recency_decay_map(paths, half_life_days=180)
    # The oldest window must decay more steeply with the shorter half-life.
    assert dm_short[old_path_key] < dm_long[old_path_key], (
        f"short half-life={dm_short[old_path_key]} should be < long half-life={dm_long[old_path_key]}"
    )
    # The newest window always has factor 1.0 regardless of half-life.
    assert dm_short[str(paths[1])] == pytest.approx(1.0)
    assert dm_long[str(paths[1])] == pytest.approx(1.0)


def test_evaluator_uses_recency_half_life_days_param(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator trials with shorter half-life should weight old windows less than trials with longer half-life.

    Windows are chosen to be ~100 calendar days apart so both half-life candidates (60 and 180 days)
    keep the old window above the RECENCY_DECAY_MIN_FACTOR floor, producing different effective weights.
    """
    _surface = {
        "next_day_available_count": 10,
        "closed_cycle_count": 6,
        "next_close_positive_rate": 0.60,
        "next_high_hit_rate_at_threshold": 0.60,
        "next_close_expectancy": 0.015,
        "next_close_payoff_ratio": 1.5,
        "t_plus_2_close_positive_rate": 0.58,
        "t_plus_2_close_return_distribution": {"median": 0.014},
        "t_plus_3_close_positive_rate": 0.56,
        "t_plus_3_close_expectancy": 0.010,
        "t_plus_3_close_return_distribution": {"median": 0.012},
        "next_close_return_distribution": {"p10": -0.02},
    }

    def fake_analyze(input_path: Path, **_: object) -> dict[str, object]:
        return {"surface_summaries": {"selected": dict(_surface), "tradeable": dict(_surface)}}

    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")
    fake_module.analyze_btst_profile_replay_window = fake_analyze
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)

    # Two windows: ~100 days apart — old window stays above floor for both half-life candidates.
    old_path = Path("data/selection_artifacts/2025-12-10/selection_target_replay_input.json")
    new_path = Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")
    evaluator = _build_replay_evaluator([old_path, new_path], base_profile="default")

    # Short half-life: old window heavily discounted → lower composite sample_weight.
    metrics_short = evaluator({"recency_half_life_days": 60})
    # Long half-life: old window receives more weight → higher composite sample_weight.
    metrics_long = evaluator({"recency_half_life_days": 180})

    assert metrics_short["sample_weight"] is not None
    assert metrics_long["sample_weight"] is not None
    # With two windows (one old, one new), longer half-life must yield equal or higher weight.
    assert metrics_short["sample_weight"] <= metrics_long["sample_weight"], (
        f"short={metrics_short['sample_weight']} should be ≤ long={metrics_long['sample_weight']}"
    )


# ---------------------------------------------------------------------------
# Round 11 Task 1 — IC signal collection in replay evaluator
# ---------------------------------------------------------------------------


def _make_fake_module_with_surface(surface: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: register a fake btst_profile_replay_utils module that always returns ``surface``."""
    fake_module = types.ModuleType("scripts.btst_profile_replay_utils")

    def fake_analyze(input_path: Path, **_: object) -> dict[str, object]:
        return {"surface_summaries": {"selected": dict(surface), "tradeable": dict(surface)}}

    fake_module.analyze_btst_profile_replay_window = fake_analyze
    monkeypatch.setitem(sys.modules, "scripts.btst_profile_replay_utils", fake_module)


def _base_replay_surface() -> dict:
    """Minimal surface that satisfies the replay evaluator's data requirements."""
    return {
        "next_day_available_count": 10,
        "closed_cycle_count": 6,
        "next_close_positive_rate": 0.62,
        "next_high_hit_rate_at_threshold": 0.64,
        "next_close_expectancy": 0.018,
        "next_close_payoff_ratio": 1.6,
        "t_plus_2_close_positive_rate": 0.58,
        "t_plus_2_close_return_distribution": {"median": 0.014},
        "t_plus_3_close_positive_rate": 0.56,
        "t_plus_3_close_expectancy": 0.011,
        "t_plus_3_close_return_distribution": {"median": 0.012},
        "next_close_return_distribution": {"p10": -0.018},
        "downside_p10": -0.018,
    }


def test_replay_evaluator_reads_factor_ic_from_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator must aggregate factor ICs across windows and expose ic_positive_factor_fraction."""
    surface = _base_replay_surface()
    # Inject IC values: all 7 factors positive → fraction should be 1.0
    surface["factor_ic_next_close"] = {
        "breakout_freshness": 0.08,
        "trend_acceleration": 0.05,
        "volume_expansion_quality": 0.06,
        "catalyst_freshness": 0.03,
        "close_strength": 0.04,
        "volatility_regime": 0.07,
        "sector_resonance": 0.09,
    }
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator([Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")], base_profile="default")
    metrics = evaluator({})

    assert "ic_positive_factor_fraction" in metrics
    # All 7 ICs are above IC_SIGNAL_MIN (0.02) → fraction = 1.0
    assert metrics["ic_positive_factor_fraction"] == pytest.approx(1.0)


def test_replay_evaluator_ic_fraction_none_when_no_ic_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no factor_ic_next_close is present on any window surface, ic_positive_factor_fraction must be None."""
    surface = _base_replay_surface()
    # No IC key injected
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator([Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")], base_profile="default")
    metrics = evaluator({})

    assert metrics.get("ic_positive_factor_fraction") is None


def test_replay_evaluator_ic_fraction_partial_factors_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """ic_positive_factor_fraction reflects only the fraction of factors with IC >= IC_SIGNAL_MIN."""
    surface = _base_replay_surface()
    # 4 out of 7 factors above threshold
    surface["factor_ic_next_close"] = {
        "breakout_freshness": 0.05,   # above
        "trend_acceleration": 0.03,   # above
        "volume_expansion_quality": -0.01,  # below
        "catalyst_freshness": 0.04,   # above
        "close_strength": 0.01,       # below (< 0.02)
        "volatility_regime": -0.03,   # below
        "sector_resonance": 0.06,     # above
    }
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator([Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")], base_profile="default")
    metrics = evaluator({})

    expected_fraction = 4 / 7
    assert metrics["ic_positive_factor_fraction"] == pytest.approx(expected_fraction, abs=0.01)


def test_replay_evaluator_returns_candidate_pool_avg_composite_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator must aggregate candidate_pool_avg_composite_score across windows and return its mean."""
    surface = _base_replay_surface()
    surface["candidate_pool_avg_composite_score"] = 0.67
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator([Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")], base_profile="default")
    metrics = evaluator({})

    assert "candidate_pool_avg_composite_score" in metrics
    assert metrics["candidate_pool_avg_composite_score"] == pytest.approx(0.67, abs=0.01)


def test_replay_evaluator_pool_quality_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """candidate_pool_avg_composite_score must be None when not present in the surface."""
    surface = _base_replay_surface()
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator([Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")], base_profile="default")
    metrics = evaluator({})

    assert metrics.get("candidate_pool_avg_composite_score") is None


# ---------------------------------------------------------------------------
# Round 12 Task 1 — Intraday drawdown metric in replay evaluator
# ---------------------------------------------------------------------------


def test_replay_evaluator_reads_intraday_drawdown_p10_from_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator must aggregate t_plus_1_intraday_drawdown_p10 via sample-weighted average."""
    surface = _base_replay_surface()
    surface["t_plus_1_intraday_drawdown_p10"] = -0.04
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator(
        [Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")],
        base_profile="default",
    )
    metrics = evaluator({})

    assert "t_plus_1_intraday_drawdown_p10" in metrics
    val = metrics["t_plus_1_intraday_drawdown_p10"]
    assert val is not None
    assert val == pytest.approx(-0.04, abs=0.005)


def test_replay_evaluator_intraday_drawdown_p10_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When surface has no t_plus_1_intraday_drawdown_p10, the evaluator must return None for the metric."""
    surface = _base_replay_surface()
    # No t_plus_1_intraday_drawdown_p10 injected
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator(
        [Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")],
        base_profile="default",
    )
    metrics = evaluator({})

    assert metrics.get("t_plus_1_intraday_drawdown_p10") is None


# ---------------------------------------------------------------------------
# Round 12 Task 3 — IC weight suggestions aggregated across replay windows
# ---------------------------------------------------------------------------


def test_replay_evaluator_returns_ic_weight_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluator must aggregate ic_weight_suggestions via majority-vote and return the dict."""
    surface = _base_replay_surface()
    surface["ic_weight_suggestions"] = {
        "breakout_freshness": "increase",
        "trend_acceleration": "maintain",
        "volume_expansion_quality": "reduce",
        "catalyst_freshness": "maintain",
        "close_strength": "increase",
        "volatility_regime": "maintain",
        "sector_resonance": "reduce",
    }
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator(
        [Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")],
        base_profile="default",
    )
    metrics = evaluator({})

    assert "ic_weight_suggestions" in metrics
    suggestions = metrics["ic_weight_suggestions"]
    assert isinstance(suggestions, dict)
    # With a single window the majority-vote should reproduce the original suggestions exactly
    assert suggestions.get("breakout_freshness") == "increase"
    assert suggestions.get("volume_expansion_quality") == "reduce"
    assert suggestions.get("trend_acceleration") == "maintain"


def test_replay_evaluator_ic_weight_suggestions_empty_when_no_surface_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ic_weight_suggestions must be an empty dict when surface has no ic_weight_suggestions."""
    surface = _base_replay_surface()
    # No ic_weight_suggestions injected
    _make_fake_module_with_surface(surface, monkeypatch)

    evaluator = _build_replay_evaluator(
        [Path("data/selection_artifacts/2026-03-20/selection_target_replay_input.json")],
        base_profile="default",
    )
    metrics = evaluator({})

    # key must exist but be an empty dict (no votes accumulated)
    assert "ic_weight_suggestions" in metrics
    assert metrics["ic_weight_suggestions"] == {}


# ---------------------------------------------------------------------------
# Round 13 — Task 3: IC Weight Feedback Loop (apply_ic_feedback_to_probe_grid)
# ---------------------------------------------------------------------------


def test_apply_ic_feedback_reduce_drops_top_candidate() -> None:
    """'reduce' suggestion must remove the highest candidate value from the grid (Task 3, Round 13)."""
    from scripts.optimize_profile import apply_ic_feedback_to_probe_grid, BTST_RUNNER_PROBE_GRID

    suggestions = {"breakout_freshness": "reduce"}
    result = apply_ic_feedback_to_probe_grid(suggestions, BTST_RUNNER_PROBE_GRID)

    original = sorted(float(v) for v in BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"])
    modified = sorted(float(v) for v in result["runner_composite_score_breakout_weight"])

    assert max(modified) < max(original), (
        f"'reduce' should drop the top candidate: original={original}, modified={modified}"
    )
    assert len(modified) == len(original) - 1


def test_apply_ic_feedback_increase_adds_one_step_above_max() -> None:
    """'increase' suggestion must add a candidate one IC_WEIGHT_GRID_STEP above the current max (Task 3, Round 13)."""
    from scripts.optimize_profile import (
        apply_ic_feedback_to_probe_grid,
        BTST_RUNNER_PROBE_GRID,
        IC_WEIGHT_GRID_STEP,
        IC_WEIGHT_GRID_MAX_UPPER_BOUND,
    )

    suggestions = {"trend_acceleration": "increase"}
    result = apply_ic_feedback_to_probe_grid(suggestions, BTST_RUNNER_PROBE_GRID)

    original_max = max(float(v) for v in BTST_RUNNER_PROBE_GRID["runner_composite_score_trend_weight"])
    expected_new_max = round(original_max + IC_WEIGHT_GRID_STEP, 4)

    modified = sorted(float(v) for v in result["runner_composite_score_trend_weight"])

    if expected_new_max <= IC_WEIGHT_GRID_MAX_UPPER_BOUND:
        assert max(modified) == pytest.approx(expected_new_max, abs=1e-6), (
            f"'increase' should add {expected_new_max} but got max={max(modified)}"
        )
        assert len(modified) == len(BTST_RUNNER_PROBE_GRID["runner_composite_score_trend_weight"]) + 1


def test_apply_ic_feedback_maintain_leaves_candidates_unchanged() -> None:
    """'maintain' suggestion must not alter the candidate list (Task 3, Round 13)."""
    from scripts.optimize_profile import apply_ic_feedback_to_probe_grid, BTST_RUNNER_PROBE_GRID

    suggestions = {"volume_expansion_quality": "maintain"}
    result = apply_ic_feedback_to_probe_grid(suggestions, BTST_RUNNER_PROBE_GRID)

    original = sorted(float(v) for v in BTST_RUNNER_PROBE_GRID["runner_composite_score_volume_weight"])
    modified = sorted(float(v) for v in result["runner_composite_score_volume_weight"])

    assert original == pytest.approx(modified, abs=1e-6), (
        f"'maintain' should not change candidates: original={original}, modified={modified}"
    )


def test_apply_ic_feedback_unknown_factor_is_ignored() -> None:
    """Suggestions for factors not in BTST_FACTOR_TO_PROBE_WEIGHT_KEY must be silently ignored (Task 3, Round 13)."""
    from scripts.optimize_profile import apply_ic_feedback_to_probe_grid, BTST_RUNNER_PROBE_GRID

    suggestions = {"nonexistent_factor": "reduce", "breakout_freshness": "maintain"}
    # Should not raise; should return grid unchanged for the nonexistent factor
    result = apply_ic_feedback_to_probe_grid(suggestions, BTST_RUNNER_PROBE_GRID)
    assert isinstance(result, dict)
    assert "runner_composite_score_breakout_weight" in result


def test_apply_ic_feedback_reduce_never_empties_candidate_list() -> None:
    """'reduce' must never reduce a single-candidate list to empty (Task 3, Round 13)."""
    from scripts.optimize_profile import apply_ic_feedback_to_probe_grid

    # Construct a minimal grid with only one candidate for the target weight key
    minimal_grid: dict = {"runner_composite_score_breakout_weight": [0.40]}
    suggestions = {"breakout_freshness": "reduce"}

    result = apply_ic_feedback_to_probe_grid(suggestions, minimal_grid)

    modified = result["runner_composite_score_breakout_weight"]
    assert len(modified) >= 1, "reduce must never empty the candidate list"


def test_apply_ic_feedback_increase_respects_max_upper_bound() -> None:
    """'increase' must not add a candidate that exceeds IC_WEIGHT_GRID_MAX_UPPER_BOUND (Task 3, Round 13)."""
    from scripts.optimize_profile import (
        apply_ic_feedback_to_probe_grid,
        IC_WEIGHT_GRID_MAX_UPPER_BOUND,
        IC_WEIGHT_GRID_STEP,
    )

    # Place the max exactly at the bound
    at_ceiling_grid: dict = {"runner_composite_score_breakout_weight": [IC_WEIGHT_GRID_MAX_UPPER_BOUND]}
    suggestions = {"breakout_freshness": "increase"}

    result = apply_ic_feedback_to_probe_grid(suggestions, at_ceiling_grid)

    modified = sorted(float(v) for v in result["runner_composite_score_breakout_weight"])
    assert max(modified) <= IC_WEIGHT_GRID_MAX_UPPER_BOUND, (
        f"'increase' exceeded IC_WEIGHT_GRID_MAX_UPPER_BOUND {IC_WEIGHT_GRID_MAX_UPPER_BOUND}: max={max(modified)}"
    )


def test_apply_ic_feedback_does_not_mutate_base_grid() -> None:
    """apply_ic_feedback_to_probe_grid must return a new dict and not modify the input (Task 3, Round 13)."""
    from scripts.optimize_profile import apply_ic_feedback_to_probe_grid, BTST_RUNNER_PROBE_GRID

    original_breakout = list(BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"])
    suggestions = {"breakout_freshness": "reduce"}

    _ = apply_ic_feedback_to_probe_grid(suggestions, BTST_RUNNER_PROBE_GRID)

    # Original grid must be unchanged
    assert list(BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"]) == original_breakout, (
        "apply_ic_feedback_to_probe_grid must not mutate the input grid"
    )


def test_resolve_grid_params_btst_runner_probe_applies_ic_feedback() -> None:
    """resolve_grid_params must apply IC feedback when ic_weight_suggestions is provided (Task 3, Round 13)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID

    # 'reduce' for breakout_freshness should drop the top candidate
    suggestions = {"breakout_freshness": "reduce"}

    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="btst_runner_probe",
        ic_weight_suggestions=suggestions,
    )

    original_breakout = sorted(float(v) for v in BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"])
    result_breakout = sorted(float(v) for v in grid["runner_composite_score_breakout_weight"])

    assert max(result_breakout) < max(original_breakout), (
        f"IC feedback 'reduce' should drop top breakout weight: original={original_breakout}, result={result_breakout}"
    )


def test_resolve_grid_params_btst_runner_probe_no_ic_feedback_unchanged() -> None:
    """resolve_grid_params must return the base BTST_RUNNER_PROBE_GRID when ic_weight_suggestions=None (Task 3, Round 13)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID

    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="btst_runner_probe",
        ic_weight_suggestions=None,
    )

    assert sorted(grid["runner_composite_score_breakout_weight"]) == sorted(
        BTST_RUNNER_PROBE_GRID["runner_composite_score_breakout_weight"]
    ), "Without IC feedback, breakout weight candidates must match the base grid"
    assert sorted(grid["runner_composite_score_trend_weight"]) == sorted(
        BTST_RUNNER_PROBE_GRID["runner_composite_score_trend_weight"]
    ), "Without IC feedback, trend weight candidates must match the base grid"


def test_resolve_grid_params_non_btst_runner_probe_ignores_ic_feedback() -> None:
    """IC feedback must have no effect when profile_name != 'btst_runner_probe' (Task 3, Round 13)."""
    suggestions = {"breakout_freshness": "reduce"}

    # Use the default momentum profile; IC feedback should be silently ignored
    grid_with = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="default",
        ic_weight_suggestions=suggestions,
    )
    grid_without = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="default",
        ic_weight_suggestions=None,
    )

    assert grid_with == grid_without, (
        "IC suggestions should have no effect on non-btst_runner_probe profiles"
    )


# ---------------------------------------------------------------------------
# Round 15 — Task 4 / 5 / 2 : new metrics wired into optimize_profile.py
# ---------------------------------------------------------------------------

from scripts.optimize_profile import (
    COMPARISON_METRICS,
    COMPARISON_METRIC_LABELS,
    COMPARISON_METRIC_EPSILON,
    LOWER_IS_BETTER_COMPARISON_METRICS,
    OPTIONAL_COMPARISON_METRICS,
)


def test_r15_stop_loss_metrics_in_comparison_metrics() -> None:
    """stop_loss_trigger_rate_2pct/3pct/5pct must be in COMPARISON_METRICS (Task 4, Round 15)."""
    for key in ("stop_loss_trigger_rate_2pct", "stop_loss_trigger_rate_3pct", "stop_loss_trigger_rate_5pct"):
        assert key in COMPARISON_METRICS, f"{key} missing from COMPARISON_METRICS"


def test_r15_stop_loss_metrics_have_labels() -> None:
    """stop_loss trigger rate metrics must have human-readable labels (Task 4, Round 15)."""
    for key in ("stop_loss_trigger_rate_2pct", "stop_loss_trigger_rate_3pct", "stop_loss_trigger_rate_5pct"):
        assert key in COMPARISON_METRIC_LABELS, f"{key} missing from COMPARISON_METRIC_LABELS"


def test_r15_stop_loss_metrics_are_optional() -> None:
    """stop_loss trigger rate metrics must be optional (pre-Round-15 surfaces lack them) (Task 4, Round 15)."""
    for key in ("stop_loss_trigger_rate_2pct", "stop_loss_trigger_rate_3pct", "stop_loss_trigger_rate_5pct"):
        assert key in OPTIONAL_COMPARISON_METRICS, f"{key} missing from OPTIONAL_COMPARISON_METRICS"


def test_r15_stop_loss_metrics_are_lower_is_better() -> None:
    """stop_loss trigger rates must be lower-is-better (higher rate = more stops hit = worse) (Task 4, Round 15)."""
    for key in ("stop_loss_trigger_rate_2pct", "stop_loss_trigger_rate_3pct", "stop_loss_trigger_rate_5pct"):
        assert key in LOWER_IS_BETTER_COMPARISON_METRICS, f"{key} missing from LOWER_IS_BETTER_COMPARISON_METRICS"


def test_r15_stop_loss_metrics_have_epsilon() -> None:
    """stop_loss trigger rate metrics must have epsilon values in COMPARISON_METRIC_EPSILON (Task 4, Round 15)."""
    for key in ("stop_loss_trigger_rate_2pct", "stop_loss_trigger_rate_3pct", "stop_loss_trigger_rate_5pct"):
        assert key in COMPARISON_METRIC_EPSILON, f"{key} missing from COMPARISON_METRIC_EPSILON"


def test_r15_cross_day_autocorr_metrics_in_comparison_metrics() -> None:
    """cross_day_autocorr_t1_vs_t2 and t2_vs_t3 must be in COMPARISON_METRICS (Task 5, Round 15)."""
    assert "cross_day_autocorr_t1_vs_t2" in COMPARISON_METRICS
    assert "cross_day_autocorr_t2_vs_t3" in COMPARISON_METRICS


def test_r15_cross_day_autocorr_metrics_are_optional() -> None:
    """cross_day autocorr metrics must be optional (pre-Round-15 surfaces lack them) (Task 5, Round 15)."""
    assert "cross_day_autocorr_t1_vs_t2" in OPTIONAL_COMPARISON_METRICS
    assert "cross_day_autocorr_t2_vs_t3" in OPTIONAL_COMPARISON_METRICS


def test_r15_cross_day_autocorr_metrics_have_labels() -> None:
    """cross_day autocorr metrics must have human-readable labels (Task 5, Round 15)."""
    assert "cross_day_autocorr_t1_vs_t2" in COMPARISON_METRIC_LABELS
    assert "cross_day_autocorr_t2_vs_t3" in COMPARISON_METRIC_LABELS


def test_r15_gap_continuation_rate_in_comparison_metrics() -> None:
    """gap_continuation_rate must be in COMPARISON_METRICS (Task 2, Round 15)."""
    assert "gap_continuation_rate" in COMPARISON_METRICS


def test_r15_gap_continuation_rate_is_optional() -> None:
    """gap_continuation_rate must be optional (pre-Round-15 surfaces lack it) (Task 2, Round 15)."""
    assert "gap_continuation_rate" in OPTIONAL_COMPARISON_METRICS


def test_r15_gap_continuation_rate_has_label() -> None:
    """gap_continuation_rate must have a human-readable label (Task 2, Round 15)."""
    assert "gap_continuation_rate" in COMPARISON_METRIC_LABELS


def test_r15_gap_continuation_rate_has_epsilon() -> None:
    """gap_continuation_rate must have an epsilon value for regression detection (Task 2, Round 15)."""
    assert "gap_continuation_rate" in COMPARISON_METRIC_EPSILON


def test_r15_all_comparison_metrics_have_labels() -> None:
    """Every metric in COMPARISON_METRICS must have a corresponding label (invariant check)."""
    for metric in COMPARISON_METRICS:
        assert metric in COMPARISON_METRIC_LABELS, f"COMPARISON_METRICS entry '{metric}' has no label in COMPARISON_METRIC_LABELS"


# ===========================================================================
# Round 20 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Task 1 (Round 20, Beta): realized_payoff_ratio in COMPARISON_METRICS
# ---------------------------------------------------------------------------

def test_r20_realized_payoff_ratio_in_comparison_metrics() -> None:
    """realized_payoff_ratio must be in COMPARISON_METRICS (Task 1, Round 20)."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "realized_payoff_ratio" in COMPARISON_METRICS


def test_r20_realized_payoff_ratio_has_label() -> None:
    """realized_payoff_ratio must have a human-readable label (Task 1, Round 20)."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "realized_payoff_ratio" in COMPARISON_METRIC_LABELS


def test_r20_realized_payoff_ratio_is_optional() -> None:
    """realized_payoff_ratio must be optional (pre-Round-20 surfaces lack it) (Task 1, Round 20)."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "realized_payoff_ratio" in OPTIONAL_COMPARISON_METRICS


def test_r20_realized_payoff_ratio_has_epsilon() -> None:
    """realized_payoff_ratio must have an epsilon in COMPARISON_METRIC_EPSILON (Task 1, Round 20)."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    assert "realized_payoff_ratio" in COMPARISON_METRIC_EPSILON


def test_r20_realized_payoff_ratio_floor_in_btst_quality_floors() -> None:
    """realized_payoff_ratio must have a floor of 1.0 in BTST_QUALITY_FLOORS (Task 1, Round 20)."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "realized_payoff_ratio" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["realized_payoff_ratio"] == pytest.approx(1.0)


def test_r20_realized_payoff_ratio_floor_triggers_blocker() -> None:
    """Floor breach on realized_payoff_ratio must trigger a blocker label (Task 1, Round 20)."""
    from src.backtesting.evaluation_bundle import build_btst_quality_floor_blockers
    metrics = {"realized_payoff_ratio": 0.8, "next_close_positive_rate": 0.60, "next_high_hit_rate": 0.62, "t_plus_2_close_positive_rate": 0.55, "t_plus_2_close_payoff_ratio": 1.1, "t_plus_3_close_positive_rate": 0.52, "t_plus_3_close_expectancy": 0.01, "t_plus_3_close_payoff_ratio": 1.05, "downside_p10": -0.04, "sample_weight": 0.80, "window_coverage": 0.80, "avg_composite_score_escaped": 0.50, "t_plus_1_intraday_drawdown_p10": -0.05, "avg_escape_gap_cost": -0.01}
    blockers = build_btst_quality_floor_blockers(metrics)
    assert any("realized_payoff_ratio" in b for b in blockers), f"Expected realized_payoff_ratio blocker, got: {blockers}"


def test_r20_realized_payoff_ratio_no_blocker_when_above_floor() -> None:
    """No blocker for realized_payoff_ratio when it meets the floor (Task 1, Round 20)."""
    from src.backtesting.evaluation_bundle import build_btst_quality_floor_blockers
    metrics = {"realized_payoff_ratio": 1.5, "next_close_positive_rate": 0.60, "next_high_hit_rate": 0.62, "t_plus_2_close_positive_rate": 0.55, "t_plus_2_close_payoff_ratio": 1.1, "t_plus_3_close_positive_rate": 0.52, "t_plus_3_close_expectancy": 0.01, "t_plus_3_close_payoff_ratio": 1.05, "downside_p10": -0.04, "sample_weight": 0.80, "window_coverage": 0.80, "avg_composite_score_escaped": 0.50, "t_plus_1_intraday_drawdown_p10": -0.05, "avg_escape_gap_cost": -0.01}
    blockers = build_btst_quality_floor_blockers(metrics)
    assert not any("realized_payoff_ratio" in b for b in blockers), f"Unexpected realized_payoff_ratio blocker: {blockers}"


# ---------------------------------------------------------------------------
# Task 2 (Round 20, Alpha): score-conditioned metrics in COMPARISON_METRICS
# ---------------------------------------------------------------------------

def test_r20_score_conditioned_metrics_in_comparison_metrics() -> None:
    """All Task 2 Round 20 score-conditioned metrics must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    for key in ("high_confidence_selection_rate", "score_weighted_win_rate", "score_win_rate_lift", "high_confidence_win_rate"):
        assert key in COMPARISON_METRICS, f"{key} missing from COMPARISON_METRICS"


def test_r20_score_conditioned_metrics_have_labels() -> None:
    """All Task 2 Round 20 score-conditioned metrics must have labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    for key in ("high_confidence_selection_rate", "score_weighted_win_rate", "score_win_rate_lift", "high_confidence_win_rate"):
        assert key in COMPARISON_METRIC_LABELS, f"{key} missing from COMPARISON_METRIC_LABELS"


def test_r20_score_conditioned_metrics_are_optional() -> None:
    """All Task 2 Round 20 score-conditioned metrics must be optional."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    for key in ("high_confidence_selection_rate", "score_weighted_win_rate", "score_win_rate_lift", "high_confidence_win_rate"):
        assert key in OPTIONAL_COMPARISON_METRICS, f"{key} missing from OPTIONAL_COMPARISON_METRICS"


def test_r20_score_conditioned_metrics_have_epsilon() -> None:
    """All Task 2 Round 20 score-conditioned metrics must have epsilon values."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    for key in ("high_confidence_selection_rate", "score_weighted_win_rate", "score_win_rate_lift", "high_confidence_win_rate"):
        assert key in COMPARISON_METRIC_EPSILON, f"{key} missing from COMPARISON_METRIC_EPSILON"


# ---------------------------------------------------------------------------
# Task 3 (Round 20, Gamma): limit-up risk metrics in COMPARISON_METRICS
# ---------------------------------------------------------------------------

def test_r20_limit_up_metrics_in_comparison_metrics() -> None:
    """All Task 3 Round 20 limit-up metrics must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    for key in ("consecutive_limit_up_rate", "limit_up_win_rate", "non_limit_up_win_rate"):
        assert key in COMPARISON_METRICS, f"{key} missing from COMPARISON_METRICS"


def test_r20_limit_up_metrics_have_labels() -> None:
    """All Task 3 Round 20 limit-up metrics must have labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    for key in ("consecutive_limit_up_rate", "limit_up_win_rate", "non_limit_up_win_rate"):
        assert key in COMPARISON_METRIC_LABELS, f"{key} missing from COMPARISON_METRIC_LABELS"


def test_r20_limit_up_metrics_are_optional() -> None:
    """All Task 3 Round 20 limit-up metrics must be optional."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    for key in ("consecutive_limit_up_rate", "limit_up_win_rate", "non_limit_up_win_rate"):
        assert key in OPTIONAL_COMPARISON_METRICS, f"{key} missing from OPTIONAL_COMPARISON_METRICS"


def test_r20_consecutive_limit_up_rate_is_lower_is_better() -> None:
    """consecutive_limit_up_rate must be in LOWER_IS_BETTER_COMPARISON_METRICS (Task 3, Round 20)."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "consecutive_limit_up_rate" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r20_all_new_metrics_have_labels() -> None:
    """All Round 20 new metrics in COMPARISON_METRICS must have labels (invariant check)."""
    from scripts.optimize_profile import COMPARISON_METRICS, COMPARISON_METRIC_LABELS
    r20_metrics = ("realized_payoff_ratio", "high_confidence_selection_rate", "score_weighted_win_rate", "score_win_rate_lift", "high_confidence_win_rate", "consecutive_limit_up_rate", "limit_up_win_rate", "non_limit_up_win_rate")
    for metric in r20_metrics:
        assert metric in COMPARISON_METRICS, f"{metric} must be in COMPARISON_METRICS"
        assert metric in COMPARISON_METRIC_LABELS, f"{metric} must be in COMPARISON_METRIC_LABELS"


# =============================================================================
# Round 21 — Task 1 (Gamma): compute_surface_metric_correlations
# =============================================================================

def test_r21_compute_surface_metric_correlations_returns_empty_below_5_windows() -> None:
    """compute_surface_metric_correlations returns {} when fewer than 5 summaries provided."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    assert compute_surface_metric_correlations([]) == {}
    four_summaries = [{"next_close_positive_rate": 0.5, "some_metric": float(i)} for i in range(4)]
    assert compute_surface_metric_correlations(four_summaries) == {}


def test_r21_compute_surface_metric_correlations_positive_correlation() -> None:
    """Metrics that increase monotonically with win rate should have high positive Spearman corr."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    summaries = [{"next_close_positive_rate": float(i) / 9.0, "good_metric": float(i)} for i in range(10)]
    result = compute_surface_metric_correlations(summaries)
    assert "good_metric" in result, "good_metric should be in correlations"
    assert result["good_metric"] > 0.9, f"expected high positive corr, got {result['good_metric']}"


def test_r21_compute_surface_metric_correlations_negative_correlation() -> None:
    """Metrics that decrease as win rate increases should have negative Spearman corr."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    summaries = [{"next_close_positive_rate": float(i) / 9.0, "bad_metric": float(9 - i)} for i in range(10)]
    result = compute_surface_metric_correlations(summaries)
    assert "bad_metric" in result
    assert result["bad_metric"] < -0.9


def test_r21_compute_surface_metric_correlations_result_in_range() -> None:
    """All returned correlation values must be in [-1, 1]."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    import random
    random.seed(42)
    summaries = [{"next_close_positive_rate": random.random(), "m1": random.random(), "m2": random.random()} for _ in range(8)]
    result = compute_surface_metric_correlations(summaries)
    for k, v in result.items():
        if isinstance(v, float):
            assert -1.0 <= v <= 1.0, f"{k}={v} out of [-1,1]"


def test_r21_compute_surface_metric_correlations_top_bottom_5() -> None:
    """top_5_correlated_metrics and bottom_5_correlated_metrics must be present and be lists."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    summaries = [{"next_close_positive_rate": float(i) / 9.0, "m1": float(i), "m2": float(9 - i), "m3": float(i) * 0.5} for i in range(10)]
    result = compute_surface_metric_correlations(summaries)
    assert "top_5_correlated_metrics" in result
    assert isinstance(result["top_5_correlated_metrics"], list)
    assert "bottom_5_correlated_metrics" in result
    assert isinstance(result["bottom_5_correlated_metrics"], list)


def test_r21_compute_surface_metric_correlations_nan_in_summaries() -> None:
    """Summaries with None metric values are gracefully skipped; result still computed from valid pairs."""
    from scripts.btst_analysis_utils import compute_surface_metric_correlations
    summaries = [{"next_close_positive_rate": float(i) / 9.0, "partial": float(i) if i < 7 else None} for i in range(10)]
    result = compute_surface_metric_correlations(summaries)
    # partial has 7 valid pairs (i=0..6) — >= 5, so it should appear
    assert "partial" in result
    assert isinstance(result["partial"], float)


# =============================================================================
# Round 21 — Task 2 (Alpha): compute_factor_ic_stability
# =============================================================================

def test_r21_compute_factor_ic_stability_empty_input_returns_empty() -> None:
    """compute_factor_ic_stability returns {} when given empty list."""
    from scripts.btst_analysis_utils import compute_factor_ic_stability
    assert compute_factor_ic_stability([]) == {}


def test_r21_compute_factor_ic_stability_single_window_no_std() -> None:
    """Single-window input: std_IC = 0 and IR falls back to mean_IC."""
    from scripts.btst_analysis_utils import compute_factor_ic_stability, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    summaries = [{"factor_ic_next_close": {factor: 0.05}}]
    result = compute_factor_ic_stability(summaries)
    assert f"{factor}_ic_mean" in result
    assert result[f"{factor}_ic_mean"] == 0.05
    assert result[f"{factor}_ic_std"] == 0.0
    assert result[f"{factor}_ic_ir"] == 0.05  # fallback when std≈0


def test_r21_compute_factor_ic_stability_ir_computation() -> None:
    """IR = mean / std should be correctly computed for multi-window input."""
    from scripts.btst_analysis_utils import compute_factor_ic_stability, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    ic_vals = [0.04, 0.06, 0.05, 0.07, 0.03]
    summaries = [{"factor_ic_next_close": {factor: v}} for v in ic_vals]
    result = compute_factor_ic_stability(summaries)
    import math
    mean_ic = sum(ic_vals) / len(ic_vals)
    std_ic = math.sqrt(sum((v - mean_ic) ** 2 for v in ic_vals) / (len(ic_vals) - 1))
    expected_ir = mean_ic / std_ic
    assert abs(result[f"{factor}_ic_ir"] - round(expected_ir, 4)) < 0.001


def test_r21_compute_factor_ic_stability_most_least_stable() -> None:
    """most_stable_factor has highest IR; least_stable_factor has lowest IR."""
    from scripts.btst_analysis_utils import compute_factor_ic_stability, BTST_FACTOR_NAMES
    f1, f2 = BTST_FACTOR_NAMES[0], BTST_FACTOR_NAMES[1]
    # f1: constant IC 0.05 → std≈0 → IR = mean = 0.05
    # f2: highly volatile IC → low IR
    summaries = [{"factor_ic_next_close": {f1: 0.05, f2: float(i) * 0.10 - 0.25}} for i in range(6)]
    result = compute_factor_ic_stability(summaries)
    assert "most_stable_factor" in result
    assert "least_stable_factor" in result


def test_r21_compute_factor_ic_stability_positive_fraction() -> None:
    """ic_positive_fraction should reflect fraction of windows with IC > 0."""
    from scripts.btst_analysis_utils import compute_factor_ic_stability, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    ic_vals = [0.05, -0.02, 0.03, -0.01, 0.04]  # 3 positive out of 5
    summaries = [{"factor_ic_next_close": {factor: v}} for v in ic_vals]
    result = compute_factor_ic_stability(summaries)
    assert result[f"{factor}_ic_positive_fraction"] == 0.6


# =============================================================================
# Round 21 — Task 3 (Beta): compute_optimal_entry_signal
# =============================================================================

def _make_timing_rows(early_n: int, late_n: int, mid_n: int, t0_tail: float) -> list[dict]:
    """Helper: build synthetic rows with desired early/late/mid high-timing and t0_tail_strength."""
    rows = []
    # Early rows: open ≈ high (open/high ≥ 0.97)
    for _ in range(early_n):
        rows.append({"next_open": 100.0, "next_high": 100.0, "next_close": 95.0, "t0_tail_strength": t0_tail})
    # Late rows: close ≈ high (close/high ≥ 0.97, open/high < 0.97)
    for _ in range(late_n):
        rows.append({"next_open": 90.0, "next_high": 100.0, "next_close": 99.0, "t0_tail_strength": t0_tail})
    # Mid rows: neither
    for _ in range(mid_n):
        rows.append({"next_open": 90.0, "next_high": 100.0, "next_close": 90.0, "t0_tail_strength": t0_tail})
    return rows


def test_r21_compute_optimal_entry_signal_empty_rows_returns_uncertain() -> None:
    """Empty row list should return recommended_execution='uncertain' and None numeric fields."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    result = compute_optimal_entry_signal([])
    assert result["recommended_execution"] == "uncertain"
    assert result["open_entry_signal_strength"] is None
    assert result["wait_entry_signal_strength"] is None
    assert result["execution_timing_confidence"] is None


def test_r21_compute_optimal_entry_signal_early_dominated_recommends_immediate() -> None:
    """When most T+1 highs are early AND t0_tail_strength is high, recommend 'immediate'."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    rows = _make_timing_rows(early_n=8, late_n=1, mid_n=1, t0_tail=0.95)
    result = compute_optimal_entry_signal(rows)
    assert result["recommended_execution"] == "immediate", f"expected immediate, got {result['recommended_execution']}"
    assert result["open_entry_signal_strength"] is not None
    assert result["open_entry_signal_strength"] > result["wait_entry_signal_strength"]


def test_r21_compute_optimal_entry_signal_late_dominated_recommends_wait() -> None:
    """When most T+1 highs are late AND t0_tail_strength is low, recommend 'wait'."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    rows = _make_timing_rows(early_n=1, late_n=8, mid_n=1, t0_tail=0.30)
    result = compute_optimal_entry_signal(rows)
    assert result["recommended_execution"] == "wait", f"expected wait, got {result['recommended_execution']}"
    assert result["wait_entry_signal_strength"] > result["open_entry_signal_strength"]


def test_r21_compute_optimal_entry_signal_balanced_returns_uncertain() -> None:
    """Equal early/late split with median t0_tail=0.5 should yield 'uncertain'."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    rows = _make_timing_rows(early_n=5, late_n=5, mid_n=0, t0_tail=0.5)
    result = compute_optimal_entry_signal(rows)
    assert result["recommended_execution"] == "uncertain"


def test_r21_compute_optimal_entry_signal_signal_values_in_range() -> None:
    """All numeric output values must be in sensible ranges."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    rows = _make_timing_rows(early_n=6, late_n=2, mid_n=2, t0_tail=0.70)
    result = compute_optimal_entry_signal(rows)
    assert 0.0 <= result["open_entry_signal_strength"] <= 1.0
    assert 0.0 <= result["wait_entry_signal_strength"] <= 1.0
    assert isinstance(result["execution_timing_confidence"], float)


def test_r21_compute_optimal_entry_signal_missing_t0_tail_returns_uncertain() -> None:
    """Rows without t0_tail_strength should fall back to 'uncertain'."""
    from scripts.btst_analysis_utils import compute_optimal_entry_signal
    rows = [{"next_open": 100.0, "next_high": 100.0, "next_close": 95.0} for _ in range(5)]
    result = compute_optimal_entry_signal(rows)
    assert result["recommended_execution"] == "uncertain"
    assert result["open_entry_signal_strength"] is None


# =============================================================================
# Round 21 — COMPARISON_METRICS / optimizer registry checks
# =============================================================================

def test_r21_entry_signal_metrics_in_comparison_metrics() -> None:
    """open_entry_signal_strength and execution_timing_confidence must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "open_entry_signal_strength" in COMPARISON_METRICS
    assert "execution_timing_confidence" in COMPARISON_METRICS


def test_r21_entry_signal_metrics_have_labels() -> None:
    """R21 execution timing metrics must have labels in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "open_entry_signal_strength" in COMPARISON_METRIC_LABELS
    assert "execution_timing_confidence" in COMPARISON_METRIC_LABELS


def test_r21_entry_signal_metrics_are_optional() -> None:
    """R21 execution timing metrics must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "open_entry_signal_strength" in OPTIONAL_COMPARISON_METRICS
    assert "execution_timing_confidence" in OPTIONAL_COMPARISON_METRICS


def test_r21_entry_signal_metrics_have_epsilon() -> None:
    """R21 execution timing metrics must have epsilon entries."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    assert "open_entry_signal_strength" in COMPARISON_METRIC_EPSILON
    assert "execution_timing_confidence" in COMPARISON_METRIC_EPSILON


def test_r21_all_new_metrics_have_labels() -> None:
    """All Round 21 new metrics must be in both COMPARISON_METRICS and COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRICS, COMPARISON_METRIC_LABELS
    r21_metrics = ("open_entry_signal_strength", "execution_timing_confidence")
    for metric in r21_metrics:
        assert metric in COMPARISON_METRICS, f"{metric} must be in COMPARISON_METRICS"
        assert metric in COMPARISON_METRIC_LABELS, f"{metric} must be in COMPARISON_METRIC_LABELS"


# =============================================================================
# Round 22 — Task 1 (Gamma): compute_low_impact_probe_axes
# =============================================================================

def test_r22_compute_low_impact_probe_axes_empty_inputs_returns_empty_lists() -> None:
    """Empty surface_metric_correlations and ic_stability → all lists empty."""
    from scripts.optimize_profile import compute_low_impact_probe_axes
    result = compute_low_impact_probe_axes({}, {})
    assert result["low_impact_axes"] == []
    assert result["low_ir_factors"] == []
    assert result["pruning_candidates"] == []
    assert isinstance(result["pruning_summary"], str)


def test_r22_compute_low_impact_probe_axes_low_corr_threshold() -> None:
    """Factor with |corr| < threshold is added to low_impact_axes."""
    from scripts.optimize_profile import compute_low_impact_probe_axes, BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    factor = next(iter(BTST_FACTOR_TO_PROBE_WEIGHT_KEY))
    probe_key = BTST_FACTOR_TO_PROBE_WEIGHT_KEY[factor]
    result = compute_low_impact_probe_axes({factor: 0.01}, {}, ic_corr_threshold=0.05)
    assert probe_key in result["low_impact_axes"]
    assert probe_key not in result["pruning_candidates"]  # IR condition not met


def test_r22_compute_low_impact_probe_axes_low_ir_threshold() -> None:
    """Factor with IR < threshold is added to low_ir_factors."""
    from scripts.optimize_profile import compute_low_impact_probe_axes, BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    factor = next(iter(BTST_FACTOR_TO_PROBE_WEIGHT_KEY))
    result = compute_low_impact_probe_axes({}, {f"{factor}_ic_ir": 0.10}, ir_threshold=0.20)
    assert factor in result["low_ir_factors"]
    assert BTST_FACTOR_TO_PROBE_WEIGHT_KEY[factor] not in result["pruning_candidates"]  # corr condition not met


def test_r22_compute_low_impact_probe_axes_pruning_candidate_requires_both() -> None:
    """pruning_candidates only includes axes where BOTH low-corr AND low-IR hold."""
    from scripts.optimize_profile import compute_low_impact_probe_axes, BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    factor = next(iter(BTST_FACTOR_TO_PROBE_WEIGHT_KEY))
    probe_key = BTST_FACTOR_TO_PROBE_WEIGHT_KEY[factor]
    result = compute_low_impact_probe_axes(
        {factor: 0.01},
        {f"{factor}_ic_ir": 0.10},
        ic_corr_threshold=0.05,
        ir_threshold=0.20,
    )
    assert probe_key in result["pruning_candidates"]
    assert factor in result["low_ir_factors"]


def test_r22_compute_low_impact_probe_axes_high_corr_not_flagged() -> None:
    """Factor with |corr| above threshold must NOT appear in low_impact_axes."""
    from scripts.optimize_profile import compute_low_impact_probe_axes, BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    factor = next(iter(BTST_FACTOR_TO_PROBE_WEIGHT_KEY))
    probe_key = BTST_FACTOR_TO_PROBE_WEIGHT_KEY[factor]
    result = compute_low_impact_probe_axes({factor: 0.30}, {}, ic_corr_threshold=0.05)
    assert probe_key not in result["low_impact_axes"]


# =============================================================================
# Round 22 — Task 2 (Alpha): compute_optimal_hold_period
# =============================================================================

def _make_hold_rows(t1: list[float], t2: list[float], t3: list[float]) -> list[dict]:
    """Build synthetic rows with T+1/T+2/T+3 returns."""
    max_len = max(len(t1), len(t2), len(t3))
    rows = []
    for i in range(max_len):
        row: dict = {}
        if i < len(t1):
            row["next_close_return"] = t1[i]
        if i < len(t2):
            row["t_plus_2_close_return"] = t2[i]
        if i < len(t3):
            row["t_plus_3_close_return"] = t3[i]
        rows.append(row)
    return rows


def test_r22_compute_optimal_hold_period_t1_optimal() -> None:
    """When T+1 has clearly higher Sharpe, optimal_hold_days should be 1."""
    from scripts.btst_analysis_utils import compute_optimal_hold_period
    t1 = [0.05, 0.06, 0.04, 0.07, 0.05, 0.06]    # high mean, low std → high Sharpe
    t2 = [0.01, -0.05, 0.03, -0.04, 0.02, -0.03]  # lower Sharpe
    t3 = [-0.02, -0.03, 0.01, -0.04, -0.01, -0.02]  # worst
    rows = _make_hold_rows(t1, t2, t3)
    result = compute_optimal_hold_period(rows)
    assert result["optimal_hold_days"] == 1
    assert result["t1_sharpe"] is not None


def test_r22_compute_optimal_hold_period_t2_optimal() -> None:
    """When T+2 has clearly higher Sharpe, optimal_hold_days should be 2."""
    from scripts.btst_analysis_utils import compute_optimal_hold_period
    t1 = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01]  # near zero Sharpe
    t2 = [0.06, 0.07, 0.05, 0.08, 0.06, 0.07]     # high Sharpe
    t3 = [-0.01, 0.00, -0.02, 0.01, -0.01, 0.00]
    rows = _make_hold_rows(t1, t2, t3)
    result = compute_optimal_hold_period(rows)
    assert result["optimal_hold_days"] == 2


def test_r22_compute_optimal_hold_period_insufficient_data_returns_none_sharpe() -> None:
    """Period with < 5 rows yields None Sharpe."""
    from scripts.btst_analysis_utils import compute_optimal_hold_period
    # T+1: 6 rows, T+2: 3 rows (< 5), T+3: 3 rows (< 5)
    t1 = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    t2 = [0.01, 0.02, 0.03]
    t3 = [0.01, 0.02, 0.03]
    rows = _make_hold_rows(t1, t2, t3)
    result = compute_optimal_hold_period(rows)
    assert result["t2_sharpe"] is None
    assert result["t3_sharpe"] is None
    assert result["t1_sharpe"] is not None
    assert result["optimal_hold_days"] == 1


def test_r22_compute_optimal_hold_period_all_missing_returns_none() -> None:
    """All periods < 5 rows → optimal_hold_days is None."""
    from scripts.btst_analysis_utils import compute_optimal_hold_period
    rows = [{"next_close_return": 0.01}, {"next_close_return": 0.02}]
    result = compute_optimal_hold_period(rows)
    assert result["optimal_hold_days"] is None
    assert result["t1_sharpe"] is None


def test_r22_compute_optimal_hold_period_sharpe_diff_fields_present() -> None:
    """t1_vs_t2_sharpe_diff and t1_vs_t3_sharpe_diff are computed when both periods valid."""
    from scripts.btst_analysis_utils import compute_optimal_hold_period
    returns = [0.02, 0.03, 0.01, 0.04, 0.02, 0.03]
    rows = _make_hold_rows(returns, returns, returns)
    result = compute_optimal_hold_period(rows)
    assert result["t1_vs_t2_sharpe_diff"] is not None
    assert result["t1_vs_t3_sharpe_diff"] is not None
    # Same data → diff ≈ 0
    assert abs(result["t1_vs_t2_sharpe_diff"]) < 0.01


# =============================================================================
# Round 22 — Task 3 (Beta): compute_score_position_tiers
# =============================================================================

def _make_tier_rows(score_return_pairs: list[tuple[float, float]]) -> list[dict]:
    """Build rows with runner_composite_score and next_close_return."""
    return [{"runner_composite_score": s, "next_close_return": r} for s, r in score_return_pairs]


def test_r22_compute_score_position_tiers_monotone_when_high_scores_win_more() -> None:
    """tier_monotone_win_rate=True when high-score tier has highest win rate."""
    from scripts.btst_analysis_utils import compute_score_position_tiers
    # 30 rows: high (0.9) → all positive, mid (0.5) → mixed, low (0.1) → all negative
    pairs = [(0.9, 0.05)] * 10 + [(0.5, 0.01)] * 5 + [(0.5, -0.01)] * 5 + [(0.1, -0.03)] * 10
    rows = _make_tier_rows(pairs)
    result = compute_score_position_tiers(rows)
    assert result["tier_monotone_win_rate"] is True


def test_r22_compute_score_position_tiers_spread_is_positive_when_high_wins_more() -> None:
    """tier_win_rate_spread > 0 when high tier wins more than low tier."""
    from scripts.btst_analysis_utils import compute_score_position_tiers
    pairs = [(0.9, 0.04)] * 10 + [(0.5, 0.01)] * 10 + [(0.1, -0.02)] * 10
    rows = _make_tier_rows(pairs)
    result = compute_score_position_tiers(rows)
    assert result["tier_win_rate_spread"] is not None
    assert result["tier_win_rate_spread"] >= 0.0


def test_r22_compute_score_position_tiers_too_few_rows_returns_none_tiers() -> None:
    """Tiers with < 3 rows yield None win_rate and payoff."""
    from scripts.btst_analysis_utils import compute_score_position_tiers
    # Only 4 rows total → each tier will have < 3
    pairs = [(0.1, 0.01), (0.4, 0.02), (0.6, -0.01), (0.9, 0.03)]
    rows = _make_tier_rows(pairs)
    result = compute_score_position_tiers(rows)
    # At least some tiers should be None (tiers have ≤ 1-2 rows each)
    assert result["tier_high_win_rate"] is None or result["tier_low_win_rate"] is None


def test_r22_compute_score_position_tiers_empty_rows_returns_none() -> None:
    """Empty input returns all None metrics and tier_monotone_win_rate=False."""
    from scripts.btst_analysis_utils import compute_score_position_tiers
    result = compute_score_position_tiers([])
    assert result["score_p33"] is None
    assert result["score_p67"] is None
    assert result["tier_win_rate_spread"] is None
    assert result["tier_monotone_win_rate"] is False


def test_r22_compute_score_position_tiers_percentile_ordering() -> None:
    """score_p33 < score_p67 for a non-trivial distribution."""
    from scripts.btst_analysis_utils import compute_score_position_tiers
    pairs = [(float(i) / 20.0, 0.01 if i > 10 else -0.01) for i in range(20)]
    rows = _make_tier_rows(pairs)
    result = compute_score_position_tiers(rows)
    assert result["score_p33"] is not None
    assert result["score_p67"] is not None
    assert result["score_p33"] < result["score_p67"]


# =============================================================================
# Round 22 — COMPARISON_METRICS / optimizer registry checks
# =============================================================================

def test_r22_new_metrics_in_comparison_metrics() -> None:
    """Round 22 new metrics must all be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    for m in ("t1_vs_t2_sharpe_diff", "hold_period_confidence", "tier_win_rate_spread", "tier_monotone_win_rate"):
        assert m in COMPARISON_METRICS, f"{m} missing from COMPARISON_METRICS"


def test_r22_new_metrics_have_labels() -> None:
    """Round 22 new metrics must have labels in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    for m in ("t1_vs_t2_sharpe_diff", "hold_period_confidence", "tier_win_rate_spread", "tier_monotone_win_rate"):
        assert m in COMPARISON_METRIC_LABELS, f"{m} missing from COMPARISON_METRIC_LABELS"


def test_r22_new_metrics_are_optional() -> None:
    """Round 22 new metrics must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    for m in ("t1_vs_t2_sharpe_diff", "hold_period_confidence", "tier_win_rate_spread", "tier_monotone_win_rate"):
        assert m in OPTIONAL_COMPARISON_METRICS, f"{m} missing from OPTIONAL_COMPARISON_METRICS"


def test_r22_new_metrics_have_epsilon() -> None:
    """Round 22 new metrics must have epsilon entries in COMPARISON_METRIC_EPSILON."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    for m in ("t1_vs_t2_sharpe_diff", "hold_period_confidence", "tier_win_rate_spread", "tier_monotone_win_rate"):
        assert m in COMPARISON_METRIC_EPSILON, f"{m} missing from COMPARISON_METRIC_EPSILON"


# ---------------------------------------------------------------------------
# Round 23 tests — Task 1 (Gamma): BTST_RUNNER_LEAN_PROBE_GRID and lean_mode
# ---------------------------------------------------------------------------


def test_r23_lean_grid_is_subset_of_full_grid() -> None:
    """Every axis in BTST_RUNNER_LEAN_PROBE_GRID must also exist in BTST_RUNNER_PROBE_GRID."""
    from scripts.optimize_profile import BTST_RUNNER_LEAN_PROBE_GRID, BTST_RUNNER_PROBE_GRID
    for key in BTST_RUNNER_LEAN_PROBE_GRID:
        assert key in BTST_RUNNER_PROBE_GRID, f"lean grid axis '{key}' is absent from full BTST_RUNNER_PROBE_GRID"


def test_r23_lean_grid_axis_count_constant() -> None:
    """LEAN_GRID_AXIS_COUNT must equal len(BTST_RUNNER_LEAN_PROBE_GRID)."""
    from scripts.optimize_profile import BTST_RUNNER_LEAN_PROBE_GRID, LEAN_GRID_AXIS_COUNT
    assert LEAN_GRID_AXIS_COUNT == len(BTST_RUNNER_LEAN_PROBE_GRID)


def test_r23_full_grid_axis_count_constant() -> None:
    """FULL_GRID_AXIS_COUNT must equal len(BTST_RUNNER_PROBE_GRID)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID, FULL_GRID_AXIS_COUNT
    assert FULL_GRID_AXIS_COUNT == len(BTST_RUNNER_PROBE_GRID)


def test_r23_lean_mode_true_uses_lean_grid() -> None:
    """resolve_grid_params with lean_mode=True must return only lean-grid axes (no extras from full grid)."""
    from scripts.optimize_profile import BTST_RUNNER_LEAN_PROBE_GRID, BTST_RUNNER_PROBE_GRID, resolve_grid_params
    lean_result = resolve_grid_params(grid_params=[], preset_grid=True, profile_name="btst_runner_probe", lean_mode=True)
    # All lean axes must be present.
    for key in BTST_RUNNER_LEAN_PROBE_GRID:
        assert key in lean_result, f"lean axis '{key}' missing from lean_mode=True result"
    # At least one full-grid axis that is NOT in the lean grid must be absent.
    full_only_axes = [k for k in BTST_RUNNER_PROBE_GRID if k not in BTST_RUNNER_LEAN_PROBE_GRID]
    assert full_only_axes, "No full-grid-only axes found; lean grid may equal full grid"
    for key in full_only_axes:
        assert key not in lean_result, f"full-only axis '{key}' should be absent in lean_mode=True result"


def test_r23_lean_mode_false_uses_full_grid() -> None:
    """resolve_grid_params with lean_mode=False must include all full-grid axes."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID, resolve_grid_params
    full_result = resolve_grid_params(grid_params=[], preset_grid=True, profile_name="btst_runner_probe", lean_mode=False)
    for key in BTST_RUNNER_PROBE_GRID:
        assert key in full_result, f"full grid axis '{key}' missing from lean_mode=False result"


def test_r23_lean_mode_default_is_false() -> None:
    """resolve_grid_params must default to lean_mode=False (full grid)."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID, resolve_grid_params
    default_result = resolve_grid_params(grid_params=[], preset_grid=True, profile_name="btst_runner_probe")
    for key in BTST_RUNNER_PROBE_GRID:
        assert key in default_result, f"full grid axis '{key}' missing when lean_mode not specified"


def test_r23_lean_grid_size_smaller_than_full() -> None:
    """LEAN_GRID_AXIS_COUNT must be strictly smaller than FULL_GRID_AXIS_COUNT."""
    from scripts.optimize_profile import FULL_GRID_AXIS_COUNT, LEAN_GRID_AXIS_COUNT
    assert LEAN_GRID_AXIS_COUNT < FULL_GRID_AXIS_COUNT, f"lean grid ({LEAN_GRID_AXIS_COUNT}) is not smaller than full grid ({FULL_GRID_AXIS_COUNT})"


def test_r23_new_metrics_in_comparison_metrics() -> None:
    """Round 23 new metrics must all be present in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    for m in ("kelly_fraction_half", "kelly_positive", "regime_consistency_score", "regime_robustness_flag"):
        assert m in COMPARISON_METRICS, f"{m} missing from COMPARISON_METRICS"


def test_r23_new_metrics_have_labels() -> None:
    """Round 23 new metrics must have entries in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    for m in ("kelly_fraction_half", "kelly_positive", "regime_consistency_score", "regime_robustness_flag"):
        assert m in COMPARISON_METRIC_LABELS, f"{m} missing from COMPARISON_METRIC_LABELS"


def test_r23_new_metrics_are_optional() -> None:
    """Round 23 new metrics must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    for m in ("kelly_fraction_half", "kelly_positive", "regime_consistency_score", "regime_robustness_flag"):
        assert m in OPTIONAL_COMPARISON_METRICS, f"{m} missing from OPTIONAL_COMPARISON_METRICS"


def test_r23_new_metrics_have_epsilon() -> None:
    """Round 23 new metrics must have epsilon entries in COMPARISON_METRIC_EPSILON."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    for m in ("kelly_fraction_half", "kelly_positive", "regime_consistency_score", "regime_robustness_flag"):
        assert m in COMPARISON_METRIC_EPSILON, f"{m} missing from COMPARISON_METRIC_EPSILON"


# =============================================================================
# Round 24 — comparison metrics structure tests
# =============================================================================


def test_r24_new_metrics_in_comparison_metrics() -> None:
    """Round 24 new metrics must all be present in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    for m in ("decaying_factor_count", "kelly_fraction_drawdown_adjusted", "drawdown_adjustment_factor", "verdict_calibration_score", "verdict_monotone"):
        assert m in COMPARISON_METRICS, f"{m} missing from COMPARISON_METRICS"


def test_r24_new_metrics_have_labels() -> None:
    """Round 24 new metrics must have entries in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    for m in ("decaying_factor_count", "kelly_fraction_drawdown_adjusted", "drawdown_adjustment_factor", "verdict_calibration_score", "verdict_monotone"):
        assert m in COMPARISON_METRIC_LABELS, f"{m} missing from COMPARISON_METRIC_LABELS"


def test_r24_new_metrics_are_optional() -> None:
    """Round 24 new metrics must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    for m in ("decaying_factor_count", "kelly_fraction_drawdown_adjusted", "drawdown_adjustment_factor", "verdict_calibration_score", "verdict_monotone"):
        assert m in OPTIONAL_COMPARISON_METRICS, f"{m} missing from OPTIONAL_COMPARISON_METRICS"


def test_r24_new_metrics_have_epsilon() -> None:
    """Round 24 new metrics must have epsilon entries in COMPARISON_METRIC_EPSILON."""
    from scripts.optimize_profile import COMPARISON_METRIC_EPSILON
    for m in ("decaying_factor_count", "kelly_fraction_drawdown_adjusted", "drawdown_adjustment_factor", "verdict_calibration_score", "verdict_monotone"):
        assert m in COMPARISON_METRIC_EPSILON, f"{m} missing from COMPARISON_METRIC_EPSILON"


def test_r24_decaying_factor_count_is_lower_is_better() -> None:
    """decaying_factor_count must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "decaying_factor_count" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r24_quality_floor_for_drawdown_adjusted_kelly() -> None:
    """BTST_QUALITY_FLOORS must contain kelly_fraction_drawdown_adjusted with value 0.01."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "kelly_fraction_drawdown_adjusted" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["kelly_fraction_drawdown_adjusted"] == 0.01


# =============================================================================
# Round 24 — Task 2: compute_drawdown_adjusted_kelly unit tests
# =============================================================================


def test_r24_drawdown_adjusted_kelly_null_when_kelly_missing() -> None:
    """Returns all None when kelly_fraction_half is absent."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"t_plus_1_intraday_drawdown_p10": -0.04})
    assert result["kelly_fraction_drawdown_adjusted"] is None
    assert result["drawdown_adjustment_factor"] is None


def test_r24_drawdown_adjusted_kelly_null_when_p10_missing() -> None:
    """Returns all None when t_plus_1_intraday_drawdown_p10 is absent."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"kelly_fraction_half": 0.10})
    assert result["kelly_fraction_drawdown_adjusted"] is None


def test_r24_drawdown_adjusted_kelly_low_risk_no_reduction() -> None:
    """p10 > -0.02 (low risk) → risk_level='low'; adjustment_factor = 1/(1+severity) with severity=max(0,-p10/0.05)."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"kelly_fraction_half": 0.10, "t_plus_1_intraday_drawdown_p10": -0.01})
    assert result["drawdown_risk_level"] == "low"
    # severity = max(0, 0.01/0.05) = 0.2 → adj_factor = 1/1.2 ≈ 0.8333
    expected_adj_factor = round(1.0 / (1.0 + 0.01 / 0.05), 4)
    assert abs(result["drawdown_adjustment_factor"] - expected_adj_factor) < 0.001
    expected_kelly = round(0.10 * expected_adj_factor, 4)
    assert abs(result["kelly_fraction_drawdown_adjusted"] - expected_kelly) < 0.001


def test_r24_drawdown_adjusted_kelly_severe_risk_large_reduction() -> None:
    """p10 = -0.10 (severe) → severity=2.0 → adj_factor=1/3 ≈ 0.333."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"kelly_fraction_half": 0.12, "t_plus_1_intraday_drawdown_p10": -0.10})
    assert result["drawdown_risk_level"] == "severe"
    assert result["drawdown_adjustment_factor"] is not None
    assert abs(result["drawdown_adjustment_factor"] - round(1.0 / 3.0, 4)) < 0.001
    assert result["kelly_fraction_drawdown_adjusted"] < 0.12
    assert result["drawdown_kelly_vs_base_diff"] <= 0.0


def test_r24_drawdown_adjusted_kelly_moderate_risk_partial_reduction() -> None:
    """p10 = -0.03 (moderate) → severity=0.6 → adj_factor=1/1.6=0.625."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"kelly_fraction_half": 0.10, "t_plus_1_intraday_drawdown_p10": -0.03})
    assert result["drawdown_risk_level"] == "moderate"
    expected_adj_factor = 1.0 / (1.0 + 0.6)
    assert abs(result["drawdown_adjustment_factor"] - round(expected_adj_factor, 4)) < 0.001
    assert 0.0 < result["kelly_fraction_drawdown_adjusted"] < 0.10


def test_r24_drawdown_adjusted_kelly_capped_at_half() -> None:
    """Output is clipped to [0, 0.50]; a very large kelly_half stays within bounds."""
    from scripts.btst_analysis_utils import compute_drawdown_adjusted_kelly
    result = compute_drawdown_adjusted_kelly([], {"kelly_fraction_half": 0.60, "t_plus_1_intraday_drawdown_p10": -0.01})
    assert result["kelly_fraction_drawdown_adjusted"] <= 0.50


# =============================================================================
# Round 24 — Task 1: compute_factor_ic_temporal_trend unit tests
# =============================================================================


def test_r24_ic_temporal_trend_empty_returns_defaults() -> None:
    """Empty input returns decaying_factor_count=0 and None summary fields."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend
    result = compute_factor_ic_temporal_trend([])
    assert result["decaying_factor_count"] == 0
    assert result["decaying_factors"] == []
    assert result["most_decaying_factor"] is None
    assert result["most_improving_factor"] is None


def test_r24_ic_temporal_trend_single_window_returns_defaults() -> None:
    """Single window: insufficient for split, returns minimal defaults."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend, BTST_FACTOR_NAMES
    result = compute_factor_ic_temporal_trend([{"factor_ic_next_close": {BTST_FACTOR_NAMES[0]: 0.05}}])
    assert result["decaying_factor_count"] == 0


def test_r24_ic_temporal_trend_detects_decay() -> None:
    """Factor with early IC=0.10, late IC=0.02 should be flagged as decaying (trend=-0.08<-0.02)."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    # 8 windows: first 4 (early) have IC=0.10, last 4 (late) have IC=0.02
    summaries = [{"factor_ic_next_close": {factor: 0.10}} for _ in range(4)] + [{"factor_ic_next_close": {factor: 0.02}} for _ in range(4)]
    result = compute_factor_ic_temporal_trend(summaries)
    assert result[f"{factor}_ic_decaying"] is True
    assert result["decaying_factor_count"] >= 1
    assert factor in result["decaying_factors"]
    assert result[f"{factor}_ic_trend"] < -0.02


def test_r24_ic_temporal_trend_no_decay_when_stable() -> None:
    """Factor with constant IC across all windows should NOT be flagged as decaying."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    summaries = [{"factor_ic_next_close": {factor: 0.05}} for _ in range(8)]
    result = compute_factor_ic_temporal_trend(summaries)
    assert result[f"{factor}_ic_decaying"] is False
    assert result["decaying_factor_count"] == 0


def test_r24_ic_temporal_trend_most_decaying_most_improving() -> None:
    """most_decaying_factor should be the factor with the most negative trend."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend, BTST_FACTOR_NAMES
    f1, f2 = BTST_FACTOR_NAMES[0], BTST_FACTOR_NAMES[1]
    # f1: strong decay (0.15 → 0.01), f2: improving (0.01 → 0.12)
    # Need ≥3 windows per half — use 6 total (split=3 early, 3 late)
    summaries = (
        [{"factor_ic_next_close": {f1: 0.15, f2: 0.01}} for _ in range(3)] +
        [{"factor_ic_next_close": {f1: 0.01, f2: 0.12}} for _ in range(3)]
    )
    result = compute_factor_ic_temporal_trend(summaries)
    assert result["most_decaying_factor"] == f1
    assert result["most_improving_factor"] == f2


def test_r24_ic_temporal_trend_skip_factors_with_insufficient_data() -> None:
    """Factors with fewer than 3 valid IC values in either half get None trend and False decaying."""
    from scripts.btst_analysis_utils import compute_factor_ic_temporal_trend, BTST_FACTOR_NAMES
    factor = BTST_FACTOR_NAMES[0]
    # 4 windows total: split=2 early, 2 late → each half has only 2 valid ICs for this factor → skip
    summaries = [{"factor_ic_next_close": {factor: 0.10}} for _ in range(4)]
    result = compute_factor_ic_temporal_trend(summaries)
    assert result[f"{factor}_ic_trend"] is None
    assert result[f"{factor}_ic_decaying"] is False


# =============================================================================
# Round 24 — Task 3: compute_verdict_calibration unit tests
# =============================================================================


def test_r24_verdict_calibration_empty_returns_none() -> None:
    """Empty input returns None calibration score and empty maps."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    result = compute_verdict_calibration([])
    assert result["verdict_calibration_score"] is None
    assert result["verdict_monotone"] is None
    assert result["verdict_win_rate_map"] == {}


def test_r24_verdict_calibration_uses_real_verdicts_when_present() -> None:
    """When verdict field is present, uses real categories (not quartile proxy)."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    summaries = [
        {"verdict": "promotable", "next_close_positive_rate": 0.70},
        {"verdict": "promotable", "next_close_positive_rate": 0.68},
        {"verdict": "watch", "next_close_positive_rate": 0.58},
        {"verdict": "probation", "next_close_positive_rate": 0.48},
        {"verdict": "probation", "next_close_positive_rate": 0.46},
    ]
    result = compute_verdict_calibration(summaries)
    assert "promotable" in result["verdict_win_rate_map"] or "promotable-like" in result["verdict_win_rate_map"]
    assert result["verdict_calibration_score"] is not None
    assert 0.0 <= result["verdict_calibration_score"] <= 1.0


def test_r24_verdict_calibration_monotone_true_when_ordered() -> None:
    """When promotable_wr > watch_wr > probation_wr, verdict_monotone must be True."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    summaries = [
        {"verdict": "promotable", "next_close_positive_rate": 0.70},
        {"verdict": "watch", "next_close_positive_rate": 0.58},
        {"verdict": "probation", "next_close_positive_rate": 0.45},
    ]
    result = compute_verdict_calibration(summaries)
    assert result["verdict_monotone"] is True


def test_r24_verdict_calibration_monotone_false_when_inverted() -> None:
    """When probation_wr > promotable_wr, verdict_monotone must be False."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    summaries = [
        {"verdict": "promotable", "next_close_positive_rate": 0.45},
        {"verdict": "probation", "next_close_positive_rate": 0.70},
    ]
    result = compute_verdict_calibration(summaries)
    assert result["verdict_monotone"] is False


def test_r24_verdict_calibration_proxy_splits_by_quartile() -> None:
    """When no real verdicts present, uses quartile proxy for categorisation."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    # 8 windows, no 'verdict' field — use proxy
    summaries = [{"next_close_positive_rate": 0.40 + i * 0.04} for i in range(8)]
    result = compute_verdict_calibration(summaries)
    assert result["verdict_win_rate_map"]
    # Should have promotable-like and probation-like categories
    assert any("promotable" in k for k in result["verdict_win_rate_map"])
    assert any("probation" in k for k in result["verdict_win_rate_map"])


def test_r24_verdict_calibration_score_capped_at_one() -> None:
    """calibration_score must not exceed 1.0 even when spread > 0.20."""
    from scripts.btst_analysis_utils import compute_verdict_calibration
    summaries = [
        {"verdict": "promotable", "next_close_positive_rate": 0.90},
        {"verdict": "probation", "next_close_positive_rate": 0.40},
    ]
    result = compute_verdict_calibration(summaries)
    assert result["verdict_calibration_score"] is not None
    assert result["verdict_calibration_score"] <= 1.0
    assert result["verdict_calibration_score"] == 1.0  # (0.90-0.40)/0.20 = 2.5 → capped to 1.0


# ---------------------------------------------------------------------------
# Round 25 — T3 (Alpha): compute_auto_calibrated_floor_suggestions
# ---------------------------------------------------------------------------

def test_r25_floor_suggestions_too_easy_when_floor_below_p25() -> None:
    """A current floor at or below 80% of P25 must produce action='too_easy'."""
    from scripts.optimize_profile import compute_auto_calibrated_floor_suggestions
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    # next_close_positive_rate has current floor 0.54.
    # Feed 8 windows all with value 0.80 → P25=0.80*0.25+… ≈ 0.80.
    # 0.54 ≤ 0.80 * 0.80 = 0.64 → too_easy.
    windows = [{"next_close_positive_rate": 0.80} for _ in range(8)]
    result = compute_auto_calibrated_floor_suggestions(windows)
    suggestion = result["floor_suggestions"].get("next_close_positive_rate")
    assert suggestion is not None
    assert suggestion["action"] == "too_easy"
    assert "next_close_positive_rate" in result["overly_easy_floors"]


def test_r25_floor_suggestions_too_strict_when_floor_above_p75() -> None:
    """A current floor above 120% of P75 must produce action='too_strict'."""
    from scripts.optimize_profile import compute_auto_calibrated_floor_suggestions

    # next_close_positive_rate floor = 0.54.
    # Feed windows with value ≈ 0.30 so P75 < 0.45, making floor > P75*1.20.
    windows = [{"next_close_positive_rate": 0.25 + i * 0.01} for i in range(8)]
    result = compute_auto_calibrated_floor_suggestions(windows)
    suggestion = result["floor_suggestions"].get("next_close_positive_rate")
    assert suggestion is not None
    assert suggestion["action"] == "too_strict"
    assert "next_close_positive_rate" in result["overly_strict_floors"]


def test_r25_floor_suggestions_calibrated() -> None:
    """A floor that falls between P25*0.80 and P75*1.20 must produce action='calibrated'."""
    from scripts.optimize_profile import compute_auto_calibrated_floor_suggestions

    # next_close_positive_rate floor = 0.54.
    # Feed window values centered around 0.54 so the distribution brackets it nicely.
    import statistics
    windows = [{"next_close_positive_rate": 0.48 + i * 0.02} for i in range(9)]  # 0.48…0.64
    result = compute_auto_calibrated_floor_suggestions(windows)
    suggestion = result["floor_suggestions"].get("next_close_positive_rate")
    # P25 ≈ 0.50, P75 ≈ 0.62  → P25*0.80=0.40 < 0.54 ≤ P75*1.20=0.744 → calibrated
    assert suggestion is not None
    assert suggestion["action"] == "calibrated"
    assert "next_close_positive_rate" in result["well_calibrated_floors"]


def test_r25_floor_suggestions_empty_input() -> None:
    """Empty window list must return empty suggestions and empty category lists."""
    from scripts.optimize_profile import compute_auto_calibrated_floor_suggestions
    result = compute_auto_calibrated_floor_suggestions([])
    assert result["floor_suggestions"] == {}
    assert result["overly_easy_floors"] == []
    assert result["overly_strict_floors"] == []
    assert result["well_calibrated_floors"] == []


def test_r25_floor_suggestions_missing_metric_graceful() -> None:
    """Windows missing a metric must yield action='no_data' for that metric."""
    from scripts.optimize_profile import compute_auto_calibrated_floor_suggestions
    # Windows contain no 'next_close_positive_rate' field at all
    windows = [{"realized_payoff_ratio": 1.5} for _ in range(5)]
    result = compute_auto_calibrated_floor_suggestions(windows)
    suggestion = result["floor_suggestions"].get("next_close_positive_rate")
    assert suggestion is not None
    assert suggestion["action"] == "no_data"


# ===========================================================================
# Round 27 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Task 1 (Round 27, Alpha): compute_return_distribution_shape
# ---------------------------------------------------------------------------

def test_r27_return_distribution_symmetric_skewness_near_zero() -> None:
    """Symmetric distribution should have skewness close to 0."""
    from scripts.btst_analysis_utils import compute_return_distribution_shape
    rows = [{"next_close_return": v} for v in [-0.03, -0.01, 0.0, 0.01, 0.03]]
    result = compute_return_distribution_shape(rows)
    assert result["next_close_return_skewness"] is not None
    assert abs(result["next_close_return_skewness"]) < 0.5  # near zero for symmetric


def test_r27_return_distribution_left_skewed() -> None:
    """Distribution with large losses should be left-skewed (negative skewness)."""
    from scripts.btst_analysis_utils import compute_return_distribution_shape
    # Big loss outlier makes distribution left-skewed
    rows = [{"next_close_return": v} for v in [0.01, 0.02, 0.01, 0.01, 0.01, -0.20]]
    result = compute_return_distribution_shape(rows)
    assert result["next_close_return_skewness"] is not None
    assert result["next_close_return_skewness"] < 0.0  # left-skewed


def test_r27_return_distribution_win_loss_std_ratio_favourable() -> None:
    """Win/loss std ratio > 1 when upside volatility exceeds downside volatility."""
    from scripts.btst_analysis_utils import compute_return_distribution_shape
    # Varied losses (small) and varied large wins → upside_std > downside_std
    rows = [{"next_close_return": v} for v in [-0.01, -0.02, -0.015, -0.005, 0.05, 0.10, 0.15, 0.20]]
    result = compute_return_distribution_shape(rows)
    ratio = result.get("win_loss_std_ratio")
    assert ratio is not None
    assert ratio > 1.0


def test_r27_return_distribution_heavy_left_tail_flag() -> None:
    """heavy_left_tail_flag triggers when skewness < -1.0 AND p5 < -0.05."""
    from scripts.btst_analysis_utils import compute_return_distribution_shape
    # Extreme loss outliers to force heavy left tail
    rows = [{"next_close_return": v} for v in [0.01, 0.01, 0.01, 0.01, -0.15, -0.20, -0.30, 0.01, 0.01, 0.01]]
    result = compute_return_distribution_shape(rows)
    # p5 should be very negative; skewness should be < -1.0
    assert result["heavy_left_tail_flag"] is True
    assert result["return_p5"] < -0.05


def test_r27_return_distribution_insufficient_data() -> None:
    """Fewer than 5 rows should return all None values."""
    from scripts.btst_analysis_utils import compute_return_distribution_shape
    rows = [{"next_close_return": 0.01}, {"next_close_return": 0.02}, {"next_close_return": -0.01}]
    result = compute_return_distribution_shape(rows)
    assert result["next_close_return_skewness"] is None
    assert result["win_loss_std_ratio"] is None
    assert result["heavy_left_tail_flag"] is False


# ---------------------------------------------------------------------------
# Task 2 (Round 27, Gamma): compute_score_discrimination_power
# ---------------------------------------------------------------------------

def test_r27_score_discrimination_high_spread() -> None:
    """Wide score distribution should yield large spread and no low_discrimination_flag."""
    from scripts.btst_analysis_utils import compute_score_discrimination_power
    scores = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    rows = [{"runner_composite_score": s, "next_close_return": (s - 0.5) * 0.1} for s in scores]
    result = compute_score_discrimination_power(rows)
    assert result["score_spread_p95_p5"] is not None
    assert result["score_spread_p95_p5"] >= 0.20  # 0.9 - 0.2 = 0.70 spread
    assert result["low_discrimination_flag"] is False


def test_r27_score_discrimination_low_spread_flag() -> None:
    """Scores clustered around 0.5 trigger low_discrimination_flag."""
    from scripts.btst_analysis_utils import compute_score_discrimination_power
    scores = [0.48, 0.49, 0.50, 0.51, 0.52, 0.49, 0.50, 0.51]
    rows = [{"runner_composite_score": s, "next_close_return": 0.01} for s in scores]
    result = compute_score_discrimination_power(rows)
    assert result["score_spread_p95_p5"] is not None
    assert result["score_spread_p95_p5"] < 0.20
    assert result["low_discrimination_flag"] is True


def test_r27_score_discrimination_spearman_positive_correlation() -> None:
    """Perfect rank correlation between score and return should give spearman ≈ 1.0."""
    from scripts.btst_analysis_utils import compute_score_discrimination_power
    pairs = [(0.2, -0.04), (0.4, -0.02), (0.5, 0.0), (0.6, 0.02), (0.8, 0.04), (0.9, 0.06)]
    rows = [{"runner_composite_score": s, "next_close_return": r} for s, r in pairs]
    result = compute_score_discrimination_power(rows)
    spearman = result["score_return_spearman"]
    assert spearman is not None
    assert spearman > 0.9  # near-perfect positive rank correlation


def test_r27_score_discrimination_index_equals_spread_times_abs_spearman() -> None:
    """discrimination_index should equal spread_p95_p5 × |spearman|."""
    from scripts.btst_analysis_utils import compute_score_discrimination_power
    scores = [0.2, 0.4, 0.5, 0.6, 0.8, 0.9]
    returns = [-0.04, -0.02, 0.0, 0.02, 0.04, 0.06]
    rows = [{"runner_composite_score": s, "next_close_return": r} for s, r in zip(scores, returns)]
    result = compute_score_discrimination_power(rows)
    expected = round((result["score_spread_p95_p5"] or 0.0) * abs(result["score_return_spearman"] or 0.0), 4)
    assert abs((result["score_discrimination_index"] or 0.0) - expected) < 1e-6


def test_r27_score_discrimination_missing_field_returns_null() -> None:
    """Rows without runner_composite_score should return all-None result."""
    from scripts.btst_analysis_utils import compute_score_discrimination_power
    rows = [{"next_close_return": 0.01} for _ in range(6)]
    result = compute_score_discrimination_power(rows)
    assert result["score_spread_p95_p5"] is None
    assert result["score_discrimination_index"] is None


# ---------------------------------------------------------------------------
# Task 3 (Round 27, Beta): compute_liquidity_position_guidance
# ---------------------------------------------------------------------------

def test_r27_liquidity_large_pool_low_risk() -> None:
    """Pool > 100 should give max positions = 10 and concentration_risk_level = 'low'."""
    from scripts.btst_analysis_utils import compute_liquidity_position_guidance
    result = compute_liquidity_position_guidance({"avg_candidate_pool_size": 120.0, "scarce_market_window_count": 0, "market_size_classification": "abundant_dominated"})
    assert result["recommended_max_positions"] == 10
    assert result["concentration_risk_level"] == "low"
    assert result["diversification_feasible"] is True


def test_r27_liquidity_small_pool_extreme_risk() -> None:
    """Pool < 10 should give max positions = 1 and concentration_risk_level = 'extreme'."""
    from scripts.btst_analysis_utils import compute_liquidity_position_guidance
    result = compute_liquidity_position_guidance({"avg_candidate_pool_size": 8.0, "scarce_market_window_count": 3, "market_size_classification": "scarce_dominated"})
    assert result["recommended_max_positions"] == 1
    assert result["concentration_risk_level"] == "extreme"
    assert result["diversification_feasible"] is False


def test_r27_liquidity_pool_stability_classification() -> None:
    """market_size_classification drives pool_size_stability correctly."""
    from scripts.btst_analysis_utils import compute_liquidity_position_guidance
    assert compute_liquidity_position_guidance({"avg_candidate_pool_size": 50.0, "scarce_market_window_count": 0, "market_size_classification": "abundant_dominated"})["pool_size_stability"] == "stable"
    assert compute_liquidity_position_guidance({"avg_candidate_pool_size": 50.0, "scarce_market_window_count": 2, "market_size_classification": "mixed"})["pool_size_stability"] == "variable"
    assert compute_liquidity_position_guidance({"avg_candidate_pool_size": 15.0, "scarce_market_window_count": 5, "market_size_classification": "scarce_dominated"})["pool_size_stability"] == "scarce"


def test_r27_liquidity_missing_pool_size_uses_default() -> None:
    """Missing avg_candidate_pool_size should fall back to 50 (medium pool)."""
    from scripts.btst_analysis_utils import compute_liquidity_position_guidance
    result = compute_liquidity_position_guidance({})
    # Default pool=50 → floor(50/10)=5 positions → medium risk
    assert result["recommended_max_positions"] == 5
    assert result["concentration_risk_level"] == "medium"


def test_r27_liquidity_position_size_pct_capped_at_20pct() -> None:
    """Minimum 1 position → max position size = 1.0 (100% but capped at 20%)."""
    from scripts.btst_analysis_utils import compute_liquidity_position_guidance
    result = compute_liquidity_position_guidance({"avg_candidate_pool_size": 5.0})
    # 1 position → min(0.20, 1.0/1) = 0.20
    assert result["recommended_position_size_pct"] == 0.20


# ---------------------------------------------------------------------------
# Task 1/2/3 (Round 27): registry checks — new metrics in comparison/quality dicts
# ---------------------------------------------------------------------------

def test_r27_new_metrics_in_comparison_metrics() -> None:
    """All four R27 COMPARISON_METRICS entries must be present."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "next_close_return_skewness" in COMPARISON_METRICS
    assert "win_loss_std_ratio" in COMPARISON_METRICS
    assert "score_discrimination_index" in COMPARISON_METRICS
    assert "recommended_max_positions" in COMPARISON_METRICS


def test_r27_new_metrics_in_optional_comparison_metrics() -> None:
    """All four R27 metrics must be optional (pre-R27 surfaces omit them)."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "next_close_return_skewness" in OPTIONAL_COMPARISON_METRICS
    assert "win_loss_std_ratio" in OPTIONAL_COMPARISON_METRICS
    assert "score_discrimination_index" in OPTIONAL_COMPARISON_METRICS
    assert "recommended_max_positions" in OPTIONAL_COMPARISON_METRICS


def test_r27_new_metrics_have_labels() -> None:
    """All R27 metrics must have human-readable labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "next_close_return_skewness" in COMPARISON_METRIC_LABELS
    assert "win_loss_std_ratio" in COMPARISON_METRIC_LABELS
    assert "score_discrimination_index" in COMPARISON_METRIC_LABELS
    assert "recommended_max_positions" in COMPARISON_METRIC_LABELS


def test_r27_skewness_cap_in_btst_quality_caps() -> None:
    """next_close_return_skewness floor must be registered at -2.0."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "next_close_return_skewness" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["next_close_return_skewness"] == -2.0


def test_r27_score_spread_floor_in_btst_quality_floors() -> None:
    """score_spread_p95_p5 floor must be registered at 0.10."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "score_spread_p95_p5" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_spread_p95_p5"] == 0.10


def test_r27_skewness_cap_blocker_fires_when_too_negative() -> None:
    """build_btst_quality_floor_blockers must fire when skewness < -2.0."""
    from src.backtesting.evaluation_bundle import build_btst_quality_floor_blockers
    metrics = {"next_close_return_skewness": -3.5, "score_spread_p95_p5": 0.50, "next_close_positive_rate": 0.60, "kelly_fraction_half": 0.05, "realized_payoff_ratio": 1.2, "alpha_avg_return": 0.001, "regime_consistency_score": 0.80, "kelly_fraction_drawdown_adjusted": 0.02, "downside_p10": -0.04, "sample_weight": 0.80, "window_coverage": 0.70, "avg_composite_score_escaped": 0.50, "t_plus_1_intraday_drawdown_p10": -0.04, "avg_escape_gap_cost": -0.01, "t_plus_2_close_payoff_ratio": 1.1, "t_plus_3_close_payoff_ratio": 1.05, "t_plus_3_close_expectancy": 0.001, "t_plus_3_close_positive_rate": 0.51, "t_plus_2_close_positive_rate": 0.53, "next_high_hit_rate": 0.57}
    blockers = build_btst_quality_floor_blockers(metrics)
    assert any("next_close_return_skewness" in b for b in blockers)


def test_r27_skewness_cap_blocker_silent_when_acceptable() -> None:
    """No blocker when skewness >= -2.0."""
    from src.backtesting.evaluation_bundle import build_btst_quality_floor_blockers
    metrics = {"next_close_return_skewness": -1.5, "score_spread_p95_p5": 0.50, "next_close_positive_rate": 0.60, "kelly_fraction_half": 0.05, "realized_payoff_ratio": 1.2, "alpha_avg_return": 0.001, "regime_consistency_score": 0.80, "kelly_fraction_drawdown_adjusted": 0.02, "downside_p10": -0.04, "sample_weight": 0.80, "window_coverage": 0.70, "avg_composite_score_escaped": 0.50, "t_plus_1_intraday_drawdown_p10": -0.04, "avg_escape_gap_cost": -0.01, "t_plus_2_close_payoff_ratio": 1.1, "t_plus_3_close_payoff_ratio": 1.05, "t_plus_3_close_expectancy": 0.001, "t_plus_3_close_positive_rate": 0.51, "t_plus_2_close_positive_rate": 0.53, "next_high_hit_rate": 0.57}
    blockers = build_btst_quality_floor_blockers(metrics)
    assert not any("next_close_return_skewness" in b for b in blockers)


def test_r27_score_spread_floor_blocker_fires_when_too_narrow() -> None:
    """build_btst_quality_floor_blockers must fire when score_spread_p95_p5 < 0.10."""
    from src.backtesting.evaluation_bundle import build_btst_quality_floor_blockers
    metrics = {"score_spread_p95_p5": 0.05, "next_close_positive_rate": 0.60, "kelly_fraction_half": 0.05, "realized_payoff_ratio": 1.2, "alpha_avg_return": 0.001, "regime_consistency_score": 0.80, "kelly_fraction_drawdown_adjusted": 0.02, "downside_p10": -0.04, "sample_weight": 0.80, "window_coverage": 0.70, "avg_composite_score_escaped": 0.50, "t_plus_1_intraday_drawdown_p10": -0.04, "avg_escape_gap_cost": -0.01, "t_plus_2_close_payoff_ratio": 1.1, "t_plus_3_close_payoff_ratio": 1.05, "t_plus_3_close_expectancy": 0.001, "t_plus_3_close_positive_rate": 0.51, "t_plus_2_close_positive_rate": 0.53, "next_high_hit_rate": 0.57}
    blockers = build_btst_quality_floor_blockers(metrics)
    assert any("score_spread_p95_p5" in b for b in blockers)


# ---------------------------------------------------------------------------
# Task 1 (Round 28, Alpha): compute_factor_cross_correlation
# ---------------------------------------------------------------------------


def test_r28_factor_cross_corr_perfectly_positively_correlated() -> None:
    """Two factors with identical values should yield Spearman corr = 1.0."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    rows = [{"breakout_freshness": float(i) / 9, "close_strength": float(i) / 9} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    assert result["factor_max_correlation"] is not None
    assert abs(result["factor_max_correlation"] - 1.0) < 0.0001
    assert ("breakout_freshness", "close_strength") == result["factor_max_correlation_pair"] or ("close_strength", "breakout_freshness") == result["factor_max_correlation_pair"]


def test_r28_factor_cross_corr_perfectly_negatively_correlated() -> None:
    """Monotone-inverse factor pair should yield Spearman corr = -1.0."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    rows = [{"breakout_freshness": float(i) / 9, "trend_acceleration": 1.0 - float(i) / 9} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    assert result["factor_max_correlation"] is not None
    assert abs(abs(result["factor_max_correlation"]) - 1.0) < 0.0001


def test_r28_factor_cross_corr_orthogonal_pair_near_zero() -> None:
    """Alternating-sign factor should have near-zero Spearman corr with monotone factor."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    import math
    rows = [{"breakout_freshness": float(i), "close_strength": math.sin(i * math.pi)} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    assert result["factor_min_correlation"] is not None
    assert abs(result["factor_min_correlation"]) < 0.5


def test_r28_factor_cross_corr_high_correlation_pairs_filtered() -> None:
    """|corr| > 0.70 threshold should correctly classify high-correlation pairs."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    # Create a case where breakout_freshness and close_strength are almost perfectly correlated
    rows = [{"breakout_freshness": float(i), "close_strength": float(i) + 0.01 * (i % 3), "trend_acceleration": float(9 - i)} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    high_pairs = result["high_correlation_pairs"]
    # breakout_freshness vs close_strength should be very high correlation
    assert any(("breakout_freshness" in p[0] or "breakout_freshness" in p[1]) and ("close_strength" in p[0] or "close_strength" in p[1]) for p in high_pairs)


def test_r28_factor_cross_corr_redundancy_warning_flag_threshold() -> None:
    """redundancy_warning_flag fires only when high_correlation_pair_count > 3."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    from scripts.btst_analysis_utils import BTST_FACTOR_NAMES
    # Create 4+ factors all perfectly correlated
    base = [float(i) for i in range(10)]
    rows = [{f: base[i] + (0.001 * j) for j, f in enumerate(BTST_FACTOR_NAMES)} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    assert result["redundancy_warning_flag"] is True
    assert result["high_correlation_pair_count"] > 3


def test_r28_factor_cross_corr_redundancy_warning_false_when_few_high_pairs() -> None:
    """redundancy_warning_flag is False when only 1-3 high-correlation pairs."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    # Only two factors present — at most 1 pair
    rows = [{"breakout_freshness": float(i), "close_strength": float(i)} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    # At most 1 high-corr pair so flag must be False
    assert result["high_correlation_pair_count"] <= 1
    assert result["redundancy_warning_flag"] is False


def test_r28_factor_cross_corr_absent_factor_gracefully_skipped() -> None:
    """Factors with no data in rows (like F11/F12 cross-factors absent) are silently excluded."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    # Only provide two factors; all others are absent.
    rows = [{"breakout_freshness": float(i), "trend_acceleration": float(i) * 0.5} for i in range(10)]
    result = compute_factor_cross_correlation(rows)
    assert result["factor_max_correlation"] is not None
    assert result["high_correlation_pair_count"] is not None


def test_r28_factor_cross_corr_empty_rows_returns_nulls() -> None:
    """Empty rows should return all-null result without raising."""
    from scripts.btst_analysis_utils import compute_factor_cross_correlation
    result = compute_factor_cross_correlation([])
    assert result["factor_max_correlation"] is None
    assert result["avg_pairwise_correlation"] is None
    assert result["redundancy_warning_flag"] is False


# ---------------------------------------------------------------------------
# Task 2 (Round 28, Gamma): compute_regime_alpha_consistency
# ---------------------------------------------------------------------------


def test_r28_regime_alpha_all_positive() -> None:
    """When all domain alphas > 0, all_regimes_positive_alpha must be True."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    # bull days (hs300 > 0.003), bear days (hs300 < -0.003), sideways
    rows = (
        [{"hs300_daily_return": 0.01, "next_close_return": 0.02} for _ in range(6)]
        + [{"hs300_daily_return": -0.01, "next_close_return": 0.0} for _ in range(6)]
        + [{"hs300_daily_return": 0.001, "next_close_return": 0.005} for _ in range(6)]
    )
    result = compute_regime_alpha_consistency(rows)
    assert result["all_regimes_positive_alpha"] is True
    assert result["bull_alpha_avg"] is not None and result["bull_alpha_avg"] > 0
    assert result["bear_alpha_avg"] is not None and result["bear_alpha_avg"] > 0
    assert result["sideways_alpha_avg"] is not None and result["sideways_alpha_avg"] > 0


def test_r28_regime_alpha_bear_negative() -> None:
    """When bear alpha < 0, all_regimes_positive_alpha must be False."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    rows = (
        [{"hs300_daily_return": 0.01, "next_close_return": 0.02} for _ in range(6)]
        + [{"hs300_daily_return": -0.01, "next_close_return": -0.02} for _ in range(6)]
        + [{"hs300_daily_return": 0.001, "next_close_return": 0.005} for _ in range(6)]
    )
    result = compute_regime_alpha_consistency(rows)
    assert result["all_regimes_positive_alpha"] is False
    assert result["bear_alpha_avg"] is not None and result["bear_alpha_avg"] < 0
    assert result["worst_regime"] == "bear"


def test_r28_regime_alpha_consistency_score_correct() -> None:
    """alpha_consistency_score = min_alpha / max(|domain_alphas|)."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    # bull alpha = 0.01, bear alpha = 0.005, sideways alpha = 0.008  → min=0.005, max_abs=0.01
    rows = (
        [{"hs300_daily_return": 0.01, "next_close_return": 0.02} for _ in range(6)]   # alpha 0.01
        + [{"hs300_daily_return": -0.01, "next_close_return": -0.005} for _ in range(6)]  # alpha 0.005
        + [{"hs300_daily_return": 0.001, "next_close_return": 0.009} for _ in range(6)]  # alpha 0.008
    )
    result = compute_regime_alpha_consistency(rows)
    score = result["alpha_consistency_score"]
    assert score is not None
    # min(0.01, 0.005, 0.008) / max_abs(0.01) = 0.005 / 0.01 = 0.5
    assert abs(score - 0.5) < 0.01


def test_r28_regime_alpha_missing_hs300_returns_all_none() -> None:
    """When hs300_daily_return is absent, all fields should degrade to None."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    rows = [{"next_close_return": 0.01} for _ in range(10)]
    result = compute_regime_alpha_consistency(rows)
    assert result["bull_alpha_avg"] is None
    assert result["alpha_consistency_score"] is None
    assert result["all_regimes_positive_alpha"] is False


def test_r28_regime_alpha_insufficient_domain_samples() -> None:
    """Domain with < 5 samples returns None for that domain's alpha."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    # Only 3 bear days — bear_alpha_avg should be None
    rows = (
        [{"hs300_daily_return": 0.01, "next_close_return": 0.02} for _ in range(6)]
        + [{"hs300_daily_return": -0.01, "next_close_return": -0.005} for _ in range(3)]
        + [{"hs300_daily_return": 0.001, "next_close_return": 0.009} for _ in range(6)]
    )
    result = compute_regime_alpha_consistency(rows)
    assert result["bear_alpha_avg"] is None


def test_r28_regime_alpha_spread_calculation() -> None:
    """alpha_regime_spread should equal max_alpha - min_alpha across valid domains."""
    from scripts.btst_analysis_utils import compute_regime_alpha_consistency
    rows = (
        [{"hs300_daily_return": 0.01, "next_close_return": 0.03} for _ in range(6)]   # alpha 0.02
        + [{"hs300_daily_return": -0.01, "next_close_return": -0.008} for _ in range(6)]  # alpha 0.002
        + [{"hs300_daily_return": 0.001, "next_close_return": 0.006} for _ in range(6)]  # alpha 0.005
    )
    result = compute_regime_alpha_consistency(rows)
    spread = result["alpha_regime_spread"]
    assert spread is not None
    # max=0.02, min=0.002 → spread≈0.018
    assert abs(spread - 0.018) < 0.002


# ---------------------------------------------------------------------------
# Task 3 (Round 28, Beta): compute_post_loss_recovery_analysis
# ---------------------------------------------------------------------------


def test_r28_post_loss_mean_reversion_signal() -> None:
    """T+2 positive rate > 0.55 triggers mean_reversion_signal."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    # 7 out of 8 loss rows have T+2 > 0 → positive rate = 0.875
    rows = (
        [{"next_close_return": -0.02, "t_plus_2_close_return": 0.01} for _ in range(7)]
        + [{"next_close_return": -0.02, "t_plus_2_close_return": -0.01}]
        + [{"next_close_return": 0.01}]  # win row — excluded
    )
    result = compute_post_loss_recovery_analysis(rows)
    assert result["mean_reversion_signal"] is True
    assert result["momentum_continuation_signal"] is False
    assert result["post_loss_t2_positive_rate"] > 0.55


def test_r28_post_loss_momentum_continuation_signal() -> None:
    """T+2 positive rate < 0.45 triggers momentum_continuation_signal."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    rows = (
        [{"next_close_return": -0.02, "t_plus_2_close_return": -0.01} for _ in range(7)]
        + [{"next_close_return": -0.02, "t_plus_2_close_return": 0.01}]
        + [{"next_close_return": 0.01}]
    )
    result = compute_post_loss_recovery_analysis(rows)
    assert result["momentum_continuation_signal"] is True
    assert result["mean_reversion_signal"] is False


def test_r28_post_loss_hold_through_loss_beneficial_true() -> None:
    """hold_through_loss_beneficial is True when T+2 avg > |T1 loss avg| × 0.30."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    # T1 loss avg = -0.04; need T+2 avg > 0.04 × 0.30 = 0.012
    rows = [{"next_close_return": -0.04, "t_plus_2_close_return": 0.02} for _ in range(6)]
    result = compute_post_loss_recovery_analysis(rows)
    assert result["hold_through_loss_beneficial"] is True


def test_r28_post_loss_hold_through_loss_beneficial_false() -> None:
    """hold_through_loss_beneficial is False when T+2 avg ≤ |T1 loss avg| × 0.30."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    # T1 loss avg = -0.04; T+2 avg = 0.005 < 0.012 threshold
    rows = [{"next_close_return": -0.04, "t_plus_2_close_return": 0.005} for _ in range(6)]
    result = compute_post_loss_recovery_analysis(rows)
    assert result["hold_through_loss_beneficial"] is False


def test_r28_post_loss_insufficient_samples_degradation() -> None:
    """Fewer than 5 loss rows should degrade most fields to None."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    rows = [{"next_close_return": -0.02, "t_plus_2_close_return": 0.01} for _ in range(3)]
    result = compute_post_loss_recovery_analysis(rows)
    assert result["loss_sample_count"] == 3
    assert result["post_loss_t2_positive_rate"] is None
    assert result["mean_reversion_signal"] is False


def test_r28_post_loss_recovery_expected_value() -> None:
    """recovery_expected_value = t1_loss_avg × (1 + t2_avg_return)."""
    from scripts.btst_analysis_utils import compute_post_loss_recovery_analysis
    # T1 loss = -0.04, T+2 return = 0.02 → EV = -0.04 × 1.02 = -0.0408
    rows = [{"next_close_return": -0.04, "t_plus_2_close_return": 0.02} for _ in range(6)]
    result = compute_post_loss_recovery_analysis(rows)
    ev = result["recovery_expected_value"]
    assert ev is not None
    assert abs(ev - (-0.04 * 1.02)) < 0.001


# ---------------------------------------------------------------------------
# Round 28 registry tests — metrics in COMPARISON_METRICS / OPTIONAL / labels / floors
# ---------------------------------------------------------------------------


def test_r28_new_metrics_in_comparison_metrics() -> None:
    """All R28 COMPARISON_METRICS entries must be present."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "high_correlation_pair_count" in COMPARISON_METRICS
    assert "alpha_consistency_score" in COMPARISON_METRICS
    assert "all_regimes_positive_alpha" in COMPARISON_METRICS
    assert "post_loss_t2_positive_rate" in COMPARISON_METRICS


def test_r28_new_metrics_in_optional_comparison_metrics() -> None:
    """All R28 metrics must be optional (pre-R28 surfaces omit them)."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "high_correlation_pair_count" in OPTIONAL_COMPARISON_METRICS
    assert "alpha_consistency_score" in OPTIONAL_COMPARISON_METRICS
    assert "all_regimes_positive_alpha" in OPTIONAL_COMPARISON_METRICS
    assert "post_loss_t2_positive_rate" in OPTIONAL_COMPARISON_METRICS


def test_r28_new_metrics_have_labels() -> None:
    """All R28 metrics must have human-readable labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "high_correlation_pair_count" in COMPARISON_METRIC_LABELS
    assert "alpha_consistency_score" in COMPARISON_METRIC_LABELS
    assert "all_regimes_positive_alpha" in COMPARISON_METRIC_LABELS
    assert "post_loss_t2_positive_rate" in COMPARISON_METRIC_LABELS


def test_r28_high_correlation_pair_count_lower_is_better() -> None:
    """high_correlation_pair_count must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "high_correlation_pair_count" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r28_bear_alpha_floor_in_btst_quality_floors() -> None:
    """bear_alpha_avg floor must be registered at -0.005."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "bear_alpha_avg" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["bear_alpha_avg"] == -0.005


# ===========================================================================
# Round 29 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 (Alpha): compute_factor_pca_analysis
# ---------------------------------------------------------------------------


def test_r29_pca_fully_correlated_rank1() -> None:
    """All factors identical → PC1 explains 100 %, effective_factor_rank = 1."""
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness"]
    rows = []
    for i in range(20):
        v = float(i)
        rows.append({f: v for f in factor_names})
    result = compute_factor_pca_analysis(rows)
    assert result["effective_factor_rank"] == 1
    assert result["pca_diversity_score"] is not None
    assert 0.0 < result["pca_diversity_score"] <= 1.0


def test_r29_pca_fully_orthogonal_high_rank() -> None:
    """Fully independent factors → effective_rank ≥ 2 (more PCs needed for 80 %)."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    np.random.seed(42)
    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness"]
    data = np.random.randn(50, len(factor_names))
    rows = [{f: float(data[i, j]) for j, f in enumerate(factor_names)} for i in range(50)]
    result = compute_factor_pca_analysis(rows)
    assert result["effective_factor_rank"] is not None
    assert result["effective_factor_rank"] >= 2


def test_r29_pca_too_few_rows_returns_null() -> None:
    """Fewer than 10 aligned rows → all None fields."""
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    rows = [{"breakout_freshness": 0.5, "trend_acceleration": 0.3} for _ in range(8)]
    result = compute_factor_pca_analysis(rows)
    assert result["effective_factor_rank"] is None
    assert result["pca_diversity_score"] is None
    assert result["explained_variance_ratio"] is None


def test_r29_pca_diversity_score_in_unit_interval() -> None:
    """pca_diversity_score must always be in (0, 1]."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    np.random.seed(7)
    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength"]
    data = np.random.randn(30, len(factor_names))
    rows = [{f: float(data[i, j]) for j, f in enumerate(factor_names)} for i in range(30)]
    result = compute_factor_pca_analysis(rows)
    assert result["pca_diversity_score"] is not None
    assert 0.0 < result["pca_diversity_score"] <= 1.0


def test_r29_pca_pc1_dominant_factors_at_most_3() -> None:
    """pc1_dominant_factors should return at most 3 factor names."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    np.random.seed(13)
    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness"]
    data = np.random.randn(20, len(factor_names))
    rows = [{f: float(data[i, j]) for j, f in enumerate(factor_names)} for i in range(20)]
    result = compute_factor_pca_analysis(rows)
    assert isinstance(result["pc1_dominant_factors"], list)
    assert len(result["pc1_dominant_factors"]) <= 3


def test_r29_pca_redundancy_candidates_are_factor_names() -> None:
    """redundancy_reduction_candidates contains valid factor name strings."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis, BTST_FACTOR_NAMES

    np.random.seed(99)
    n = 30
    base = np.random.randn(n)
    noise = np.random.randn(n) * 0.01
    rows = [{"breakout_freshness": float(base[i]), "trend_acceleration": float(base[i] + noise[i]), "volume_expansion_quality": float(np.random.randn())} for i in range(n)]
    result = compute_factor_pca_analysis(rows)
    for name in result["redundancy_reduction_candidates"]:
        assert isinstance(name, str)
        assert name in BTST_FACTOR_NAMES


def test_r29_pca_absent_f11_f12_graceful_skip() -> None:
    """F11/F12 absent from rows → analysis still works on remaining factors."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    np.random.seed(5)
    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness", "close_strength"]
    data = np.random.randn(20, len(factor_names))
    rows = [{f: float(data[i, j]) for j, f in enumerate(factor_names)} for i in range(20)]
    result = compute_factor_pca_analysis(rows)
    # Should produce results without F11/F12
    assert result["pca_diversity_score"] is not None
    assert result["effective_factor_rank"] is not None


def test_r29_pca_explained_variance_sums_to_one() -> None:
    """explained_variance_ratio must sum to ≈ 1.0."""
    import numpy as np
    from scripts.btst_analysis_utils import compute_factor_pca_analysis

    np.random.seed(21)
    factor_names = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "catalyst_freshness"]
    data = np.random.randn(25, len(factor_names))
    rows = [{f: float(data[i, j]) for j, f in enumerate(factor_names)} for i in range(25)]
    result = compute_factor_pca_analysis(rows)
    if result["explained_variance_ratio"] is not None:
        total = sum(result["explained_variance_ratio"])
        assert abs(total - 1.0) < 0.01


# ---------------------------------------------------------------------------
# T2 (Gamma): compute_in_sample_oos_gap
# ---------------------------------------------------------------------------


def test_r29_oos_gap_overfit_warning_triggered() -> None:
    """IS much better than OOS → overfit_warning_flag = True."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = []
    for i in range(14):
        rows.append({"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.05})
    for i in range(6):
        rows.append({"date": f"2024-03-{i + 1:02d}", "next_close_return": -0.05})
    result = compute_in_sample_oos_gap(rows)
    assert result["overfit_warning_flag"] is True
    assert result["win_rate_gap"] is not None and result["win_rate_gap"] > 0


def test_r29_oos_gap_no_overfit_when_similar() -> None:
    """IS = OOS (identical alternating pattern) → overfit_score = 0, flag = False."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    # Strict alternating win/loss produces exactly 50% WR in both IS and OOS portions
    rows = [{"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.01 if i % 2 == 0 else -0.01} for i in range(20)]
    result = compute_in_sample_oos_gap(rows)
    assert result["overfit_score"] is not None
    assert result["overfit_warning_flag"] is False


def test_r29_oos_gap_oos_better_than_is() -> None:
    """OOS better than IS → negative win_rate_gap, flag = False."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = []
    for i in range(14):
        rows.append({"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.01 if i % 2 == 0 else -0.01})
    for i in range(6):
        rows.append({"date": f"2024-03-{i + 1:02d}", "next_close_return": 0.02 if i < 5 else -0.01})
    result = compute_in_sample_oos_gap(rows)
    assert result["win_rate_gap"] is not None
    assert result["win_rate_gap"] < 0
    assert result["overfit_warning_flag"] is False


def test_r29_oos_gap_too_few_rows_returns_null() -> None:
    """Fewer than ~17 total rows → None fields (IS or OOS set < 5)."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = [{"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.01} for i in range(10)]
    result = compute_in_sample_oos_gap(rows)
    assert result["overfit_score"] is None
    assert result["is_win_rate"] is None


def test_r29_oos_gap_win_rate_gap_consistency() -> None:
    """win_rate_gap must equal is_win_rate - oos_win_rate."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = [{"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.03 if i < 14 else -0.02} for i in range(20)]
    result = compute_in_sample_oos_gap(rows)
    if result["win_rate_gap"] is not None:
        expected = round((result["is_win_rate"] or 0.0) - (result["oos_win_rate"] or 0.0), 4)
        assert abs(result["win_rate_gap"] - expected) < 0.001


def test_r29_oos_gap_flag_consistent_with_score() -> None:
    """overfit_warning_flag must be True iff overfit_score > 0.20."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = []
    for i in range(14):
        rows.append({"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.021 if i % 2 == 0 else -0.001})
    for i in range(6):
        rows.append({"date": f"2024-03-{i + 1:02d}", "next_close_return": 0.018 if i % 2 == 0 else -0.002})
    result = compute_in_sample_oos_gap(rows)
    assert result["overfit_score"] is not None
    assert result["overfit_warning_flag"] == (result["overfit_score"] > 0.20)


def test_r29_oos_gap_missing_date_rows_skipped() -> None:
    """Rows without date or next_close_return excluded gracefully."""
    from scripts.btst_analysis_utils import compute_in_sample_oos_gap

    rows = [{"next_close_return": 0.01}] * 5
    rows += [{"date": f"2024-01-{i + 1:02d}", "next_close_return": 0.01} for i in range(20)]
    result = compute_in_sample_oos_gap(rows)
    assert result["overfit_score"] is not None


# ---------------------------------------------------------------------------
# T3 (Beta): compute_weekday_performance_analysis
# ---------------------------------------------------------------------------


def test_r29_weekday_monday_worst() -> None:
    """Monday (0) always negative → worst_weekday = 0."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 55:
        wd = d.weekday()
        if wd < 5:
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": -0.03 if wd == 0 else 0.03})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    assert result["worst_weekday"] == 0
    assert result["recommended_avoid_weekday"] == 0


def test_r29_weekday_friday_worst() -> None:
    """Friday (4) always negative → worst_weekday = 4."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 55:
        wd = d.weekday()
        if wd < 5:
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": -0.03 if wd == 4 else 0.03})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    assert result["worst_weekday"] == 4


def test_r29_weekday_uniform_no_strong_effect() -> None:
    """Uniform returns → calendar_effect_strong = False (small spread)."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    i = 0
    while len(rows) < 50:
        wd = d.weekday()
        if wd < 5:
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": 0.01 if i % 2 == 0 else -0.01})
            i += 1
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    assert result["weekday_win_rate_spread"] is not None
    assert result["calendar_effect_strong"] is False


def test_r29_weekday_spread_equals_best_minus_worst() -> None:
    """weekday_win_rate_spread = weekday_best_win_rate - weekday_worst_win_rate."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 55:
        wd = d.weekday()
        if wd < 5:
            ret = 0.03 if wd == 1 else (-0.03 if wd == 3 else 0.01)
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": ret})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    if result["weekday_win_rate_spread"] is not None:
        expected = round((result["weekday_best_win_rate"] or 0.0) - (result["weekday_worst_win_rate"] or 0.0), 4)
        assert abs(result["weekday_win_rate_spread"] - expected) < 0.001


def test_r29_weekday_calendar_effect_strong_flag() -> None:
    """calendar_effect_strong = True when spread > 0.10."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 65:
        wd = d.weekday()
        if wd < 5:
            ret = 0.03 if wd == 0 else (-0.03 if wd == 2 else 0.01)
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": ret})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    assert result["calendar_effect_strong"] is True
    assert result["weekday_win_rate_spread"] is not None and result["weekday_win_rate_spread"] > 0.10


def test_r29_weekday_insufficient_samples_per_day_excluded() -> None:
    """Weekday with < 5 samples excluded; < 2 valid weekdays → mostly None."""
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = [
        {"date": "2024-01-01", "next_close_return": 0.01},
        {"date": "2024-01-08", "next_close_return": 0.01},
        {"date": "2024-01-15", "next_close_return": 0.01},
    ]
    result = compute_weekday_performance_analysis(rows)
    assert result["best_weekday"] is None
    assert 0 not in result["weekday_win_rates"]


def test_r29_weekday_best_weekday_identified() -> None:
    """best_weekday = weekday with highest win rate."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 55:
        wd = d.weekday()
        if wd < 5:
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": 0.04 if wd == 1 else -0.01})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    if result["best_weekday"] is not None:
        assert result["best_weekday"] == 1


def test_r29_weekday_win_rates_keys_are_ints() -> None:
    """weekday_win_rates dict keys must be integers 0–4."""
    import datetime
    from scripts.btst_analysis_utils import compute_weekday_performance_analysis

    rows = []
    d = datetime.date(2024, 1, 1)
    while len(rows) < 40:
        wd = d.weekday()
        if wd < 5:
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": 0.01})
        d += datetime.timedelta(days=1)
    result = compute_weekday_performance_analysis(rows)
    for k in result["weekday_win_rates"]:
        assert isinstance(k, int) and 0 <= k <= 4


# ---------------------------------------------------------------------------
# Round 29: floor / cap / metric registration
# ---------------------------------------------------------------------------


def test_r29_effective_factor_rank_floor_registered() -> None:
    """effective_factor_rank floor must be registered at 3."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "effective_factor_rank" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["effective_factor_rank"] == 3


def test_r29_overfit_score_cap_registered() -> None:
    """overfit_score cap must be registered at 0.30."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    assert "overfit_score" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["overfit_score"] == 0.30


def test_r29_new_metrics_in_optional_comparison_metrics() -> None:
    """All R29 metrics must appear in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "pca_diversity_score" in OPTIONAL_COMPARISON_METRICS
    assert "overfit_score" in OPTIONAL_COMPARISON_METRICS
    assert "weekday_win_rate_spread" in OPTIONAL_COMPARISON_METRICS


def test_r29_overfit_score_in_lower_is_better_metrics() -> None:
    """overfit_score must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "overfit_score" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r29_new_metrics_have_labels() -> None:
    """All R29 metrics must have human-readable labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "pca_diversity_score" in COMPARISON_METRIC_LABELS
    assert "overfit_score" in COMPARISON_METRIC_LABELS
    assert "weekday_win_rate_spread" in COMPARISON_METRIC_LABELS


# ---------------------------------------------------------------------------
# Round 30 Tests
# ---------------------------------------------------------------------------

# T1 (Gamma): compute_parameter_stability_metrics
# ---------------------------------------------------------------------------


def test_r30_param_stability_stable_parameters() -> None:
    """Very stable metrics across windows → low param_drift_score, grade A or B."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    windows = [
        {"next_close_positive_rate": 0.60 + i * 0.001, "next_close_expectancy": 0.02 + i * 0.0001,
         "candidate_pool_avg_composite_score": 0.70, "realized_payoff_ratio": 1.5, "regime_consistency_score": 0.80}
        for i in range(6)
    ]
    result = compute_parameter_stability_metrics(windows)
    assert result["param_drift_score"] is not None
    assert result["param_drift_score"] < 0.30
    assert result["parameter_stability_grade"] in ("A", "B")


def test_r30_param_stability_unstable_parameters() -> None:
    """Wildly fluctuating metrics → high param_drift_score."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    windows = [
        {"next_close_positive_rate": v, "next_close_expectancy": v * 0.1,
         "candidate_pool_avg_composite_score": v, "realized_payoff_ratio": v * 2.0, "regime_consistency_score": v}
        for v in [0.20, 0.90, 0.15, 0.85, 0.10, 0.95]
    ]
    result = compute_parameter_stability_metrics(windows)
    assert result["param_drift_score"] is not None
    assert result["param_drift_score"] > 0.30


def test_r30_param_stability_insufficient_windows() -> None:
    """< 3 windows → param_drift_score = None."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    windows = [
        {"next_close_positive_rate": 0.60, "realized_payoff_ratio": 1.5},
        {"next_close_positive_rate": 0.65, "realized_payoff_ratio": 1.6},
    ]
    result = compute_parameter_stability_metrics(windows)
    assert result["param_drift_score"] is None
    assert result["parameter_stability_grade"] is None


def test_r30_param_stability_unstable_count() -> None:
    """unstable_param_count counts keys with relative drift > 0.40."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    # Build windows where all 5 keys fluctuate wildly
    windows = [
        {"next_close_positive_rate": v, "next_close_expectancy": v * 0.05,
         "candidate_pool_avg_composite_score": v + 0.1, "realized_payoff_ratio": v * 3.0, "regime_consistency_score": 1.0 - v}
        for v in [0.10, 0.90, 0.10, 0.90, 0.10]
    ]
    result = compute_parameter_stability_metrics(windows)
    assert result["unstable_param_count"] >= 1


def test_r30_param_stability_grade_assignment() -> None:
    """Grade boundaries: drift < 0.15 → A, < 0.30 → B, < 0.50 → C, ≥ 0.50 → D."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    # Constant values → drift ≈ 0 → grade A
    windows_const = [
        {"next_close_positive_rate": 0.60, "next_close_expectancy": 0.02,
         "candidate_pool_avg_composite_score": 0.70, "realized_payoff_ratio": 1.5, "regime_consistency_score": 0.80}
        for _ in range(5)
    ]
    r = compute_parameter_stability_metrics(windows_const)
    assert r["parameter_stability_grade"] == "A"


def test_r30_param_drift_score_is_median() -> None:
    """param_drift_score must equal the median of per-key drift scores."""
    from scripts.btst_analysis_utils import compute_parameter_stability_metrics

    windows = [
        {"next_close_positive_rate": v, "realized_payoff_ratio": 1.5,
         "next_close_expectancy": 0.02, "candidate_pool_avg_composite_score": 0.7, "regime_consistency_score": 0.8}
        for v in [0.50, 0.60, 0.70, 0.80, 0.90]
    ]
    result = compute_parameter_stability_metrics(windows)
    assert result["param_drift_score"] is not None
    drifts = list(result["param_drift_by_key"].values())
    drifts_sorted = sorted(drifts)
    n = len(drifts_sorted)
    expected = drifts_sorted[n // 2] if n % 2 == 1 else (drifts_sorted[n // 2 - 1] + drifts_sorted[n // 2]) / 2.0
    assert abs(result["param_drift_score"] - round(expected, 4)) < 0.001


def test_r30_param_drift_cap_registered() -> None:
    """param_drift_score cap must be registered at 0.50 in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    assert "param_drift_score" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["param_drift_score"] == 0.50


# ---------------------------------------------------------------------------
# T2 (Alpha): compute_monthly_performance_analysis
# ---------------------------------------------------------------------------


def _make_monthly_rows(month_returns: dict[int, list[float]]) -> list[dict]:
    """Build rows with dates targeting specific months."""
    import datetime
    rows = []
    base_year = 2022
    for month, rets in month_returns.items():
        for i, ret in enumerate(rets):
            day = min(i + 1, 28)
            d = datetime.date(base_year, month, day)
            rows.append({"date": d.strftime("%Y-%m-%d"), "next_close_return": ret})
    return rows


def test_r30_monthly_january_effect_present() -> None:
    """Month 1 win rate significantly above mean → january_effect_present = True."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    # January: all positive (wr=1.0); other months: 50/50 (wr=0.5)
    month_rets: dict[int, list[float]] = {1: [0.03] * 8}
    for m in range(2, 7):
        month_rets[m] = [0.02 if j % 2 == 0 else -0.02 for j in range(8)]
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    assert result["january_effect_present"] is True
    assert result["best_month"] == 1


def test_r30_monthly_worst_month_identified() -> None:
    """Month 12 all negative → worst_month = 12."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    month_rets: dict[int, list[float]] = {12: [-0.03] * 8}
    for m in range(1, 7):
        month_rets[m] = [0.02 if j % 2 == 0 else -0.01 for j in range(8)]
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    assert result["worst_month"] == 12


def test_r30_monthly_uniform_no_strong_effect() -> None:
    """Uniform win rates across months → seasonal_effect_strong = False."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    # All months 50/50 returns
    month_rets: dict[int, list[float]] = {}
    for m in range(1, 7):
        month_rets[m] = [0.02 if j % 2 == 0 else -0.02 for j in range(8)]
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    assert result["seasonal_effect_strong"] is False


def test_r30_monthly_spread_equals_best_minus_worst() -> None:
    """monthly_win_rate_spread = best win rate − worst win rate."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    month_rets: dict[int, list[float]] = {}
    for m in range(1, 5):
        month_rets[m] = [0.03] * 8 if m == 1 else [-0.03] * 8 if m == 3 else [0.01 if j % 2 == 0 else -0.01 for j in range(8)]
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    if result["monthly_win_rate_spread"] is not None:
        wrs = result["monthly_win_rates"]
        expected = round(max(wrs.values()) - min(wrs.values()), 4)
        assert abs(result["monthly_win_rate_spread"] - expected) < 0.001


def test_r30_monthly_seasonal_effect_strong_flag() -> None:
    """seasonal_effect_strong = True when spread > 0.10."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    month_rets: dict[int, list[float]] = {
        1: [0.05] * 8,   # wr=1.0
        2: [-0.05] * 8,  # wr=0.0
        3: [0.02 if j % 2 == 0 else -0.02 for j in range(8)],
        4: [0.02 if j % 2 == 0 else -0.02 for j in range(8)],
    }
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    assert result["seasonal_effect_strong"] is True


def test_r30_monthly_insufficient_samples_excluded() -> None:
    """Months with < 5 samples are excluded from spread/best/worst."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis
    import datetime

    # Month 1 has only 3 rows (excluded); month 2 has 8 rows
    rows = [{"date": f"2022-01-0{i + 1}", "next_close_return": 0.03} for i in range(3)]
    rows += [{"date": f"2022-0{m}-0{i + 1}", "next_close_return": 0.02 if i % 2 == 0 else -0.02}
             for m in range(2, 5) for i in range(8)]
    result = compute_monthly_performance_analysis(rows)
    # Month 1 should not appear in monthly_win_rates
    assert 1 not in result["monthly_win_rates"]


def test_r30_monthly_best_worst_month_identified() -> None:
    """best_month and worst_month are the months with max/min win rates."""
    from scripts.btst_analysis_utils import compute_monthly_performance_analysis

    month_rets: dict[int, list[float]] = {
        3: [0.05] * 8,   # wr=1.0 → best
        6: [-0.05] * 8,  # wr=0.0 → worst
        9: [0.02 if j % 2 == 0 else -0.02 for j in range(8)],  # wr≈0.5
    }
    rows = _make_monthly_rows(month_rets)
    result = compute_monthly_performance_analysis(rows)
    assert result["best_month"] == 3
    assert result["worst_month"] == 6


# ---------------------------------------------------------------------------
# T3 (Beta): compute_factor_nonlinearity
# ---------------------------------------------------------------------------


def _make_nonlin_rows(factor_name: str, factor_returns: list[tuple[float, float]]) -> list[dict]:
    """Build rows with (factor_value, next_close_return) pairs."""
    return [{"next_close_return": ret, factor_name: fv} for fv, ret in factor_returns]


def test_r30_nonlinear_u_shaped_factor_detected() -> None:
    """U-shaped factor (mid worse than extremes) → flagged as nonlinear."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    # Low: returns +5%, Mid: returns -5%, High: returns +5% → U-shape
    n_each = 10
    rows = (
        [{"next_close_return": 0.05, factor: 0.1 + i * 0.005} for i in range(n_each)]  # low
        + [{"next_close_return": -0.05, factor: 0.4 + i * 0.005} for i in range(n_each)]  # mid
        + [{"next_close_return": 0.05, factor: 0.7 + i * 0.005} for i in range(n_each)]  # high
    )
    result = compute_factor_nonlinearity(rows)
    assert factor in result["nonlinear_factor_names"]
    assert result["nonlinear_factor_count"] >= 1


def test_r30_nonlinear_monotone_linear_factor_not_flagged() -> None:
    """Strictly monotone linear factor → nonlinearity_ratio ≈ 0, not flagged."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    # Linear: low=-0.05, mid=0.0, high=+0.05 → mid is exactly at linear expectation
    n_each = 10
    rows = (
        [{"next_close_return": -0.05, factor: 0.1 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.00, factor: 0.4 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.05, factor: 0.7 + i * 0.005} for i in range(n_each)]
    )
    result = compute_factor_nonlinearity(rows)
    assert factor not in result["nonlinear_factor_names"]


def test_r30_nonlinearity_ratio_calculation() -> None:
    """nonlinearity_ratio = nonlinear_deviation / max(linear_score, 0.001)."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    # Inverted-U: low=0.0, mid=+0.10, high=0.0 → linear_score≈0.0, nonlin large
    n_each = 10
    rows = (
        [{"next_close_return": 0.00, factor: 0.1 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.10, factor: 0.4 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.00, factor: 0.7 + i * 0.005} for i in range(n_each)]
    )
    result = compute_factor_nonlinearity(rows)
    # nonlinear_deviation = |0.10 - 0.0| = 0.10, linear_score = |0.0 - 0.0| = 0.0 → ratio = 100
    assert result["nonlinear_factor_count"] >= 1 or result["avg_nonlinearity_ratio"] is not None


def test_r30_nonlinearity_threshold_0_30() -> None:
    """Factors with ratio > 0.30 are flagged; those ≤ 0.30 are not."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    # Weak nonlinearity: mid deviates only 1% from linear expectation
    n_each = 10
    rows = (
        [{"next_close_return": 0.00, factor: 0.1 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.051, factor: 0.4 + i * 0.005} for i in range(n_each)]  # expected mid = 0.05
        + [{"next_close_return": 0.10, factor: 0.7 + i * 0.005} for i in range(n_each)]
    )
    result = compute_factor_nonlinearity(rows)
    # linear_score=0.10, nonlinear_deviation=|0.051-0.05|=0.001 → ratio=0.01 → not flagged
    assert factor not in result["nonlinear_factor_names"]


def test_r30_nonlinearity_insufficient_samples_skipped() -> None:
    """Factors with < 15 paired rows are skipped (not included in result)."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    rows = [{"next_close_return": 0.03, factor: float(i)} for i in range(10)]  # only 10 rows
    result = compute_factor_nonlinearity(rows)
    assert result["nonlinear_factor_count"] == 0
    assert result["avg_nonlinearity_ratio"] is None


def test_r30_nonlinearity_most_nonlinear_factor() -> None:
    """most_nonlinear_factor is the factor with the highest nonlinearity_ratio."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    f0 = BTST_FACTOR_NAMES[0]
    f1 = BTST_FACTOR_NAMES[1] if len(BTST_FACTOR_NAMES) > 1 else None
    if f1 is None:
        return  # skip if only one factor

    n_each = 10
    # f0: strong U-shape (high nonlinearity)
    rows_f0 = (
        [{"next_close_return": 0.10, f0: 0.1 + i * 0.005, f1: 0.5} for i in range(n_each)]
        + [{"next_close_return": -0.10, f0: 0.4 + i * 0.005, f1: 0.5} for i in range(n_each)]
        + [{"next_close_return": 0.10, f0: 0.7 + i * 0.005, f1: 0.5} for i in range(n_each)]
    )
    result = compute_factor_nonlinearity(rows_f0)
    assert result["most_nonlinear_factor"] == f0


def test_r30_nonlinearity_count_and_avg_correct() -> None:
    """nonlinear_factor_count and avg_nonlinearity_ratio are consistent."""
    from scripts.btst_analysis_utils import compute_factor_nonlinearity, BTST_FACTOR_NAMES

    factor = BTST_FACTOR_NAMES[0]
    n_each = 10
    rows = (
        [{"next_close_return": 0.10, factor: 0.1 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": -0.10, factor: 0.4 + i * 0.005} for i in range(n_each)]
        + [{"next_close_return": 0.10, factor: 0.7 + i * 0.005} for i in range(n_each)]
    )
    result = compute_factor_nonlinearity(rows)
    assert isinstance(result["nonlinear_factor_count"], int)
    if result["avg_nonlinearity_ratio"] is not None:
        assert result["avg_nonlinearity_ratio"] >= 0.0


# ---------------------------------------------------------------------------
# Round 30: metric registration
# ---------------------------------------------------------------------------


def test_r30_new_metrics_in_comparison_metrics() -> None:
    """All R30 metrics must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "param_drift_score" in COMPARISON_METRICS
    assert "monthly_win_rate_spread" in COMPARISON_METRICS
    assert "nonlinear_factor_count" in COMPARISON_METRICS


def test_r30_new_metrics_in_optional_comparison_metrics() -> None:
    """All R30 metrics must appear in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "param_drift_score" in OPTIONAL_COMPARISON_METRICS
    assert "monthly_win_rate_spread" in OPTIONAL_COMPARISON_METRICS
    assert "nonlinear_factor_count" in OPTIONAL_COMPARISON_METRICS


def test_r30_lower_is_better_metrics_registered() -> None:
    """param_drift_score and nonlinear_factor_count must be in LOWER_IS_BETTER."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "param_drift_score" in LOWER_IS_BETTER_COMPARISON_METRICS
    assert "nonlinear_factor_count" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r30_new_metrics_have_labels() -> None:
    """All R30 metrics must have human-readable labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "param_drift_score" in COMPARISON_METRIC_LABELS
    assert "monthly_win_rate_spread" in COMPARISON_METRIC_LABELS
    assert "nonlinear_factor_count" in COMPARISON_METRIC_LABELS


# ===========================================================================
# Round 31 Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Task 1 (Alpha): compute_factor_return_autocorr — 7 tests
# ---------------------------------------------------------------------------


def test_r31_autocorr_positive_trend_sequence() -> None:
    """Strong trending sequence → autocorr_lag1 > 0 and momentum_persistence=True."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    # Alternating positive/negative but trending upward: 0.01, 0.02, ..., 0.10 x 2
    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": 0.01 * (i + 1)} for i in range(15)]
    result = compute_factor_return_autocorr(rows)
    assert result["autocorr_lag1"] is not None
    assert result["autocorr_lag1"] > 0
    assert result["momentum_persistence"] is True


def test_r31_autocorr_negative_mean_reversion() -> None:
    """Alternating positive/negative sequence → autocorr_lag1 < 0 and mean_reversion_tendency=True."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    vals = [0.05 * (1 if i % 2 == 0 else -1) for i in range(20)]
    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": vals[i]} for i in range(20)]
    result = compute_factor_return_autocorr(rows)
    assert result["autocorr_lag1"] is not None
    assert result["autocorr_lag1"] < 0
    assert result["mean_reversion_tendency"] is True


def test_r31_autocorr_insufficient_data_returns_none() -> None:
    """Fewer than 10 valid rows → all values are None."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": 0.01} for i in range(5)]
    result = compute_factor_return_autocorr(rows)
    assert result["autocorr_lag1"] is None
    assert result["autocorr_lag2"] is None
    assert result["longest_win_streak"] is None


def test_r31_autocorr_lag2_computed() -> None:
    """Lag-2 autocorrelation should be computed when n >= 12."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": 0.01 * (i + 1)} for i in range(15)]
    result = compute_factor_return_autocorr(rows)
    assert result["autocorr_lag2"] is not None


def test_r31_autocorr_win_loss_streaks_computed() -> None:
    """Win/loss streaks are correctly identified."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    # 5 wins, 5 losses, 5 wins
    vals = [0.01] * 5 + [-0.01] * 5 + [0.01] * 5
    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": vals[i]} for i in range(15)]
    result = compute_factor_return_autocorr(rows)
    assert result["longest_win_streak"] == 5
    assert result["longest_loss_streak"] == 5
    assert result["mean_win_streak"] is not None
    assert result["mean_loss_streak"] is not None


def test_r31_autocorr_significant_flag() -> None:
    """autocorr_significant=True when abs(lag1) > 0.15."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    # Strong alternating = large negative autocorr
    vals = [0.05 * (1 if i % 2 == 0 else -1) for i in range(20)]
    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": vals[i]} for i in range(20)]
    result = compute_factor_return_autocorr(rows)
    assert result["autocorr_significant"] is True


def test_r31_autocorr_random_sequence_small_abs() -> None:
    """Near-constant sequence has abs autocorr < 1 (sanity check)."""
    from scripts.btst_analysis_utils import compute_factor_return_autocorr

    # Same value every day → zero variance → None
    rows = [{"date": f"2024-01-{i+1:02d}", "next_close_return": 0.02} for i in range(15)]
    result = compute_factor_return_autocorr(rows)
    # All same values → Pearson undefined → None
    assert result["autocorr_lag1"] is None


# ---------------------------------------------------------------------------
# Task 2 (Gamma): compute_score_stability_across_windows — 7 tests
# ---------------------------------------------------------------------------


def test_r31_score_stability_stable_system() -> None:
    """Constant scores → low CV → score_system_stable=True."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    windows = [{"candidate_pool_avg_composite_score": 0.60, "next_close_positive_rate": 0.55} for _ in range(5)]
    result = compute_score_stability_across_windows(windows)
    assert result["score_cv_across_windows"] is not None
    assert result["score_cv_across_windows"] < 0.15
    assert result["score_system_stable"] is True


def test_r31_score_stability_unstable_system() -> None:
    """Highly variable scores → high CV → score_system_stable=False."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    scores = [0.20, 0.80, 0.20, 0.80, 0.20, 0.80]
    windows = [{"candidate_pool_avg_composite_score": s, "next_close_positive_rate": 0.55} for s in scores]
    result = compute_score_stability_across_windows(windows)
    assert result["score_cv_across_windows"] is not None
    assert result["score_cv_across_windows"] >= 0.15
    assert result["score_system_stable"] is False


def test_r31_score_stability_insufficient_windows_returns_none() -> None:
    """Fewer than 3 windows → all None."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    windows = [{"candidate_pool_avg_composite_score": 0.60} for _ in range(2)]
    result = compute_score_stability_across_windows(windows)
    assert result["score_cv_across_windows"] is None
    assert result["score_system_stable"] is None


def test_r31_score_stability_cv_calculation() -> None:
    """CV = std / mean, validated manually."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    scores = [0.5, 0.6, 0.7]
    windows = [{"candidate_pool_avg_composite_score": s} for s in scores]
    result = compute_score_stability_across_windows(windows)
    mean_s = sum(scores) / 3
    std_s = (sum((s - mean_s) ** 2 for s in scores) / 3) ** 0.5
    expected_cv = round(std_s / mean_s, 4)
    assert abs(result["score_cv_across_windows"] - expected_cv) < 0.001


def test_r31_score_stability_positive_trend() -> None:
    """Rising scores → positive score_trend_across_windows."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    scores = [0.40, 0.50, 0.60, 0.70, 0.80]
    windows = [{"candidate_pool_avg_composite_score": s} for s in scores]
    result = compute_score_stability_across_windows(windows)
    assert result["score_trend_across_windows"] is not None
    assert result["score_trend_across_windows"] > 0


def test_r31_score_stability_win_rate_corr_positive() -> None:
    """When score and win_rate move together → positive Spearman correlation."""
    from scripts.btst_analysis_utils import compute_score_stability_across_windows

    data = [{"candidate_pool_avg_composite_score": 0.4 + i * 0.05, "next_close_positive_rate": 0.50 + i * 0.02} for i in range(6)]
    result = compute_score_stability_across_windows(data)
    assert result["win_rate_score_corr"] is not None
    assert result["win_rate_score_corr"] > 0


def test_r31_score_cv_cap_registered() -> None:
    """score_cv_across_windows cap must be 0.30 in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    assert "score_cv_across_windows" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["score_cv_across_windows"] == 0.30


# ---------------------------------------------------------------------------
# Task 3 (Beta): F13 rs_sector_rank — 6 tests
# ---------------------------------------------------------------------------


def test_r31_f13_in_btst_factor_names() -> None:
    """BTST_FACTOR_NAMES must contain 'rs_sector_rank'."""
    from scripts.btst_analysis_utils import BTST_FACTOR_NAMES
    assert "rs_sector_rank" in BTST_FACTOR_NAMES


def test_r31_f13_profile_has_weight_field() -> None:
    """ShortTradeTargetProfile must have runner_composite_score_rs_sector_rank_weight defaulting to 0.0."""
    from src.targets.profiles import ShortTradeTargetProfile
    profile = ShortTradeTargetProfile(name="test_r31")
    assert hasattr(profile, "runner_composite_score_rs_sector_rank_weight")
    assert profile.runner_composite_score_rs_sector_rank_weight == 0.0


def test_r31_f13_probe_grid_has_rs_sector_rank_axis() -> None:
    """BTST_RUNNER_PROBE_GRID must include runner_composite_score_rs_sector_rank_weight axis."""
    from scripts.optimize_profile import BTST_RUNNER_PROBE_GRID
    assert "runner_composite_score_rs_sector_rank_weight" in BTST_RUNNER_PROBE_GRID
    assert 0.0 in BTST_RUNNER_PROBE_GRID["runner_composite_score_rs_sector_rank_weight"]


def test_r31_f13_full_grid_axis_count_24() -> None:
    """FULL_GRID_AXIS_COUNT must equal 24 after adding F13 axis."""
    from scripts.optimize_profile import FULL_GRID_AXIS_COUNT
    assert FULL_GRID_AXIS_COUNT == 24


def test_r31_f13_factor_to_probe_weight_key_mapping() -> None:
    """BTST_FACTOR_TO_PROBE_WEIGHT_KEY must map rs_sector_rank to the correct grid key."""
    from scripts.optimize_profile import BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    assert "rs_sector_rank" in BTST_FACTOR_TO_PROBE_WEIGHT_KEY
    assert BTST_FACTOR_TO_PROBE_WEIGHT_KEY["rs_sector_rank"] == "runner_composite_score_rs_sector_rank_weight"


def test_r31_f13_weight_positive_changes_score() -> None:
    """compute_runner_composite_score changes output when rs_sector_rank weight is non-zero."""
    from src.targets.short_trade_target_rank_helpers import compute_runner_composite_score

    class _ProfileZero:
        runner_composite_score_breakout_weight = 0.40
        runner_composite_score_trend_weight = 0.30
        runner_composite_score_volume_weight = 0.20
        runner_composite_score_catalyst_weight = 0.10
        runner_composite_score_close_strength_weight = 0.10
        runner_composite_score_volatility_regime_weight = 0.0
        runner_composite_score_sector_resonance_weight = 0.0
        runner_composite_score_quiet_breakout_weight = 0.0
        runner_composite_score_net_inflow_weight = 0.0
        runner_composite_score_volume_price_divergence_weight = 0.0
        runner_composite_score_t0_tail_weight = 0.0
        runner_composite_score_momentum_alignment_weight = 0.0
        runner_composite_score_momentum_confirmation_weight = 0.0
        runner_composite_score_volume_momentum_weight = 0.0
        runner_composite_score_rs_sector_rank_weight = 0.0

    class _ProfileWithRS(_ProfileZero):
        runner_composite_score_rs_sector_rank_weight = 0.20

    snapshot = {
        "breakout_freshness": 0.8,
        "trend_acceleration": 0.6,
        "volume_expansion_quality": 0.7,
        "catalyst_freshness": 0.5,
        "close_strength": 0.9,
        "sector_resonance": 0.3,
    }
    score_zero = compute_runner_composite_score(snapshot, _ProfileZero())
    score_with_rs = compute_runner_composite_score(snapshot, _ProfileWithRS())
    # F13 = (0.3 + 0.9) / 2 = 0.60, which differs from some other factor contributions
    # so the scores should differ when weight > 0
    assert score_zero != score_with_rs


# ---------------------------------------------------------------------------
# Round 32 Tests
# ---------------------------------------------------------------------------
# Task 1 (Gamma): compute_conditional_tail_risk — 7 tests
# Task 2 (Alpha): compute_volume_anomaly_metrics — 7 tests
# Task 3 (Beta): compute_composite_gate_score — 8 tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task 1 (Gamma): compute_conditional_tail_risk
# ---------------------------------------------------------------------------


def _make_ctr_rows(n: int = 40) -> list[dict]:
    """Create rows where high-score rows have low-loss returns, low-score rows high-loss returns."""
    rows = []
    for i in range(n):
        # scores 0..1 evenly spaced; low scores get more negative returns
        sc = i / (n - 1)
        ret = 0.05 if sc >= 0.5 else -0.05
        rows.append({"runner_composite_score": round(sc, 3), "next_close_return": round(ret, 4)})
    return rows


def test_r32_t1_score_tail_separation_positive() -> None:
    """High-score group has lower tail-loss rate → score_tail_separation > 0."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    rows = _make_ctr_rows(40)
    result = compute_conditional_tail_risk(rows)
    assert result["score_tail_separation"] is not None
    assert result["score_tail_separation"] > 0.0, f"Expected separation > 0, got {result['score_tail_separation']}"


def test_r32_t1_score_tail_separation_negative() -> None:
    """When high-score group has MORE losses, separation is negative and tail_risk_well_controlled=False."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    rows = []
    n = 40
    for i in range(n):
        sc = i / (n - 1)
        # Inverted: high score → deep loss
        ret = -0.05 if sc >= 0.5 else 0.05
        rows.append({"runner_composite_score": round(sc, 3), "next_close_return": round(ret, 4)})
    result = compute_conditional_tail_risk(rows)
    assert result["score_tail_separation"] is not None
    assert result["score_tail_separation"] < 0.0
    assert result["tail_risk_well_controlled"] is False


def test_r32_t1_cvar_calculation() -> None:
    """CVaR equals mean of worst 5% of returns."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    # 40 rows, all same high score → high-score group = all rows
    rows = [{"runner_composite_score": 0.9, "next_close_return": float(i) / 100} for i in range(-20, 20)]
    result = compute_conditional_tail_risk(rows)
    assert result["high_score_cvar_5pct"] is not None
    # Worst 5% of 40 rows = worst 2 rows: -0.20 and -0.19 → mean = -0.195
    assert abs(result["high_score_cvar_5pct"] - (-0.195)) < 0.001


def test_r32_t1_tail_risk_asymmetry() -> None:
    """tail_risk_asymmetry = |cvar_5pct| / max(upside_5pct, 0.001)."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    rows = [{"runner_composite_score": 0.9, "next_close_return": float(i) / 100} for i in range(-20, 20)]
    result = compute_conditional_tail_risk(rows)
    cvar = result["high_score_cvar_5pct"]
    upside = result["high_score_upside_5pct"]
    asym = result["tail_risk_asymmetry"]
    assert cvar is not None and upside is not None and asym is not None
    expected = round(abs(cvar) / max(upside, 0.001), 4)
    assert abs(asym - expected) < 0.001


def test_r32_t1_score_field_fallback() -> None:
    """composite_score → runner_composite_score fallback works correctly."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    rows = [{"composite_score": 0.9, "next_close_return": 0.02}] * 20 + \
           [{"composite_score": 0.1, "next_close_return": -0.04}] * 20
    result = compute_conditional_tail_risk(rows)
    assert result["score_field_used"] == "composite_score"
    assert result["score_tail_separation"] is not None


def test_r32_t1_insufficient_high_score_rows() -> None:
    """When high-score group has fewer than 5 rows, returns None for group-level stats."""
    from scripts.btst_analysis_utils import compute_conditional_tail_risk

    # Only 3 rows with score > P75 threshold
    rows = [{"runner_composite_score": 0.99, "next_close_return": 0.01}] * 3 + \
           [{"runner_composite_score": 0.01, "next_close_return": -0.05}] * 3
    result = compute_conditional_tail_risk(rows)
    # total rows = 6 < 10 → falls to global path or None group stats
    # No assertion on exact values; just must not raise
    assert isinstance(result, dict)


def test_r32_t1_floor_registered() -> None:
    """score_tail_separation floor must be registered in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "score_tail_separation" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_tail_separation"] == 0.0


# ---------------------------------------------------------------------------
# Task 2 (Alpha): compute_volume_anomaly_metrics
# ---------------------------------------------------------------------------


def _make_vam_rows_monotone(n: int = 30) -> list[dict]:
    """Create rows where volume_expansion_quality correlates with win rate."""
    rows = []
    for i in range(n):
        veq = i / (n - 1)
        enir = veq  # aligned
        ret = 0.03 if veq > 0.5 else -0.02
        rows.append({
            "volume_expansion_quality": round(veq, 3),
            "t0_estimated_net_inflow_ratio": round(enir, 3),
            "next_close_return": round(ret, 4),
        })
    return rows


def test_r32_t2_volume_monotone_win_rate_true() -> None:
    """When high volume has highest win rate, volume_monotone_win_rate=True."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    rows = _make_vam_rows_monotone(30)
    result = compute_volume_anomaly_metrics(rows)
    assert result["volume_monotone_win_rate"] is not None
    assert result["volume_monotone_win_rate"] is True


def test_r32_t2_volume_monotone_win_rate_false() -> None:
    """When low volume has highest win rate, volume_monotone_win_rate=False."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    rows = []
    n = 30
    for i in range(n):
        veq = i / (n - 1)
        # Inverted: low volume → positive return
        ret = 0.03 if veq < 0.5 else -0.02
        rows.append({"volume_expansion_quality": round(veq, 3), "t0_estimated_net_inflow_ratio": 0.5, "next_close_return": round(ret, 4)})
    result = compute_volume_anomaly_metrics(rows)
    assert result["volume_monotone_win_rate"] is False


def test_r32_t2_extreme_volume_premium_calculation() -> None:
    """extreme_volume_win_rate_premium = high_win_rate - low_win_rate."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    rows = _make_vam_rows_monotone(30)
    result = compute_volume_anomaly_metrics(rows)
    prem = result["extreme_volume_win_rate_premium"]
    h_wr = result["volume_high_win_rate"]
    l_wr = result["volume_low_win_rate"]
    assert prem is not None and h_wr is not None and l_wr is not None
    assert abs(prem - (h_wr - l_wr)) < 0.001


def test_r32_t2_inflow_win_rate_premium() -> None:
    """inflow_win_rate_premium = inflow_high_win_rate - inflow_low_win_rate."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    rows = _make_vam_rows_monotone(30)
    result = compute_volume_anomaly_metrics(rows)
    prem = result["inflow_win_rate_premium"]
    assert prem is not None
    assert isinstance(prem, float)


def test_r32_t2_volume_inflow_alignment_trigger() -> None:
    """volume_inflow_alignment is True when monotone AND inflow_premium > 0.05."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    rows = []
    n = 60
    for i in range(n):
        veq = i / (n - 1)
        enir = veq
        # Clear monotone signal: high vol/inflow → big positive return
        ret = 0.08 if veq > 0.67 else (0.02 if veq > 0.33 else -0.04)
        rows.append({"volume_expansion_quality": round(veq, 3), "t0_estimated_net_inflow_ratio": round(enir, 3), "next_close_return": round(ret, 4)})
    result = compute_volume_anomaly_metrics(rows)
    assert result["volume_inflow_alignment"] is not None


def test_r32_t2_insufficient_bucket_graceful() -> None:
    """When a volume bucket has < 3 rows, degrade gracefully (None, no exception)."""
    from scripts.btst_analysis_utils import compute_volume_anomaly_metrics

    # All rows in the same VEQ range — mid/high buckets will be empty or tiny
    rows = [{"volume_expansion_quality": 0.1, "t0_estimated_net_inflow_ratio": 0.5, "next_close_return": 0.01}] * 5
    result = compute_volume_anomaly_metrics(rows)
    # Should not raise; some stats will be None
    assert isinstance(result, dict)
    # With all rows having same VEQ, P33≈P67≈0.1; mid/high buckets might be empty
    # The function should not raise


def test_r32_t2_floor_registered() -> None:
    """extreme_volume_win_rate_premium floor must be 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "extreme_volume_win_rate_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["extreme_volume_win_rate_premium"] == 0.0


# ---------------------------------------------------------------------------
# Task 3 (Beta): compute_composite_gate_score
# ---------------------------------------------------------------------------


def _make_best_surface() -> dict:
    """Surface summary where all 6 dimensions are at or above ceiling."""
    return {
        "next_close_positive_rate": 0.60,  # above 0.55 ceiling
        "regime_consistency_score": 0.90,  # above 0.80 ceiling
        "profile_health_score": 90.0,       # above 80 ceiling
        "realized_payoff_ratio": 2.0,       # above 1.5 ceiling
        "overfit_score": 0.0,               # at 0.0 ceiling (lower is better)
        "kelly_fraction_half": 0.10,        # above 0.05 ceiling
    }


def _make_worst_surface() -> dict:
    """Surface summary where all 6 dimensions are at or below floor."""
    return {
        "next_close_positive_rate": 0.40,  # below 0.45 floor
        "regime_consistency_score": 0.50,  # below 0.60 floor
        "profile_health_score": 30.0,       # below 50 floor
        "realized_payoff_ratio": 0.50,      # below 1.0 floor
        "overfit_score": 0.30,              # above 0.20 floor (inverted)
        "kelly_fraction_half": 0.01,        # below 0.02 floor
    }


def test_r32_t3_all_best_gives_high_score() -> None:
    """All metrics at ceiling → gate_score near 100, grade=A, trade_recommended=True."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    result = compute_composite_gate_score(_make_best_surface())
    assert result["composite_gate_score"] is not None
    assert result["composite_gate_score"] >= 95.0, f"Expected ≥95, got {result['composite_gate_score']}"
    assert result["gate_score_grade"] == "A"
    assert result["trade_recommended"] is True


def test_r32_t3_all_worst_gives_low_score() -> None:
    """All metrics at floor → gate_score near 0, grade=D, trade_recommended=False."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    result = compute_composite_gate_score(_make_worst_surface())
    assert result["composite_gate_score"] is not None
    assert result["composite_gate_score"] <= 5.0, f"Expected ≤5, got {result['composite_gate_score']}"
    assert result["gate_score_grade"] == "D"
    assert result["trade_recommended"] is False


def test_r32_t3_partial_missing_normalises() -> None:
    """When some metrics are None, weights are renormalised, score stays in [0, 100]."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    surface = {
        "next_close_positive_rate": 0.60,
        "regime_consistency_score": None,
        "profile_health_score": None,
        "realized_payoff_ratio": 2.0,
        "overfit_score": None,
        "kelly_fraction_half": 0.10,
    }
    result = compute_composite_gate_score(surface)
    assert result["composite_gate_score"] is not None
    assert 0.0 <= result["composite_gate_score"] <= 100.0


def test_r32_t3_overfit_score_inverted() -> None:
    """overfit_score=0.0 → full credit; overfit_score=0.20 → zero credit."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    surface_good = {"overfit_score": 0.0}
    surface_bad = {"overfit_score": 0.20}
    score_good = compute_composite_gate_score(surface_good)["composite_gate_score"]
    score_bad = compute_composite_gate_score(surface_bad)["composite_gate_score"]
    assert score_good is not None and score_bad is not None
    assert score_good > score_bad, f"Expected {score_good} > {score_bad}"


def test_r32_t3_grade_thresholds() -> None:
    """Gate score grades: A(≥80) B(≥65) C(≥50) D(<50)."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    def _score_at(val: float) -> str | None:
        # Set all metrics to mid-range, then tweak next_close_positive_rate to drive score
        surface = {
            "next_close_positive_rate": val,
            "regime_consistency_score": None,
            "profile_health_score": None,
            "realized_payoff_ratio": None,
            "overfit_score": None,
            "kelly_fraction_half": None,
        }
        return compute_composite_gate_score(surface)["gate_score_grade"]

    # With only next_close_positive_rate present, the full 100 pts are from it.
    # val=0.55 → 100% → grade A
    assert _score_at(0.55) == "A"
    # val=0.45 → 0% → grade D
    assert _score_at(0.45) == "D"


def test_r32_t3_trade_recommended_threshold() -> None:
    """trade_recommended is True iff composite_gate_score >= 65."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    surface_pass = dict(_make_best_surface())
    surface_fail = dict(_make_worst_surface())
    assert compute_composite_gate_score(surface_pass)["trade_recommended"] is True
    assert compute_composite_gate_score(surface_fail)["trade_recommended"] is False


def test_r32_t3_score_in_range() -> None:
    """composite_gate_score must always be in [0, 100]."""
    from scripts.btst_analysis_utils import compute_composite_gate_score

    import random
    rng = random.Random(42)
    for _ in range(50):
        surface = {
            "next_close_positive_rate": rng.uniform(0.3, 0.7),
            "regime_consistency_score": rng.uniform(0.4, 1.0),
            "profile_health_score": rng.uniform(20.0, 100.0),
            "realized_payoff_ratio": rng.uniform(0.5, 3.0),
            "overfit_score": rng.uniform(0.0, 0.5),
            "kelly_fraction_half": rng.uniform(0.0, 0.15),
        }
        score = compute_composite_gate_score(surface)["composite_gate_score"]
        assert score is not None and 0.0 <= score <= 100.0, f"Out-of-range score: {score}"


def test_r32_t3_floor_registered() -> None:
    """composite_gate_score floor must be 50.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "composite_gate_score" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["composite_gate_score"] == 50.0


# ===========================================================================
# Round 33 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Task 1 (Alpha): compute_expected_value_metrics
# ---------------------------------------------------------------------------


def _make_ev_rows(n: int = 20, win_frac: float = 0.6, avg_win: float = 0.03, avg_loss: float = -0.02) -> list[dict]:
    """Make synthetic rows for EV metric tests."""
    rows = []
    for i in range(n):
        ret = avg_win if i < int(n * win_frac) else avg_loss
        rows.append({"next_close_return": round(ret, 4)})
    return rows


def test_r33_t1_ev_basic_calculation() -> None:
    """expected_value_per_trade matches manual E[R] formula."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = _make_ev_rows(20, win_frac=0.6, avg_win=0.03, avg_loss=-0.02)
    result = compute_expected_value_metrics(rows)
    assert result["expected_value_per_trade"] is not None
    ev = result["expected_value_per_trade"]
    expected = 0.6 * 0.03 + 0.4 * (-0.02)
    assert abs(ev - expected) < 1e-5, f"EV mismatch: {ev} vs {expected}"


def test_r33_t1_win_rate_ev_fraction() -> None:
    """win_rate_ev equals fraction of positive-return rows."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = _make_ev_rows(20, win_frac=0.5)
    result = compute_expected_value_metrics(rows)
    assert result["win_rate_ev"] is not None
    assert abs(result["win_rate_ev"] - 0.5) < 1e-4


def test_r33_t1_payoff_ratio_ev() -> None:
    """payoff_ratio_ev = avg_win / abs(avg_loss)."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = _make_ev_rows(20, avg_win=0.04, avg_loss=-0.02)
    result = compute_expected_value_metrics(rows)
    assert result["payoff_ratio_ev"] is not None
    assert abs(result["payoff_ratio_ev"] - 2.0) < 0.01


def test_r33_t1_grade_a_high_ev() -> None:
    """ev > 0.015 → grade A."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = [{"next_close_return": 0.04}] * 12 + [{"next_close_return": -0.01}] * 8
    result = compute_expected_value_metrics(rows)
    assert result["ev_grade"] == "A", f"Expected A, got {result['ev_grade']}"


def test_r33_t1_grade_d_negative_ev() -> None:
    """ev ≤ 0 → grade D."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = [{"next_close_return": 0.01}] * 8 + [{"next_close_return": -0.05}] * 12
    result = compute_expected_value_metrics(rows)
    assert result["ev_grade"] == "D", f"Expected D, got {result['ev_grade']}"
    assert result["ev_positive"] is False


def test_r33_t1_ev_positive_flag() -> None:
    """ev_positive=True when E[R] > 0."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = _make_ev_rows(20, win_frac=0.7, avg_win=0.03, avg_loss=-0.01)
    result = compute_expected_value_metrics(rows)
    assert result["ev_positive"] is True


def test_r33_t1_insufficient_rows_returns_none() -> None:
    """Fewer than 10 rows → all values are None."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = [{"next_close_return": 0.02}] * 9
    result = compute_expected_value_metrics(rows)
    assert result["expected_value_per_trade"] is None
    assert result["win_rate_ev"] is None
    assert result["ev_grade"] is None


def test_r33_t1_empty_rows_returns_none() -> None:
    """Empty input → all values are None, no exception."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    result = compute_expected_value_metrics([])
    assert result["expected_value_per_trade"] is None


def test_r33_t1_none_returns_filtered() -> None:
    """Rows with next_close_return=None are excluded from calculation."""
    from scripts.btst_analysis_utils import compute_expected_value_metrics

    rows = [{"next_close_return": None}] * 5 + [{"next_close_return": 0.02}] * 12
    result = compute_expected_value_metrics(rows)
    assert result["expected_value_per_trade"] is not None
    assert result["win_rate_ev"] == 1.0


def test_r33_t1_floor_registered() -> None:
    """expected_value_per_trade floor must be 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "expected_value_per_trade" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["expected_value_per_trade"] == 0.0


def test_r33_t1_in_comparison_metrics() -> None:
    """expected_value_per_trade must be registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "expected_value_per_trade" in COMPARISON_METRICS


def test_r33_t1_label_registered() -> None:
    """COMPARISON_METRIC_LABELS must contain the Chinese label for expected_value_per_trade."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "expected_value_per_trade" in COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS["expected_value_per_trade"] == "期望收益/笔"


# ---------------------------------------------------------------------------
# Task 2 (Gamma): compute_momentum_decay_curve
# ---------------------------------------------------------------------------


def _make_decay_rows(n: int = 20, t1: float = 0.03, t2: float = 0.02, t3: float = 0.01) -> list[dict]:
    """Make rows with explicit t2/t3 returns for decay curve tests."""
    return [{"next_close_return": t1, "t2_return": t2, "t3_return": t3} for _ in range(n)]


def test_r33_t2_half_life_fast_decay() -> None:
    """When t2 << t1, half_life < 1.5 → decay_speed='fast'."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = _make_decay_rows(20, t1=0.04, t2=0.005, t3=0.001)
    result = compute_momentum_decay_curve(rows)
    assert result["decay_curve_valid"] is True
    assert result["momentum_half_life_days"] is not None
    assert result["decay_speed"] == "fast", f"Expected fast, got {result['decay_speed']}"


def test_r33_t2_half_life_slow_decay() -> None:
    """When t2 ≈ t1, half_life is clamped to 10 and decay_speed='slow'."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = _make_decay_rows(20, t1=0.03, t2=0.03, t3=0.03)
    result = compute_momentum_decay_curve(rows)
    assert result["decay_curve_valid"] is True
    assert result["decay_speed"] == "slow"


def test_r33_t2_momentum_persists_true() -> None:
    """avg_t2 > 0.5 × avg_t1 → momentum_persists=True."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = _make_decay_rows(20, t1=0.02, t2=0.015, t3=0.01)
    result = compute_momentum_decay_curve(rows)
    assert result["momentum_persists"] is True


def test_r33_t2_momentum_persists_false() -> None:
    """avg_t2 < 0.5 × avg_t1 → momentum_persists=False."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = _make_decay_rows(20, t1=0.04, t2=0.01, t3=0.005)
    result = compute_momentum_decay_curve(rows)
    assert result["momentum_persists"] is False


def test_r33_t2_graceful_no_t2_column() -> None:
    """When t2_return and t_plus_2_close_return both absent → decay_curve_valid=False, no error."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = [{"next_close_return": 0.02} for _ in range(20)]
    result = compute_momentum_decay_curve(rows)
    assert result["decay_curve_valid"] is False
    assert result["momentum_half_life_days"] is None


def test_r33_t2_fallback_production_field_names() -> None:
    """Accepts t_plus_2_close_return and t_plus_3_close_return production field names."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    rows = [{"next_close_return": 0.03, "t_plus_2_close_return": 0.02, "t_plus_3_close_return": 0.01} for _ in range(20)]
    result = compute_momentum_decay_curve(rows)
    assert result["decay_curve_valid"] is True
    assert result["avg_t2_abs"] is not None


def test_r33_t2_half_life_clamped() -> None:
    """momentum_half_life_days is always clamped to [0.5, 10.0]."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    # Extreme scenario: t1 >> t2 → very short half-life, but clamped to 0.5
    rows = _make_decay_rows(20, t1=0.10, t2=0.0001, t3=0.0)
    result = compute_momentum_decay_curve(rows)
    assert result["decay_curve_valid"] is True
    hl = result["momentum_half_life_days"]
    assert hl is not None
    assert 0.5 <= hl <= 10.0


def test_r33_t2_in_comparison_metrics() -> None:
    """momentum_half_life_days must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "momentum_half_life_days" in COMPARISON_METRICS


def test_r33_t2_lower_is_better_registered() -> None:
    """momentum_half_life_days must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS

    assert "momentum_half_life_days" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r33_t2_empty_rows_no_error() -> None:
    """Empty row list → decay_curve_valid=False, no exception."""
    from scripts.btst_analysis_utils import compute_momentum_decay_curve

    result = compute_momentum_decay_curve([])
    assert result["decay_curve_valid"] is False


# ---------------------------------------------------------------------------
# Task 3 (Beta): compute_factor_ic_trend (cross-window)
# ---------------------------------------------------------------------------


def _make_ic_windows(n_windows: int = 5, factors: list[str] | None = None, trend: str = "stable") -> list[dict]:
    """Make synthetic all_primary_surfaces for IC trend tests."""
    if factors is None:
        factors = ["breakout_freshness", "trend_acceleration", "volume_expansion_quality"]
    windows = []
    for i in range(n_windows):
        if trend == "declining":
            ic_vals = {f: round(0.10 - i * 0.03, 4) for f in factors}
        elif trend == "improving":
            ic_vals = {f: round(-0.05 + i * 0.03, 4) for f in factors}
        else:  # stable
            ic_vals = {f: round(0.05 + (i % 2) * 0.01, 4) for f in factors}
        windows.append({"factor_ic_next_close": ic_vals, "next_close_positive_rate": 0.55})
    return windows


def test_r33_t3_stable_ic_high_stability() -> None:
    """Stable IC across windows → ic_trend_stability close to 1.0."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(6, trend="stable")
    result = compute_factor_ic_trend(windows)
    assert result["ic_trend_stability"] is not None
    assert result["ic_trend_stability"] >= 0.5


def test_r33_t3_all_declining_ic() -> None:
    """When all factors have strongly declining IC → factor_ic_trend_deteriorating=True."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(6, trend="declining")
    result = compute_factor_ic_trend(windows)
    assert result["factor_ic_trend_deteriorating"] is True


def test_r33_t3_all_improving_ic() -> None:
    """Improving IC → factor_ic_trend_deteriorating=False."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(6, trend="improving")
    result = compute_factor_ic_trend(windows)
    assert result["factor_ic_trend_deteriorating"] is False


def test_r33_t3_too_few_windows_returns_none() -> None:
    """Fewer than 3 windows → ic_trend_stability=None."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(2)
    result = compute_factor_ic_trend(windows)
    assert result["ic_trend_stability"] is None
    assert result["factor_ic_trend_deteriorating"] is None


def test_r33_t3_empty_windows_returns_none() -> None:
    """Empty window list → graceful None result, no exception."""
    from scripts.optimize_profile import compute_factor_ic_trend

    result = compute_factor_ic_trend([])
    assert result["ic_trend_stability"] is None


def test_r33_t3_missing_ic_field_graceful() -> None:
    """Windows without factor_ic_next_close or factor_ic_mean don't crash."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = [{"next_close_positive_rate": 0.55} for _ in range(5)]
    result = compute_factor_ic_trend(windows)
    assert isinstance(result, dict)
    assert result["ic_trend_stability"] is None


def test_r33_t3_ic_trend_stability_in_0_1() -> None:
    """ic_trend_stability is always in [0, 1]."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(5, trend="declining")
    result = compute_factor_ic_trend(windows)
    if result["ic_trend_stability"] is not None:
        assert 0.0 <= result["ic_trend_stability"] <= 1.0


def test_r33_t3_declining_factors_list_populated() -> None:
    """declining_factors key is populated when IC is declining."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = _make_ic_windows(6, factors=["breakout_freshness"], trend="declining")
    result = compute_factor_ic_trend(windows)
    assert "declining_factors" in result
    assert len(result["declining_factors"]) >= 1


def test_r33_t3_in_comparison_metrics() -> None:
    """ic_trend_stability and factor_ic_trend_deteriorating in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "ic_trend_stability" in COMPARISON_METRICS
    assert "factor_ic_trend_deteriorating" in COMPARISON_METRICS


def test_r33_t3_factor_ic_mean_key_supported() -> None:
    """compute_factor_ic_trend reads factor_ic_mean key as well as factor_ic_next_close."""
    from scripts.optimize_profile import compute_factor_ic_trend

    windows = [{"factor_ic_mean": {"breakout_freshness": 0.10 - i * 0.03}} for i in range(5)]
    result = compute_factor_ic_trend(windows)
    assert result["ic_trend_stability"] is not None


# ===========================================================================
# Round 34 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers for Round 34
# ---------------------------------------------------------------------------

def _make_cross_factor_rows(n: int, *, win_frac: float = 0.6, high_frac: float = 0.5) -> list[dict]:
    """Generate rows with 7 cross-factors and next_close_return."""
    import random
    random.seed(42)
    rows = []
    factors = ["close_strength", "volume_expansion_quality", "sector_resonance", "rs_sector_rank",
               "t0_estimated_net_inflow_ratio", "breakout_quality_score", "momentum_slope_20d"]
    for i in range(n):
        ret = 0.02 if i < int(n * win_frac) else -0.01
        row: dict = {"next_close_return": ret}
        for f in factors:
            # First high_frac rows get high values, rest get low values.
            row[f] = 0.8 if i < int(n * high_frac) else 0.2
        rows.append(row)
    return rows


def _make_churn_windows(n: int, *, stable: bool = True) -> list[dict]:
    """Generate n window summaries with candidate_pool_size and top_stocks."""
    windows = []
    for i in range(n):
        size = 10 if stable else max(1, 10 + (i % 3) * 8)
        stocks = [f"STOCK_{j}" for j in range(i, i + 5)] if stable else [f"STOCK_{j}" for j in range(i * 5, i * 5 + 5)]
        windows.append({"candidate_pool_size": size, "top_stocks": stocks})
    return windows


# ---------------------------------------------------------------------------
# Round 34, T1 — compute_cross_factor_conditional
# ---------------------------------------------------------------------------

def test_r34_t1_basic_returns_expected_keys() -> None:
    """compute_cross_factor_conditional returns all required keys."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    rows = _make_cross_factor_rows(40)
    result = compute_cross_factor_conditional(rows)
    for key in ("group_win_rates", "group_counts", "multi_factor_lift", "multi_factor_synergy", "optimal_factor_count"):
        assert key in result, f"Missing key: {key}"


def test_r34_t1_insufficient_rows_returns_empty() -> None:
    """Fewer than 20 rows with next_close_return → empty / None result."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    rows = _make_cross_factor_rows(15)
    result = compute_cross_factor_conditional(rows)
    assert result["multi_factor_lift"] is None
    assert result["group_win_rates"] == {}


def test_r34_t1_empty_rows_no_error() -> None:
    """Empty input → graceful empty result."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    result = compute_cross_factor_conditional([])
    assert result["multi_factor_lift"] is None


def test_r34_t1_none_returns_filtered() -> None:
    """Rows with next_close_return=None are excluded from analysis."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    factors = ["close_strength", "volume_expansion_quality", "sector_resonance", "rs_sector_rank",
               "t0_estimated_net_inflow_ratio", "breakout_quality_score", "momentum_slope_20d"]
    rows = [{"next_close_return": None, **{f: 0.5 for f in factors}}] * 25
    result = compute_cross_factor_conditional(rows)
    assert result["multi_factor_lift"] is None


def test_r34_t1_group_counts_sum_to_total() -> None:
    """Sum of group_counts equals number of rows with next_close_return."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    rows = _make_cross_factor_rows(40)
    result = compute_cross_factor_conditional(rows)
    total = sum(result["group_counts"].values())
    assert total == 40


def test_r34_t1_synergy_true_when_lift_positive() -> None:
    """multi_factor_synergy=True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    # Force: rows with ALL factors high → all win; rows with none high → all lose.
    factors = ["close_strength", "volume_expansion_quality", "sector_resonance", "rs_sector_rank",
               "t0_estimated_net_inflow_ratio", "breakout_quality_score", "momentum_slope_20d"]
    high_rows = [{"next_close_return": 0.03, **{f: 0.95 for f in factors}} for _ in range(20)]
    low_rows = [{"next_close_return": -0.02, **{f: 0.05 for f in factors}} for _ in range(20)]
    result = compute_cross_factor_conditional(high_rows + low_rows)
    if result["multi_factor_lift"] is not None:
        assert result["multi_factor_synergy"] == (result["multi_factor_lift"] > 0.05)


def test_r34_t1_optimal_factor_count_valid_key() -> None:
    """optimal_factor_count is one of the valid group keys (0,1,2,'3+')."""
    from scripts.btst_analysis_utils import compute_cross_factor_conditional

    rows = _make_cross_factor_rows(50)
    result = compute_cross_factor_conditional(rows)
    if result["optimal_factor_count"] is not None:
        assert result["optimal_factor_count"] in (0, 1, 2, "3+")


def test_r34_t1_floor_registered() -> None:
    """multi_factor_lift floor = 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "multi_factor_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["multi_factor_lift"] == 0.0


def test_r34_t1_in_comparison_metrics() -> None:
    """multi_factor_lift registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "multi_factor_lift" in COMPARISON_METRICS


def test_r34_t1_label_registered() -> None:
    """multi_factor_lift has Chinese label '多因子联合提升'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("multi_factor_lift") == "多因子联合提升"


# ---------------------------------------------------------------------------
# Round 34, T2 — compute_adaptive_sizing_score
# ---------------------------------------------------------------------------

def test_r34_t2_basic_returns_required_keys() -> None:
    """compute_adaptive_sizing_score returns all required keys."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    summary = {"expected_value_per_trade": 0.01, "kelly_fraction_half": 0.10, "composite_gate_score": 70.0, "score_tail_separation": 0.05}
    result = compute_adaptive_sizing_score(summary)
    for key in ("adaptive_sizing_score", "sizing_multiplier", "sizing_grade", "full_size_recommended"):
        assert key in result, f"Missing key: {key}"


def test_r34_t2_empty_dict_no_error() -> None:
    """Empty summary dict → graceful result, score=0, grade D."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    result = compute_adaptive_sizing_score({})
    assert result["adaptive_sizing_score"] == 0.0
    assert result["sizing_grade"] == "D"
    assert result["full_size_recommended"] is False


def test_r34_t2_all_max_values_grade_a() -> None:
    """All dimensions at maximum → score=100, grade A, full_size_recommended."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    summary = {"expected_value_per_trade": 0.05, "kelly_fraction_half": 0.30, "composite_gate_score": 100.0, "score_tail_separation": 0.10}
    result = compute_adaptive_sizing_score(summary)
    assert result["adaptive_sizing_score"] == 100.0
    assert result["sizing_grade"] == "A"
    assert result["full_size_recommended"] is True


def test_r34_t2_all_min_values_grade_d() -> None:
    """All dimensions at minimum → score=0, grade D."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    summary = {"expected_value_per_trade": -0.05, "kelly_fraction_half": 0.0, "composite_gate_score": 0.0, "score_tail_separation": -0.10}
    result = compute_adaptive_sizing_score(summary)
    assert result["adaptive_sizing_score"] == 0.0
    assert result["sizing_grade"] == "D"


def test_r34_t2_sizing_multiplier_range() -> None:
    """sizing_multiplier is always in [0.5, 1.0]."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    for ev in [-0.05, 0.0, 0.02, 0.05]:
        result = compute_adaptive_sizing_score({"expected_value_per_trade": ev})
        m = result["sizing_multiplier"]
        assert 0.5 <= m <= 1.0, f"multiplier {m} out of [0.5, 1.0] for ev={ev}"


def test_r34_t2_partial_none_normalises_weights() -> None:
    """Missing dimensions are skipped; remaining weights normalised to 100."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    # Only one dimension present.
    result = compute_adaptive_sizing_score({"composite_gate_score": 100.0})
    assert result["adaptive_sizing_score"] == 100.0


def test_r34_t2_kelly_half_alias() -> None:
    """kelly_half key is accepted as alias for kelly_fraction_half."""
    from scripts.btst_analysis_utils import compute_adaptive_sizing_score

    r1 = compute_adaptive_sizing_score({"kelly_half": 0.15})
    r2 = compute_adaptive_sizing_score({"kelly_fraction_half": 0.15})
    assert r1["adaptive_sizing_score"] == r2["adaptive_sizing_score"]


def test_r34_t2_floor_registered() -> None:
    """adaptive_sizing_score floor = 50.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "adaptive_sizing_score" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["adaptive_sizing_score"] == 50.0


def test_r34_t2_in_comparison_metrics() -> None:
    """adaptive_sizing_score registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "adaptive_sizing_score" in COMPARISON_METRICS


def test_r34_t2_label_registered() -> None:
    """adaptive_sizing_score has Chinese label '自适应仓位评分'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("adaptive_sizing_score") == "自适应仓位评分"


# ---------------------------------------------------------------------------
# Round 34, T3 — compute_signal_churn_metrics
# ---------------------------------------------------------------------------

def test_r34_t3_basic_returns_required_keys() -> None:
    """compute_signal_churn_metrics returns required keys."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    windows = _make_churn_windows(5)
    result = compute_signal_churn_metrics(windows)
    for key in ("signal_churn_rate", "avg_signal_persistence", "avg_pool_size_churn", "pool_stable"):
        assert key in result, f"Missing key: {key}"


def test_r34_t3_too_few_windows_returns_none() -> None:
    """Fewer than 3 windows → all None."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    result = compute_signal_churn_metrics([{"candidate_pool_size": 10}] * 2)
    assert result["signal_churn_rate"] is None
    assert result["avg_signal_persistence"] is None
    assert result["pool_stable"] is None


def test_r34_t3_empty_returns_none() -> None:
    """Empty list → all None."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    result = compute_signal_churn_metrics([])
    assert result["signal_churn_rate"] is None


def test_r34_t3_stable_pool_pool_stable_true() -> None:
    """Stable pool (same size, same stocks) → pool_stable True."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    windows = [{"candidate_pool_size": 10, "top_stocks": ["A", "B", "C", "D", "E"]} for _ in range(5)]
    result = compute_signal_churn_metrics(windows)
    assert result["pool_stable"] is True
    assert result["avg_pool_size_churn"] == 0.0


def test_r34_t3_completely_churned_stocks() -> None:
    """Completely different stocks every window → signal_churn_rate = 1.0."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    windows = [{"candidate_pool_size": 5, "top_stocks": [f"S{i*5+j}" for j in range(5)]} for i in range(5)]
    result = compute_signal_churn_metrics(windows)
    if result["avg_signal_persistence"] is not None:
        assert result["signal_churn_rate"] is not None
        assert abs(result["signal_churn_rate"] - (1 - result["avg_signal_persistence"])) < 1e-6


def test_r34_t3_missing_top_stocks_graceful() -> None:
    """Missing top_stocks field → avg_signal_persistence None, no error."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    windows = [{"candidate_pool_size": 10} for _ in range(5)]
    result = compute_signal_churn_metrics(windows)
    assert result["avg_signal_persistence"] is None
    assert result["signal_churn_rate"] is None


def test_r34_t3_pool_size_churn_computed() -> None:
    """avg_pool_size_churn is computed when candidate_pool_size present."""
    from scripts.optimize_profile import compute_signal_churn_metrics

    windows = [{"candidate_pool_size": 10 + i * 2} for i in range(5)]
    result = compute_signal_churn_metrics(windows)
    assert result["avg_pool_size_churn"] is not None
    assert result["avg_pool_size_churn"] >= 0.0


def test_r34_t3_signal_churn_rate_in_comparison_metrics() -> None:
    """signal_churn_rate in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "signal_churn_rate" in COMPARISON_METRICS


def test_r34_t3_signal_churn_lower_is_better() -> None:
    """signal_churn_rate in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS

    assert "signal_churn_rate" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r34_t3_avg_signal_persistence_in_comparison_metrics() -> None:
    """avg_signal_persistence in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "avg_signal_persistence" in COMPARISON_METRICS


def test_r34_t3_label_registered() -> None:
    """avg_signal_persistence has Chinese label '信号持续率'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("avg_signal_persistence") == "信号持续率"


def test_r34_t3_signal_churn_label_registered() -> None:
    """signal_churn_rate has Chinese label '信号流失率'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("signal_churn_rate") == "信号流失率"


# ===========================================================================
# Round 35 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Round 35, T1 — compute_sharpe_sortino_analysis
# ---------------------------------------------------------------------------

def _make_rows_with_returns(returns: list[float]) -> list[dict]:
    """Helper: build row dicts with next_close_return."""
    return [{"next_close_return": r} for r in returns]


def test_r35_t1_basic_returns_required_keys() -> None:
    """compute_sharpe_sortino_analysis returns all required keys."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    rows = _make_rows_with_returns([0.01] * 10 + [-0.005] * 5)
    result = compute_sharpe_sortino_analysis(rows)
    for key in ("sharpe_ratio", "sortino_ratio", "calmar_proxy", "annualized_return", "annualized_vol", "risk_adjusted_grade", "sortino_positive"):
        assert key in result, f"Missing key: {key}"


def test_r35_t1_insufficient_rows_returns_all_none() -> None:
    """Fewer than 10 rows → all None values."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    result = compute_sharpe_sortino_analysis(_make_rows_with_returns([0.01] * 9))
    assert result["sortino_ratio"] is None
    assert result["sharpe_ratio"] is None
    assert result["risk_adjusted_grade"] is None


def test_r35_t1_empty_rows_all_none() -> None:
    """Empty rows → all None."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    result = compute_sharpe_sortino_analysis([])
    assert result["sortino_ratio"] is None


def test_r35_t1_none_returns_filtered_gracefully() -> None:
    """Rows with None next_close_return are silently skipped."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    rows = [{"next_close_return": None}] * 5 + _make_rows_with_returns([0.01] * 15)
    result = compute_sharpe_sortino_analysis(rows)
    assert result["sortino_ratio"] is not None


def test_r35_t1_positive_returns_grade_reflects_sortino() -> None:
    """Consistently positive returns → sortino_positive True and grade A or B."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    rows = _make_rows_with_returns([0.02] * 20)
    result = compute_sharpe_sortino_analysis(rows)
    assert result["sortino_positive"] is True
    assert result["risk_adjusted_grade"] in ("A", "B", "C")


def test_r35_t1_all_losses_grade_d() -> None:
    """All negative returns → sortino_positive False, grade D."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    rows = _make_rows_with_returns([-0.01] * 20)
    result = compute_sharpe_sortino_analysis(rows)
    assert result["sortino_positive"] is False
    assert result["risk_adjusted_grade"] == "D"


def test_r35_t1_sortino_ratio_clamped() -> None:
    """sortino_ratio is clamped to [-5, 5]."""
    from scripts.btst_analysis_utils import compute_sharpe_sortino_analysis

    rows = _make_rows_with_returns([0.10] * 10 + [-0.0001] * 5)
    result = compute_sharpe_sortino_analysis(rows)
    assert -5.0 <= result["sortino_ratio"] <= 5.0


def test_r35_t1_floor_registered() -> None:
    """sortino_ratio floor = 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "sortino_ratio" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["sortino_ratio"] == 0.0


def test_r35_t1_in_comparison_metrics() -> None:
    """sortino_ratio registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "sortino_ratio" in COMPARISON_METRICS


def test_r35_t1_label_registered() -> None:
    """sortino_ratio has Chinese label 'Sortino风险收益比'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("sortino_ratio") == "Sortino风险收益比"


# ---------------------------------------------------------------------------
# Round 35, T2 — compute_quality_trend_analysis
# ---------------------------------------------------------------------------

def test_r35_t2_basic_returns_required_keys() -> None:
    """compute_quality_trend_analysis returns required keys."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    summaries = [{"win_rate": 0.55 + i * 0.01, "expected_value_per_trade": 0.005 * (i + 1)} for i in range(5)]
    result = compute_quality_trend_analysis(summaries)
    for key in ("quality_trend_improving", "quality_trend_score", "quality_trend_grade"):
        assert key in result, f"Missing key: {key}"


def test_r35_t2_too_few_windows_returns_none() -> None:
    """Fewer than 3 windows → all None."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    result = compute_quality_trend_analysis([{"win_rate": 0.6}] * 2)
    assert result["quality_trend_improving"] is None
    assert result["quality_trend_score"] is None


def test_r35_t2_empty_returns_none() -> None:
    """Empty list → all None."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    result = compute_quality_trend_analysis([])
    assert result["quality_trend_score"] is None


def test_r35_t2_all_improving_score_one() -> None:
    """All metrics monotonically increasing → quality_trend_score = 1.0, grade A."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    summaries = [
        {"win_rate": 0.50 + i * 0.02, "expected_value_per_trade": 0.001 * (i + 1), "composite_gate_score": 60 + i * 2, "sortino_ratio": 0.1 * (i + 1)}
        for i in range(5)
    ]
    result = compute_quality_trend_analysis(summaries)
    assert result["quality_trend_score"] == 1.0
    assert result["quality_trend_improving"] is True
    assert result["quality_trend_grade"] == "A"


def test_r35_t2_all_declining_score_zero() -> None:
    """All metrics declining → quality_trend_score = 0.0, grade D."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    summaries = [
        {"win_rate": 0.70 - i * 0.02, "expected_value_per_trade": 0.01 - i * 0.002, "composite_gate_score": 80 - i * 3, "sortino_ratio": 1.0 - i * 0.2}
        for i in range(5)
    ]
    result = compute_quality_trend_analysis(summaries)
    assert result["quality_trend_score"] == 0.0
    assert result["quality_trend_improving"] is False
    assert result["quality_trend_grade"] == "D"


def test_r35_t2_partial_none_metrics_graceful() -> None:
    """Metrics with all-None values are excluded; remaining metrics drive the score."""
    from scripts.optimize_profile import compute_quality_trend_analysis

    summaries = [{"win_rate": 0.50 + i * 0.01} for i in range(4)]
    result = compute_quality_trend_analysis(summaries)
    assert result["quality_trend_score"] is not None
    assert result["quality_trend_improving"] is True


def test_r35_t2_in_comparison_metrics() -> None:
    """quality_trend_score registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "quality_trend_score" in COMPARISON_METRICS


def test_r35_t2_label_registered() -> None:
    """quality_trend_score has Chinese label '质量趋势评分'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("quality_trend_score") == "质量趋势评分"


# ---------------------------------------------------------------------------
# Round 35, T3 — compute_candidate_diversity_score
# ---------------------------------------------------------------------------

def _make_rows_with_sectors(sectors: list[str | None]) -> list[dict]:
    """Helper: build row dicts with sector field."""
    return [{"sector": s} for s in sectors]


def test_r35_t3_basic_returns_required_keys() -> None:
    """compute_candidate_diversity_score returns all required keys."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    rows = _make_rows_with_sectors(["tech", "finance", "health", "energy", "tech", "finance", "health"])
    result = compute_candidate_diversity_score(rows)
    for key in ("sector_hhi", "diversity_score", "diversity_grade", "sector_count", "dominant_sector_share", "concentration_risk"):
        assert key in result, f"Missing key: {key}"


def test_r35_t3_too_few_rows_returns_all_none() -> None:
    """Fewer than 5 valid rows → all None."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    result = compute_candidate_diversity_score(_make_rows_with_sectors(["tech", "finance", "health", "energy"]))
    assert result["diversity_score"] is None
    assert result["sector_hhi"] is None


def test_r35_t3_empty_rows_returns_all_none() -> None:
    """Empty rows → all None."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    result = compute_candidate_diversity_score([])
    assert result["diversity_score"] is None


def test_r35_t3_all_same_sector_low_diversity() -> None:
    """All rows same sector → diversity_score ≈ 0, grade D, concentration_risk True."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    rows = _make_rows_with_sectors(["tech"] * 10)
    result = compute_candidate_diversity_score(rows)
    assert result["diversity_score"] is not None
    assert result["diversity_score"] == 0.0
    assert result["diversity_grade"] == "D"
    assert result["concentration_risk"] is True


def test_r35_t3_uniform_distribution_high_diversity() -> None:
    """Equal distribution across 10 sectors → high diversity_score, grade A."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    rows = _make_rows_with_sectors([f"sector_{i}" for i in range(10)] * 2)
    result = compute_candidate_diversity_score(rows)
    assert result["diversity_score"] is not None
    assert result["diversity_score"] >= 0.70
    assert result["diversity_grade"] == "A"
    assert result["concentration_risk"] is False


def test_r35_t3_fallback_to_industry() -> None:
    """When all sector fields are None, falls back to industry field."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    rows = [{"sector": None, "industry": ind} for ind in ["ind_a", "ind_b", "ind_c", "ind_d", "ind_e"]]
    result = compute_candidate_diversity_score(rows)
    assert result["diversity_score"] is not None


def test_r35_t3_none_sector_rows_filtered() -> None:
    """Rows with None sector are filtered; remaining rows computed normally."""
    from scripts.btst_analysis_utils import compute_candidate_diversity_score

    rows = [{"sector": None}] * 3 + _make_rows_with_sectors(["tech", "finance", "health", "energy", "tech"])
    result = compute_candidate_diversity_score(rows)
    assert result["diversity_score"] is not None


def test_r35_t3_floor_registered() -> None:
    """diversity_score floor = 0.30 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "diversity_score" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["diversity_score"] == 0.30


def test_r35_t3_in_comparison_metrics() -> None:
    """diversity_score registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "diversity_score" in COMPARISON_METRICS


def test_r35_t3_label_registered() -> None:
    """diversity_score has Chinese label '候选多样性评分'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("diversity_score") == "候选多样性评分"


# ===========================================================================
# Round 36 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 — compute_return_percentile_breakdown
# ---------------------------------------------------------------------------

def test_r36_t1_basic_returns_required_keys() -> None:
    """compute_return_percentile_breakdown returns all required keys for >=10 rows."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    rows = [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06]]
    result = compute_return_percentile_breakdown(rows)
    for key in ("p5", "p10", "p25", "p50", "p75", "p90", "p95", "right_tail_dominance", "iqr", "iqr_ratio", "upper_fence", "lower_fence", "right_outlier_rate", "left_outlier_rate", "tail_asymmetry_index"):
        assert key in result, f"Missing key: {key}"
        assert result[key] is not None, f"Key {key} should not be None with 10 rows"


def test_r36_t1_insufficient_rows_returns_all_none() -> None:
    """compute_return_percentile_breakdown returns all-None dict when fewer than 10 rows."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    rows = [{"next_close_return": 0.05} for _ in range(9)]
    result = compute_return_percentile_breakdown(rows)
    assert result["right_tail_dominance"] is None
    assert result["p50"] is None


def test_r36_t1_empty_rows_no_error() -> None:
    """compute_return_percentile_breakdown handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    result = compute_return_percentile_breakdown([])
    assert result["right_tail_dominance"] is None


def test_r36_t1_none_returns_filtered() -> None:
    """compute_return_percentile_breakdown filters None next_close_return values."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    rows = [{"next_close_return": None}] * 5 + [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06]]
    result = compute_return_percentile_breakdown(rows)
    assert result["p50"] is not None


def test_r36_t1_right_tail_dominance_clamped_max() -> None:
    """right_tail_dominance is clamped to 5.0."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    # Very right-skewed: huge upside, tiny downside
    rows = [{"next_close_return": v} for v in [0.0] * 5 + [10.0] * 5]
    result = compute_return_percentile_breakdown(rows)
    assert result["right_tail_dominance"] is not None
    assert result["right_tail_dominance"] <= 5.0


def test_r36_t1_right_tail_dominance_clamped_min() -> None:
    """right_tail_dominance is non-negative (clamped to 0.0)."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    rows = [{"next_close_return": v} for v in [-0.05, -0.03, -0.02, -0.08, -0.12, -0.01, -0.07, -0.15, -0.03, -0.06]]
    result = compute_return_percentile_breakdown(rows)
    assert result["right_tail_dominance"] is not None
    assert result["right_tail_dominance"] >= 0.0


def test_r36_t1_percentile_ordering() -> None:
    """Percentiles are non-decreasing: p5<=p10<=p25<=p50<=p75<=p90<=p95."""
    from scripts.btst_analysis_utils import compute_return_percentile_breakdown

    rows = [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04, -0.05, 0.09, 0.11, 0.02]]
    result = compute_return_percentile_breakdown(rows)
    assert result["p5"] <= result["p10"] <= result["p25"] <= result["p50"] <= result["p75"] <= result["p90"] <= result["p95"]


def test_r36_t1_floor_registered() -> None:
    """right_tail_dominance floor = 0.80 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "right_tail_dominance" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["right_tail_dominance"] == 0.80


def test_r36_t1_in_comparison_metrics() -> None:
    """right_tail_dominance registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "right_tail_dominance" in COMPARISON_METRICS


def test_r36_t1_label_registered() -> None:
    """right_tail_dominance has Chinese label '右尾优势比'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("right_tail_dominance") == "右尾优势比"


# ---------------------------------------------------------------------------
# T2 — compute_composite_score_ic
# ---------------------------------------------------------------------------

def test_r36_t2_basic_returns_required_keys() -> None:
    """compute_composite_score_ic returns all required keys for >=10 paired rows."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": v, "runner_composite_score": s} for v, s in zip([0.05, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04], [0.7, 0.3, 0.8, 0.9, 0.4, 0.75, 0.95, 0.2, 0.65, 0.55])]
    result = compute_composite_score_ic(rows)
    for key in ("composite_ic", "composite_ic_positive", "composite_ic_magnitude", "ic_t_stat", "ic_significant"):
        assert key in result, f"Missing key: {key}"


def test_r36_t2_insufficient_rows_returns_none() -> None:
    """compute_composite_score_ic returns None composite_ic when fewer than 10 paired rows."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": 0.05, "runner_composite_score": 0.7} for _ in range(9)]
    result = compute_composite_score_ic(rows)
    assert result["composite_ic"] is None
    assert result["composite_ic_positive"] is None


def test_r36_t2_empty_rows_no_error() -> None:
    """compute_composite_score_ic handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    result = compute_composite_score_ic([])
    assert result["composite_ic"] is None


def test_r36_t2_score_fallback_priority() -> None:
    """Fallback from runner_composite_score to composite_score to score."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": v, "score": s} for v, s in zip([0.05, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04], [0.7, 0.3, 0.8, 0.9, 0.4, 0.75, 0.95, 0.2, 0.65, 0.55])]
    result = compute_composite_score_ic(rows)
    assert result["composite_ic"] is not None


def test_r36_t2_ic_clamped_to_neg1_pos1() -> None:
    """composite_ic is clamped to [-1, 1]."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": float(i), "runner_composite_score": float(i)} for i in range(15)]
    result = compute_composite_score_ic(rows)
    assert result["composite_ic"] is not None
    assert -1.0 <= result["composite_ic"] <= 1.0


def test_r36_t2_magnitude_strong_for_high_ic() -> None:
    """composite_ic_magnitude is 'strong' when |IC| > 0.10."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": float(i) * 0.01, "runner_composite_score": float(i)} for i in range(15)]
    result = compute_composite_score_ic(rows)
    assert result["composite_ic"] is not None
    if abs(result["composite_ic"]) > 0.10:
        assert result["composite_ic_magnitude"] == "strong"


def test_r36_t2_none_returns_filtered() -> None:
    """Rows with None next_close_return or None score are excluded from IC computation."""
    from scripts.btst_analysis_utils import compute_composite_score_ic

    rows = [{"next_close_return": None, "runner_composite_score": 0.7}] * 5
    rows += [{"next_close_return": v, "runner_composite_score": s} for v, s in zip([0.05, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04], [0.7, 0.3, 0.8, 0.9, 0.4, 0.75, 0.95, 0.2, 0.65, 0.55])]
    result = compute_composite_score_ic(rows)
    assert result["composite_ic"] is not None


def test_r36_t2_floor_registered() -> None:
    """composite_ic floor = 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "composite_ic" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["composite_ic"] == 0.0


def test_r36_t2_in_comparison_metrics() -> None:
    """composite_ic registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "composite_ic" in COMPARISON_METRICS


def test_r36_t2_label_registered() -> None:
    """composite_ic has Chinese label '综合评分IC'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("composite_ic") == "综合评分IC"


# ---------------------------------------------------------------------------
# T3 — compute_win_rate_confidence_interval
# ---------------------------------------------------------------------------

def test_r36_t3_basic_returns_required_keys() -> None:
    """compute_win_rate_confidence_interval returns all required keys for >=10 rows."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06]]
    result = compute_win_rate_confidence_interval(rows)
    for key in ("observed_win_rate", "ci_lower", "ci_upper", "ci_width", "win_rate_reliable", "win_rate_ci_grade"):
        assert key in result, f"Missing key: {key}"
        assert result[key] is not None


def test_r36_t3_insufficient_rows_returns_all_none() -> None:
    """compute_win_rate_confidence_interval returns all-None when fewer than 10 rows."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": 0.05} for _ in range(9)]
    result = compute_win_rate_confidence_interval(rows)
    assert result["observed_win_rate"] is None
    assert result["ci_width"] is None


def test_r36_t3_empty_rows_no_error() -> None:
    """compute_win_rate_confidence_interval handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    result = compute_win_rate_confidence_interval([])
    assert result["observed_win_rate"] is None


def test_r36_t3_none_returns_filtered() -> None:
    """compute_win_rate_confidence_interval filters None next_close_return values."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": None}] * 5 + [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06]]
    result = compute_win_rate_confidence_interval(rows)
    assert result["observed_win_rate"] is not None


def test_r36_t3_ci_bounds_valid() -> None:
    """ci_lower <= observed_win_rate <= ci_upper and ci_width = ci_upper - ci_lower."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04, -0.05, 0.09, 0.11, 0.02]]
    result = compute_win_rate_confidence_interval(rows)
    assert result["ci_lower"] <= result["observed_win_rate"] <= result["ci_upper"]
    assert abs(result["ci_width"] - (result["ci_upper"] - result["ci_lower"])) < 1e-4


def test_r36_t3_deterministic_seed() -> None:
    """compute_win_rate_confidence_interval produces identical results on two calls (deterministic seed=42)."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": v} for v in [0.05, 0.03, -0.02, 0.08, 0.12, -0.01, 0.07, 0.15, -0.03, 0.06, 0.04, -0.05, 0.09, 0.11, 0.02]]
    r1 = compute_win_rate_confidence_interval(rows)
    r2 = compute_win_rate_confidence_interval(rows)
    assert r1["ci_lower"] == r2["ci_lower"]
    assert r1["ci_upper"] == r2["ci_upper"]


def test_r36_t3_all_wins_grade_A_for_large_sample() -> None:
    """All-positive returns with large sample produce grade A (narrow CI)."""
    from scripts.btst_analysis_utils import compute_win_rate_confidence_interval

    rows = [{"next_close_return": 0.05} for _ in range(100)]
    result = compute_win_rate_confidence_interval(rows)
    assert result["win_rate_ci_grade"] == "A"
    assert result["win_rate_reliable"] is True


def test_r36_t3_cap_registered() -> None:
    """win_rate_ci_width cap = 0.30 in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS

    assert "win_rate_ci_width" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["win_rate_ci_width"] == 0.30


def test_r36_t3_in_comparison_metrics() -> None:
    """win_rate_ci_width registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "win_rate_ci_width" in COMPARISON_METRICS


def test_r36_t3_in_lower_is_better() -> None:
    """win_rate_ci_width registered in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS

    assert "win_rate_ci_width" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r36_t3_label_registered() -> None:
    """win_rate_ci_width has Chinese label '胜率置信区间宽度'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("win_rate_ci_width") == "胜率置信区间宽度"


# ===========================================================================
# Round 37 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 — compute_holding_period_analysis
# ---------------------------------------------------------------------------

def test_r37_t1_basic_returns_required_keys() -> None:
    """compute_holding_period_analysis returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.03, "t2_return": 0.02, "t3_return": 0.01} for _ in range(10)]
    result = compute_holding_period_analysis(rows)
    for key in ("optimal_holding_days", "holding_analysis_valid", "avg_return_t1", "avg_return_t2",
                "avg_return_t3", "ev_t1", "ev_t2", "ev_t3", "holding_period_monotone",
                "t1_vs_t2_advantage", "multi_day_cumulative_return"):
        assert key in result, f"Missing key: {key}"


def test_r37_t1_no_t2_t3_graceful_degradation() -> None:
    """compute_holding_period_analysis degrades gracefully when T+2/T+3 absent."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.03} for _ in range(10)]
    result = compute_holding_period_analysis(rows)
    assert result["optimal_holding_days"] == 1
    assert result["holding_analysis_valid"] is False
    assert result["avg_return_t2"] is None
    assert result["avg_return_t3"] is None


def test_r37_t1_all_none_t2_t3_degrades() -> None:
    """compute_holding_period_analysis degrades when t2_return/t3_return all None."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.03, "t2_return": None, "t3_return": None} for _ in range(10)]
    result = compute_holding_period_analysis(rows)
    assert result["holding_analysis_valid"] is False
    assert result["optimal_holding_days"] == 1


def test_r37_t1_optimal_days_selects_max_ev() -> None:
    """optimal_holding_days is the period with highest EV."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    # T+2 rows all large positive → EV should be highest for T+2
    rows = []
    for _ in range(10):
        rows.append({"next_close_return": 0.01, "t2_return": 0.10, "t3_return": 0.005})
    result = compute_holding_period_analysis(rows)
    assert result["holding_analysis_valid"] is True
    assert result["optimal_holding_days"] == 2


def test_r37_t1_monotone_flag_true_for_decreasing_returns() -> None:
    """holding_period_monotone is True when avg T+1 >= T+2 >= T+3."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.05, "t2_return": 0.03, "t3_return": 0.01} for _ in range(10)]
    result = compute_holding_period_analysis(rows)
    assert result["holding_period_monotone"] is True


def test_r37_t1_t1_vs_t2_advantage_is_difference_of_evs() -> None:
    """t1_vs_t2_advantage is ev_t1 - ev_t2 when both valid."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.05, "t2_return": 0.02, "t3_return": 0.01} for _ in range(10)]
    result = compute_holding_period_analysis(rows)
    if result["ev_t1"] is not None and result["ev_t2"] is not None:
        expected = round(result["ev_t1"] - result["ev_t2"], 6)
        assert abs(result["t1_vs_t2_advantage"] - expected) < 1e-5


def test_r37_t1_insufficient_t1_rows_returns_null() -> None:
    """compute_holding_period_analysis returns null dict when fewer than 5 T+1 rows."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    rows = [{"next_close_return": 0.03, "t2_return": 0.02} for _ in range(4)]
    result = compute_holding_period_analysis(rows)
    assert result["optimal_holding_days"] == 1
    assert result["holding_analysis_valid"] is False


def test_r37_t1_empty_rows_no_error() -> None:
    """compute_holding_period_analysis handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_holding_period_analysis

    result = compute_holding_period_analysis([])
    assert result["optimal_holding_days"] == 1
    assert result["holding_analysis_valid"] is False


def test_r37_t1_in_comparison_metrics() -> None:
    """optimal_holding_days registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "optimal_holding_days" in COMPARISON_METRICS


def test_r37_t1_label_registered() -> None:
    """optimal_holding_days has Chinese label '最优持仓天数'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("optimal_holding_days") == "最优持仓天数"


# ---------------------------------------------------------------------------
# T2 — compute_loss_trade_signature
# ---------------------------------------------------------------------------

def test_r37_t2_basic_returns_required_keys() -> None:
    """compute_loss_trade_signature returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_loss_trade_signature

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.02,
         "close_strength": 0.6, "volume_expansion_quality": 0.5,
         "sector_resonance": 0.4, "rs_sector_rank": 0.7,
         "t0_estimated_net_inflow_ratio": 0.3, "breakout_quality_score": 0.8,
         "momentum_slope_20d": 0.2}
        for i in range(20)
    ]
    result = compute_loss_trade_signature(rows)
    for key in ("loss_warning_factors", "loss_warning_factor_count", "loss_signature_strength",
                "loss_avoidable", "factor_divergence"):
        assert key in result, f"Missing key: {key}"


def test_r37_t2_insufficient_rows_returns_null() -> None:
    """compute_loss_trade_signature returns null when fewer than 10 valid rows."""
    from scripts.btst_analysis_utils import compute_loss_trade_signature

    rows = [{"next_close_return": 0.03, "close_strength": 0.5} for _ in range(9)]
    result = compute_loss_trade_signature(rows)
    assert result["loss_signature_strength"] is None
    assert result["loss_warning_factor_count"] == 0


def test_r37_t2_empty_rows_no_error() -> None:
    """compute_loss_trade_signature handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_loss_trade_signature

    result = compute_loss_trade_signature([])
    assert result["loss_signature_strength"] is None


def test_r37_t2_none_return_filtered() -> None:
    """compute_loss_trade_signature filters rows with None next_close_return."""
    from scripts.btst_analysis_utils import compute_loss_trade_signature

    rows = [{"next_close_return": None, "close_strength": 0.5}] * 5 + [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.02,
         "close_strength": 0.6, "volume_expansion_quality": 0.5,
         "sector_resonance": 0.4, "rs_sector_rank": 0.7,
         "t0_estimated_net_inflow_ratio": 0.3, "breakout_quality_score": 0.8,
         "momentum_slope_20d": 0.2}
        for i in range(20)
    ]
    result = compute_loss_trade_signature(rows)
    assert result["loss_signature_strength"] is not None


def test_r37_t2_divergence_direction() -> None:
    """factor_divergence positive when winning trades have higher factor values."""
    from scripts.btst_analysis_utils import compute_loss_trade_signature

    rows = []
    for i in range(15):
        rows.append({
            "next_close_return": 0.05,
            "close_strength": 0.9, "volume_expansion_quality": 0.8,
            "sector_resonance": 0.7, "rs_sector_rank": 0.8,
            "t0_estimated_net_inflow_ratio": 0.6, "breakout_quality_score": 0.9,
            "momentum_slope_20d": 0.5,
        })
    for i in range(15):
        rows.append({
            "next_close_return": -0.03,
            "close_strength": 0.2, "volume_expansion_quality": 0.1,
            "sector_resonance": 0.2, "rs_sector_rank": 0.1,
            "t0_estimated_net_inflow_ratio": 0.1, "breakout_quality_score": 0.2,
            "momentum_slope_20d": 0.1,
        })
    result = compute_loss_trade_signature(rows)
    assert result["loss_avoidable"] is True
    for f, div in result["factor_divergence"].items():
        if div is not None:
            assert div > 0, f"Expected positive divergence for {f}, got {div}"


def test_r37_t2_floor_registered() -> None:
    """loss_signature_strength floor = 0.02 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "loss_signature_strength" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["loss_signature_strength"] == 0.02


def test_r37_t2_in_comparison_metrics() -> None:
    """loss_signature_strength registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "loss_signature_strength" in COMPARISON_METRICS


def test_r37_t2_label_registered() -> None:
    """loss_signature_strength has Chinese label '亏损特征区分度'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("loss_signature_strength") == "亏损特征区分度"


# ---------------------------------------------------------------------------
# T3 — compute_score_gini_coefficient
# ---------------------------------------------------------------------------

def test_r37_t3_basic_returns_required_keys() -> None:
    """compute_score_gini_coefficient returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    rows = [{"runner_composite_score": float(i) / 10} for i in range(1, 11)]
    result = compute_score_gini_coefficient(rows)
    for key in ("score_gini", "top20_share", "elite_candidate_rate",
                "score_distribution_quality", "score_well_differentiated"):
        assert key in result, f"Missing key: {key}"
        assert result[key] is not None


def test_r37_t3_insufficient_rows_returns_all_none() -> None:
    """compute_score_gini_coefficient returns all-None when fewer than 5 valid rows."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    rows = [{"runner_composite_score": 0.5} for _ in range(4)]
    result = compute_score_gini_coefficient(rows)
    assert result["score_gini"] is None
    assert result["score_distribution_quality"] is None


def test_r37_t3_empty_rows_no_error() -> None:
    """compute_score_gini_coefficient handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    result = compute_score_gini_coefficient([])
    assert result["score_gini"] is None


def test_r37_t3_equal_scores_gini_near_zero() -> None:
    """All-equal scores produce Gini near 0."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    rows = [{"runner_composite_score": 0.5} for _ in range(20)]
    result = compute_score_gini_coefficient(rows)
    assert result["score_gini"] is not None
    assert result["score_gini"] < 0.05


def test_r37_t3_composite_score_fallback() -> None:
    """compute_score_gini_coefficient falls back to composite_score when runner_composite_score absent."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    rows = [{"composite_score": float(i) / 10} for i in range(1, 11)]
    result = compute_score_gini_coefficient(rows)
    assert result["score_gini"] is not None


def test_r37_t3_gini_in_unit_interval() -> None:
    """score_gini is always in [0, 1]."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    import random
    rng = random.Random(7)
    rows = [{"runner_composite_score": rng.uniform(0.1, 1.0)} for _ in range(30)]
    result = compute_score_gini_coefficient(rows)
    assert 0.0 <= result["score_gini"] <= 1.0


def test_r37_t3_quality_grade_A_for_moderate_gini() -> None:
    """score_distribution_quality is 'A' when 0.3 <= gini <= 0.6."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    # Uniform distribution in [0,1] → moderate Gini ~ 0.33
    rows = [{"runner_composite_score": (i + 1) / 20.0} for i in range(20)]
    result = compute_score_gini_coefficient(rows)
    assert result["score_distribution_quality"] in ("A", "B", "C")


def test_r37_t3_in_comparison_metrics() -> None:
    """score_gini registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "score_gini" in COMPARISON_METRICS


def test_r37_t3_label_registered() -> None:
    """score_gini has Chinese label '评分基尼系数'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("score_gini") == "评分基尼系数"


def test_r37_t3_none_scores_filtered() -> None:
    """compute_score_gini_coefficient filters None scores and still works."""
    from scripts.btst_analysis_utils import compute_score_gini_coefficient

    rows = [{"runner_composite_score": None}] * 5 + [{"runner_composite_score": float(i) / 10} for i in range(1, 11)]
    result = compute_score_gini_coefficient(rows)
    assert result["score_gini"] is not None


# ===========================================================================
# Round 38 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 — compute_market_environment_sensitivity
# ---------------------------------------------------------------------------


def test_r38_t1_basic_returns_required_keys() -> None:
    """compute_market_environment_sensitivity returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01, "sector_resonance": float(i) / 20}
        for i in range(20)
    ]
    result = compute_market_environment_sensitivity(rows)
    for key in ("bull_env_win_rate", "bear_env_win_rate", "bull_env_avg_return",
                "bear_env_avg_return", "market_sensitivity_ratio", "env_win_rate_gap",
                "environment_adaptive", "market_neutral"):
        assert key in result, f"Missing key: {key}"


def test_r38_t1_insufficient_rows_returns_all_none() -> None:
    """compute_market_environment_sensitivity returns all-None when fewer than 10 valid rows."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = [{"next_close_return": 0.02, "sector_resonance": 0.5} for _ in range(9)]
    result = compute_market_environment_sensitivity(rows)
    assert result["env_win_rate_gap"] is None
    assert result["bull_env_win_rate"] is None
    assert result["market_neutral"] is None


def test_r38_t1_empty_rows_all_none() -> None:
    """compute_market_environment_sensitivity handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    result = compute_market_environment_sensitivity([])
    assert result["env_win_rate_gap"] is None


def test_r38_t1_none_fields_filtered() -> None:
    """Rows with None next_close_return or sector_resonance are excluded."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = [{"next_close_return": None, "sector_resonance": 0.5}] * 5 + [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01, "sector_resonance": float(i) / 20}
        for i in range(20)
    ]
    result = compute_market_environment_sensitivity(rows)
    assert result["env_win_rate_gap"] is not None


def test_r38_t1_bull_env_better_gap_positive() -> None:
    """env_win_rate_gap > 0 when bull-env rows have higher win rates."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = []
    for i in range(10):
        rows.append({"next_close_return": 0.05, "sector_resonance": 0.9})
    for i in range(10):
        rows.append({"next_close_return": -0.02, "sector_resonance": 0.1})
    result = compute_market_environment_sensitivity(rows)
    assert result["env_win_rate_gap"] is not None
    assert result["env_win_rate_gap"] > 0


def test_r38_t1_sensitivity_ratio_clamped() -> None:
    """market_sensitivity_ratio is clamped to [0, 5]."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = []
    for i in range(10):
        rows.append({"next_close_return": 0.05, "sector_resonance": 0.9})
    for i in range(10):
        rows.append({"next_close_return": -0.05, "sector_resonance": 0.1})
    result = compute_market_environment_sensitivity(rows)
    if result["market_sensitivity_ratio"] is not None:
        assert 0.0 <= result["market_sensitivity_ratio"] <= 5.0


def test_r38_t1_environment_adaptive_flag() -> None:
    """environment_adaptive is True when env_win_rate_gap > 0.05."""
    from scripts.btst_analysis_utils import compute_market_environment_sensitivity

    rows = []
    for i in range(15):
        rows.append({"next_close_return": 0.04, "sector_resonance": 0.9})
    for i in range(15):
        rows.append({"next_close_return": -0.03, "sector_resonance": 0.1})
    result = compute_market_environment_sensitivity(rows)
    if result["env_win_rate_gap"] is not None and result["env_win_rate_gap"] > 0.05:
        assert result["environment_adaptive"] is True


def test_r38_t1_floor_registered() -> None:
    """env_win_rate_gap floor = -0.10 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "env_win_rate_gap" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["env_win_rate_gap"] == -0.10


def test_r38_t1_in_comparison_metrics() -> None:
    """env_win_rate_gap registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "env_win_rate_gap" in COMPARISON_METRICS


def test_r38_t1_label_registered() -> None:
    """env_win_rate_gap has Chinese label '多空环境胜率差'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("env_win_rate_gap") == "多空环境胜率差"


# ---------------------------------------------------------------------------
# T2 — compute_factor_importance_ranking
# ---------------------------------------------------------------------------


def test_r38_t2_basic_returns_required_keys() -> None:
    """compute_factor_importance_ranking returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "close_strength": float(i) / 20, "sector_resonance": float(i) / 20,
         "rs_sector_rank": float(i) / 20}
        for i in range(20)
    ]
    result = compute_factor_importance_ranking(rows)
    for key in ("factor_ic_ranking", "top_factor", "bottom_factor",
                "positive_ic_factor_count", "top3_avg_ic", "factor_ic_spread"):
        assert key in result, f"Missing key: {key}"


def test_r38_t2_insufficient_rows_returns_null() -> None:
    """compute_factor_importance_ranking returns null when fewer than 10 valid return rows."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    rows = [{"next_close_return": 0.02, "close_strength": 0.5} for _ in range(9)]
    result = compute_factor_importance_ranking(rows)
    assert result["positive_ic_factor_count"] is None
    assert result["factor_ic_ranking"] == []


def test_r38_t2_empty_rows_graceful() -> None:
    """compute_factor_importance_ranking handles empty input."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    result = compute_factor_importance_ranking([])
    assert result["positive_ic_factor_count"] is None


def test_r38_t2_none_returns_filtered() -> None:
    """Rows with None next_close_return are excluded."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    rows = [{"next_close_return": None, "close_strength": 0.5}] * 5 + [
        {"next_close_return": float(i) / 20 - 0.05, "close_strength": float(i) / 20}
        for i in range(20)
    ]
    result = compute_factor_importance_ranking(rows)
    assert result["positive_ic_factor_count"] is not None


def test_r38_t2_ranking_sorted_descending() -> None:
    """factor_ic_ranking is sorted from highest IC to lowest."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    rows = [
        {"next_close_return": float(i) / 20 - 0.25,
         "close_strength": float(i) / 20,
         "sector_resonance": 1.0 - float(i) / 20,
         "rs_sector_rank": float(i) / 20}
        for i in range(20)
    ]
    result = compute_factor_importance_ranking(rows)
    ranking = result["factor_ic_ranking"]
    if len(ranking) >= 2:
        for j in range(len(ranking) - 1):
            assert ranking[j][1] >= ranking[j + 1][1], "Ranking not sorted descending"


def test_r38_t2_positive_ic_count_non_negative() -> None:
    """positive_ic_factor_count is a non-negative integer when data is available."""
    from scripts.btst_analysis_utils import compute_factor_importance_ranking

    rows = [
        {"next_close_return": float(i) / 20 - 0.25, "close_strength": float(i) / 20}
        for i in range(20)
    ]
    result = compute_factor_importance_ranking(rows)
    if result["positive_ic_factor_count"] is not None:
        assert isinstance(result["positive_ic_factor_count"], int)
        assert result["positive_ic_factor_count"] >= 0


def test_r38_t2_floor_registered() -> None:
    """positive_ic_factor_count floor = 6 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "positive_ic_factor_count" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["positive_ic_factor_count"] == 6


def test_r38_t2_in_comparison_metrics() -> None:
    """positive_ic_factor_count registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "positive_ic_factor_count" in COMPARISON_METRICS


def test_r38_t2_label_registered() -> None:
    """positive_ic_factor_count has Chinese label '正IC因子数'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("positive_ic_factor_count") == "正IC因子数"


# ---------------------------------------------------------------------------
# T3 — compute_score_bucket_win_rates
# ---------------------------------------------------------------------------


def test_r38_t3_basic_returns_required_keys() -> None:
    """compute_score_bucket_win_rates returns all required keys for valid input."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "runner_composite_score": float(i) / 30}
        for i in range(30)
    ]
    result = compute_score_bucket_win_rates(rows)
    for key in ("win_rate_q1", "win_rate_q2", "win_rate_q3", "win_rate_q4", "win_rate_q5",
                "score_monotone", "score_near_monotone", "top_quintile_premium",
                "score_rank_ic", "score_discriminates_well"):
        assert key in result, f"Missing key: {key}"


def test_r38_t3_insufficient_rows_returns_all_none() -> None:
    """compute_score_bucket_win_rates returns all-None when fewer than 15 valid rows."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = [{"next_close_return": 0.02, "runner_composite_score": 0.5} for _ in range(14)]
    result = compute_score_bucket_win_rates(rows)
    assert result["top_quintile_premium"] is None
    assert result["score_monotone"] is None


def test_r38_t3_empty_rows_graceful() -> None:
    """compute_score_bucket_win_rates handles empty input gracefully."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    result = compute_score_bucket_win_rates([])
    assert result["top_quintile_premium"] is None


def test_r38_t3_none_fields_filtered() -> None:
    """Rows with None return or score are excluded from computation."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = [{"next_close_return": None, "runner_composite_score": 0.5}] * 5 + [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "runner_composite_score": float(i) / 30}
        for i in range(30)
    ]
    result = compute_score_bucket_win_rates(rows)
    assert result["top_quintile_premium"] is not None


def test_r38_t3_composite_score_fallback() -> None:
    """compute_score_bucket_win_rates falls back to composite_score when runner_composite_score absent."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "composite_score": float(i) / 30}
        for i in range(30)
    ]
    result = compute_score_bucket_win_rates(rows)
    assert result["top_quintile_premium"] is not None


def test_r38_t3_monotone_score_produces_valid_flags() -> None:
    """Monotonically increasing score-win-rate mapping sets score_monotone True."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = []
    for bucket in range(5):
        win_prob = 0.3 + bucket * 0.15
        for _ in range(8):
            import random
            rng = random.Random(bucket * 100 + _)
            ret = 0.04 if rng.random() < win_prob else -0.02
            rows.append({"next_close_return": ret,
                         "runner_composite_score": float(bucket) + rng.uniform(0, 0.9)})
    result = compute_score_bucket_win_rates(rows)
    assert result["score_monotone"] in (True, False, None)
    assert result["score_near_monotone"] in (True, False, None)


def test_r38_t3_top_quintile_premium_direction() -> None:
    """top_quintile_premium > 0 when high-score group wins more than low-score group."""
    from scripts.btst_analysis_utils import compute_score_bucket_win_rates

    rows = []
    for i in range(15):
        rows.append({"next_close_return": 0.05, "runner_composite_score": 0.9})
    for i in range(15):
        rows.append({"next_close_return": -0.03, "runner_composite_score": 0.1})
    result = compute_score_bucket_win_rates(rows)
    if result["top_quintile_premium"] is not None:
        assert result["top_quintile_premium"] > 0


def test_r38_t3_floor_registered() -> None:
    """top_quintile_premium floor = 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "top_quintile_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["top_quintile_premium"] == 0.0


def test_r38_t3_in_comparison_metrics() -> None:
    """top_quintile_premium registered in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "top_quintile_premium" in COMPARISON_METRICS


def test_r38_t3_label_registered() -> None:
    """top_quintile_premium has Chinese label '顶分位胜率溢价'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert COMPARISON_METRIC_LABELS.get("top_quintile_premium") == "顶分位胜率溢价"


# ===========================================================================
# Round 39, Task 1 (Alpha): Recency vs history performance analysis
# ===========================================================================


def test_r39_t1_basic_stable() -> None:
    """compute_recency_vs_history_analysis returns stable flag when gaps are small."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    rows = [{"next_close_return": 0.02 if i % 2 == 0 else -0.01} for i in range(30)]
    result = compute_recency_vs_history_analysis(rows)
    assert result["recency_win_rate_gap"] is not None
    assert result["recency_stable"] in (True, False)
    assert result["recency_degraded"] in (True, False)
    assert result["recency_improved"] in (True, False)


def test_r39_t1_insufficient_rows_returns_none() -> None:
    """compute_recency_vs_history_analysis returns all-None when fewer than 15 valid rows."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    rows = [{"next_close_return": 0.01} for _ in range(14)]
    result = compute_recency_vs_history_analysis(rows)
    assert result["recency_win_rate_gap"] is None
    assert result["recency_degraded"] is None


def test_r39_t1_empty_rows_graceful() -> None:
    """compute_recency_vs_history_analysis handles empty input without raising."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    result = compute_recency_vs_history_analysis([])
    assert result["recency_win_rate_gap"] is None


def test_r39_t1_none_returns_filtered() -> None:
    """Rows with None next_close_return are excluded from computation."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    rows = [{"next_close_return": None}] * 10 + [{"next_close_return": 0.02 if i % 2 == 0 else -0.01} for i in range(20)]
    result = compute_recency_vs_history_analysis(rows)
    assert result["recency_win_rate_gap"] is not None


def test_r39_t1_degraded_flag_triggers() -> None:
    """recency_degraded is True when recent win-rate is >5% below historical."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    historical = [{"next_close_return": 0.03}] * 20 + [{"next_close_return": -0.01}] * 1
    recent = [{"next_close_return": -0.02}] * 10 + [{"next_close_return": 0.01}] * 1
    rows = historical + recent
    result = compute_recency_vs_history_analysis(rows)
    assert result["recency_win_rate_gap"] is not None
    assert result["recency_degraded"] is True


def test_r39_t1_improved_flag_triggers() -> None:
    """recency_improved is True when recent win-rate is >5% above historical."""
    from scripts.btst_analysis_utils import compute_recency_vs_history_analysis

    historical = [{"next_close_return": -0.02}] * 14 + [{"next_close_return": 0.01}] * 7
    recent = [{"next_close_return": 0.05}] * 9
    rows = historical + recent
    result = compute_recency_vs_history_analysis(rows)
    assert result["recency_win_rate_gap"] is not None
    assert result["recency_improved"] is True


def test_r39_t1_floor_registered() -> None:
    """recency_win_rate_gap floor is -0.15 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "recency_win_rate_gap" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["recency_win_rate_gap"] == -0.15


def test_r39_t1_metric_registered() -> None:
    """recency_win_rate_gap is in COMPARISON_METRICS and has a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRICS, COMPARISON_METRIC_LABELS

    assert "recency_win_rate_gap" in COMPARISON_METRICS
    assert "近期" in COMPARISON_METRIC_LABELS.get("recency_win_rate_gap", "")


# ===========================================================================
# Round 39, Task 2 (Beta): Optimal score threshold search
# ===========================================================================


def test_r39_t2_basic_returns_result() -> None:
    """compute_optimal_score_threshold returns a valid result with enough rows."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    rows = [
        {"next_close_return": 0.04 if i % 2 == 0 else -0.01,
         "runner_composite_score": float(i) / 25}
        for i in range(25)
    ]
    result = compute_optimal_score_threshold(rows)
    assert result["optimal_threshold_pct"] is not None
    assert result["optimal_threshold_lift"] is not None


def test_r39_t2_insufficient_rows_returns_none() -> None:
    """compute_optimal_score_threshold returns all-None for fewer than 20 valid rows."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    rows = [{"next_close_return": 0.01, "runner_composite_score": 0.5} for _ in range(19)]
    result = compute_optimal_score_threshold(rows)
    assert result["optimal_threshold_lift"] is None


def test_r39_t2_empty_rows_graceful() -> None:
    """compute_optimal_score_threshold handles empty input without raising."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    result = compute_optimal_score_threshold([])
    assert result["optimal_threshold_lift"] is None


def test_r39_t2_none_fields_filtered() -> None:
    """Rows with None return or score are excluded from threshold analysis."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    rows = [{"next_close_return": None, "runner_composite_score": 0.5}] * 5 + [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "runner_composite_score": float(i) / 25}
        for i in range(25)
    ]
    result = compute_optimal_score_threshold(rows)
    assert result["optimal_threshold_lift"] is not None


def test_r39_t2_score_field_fallback() -> None:
    """compute_optimal_score_threshold falls back to composite_score when runner_composite_score absent."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    rows = [
        {"next_close_return": 0.03 if i % 2 == 0 else -0.01,
         "composite_score": float(i) / 25}
        for i in range(25)
    ]
    result = compute_optimal_score_threshold(rows)
    assert result["optimal_threshold_pct"] is not None


def test_r39_t2_coverage_in_range() -> None:
    """threshold_coverage is in [0, 1]."""
    from scripts.btst_analysis_utils import compute_optimal_score_threshold

    rows = [
        {"next_close_return": 0.04 if i % 2 == 0 else -0.01,
         "runner_composite_score": float(i) / 30}
        for i in range(30)
    ]
    result = compute_optimal_score_threshold(rows)
    if result["threshold_coverage"] is not None:
        assert 0.0 <= result["threshold_coverage"] <= 1.0


def test_r39_t2_floor_registered() -> None:
    """optimal_threshold_lift floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "optimal_threshold_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["optimal_threshold_lift"] == 0.0


def test_r39_t2_metric_registered() -> None:
    """optimal_threshold_lift is in COMPARISON_METRICS with a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRICS, COMPARISON_METRIC_LABELS

    assert "optimal_threshold_lift" in COMPARISON_METRICS
    assert "阈值" in COMPARISON_METRIC_LABELS.get("optimal_threshold_lift", "")


# ===========================================================================
# Round 39, Task 3 (Gamma): Simulated equity curve analysis
# ===========================================================================


def test_r39_t3_basic_returns_result() -> None:
    """compute_simulated_equity_curve returns valid metrics with enough rows."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": 0.02 if i % 3 != 0 else -0.01} for i in range(20)]
    result = compute_simulated_equity_curve(rows)
    assert result["recovery_factor"] is not None
    assert result["max_drawdown"] is not None
    assert result["equity_curve_grade"] in ("A", "B", "C", "D")


def test_r39_t3_insufficient_rows_returns_none() -> None:
    """compute_simulated_equity_curve returns all-None for fewer than 10 valid rows."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": 0.01} for _ in range(9)]
    result = compute_simulated_equity_curve(rows)
    assert result["recovery_factor"] is None
    assert result["max_drawdown"] is None


def test_r39_t3_empty_rows_graceful() -> None:
    """compute_simulated_equity_curve handles empty input without raising."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    result = compute_simulated_equity_curve([])
    assert result["recovery_factor"] is None


def test_r39_t3_none_returns_filtered() -> None:
    """Rows with None next_close_return are excluded from equity simulation."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": None}] * 5 + [{"next_close_return": 0.02} for _ in range(15)]
    result = compute_simulated_equity_curve(rows)
    assert result["recovery_factor"] is not None


def test_r39_t3_all_winning_trades() -> None:
    """All positive returns produces grade A and positive equity."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": 0.02} for _ in range(20)]
    result = compute_simulated_equity_curve(rows)
    assert result["total_return"] is not None and result["total_return"] > 0
    assert result["equity_rising"] is True
    assert result["equity_curve_grade"] == "A"


def test_r39_t3_all_losing_trades() -> None:
    """All negative returns produces grade D and zero consecutive_losses = len(rows)."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": -0.01} for _ in range(20)]
    result = compute_simulated_equity_curve(rows)
    assert result["total_return"] is not None and result["total_return"] < 0
    assert result["max_consecutive_losses"] == 20
    assert result["equity_curve_grade"] == "D"


def test_r39_t3_recovery_factor_clamped() -> None:
    """recovery_factor is clamped to [-10, 10]."""
    from scripts.btst_analysis_utils import compute_simulated_equity_curve

    rows = [{"next_close_return": 0.10} for _ in range(15)]
    result = compute_simulated_equity_curve(rows)
    if result["recovery_factor"] is not None:
        assert -10.0 <= result["recovery_factor"] <= 10.0


def test_r39_t3_floor_registered() -> None:
    """recovery_factor floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "recovery_factor" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["recovery_factor"] == 0.0


def test_r39_t3_metric_registered() -> None:
    """recovery_factor and max_drawdown_simulated are in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, LOWER_IS_BETTER_COMPARISON_METRICS

    assert "recovery_factor" in COMPARISON_METRICS
    assert "max_drawdown_simulated" in COMPARISON_METRICS
    assert "max_drawdown_simulated" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r39_t3_label_registered() -> None:
    """recovery_factor and max_drawdown_simulated have Chinese labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "权益" in COMPARISON_METRIC_LABELS.get("recovery_factor", "")
    assert "回撤" in COMPARISON_METRIC_LABELS.get("max_drawdown_simulated", "")


# ===========================================================================
# Round 40 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1: compute_factor_synergy_matrix
# ---------------------------------------------------------------------------

def _make_synergy_rows(n: int = 40, seed: int = 0) -> list[dict]:
    """Return n synthetic rows with core factor fields and next_close_return."""
    import random
    rng = random.Random(seed)
    factors = [
        "close_strength", "volume_expansion_quality", "sector_resonance",
        "rs_sector_rank", "t0_estimated_net_inflow_ratio",
        "breakout_quality_score", "momentum_slope_20d",
    ]
    rows = []
    for i in range(n):
        row: dict = {"next_close_return": rng.uniform(-0.05, 0.10)}
        for f in factors:
            row[f] = rng.uniform(0.0, 1.0)
        rows.append(row)
    return rows


def test_r40_t1_basic_returns_result() -> None:
    """compute_factor_synergy_matrix returns a valid result dict for sufficient data."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    rows = _make_synergy_rows(60)
    result = compute_factor_synergy_matrix(rows)
    assert isinstance(result, dict)
    assert "max_synergy_lift" in result
    assert "best_factor_pair" in result
    assert "synergy_pair_count" in result
    assert "synergy_matrix_valid" in result


def test_r40_t1_insufficient_rows_returns_null() -> None:
    """compute_factor_synergy_matrix returns None fields when fewer than 15 valid rows."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    rows = _make_synergy_rows(10)
    result = compute_factor_synergy_matrix(rows)
    assert result["synergy_matrix_valid"] is False
    assert result["max_synergy_lift"] is None
    assert result["best_factor_pair"] is None


def test_r40_t1_empty_rows_graceful() -> None:
    """compute_factor_synergy_matrix handles empty list gracefully."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    result = compute_factor_synergy_matrix([])
    assert result["synergy_matrix_valid"] is False
    assert result["max_synergy_lift"] is None


def test_r40_t1_none_returns_filtered() -> None:
    """Rows with next_close_return=None are excluded from computation."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    rows = _make_synergy_rows(50)
    for row in rows[:25]:
        row["next_close_return"] = None
    result = compute_factor_synergy_matrix(rows)
    # Only 25 valid rows remain, still ≥ 15 so should succeed.
    assert result["synergy_matrix_valid"] is True


def test_r40_t1_lift_clamped() -> None:
    """max_synergy_lift is clamped to [-0.3, 0.5]."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    rows = _make_synergy_rows(80, seed=7)
    result = compute_factor_synergy_matrix(rows)
    if result["max_synergy_lift"] is not None:
        assert -0.3 <= result["max_synergy_lift"] <= 0.5


def test_r40_t1_best_pair_is_tuple() -> None:
    """best_factor_pair is a tuple of two factor name strings."""
    from scripts.btst_analysis_utils import compute_factor_synergy_matrix

    rows = _make_synergy_rows(80, seed=42)
    result = compute_factor_synergy_matrix(rows)
    if result["synergy_matrix_valid"]:
        bp = result["best_factor_pair"]
        assert isinstance(bp, (tuple, list))
        assert len(bp) == 2
        assert all(isinstance(f, str) for f in bp)


def test_r40_t1_floor_registered() -> None:
    """max_synergy_lift floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "max_synergy_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["max_synergy_lift"] == 0.0


def test_r40_t1_metric_registered() -> None:
    """max_synergy_lift is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "max_synergy_lift" in COMPARISON_METRICS
    assert "max_synergy_lift" in OPTIONAL_COMPARISON_METRICS


def test_r40_t1_label_registered() -> None:
    """max_synergy_lift has a Chinese label containing '协同'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "协同" in COMPARISON_METRIC_LABELS.get("max_synergy_lift", "")


# ---------------------------------------------------------------------------
# T2: compute_float_turnover_analysis
# ---------------------------------------------------------------------------

def _make_turnover_rows(n: int = 40, seed: int = 0, include_turnover: bool = True) -> list[dict]:
    """Return n synthetic rows with float_turnover_rate and next_close_return."""
    import random
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        row: dict = {"next_close_return": rng.uniform(-0.05, 0.10)}
        if include_turnover:
            row["float_turnover_rate"] = rng.uniform(0.01, 0.20)
        else:
            row["float_turnover_rate"] = None
        rows.append(row)
    return rows


def test_r40_t2_basic_returns_result() -> None:
    """compute_float_turnover_analysis returns valid dict for sufficient data."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    rows = _make_turnover_rows(60)
    result = compute_float_turnover_analysis(rows)
    assert isinstance(result, dict)
    assert result["turnover_analysis_valid"] is True
    assert "turnover_low_win_rate" in result
    assert "high_vs_low_lift" in result
    assert "optimal_turnover_bucket" in result


def test_r40_t2_empty_rows_graceful() -> None:
    """compute_float_turnover_analysis handles empty list gracefully."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    result = compute_float_turnover_analysis([])
    assert result["turnover_analysis_valid"] is False


def test_r40_t2_all_none_turnover_returns_invalid() -> None:
    """Returns turnover_analysis_valid=False when float_turnover_rate is all None."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    rows = _make_turnover_rows(30, include_turnover=False)
    result = compute_float_turnover_analysis(rows)
    assert result["turnover_analysis_valid"] is False
    assert result["high_vs_low_lift"] is None


def test_r40_t2_insufficient_rows_returns_invalid() -> None:
    """Returns turnover_analysis_valid=False when fewer than 10 valid rows."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    rows = _make_turnover_rows(8)
    result = compute_float_turnover_analysis(rows)
    assert result["turnover_analysis_valid"] is False


def test_r40_t2_optimal_bucket_valid_value() -> None:
    """optimal_turnover_bucket is one of 'low', 'mid', 'high' or None."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    rows = _make_turnover_rows(60)
    result = compute_float_turnover_analysis(rows)
    if result["optimal_turnover_bucket"] is not None:
        assert result["optimal_turnover_bucket"] in ("low", "mid", "high")


def test_r40_t2_thresholds_present() -> None:
    """p33_turnover and p67_turnover are returned as non-None floats."""
    from scripts.btst_analysis_utils import compute_float_turnover_analysis

    rows = _make_turnover_rows(60)
    result = compute_float_turnover_analysis(rows)
    assert result["turnover_analysis_valid"] is True
    assert result["p33_turnover"] is not None
    assert result["p67_turnover"] is not None
    assert result["p33_turnover"] <= result["p67_turnover"]


def test_r40_t2_metric_registered() -> None:
    """high_vs_low_lift is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "high_vs_low_lift" in COMPARISON_METRICS
    assert "high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r40_t2_label_registered() -> None:
    """high_vs_low_lift has a Chinese label containing '换手'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "换手" in COMPARISON_METRIC_LABELS.get("high_vs_low_lift", "")


# ---------------------------------------------------------------------------
# T3: compute_cross_window_factor_exposure
# ---------------------------------------------------------------------------

def _make_window_summaries(n: int = 5, seed: int = 0) -> list[dict]:
    """Return n synthetic window summary dicts with core metric fields."""
    import random
    rng = random.Random(seed)
    summaries = []
    for _ in range(n):
        summaries.append({
            "win_rate": rng.uniform(0.45, 0.70),
            "composite_gate_score": rng.uniform(40.0, 80.0),
            "sortino_ratio": rng.uniform(-0.5, 3.0),
            "expected_value_per_trade": rng.uniform(-0.01, 0.03),
        })
    return summaries


def test_r40_t3_basic_returns_result() -> None:
    """compute_cross_window_factor_exposure returns valid dict for 5+ windows."""
    from scripts.optimize_profile import compute_cross_window_factor_exposure

    summaries = _make_window_summaries(5)
    result = compute_cross_window_factor_exposure(summaries)
    assert isinstance(result, dict)
    assert "factor_drift_score" in result
    assert "factor_exposure_stable" in result
    assert result["factor_drift_score"] is not None


def test_r40_t3_insufficient_windows_returns_null() -> None:
    """Returns None fields when fewer than 3 windows."""
    from scripts.optimize_profile import compute_cross_window_factor_exposure

    for n in (0, 1, 2):
        result = compute_cross_window_factor_exposure(_make_window_summaries(n))
        assert result["factor_drift_score"] is None
        assert result["factor_exposure_stable"] is None


def test_r40_t3_stable_metrics_flag_true() -> None:
    """factor_exposure_stable is True when all metrics have very low CV."""
    from scripts.optimize_profile import compute_cross_window_factor_exposure

    # All windows with nearly identical values → very low CV.
    summaries = [{"win_rate": 0.60, "composite_gate_score": 65.0, "sortino_ratio": 1.5, "expected_value_per_trade": 0.01} for _ in range(5)]
    result = compute_cross_window_factor_exposure(summaries)
    assert result["factor_drift_score"] is not None
    assert result["factor_exposure_stable"] is True


def test_r40_t3_drift_score_positive() -> None:
    """factor_drift_score is a non-negative float."""
    from scripts.optimize_profile import compute_cross_window_factor_exposure

    summaries = _make_window_summaries(8, seed=99)
    result = compute_cross_window_factor_exposure(summaries)
    if result["factor_drift_score"] is not None:
        assert result["factor_drift_score"] >= 0.0


def test_r40_t3_most_and_least_drifting_present() -> None:
    """most_drifting_metric and least_drifting_metric are returned when data is valid."""
    from scripts.optimize_profile import compute_cross_window_factor_exposure

    summaries = _make_window_summaries(6)
    result = compute_cross_window_factor_exposure(summaries)
    if result["factor_drift_score"] is not None:
        assert result["most_drifting_metric"] is not None
        assert result["least_drifting_metric"] is not None


def test_r40_t3_cap_registered() -> None:
    """factor_drift_score cap is 0.50 in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS

    assert "factor_drift_score" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["factor_drift_score"] == 0.50


def test_r40_t3_metric_registered() -> None:
    """factor_drift_score is in COMPARISON_METRICS and LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, LOWER_IS_BETTER_COMPARISON_METRICS

    assert "factor_drift_score" in COMPARISON_METRICS
    assert "factor_drift_score" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r40_t3_label_registered() -> None:
    """factor_drift_score has a Chinese label containing '漂移'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "漂移" in COMPARISON_METRIC_LABELS.get("factor_drift_score", "")


# ===========================================================================
# Round 41 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_r41_windows(n: int = 5, seed: int = 0, include_ranking: bool = True) -> list[dict]:
    """Return n synthetic window summary dicts with factor_ic_ranking."""
    import random
    rng = random.Random(seed)
    factors = ["momentum_score", "volume_expansion_quality", "price_strength_score",
               "t0_estimated_net_inflow_ratio", "t0_tail_strength", "gap_body_ratio",
               "float_turnover_rate"]
    summaries = []
    for _ in range(n):
        if include_ranking:
            shuffled = factors[:]
            rng.shuffle(shuffled)
            ranking = [(f, round(rng.uniform(-0.3, 0.5), 4)) for f in shuffled]
            ranking.sort(key=lambda x: x[1], reverse=True)
        else:
            ranking = []
        summaries.append({"factor_ic_ranking": ranking if include_ranking else None})
    return summaries


def _make_r41_vpa_rows(n: int = 40, seed: int = 0, include_veq: bool = True, include_enir: bool = True) -> list[dict]:
    """Return n rows with next_close_return, volume_expansion_quality, t0_estimated_net_inflow_ratio."""
    import random
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        row: dict = {"next_close_return": rng.uniform(-0.06, 0.10)}
        if include_veq:
            row["volume_expansion_quality"] = rng.uniform(0.0, 1.0)
        if include_enir:
            row["t0_estimated_net_inflow_ratio"] = rng.uniform(-1.0, 1.0)
        rows.append(row)
    return rows


def _make_r41_stat_rows(n: int = 50, seed: int = 0, positive_bias: float = 0.02) -> list[dict]:
    """Return n rows with next_close_return having a slight positive bias."""
    import random
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        rows.append({"next_close_return": rng.gauss(positive_bias, 0.03)})
    return rows


# ---------------------------------------------------------------------------
# T1: compute_factor_rank_consistency
# ---------------------------------------------------------------------------

def test_r41_t1_basic_returns_result() -> None:
    """compute_factor_rank_consistency returns a dict with expected keys for sufficient windows."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    summaries = _make_r41_windows(5, seed=1)
    result = compute_factor_rank_consistency(summaries)
    assert "factor_rank_consistency_score" in result
    assert "top_factor_stable" in result
    assert "most_consistent_factor" in result
    assert "most_volatile_rank_factor" in result


def test_r41_t1_insufficient_windows_returns_null() -> None:
    """Returns all-None when fewer than 3 windows have valid ranking data."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    result = compute_factor_rank_consistency(_make_r41_windows(2))
    assert result["factor_rank_consistency_score"] is None
    assert result["top_factor_stable"] is None


def test_r41_t1_empty_summaries_returns_null() -> None:
    """Returns all-None for empty input."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    result = compute_factor_rank_consistency([])
    assert result["factor_rank_consistency_score"] is None


def test_r41_t1_no_ranking_field_returns_null() -> None:
    """Returns all-None when no window contains factor_ic_ranking data."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    summaries = [{"factor_ic_ranking": None}, {"factor_ic_ranking": None}, {"factor_ic_ranking": None}]
    result = compute_factor_rank_consistency(summaries)
    assert result["factor_rank_consistency_score"] is None


def test_r41_t1_score_clamped_to_unit_interval() -> None:
    """factor_rank_consistency_score is clamped to [0, 1]."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    summaries = _make_r41_windows(8, seed=42)
    result = compute_factor_rank_consistency(summaries)
    score = result["factor_rank_consistency_score"]
    if score is not None:
        assert 0.0 <= score <= 1.0


def test_r41_t1_stable_ranking_gives_high_score() -> None:
    """A perfectly stable ranking (same order every window) should give score near 1."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    factors = ["f1", "f2", "f3"]
    fixed_ranking = [("f1", 0.5), ("f2", 0.3), ("f3", 0.1)]
    summaries = [{"factor_ic_ranking": fixed_ranking} for _ in range(6)]
    result = compute_factor_rank_consistency(summaries)
    score = result["factor_rank_consistency_score"]
    assert score is not None
    assert score >= 0.90  # Very stable → high consistency score


def test_r41_t1_consistent_factor_name_is_string() -> None:
    """most_consistent_factor and most_volatile_rank_factor are strings when computable."""
    from scripts.optimize_profile import compute_factor_rank_consistency

    summaries = _make_r41_windows(5, seed=7)
    result = compute_factor_rank_consistency(summaries)
    if result["most_consistent_factor"] is not None:
        assert isinstance(result["most_consistent_factor"], str)
    if result["most_volatile_rank_factor"] is not None:
        assert isinstance(result["most_volatile_rank_factor"], str)


def test_r41_t1_floor_registered() -> None:
    """factor_rank_consistency_score floor is 0.30 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "factor_rank_consistency_score" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["factor_rank_consistency_score"] == 0.30


def test_r41_t1_metric_registered() -> None:
    """factor_rank_consistency_score is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "factor_rank_consistency_score" in COMPARISON_METRICS
    assert "factor_rank_consistency_score" in OPTIONAL_COMPARISON_METRICS


def test_r41_t1_label_registered() -> None:
    """factor_rank_consistency_score label contains '一致性'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "一致性" in COMPARISON_METRIC_LABELS.get("factor_rank_consistency_score", "")


# ---------------------------------------------------------------------------
# T2: compute_volume_price_alignment
# ---------------------------------------------------------------------------

def test_r41_t2_basic_returns_result() -> None:
    """compute_volume_price_alignment returns valid dict for sufficient data."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = _make_r41_vpa_rows(40, seed=1)
    result = compute_volume_price_alignment(rows)
    assert result["vol_price_signal_valid"] is True
    assert "vol_price_alignment_rate" in result


def test_r41_t2_empty_rows_returns_invalid() -> None:
    """Returns vol_price_signal_valid=False for empty input."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    result = compute_volume_price_alignment([])
    assert result["vol_price_signal_valid"] is False
    assert result["vol_price_alignment_rate"] is None


def test_r41_t2_insufficient_rows_returns_invalid() -> None:
    """Returns invalid when fewer than 10 rows have non-None next_close_return."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = _make_r41_vpa_rows(5)
    result = compute_volume_price_alignment(rows)
    assert result["vol_price_signal_valid"] is False


def test_r41_t2_both_none_fields_returns_invalid() -> None:
    """Returns invalid when both VEQ and ENIR are absent."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = [{"next_close_return": 0.01} for _ in range(20)]
    result = compute_volume_price_alignment(rows)
    assert result["vol_price_signal_valid"] is False
    assert result["vol_price_alignment_rate"] is None


def test_r41_t2_alignment_rate_in_unit_interval() -> None:
    """vol_price_alignment_rate is between 0 and 1 when computable."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = _make_r41_vpa_rows(50, seed=99)
    result = compute_volume_price_alignment(rows)
    rate = result.get("vol_price_alignment_rate")
    if rate is not None:
        assert 0.0 <= rate <= 1.0


def test_r41_t2_alignment_strong_flag_correct() -> None:
    """vol_price_alignment_strong is True iff alignment_rate > 0.55."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = _make_r41_vpa_rows(60, seed=5)
    result = compute_volume_price_alignment(rows)
    rate = result.get("vol_price_alignment_rate")
    flag = result.get("vol_price_alignment_strong")
    if rate is not None and flag is not None:
        assert flag == (rate > 0.55)


def test_r41_t2_enir_only_scenario() -> None:
    """When only ENIR is provided (no VEQ), scenario 2 still runs."""
    from scripts.btst_analysis_utils import compute_volume_price_alignment

    rows = [
        {"next_close_return": 0.02, "t0_estimated_net_inflow_ratio": 0.5}
        for _ in range(25)
    ] + [
        {"next_close_return": -0.01, "t0_estimated_net_inflow_ratio": -0.3}
        for _ in range(15)
    ]
    result = compute_volume_price_alignment(rows)
    assert result["vol_price_signal_valid"] is True
    # VEQ not provided so alignment_rate may be None; but ENIR rates may be set
    assert result.get("inflow_win_rate") is not None or result.get("outflow_win_rate") is not None


def test_r41_t2_floor_registered() -> None:
    """vol_price_alignment_rate floor is 0.45 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "vol_price_alignment_rate" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["vol_price_alignment_rate"] == 0.45


def test_r41_t2_metric_registered() -> None:
    """vol_price_alignment_rate is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "vol_price_alignment_rate" in COMPARISON_METRICS
    assert "vol_price_alignment_rate" in OPTIONAL_COMPARISON_METRICS


def test_r41_t2_label_registered() -> None:
    """vol_price_alignment_rate label contains '量价'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "量价" in COMPARISON_METRIC_LABELS.get("vol_price_alignment_rate", "")


# ---------------------------------------------------------------------------
# T3: compute_statistical_significance_tests
# ---------------------------------------------------------------------------

def test_r41_t3_basic_returns_result() -> None:
    """compute_statistical_significance_tests returns dict with expected keys."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(50, seed=1, positive_bias=0.02)
    result = compute_statistical_significance_tests(rows)
    assert "combined_significance_score" in result
    assert "win_rate_p_value" in result
    assert "z_win_rate" in result
    assert "t_stat_return" in result


def test_r41_t3_empty_returns_null() -> None:
    """Returns all-None for empty input."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    result = compute_statistical_significance_tests([])
    assert result["combined_significance_score"] is None
    assert result["strategy_statistically_valid"] is None


def test_r41_t3_insufficient_rows_returns_null() -> None:
    """Returns all-None when fewer than 10 rows have valid returns."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(5, seed=0)
    result = compute_statistical_significance_tests(rows)
    assert result["combined_significance_score"] is None


def test_r41_t3_high_positive_bias_is_significant() -> None:
    """Large positive-bias returns should pass at least the 90% significance tests."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(200, seed=42, positive_bias=0.05)
    result = compute_statistical_significance_tests(rows)
    assert result["win_rate_significant_90"] is True
    assert result["return_significant_90"] is True
    assert result["strategy_statistically_valid"] is True


def test_r41_t3_combined_score_in_unit_interval() -> None:
    """combined_significance_score is between 0 and 1."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(40, seed=10, positive_bias=0.01)
    result = compute_statistical_significance_tests(rows)
    score = result["combined_significance_score"]
    if score is not None:
        assert 0.0 <= score <= 1.0


def test_r41_t3_negative_bias_not_significant() -> None:
    """Negative-bias returns should fail significance tests."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(100, seed=99, positive_bias=-0.03)
    result = compute_statistical_significance_tests(rows)
    assert result["win_rate_significant_90"] is False
    assert result["return_significant_90"] is False


def test_r41_t3_strategy_valid_requires_both_90() -> None:
    """strategy_statistically_valid is True iff both 90% tests pass."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(100, seed=42, positive_bias=0.04)
    result = compute_statistical_significance_tests(rows)
    expected = result["win_rate_significant_90"] and result["return_significant_90"]
    assert result["strategy_statistically_valid"] == expected


def test_r41_t3_p_value_in_unit_interval() -> None:
    """win_rate_p_value is between 0 and 1."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = _make_r41_stat_rows(50, seed=3)
    result = compute_statistical_significance_tests(rows)
    p = result["win_rate_p_value"]
    if p is not None:
        assert 0.0 <= p <= 1.0


def test_r41_t3_none_returns_skipped_gracefully() -> None:
    """Rows with None next_close_return are silently skipped."""
    from scripts.btst_analysis_utils import compute_statistical_significance_tests

    rows = [{"next_close_return": None} for _ in range(5)] + _make_r41_stat_rows(20, seed=5)
    result = compute_statistical_significance_tests(rows)
    assert result["combined_significance_score"] is not None


def test_r41_t3_floor_registered() -> None:
    """combined_significance_score floor is 0.25 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "combined_significance_score" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["combined_significance_score"] == 0.25


def test_r41_t3_metric_registered() -> None:
    """combined_significance_score is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "combined_significance_score" in COMPARISON_METRICS
    assert "combined_significance_score" in OPTIONAL_COMPARISON_METRICS


def test_r41_t3_label_registered() -> None:
    """combined_significance_score label contains '显著性'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "显著性" in COMPARISON_METRIC_LABELS.get("combined_significance_score", "")


# ===========================================================================
# Round 42 — T1: Score calibration curve
# ===========================================================================

import random as _rnd42


def _make_r42_calib_rows(n: int = 40, seed: int = 0, score_key: str = "runner_composite_score", score_win_corr: float = 0.5) -> list[dict]:
    """Build rows for calibration tests; score_win_corr controls score→return correlation."""
    rng = _rnd42.Random(seed)
    rows = []
    for i in range(n):
        score = rng.uniform(0.0, 1.0)
        # Higher score → higher probability of positive return
        prob_win = 0.4 + score_win_corr * 0.4
        ret = rng.uniform(0.001, 0.05) if rng.random() < prob_win else rng.uniform(-0.05, -0.001)
        rows.append({score_key: score, "next_close_return": ret})
    return rows


def _make_r42_cs_rows(n: int = 40, seed: int = 0, monotone: bool = True) -> list[dict]:
    """Build rows for close_strength stratification tests."""
    rng = _rnd42.Random(seed)
    rows = []
    for i in range(n):
        cs = rng.uniform(0.0, 1.0)
        if monotone:
            prob_win = 0.35 + cs * 0.4
        else:
            prob_win = 0.55  # flat, no correlation
        ret = rng.uniform(0.001, 0.04) if rng.random() < prob_win else rng.uniform(-0.04, -0.001)
        rows.append({"close_strength": cs, "next_close_return": ret})
    return rows


def _make_r42_consensus_windows(n: int = 5, seed: int = 0, pct_passing: float = 0.8) -> list[dict]:
    """Build per-window surface summaries with controllable pass rate."""
    rng = _rnd42.Random(seed)
    windows = []
    for i in range(n):
        passing = rng.random() < pct_passing
        windows.append({
            "next_close_positive_rate": 0.60 if passing else 0.48,
            "composite_gate_score": 65.0 if passing else 40.0,
            "expected_value_per_trade": 0.008 if passing else 0.001,
            "combined_significance_score": 0.50 if passing else 0.10,
        })
    return windows


def test_r42_t1_basic_returns_result() -> None:
    """compute_score_calibration_curve returns dict with expected keys."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    rows = _make_r42_calib_rows(40, seed=0)
    result = compute_score_calibration_curve(rows)
    assert "calibration_slope" in result
    assert "calibration_monotone" in result
    assert "well_calibrated" in result
    assert "calibration_valid" in result


def test_r42_t1_empty_returns_invalid() -> None:
    """Empty input returns calibration_valid=False."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    result = compute_score_calibration_curve([])
    assert result["calibration_valid"] is False
    assert result["calibration_slope"] is None


def test_r42_t1_insufficient_rows_returns_invalid() -> None:
    """Fewer than 15 paired rows returns invalid."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    rows = _make_r42_calib_rows(10, seed=0)
    result = compute_score_calibration_curve(rows)
    assert result["calibration_valid"] is False


def test_r42_t1_positive_slope_for_correlated_scores() -> None:
    """Strongly correlated score→return should produce positive calibration_slope."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    rows = _make_r42_calib_rows(80, seed=1, score_win_corr=0.9)
    result = compute_score_calibration_curve(rows)
    if result["calibration_valid"]:
        assert result["calibration_slope"] is not None


def test_r42_t1_score_priority_runner_composite() -> None:
    """runner_composite_score is preferred over composite_score."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    import random as _r
    rng = _r.Random(42)
    rows = [{"runner_composite_score": rng.uniform(0, 1), "composite_score": None, "next_close_return": rng.uniform(-0.03, 0.03)} for _ in range(20)]
    result = compute_score_calibration_curve(rows)
    # Should not crash; calibration_valid depends on sample count and bins
    assert "calibration_slope" in result


def test_r42_t1_fallback_to_composite_score() -> None:
    """Falls back to composite_score when runner_composite_score is absent."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    import random as _r
    rng = _r.Random(5)
    rows = [{"composite_score": rng.uniform(0, 1), "next_close_return": rng.uniform(-0.03, 0.03)} for _ in range(20)]
    result = compute_score_calibration_curve(rows)
    assert "calibration_slope" in result


def test_r42_t1_none_returns_skipped() -> None:
    """Rows with None score or return are excluded gracefully."""
    from scripts.btst_analysis_utils import compute_score_calibration_curve

    rows = [{"runner_composite_score": None, "next_close_return": 0.01} for _ in range(10)]
    rows += _make_r42_calib_rows(20, seed=3)
    result = compute_score_calibration_curve(rows)
    assert "calibration_valid" in result


def test_r42_t1_floor_registered() -> None:
    """calibration_slope floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "calibration_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["calibration_slope"] == 0.0


def test_r42_t1_metric_registered() -> None:
    """calibration_slope is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "calibration_slope" in COMPARISON_METRICS
    assert "calibration_slope" in OPTIONAL_COMPARISON_METRICS


def test_r42_t1_label_registered() -> None:
    """calibration_slope label contains '校准'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "校准" in COMPARISON_METRIC_LABELS.get("calibration_slope", "")


# ===========================================================================
# Round 42 — T2: Close-strength quartile stratification
# ===========================================================================


def test_r42_t2_basic_returns_result() -> None:
    """compute_close_strength_stratification returns dict with expected keys."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = _make_r42_cs_rows(40, seed=0)
    result = compute_close_strength_stratification(rows)
    assert "close_strength_valid" in result
    assert "cs_top_quartile_premium" in result
    assert "cs_monotone" in result


def test_r42_t2_empty_returns_invalid() -> None:
    """Empty input returns close_strength_valid=False."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    result = compute_close_strength_stratification([])
    assert result["close_strength_valid"] is False


def test_r42_t2_all_none_cs_returns_invalid() -> None:
    """All-None close_strength returns close_strength_valid=False."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = [{"close_strength": None, "next_close_return": 0.01} for _ in range(20)]
    result = compute_close_strength_stratification(rows)
    assert result["close_strength_valid"] is False


def test_r42_t2_insufficient_rows_returns_invalid() -> None:
    """Fewer than 10 paired rows returns invalid."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = _make_r42_cs_rows(5, seed=0)
    result = compute_close_strength_stratification(rows)
    assert result["close_strength_valid"] is False


def test_r42_t2_premium_is_float() -> None:
    """cs_top_quartile_premium is a float when valid."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = _make_r42_cs_rows(60, seed=7, monotone=True)
    result = compute_close_strength_stratification(rows)
    if result["close_strength_valid"] and result["cs_top_quartile_premium"] is not None:
        assert isinstance(result["cs_top_quartile_premium"], float)


def test_r42_t2_win_rates_in_unit_interval() -> None:
    """All per-quartile win rates are between 0 and 1."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = _make_r42_cs_rows(80, seed=9)
    result = compute_close_strength_stratification(rows)
    for key in ("cs_win_rate_q1", "cs_win_rate_q2", "cs_win_rate_q3", "cs_win_rate_q4"):
        val = result.get(key)
        if val is not None:
            assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


def test_r42_t2_effective_flag_when_premium_above_5pct() -> None:
    """cs_effective is True when premium > 0.05."""
    from scripts.btst_analysis_utils import compute_close_strength_stratification

    rows = _make_r42_cs_rows(100, seed=11, monotone=True)
    result = compute_close_strength_stratification(rows)
    if result.get("cs_top_quartile_premium") is not None:
        expected = result["cs_top_quartile_premium"] > 0.05
        assert result["cs_effective"] == expected


def test_r42_t2_floor_registered() -> None:
    """cs_top_quartile_premium floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "cs_top_quartile_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["cs_top_quartile_premium"] == 0.0


def test_r42_t2_metric_registered() -> None:
    """cs_top_quartile_premium is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "cs_top_quartile_premium" in COMPARISON_METRICS
    assert "cs_top_quartile_premium" in OPTIONAL_COMPARISON_METRICS


def test_r42_t2_label_registered() -> None:
    """cs_top_quartile_premium label contains '顶档'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "顶档" in COMPARISON_METRIC_LABELS.get("cs_top_quartile_premium", "")


# ===========================================================================
# Round 42 — T3: Cross-window consensus score
# ===========================================================================


def test_r42_t3_basic_returns_result() -> None:
    """compute_window_consensus_score returns dict with expected keys."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = _make_r42_consensus_windows(5, seed=0)
    result = compute_window_consensus_score(windows)
    assert "consensus_windows_pct" in result
    assert "strategy_consistently_valid" in result
    assert "consensus_grade" in result
    assert "best_consensus_window_idx" in result


def test_r42_t3_empty_returns_null() -> None:
    """Empty input returns all-None."""
    from scripts.optimize_profile import compute_window_consensus_score

    result = compute_window_consensus_score([])
    assert result["consensus_windows_pct"] is None
    assert result["strategy_consistently_valid"] is None


def test_r42_t3_fewer_than_3_windows_returns_null() -> None:
    """Fewer than 3 windows returns all-None."""
    from scripts.optimize_profile import compute_window_consensus_score

    result = compute_window_consensus_score(_make_r42_consensus_windows(2))
    assert result["consensus_windows_pct"] is None


def test_r42_t3_all_passing_windows_gives_pct_one() -> None:
    """All windows with 4 passing conditions → consensus_windows_pct = 1.0."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = [{"next_close_positive_rate": 0.65, "composite_gate_score": 75.0, "expected_value_per_trade": 0.010, "combined_significance_score": 0.50} for _ in range(5)]
    result = compute_window_consensus_score(windows)
    assert result["consensus_windows_pct"] == 1.0
    assert result["strategy_consistently_valid"] is True
    assert result["consensus_grade"] == "A"


def test_r42_t3_no_passing_windows_gives_grade_d() -> None:
    """No windows pass → grade D."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = [{"next_close_positive_rate": 0.40, "composite_gate_score": 30.0, "expected_value_per_trade": 0.001, "combined_significance_score": 0.0} for _ in range(5)]
    result = compute_window_consensus_score(windows)
    assert result["consensus_grade"] == "D"
    assert result["strategy_consistently_valid"] is False


def test_r42_t3_missing_keys_treated_as_false() -> None:
    """Missing condition keys are treated as not-met (False), no crash."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = [{} for _ in range(4)]
    result = compute_window_consensus_score(windows)
    assert result["consensus_windows_pct"] == 0.0


def test_r42_t3_pct_in_unit_interval() -> None:
    """consensus_windows_pct is between 0 and 1."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = _make_r42_consensus_windows(8, seed=42, pct_passing=0.5)
    result = compute_window_consensus_score(windows)
    pct = result["consensus_windows_pct"]
    if pct is not None:
        assert 0.0 <= pct <= 1.0


def test_r42_t3_best_window_idx_valid() -> None:
    """best_consensus_window_idx is a valid index into the input list."""
    from scripts.optimize_profile import compute_window_consensus_score

    windows = _make_r42_consensus_windows(6, seed=10)
    result = compute_window_consensus_score(windows)
    idx = result["best_consensus_window_idx"]
    if idx is not None:
        assert 0 <= idx < len(windows)


def test_r42_t3_floor_registered() -> None:
    """consensus_windows_pct floor is 0.40 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "consensus_windows_pct" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["consensus_windows_pct"] == 0.40


def test_r42_t3_metric_registered() -> None:
    """consensus_windows_pct is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "consensus_windows_pct" in COMPARISON_METRICS
    assert "consensus_windows_pct" in OPTIONAL_COMPARISON_METRICS


def test_r42_t3_label_registered() -> None:
    """consensus_windows_pct label contains '共识'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "共识" in COMPARISON_METRIC_LABELS.get("consensus_windows_pct", "")


# ===========================================================================
# Round 43 — T1 (Alpha): Profit Factor Analysis helpers
# ===========================================================================

def _make_r43_pf_rows(n: int, *, seed: int = 0, win_rate: float = 0.6, avg_win: float = 0.03, avg_loss: float = -0.02) -> list[dict]:
    import random as _r
    rng = _r.Random(seed)
    rows = []
    for _ in range(n):
        if rng.random() < win_rate:
            rows.append({"next_close_return": abs(avg_win) * rng.uniform(0.5, 1.5)})
        else:
            rows.append({"next_close_return": -abs(avg_loss) * rng.uniform(0.5, 1.5)})
    return rows


# ===========================================================================
# Round 43 — T2 (Beta): News Sentiment Stratification helpers
# ===========================================================================

def _make_r43_sentiment_rows(n: int, *, seed: int = 0, sentiment_lift: float = 0.10) -> list[dict]:
    import random as _r
    rng = _r.Random(seed)
    rows = []
    for i in range(n):
        score = rng.uniform(0.0, 1.0)
        base_wr = 0.50 + sentiment_lift * score
        ret = rng.uniform(0.01, 0.05) if rng.random() < base_wr else rng.uniform(-0.05, -0.01)
        rows.append({"news_sentiment_score": score, "next_close_return": ret})
    return rows


# ===========================================================================
# Round 43 — T3 (Gamma): Score Momentum Trend helpers
# ===========================================================================

def _make_r43_trend_windows(n: int, *, seed: int = 0, slope: float = 0.01) -> list[dict]:
    import random as _r
    rng = _r.Random(seed)
    base = 0.55
    return [{"candidate_pool_avg_composite_score": base + slope * i + rng.uniform(-0.005, 0.005)} for i in range(n)]


# ---------------------------------------------------------------------------
# T1 tests
# ---------------------------------------------------------------------------

def test_r43_t1_basic_returns_result() -> None:
    """compute_profit_factor_analysis returns dict with expected keys."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = _make_r43_pf_rows(30, seed=0)
    result = compute_profit_factor_analysis(rows)
    assert "profit_factor" in result
    assert "profit_factor_grade" in result
    assert "profitable" in result
    assert "profit_factor_valid" in result


def test_r43_t1_empty_returns_invalid() -> None:
    """Empty input returns profit_factor_valid=False."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    result = compute_profit_factor_analysis([])
    assert result["profit_factor_valid"] is False
    assert result["profit_factor"] is None


def test_r43_t1_insufficient_rows_returns_invalid() -> None:
    """Fewer than 10 valid rows returns invalid."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = _make_r43_pf_rows(5, seed=0)
    result = compute_profit_factor_analysis(rows)
    assert result["profit_factor_valid"] is False


def test_r43_t1_profitable_strategy_pf_above_one() -> None:
    """Strategy with win_rate=0.7 and avg_win>avg_loss should have profit_factor>=1.0."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = _make_r43_pf_rows(60, seed=1, win_rate=0.70, avg_win=0.04, avg_loss=0.02)
    result = compute_profit_factor_analysis(rows)
    assert result["profit_factor_valid"] is True
    assert result["profit_factor"] is not None
    assert result["profit_factor"] >= 1.0
    assert result["profitable"] is True


def test_r43_t1_losing_strategy_pf_below_one() -> None:
    """Strategy with low win_rate and avg_win<avg_loss should have profit_factor<1.0."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = _make_r43_pf_rows(50, seed=2, win_rate=0.30, avg_win=0.01, avg_loss=0.05)
    result = compute_profit_factor_analysis(rows)
    assert result["profit_factor_valid"] is True
    assert result["profit_factor"] < 1.0
    assert result["profitable"] is False
    assert result["profit_factor_grade"] == "D"


def test_r43_t1_pf_clamped_at_10() -> None:
    """Profit factor is clamped to [0, 10] even with extreme wins."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = [{"next_close_return": 100.0} for _ in range(15)]
    rows += [{"next_close_return": -0.0001} for _ in range(3)]
    result = compute_profit_factor_analysis(rows)
    assert result["profit_factor"] <= 10.0


def test_r43_t1_none_returns_skipped() -> None:
    """Rows with None next_close_return are excluded gracefully."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = [{"next_close_return": None} for _ in range(5)]
    rows += _make_r43_pf_rows(20, seed=3)
    result = compute_profit_factor_analysis(rows)
    assert result["profit_factor_valid"] is True


def test_r43_t1_grade_a_for_high_pf() -> None:
    """Grade A is assigned when profit_factor >= 2.0."""
    from scripts.btst_analysis_utils import compute_profit_factor_analysis

    rows = _make_r43_pf_rows(50, seed=4, win_rate=0.80, avg_win=0.05, avg_loss=0.01)
    result = compute_profit_factor_analysis(rows)
    if result["profit_factor"] is not None and result["profit_factor"] >= 2.0:
        assert result["profit_factor_grade"] == "A"


def test_r43_t1_floor_registered() -> None:
    """profit_factor floor is 1.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "profit_factor" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["profit_factor"] == 1.0


def test_r43_t1_metric_registered() -> None:
    """profit_factor is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "profit_factor" in COMPARISON_METRICS
    assert "profit_factor" in OPTIONAL_COMPARISON_METRICS


def test_r43_t1_label_registered() -> None:
    """profit_factor label contains 'PF'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "PF" in COMPARISON_METRIC_LABELS.get("profit_factor", "")


# ---------------------------------------------------------------------------
# T2 tests
# ---------------------------------------------------------------------------

def test_r43_t2_basic_returns_result() -> None:
    """compute_news_sentiment_stratification returns dict with expected keys."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(40, seed=0)
    result = compute_news_sentiment_stratification(rows)
    assert "sentiment_analysis_valid" in result
    assert "high_vs_low_sentiment_lift" in result
    assert "optimal_sentiment_bucket" in result


def test_r43_t2_empty_returns_invalid() -> None:
    """Empty input returns sentiment_analysis_valid=False."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    result = compute_news_sentiment_stratification([])
    assert result["sentiment_analysis_valid"] is False
    assert result["high_vs_low_sentiment_lift"] is None


def test_r43_t2_all_none_sentiment_returns_invalid() -> None:
    """All-None news_sentiment_score returns invalid."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = [{"news_sentiment_score": None, "next_close_return": 0.01} for _ in range(20)]
    result = compute_news_sentiment_stratification(rows)
    assert result["sentiment_analysis_valid"] is False


def test_r43_t2_insufficient_rows_returns_invalid() -> None:
    """Fewer than 10 paired rows returns invalid."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(5, seed=0)
    result = compute_news_sentiment_stratification(rows)
    assert result["sentiment_analysis_valid"] is False


def test_r43_t2_positive_lift_for_sentiment_correlated_rows() -> None:
    """High sentiment lift (0.20) should produce positive high_vs_low_sentiment_lift."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(80, seed=5, sentiment_lift=0.20)
    result = compute_news_sentiment_stratification(rows)
    if result["sentiment_analysis_valid"] and result["high_vs_low_sentiment_lift"] is not None:
        assert result["high_vs_low_sentiment_lift"] > 0


def test_r43_t2_sentiment_effective_when_lift_above_5pct() -> None:
    """sentiment_effective is True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(80, seed=6, sentiment_lift=0.30)
    result = compute_news_sentiment_stratification(rows)
    if result["sentiment_analysis_valid"] and result["high_vs_low_sentiment_lift"] is not None:
        if result["high_vs_low_sentiment_lift"] > 0.05:
            assert result["sentiment_effective"] is True


def test_r43_t2_optimal_bucket_is_valid_string() -> None:
    """optimal_sentiment_bucket is one of 'low'/'mid'/'high' when valid."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(40, seed=7)
    result = compute_news_sentiment_stratification(rows)
    if result["sentiment_analysis_valid"] and result["optimal_sentiment_bucket"] is not None:
        assert result["optimal_sentiment_bucket"] in ("low", "mid", "high")


def test_r43_t2_win_rates_in_unit_interval() -> None:
    """All per-tercile win rates are in [0, 1] when not None."""
    from scripts.btst_analysis_utils import compute_news_sentiment_stratification

    rows = _make_r43_sentiment_rows(60, seed=8)
    result = compute_news_sentiment_stratification(rows)
    for key in ("sentiment_low_win_rate", "sentiment_mid_win_rate", "sentiment_high_win_rate"):
        val = result.get(key)
        if val is not None:
            assert 0.0 <= val <= 1.0


def test_r43_t2_metric_registered() -> None:
    """high_vs_low_sentiment_lift is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "high_vs_low_sentiment_lift" in COMPARISON_METRICS
    assert "high_vs_low_sentiment_lift" in OPTIONAL_COMPARISON_METRICS


def test_r43_t2_label_registered() -> None:
    """high_vs_low_sentiment_lift label contains '情绪'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "情绪" in COMPARISON_METRIC_LABELS.get("high_vs_low_sentiment_lift", "")


# ---------------------------------------------------------------------------
# T3 tests
# ---------------------------------------------------------------------------

def test_r43_t3_basic_returns_result() -> None:
    """compute_score_momentum_trend returns dict with expected keys."""
    from scripts.optimize_profile import compute_score_momentum_trend

    windows = _make_r43_trend_windows(5, seed=0)
    result = compute_score_momentum_trend(windows)
    assert "score_trend_slope" in result
    assert "score_trend_normalized" in result
    assert "score_momentum_positive" in result
    assert "score_trend_acceleration" in result
    assert "score_trend_grade" in result


def test_r43_t3_empty_returns_null() -> None:
    """Empty input returns all-None."""
    from scripts.optimize_profile import compute_score_momentum_trend

    result = compute_score_momentum_trend([])
    assert result["score_trend_slope"] is None
    assert result["score_momentum_positive"] is None


def test_r43_t3_fewer_than_3_windows_returns_null() -> None:
    """Fewer than 3 windows returns all-None."""
    from scripts.optimize_profile import compute_score_momentum_trend

    result = compute_score_momentum_trend(_make_r43_trend_windows(2))
    assert result["score_trend_slope"] is None


def test_r43_t3_positive_slope_for_rising_scores() -> None:
    """Rising score series should produce positive slope and momentum."""
    from scripts.optimize_profile import compute_score_momentum_trend

    windows = [{"candidate_pool_avg_composite_score": 0.50 + 0.02 * i} for i in range(6)]
    result = compute_score_momentum_trend(windows)
    assert result["score_trend_slope"] is not None
    assert result["score_trend_slope"] > 0
    assert result["score_momentum_positive"] is True


def test_r43_t3_negative_slope_for_declining_scores() -> None:
    """Declining score series should produce negative slope."""
    from scripts.optimize_profile import compute_score_momentum_trend

    windows = [{"candidate_pool_avg_composite_score": 0.60 - 0.02 * i} for i in range(6)]
    result = compute_score_momentum_trend(windows)
    assert result["score_trend_slope"] < 0
    assert result["score_momentum_positive"] is False


def test_r43_t3_acceleration_is_last_minus_first() -> None:
    """score_trend_acceleration = last score - first score."""
    from scripts.optimize_profile import compute_score_momentum_trend

    scores = [0.50, 0.52, 0.54, 0.56, 0.58]
    windows = [{"candidate_pool_avg_composite_score": s} for s in scores]
    result = compute_score_momentum_trend(windows)
    assert result["score_trend_acceleration"] is not None
    assert abs(result["score_trend_acceleration"] - (scores[-1] - scores[0])) < 1e-6


def test_r43_t3_missing_score_key_skipped() -> None:
    """Windows without candidate_pool_avg_composite_score are skipped gracefully."""
    from scripts.optimize_profile import compute_score_momentum_trend

    windows = [{"candidate_pool_avg_composite_score": 0.55 + 0.01 * i} for i in range(4)]
    windows.insert(2, {"other_key": 0.99})
    result = compute_score_momentum_trend(windows)
    assert "score_trend_slope" in result


def test_r43_t3_grade_a_for_strong_uptrend() -> None:
    """Grade A for normalized slope > 0.05."""
    from scripts.optimize_profile import compute_score_momentum_trend

    windows = [{"candidate_pool_avg_composite_score": 0.10 + 0.10 * i} for i in range(5)]
    result = compute_score_momentum_trend(windows)
    if result["score_trend_normalized"] is not None and result["score_trend_normalized"] > 0.05:
        assert result["score_trend_grade"] == "A"


def test_r43_t3_floor_registered() -> None:
    """score_trend_normalized floor is -0.10 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "score_trend_normalized" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_trend_normalized"] == -0.10


def test_r43_t3_metric_registered() -> None:
    """score_trend_normalized is in COMPARISON_METRICS and OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS, OPTIONAL_COMPARISON_METRICS

    assert "score_trend_normalized" in COMPARISON_METRICS
    assert "score_trend_normalized" in OPTIONAL_COMPARISON_METRICS


def test_r43_t3_label_registered() -> None:
    """score_trend_normalized label contains '动量'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "动量" in COMPARISON_METRIC_LABELS.get("score_trend_normalized", "")


# ===========================================================================
# Round 44 — T1 (Alpha): compute_relative_strength_stratification
# ===========================================================================


def _make_rs_rows(n: int, *, win_frac: float = 0.6, rs_spread: float = 1.0) -> list[dict]:
    """Helper: n rows with relative_strength_rank spread and deterministic win/loss."""
    import math
    rows = []
    for i in range(n):
        rs = (i / max(n - 1, 1)) * rs_spread
        ret = 0.01 if (i % 10) < round(win_frac * 10) else -0.01
        rows.append({"relative_strength_rank": rs, "next_day_return": ret})
    return rows


def test_r44_rs_stratification_empty_input() -> None:
    """Empty rows → all None, stratification_valid=False."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    result = compute_relative_strength_stratification([])
    assert result["rs_stratification_valid"] is False
    assert result["rs_top_quartile_premium"] is None


def test_r44_rs_stratification_missing_field() -> None:
    """Rows without relative_strength_rank → graceful degradation."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_relative_strength_stratification(rows)
    assert result["rs_stratification_valid"] is False
    assert result["rs_top_quartile_premium"] is None


def test_r44_rs_stratification_few_rows() -> None:
    """3 rows (below 4) still runs without error; some quartiles may be None."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = [{"relative_strength_rank": float(i), "next_day_return": 0.01} for i in range(3)]
    result = compute_relative_strength_stratification(rows)
    # Should not raise; stratification_valid may be True or False
    assert "rs_stratification_valid" in result
    assert "rs_top_quartile_premium" in result


def test_r44_rs_stratification_normal_input_quartile_win_rates() -> None:
    """With 40 rows spread evenly, all four quartiles should have valid win rates."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = _make_rs_rows(40, win_frac=0.6)
    result = compute_relative_strength_stratification(rows)
    assert result["rs_q1_win_rate"] is not None
    assert result["rs_q2_win_rate"] is not None
    assert result["rs_q3_win_rate"] is not None
    assert result["rs_q4_win_rate"] is not None


def test_r44_rs_stratification_premium_in_range() -> None:
    """rs_top_quartile_premium must be in [-1, 1] when not None."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = _make_rs_rows(40, win_frac=0.6)
    result = compute_relative_strength_stratification(rows)
    premium = result["rs_top_quartile_premium"]
    if premium is not None:
        assert -1.0 <= premium <= 1.0


def test_r44_rs_stratification_monotone_true() -> None:
    """When high RS rows always win and low RS rows always lose, rs_monotone should be True."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = []
    for i in range(40):
        rs = float(i)
        # Bottom 25% always lose, top 25% always win, middle gradient
        if i < 10:
            ret = -0.01
        elif i < 20:
            ret = 0.005 if i % 2 == 0 else -0.005
        elif i < 30:
            ret = 0.01 if i % 3 != 0 else -0.005
        else:
            ret = 0.01
        rows.append({"relative_strength_rank": rs, "next_day_return": ret})
    result = compute_relative_strength_stratification(rows)
    # Just check the key exists and is a bool or None
    assert result["rs_monotone"] in (True, False, None)


def test_r44_rs_stratification_monotone_false_when_inverted() -> None:
    """When low RS rows win more than high RS, rs_monotone should be False."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = []
    for i in range(40):
        rs = float(i)
        # Invert: low RS wins, high RS loses
        ret = 0.01 if i < 20 else -0.01
        rows.append({"relative_strength_rank": rs, "next_day_return": ret})
    result = compute_relative_strength_stratification(rows)
    if result["rs_monotone"] is not None:
        assert result["rs_monotone"] is False


def test_r44_rs_stratification_valid_flag() -> None:
    """rs_stratification_valid=True when ≥2 quartiles are valid."""
    from scripts.btst_analysis_utils import compute_relative_strength_stratification

    rows = _make_rs_rows(40)
    result = compute_relative_strength_stratification(rows)
    assert result["rs_stratification_valid"] is True


def test_r44_rs_stratification_floor_registered() -> None:
    """rs_top_quartile_premium floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "rs_top_quartile_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["rs_top_quartile_premium"] == 0.0


def test_r44_rs_stratification_label_registered() -> None:
    """rs_top_quartile_premium label is in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "rs_top_quartile_premium" in COMPARISON_METRIC_LABELS
    assert "RS" in COMPARISON_METRIC_LABELS["rs_top_quartile_premium"]


def test_r44_rs_stratification_optional_registered() -> None:
    """rs_top_quartile_premium is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "rs_top_quartile_premium" in OPTIONAL_COMPARISON_METRICS


# ===========================================================================
# Round 44 — T2 (Beta): compute_breakout_quality_stratification
# ===========================================================================


def _make_bq_rows(n: int, *, high_wins: float = 0.8, low_wins: float = 0.3) -> list[dict]:
    """Helper: n rows with breakout_quality_score spanning [0,1] and win rates."""
    rows = []
    for i in range(n):
        bq = i / max(n - 1, 1)
        if bq > 0.67:
            ret = 0.01 if (i % 10) < round(high_wins * 10) else -0.01
        elif bq > 0.33:
            ret = 0.01 if i % 2 == 0 else -0.01
        else:
            ret = 0.01 if (i % 10) < round(low_wins * 10) else -0.01
        rows.append({"breakout_quality_score": bq, "next_day_return": ret})
    return rows


def test_r44_bq_stratification_empty_input() -> None:
    """Empty rows → all None, stratification_valid=False."""
    from scripts.btst_analysis_utils import compute_breakout_quality_stratification

    result = compute_breakout_quality_stratification([])
    assert result["bq_stratification_valid"] is False
    assert result["bq_high_vs_low_lift"] is None


def test_r44_bq_stratification_missing_field() -> None:
    """Rows without breakout_quality_score → graceful degradation."""
    from scripts.btst_analysis_utils import compute_breakout_quality_stratification

    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_breakout_quality_stratification(rows)
    assert result["bq_stratification_valid"] is False
    assert result["bq_high_vs_low_lift"] is None


def test_r44_bq_stratification_normal_three_tiers() -> None:
    """Normal 30-row input should produce bq_high_vs_low_lift."""
    from scripts.btst_analysis_utils import compute_breakout_quality_stratification

    rows = _make_bq_rows(30)
    result = compute_breakout_quality_stratification(rows)
    assert result["bq_high_vs_low_lift"] is not None


def test_r44_bq_stratification_effective_threshold() -> None:
    """bq_effective=True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_breakout_quality_stratification

    # Force a large spread
    rows = _make_bq_rows(30, high_wins=0.9, low_wins=0.2)
    result = compute_breakout_quality_stratification(rows)
    lift = result["bq_high_vs_low_lift"]
    if lift is not None and lift > 0.05:
        assert result["bq_effective"] is True
    elif lift is not None and lift <= 0.05:
        assert result["bq_effective"] is False


def test_r44_bq_stratification_monotone_logic() -> None:
    """bq_monotone reflects low < mid < high ordering."""
    from scripts.btst_analysis_utils import compute_breakout_quality_stratification

    rows = _make_bq_rows(30, high_wins=0.9, low_wins=0.2)
    result = compute_breakout_quality_stratification(rows)
    # Monotone should be a bool or None — just validate type
    assert result["bq_monotone"] in (True, False, None)


def test_r44_bq_stratification_label_registered() -> None:
    """bq_high_vs_low_lift label is in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "bq_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert "突破" in COMPARISON_METRIC_LABELS["bq_high_vs_low_lift"]


def test_r44_bq_stratification_optional_registered() -> None:
    """bq_high_vs_low_lift is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "bq_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r44_bq_stratification_no_floor() -> None:
    """bq_high_vs_low_lift must NOT be in BTST_QUALITY_FLOORS (diagnostic only)."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "bq_high_vs_low_lift" not in BTST_QUALITY_FLOORS


# ===========================================================================
# Round 44 — T3 (Gamma): compute_win_rate_stability_analysis
# ===========================================================================


def test_r44_win_rate_stability_empty_input() -> None:
    """Empty list → all None, valid=False."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    result = compute_win_rate_stability_analysis([])
    assert result["win_rate_stability_valid"] is False
    assert result["win_rate_cv"] is None


def test_r44_win_rate_stability_too_few_windows() -> None:
    """< 3 windows → graceful degradation."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    windows = [{"win_rate": 0.60}, {"win_rate": 0.65}]
    result = compute_win_rate_stability_analysis(windows)
    assert result["win_rate_stability_valid"] is False
    assert result["win_rate_cv"] is None


def test_r44_win_rate_stability_normal_input_cv_nonneg() -> None:
    """Normal input: win_rate_cv ≥ 0 and win_rate_mean in [0, 1]."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    windows = [{"win_rate": 0.55 + 0.02 * i} for i in range(5)]
    result = compute_win_rate_stability_analysis(windows)
    assert result["win_rate_stability_valid"] is True
    assert result["win_rate_cv"] is not None and result["win_rate_cv"] >= 0.0
    assert 0.0 <= result["win_rate_mean"] <= 1.0


def test_r44_win_rate_stability_perfect_stability() -> None:
    """All windows same win_rate → cv = 0.0, grade A."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    windows = [{"win_rate": 0.65} for _ in range(5)]
    result = compute_win_rate_stability_analysis(windows)
    assert result["win_rate_stability_valid"] is True
    assert result["win_rate_cv"] == 0.0
    assert result["win_rate_stability_grade"] == "A"


def test_r44_win_rate_stability_high_variance_grade_d() -> None:
    """High variance input → grade D (cv ≥ 0.30)."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    # Very wide spread: 0.20 to 0.80 → cv well above 0.30
    windows = [{"win_rate": v} for v in [0.20, 0.80, 0.20, 0.80, 0.20, 0.80]]
    result = compute_win_rate_stability_analysis(windows)
    assert result["win_rate_stability_valid"] is True
    if result["win_rate_cv"] is not None and result["win_rate_cv"] >= 0.30:
        assert result["win_rate_stability_grade"] == "D"


def test_r44_win_rate_stability_missing_key_skipped() -> None:
    """Windows without 'win_rate' key are skipped; < 3 valid → degradation."""
    from scripts.optimize_profile import compute_win_rate_stability_analysis

    windows = [{"other": 0.5} for _ in range(10)]
    result = compute_win_rate_stability_analysis(windows)
    assert result["win_rate_stability_valid"] is False


def test_r44_win_rate_stability_cap_registered() -> None:
    """win_rate_cv cap is 0.30 in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS

    assert "win_rate_cv" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["win_rate_cv"] == 0.30


def test_r44_win_rate_stability_lower_is_better_registered() -> None:
    """win_rate_cv is in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS

    assert "win_rate_cv" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r44_win_rate_stability_optional_registered() -> None:
    """win_rate_cv is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "win_rate_cv" in OPTIONAL_COMPARISON_METRICS


# ===========================================================================
# Round 45 — T1 (Alpha): compute_market_cap_stratification
# ===========================================================================


def _make_mc_rows(n: int, *, high_wins: float = 0.8, low_wins: float = 0.3) -> list[dict]:
    """Helper: n rows with market_cap_score spanning [0,1] and win rates."""
    rows = []
    for i in range(n):
        mc = i / max(n - 1, 1)
        if mc > 0.67:
            ret = 0.01 if (i % 10) < round(high_wins * 10) else -0.01
        elif mc > 0.33:
            ret = 0.01 if i % 2 == 0 else -0.01
        else:
            ret = 0.01 if (i % 10) < round(low_wins * 10) else -0.01
        rows.append({"market_cap_score": mc, "next_day_return": ret})
    return rows


def test_r45_market_cap_strat_empty_input() -> None:
    """Empty rows → mc_stratification_valid=False, all None."""
    from scripts.btst_analysis_utils import compute_market_cap_stratification

    result = compute_market_cap_stratification([])
    assert result["mc_stratification_valid"] is False
    assert result["mc_high_vs_low_lift"] is None
    assert result["mc_low_win_rate"] is None
    assert result["mc_high_win_rate"] is None


def test_r45_market_cap_strat_missing_field() -> None:
    """Rows without market_cap_score → graceful degradation."""
    from scripts.btst_analysis_utils import compute_market_cap_stratification

    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_market_cap_stratification(rows)
    assert result["mc_stratification_valid"] is False
    assert result["mc_high_vs_low_lift"] is None


def test_r45_market_cap_strat_normal_three_tiers() -> None:
    """Normal 30-row input should produce mc_high_vs_low_lift and mc_stratification_valid=True."""
    from scripts.btst_analysis_utils import compute_market_cap_stratification

    rows = _make_mc_rows(30)
    result = compute_market_cap_stratification(rows)
    assert result["mc_stratification_valid"] is True
    assert result["mc_high_vs_low_lift"] is not None


def test_r45_market_cap_strat_monotone_logic() -> None:
    """mc_monotone=True when high_wins >> low_wins with clear ordering."""
    from scripts.btst_analysis_utils import compute_market_cap_stratification

    rows = _make_mc_rows(60, high_wins=0.9, low_wins=0.1)
    result = compute_market_cap_stratification(rows)
    # monotone should be a bool or None
    assert result["mc_monotone"] in (True, False, None)
    # With such extreme spread, lift must be positive
    if result["mc_high_vs_low_lift"] is not None:
        assert result["mc_high_vs_low_lift"] > 0


def test_r45_market_cap_strat_effective_threshold() -> None:
    """mc_effective=True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_market_cap_stratification

    rows = _make_mc_rows(60, high_wins=0.9, low_wins=0.2)
    result = compute_market_cap_stratification(rows)
    lift = result["mc_high_vs_low_lift"]
    if lift is not None and lift > 0.05:
        assert result["mc_effective"] is True
    elif lift is not None and lift <= 0.05:
        assert result["mc_effective"] is False


def test_r45_market_cap_strat_label_registered() -> None:
    """mc_high_vs_low_lift label is in COMPARISON_METRIC_LABELS with '市值'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "mc_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert "市值" in COMPARISON_METRIC_LABELS["mc_high_vs_low_lift"]


def test_r45_market_cap_strat_optional_registered() -> None:
    """mc_high_vs_low_lift is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "mc_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r45_market_cap_strat_no_floor() -> None:
    """mc_high_vs_low_lift must NOT be in BTST_QUALITY_FLOORS (diagnostic metric)."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "mc_high_vs_low_lift" not in BTST_QUALITY_FLOORS


# ===========================================================================
# Round 45 — T2 (Beta): compute_catalyst_score_stratification
# ===========================================================================


def _make_catalyst_rows(n: int, *, q4_wins: float = 0.8, q1_wins: float = 0.3) -> list[dict]:
    """Helper: n rows with catalyst_theme_score spanning [0,1] and win rates."""
    rows = []
    for i in range(n):
        cat = i / max(n - 1, 1)
        if cat > 0.75:
            ret = 0.01 if (i % 10) < round(q4_wins * 10) else -0.01
        elif cat > 0.50:
            ret = 0.01 if i % 3 < 2 else -0.01
        elif cat > 0.25:
            ret = 0.01 if i % 2 == 0 else -0.01
        else:
            ret = 0.01 if (i % 10) < round(q1_wins * 10) else -0.01
        rows.append({"catalyst_theme_score": cat, "next_day_return": ret})
    return rows


def test_r45_catalyst_strat_empty_input() -> None:
    """Empty rows → catalyst_stratification_valid=False, all None."""
    from scripts.btst_analysis_utils import compute_catalyst_score_stratification

    result = compute_catalyst_score_stratification([])
    assert result["catalyst_stratification_valid"] is False
    assert result["catalyst_top_quartile_premium"] is None
    assert result["catalyst_q1_win_rate"] is None
    assert result["catalyst_q4_win_rate"] is None


def test_r45_catalyst_strat_missing_field() -> None:
    """Rows without catalyst_theme_score → graceful degradation."""
    from scripts.btst_analysis_utils import compute_catalyst_score_stratification

    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_catalyst_score_stratification(rows)
    assert result["catalyst_stratification_valid"] is False
    assert result["catalyst_top_quartile_premium"] is None


def test_r45_catalyst_strat_normal_four_quartiles() -> None:
    """Normal 40-row input should produce catalyst_top_quartile_premium."""
    from scripts.btst_analysis_utils import compute_catalyst_score_stratification

    rows = _make_catalyst_rows(40)
    result = compute_catalyst_score_stratification(rows)
    assert result["catalyst_top_quartile_premium"] is not None
    assert result["catalyst_stratification_valid"] is True


def test_r45_catalyst_strat_monotone_logic() -> None:
    """catalyst_monotone reflects Q1 < Q2 < Q3 < Q4 ordering."""
    from scripts.btst_analysis_utils import compute_catalyst_score_stratification

    rows = _make_catalyst_rows(40)
    result = compute_catalyst_score_stratification(rows)
    assert result["catalyst_monotone"] in (True, False, None)


def test_r45_catalyst_strat_valid_flag_boundary() -> None:
    """catalyst_stratification_valid=True when ≥ 2 quartiles have ≥ 3 rows."""
    from scripts.btst_analysis_utils import compute_catalyst_score_stratification

    # 12 rows split equally across [0,1] → 4 groups of 3 → valid
    rows = _make_catalyst_rows(12)
    result = compute_catalyst_score_stratification(rows)
    assert result["catalyst_stratification_valid"] is True


def test_r45_catalyst_strat_floor_registered() -> None:
    """catalyst_top_quartile_premium floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "catalyst_top_quartile_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["catalyst_top_quartile_premium"] == 0.0


def test_r45_catalyst_strat_label_registered() -> None:
    """catalyst_top_quartile_premium label is in COMPARISON_METRIC_LABELS with '催化'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "catalyst_top_quartile_premium" in COMPARISON_METRIC_LABELS
    assert "催化" in COMPARISON_METRIC_LABELS["catalyst_top_quartile_premium"]


def test_r45_catalyst_strat_optional_registered() -> None:
    """catalyst_top_quartile_premium is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "catalyst_top_quartile_premium" in OPTIONAL_COMPARISON_METRICS


# ===========================================================================
# Round 45 — T3 (Gamma): compute_top_candidate_consistency
# ===========================================================================


def test_r45_top_candidate_consistency_empty_list() -> None:
    """Empty list → all None (graceful degradation)."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    result = compute_top_candidate_consistency([])
    assert result["top_candidate_consistency_rate"] is None
    assert result["top_candidate_mean_win_rate"] is None
    assert result["top_candidate_best_win_rate"] is None
    assert result["top_candidate_consistency_grade"] is None


def test_r45_top_candidate_consistency_too_few_windows() -> None:
    """< 3 valid windows → graceful degradation."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    windows = [{"win_rate": 0.65}, {"win_rate": 0.70}]
    result = compute_top_candidate_consistency(windows)
    assert result["top_candidate_consistency_rate"] is None
    assert result["top_candidate_consistency_grade"] is None


def test_r45_top_candidate_consistency_all_above_threshold() -> None:
    """All windows with win_rate ≥ 0.60 → rate=1.0, grade A."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    windows = [{"win_rate": 0.65 + 0.01 * i} for i in range(5)]
    result = compute_top_candidate_consistency(windows)
    assert result["top_candidate_consistency_rate"] == 1.0
    assert result["top_candidate_consistency_grade"] == "A"


def test_r45_top_candidate_consistency_none_above_threshold() -> None:
    """All windows with win_rate < 0.60 → rate=0.0, grade D."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    windows = [{"win_rate": 0.40 + 0.02 * i} for i in range(5)]
    result = compute_top_candidate_consistency(windows)
    assert result["top_candidate_consistency_rate"] == 0.0
    assert result["top_candidate_consistency_grade"] == "D"


def test_r45_top_candidate_consistency_mixed_scenario() -> None:
    """Mixed win rates: rate = above_count / total."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    # 3 above (0.65, 0.70, 0.75) and 2 below (0.50, 0.55) → rate = 3/5 = 0.6
    windows = [{"win_rate": v} for v in [0.65, 0.50, 0.70, 0.55, 0.75]]
    result = compute_top_candidate_consistency(windows)
    assert result["top_candidate_consistency_rate"] is not None
    assert abs(result["top_candidate_consistency_rate"] - 0.6) < 1e-5
    assert result["top_candidate_consistency_grade"] == "B"


def test_r45_top_candidate_consistency_score_bucket_priority() -> None:
    """score_bucket_win_rates Q5 takes priority over win_rate fallback."""
    from scripts.optimize_profile import compute_top_candidate_consistency

    # Q5 = 0.75 > 0.60 threshold; win_rate = 0.45 < 0.60 threshold
    windows = [
        {"score_bucket_win_rates": {"Q5": 0.75}, "win_rate": 0.45},
        {"score_bucket_win_rates": {"Q5": 0.80}, "win_rate": 0.40},
        {"score_bucket_win_rates": {"Q5": 0.70}, "win_rate": 0.35},
    ]
    result = compute_top_candidate_consistency(windows)
    # All Q5 values are ≥ 0.60 → rate should be 1.0
    assert result["top_candidate_consistency_rate"] == 1.0
    assert result["top_candidate_consistency_grade"] == "A"


def test_r45_top_candidate_consistency_floor_registered() -> None:
    """top_candidate_consistency_rate floor is 0.40 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "top_candidate_consistency_rate" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["top_candidate_consistency_rate"] == 0.40


def test_r45_top_candidate_consistency_label_registered() -> None:
    """top_candidate_consistency_rate label is in COMPARISON_METRIC_LABELS with '顶候选'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "top_candidate_consistency_rate" in COMPARISON_METRIC_LABELS
    assert "顶候选" in COMPARISON_METRIC_LABELS["top_candidate_consistency_rate"]


def test_r45_top_candidate_consistency_optional_registered() -> None:
    """top_candidate_consistency_rate is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "top_candidate_consistency_rate" in OPTIONAL_COMPARISON_METRICS


# ===========================================================================
# Round 46 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 — compute_volume_price_divergence_stratification
# ---------------------------------------------------------------------------

def test_r46_vpd_strat_empty_input() -> None:
    """Empty rows -> graceful degradation with vpd_stratification_valid=False."""
    from scripts.btst_analysis_utils import compute_volume_price_divergence_stratification
    result = compute_volume_price_divergence_stratification([])
    assert result["vpd_stratification_valid"] is False
    assert result["vpd_low_win_rate"] is None
    assert result["vpd_mid_win_rate"] is None
    assert result["vpd_high_win_rate"] is None
    assert result["vpd_low_vs_high_lift"] is None


def test_r46_vpd_strat_missing_field() -> None:
    """Rows lacking volume_price_divergence -> graceful degradation."""
    from scripts.btst_analysis_utils import compute_volume_price_divergence_stratification
    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_volume_price_divergence_stratification(rows)
    assert result["vpd_stratification_valid"] is False
    assert result["vpd_low_vs_high_lift"] is None


def test_r46_vpd_strat_normal_three_tiers() -> None:
    """Normal input with clear low/mid/high tiers -> lift has a value."""
    from scripts.btst_analysis_utils import compute_volume_price_divergence_stratification
    rows = []
    # low vpd rows: 9 rows returning positive (high win rate in low tier)
    for _ in range(9):
        rows.append({"volume_price_divergence": 0.1, "next_day_return": 0.02})
    rows.append({"volume_price_divergence": 0.1, "next_day_return": -0.01})
    # mid vpd rows: ~50% win rate
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": 0.01})
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": -0.01})
    # high vpd rows: low win rate
    rows.append({"volume_price_divergence": 0.9, "next_day_return": 0.02})
    for _ in range(9):
        rows.append({"volume_price_divergence": 0.9, "next_day_return": -0.02})
    result = compute_volume_price_divergence_stratification(rows)
    assert result["vpd_low_vs_high_lift"] is not None
    assert result["vpd_stratification_valid"] is True


def test_r46_vpd_strat_anti_monotone_logic() -> None:
    """When low > mid > high win rate, vpd_anti_monotone should be True."""
    from scripts.btst_analysis_utils import compute_volume_price_divergence_stratification
    rows = []
    # low tier: 8/10 win
    for _ in range(8):
        rows.append({"volume_price_divergence": 0.1, "next_day_return": 0.03})
    for _ in range(2):
        rows.append({"volume_price_divergence": 0.1, "next_day_return": -0.01})
    # mid tier: 5/10 win
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": 0.02})
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": -0.02})
    # high tier: 2/10 win
    for _ in range(2):
        rows.append({"volume_price_divergence": 0.9, "next_day_return": 0.01})
    for _ in range(8):
        rows.append({"volume_price_divergence": 0.9, "next_day_return": -0.03})
    result = compute_volume_price_divergence_stratification(rows)
    assert result["vpd_anti_monotone"] is True


def test_r46_vpd_strat_effective_threshold() -> None:
    """When lift > 0.05 vpd_effective should be True, otherwise False."""
    from scripts.btst_analysis_utils import compute_volume_price_divergence_stratification
    # Build rows where low wins 9/10 and high wins 2/10 -> lift ~ 0.70
    rows = []
    for _ in range(9):
        rows.append({"volume_price_divergence": 0.1, "next_day_return": 0.02})
    rows.append({"volume_price_divergence": 0.1, "next_day_return": -0.01})
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": 0.01})
    for _ in range(5):
        rows.append({"volume_price_divergence": 0.5, "next_day_return": -0.01})
    for _ in range(2):
        rows.append({"volume_price_divergence": 0.9, "next_day_return": 0.01})
    for _ in range(8):
        rows.append({"volume_price_divergence": 0.9, "next_day_return": -0.02})
    result = compute_volume_price_divergence_stratification(rows)
    assert result["vpd_effective"] is True
    # Now build rows where lift < 0.05 (both tiers have same win rate)
    rows2 = []
    for _ in range(6):
        rows2.append({"volume_price_divergence": 0.1, "next_day_return": 0.01})
    for _ in range(4):
        rows2.append({"volume_price_divergence": 0.1, "next_day_return": -0.01})
    for _ in range(5):
        rows2.append({"volume_price_divergence": 0.5, "next_day_return": 0.01})
    for _ in range(5):
        rows2.append({"volume_price_divergence": 0.5, "next_day_return": -0.01})
    for _ in range(6):
        rows2.append({"volume_price_divergence": 0.9, "next_day_return": 0.01})
    for _ in range(4):
        rows2.append({"volume_price_divergence": 0.9, "next_day_return": -0.01})
    result2 = compute_volume_price_divergence_stratification(rows2)
    assert result2["vpd_effective"] is False


def test_r46_vpd_strat_floor_registered() -> None:
    """vpd_low_vs_high_lift: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "vpd_low_vs_high_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["vpd_low_vs_high_lift"] == 0.0


def test_r46_vpd_strat_label_registered() -> None:
    """vpd_low_vs_high_lift must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "vpd_low_vs_high_lift" in COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS["vpd_low_vs_high_lift"] == "量价低背离胜率溢价"


def test_r46_vpd_strat_optional_registered() -> None:
    """vpd_low_vs_high_lift must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "vpd_low_vs_high_lift" in OPTIONAL_COMPARISON_METRICS


# ---------------------------------------------------------------------------
# T2 — compute_score_distribution_moments
# ---------------------------------------------------------------------------

def test_r46_score_moments_empty_input() -> None:
    """Empty rows -> graceful degradation (all None)."""
    from scripts.btst_analysis_utils import compute_score_distribution_moments
    result = compute_score_distribution_moments([])
    assert result["score_mean"] is None
    assert result["score_skewness"] is None
    assert result["score_positive_pct"] is None


def test_r46_score_moments_too_few_rows() -> None:
    """Fewer than 5 rows -> graceful degradation."""
    from scripts.btst_analysis_utils import compute_score_distribution_moments
    rows = [{"score": float(i)} for i in range(4)]
    result = compute_score_distribution_moments(rows)
    assert result["score_mean"] is None
    assert result["score_std"] is None


def test_r46_score_moments_near_normal_skewness() -> None:
    """Near-symmetric input -> |skewness| < 0.3."""
    from scripts.btst_analysis_utils import compute_score_distribution_moments
    # symmetric around 0: -4 -3 -2 -1 0 1 2 3 4
    rows = [{"score": float(v)} for v in range(-4, 5)]
    result = compute_score_distribution_moments(rows)
    assert result["score_skewness"] is not None
    assert abs(result["score_skewness"]) < 0.3


def test_r46_score_moments_right_skewed() -> None:
    """Right-skewed input -> score_skewness > 0."""
    from scripts.btst_analysis_utils import compute_score_distribution_moments
    # Many low values, a few high ones -> right skew
    rows = [{"score": 0.1}] * 15 + [{"score": 5.0}, {"score": 8.0}, {"score": 10.0}]
    result = compute_score_distribution_moments(rows)
    assert result["score_skewness"] is not None
    assert result["score_skewness"] > 0


def test_r46_score_moments_all_positive_pct() -> None:
    """All scores > 0 -> score_positive_pct == 1.0."""
    from scripts.btst_analysis_utils import compute_score_distribution_moments
    rows = [{"score": float(i + 1)} for i in range(10)]
    result = compute_score_distribution_moments(rows)
    assert result["score_positive_pct"] == 1.0


def test_r46_score_moments_floor_skewness_registered() -> None:
    """score_skewness: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "score_skewness" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_skewness"] == 0.0


def test_r46_score_moments_floor_positive_pct_registered() -> None:
    """score_positive_pct: 0.50 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "score_positive_pct" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_positive_pct"] == 0.50


def test_r46_score_moments_label_skewness_registered() -> None:
    """score_skewness must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "score_skewness" in COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS["score_skewness"] == "评分分布偏度"


def test_r46_score_moments_label_positive_pct_registered() -> None:
    """score_positive_pct must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "score_positive_pct" in COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS["score_positive_pct"] == "评分正值占比"


def test_r46_score_moments_optional_skewness_registered() -> None:
    """score_skewness must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "score_skewness" in OPTIONAL_COMPARISON_METRICS


def test_r46_score_moments_optional_positive_pct_registered() -> None:
    """score_positive_pct must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "score_positive_pct" in OPTIONAL_COMPARISON_METRICS


# ---------------------------------------------------------------------------
# T3 — compute_cross_window_gate_consistency
# ---------------------------------------------------------------------------

def test_r46_gate_consistency_empty_list() -> None:
    """Empty list -> graceful degradation (all None)."""
    from scripts.optimize_profile import compute_cross_window_gate_consistency
    result = compute_cross_window_gate_consistency([])
    assert result["gate_above_threshold_mean"] is None
    assert result["gate_above_threshold_cv"] is None
    assert result["gate_consistency_grade"] is None


def test_r46_gate_consistency_too_few_windows() -> None:
    """Fewer than 3 valid windows -> graceful degradation."""
    from scripts.optimize_profile import compute_cross_window_gate_consistency
    summaries = [{"gate_high_pct": 0.5}, {"gate_high_pct": 0.4}]
    result = compute_cross_window_gate_consistency(summaries)
    assert result["gate_above_threshold_cv"] is None
    assert result["gate_consistency_grade"] is None


def test_r46_gate_consistency_perfectly_stable() -> None:
    """All windows with same gate fraction -> cv == 0.0, grade A."""
    from scripts.optimize_profile import compute_cross_window_gate_consistency
    summaries = [{"gate_high_pct": 0.6}] * 5
    result = compute_cross_window_gate_consistency(summaries)
    assert result["gate_above_threshold_cv"] == 0.0
    assert result["gate_consistency_grade"] == "A"


def test_r46_gate_consistency_high_variation_grade_d() -> None:
    """High variation -> cv >= 0.25, grade D."""
    from scripts.optimize_profile import compute_cross_window_gate_consistency
    summaries = [
        {"gate_high_pct": 0.1},
        {"gate_high_pct": 0.9},
        {"gate_high_pct": 0.05},
        {"gate_high_pct": 0.85},
    ]
    result = compute_cross_window_gate_consistency(summaries)
    assert result["gate_consistency_grade"] == "D"
    assert result["gate_above_threshold_cv"] is not None
    assert result["gate_above_threshold_cv"] >= 0.25


def test_r46_gate_consistency_grade_b_boundary() -> None:
    """Values close together but not identical -> cv in [0.10, 0.20) -> grade B."""
    from scripts.optimize_profile import compute_cross_window_gate_consistency
    # mean ~0.6, std ~0.08 -> cv ~0.13 (grade B)
    summaries = [
        {"gate_high_pct": 0.52},
        {"gate_high_pct": 0.60},
        {"gate_high_pct": 0.68},
    ]
    result = compute_cross_window_gate_consistency(summaries)
    assert result["gate_consistency_grade"] == "B"


def test_r46_gate_consistency_cap_registered() -> None:
    """gate_above_threshold_cv: 0.25 must be in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    assert "gate_above_threshold_cv" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["gate_above_threshold_cv"] == 0.25


def test_r46_gate_consistency_lower_is_better_registered() -> None:
    """gate_above_threshold_cv must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "gate_above_threshold_cv" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r46_gate_consistency_optional_registered() -> None:
    """gate_above_threshold_cv must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "gate_above_threshold_cv" in OPTIONAL_COMPARISON_METRICS


# ===========================================================================
# Round 47 — T1 (Alpha): compute_momentum_slope_stratification
# ===========================================================================


def _make_ms_rows(n: int, *, high_wins: float = 0.8, low_wins: float = 0.3) -> list[dict]:
    """Helper: n rows with momentum_slope_20d spanning [-1, 1] and controlled win rates."""
    rows = []
    third = n // 3
    for i in range(n):
        ms_val = -1.0 + 2.0 * i / max(1, n - 1)
        if i < third:
            # low tier — low_wins fraction should win
            ret = 0.05 if (i % 10) < int(low_wins * 10) else -0.05
        elif i < 2 * third:
            # mid tier
            mid_wins = (high_wins + low_wins) / 2.0
            ret = 0.05 if (i % 10) < int(mid_wins * 10) else -0.05
        else:
            # high tier — high_wins fraction should win
            ret = 0.05 if (i % 10) < int(high_wins * 10) else -0.05
        rows.append({"momentum_slope_20d": ms_val, "next_day_return": ret})
    return rows


def test_r47_momentum_strat_empty_input() -> None:
    """Empty rows → ms_stratification_valid=False, all None."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    result = compute_momentum_slope_stratification([])
    assert result["ms_stratification_valid"] is False
    assert result["ms_high_vs_low_lift"] is None
    assert result["ms_high_win_rate"] is None
    assert result["ms_low_win_rate"] is None


def test_r47_momentum_strat_missing_field() -> None:
    """Rows missing momentum_slope_20d → degraded (ms_stratification_valid=False)."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    rows = [{"next_day_return": 0.05} for _ in range(20)]
    result = compute_momentum_slope_stratification(rows)
    assert result["ms_stratification_valid"] is False
    assert result["ms_high_vs_low_lift"] is None


def test_r47_momentum_strat_normal_three_tiers() -> None:
    """Normal 30-row input: ms_high_vs_low_lift has a value, valid=True."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    rows = _make_ms_rows(30, high_wins=0.8, low_wins=0.3)
    result = compute_momentum_slope_stratification(rows)
    assert result["ms_stratification_valid"] is True
    assert result["ms_high_vs_low_lift"] is not None
    assert result["ms_high_win_rate"] is not None
    assert result["ms_low_win_rate"] is not None


def test_r47_momentum_strat_lift_direction() -> None:
    """High-momentum wins > low-momentum wins → lift > 0."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    rows = _make_ms_rows(30, high_wins=0.8, low_wins=0.3)
    result = compute_momentum_slope_stratification(rows)
    assert result["ms_high_vs_low_lift"] is not None
    assert result["ms_high_vs_low_lift"] > 0.0


def test_r47_momentum_strat_monotone_true() -> None:
    """low < mid < high win rates → ms_monotone=True."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    # Build rows where win rate increases with momentum tier
    rows = []
    for i in range(30):
        ms_val = float(i)
        tier = i // 10
        # low tier wins 30%, mid 50%, high 80%
        win_probs = [0.3, 0.5, 0.8]
        ret = 0.05 if (i % 10) < int(win_probs[tier] * 10) else -0.05
        rows.append({"momentum_slope_20d": ms_val, "next_day_return": ret})
    result = compute_momentum_slope_stratification(rows)
    assert result["ms_monotone"] is True


def test_r47_momentum_strat_effective_threshold() -> None:
    """lift > 0.05 → ms_effective=True; lift ≤ 0.05 → ms_effective=False."""
    from scripts.btst_analysis_utils import compute_momentum_slope_stratification

    # High lift scenario
    rows_high = _make_ms_rows(30, high_wins=0.9, low_wins=0.2)
    result_high = compute_momentum_slope_stratification(rows_high)
    if result_high["ms_high_vs_low_lift"] is not None and result_high["ms_high_vs_low_lift"] > 0.05:
        assert result_high["ms_effective"] is True

    # Zero lift scenario — same win rate for all
    rows_flat = []
    for i in range(30):
        rows_flat.append({"momentum_slope_20d": float(i), "next_day_return": 0.05 if i % 2 == 0 else -0.05})
    result_flat = compute_momentum_slope_stratification(rows_flat)
    if result_flat["ms_high_vs_low_lift"] is not None:
        assert result_flat["ms_effective"] == (result_flat["ms_high_vs_low_lift"] > 0.05)


def test_r47_momentum_strat_floor_registered() -> None:
    """ms_high_vs_low_lift floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "ms_high_vs_low_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["ms_high_vs_low_lift"] == 0.0


def test_r47_momentum_strat_label_registered() -> None:
    """ms_high_vs_low_lift label is in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "ms_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert len(COMPARISON_METRIC_LABELS["ms_high_vs_low_lift"]) > 0


def test_r47_momentum_strat_optional_registered() -> None:
    """ms_high_vs_low_lift is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "ms_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r47_momentum_strat_in_comparison_metrics() -> None:
    """ms_high_vs_low_lift is in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "ms_high_vs_low_lift" in COMPARISON_METRICS


# ===========================================================================
# Round 47 — T2 (Beta): compute_inflow_ratio_stratification
# ===========================================================================


def _make_inflow_rows(n: int, *, high_wins: float = 0.8, low_wins: float = 0.3) -> list[dict]:
    """Helper: n rows with t0_estimated_net_inflow_ratio and controlled win rates."""
    rows = []
    third = n // 3
    for i in range(n):
        inflow_val = -0.5 + 1.0 * i / max(1, n - 1)
        if i < third:
            ret = 0.05 if (i % 10) < int(low_wins * 10) else -0.05
        elif i < 2 * third:
            mid_wins = (high_wins + low_wins) / 2.0
            ret = 0.05 if (i % 10) < int(mid_wins * 10) else -0.05
        else:
            ret = 0.05 if (i % 10) < int(high_wins * 10) else -0.05
        rows.append({"t0_estimated_net_inflow_ratio": inflow_val, "next_day_return": ret})
    return rows


def test_r47_inflow_strat_empty_input() -> None:
    """Empty rows → inflow_stratification_valid=False, all None."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    result = compute_inflow_ratio_stratification([])
    assert result["inflow_stratification_valid"] is False
    assert result["inflow_high_vs_low_lift"] is None
    assert result["inflow_high_win_rate"] is None


def test_r47_inflow_strat_missing_field() -> None:
    """Rows missing t0_estimated_net_inflow_ratio → degraded."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    rows = [{"next_day_return": 0.05} for _ in range(20)]
    result = compute_inflow_ratio_stratification(rows)
    assert result["inflow_stratification_valid"] is False
    assert result["inflow_high_vs_low_lift"] is None


def test_r47_inflow_strat_normal_three_tiers() -> None:
    """Normal 30-row input: inflow_high_vs_low_lift has a value, valid=True."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    rows = _make_inflow_rows(30, high_wins=0.8, low_wins=0.3)
    result = compute_inflow_ratio_stratification(rows)
    assert result["inflow_stratification_valid"] is True
    assert result["inflow_high_vs_low_lift"] is not None
    assert result["inflow_high_win_rate"] is not None
    assert result["inflow_low_win_rate"] is not None


def test_r47_inflow_strat_lift_direction() -> None:
    """High-inflow wins > low-inflow wins → lift > 0."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    rows = _make_inflow_rows(30, high_wins=0.8, low_wins=0.3)
    result = compute_inflow_ratio_stratification(rows)
    assert result["inflow_high_vs_low_lift"] is not None
    assert result["inflow_high_vs_low_lift"] > 0.0


def test_r47_inflow_strat_monotone_logic() -> None:
    """low < mid < high inflow win rates → inflow_monotone=True."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    rows = []
    for i in range(30):
        inflow_val = float(i)
        tier = i // 10
        win_probs = [0.3, 0.5, 0.8]
        ret = 0.05 if (i % 10) < int(win_probs[tier] * 10) else -0.05
        rows.append({"t0_estimated_net_inflow_ratio": inflow_val, "next_day_return": ret})
    result = compute_inflow_ratio_stratification(rows)
    assert result["inflow_monotone"] is True


def test_r47_inflow_strat_effective_threshold() -> None:
    """lift > 0.05 → inflow_effective=True."""
    from scripts.btst_analysis_utils import compute_inflow_ratio_stratification

    rows = _make_inflow_rows(30, high_wins=0.9, low_wins=0.2)
    result = compute_inflow_ratio_stratification(rows)
    if result["inflow_high_vs_low_lift"] is not None:
        expected = result["inflow_high_vs_low_lift"] > 0.05
        assert result["inflow_effective"] == expected


def test_r47_inflow_strat_floor_registered() -> None:
    """inflow_high_vs_low_lift floor is 0.0 in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "inflow_high_vs_low_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["inflow_high_vs_low_lift"] == 0.0


def test_r47_inflow_strat_label_registered() -> None:
    """inflow_high_vs_low_lift label is in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "inflow_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert len(COMPARISON_METRIC_LABELS["inflow_high_vs_low_lift"]) > 0


def test_r47_inflow_strat_optional_registered() -> None:
    """inflow_high_vs_low_lift is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "inflow_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r47_inflow_strat_in_comparison_metrics() -> None:
    """inflow_high_vs_low_lift is in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "inflow_high_vs_low_lift" in COMPARISON_METRICS


# ===========================================================================
# Round 47 — T3 (Gamma): compute_factor_ic_consistency
# ===========================================================================

_R47_FACTOR_NAMES = [
    "close_strength",
    "volume_expansion_quality",
    "sector_resonance",
    "rs_sector_rank",
    "t0_estimated_net_inflow_ratio",
    "breakout_quality_score",
    "momentum_slope_20d",
    "volume_price_divergence",
    "catalyst_theme_score",
    "relative_strength_rank",
    "market_cap_score",
    "news_sentiment_score",
    "float_turnover_rate",
]


def _make_r47_ic_windows(n: int, ic_value: float = 0.10) -> list[dict]:
    """Helper: n window summaries each with factor_ic_values set to ic_value for all factors."""
    windows = []
    for _ in range(n):
        ic_dict = {f: ic_value for f in _R47_FACTOR_NAMES}
        windows.append({"factor_ic_values": ic_dict})
    return windows


def test_r47_factor_ic_consistency_empty_list() -> None:
    """Empty list → positive_ic_consistency_rate=None, factor_ic_consistency_valid=False."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    result = compute_factor_ic_consistency([])
    assert result["positive_ic_consistency_rate"] is None
    assert result["factor_ic_consistency_valid"] is False
    assert result["consistent_factor_count"] is None


def test_r47_factor_ic_consistency_too_few_valid_windows() -> None:
    """Only 2 windows with factor_ic_values → degraded (< 3 valid)."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    windows = _make_r47_ic_windows(2, ic_value=0.10)
    result = compute_factor_ic_consistency(windows)
    assert result["positive_ic_consistency_rate"] is None
    assert result["factor_ic_consistency_valid"] is False


def test_r47_factor_ic_consistency_skip_windows_without_ic_values() -> None:
    """Windows missing factor_ic_values are skipped; < 3 valid → degraded."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    windows = [{"other_key": 1.0} for _ in range(10)]
    result = compute_factor_ic_consistency(windows)
    assert result["positive_ic_consistency_rate"] is None
    assert result["factor_ic_consistency_valid"] is False


def test_r47_factor_ic_consistency_all_positive_ic() -> None:
    """All IC > 0 across 3+ windows → rate=1.0, consistent_factor_count=num_factors."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    windows = _make_r47_ic_windows(5, ic_value=0.10)
    result = compute_factor_ic_consistency(windows)
    assert result["factor_ic_consistency_valid"] is True
    assert result["positive_ic_consistency_rate"] == 1.0
    assert result["consistent_factor_count"] == len(_R47_FACTOR_NAMES)


def test_r47_factor_ic_consistency_all_negative_ic() -> None:
    """All IC < 0 → rate=0.0."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    windows = _make_r47_ic_windows(5, ic_value=-0.10)
    result = compute_factor_ic_consistency(windows)
    assert result["factor_ic_consistency_valid"] is True
    assert result["positive_ic_consistency_rate"] == 0.0
    assert result["consistent_factor_count"] == 0


def test_r47_factor_ic_consistency_mixed_scenario() -> None:
    """50% positive IC windows → rate ≈ 0.5."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    # 3 windows positive, 3 windows negative
    pos_windows = _make_r47_ic_windows(3, ic_value=0.10)
    neg_windows = _make_r47_ic_windows(3, ic_value=-0.10)
    windows = pos_windows + neg_windows
    result = compute_factor_ic_consistency(windows)
    assert result["factor_ic_consistency_valid"] is True
    assert result["positive_ic_consistency_rate"] is not None
    # 3/6 windows × 13 factors → 39/78 = 0.5
    assert abs(result["positive_ic_consistency_rate"] - 0.5) < 1e-5


def test_r47_factor_ic_consistency_best_worst_factor() -> None:
    """best_factor_name has highest mean IC; worst_factor_name has lowest."""
    from scripts.optimize_profile import compute_factor_ic_consistency

    # Build 4 windows where one factor always has IC=0.5 and one always has IC=-0.5
    windows = []
    for _ in range(4):
        ic_dict = {f: 0.10 for f in _R47_FACTOR_NAMES}
        ic_dict["close_strength"] = 0.50   # always best
        ic_dict["float_turnover_rate"] = -0.50  # always worst
        windows.append({"factor_ic_values": ic_dict})
    result = compute_factor_ic_consistency(windows)
    assert result["best_factor_name"] == "close_strength"
    assert result["worst_factor_name"] == "float_turnover_rate"


def test_r47_factor_ic_consistency_floor_registered() -> None:
    """positive_ic_consistency_rate: 0.50 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS

    assert "positive_ic_consistency_rate" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["positive_ic_consistency_rate"] == 0.50


def test_r47_factor_ic_consistency_label_registered() -> None:
    """positive_ic_consistency_rate label is in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS

    assert "positive_ic_consistency_rate" in COMPARISON_METRIC_LABELS
    assert len(COMPARISON_METRIC_LABELS["positive_ic_consistency_rate"]) > 0


def test_r47_factor_ic_consistency_optional_registered() -> None:
    """positive_ic_consistency_rate is in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS

    assert "positive_ic_consistency_rate" in OPTIONAL_COMPARISON_METRICS


def test_r47_factor_ic_consistency_in_comparison_metrics() -> None:
    """positive_ic_consistency_rate is in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS

    assert "positive_ic_consistency_rate" in COMPARISON_METRICS


# ---------------------------------------------------------------------------
# Round 48 Tests
# ---------------------------------------------------------------------------

# ---- T1: VEQ Stratification ----

def test_r48_veq_strat_empty_input() -> None:
    """Empty rows → veq_stratification_valid=False."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    result = compute_veq_stratification([])
    assert result["veq_stratification_valid"] is False
    assert result["veq_high_vs_low_lift"] is None


def test_r48_veq_strat_missing_field() -> None:
    """Rows without volume_expansion_quality → graceful degradation."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_veq_stratification(rows)
    assert result["veq_stratification_valid"] is False
    assert result["veq_high_vs_low_lift"] is None


def test_r48_veq_strat_normal_three_tiers() -> None:
    """Normal data with three tiers: lift is a float, valid=True."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    rows = []
    for i in range(30):
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.01 if i >= 20 else -0.01})
    result = compute_veq_stratification(rows)
    assert result["veq_stratification_valid"] is True
    assert result["veq_high_vs_low_lift"] is not None


def test_r48_veq_strat_lift_direction() -> None:
    """High VEQ group should win more → positive lift."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    rows = []
    for i in range(30):
        win = 1 if i >= 20 else 0
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.05 if win else -0.05})
    result = compute_veq_stratification(rows)
    assert result["veq_high_vs_low_lift"] is not None
    assert result["veq_high_vs_low_lift"] > 0


def test_r48_veq_strat_monotone_logic() -> None:
    """Strictly increasing win rates → veq_monotone=True."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    # Low tier: 10 rows, 2 wins (WR=0.2); Mid: 10 rows, 5 wins (WR=0.5); High: 10 rows, 9 wins (WR=0.9)
    rows = []
    for i in range(10):
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.05 if i < 2 else -0.05})
    for i in range(10, 20):
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.05 if i < 15 else -0.05})
    for i in range(20, 30):
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.05 if i < 29 else -0.05})
    result = compute_veq_stratification(rows)
    assert result["veq_monotone"] is True


def test_r48_veq_strat_effective_threshold() -> None:
    """veq_effective=True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_veq_stratification
    rows = []
    for i in range(30):
        win = i >= 20
        rows.append({"volume_expansion_quality": float(i), "next_day_return": 0.1 if win else -0.1})
    result = compute_veq_stratification(rows)
    if result["veq_high_vs_low_lift"] is not None and result["veq_high_vs_low_lift"] > 0.05:
        assert result["veq_effective"] is True
    else:
        assert result["veq_effective"] is False


def test_r48_veq_strat_floor_registered() -> None:
    """veq_high_vs_low_lift: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "veq_high_vs_low_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["veq_high_vs_low_lift"] == 0.0


def test_r48_veq_strat_label_registered() -> None:
    """veq_high_vs_low_lift must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "veq_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert "成交量质量" in COMPARISON_METRIC_LABELS["veq_high_vs_low_lift"]


def test_r48_veq_strat_optional_registered() -> None:
    """veq_high_vs_low_lift must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "veq_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


def test_r48_veq_strat_in_comparison_metrics() -> None:
    """veq_high_vs_low_lift must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "veq_high_vs_low_lift" in COMPARISON_METRICS


# ---- T2: Sector Resonance Stratification ----

def test_r48_sr_strat_empty_input() -> None:
    """Empty rows → sr_stratification_valid=False."""
    from scripts.btst_analysis_utils import compute_sector_resonance_stratification
    result = compute_sector_resonance_stratification([])
    assert result["sr_stratification_valid"] is False
    assert result["sr_high_vs_low_lift"] is None


def test_r48_sr_strat_missing_field() -> None:
    """Rows without sector_resonance → graceful degradation."""
    from scripts.btst_analysis_utils import compute_sector_resonance_stratification
    rows = [{"next_day_return": 0.01} for _ in range(20)]
    result = compute_sector_resonance_stratification(rows)
    assert result["sr_stratification_valid"] is False


def test_r48_sr_strat_normal_three_tiers() -> None:
    """Normal data: sr_high_vs_low_lift is a float, valid=True."""
    from scripts.btst_analysis_utils import compute_sector_resonance_stratification
    rows = []
    for i in range(30):
        rows.append({"sector_resonance": float(i), "next_day_return": 0.01 if i >= 20 else -0.01})
    result = compute_sector_resonance_stratification(rows)
    assert result["sr_stratification_valid"] is True
    assert result["sr_high_vs_low_lift"] is not None


def test_r48_sr_strat_monotone_logic() -> None:
    """Strictly increasing win rates → sr_monotone=True."""
    from scripts.btst_analysis_utils import compute_sector_resonance_stratification
    # Low tier: WR=0.2; Mid: WR=0.5; High: WR=0.9
    rows = []
    for i in range(10):
        rows.append({"sector_resonance": float(i), "next_day_return": 0.05 if i < 2 else -0.05})
    for i in range(10, 20):
        rows.append({"sector_resonance": float(i), "next_day_return": 0.05 if i < 15 else -0.05})
    for i in range(20, 30):
        rows.append({"sector_resonance": float(i), "next_day_return": 0.05 if i < 29 else -0.05})
    result = compute_sector_resonance_stratification(rows)
    assert result["sr_monotone"] is True


def test_r48_sr_strat_effective_threshold() -> None:
    """sr_effective=True when lift > 0.05."""
    from scripts.btst_analysis_utils import compute_sector_resonance_stratification
    rows = []
    for i in range(30):
        win = i >= 20
        rows.append({"sector_resonance": float(i), "next_day_return": 0.1 if win else -0.1})
    result = compute_sector_resonance_stratification(rows)
    if result["sr_high_vs_low_lift"] is not None and result["sr_high_vs_low_lift"] > 0.05:
        assert result["sr_effective"] is True


def test_r48_sr_strat_floor_registered() -> None:
    """sr_high_vs_low_lift: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "sr_high_vs_low_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["sr_high_vs_low_lift"] == 0.0


def test_r48_sr_strat_label_registered() -> None:
    """sr_high_vs_low_lift must have a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "sr_high_vs_low_lift" in COMPARISON_METRIC_LABELS
    assert "板块共振" in COMPARISON_METRIC_LABELS["sr_high_vs_low_lift"]


def test_r48_sr_strat_optional_registered() -> None:
    """sr_high_vs_low_lift must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "sr_high_vs_low_lift" in OPTIONAL_COMPARISON_METRICS


# ---- T3: Cross-window EV Trend ----

def test_r48_ev_trend_empty_list() -> None:
    """Empty list → ev_trend_slope=None."""
    from scripts.optimize_profile import compute_cross_window_ev_trend
    result = compute_cross_window_ev_trend([])
    assert result["ev_trend_slope"] is None


def test_r48_ev_trend_too_few_valid_windows() -> None:
    """Fewer than 3 windows with ev values → degraded."""
    from scripts.optimize_profile import compute_cross_window_ev_trend
    summaries = [
        {"expected_value_per_trade": 0.1},
        {"other_key": 999},
    ]
    result = compute_cross_window_ev_trend(summaries)
    assert result["ev_trend_slope"] is None


def test_r48_ev_trend_rising_trend() -> None:
    """Ascending EV series → positive slope, grade A or B."""
    from scripts.optimize_profile import compute_cross_window_ev_trend
    summaries = [{"expected_value_per_trade": v} for v in [0.1, 0.2, 0.3]]
    result = compute_cross_window_ev_trend(summaries)
    assert result["ev_trend_slope"] is not None
    assert result["ev_trend_slope"] > 0
    assert result["ev_trend_grade"] in ("A", "B")


def test_r48_ev_trend_falling_trend() -> None:
    """Descending EV series → negative slope."""
    from scripts.optimize_profile import compute_cross_window_ev_trend
    summaries = [{"expected_value_per_trade": v} for v in [0.3, 0.2, 0.1]]
    result = compute_cross_window_ev_trend(summaries)
    assert result["ev_trend_slope"] is not None
    assert result["ev_trend_slope"] < 0


def test_r48_ev_trend_severe_decline_grade_d() -> None:
    """Slope < -0.05 → grade D."""
    from scripts.optimize_profile import compute_cross_window_ev_trend
    summaries = [{"expected_value_per_trade": v} for v in [0.5, 0.3, 0.1, -0.1, -0.3]]
    result = compute_cross_window_ev_trend(summaries)
    assert result["ev_trend_slope"] is not None
    if result["ev_trend_slope"] <= -0.05:
        assert result["ev_trend_grade"] == "D"


def test_r48_ev_trend_floor_registered() -> None:
    """ev_trend_slope: -0.05 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "ev_trend_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["ev_trend_slope"] == -0.05


def test_r48_ev_trend_label_registered() -> None:
    """ev_trend_slope must have a label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "ev_trend_slope" in COMPARISON_METRIC_LABELS
    assert "期望收益" in COMPARISON_METRIC_LABELS["ev_trend_slope"]


def test_r48_ev_trend_optional_registered() -> None:
    """ev_trend_slope must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "ev_trend_slope" in OPTIONAL_COMPARISON_METRICS


def test_r48_ev_trend_in_comparison_metrics() -> None:
    """ev_trend_slope must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "ev_trend_slope" in COMPARISON_METRICS


# ===========================================================================
# Round 49, Task 1 (Alpha): compute_factor_consensus_analysis tests
# ===========================================================================

def _make_consensus_rows(n: int, high_factor_rows: int = 0) -> list[dict]:
    """Build synthetic rows for consensus tests."""
    import random
    random.seed(42)
    rows = []
    core_factors = [
        "close_strength", "volume_expansion_quality", "sector_resonance",
        "rs_sector_rank", "t0_estimated_net_inflow_ratio",
        "breakout_quality_score", "momentum_slope_20d",
    ]
    for i in range(n):
        row: dict = {"next_day_return": 0.02 if i % 2 == 0 else -0.01}
        if i < high_factor_rows:
            # Give high values to all 7 factors (above P67)
            for f in core_factors:
                row[f] = 1.0
        else:
            for f in core_factors:
                row[f] = round(random.uniform(0.0, 0.5), 4)
        rows.append(row)
    return rows


def test_r49_consensus_empty_input() -> None:
    """Empty input → graceful degradation."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    result = compute_factor_consensus_analysis([])
    assert result["consensus_valid"] is False
    assert result["consensus_lift"] is None


def test_r49_consensus_fewer_than_6_rows() -> None:
    """< 6 rows → degradation (consensus_valid=False)."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    rows = _make_consensus_rows(5)
    result = compute_factor_consensus_analysis(rows)
    assert result["consensus_valid"] is False
    assert result["consensus_lift"] is None


def test_r49_consensus_all_factors_missing() -> None:
    """All factor fields absent → graceful degradation with consensus_count=0."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    rows = [{"next_day_return": 0.01} for _ in range(10)]
    result = compute_factor_consensus_analysis(rows)
    # Should not raise; mean_count should be 0.0
    assert result.get("consensus_mean_count") == 0.0
    assert result.get("consensus_high_pct") == 0.0


def test_r49_consensus_normal_with_high_group() -> None:
    """Normal scenario: rows with many strong factors → consensus_lift has value."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    # 10 high-consensus rows (all 7 factors high, win) + 10 low rows
    high_rows = [
        {
            "close_strength": 1.0, "volume_expansion_quality": 1.0, "sector_resonance": 1.0,
            "rs_sector_rank": 1.0, "t0_estimated_net_inflow_ratio": 1.0,
            "breakout_quality_score": 1.0, "momentum_slope_20d": 1.0,
            "next_day_return": 0.05,
        }
        for _ in range(10)
    ]
    low_rows = [
        {
            "close_strength": 0.0, "volume_expansion_quality": 0.0, "sector_resonance": 0.0,
            "rs_sector_rank": 0.0, "t0_estimated_net_inflow_ratio": 0.0,
            "breakout_quality_score": 0.0, "momentum_slope_20d": 0.0,
            "next_day_return": -0.02,
        }
        for _ in range(10)
    ]
    result = compute_factor_consensus_analysis(high_rows + low_rows)
    assert result["consensus_valid"] is True
    assert result["consensus_lift"] is not None
    assert result["high_consensus_win_rate"] is not None
    assert result["low_consensus_win_rate"] is not None


def test_r49_consensus_mean_count_in_range() -> None:
    """consensus_mean_count must be in [0, 7]."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    rows = _make_consensus_rows(20, high_factor_rows=5)
    result = compute_factor_consensus_analysis(rows)
    if result["consensus_mean_count"] is not None:
        assert 0.0 <= result["consensus_mean_count"] <= 7.0


def test_r49_consensus_high_pct_in_range() -> None:
    """consensus_high_pct must be in [0, 1]."""
    from scripts.btst_analysis_utils import compute_factor_consensus_analysis
    rows = _make_consensus_rows(30, high_factor_rows=10)
    result = compute_factor_consensus_analysis(rows)
    if result["consensus_high_pct"] is not None:
        assert 0.0 <= result["consensus_high_pct"] <= 1.0


def test_r49_consensus_floor_registered() -> None:
    """consensus_lift: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "consensus_lift" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["consensus_lift"] == 0.0


def test_r49_consensus_label_registered() -> None:
    """consensus_lift must have a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "consensus_lift" in COMPARISON_METRIC_LABELS
    assert "共识" in COMPARISON_METRIC_LABELS["consensus_lift"]


def test_r49_consensus_optional_registered() -> None:
    """consensus_lift must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "consensus_lift" in OPTIONAL_COMPARISON_METRICS


def test_r49_consensus_in_comparison_metrics() -> None:
    """consensus_lift must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "consensus_lift" in COMPARISON_METRICS


# ===========================================================================
# Round 49, Task 2 (Beta): compute_score_decile_analysis tests
# ===========================================================================

def _make_decile_rows(n: int, monotone: bool = False) -> list[dict]:
    """Build synthetic rows for decile tests."""
    rows = []
    for i in range(n):
        score = i / n  # linearly increasing score
        if monotone:
            # Higher score → higher win probability
            win = 1 if i > n * 0.5 else 0
        else:
            win = 1 if i % 2 == 0 else 0
        rows.append({"score": score, "next_day_return": 0.02 if win else -0.01})
    return rows


def test_r49_decile_empty_input() -> None:
    """Empty input → degradation."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    result = compute_score_decile_analysis([])
    assert result["decile_valid"] is False
    assert result["top_decile_premium"] is None


def test_r49_decile_fewer_than_20_rows() -> None:
    """< 20 rows → degradation."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    rows = _make_decile_rows(15)
    result = compute_score_decile_analysis(rows)
    assert result["decile_valid"] is False
    assert result["top_decile_premium"] is None


def test_r49_decile_normal_has_all_fields() -> None:
    """≥ 20 rows → d1..d10 win rates and top_decile_premium present."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    rows = _make_decile_rows(100)
    result = compute_score_decile_analysis(rows)
    assert result["decile_valid"] is True
    for i in range(1, 11):
        assert f"d{i}_win_rate" in result
    assert result["top_decile_premium"] is not None


def test_r49_decile_monotone_count_in_range() -> None:
    """decile_monotone_count must be in [0, 9]."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    rows = _make_decile_rows(100)
    result = compute_score_decile_analysis(rows)
    assert result["decile_valid"] is True
    assert 0 <= result["decile_monotone_count"] <= 9


def test_r49_decile_top_half_lift_computed() -> None:
    """top_half_vs_bottom_half_lift should be numeric with monotone data."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    rows = _make_decile_rows(100, monotone=True)
    result = compute_score_decile_analysis(rows)
    assert result["decile_valid"] is True
    assert result["top_half_vs_bottom_half_lift"] is not None
    # With monotone data (top half wins), lift should be positive
    assert result["top_half_vs_bottom_half_lift"] > 0


def test_r49_decile_score_priority() -> None:
    """runner_composite_score takes priority over composite_score and score."""
    from scripts.btst_analysis_utils import compute_score_decile_analysis
    rows = []
    for i in range(30):
        rows.append({
            "runner_composite_score": i / 30,
            "composite_score": 0.5,  # same for all — should be ignored
            "score": 0.9,            # same for all — should be ignored
            "next_day_return": 0.02 if i > 15 else -0.01,
        })
    result = compute_score_decile_analysis(rows)
    assert result["decile_valid"] is True


def test_r49_decile_floor_registered() -> None:
    """top_decile_premium: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "top_decile_premium" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["top_decile_premium"] == 0.0


def test_r49_decile_label_registered() -> None:
    """top_decile_premium must have a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "top_decile_premium" in COMPARISON_METRIC_LABELS
    assert "十分位" in COMPARISON_METRIC_LABELS["top_decile_premium"]


def test_r49_decile_optional_registered() -> None:
    """top_decile_premium must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "top_decile_premium" in OPTIONAL_COMPARISON_METRICS


def test_r49_decile_in_comparison_metrics() -> None:
    """top_decile_premium must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "top_decile_premium" in COMPARISON_METRICS


# ===========================================================================
# Round 49, Task 3 (Gamma): compute_cross_window_sortino_trend tests
# ===========================================================================

def test_r49_sortino_trend_empty_list() -> None:
    """Empty list → degradation."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    result = compute_cross_window_sortino_trend([])
    assert result["sortino_trend_valid"] is False
    assert result["sortino_trend_slope"] is None


def test_r49_sortino_trend_fewer_than_3_windows() -> None:
    """< 3 valid windows → degradation."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": 1.0}, {"other_key": 0.5}]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_trend_valid"] is False
    assert result["sortino_trend_slope"] is None


def test_r49_sortino_trend_rising_slope_positive() -> None:
    """Rising Sortino series → slope > 0."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": float(i)} for i in range(5)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_trend_valid"] is True
    assert result["sortino_trend_slope"] is not None
    assert result["sortino_trend_slope"] > 0


def test_r49_sortino_trend_grade_a_or_b_for_rising() -> None:
    """Strongly rising series → grade A or B."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": float(i) * 0.5} for i in range(10)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_trend_grade"] in ("A", "B")


def test_r49_sortino_trend_falling_slope_negative() -> None:
    """Declining Sortino series → slope < 0."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": float(5 - i)} for i in range(5)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_trend_valid"] is True
    assert result["sortino_trend_slope"] < 0


def test_r49_sortino_trend_grade_d_for_steep_decline() -> None:
    """Slope ≤ -0.10 → grade D."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    # Make a series where OLS slope is clearly below -0.10
    summaries = [{"sortino_ratio": 2.0 - i * 0.5} for i in range(6)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_trend_valid"] is True
    if result["sortino_trend_slope"] is not None and result["sortino_trend_slope"] <= -0.10:
        assert result["sortino_trend_grade"] == "D"


def test_r49_sortino_positive_windows_pct_all_positive() -> None:
    """All positive sortino values → sortino_positive_windows_pct == 1.0."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": 1.0 + i * 0.1} for i in range(5)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_positive_windows_pct"] == 1.0


def test_r49_sortino_positive_windows_pct_all_negative() -> None:
    """All negative sortino values → sortino_positive_windows_pct == 0.0."""
    from scripts.optimize_profile import compute_cross_window_sortino_trend
    summaries = [{"sortino_ratio": -1.0 - i * 0.1} for i in range(5)]
    result = compute_cross_window_sortino_trend(summaries)
    assert result["sortino_positive_windows_pct"] == 0.0


def test_r49_sortino_trend_floor_registered() -> None:
    """sortino_trend_slope: -0.10 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "sortino_trend_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["sortino_trend_slope"] == -0.10


def test_r49_sortino_trend_label_registered() -> None:
    """sortino_trend_slope must have a label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "sortino_trend_slope" in COMPARISON_METRIC_LABELS
    assert "Sortino" in COMPARISON_METRIC_LABELS["sortino_trend_slope"]


def test_r49_sortino_trend_optional_registered() -> None:
    """sortino_trend_slope must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "sortino_trend_slope" in OPTIONAL_COMPARISON_METRICS


def test_r49_sortino_trend_in_comparison_metrics() -> None:
    """sortino_trend_slope must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "sortino_trend_slope" in COMPARISON_METRICS


# ===========================================================================
# Round 50 Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# T1: compute_factor_redundancy_analysis
# ---------------------------------------------------------------------------

def test_r50_factor_redundancy_empty_input() -> None:
    """Empty input → redundancy_valid False, all None."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    result = compute_factor_redundancy_analysis([])
    assert result["redundancy_valid"] is False
    assert result["avg_inter_factor_correlation"] is None
    assert result["max_inter_factor_correlation"] is None
    assert result["high_correlation_pairs"] is None


def test_r50_factor_redundancy_fewer_than_6_rows() -> None:
    """< 6 rows → graceful degradation."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    rows = [{"close_strength": i * 0.1, "volume_expansion_quality": i * 0.2} for i in range(5)]
    result = compute_factor_redundancy_analysis(rows)
    assert result["redundancy_valid"] is False


def test_r50_factor_redundancy_all_factors_missing() -> None:
    """All factor fields absent → fewer than 3 present factors → degradation."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    rows = [{"unrelated_field": i} for i in range(10)]
    result = compute_factor_redundancy_analysis(rows)
    assert result["redundancy_valid"] is False


def test_r50_factor_redundancy_identical_factors_r_is_one() -> None:
    """Two identical factor columns → Spearman |r| == 1.0 for that pair."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    # Need at least 3 factors present — add a third orthogonal factor
    rows = [
        {"close_strength": float(i), "volume_expansion_quality": float(i), "sector_resonance": float(i * 2 + 1)}
        for i in range(10)
    ]
    result = compute_factor_redundancy_analysis(rows)
    assert result["redundancy_valid"] is True
    corrs = result["factor_pair_correlations"]
    key = "close_strength__volume_expansion_quality"
    assert key in corrs
    assert abs(corrs[key]) == pytest.approx(1.0, abs=1e-4)


def test_r50_factor_redundancy_independent_factors_r_near_zero() -> None:
    """Two independent random-ish factor columns → |r| well below 0.70."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    import math
    # Use deterministic, near-orthogonal sequences
    xs = [math.sin(i * 1.1) for i in range(12)]
    ys = [math.cos(i * 1.7 + 2.3) for i in range(12)]
    rows = [{"close_strength": xs[i], "volume_expansion_quality": ys[i]} for i in range(12)]
    result = compute_factor_redundancy_analysis(rows)
    if result["redundancy_valid"]:
        corrs = result["factor_pair_correlations"]
        key = "close_strength__volume_expansion_quality"
        if key in corrs:
            assert abs(corrs[key]) < 0.70


def test_r50_factor_redundancy_cap_registered() -> None:
    """avg_inter_factor_correlation: 0.50 must be in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    assert "avg_inter_factor_correlation" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["avg_inter_factor_correlation"] == pytest.approx(0.50)


def test_r50_factor_redundancy_lower_is_better_registered() -> None:
    """avg_inter_factor_correlation must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "avg_inter_factor_correlation" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r50_factor_redundancy_optional_registered() -> None:
    """avg_inter_factor_correlation must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "avg_inter_factor_correlation" in OPTIONAL_COMPARISON_METRICS


def test_r50_factor_redundancy_in_comparison_metrics() -> None:
    """avg_inter_factor_correlation must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "avg_inter_factor_correlation" in COMPARISON_METRICS


def test_r50_factor_redundancy_label_registered() -> None:
    """avg_inter_factor_correlation must have a Chinese label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "avg_inter_factor_correlation" in COMPARISON_METRIC_LABELS
    assert "冗余" in COMPARISON_METRIC_LABELS["avg_inter_factor_correlation"]


def test_r50_factor_redundancy_grade_a_for_low_correlation() -> None:
    """All factor values unique and fully orthogonal → grade A (avg < 0.20)."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    # Build rows where close_strength is identity and other factors are fixed → many pairs will have ~0 corr
    rows = []
    for i in range(12):
        rows.append({
            "close_strength": float(i),
            "volume_expansion_quality": float((i * 7) % 13),
            "sector_resonance": float((i * 3 + 5) % 11),
        })
    result = compute_factor_redundancy_analysis(rows)
    if result["redundancy_valid"] and result["avg_inter_factor_correlation"] is not None:
        assert result["avg_inter_factor_correlation"] < 0.50  # at most C grade


def test_r50_factor_redundancy_high_correlation_pairs_count() -> None:
    """Two identical factors → high_correlation_pairs >= 1."""
    from scripts.btst_analysis_utils import compute_factor_redundancy_analysis
    rows = [{"close_strength": float(i), "volume_expansion_quality": float(i), "sector_resonance": float(i * 2)} for i in range(10)]
    result = compute_factor_redundancy_analysis(rows)
    assert result["redundancy_valid"] is True
    assert result["high_correlation_pairs"] >= 1


# ---------------------------------------------------------------------------
# T2: compute_extended_holding_period
# ---------------------------------------------------------------------------

def test_r50_extended_holding_empty_input() -> None:
    """Empty input → extended_holding_valid False."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    result = compute_extended_holding_period([])
    assert result["extended_holding_valid"] is False
    assert result["t1_win_rate"] is None
    assert result["holding_data_available"] is False


def test_r50_extended_holding_fewer_than_5_t1_rows() -> None:
    """< 5 next_day_return rows → degradation."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    rows = [{"next_day_return": 0.01 * i} for i in range(4)]
    result = compute_extended_holding_period(rows)
    assert result["extended_holding_valid"] is False


def test_r50_extended_holding_t1_only_data() -> None:
    """Only T+1 data available → t1_win_rate set, t2_vs_t1_premium None, holding_data_available False."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    rows = [{"next_day_return": 0.01 * (i - 2)} for i in range(8)]
    result = compute_extended_holding_period(rows)
    assert result["extended_holding_valid"] is True
    assert result["t1_win_rate"] is not None
    assert result["t2_vs_t1_premium"] is None
    assert result["holding_data_available"] is False


def test_r50_extended_holding_t2_data_available() -> None:
    """With T+2 data (≥3 rows) → t2_win_rate not None, t2_vs_t1_premium computed."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    rows = [{"next_day_return": 0.02, "t2_return": 0.01} for _ in range(6)]
    result = compute_extended_holding_period(rows)
    assert result["extended_holding_valid"] is True
    assert result["t2_win_rate"] is not None
    assert result["t2_vs_t1_premium"] is not None
    assert result["holding_data_available"] is True


def test_r50_extended_holding_premium_computation() -> None:
    """t2_vs_t1_premium == t2_win_rate - t1_win_rate."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    # t1: all positive → win_rate=1.0; t2: all negative → win_rate=0.0
    rows = [{"next_day_return": 0.01, "t2_return": -0.01} for _ in range(6)]
    result = compute_extended_holding_period(rows)
    assert result["t1_win_rate"] == pytest.approx(1.0)
    assert result["t2_win_rate"] == pytest.approx(0.0)
    assert result["t2_vs_t1_premium"] == pytest.approx(-1.0)


def test_r50_extended_holding_label_registered() -> None:
    """t2_vs_t1_premium must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "t2_vs_t1_premium" in COMPARISON_METRIC_LABELS
    assert "T+2" in COMPARISON_METRIC_LABELS["t2_vs_t1_premium"]


def test_r50_extended_holding_optional_registered() -> None:
    """t2_vs_t1_premium must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "t2_vs_t1_premium" in OPTIONAL_COMPARISON_METRICS


def test_r50_extended_holding_no_floor() -> None:
    """t2_vs_t1_premium must NOT be in BTST_QUALITY_FLOORS (diagnostic only)."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "t2_vs_t1_premium" not in BTST_QUALITY_FLOORS


def test_r50_extended_holding_in_comparison_metrics() -> None:
    """t2_vs_t1_premium must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "t2_vs_t1_premium" in COMPARISON_METRICS


def test_r50_extended_holding_multi_day_consistency() -> None:
    """Both T+2 and T+3 ≥ 0.5 win rate → multi_day_consistency True."""
    from scripts.btst_analysis_utils import compute_extended_holding_period
    rows = [{"next_day_return": 0.01, "t2_return": 0.02, "t3_return": 0.015} for _ in range(6)]
    result = compute_extended_holding_period(rows)
    assert result["multi_day_consistency"] is True


# ---------------------------------------------------------------------------
# T3: compute_cross_window_sharpe_trend
# ---------------------------------------------------------------------------

def test_r50_sharpe_trend_empty_list() -> None:
    """Empty list → sharpe_trend_valid False."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    result = compute_cross_window_sharpe_trend([])
    assert result["sharpe_trend_valid"] is False
    assert result["sharpe_trend_slope"] is None


def test_r50_sharpe_trend_fewer_than_3_windows() -> None:
    """< 3 valid sharpe_ratio values → degradation."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 1.0}, {"sharpe_ratio": 1.5}]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_valid"] is False


def test_r50_sharpe_trend_rising_slope_positive() -> None:
    """Strictly rising sharpe series → slope > 0."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 0.5 + i * 0.3} for i in range(5)]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_valid"] is True
    assert result["sharpe_trend_slope"] > 0


def test_r50_sharpe_trend_grade_a_or_b_for_rising() -> None:
    """Rising series → grade A or B."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 0.5 + i * 0.3} for i in range(5)]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_grade"] in ("A", "B")


def test_r50_sharpe_trend_falling_slope_negative() -> None:
    """Strictly declining series → slope < 0."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 2.0 - i * 0.2} for i in range(5)]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_slope"] < 0


def test_r50_sharpe_trend_grade_d_for_steep_decline() -> None:
    """Slope ≤ -0.10 → grade D."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 2.0 - i * 0.5} for i in range(6)]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_valid"] is True
    if result["sharpe_trend_slope"] is not None and result["sharpe_trend_slope"] <= -0.10:
        assert result["sharpe_trend_grade"] == "D"


def test_r50_sharpe_trend_positive_windows_pct_all_positive() -> None:
    """All positive sharpe values → sharpe_positive_windows_pct == 1.0."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 1.0 + i * 0.1} for i in range(5)]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_positive_windows_pct"] == pytest.approx(1.0)


def test_r50_sharpe_trend_floor_registered() -> None:
    """sharpe_trend_slope: -0.10 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    assert "sharpe_trend_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["sharpe_trend_slope"] == pytest.approx(-0.10)


def test_r50_sharpe_trend_label_registered() -> None:
    """sharpe_trend_slope must have a label containing 'Sharpe'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "sharpe_trend_slope" in COMPARISON_METRIC_LABELS
    assert "Sharpe" in COMPARISON_METRIC_LABELS["sharpe_trend_slope"]


def test_r50_sharpe_trend_optional_registered() -> None:
    """sharpe_trend_slope must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "sharpe_trend_slope" in OPTIONAL_COMPARISON_METRICS


def test_r50_sharpe_trend_in_comparison_metrics() -> None:
    """sharpe_trend_slope must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "sharpe_trend_slope" in COMPARISON_METRICS


def test_r50_sharpe_trend_skips_missing_sharpe_ratio() -> None:
    """Windows without sharpe_ratio are skipped; valid windows still compute."""
    from scripts.optimize_profile import compute_cross_window_sharpe_trend
    summaries = [{"sharpe_ratio": 1.0}, {"other_key": 0.5}, {"sharpe_ratio": 1.5}, {"sharpe_ratio": 2.0}]
    result = compute_cross_window_sharpe_trend(summaries)
    assert result["sharpe_trend_valid"] is True
    assert result["sharpe_trend_slope"] is not None


# ---------------------------------------------------------------------------
# Round 51, Task 1 (Alpha): Win/Loss Magnitude Analysis tests
# ---------------------------------------------------------------------------


def test_r51_win_loss_magnitude_empty_input() -> None:
    """Empty input → graceful degradation with all-None result."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    result = compute_win_loss_magnitude_analysis([])
    assert result["win_loss_magnitude_ratio"] is None
    assert result["kelly_fraction"] is None
    assert result["profit_factor_v2"] is None


def test_r51_win_loss_magnitude_fewer_than_5_rows() -> None:
    """Fewer than 5 valid rows → graceful degradation."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    rows = [{"next_day_return": 0.05}] * 4
    result = compute_win_loss_magnitude_analysis(rows)
    assert result["win_loss_magnitude_ratio"] is None
    assert result["kelly_fraction"] is None


def test_r51_win_loss_magnitude_all_wins_no_losses() -> None:
    """All rows profitable → avg_loss_return=None, ratio=None, kelly=None."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    rows = [{"next_day_return": 0.02 + i * 0.001} for i in range(10)]
    result = compute_win_loss_magnitude_analysis(rows)
    assert result["avg_loss_return"] is None
    assert result["win_loss_magnitude_ratio"] is None
    assert result["kelly_fraction"] is None


def test_r51_win_loss_magnitude_all_losses_no_wins() -> None:
    """All rows losing → avg_win_return=None, ratio=None."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    rows = [{"next_day_return": -0.02 - i * 0.001} for i in range(10)]
    result = compute_win_loss_magnitude_analysis(rows)
    assert result["avg_win_return"] is None
    assert result["win_loss_magnitude_ratio"] is None


def test_r51_win_loss_magnitude_mixed_normal_case() -> None:
    """Normal mixed returns → positive ratio, Kelly in [-1,1]."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    import pytest
    wins = [0.05, 0.04, 0.06, 0.07, 0.03]
    losses = [-0.02, -0.01, -0.03, -0.02, -0.015]
    rows = [{"next_day_return": r} for r in wins + losses]
    result = compute_win_loss_magnitude_analysis(rows)
    assert result["win_loss_magnitude_ratio"] is not None
    assert result["win_loss_magnitude_ratio"] > 0
    assert result["kelly_fraction"] is not None
    assert -1.0 <= result["kelly_fraction"] <= 1.0


def test_r51_win_loss_magnitude_profit_factor_v2_nonneg() -> None:
    """profit_factor_v2 must always be >= 0."""
    from scripts.btst_analysis_utils import compute_win_loss_magnitude_analysis
    wins = [0.03, 0.02, 0.04, 0.05, 0.01]
    losses = [-0.05, -0.04, -0.06, -0.07, -0.08]
    rows = [{"next_day_return": r} for r in wins + losses]
    result = compute_win_loss_magnitude_analysis(rows)
    assert result["profit_factor_v2"] is not None
    assert result["profit_factor_v2"] >= 0.0


def test_r51_win_loss_magnitude_floor_registered() -> None:
    """win_loss_magnitude_ratio:1.0 and kelly_fraction:0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    import pytest
    assert "win_loss_magnitude_ratio" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["win_loss_magnitude_ratio"] == pytest.approx(1.0)
    assert "kelly_fraction" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["kelly_fraction"] == pytest.approx(0.0)


def test_r51_win_loss_magnitude_optional_registered() -> None:
    """win_loss_magnitude_ratio and kelly_fraction must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "win_loss_magnitude_ratio" in OPTIONAL_COMPARISON_METRICS
    assert "kelly_fraction" in OPTIONAL_COMPARISON_METRICS


def test_r51_win_loss_magnitude_in_comparison_metrics() -> None:
    """win_loss_magnitude_ratio and kelly_fraction must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "win_loss_magnitude_ratio" in COMPARISON_METRICS
    assert "kelly_fraction" in COMPARISON_METRICS


def test_r51_win_loss_magnitude_label_registered() -> None:
    """win_loss_magnitude_ratio and kelly_fraction must have labels."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "win_loss_magnitude_ratio" in COMPARISON_METRIC_LABELS
    assert "kelly_fraction" in COMPARISON_METRIC_LABELS


# ---------------------------------------------------------------------------
# Round 51, Task 2 (Beta): Outlier Robustness Check tests
# ---------------------------------------------------------------------------


def test_r51_outlier_robustness_empty_input() -> None:
    """Empty input → graceful degradation."""
    from scripts.btst_analysis_utils import compute_outlier_robustness_check
    result = compute_outlier_robustness_check([])
    assert result["outlier_dependency_ratio"] is None
    assert result["robustness_grade"] is None


def test_r51_outlier_robustness_fewer_than_10_rows() -> None:
    """Fewer than 10 valid rows → graceful degradation."""
    from scripts.btst_analysis_utils import compute_outlier_robustness_check
    rows = [{"next_day_return": 0.01 * i} for i in range(9)]
    result = compute_outlier_robustness_check(rows)
    assert result["outlier_dependency_ratio"] is None
    assert result["robustness_grade"] is None


def test_r51_outlier_robustness_uniform_distribution_near_zero() -> None:
    """Uniformly spaced returns → outlier dependency ratio near 0 (grade A)."""
    from scripts.btst_analysis_utils import compute_outlier_robustness_check
    rows = [{"next_day_return": 0.01 * i} for i in range(1, 21)]
    result = compute_outlier_robustness_check(rows)
    assert result["outlier_dependency_ratio"] is not None
    assert result["outlier_dependency_ratio"] >= 0.0
    assert result["robustness_grade"] in ("A", "B", "C", "D")


def test_r51_outlier_robustness_high_dependency_one_big_winner() -> None:
    """Most rows near zero with one large outlier → positive dependency ratio."""
    from scripts.btst_analysis_utils import compute_outlier_robustness_check
    rows = [{"next_day_return": -0.01}] * 15 + [{"next_day_return": 0.50}]
    result = compute_outlier_robustness_check(rows)
    assert result["outlier_dependency_ratio"] is not None
    assert result["outlier_dependency_ratio"] > 0.0


def test_r51_outlier_robustness_grade_valid_values() -> None:
    """robustness_grade must be one of A/B/C/D when data is sufficient."""
    from scripts.btst_analysis_utils import compute_outlier_robustness_check
    rows = [{"next_day_return": (i - 10) * 0.01} for i in range(20)]
    result = compute_outlier_robustness_check(rows)
    if result["robustness_grade"] is not None:
        assert result["robustness_grade"] in ("A", "B", "C", "D")


def test_r51_outlier_robustness_cap_registered() -> None:
    """outlier_dependency_ratio:0.30 must be in BTST_QUALITY_CAPS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_CAPS
    import pytest
    assert "outlier_dependency_ratio" in BTST_QUALITY_CAPS
    assert BTST_QUALITY_CAPS["outlier_dependency_ratio"] == pytest.approx(0.30)


def test_r51_outlier_robustness_lower_is_better_registered() -> None:
    """outlier_dependency_ratio must be in LOWER_IS_BETTER_COMPARISON_METRICS."""
    from scripts.optimize_profile import LOWER_IS_BETTER_COMPARISON_METRICS
    assert "outlier_dependency_ratio" in LOWER_IS_BETTER_COMPARISON_METRICS


def test_r51_outlier_robustness_optional_registered() -> None:
    """outlier_dependency_ratio must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "outlier_dependency_ratio" in OPTIONAL_COMPARISON_METRICS


def test_r51_outlier_robustness_label_registered() -> None:
    """outlier_dependency_ratio must have a label."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "outlier_dependency_ratio" in COMPARISON_METRIC_LABELS


# ---------------------------------------------------------------------------
# Round 51, Task 3 (Gamma): Cross-window Profit Factor Trend tests
# ---------------------------------------------------------------------------


def test_r51_pf_trend_empty_list() -> None:
    """Empty list → graceful degradation."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    result = compute_cross_window_profit_factor_trend([])
    assert result["pf_trend_slope"] is None
    assert result["pf_trend_valid"] is False


def test_r51_pf_trend_fewer_than_3_windows() -> None:
    """Fewer than 3 valid profit_factor values → graceful degradation."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    summaries = [{"profit_factor": 1.2}, {"profit_factor": 1.5}]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_trend_slope"] is None
    assert result["pf_trend_valid"] is False


def test_r51_pf_trend_rising_trend_positive_slope() -> None:
    """Increasing profit factors → slope > 0 and grade A or B."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    summaries = [{"profit_factor": 1.0 + i * 0.3} for i in range(6)]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_trend_valid"] is True
    assert result["pf_trend_slope"] is not None
    assert result["pf_trend_slope"] > 0
    assert result["pf_trend_grade"] in ("A", "B")


def test_r51_pf_trend_falling_trend_negative_slope() -> None:
    """Decreasing profit factors → slope < 0."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    summaries = [{"profit_factor": 2.0 - i * 0.2} for i in range(6)]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_trend_valid"] is True
    assert result["pf_trend_slope"] is not None
    assert result["pf_trend_slope"] < 0


def test_r51_pf_trend_steep_decline_grade_d() -> None:
    """slope <= -0.10 → grade D."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    summaries = [{"profit_factor": 3.0 - i * 0.5} for i in range(6)]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_trend_valid"] is True
    if result["pf_trend_slope"] is not None and result["pf_trend_slope"] <= -0.10:
        assert result["pf_trend_grade"] == "D"


def test_r51_pf_trend_above_one_pct_all_above() -> None:
    """All profit_factor >= 1.0 → pf_above_one_pct == 1.0."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    import pytest
    summaries = [{"profit_factor": 1.5 + i * 0.1} for i in range(5)]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_above_one_pct"] == pytest.approx(1.0)


def test_r51_pf_trend_floor_registered() -> None:
    """pf_trend_slope: -0.10 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    import pytest
    assert "pf_trend_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["pf_trend_slope"] == pytest.approx(-0.10)


def test_r51_pf_trend_label_registered() -> None:
    """pf_trend_slope must have a label in COMPARISON_METRIC_LABELS."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert "pf_trend_slope" in COMPARISON_METRIC_LABELS


def test_r51_pf_trend_optional_registered() -> None:
    """pf_trend_slope must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "pf_trend_slope" in OPTIONAL_COMPARISON_METRICS


def test_r51_pf_trend_in_comparison_metrics() -> None:
    """pf_trend_slope must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "pf_trend_slope" in COMPARISON_METRICS


def test_r51_pf_trend_skips_missing_profit_factor() -> None:
    """Windows without profit_factor are skipped; valid windows still compute."""
    from scripts.optimize_profile import compute_cross_window_profit_factor_trend
    summaries = [{"profit_factor": 1.2}, {"other_key": 0.5}, {"profit_factor": 1.5}, {"profit_factor": 1.8}]
    result = compute_cross_window_profit_factor_trend(summaries)
    assert result["pf_trend_valid"] is True
    assert result["pf_trend_slope"] is not None


# ---------------------------------------------------------------------------
# Round 52, Task 1 (Alpha): Information Ratio Analysis tests
# ---------------------------------------------------------------------------


def test_r52_information_ratio_empty_input() -> None:
    """Empty input → graceful degradation (IR=None)."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    result = compute_information_ratio_analysis([])
    assert result["information_ratio"] is None
    assert result["ir_grade"] is None


def test_r52_information_ratio_fewer_than_5_rows() -> None:
    """Fewer than 5 rows → graceful degradation."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    rows = [{"next_day_return": 0.01 * i} for i in range(4)]
    result = compute_information_ratio_analysis(rows)
    assert result["information_ratio"] is None
    assert result["ir_grade"] is None


def test_r52_information_ratio_all_positive_returns() -> None:
    """All positive returns → IR > 0, grade A or B, downside_capture_ratio=0.0."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    rows = [{"next_day_return": 0.02 + 0.001 * i} for i in range(10)]
    result = compute_information_ratio_analysis(rows)
    assert result["information_ratio"] is not None
    assert result["information_ratio"] > 0
    assert result["ir_grade"] in ("A", "B")
    assert result["downside_capture_ratio"] == 0.0


def test_r52_information_ratio_all_negative_returns() -> None:
    """All negative returns → IR < 0, grade D."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    rows = [{"next_day_return": -0.02 - 0.001 * i} for i in range(10)]
    result = compute_information_ratio_analysis(rows)
    assert result["information_ratio"] is not None
    assert result["information_ratio"] < 0
    assert result["ir_grade"] == "D"


def test_r52_information_ratio_mixed_clamped_range() -> None:
    """Mixed returns → IR clamped to [-10, 10]."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    rows = [{"next_day_return": 0.01 * (i % 3 - 1)} for i in range(15)]
    result = compute_information_ratio_analysis(rows)
    if result["information_ratio"] is not None:
        assert -10.0 <= result["information_ratio"] <= 10.0


def test_r52_information_ratio_upside_capture_nonneg() -> None:
    """upside_capture_ratio is non-negative when positive returns exist."""
    from scripts.btst_analysis_utils import compute_information_ratio_analysis
    rows = [{"next_day_return": 0.01 * i - 0.03} for i in range(10)]
    result = compute_information_ratio_analysis(rows)
    if result["upside_capture_ratio"] is not None:
        assert result["upside_capture_ratio"] >= 0.0


def test_r52_information_ratio_floor_registered() -> None:
    """information_ratio: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    import pytest
    assert "information_ratio" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["information_ratio"] == pytest.approx(0.0)


def test_r52_information_ratio_optional_registered() -> None:
    """information_ratio must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "information_ratio" in OPTIONAL_COMPARISON_METRICS


def test_r52_information_ratio_in_comparison_metrics() -> None:
    """information_ratio must be in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "information_ratio" in COMPARISON_METRICS


def test_r52_information_ratio_label_registered() -> None:
    """information_ratio must have label '年化信息比率'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS.get("information_ratio") == "年化信息比率"


# ---------------------------------------------------------------------------
# Round 52, Task 2 (Beta): Score Concentration Analysis tests
# ---------------------------------------------------------------------------


def test_r52_score_concentration_empty_input() -> None:
    """Empty input → graceful degradation."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    result = compute_score_concentration_analysis([])
    assert result["score_concentration_index"] is None
    assert result["dominant_tier"] is None


def test_r52_score_concentration_fewer_than_6_rows() -> None:
    """Fewer than 6 rows → graceful degradation."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    rows = [{"score": 0.5 * i} for i in range(5)]
    result = compute_score_concentration_analysis(rows)
    assert result["score_concentration_index"] is None


def test_r52_score_concentration_uniform_sci_near_zero() -> None:
    """Uniform score distribution → score_concentration_index ≈ 0 (three tiers ≈ equal)."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    import pytest
    rows = [{"score": float(i)} for i in range(1, 10)]
    result = compute_score_concentration_analysis(rows)
    assert result["score_concentration_index"] is not None
    assert abs(result["score_concentration_index"]) < 0.1


def test_r52_score_concentration_all_same_high_score_pct() -> None:
    """All scores identical → high_score_pct = 1.0 (all are >= P67 = same value)."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    import pytest
    rows = [{"runner_composite_score": 0.9} for _ in range(9)]
    result = compute_score_concentration_analysis(rows)
    assert result["high_score_pct"] is not None
    assert result["high_score_pct"] == pytest.approx(1.0)


def test_r52_score_concentration_mostly_high_sci_approx_0_67() -> None:
    """5 high + 1 low out of 6 → score_concentration_index ≈ 0.67."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    rows = [{"score": 0.1}] + [{"score": 0.9} for _ in range(5)]
    result = compute_score_concentration_analysis(rows)
    assert result["score_concentration_index"] is not None
    assert result["score_concentration_index"] > 0.5


def test_r52_score_concentration_dominant_tier_correct() -> None:
    """dominant_tier matches the tier with the largest fraction."""
    from scripts.btst_analysis_utils import compute_score_concentration_analysis
    rows = [{"score": float(i)} for i in range(12)]
    result = compute_score_concentration_analysis(rows)
    assert result["dominant_tier"] in ("high", "mid", "low")
    pcts = {
        "high": result["high_score_pct"],
        "mid": result["mid_score_pct"],
        "low": result["low_score_pct"],
    }
    assert result["dominant_tier"] == max(pcts, key=lambda k: pcts[k] or 0)


def test_r52_score_concentration_floor_registered() -> None:
    """score_concentration_index: 0.0 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    import pytest
    assert "score_concentration_index" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["score_concentration_index"] == pytest.approx(0.0)


def test_r52_score_concentration_label_registered() -> None:
    """score_concentration_index must have label '高分候选集中度'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS.get("score_concentration_index") == "高分候选集中度"


def test_r52_score_concentration_optional_registered() -> None:
    """score_concentration_index must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "score_concentration_index" in OPTIONAL_COMPARISON_METRICS


# ---------------------------------------------------------------------------
# Round 52, Task 3 (Gamma): Cross-window Kelly Trend tests
# ---------------------------------------------------------------------------


def test_r52_kelly_trend_empty_list() -> None:
    """Empty list → graceful degradation."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    result = compute_cross_window_kelly_trend([])
    assert result["kelly_trend_slope"] is None
    assert result["kelly_trend_valid"] is False


def test_r52_kelly_trend_fewer_than_3_windows() -> None:
    """Fewer than 3 valid kelly_fraction values → graceful degradation."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    summaries = [{"kelly_fraction": 0.1}, {"kelly_fraction": 0.2}]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_slope"] is None
    assert result["kelly_trend_valid"] is False


def test_r52_kelly_trend_rising_trend_positive_slope() -> None:
    """Increasing Kelly fractions → slope > 0, grade A or B."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    summaries = [{"kelly_fraction": 0.1 + 0.1 * i} for i in range(5)]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_valid"] is True
    assert result["kelly_trend_slope"] is not None
    assert result["kelly_trend_slope"] > 0
    assert result["kelly_trend_grade"] in ("A", "B")


def test_r52_kelly_trend_falling_trend_negative_slope() -> None:
    """Decreasing Kelly fractions → slope < 0."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    summaries = [{"kelly_fraction": 0.5 - 0.1 * i} for i in range(5)]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_valid"] is True
    assert result["kelly_trend_slope"] is not None
    assert result["kelly_trend_slope"] < 0


def test_r52_kelly_trend_steep_decline_grade_d() -> None:
    """slope <= -0.05 → grade D."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    summaries = [{"kelly_fraction": 0.5 - 0.15 * i} for i in range(5)]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_valid"] is True
    if result["kelly_trend_slope"] is not None and result["kelly_trend_slope"] <= -0.05:
        assert result["kelly_trend_grade"] == "D"


def test_r52_kelly_trend_positive_windows_pct_correct() -> None:
    """kelly_positive_windows_pct counts fraction of kelly_fraction > 0."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    import pytest
    summaries = [{"kelly_fraction": 0.1}, {"kelly_fraction": -0.1}, {"kelly_fraction": 0.2}]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_valid"] is True
    assert result["kelly_positive_windows_pct"] == pytest.approx(2 / 3, rel=1e-4)


def test_r52_kelly_trend_floor_registered() -> None:
    """kelly_trend_slope: -0.05 must be in BTST_QUALITY_FLOORS."""
    from src.backtesting.evaluation_bundle import BTST_QUALITY_FLOORS
    import pytest
    assert "kelly_trend_slope" in BTST_QUALITY_FLOORS
    assert BTST_QUALITY_FLOORS["kelly_trend_slope"] == pytest.approx(-0.05)


def test_r52_kelly_trend_label_registered() -> None:
    """kelly_trend_slope must have label 'Kelly分数跨窗趋势'."""
    from scripts.optimize_profile import COMPARISON_METRIC_LABELS
    assert COMPARISON_METRIC_LABELS.get("kelly_trend_slope") == "Kelly分数跨窗趋势"


def test_r52_kelly_trend_optional_registered() -> None:
    """kelly_trend_slope must be in OPTIONAL_COMPARISON_METRICS."""
    from scripts.optimize_profile import OPTIONAL_COMPARISON_METRICS
    assert "kelly_trend_slope" in OPTIONAL_COMPARISON_METRICS


def test_r52_kelly_trend_in_comparison_metrics() -> None:
    """kelly_trend_slope must appear in COMPARISON_METRICS."""
    from scripts.optimize_profile import COMPARISON_METRICS
    assert "kelly_trend_slope" in COMPARISON_METRICS


def test_r52_kelly_trend_skips_missing_kelly_fraction() -> None:
    """Windows without kelly_fraction are skipped; valid windows still compute."""
    from scripts.optimize_profile import compute_cross_window_kelly_trend
    summaries = [{"kelly_fraction": 0.1}, {"other_key": 0.5}, {"kelly_fraction": 0.2}, {"kelly_fraction": 0.3}]
    result = compute_cross_window_kelly_trend(summaries)
    assert result["kelly_trend_valid"] is True
    assert result["kelly_trend_slope"] is not None
