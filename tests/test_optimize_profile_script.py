from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.optimize_profile as optimize_profile
from scripts.optimize_profile import (
    _build_default_checkpoint_path,
    _build_replay_evaluator,
    _load_focus_params,
    _parse_grid_params,
    _resolve_primary_surface,
    build_stage_grid,
    resolve_grid_params,
    resolve_guardrails,
)
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
    monkeypatch.setattr(opt_module, "save_search_report", lambda *_: Path("fake.md"))
    monkeypatch.setattr(opt_module, "save_search_payload", lambda *_: Path("fake.json"))
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
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
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
                }
            if params:
                return {
                    "next_close_positive_rate": 0.60,
                    "next_high_hit_rate": 0.61,
                    "next_close_expectancy": 0.018,
                    "downside_p10": -0.040,
                    "window_coverage": 0.85,
                }
            return {
                "next_close_positive_rate": 0.57,
                "next_high_hit_rate": 0.59,
                "next_close_expectancy": 0.014,
                "downside_p10": -0.045,
                "window_coverage": 0.82,
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
