# BTST Ignition Breakout Staged Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a staged, baseline-aware calibration workflow for `ignition_breakout` that ranks candidates by protected T+1 improvement and source-coverage guardrails instead of raw optimizer score alone.

**Architecture:** Keep the work inside the existing optimizer stack. First add a narrow Stage 1 ignition search mode in `scripts/optimize_profile.py`, then make `src/backtesting/param_search.py` understand promotion-aware BTST ranking inputs, then emit a shortlist/verdict contract from the optimizer so the next cycle can decide whether `ignition_breakout` should actually change.

**Tech Stack:** Python 3.11+, pytest, existing replay-based BTST optimizer/report pipeline

---

## File Map

- Modify: `scripts/optimize_profile.py`
  - Add Stage 1 ignition-mode grid selection and a baseline-aware evaluator wrapper.
- Modify: `src/backtesting/param_search.py`
  - Add promotion-aware BTST ranking / filtering behavior for staged ignition calibration.
- Modify: `tests/test_optimize_profile_script.py`
  - Add TDD coverage for staged ignition entry-point behavior and shortlist/verdict output.
- Modify: `tests/backtesting/test_param_search.py`
  - Add TDD coverage for baseline-aware BTST ranking and guardrail rejection.

### Task 1: Add a narrow Stage 1 ignition calibration mode

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing staged-mode grid test**

```python
def test_resolve_grid_params_uses_stage1_ignition_grid() -> None:
    grid = resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="ignition_breakout",
        staged_mode="ignition_stage1",
    )

    assert grid["committee_alpha_min_aggressive_trade"] == [66.0, 68.0]
    assert grid["committee_score_min_normal_trade"] == [62.0, 64.0]
    assert grid["committee_fragile_breakout_alpha_weight"] == [0.08, 0.10]
    assert "committee_fragile_breakout_risk_cap" in grid
```

- [ ] **Step 2: Run the staged grid test and verify it fails**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_resolve_grid_params_uses_stage1_ignition_grid -q
```

Expected: FAIL because `resolve_grid_params()` does not yet accept `staged_mode`.

- [ ] **Step 3: Implement the minimal Stage 1 ignition grid**

```python
IGNITION_STAGE1_GRID: dict[str, list[Any]] = {
    "committee_alpha_min_aggressive_trade": [66.0, 68.0],
    "committee_beta_min_aggressive_trade": [56.0, 58.0],
    "committee_gamma_min_aggressive_trade": [54.0, 56.0],
    "committee_score_min_aggressive_trade": [64.0, 66.0],
    "committee_alpha_min_normal_trade": [64.0, 66.0],
    "committee_beta_min_normal_trade": [60.0, 62.0],
    "committee_gamma_min_normal_trade": [56.0, 58.0],
    "committee_score_min_normal_trade": [62.0, 64.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0],
}


def resolve_grid_params(
    *,
    grid_params: list[str],
    preset_grid: bool,
    profile_name: str,
    staged_mode: str | None = None,
) -> dict[str, list[Any]]:
    resolved = _parse_grid_params(grid_params)
    if staged_mode == "ignition_stage1":
        return {**IGNITION_STAGE1_GRID, **resolved}
    ...
```

- [ ] **Step 4: Add CLI wiring for staged ignition mode**

```python
parser.add_argument(
    "--staged-mode",
    choices=["ignition_stage1"],
    default=None,
    help="Run a narrow staged calibration workflow for a routed BTST profile.",
)

grid = resolve_grid_params(
    grid_params=args.grid_params or [],
    preset_grid=args.preset_grid,
    profile_name=args.profile,
    staged_mode=args.staged_mode,
)
```

- [ ] **Step 5: Run the focused staged-mode tests and verify they pass**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_resolve_grid_params_uses_stage1_ignition_grid -q
```

Expected: PASS

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/optimize_profile.py tests/test_optimize_profile_script.py
git commit -m "feat: add staged ignition calibration entrypoint"
```

### Task 2: Make BTST ranking baseline-aware and source-coverage-aware

**Files:**
- Modify: `src/backtesting/param_search.py`
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/backtesting/test_param_search.py`
- Modify: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing guardrail-ranking tests**

```python
def test_compute_objective_score_btst_returns_none_when_candidate_fails_guardrails() -> None:
    metrics = {
        "next_close_positive_rate": 0.62,
        "next_close_payoff_ratio": 1.8,
        "next_close_expectancy": 0.012,
        "next_high_hit_rate": 0.58,
        "t_plus_2_close_positive_rate": 0.56,
        "t_plus_3_close_positive_rate": 0.54,
        "t_plus_3_close_expectancy": 0.011,
        "downside_p10": -0.02,
        "sample_weight": 0.8,
        "promotion_guardrail_pass": False,
    }

    assert compute_objective_score(metrics, SearchObjective.BTST) is None


def test_compute_objective_score_btst_rewards_baseline_delta_when_guardrails_pass() -> None:
    metrics = {
        "next_close_positive_rate": 0.62,
        "next_close_payoff_ratio": 1.8,
        "next_close_expectancy": 0.012,
        "next_high_hit_rate": 0.58,
        "t_plus_2_close_positive_rate": 0.56,
        "t_plus_3_close_positive_rate": 0.54,
        "t_plus_3_close_expectancy": 0.011,
        "downside_p10": -0.02,
        "sample_weight": 0.8,
        "promotion_guardrail_pass": True,
        "baseline_next_close_positive_rate_delta": 0.03,
        "baseline_next_close_expectancy_delta": 0.004,
    }

    score = compute_objective_score(metrics, SearchObjective.BTST)
    assert score is not None
    assert score > 0.47
```

- [ ] **Step 2: Run the guardrail-ranking tests and verify they fail**

Run:

```bash
uv run pytest tests/backtesting/test_param_search.py::test_compute_objective_score_btst_returns_none_when_candidate_fails_guardrails tests/backtesting/test_param_search.py::test_compute_objective_score_btst_rewards_baseline_delta_when_guardrails_pass -q
```

Expected: FAIL because `compute_objective_score()` ignores `promotion_guardrail_pass` and baseline deltas.

- [ ] **Step 3: Implement guardrail-aware BTST ranking**

```python
if objective == SearchObjective.BTST:
    ...
    if metrics.get("promotion_guardrail_pass") is False:
        return None

    baseline_win_delta = clip(float(metrics.get("baseline_next_close_positive_rate_delta") or 0.0), -0.10, 0.10)
    baseline_expectancy_delta = clip(float(metrics.get("baseline_next_close_expectancy_delta") or 0.0), -0.03, 0.03)
    promotion_bonus = (0.30 * max(0.0, baseline_win_delta)) + (0.25 * max(0.0, baseline_expectancy_delta / 0.03))
    return ((base_score - floor_penalty) + promotion_bonus) * (0.35 + (0.65 * effective_sample_weight))
```

- [ ] **Step 4: Add the staged evaluator wrapper in optimize_profile.py**

```python
def _build_ignition_stage1_replay_evaluator(
    input_paths: list[Path],
    *,
    base_profile: str,
    next_high_hit_threshold: float = 0.02,
) -> Callable:
    baseline_metrics = _build_replay_evaluator(input_paths, base_profile=base_profile, next_high_hit_threshold=next_high_hit_threshold)({})
    default_metrics = _build_replay_evaluator(input_paths, base_profile="default", next_high_hit_threshold=next_high_hit_threshold)({})

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        candidate_metrics = _build_replay_evaluator(
            input_paths,
            base_profile=base_profile,
            next_high_hit_threshold=next_high_hit_threshold,
        )(params)
        candidate_metrics["baseline_next_close_positive_rate_delta"] = float(candidate_metrics.get("next_close_positive_rate") or 0.0) - float(baseline_metrics.get("next_close_positive_rate") or 0.0)
        candidate_metrics["baseline_next_close_expectancy_delta"] = float(candidate_metrics.get("next_close_expectancy") or 0.0) - float(baseline_metrics.get("next_close_expectancy") or 0.0)
        candidate_metrics["promotion_guardrail_pass"] = (
            candidate_metrics["baseline_next_close_positive_rate_delta"] >= 0.0
            and candidate_metrics["baseline_next_close_expectancy_delta"] >= 0.0
            and float(candidate_metrics.get("source_coverage_pass_ratio") or 0.0) >= 0.6
            and float(candidate_metrics.get("next_close_positive_rate") or 0.0) >= float(default_metrics.get("next_close_positive_rate") or 0.0)
        )
        return candidate_metrics

    return evaluator
```

- [ ] **Step 5: Run the focused ranking tests and verify they pass**

Run:

```bash
uv run pytest tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py -q
```

Expected: PASS

- [ ] **Step 6: Commit Task 2**

```bash
git add src/backtesting/param_search.py scripts/optimize_profile.py tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py
git commit -m "feat: add baseline-aware ignition ranking"
```

### Task 3: Emit shortlist and promotion verdict outputs

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing shortlist/verdict test**

```python
def test_format_staged_ignition_report_includes_promotion_verdict() -> None:
    report = {
        "best_params": {"committee_score_min_normal_trade": 64.0},
        "best_score": 0.52,
        "shortlist": [
            {
                "params": {"committee_score_min_normal_trade": 64.0},
                "score": 0.52,
                "promotion_verdict": "promotable",
            }
        ],
    }

    output = optimize_profile._format_staged_ignition_summary(report)
    assert "promotable" in output
    assert "committee_score_min_normal_trade" in output
```

- [ ] **Step 2: Run the shortlist test and verify it fails**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_format_staged_ignition_report_includes_promotion_verdict -q
```

Expected: FAIL because no staged ignition summary formatter exists yet.

- [ ] **Step 3: Implement shortlist/verdict summary helpers**

```python
def _build_staged_ignition_shortlist(report: SearchReport, *, top_n: int = 5) -> list[dict[str, Any]]:
    shortlist: list[dict[str, Any]] = []
    for result in list(report.results):
        if result.score is None:
            continue
        verdict = "promotable" if bool(result.metrics.get("promotion_guardrail_pass")) else "keep_current"
        shortlist.append(
            {
                "params": dict(result.params),
                "score": result.score,
                "promotion_verdict": verdict,
                "baseline_next_close_positive_rate_delta": result.metrics.get("baseline_next_close_positive_rate_delta"),
                "baseline_next_close_expectancy_delta": result.metrics.get("baseline_next_close_expectancy_delta"),
            }
        )
        if len(shortlist) >= top_n:
            break
    return shortlist


def _format_staged_ignition_summary(report: SearchReport) -> str:
    shortlist = _build_staged_ignition_shortlist(report)
    lines = ["# Ignition Stage 1 Summary", ""]
    for row in shortlist:
        lines.append(f"- verdict={row['promotion_verdict']} score={row['score']:.4f} params={row['params']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire staged summary into main output flow**

```python
if args.staged_mode == "ignition_stage1":
    shortlist = _build_staged_ignition_shortlist(report)
    print(_format_staged_ignition_summary(report))
else:
    print(format_search_report(report))
```

- [ ] **Step 5: Run the focused shortlist tests and verify they pass**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_format_staged_ignition_report_includes_promotion_verdict -q
```

Expected: PASS

- [ ] **Step 6: Commit Task 3**

```bash
git add scripts/optimize_profile.py tests/test_optimize_profile_script.py
git commit -m "feat: emit ignition calibration verdicts"
```

### Task 4: Final verification

**Files:**
- Modify: `docs/superpowers/specs/2026-05-09-btst-ignition-staged-calibration-design.md` (only if implementation changes design details)
- Modify: `docs/superpowers/plans/2026-05-09-btst-ignition-staged-calibration.md` (only if you are checking off steps in place)

- [ ] **Step 1: Run the full targeted regression set**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py tests/backtesting/test_param_search.py -q
```

Expected: PASS

- [ ] **Step 2: Format and lint the touched files**

Run:

```bash
uv run black scripts/optimize_profile.py src/backtesting/param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_param_search.py
uv run isort scripts/optimize_profile.py src/backtesting/param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_param_search.py
uv run flake8 scripts/optimize_profile.py src/backtesting/param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_param_search.py
```

Expected: formatting completes cleanly and `flake8` reports no new errors for the touched files.

- [ ] **Step 3: Commit the verification checkpoint**

```bash
git add scripts/optimize_profile.py src/backtesting/param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_param_search.py docs/superpowers/specs/2026-05-09-btst-ignition-staged-calibration-design.md docs/superpowers/plans/2026-05-09-btst-ignition-staged-calibration.md
git commit -m "feat: add staged ignition calibration workflow"
```

## Self-Review Notes

- Spec coverage:
  - Task 1 covers the staged ignition search entry point.
  - Task 2 covers baseline-aware ranking and source-aware promotion guardrails.
  - Task 3 covers shortlist/verdict outputs.
  - Task 4 covers verification.
- Placeholder scan: no TBD/TODO placeholders remain; every code-changing step includes concrete file paths, commands, and code skeletons.
- Type consistency:
  - `staged_mode`, `promotion_guardrail_pass`, `baseline_next_close_positive_rate_delta`, and `baseline_next_close_expectancy_delta` are used consistently across tasks.
