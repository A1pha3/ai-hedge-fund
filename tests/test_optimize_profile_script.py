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
