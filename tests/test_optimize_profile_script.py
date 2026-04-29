from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from scripts.optimize_profile import _build_default_checkpoint_path, _build_replay_evaluator, _parse_grid_params, _resolve_primary_surface, resolve_grid_params


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
    assert metrics["t_plus_2_close_positive_rate"] == pytest.approx((0.55 + 0.60) / 2.0)
    assert metrics["t_plus_3_close_positive_rate"] == pytest.approx((0.53 + 0.60) / 2.0)
    assert metrics["t_plus_3_close_expectancy"] == pytest.approx((0.012 + 0.01) / 2.0)


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
    assert metrics["t_plus_3_close_positive_rate"] == pytest.approx((0.53 + 0.55) / 2.0)
    assert metrics["t_plus_3_close_expectancy"] == pytest.approx((0.012 + 0.008) / 2.0)


def test_build_grid_params_uses_event_catalyst_preset_for_guarded_profile() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="event_catalyst_guarded",
    )

    # Verify event-catalyst-specific params are present
    assert grid["event_catalyst_selected_uplift"] == [0.02, 0.03]
    assert grid["event_catalyst_min_score_for_selected_uplift"] == [0.68, 0.72]
    assert grid["event_catalyst_near_miss_threshold_relief"] == [0.01, 0.02]
    assert grid["event_catalyst_min_score_for_near_miss_retain"] == [0.54, 0.58]
    assert grid["event_catalyst_sector_resonance_weight"] == [0.18, 0.22]
    
    # Verify base preset fields are still present (not replaced)
    assert "select_threshold" in grid
    assert "near_miss_threshold" in grid
    assert "breakout_freshness_weight" in grid


def test_main_integrates_event_catalyst_params_with_preset_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration test: main() should use resolve_grid_params() to merge event-catalyst params when --preset-grid is used with event_catalyst_guarded."""
    import scripts.optimize_profile as opt_module
    
    captured_grid: dict[str, list] | None = None
    
    def fake_param_space_init(self: object, *, grid: dict[str, list]) -> None:
        nonlocal captured_grid
        captured_grid = grid
        self.grid = grid  # type: ignore
        
    def fake_param_space_size(self: object) -> int:
        return 1
    
    # Patch ParamSpace to capture the grid that main() uses
    monkeypatch.setattr(opt_module.ParamSpace, "__init__", fake_param_space_init)
    monkeypatch.setattr(opt_module.ParamSpace, "size", fake_param_space_size)
    
    # Patch run_param_search to short-circuit execution
    def fake_run_param_search(**_: object) -> dict[str, object]:
        return {"top_params": {}, "top_value": 0.0, "evaluations": 0}
    
    monkeypatch.setattr(opt_module, "run_param_search", fake_run_param_search)
    
    # Patch save/format functions to avoid side effects
    monkeypatch.setattr(opt_module, "save_search_report", lambda *_: Path("fake.md"))
    monkeypatch.setattr(opt_module, "save_search_payload", lambda *_: Path("fake.json"))
    monkeypatch.setattr(opt_module, "format_search_report", lambda _: "")
    
    # Mock sys.argv to simulate --profile event_catalyst_guarded --preset-grid --input dummy.json
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_profile.py",
            "--profile", "event_catalyst_guarded",
            "--preset-grid",
            "--input", "dummy.json",
        ],
    )
    
    # Mock the replay evaluator builder to avoid file I/O
    def fake_build_replay_evaluator(*_: object, **__: object) -> object:
        return lambda _params: {"window_count": 1, "window_coverage": 1.0, "sample_weight": 0.5, "next_close_positive_rate": 0.6}
    
    monkeypatch.setattr(opt_module, "_build_replay_evaluator", fake_build_replay_evaluator)
    
    # Run main()
    try:
        opt_module.main()
    except SystemExit:
        pass
    
    # Verify that the grid passed to ParamSpace includes both base and event-catalyst params
    assert captured_grid is not None, "ParamSpace was not initialized with a grid"
    assert "event_catalyst_selected_uplift" in captured_grid, "Event-catalyst params missing from grid used by main()"
    assert "select_threshold" in captured_grid, "Base preset params missing from grid used by main()"
