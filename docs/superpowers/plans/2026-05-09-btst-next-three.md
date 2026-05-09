# BTST Routed Validation, Search, and Coverage Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align BTST validation with the live routed committee profiles, add a routed-profile-specific search surface, and surface raw-vs-proxy coverage guardrails before rollout decisions.

**Architecture:** Keep the work inside the existing BTST execution/replay stack. First thread routed profile and window controls through backtest/compare entry points, then add a narrow routed committee preset grid in the optimizer, then enrich replay artifacts and multi-window summaries with source-coverage evidence so promotion decisions can distinguish exact-input wins from proxy-backed wins.

**Tech Stack:** Python 3.11+, pytest, existing BTST replay/backtesting scripts, dataclass-based short-trade profiles

---

## File Map

- Modify: `src/backtesting/compare.py`
  - Extend walk-forward comparison entry points so routed profile identity and window controls can be forwarded explicitly.
- Modify: `tests/backtesting/test_compare.py`
  - Add TDD coverage for routed profile threading and window-mode/preset propagation.
- Modify: `scripts/btst_20day_backtest.py`
  - Update default BTST profile set so routed committee profiles participate in the default comparison surface.
- Modify: `tests/test_btst_20day_backtest_script.py`
  - Add regression coverage for routed default profile membership and builder sync.
- Modify: `scripts/optimize_profile.py`
  - Add a routed-committee preset grid and expose it via the existing `resolve_grid_params()` flow.
- Modify: `tests/test_optimize_profile_script.py`
  - Add tests proving routed profiles resolve to the new preset grid instead of the legacy momentum-only grid.
- Modify: `scripts/btst_profile_replay_utils.py`
  - Add source-coverage summary helpers derived from replay rows and committee payloads.
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
  - Surface replay source-coverage summaries in JSON and Markdown outputs.
- Modify: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
  - Add regression tests for source-coverage summaries appearing in analysis rows and Markdown output.

### Task 1: Align routed BTST validation and backtests with live profile routing

**Files:**
- Modify: `src/backtesting/compare.py`
- Modify: `tests/backtesting/test_compare.py`
- Modify: `scripts/btst_20day_backtest.py`
- Modify: `tests/test_btst_20day_backtest_script.py`

- [ ] **Step 1: Write the failing compare regression for routed profile and window controls**

```python
def test_run_ab_comparison_walk_forward_threads_routed_profile_and_window_controls(monkeypatch):
    captured_windows_kwargs = {}
    captured_pipelines = []

    monkeypatch.setattr(
        "src.backtesting.compare.build_walk_forward_windows",
        lambda *args, **kwargs: (
            captured_windows_kwargs.update(kwargs) or [
                WalkForwardWindow(
                    train_start="2026-01-01",
                    train_end="2026-02-28",
                    test_start="2026-03-01",
                    test_end="2026-03-31",
                )
            ]
        ),
    )

    class StubEngine:
        def __init__(self, **kwargs):
            captured_pipelines.append(kwargs["pipeline"])

        def run_backtest(self):
            return {"sharpe_ratio": 1.0, "sortino_ratio": 1.0, "max_drawdown": -5.0}

    monkeypatch.setattr("src.backtesting.compare.BacktestEngine", StubEngine)

    run_ab_comparison_walk_forward(
        tickers=["000001"],
        start_date="2026-01-01",
        end_date="2026-04-30",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        window_mode="rolling",
        walk_forward_preset="btst_primary",
        mvp_profile_name="ignition_breakout",
    )

    assert captured_windows_kwargs["window_mode"] == "rolling"
    assert captured_windows_kwargs["preset"] == "btst_primary"
    assert captured_pipelines[1].short_trade_target_profile_name == "ignition_breakout"
```

- [ ] **Step 2: Run the compare regression and verify it fails**

Run:

```bash
uv run pytest tests/backtesting/test_compare.py::test_run_ab_comparison_walk_forward_threads_routed_profile_and_window_controls -q
```

Expected: FAIL because `run_ab_comparison_walk_forward()` does not yet accept `window_mode`, `walk_forward_preset`, or `mvp_profile_name`.

- [ ] **Step 3: Implement the minimal compare wiring**

```python
def run_ab_comparison_walk_forward(
    *,
    tickers: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    agent: Callable,
    train_months: int = 2,
    test_months: int = 1,
    step_months: int = 1,
    max_test_trading_days: int | None = None,
    baseline_pct_threshold: float = 3.0,
    baseline_top_n: int = 10,
    checkpoint_path: str | None = None,
    window_mode: str = "rolling",
    walk_forward_preset: str | None = None,
    mvp_profile_name: str = "default",
) -> tuple[list[ABWindowMetrics], dict[str, float | int | None]]:
    windows = build_walk_forward_windows(
        start_date,
        end_date,
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
        max_test_trading_days=max_test_trading_days,
        window_mode=window_mode,
        preset=walk_forward_preset,
    )
    ...
    mvp_engine = BacktestEngine(
        ...,
        pipeline=DailyPipeline(
            agent_runner=agent_runner,
            short_trade_target_profile_name=mvp_profile_name,
        ),
        ...,
    )
```

- [ ] **Step 4: Run the focused compare tests and verify they pass**

Run:

```bash
uv run pytest tests/backtesting/test_compare.py::test_run_ab_comparison_walk_forward_threads_routed_profile_and_window_controls tests/backtesting/test_compare.py::test_run_ab_comparison_walk_forward_passes_max_test_trading_days -q
```

Expected: PASS

- [ ] **Step 5: Write the failing BTST 20-day backtest default-profile regression**

```python
def test_default_profile_names_include_routed_btst_committee_profiles() -> None:
    assert "ignition_breakout" in DEFAULT_PROFILE_NAMES
    assert "retention_follow" in DEFAULT_PROFILE_NAMES
    assert "shadow_research" in DEFAULT_PROFILE_NAMES


def test_module_profiles_stay_in_sync_with_routed_defaults() -> None:
    assert PROFILES == _build_profiles(DEFAULT_PROFILE_NAMES)
```

- [ ] **Step 6: Run the BTST 20-day regression and verify it fails**

Run:

```bash
uv run pytest tests/test_btst_20day_backtest_script.py::test_default_profile_names_include_routed_btst_committee_profiles -q
```

Expected: FAIL because the routed profiles are not yet in `DEFAULT_PROFILE_NAMES`.

- [ ] **Step 7: Implement the minimal default-profile update**

```python
DEFAULT_PROFILE_NAMES = (
    "default",
    "ic_optimized",
    "momentum_optimized",
    "momentum_tuned",
    "btst_precision_v1",
    "btst_precision_v2",
    "btst_precision_v3",
    "ignition_breakout",
    "retention_follow",
    "shadow_research",
    "ic_v3",
    "ic_v4",
    "ic_v5",
)
```

- [ ] **Step 8: Run the focused BTST 20-day tests and verify they pass**

Run:

```bash
uv run pytest tests/test_btst_20day_backtest_script.py::test_default_profile_names_include_routed_btst_committee_profiles tests/test_btst_20day_backtest_script.py::test_module_profiles_stay_in_sync_with_builder_output -q
```

Expected: PASS

- [ ] **Step 9: Commit Task 1**

```bash
git add src/backtesting/compare.py tests/backtesting/test_compare.py scripts/btst_20day_backtest.py tests/test_btst_20day_backtest_script.py
git commit -m "feat: align btst routed validation defaults"
```

### Task 2: Add routed committee search presets to the optimizer

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing optimizer preset-grid regression**

```python
def test_resolve_grid_params_uses_routed_btst_committee_preset_for_ignition_breakout() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="ignition_breakout",
    )

    assert "committee_alpha_min_loose" in grid
    assert "committee_beta_min_loose" in grid
    assert "committee_gamma_min_loose" in grid
    assert "committee_score_min" in grid
    assert "committee_fragile_breakout_alpha_weight" in grid
    assert "committee_fragile_breakout_activation_floor" in grid


def test_resolve_grid_params_prefers_explicit_values_over_routed_preset() -> None:
    grid = resolve_grid_params(
        grid_params=["committee_score_min=52,54"],
        preset_grid=True,
        profile_name="retention_follow",
    )

    assert grid["committee_score_min"] == [52, 54]
```

- [ ] **Step 2: Run the optimizer regression and verify it fails**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_resolve_grid_params_uses_routed_btst_committee_preset_for_ignition_breakout -q
```

Expected: FAIL because `resolve_grid_params()` only knows about the momentum/event-catalyst presets.

- [ ] **Step 3: Implement the routed committee preset grid**

```python
ROUTED_BTST_COMMITTEE_GRID = {
    "committee_alpha_min_loose": [46.0, 48.0, 50.0],
    "committee_beta_min_loose": [44.0, 46.0, 48.0],
    "committee_gamma_min_loose": [44.0, 46.0, 48.0],
    "committee_score_min": [50.0, 52.0, 54.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10, 0.12],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0, 64.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0, 58.0],
    "committee_fragile_breakout_risk_cap": [75.0, 85.0],
}

ROUTED_BTST_COMMITTEE_PROFILES = {
    "ignition_breakout",
    "retention_follow",
    "shadow_research",
}


def resolve_grid_params(*, grid_params: list[str], preset_grid: bool, profile_name: str) -> dict[str, list[Any]]:
    resolved = _parse_grid_params(grid_params)
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**MOMENTUM_OPTIMIZED_GRID, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid and profile_name in ROUTED_BTST_COMMITTEE_PROFILES:
        return {**ROUTED_BTST_COMMITTEE_GRID, **resolved}
    if preset_grid:
        return {**MOMENTUM_OPTIMIZED_GRID, **resolved}
    return resolved
```

- [ ] **Step 4: Run the focused optimizer tests and verify they pass**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_resolve_grid_params_uses_routed_btst_committee_preset_for_ignition_breakout tests/test_optimize_profile_script.py::test_resolve_grid_params_prefers_explicit_values_over_routed_preset -q
```

Expected: PASS

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/optimize_profile.py tests/test_optimize_profile_script.py
git commit -m "feat: add routed btst optimizer preset"
```

### Task 3: Add replay source-coverage summaries and multi-window guardrails

**Files:**
- Modify: `scripts/btst_profile_replay_utils.py`
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
- Modify: `tests/test_analyze_btst_multi_window_profile_validation_script.py`

- [ ] **Step 1: Write the failing multi-window coverage regression**

```python
def test_analyze_btst_multi_window_profile_validation_surfaces_source_coverage_summary(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])
    monkeypatch.setattr(
        multi_window_validation,
        "analyze_btst_profile_replay_window",
        lambda *args, **kwargs: {
            "label": "x",
            "profile_name": kwargs["profile_name"],
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {"tradeable": {"total_count": 1}},
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "source_coverage_summary": {
                "flow_60_source": {"exact_tick": 1},
                "committee_component_sources": {"fragile_breakout_risk_raw_100": {"derived:fragile_breakout_formula": 1}},
            },
        },
    )

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="btst_precision_v2",
        variant_profile="ignition_breakout",
    )

    assert analysis["rows"][0]["variant_source_coverage_summary"]["flow_60_source"]["exact_tick"] == 1
    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "variant_source_coverage" in markdown
    assert "flow_60_source" in markdown
```

- [ ] **Step 2: Run the coverage regression and verify it fails**

Run:

```bash
uv run pytest tests/test_analyze_btst_multi_window_profile_validation_script.py::test_analyze_btst_multi_window_profile_validation_surfaces_source_coverage_summary -q
```

Expected: FAIL because multi-window analysis does not yet preserve or render source coverage.

- [ ] **Step 3: Implement replay-level source coverage summaries**

```python
def _summarize_source_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metric_fields = ("flow_60_source", "persist_120_source", "close_support_30_source")
    metric_counts = {
        field: dict(Counter(str(row.get(field) or "missing") for row in rows))
        for field in metric_fields
    }
    committee_component_counts: dict[str, Counter[str]] = {}
    for row in rows:
        committee_sources = dict(((row.get("committee") or {}).get("component_sources")) or {})
        for component_name, source_name in committee_sources.items():
            committee_component_counts.setdefault(str(component_name), Counter())[str(source_name or "missing")] += 1
    return {
        **metric_counts,
        "committee_component_sources": {
            name: dict(counter)
            for name, counter in sorted(committee_component_counts.items())
        },
    }


return {
    ...,
    "source_coverage_summary": _summarize_source_coverage(rows),
    ...
}
```

- [ ] **Step 4: Implement multi-window propagation and Markdown surfacing**

```python
def _summarize_row(*, report_dir: Path, baseline: dict[str, Any], variant: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        ...,
        "baseline_source_coverage_summary": dict(baseline.get("source_coverage_summary") or {}),
        "variant_source_coverage_summary": dict(variant.get("source_coverage_summary") or {}),
    }


lines.append(
    f"  - variant_source_coverage={row.get('variant_source_coverage_summary')}"
)
```

- [ ] **Step 5: Run the focused coverage tests and verify they pass**

Run:

```bash
uv run pytest tests/test_analyze_btst_multi_window_profile_validation_script.py::test_analyze_btst_multi_window_profile_validation_surfaces_source_coverage_summary tests/test_analyze_btst_multi_window_profile_validation_script.py::test_render_btst_multi_window_profile_validation_markdown_includes_frontier_source_summary -q
```

Expected: PASS

- [ ] **Step 6: Commit Task 3**

```bash
git add scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/test_analyze_btst_multi_window_profile_validation_script.py
git commit -m "feat: add btst source coverage guardrails"
```

### Task 4: End-to-end verification and cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-05-09-btst-next-three-design.md` (only if implementation changed the agreed design)
- Modify: `docs/superpowers/plans/2026-05-09-btst-next-three.md` (mark progress only if you are using the plan as a checklist)

- [ ] **Step 1: Run the full targeted regression set**

Run:

```bash
uv run pytest tests/backtesting/test_compare.py tests/test_btst_20day_backtest_script.py tests/test_optimize_profile_script.py tests/test_analyze_btst_multi_window_profile_validation_script.py -q
```

Expected: PASS

- [ ] **Step 2: Format and lint the touched files**

Run:

```bash
uv run black src/backtesting/compare.py scripts/btst_20day_backtest.py scripts/optimize_profile.py scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/backtesting/test_compare.py tests/test_btst_20day_backtest_script.py tests/test_optimize_profile_script.py tests/test_analyze_btst_multi_window_profile_validation_script.py
uv run isort src/backtesting/compare.py scripts/btst_20day_backtest.py scripts/optimize_profile.py scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/backtesting/test_compare.py tests/test_btst_20day_backtest_script.py tests/test_optimize_profile_script.py tests/test_analyze_btst_multi_window_profile_validation_script.py
uv run flake8 src/backtesting/compare.py scripts/btst_20day_backtest.py scripts/optimize_profile.py scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/backtesting/test_compare.py tests/test_btst_20day_backtest_script.py tests/test_optimize_profile_script.py tests/test_analyze_btst_multi_window_profile_validation_script.py
```

Expected: formatting completes cleanly and `flake8` reports no new errors for the touched files.

- [ ] **Step 3: Commit the final verification checkpoint**

```bash
git add src/backtesting/compare.py scripts/btst_20day_backtest.py scripts/optimize_profile.py scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/backtesting/test_compare.py tests/test_btst_20day_backtest_script.py tests/test_optimize_profile_script.py tests/test_analyze_btst_multi_window_profile_validation_script.py docs/superpowers/specs/2026-05-09-btst-next-three-design.md docs/superpowers/plans/2026-05-09-btst-next-three.md
git commit -m "feat: align btst routed validation surfaces"
```

## Self-Review Notes

- Spec coverage:
  - Task 1 covers routed validation/backtest alignment.
  - Task 2 covers routed committee threshold search.
  - Task 3 covers raw-vs-proxy rollout guardrails.
  - Task 4 covers repo-level verification.
- Placeholder scan: no TBD/TODO placeholders remain; every code-changing step includes concrete file paths, commands, and code skeletons.
- Type consistency:
  - `window_mode`, `walk_forward_preset`, and `mvp_profile_name` are used consistently across compare tests and implementation.
  - `source_coverage_summary` and `variant_source_coverage_summary` are the only new reporting keys introduced in the reporting task.
