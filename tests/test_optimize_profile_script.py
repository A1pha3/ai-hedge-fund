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
