# BTST Runtime Activation, Formal Admission, and Rollout Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved BTST next cycle into working code by making trend-continuation-style changes produce runtime activation deltas, adding bounded non-`halt` formal admission relief, and tightening rollout logic around execution-eligible evidence.

**Architecture:** Keep the work inside the existing BTST pipeline. First extend runtime-attribution and profile/metrics surfaces so replay artifacts can prove whether trend-continuation adjustments truly move `selected` / `near_miss` / `tradeable` / `execution_eligible`. Then add a narrow non-`halt` formal-admission recovery path in target evaluation/reporting. Finally thread the resulting execution-eligible evidence into the strict rollout/promotion chain so manifest publication remains blocked unless the improvement is both runtime-visible and out-of-sample safe.

**Tech Stack:** Python 3.11+, pytest, Pydantic models, BTST replay/validation scripts, existing paper-trading/report-rendering stack

---

## File Structure

### Runtime activation surfaces

- Modify: `src/targets/short_trade_target_profile_data.py`
  - Adjust the approved trend-continuation candidate profile(s) or probe profile defaults used in replay so the factor shift can actually propagate into runtime scoring.
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
  - Inspect and, if needed, fix score/threshold/rank-cap interactions that neutralize trend-continuation changes before they reach final decisions.
- Modify: `src/targets/short_trade_metrics_payload_builders.py`
  - Preserve the relevant trend-continuation / reversal diagnostics in runtime payloads so replay artifacts can attribute the activation delta to actual score changes.
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
  - Extend runtime attribution summaries to include execution-eligible deltas and any additional activation explanation needed for the repaired factor path.

### Formal admission recovery surfaces

- Modify: `src/targets/router_build_helpers.py`
  - Keep reporting-truth semantics intact while exposing any new recovery-aware provenance fields.
- Modify: `src/paper_trading/runtime_observability_helpers.py`
  - Aggregate new recovery / recovered-formal counters into session summaries.
- Modify: `src/research/review_renderer.py`
  - Render recovery-aware reporting-truth fields in user-facing review output.
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
  - Thread any new formal-admission recovery counters into BTST brief summaries.
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
  - Render the new recovery-aware summary lines in BTST brief markdown.

### Rollout / promotion surfaces

- Modify: `scripts/btst_admission_replay_validator.py`
  - Extend structural/runtime sidecar summaries to distinguish recoverable non-`halt` formal improvements from blocked-but-non-executable outcomes.
- Modify: `scripts/btst_strict_objective_gate.py`
  - Add positive/negative execution-eligible evidence handling without weakening existing blockers.
- Modify: `scripts/optimize_profile.py`
  - Fold the new execution-eligible evidence into rollout recommendation payloads and manifest publication decisions.

### Tests

- Modify: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
- Modify: `tests/test_btst_execution_eligibility_contract.py`
- Modify: `tests/test_btst_admission_replay_validator.py`
- Modify: `tests/test_optimize_profile_script.py`
- Modify: `tests/research/test_selection_review_renderer.py`
- Modify: `tests/research/test_selection_artifact_writer.py`
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Modify or add focused target-evaluation tests if the runtime activation repair needs direct scoring coverage:
  - `tests/targets/test_target_models.py`
  - `tests/targets/test_trend_continuation_strength_v2.py`

---

### Task 1: Repair runtime activation for trend-continuation-driven profile work

**Files:**
- Modify: `src/targets/short_trade_target_profile_data.py`
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
- Modify: `src/targets/short_trade_metrics_payload_builders.py`
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
- Test: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_analyze_btst_multi_window_profile_validation_flags_execution_eligible_activation_delta(tmp_path: Path, monkeypatch) -> None:
    baseline_report = tmp_path / "baseline"
    variant_report = tmp_path / "variant"
    baseline_report.mkdir()
    variant_report.mkdir()

    monkeypatch.setattr(
        validation_script,
        "_load_report_summary",
        lambda path: {
            "profile_name": "baseline" if path == baseline_report else "trend_corrected_v1",
            "trade_dates": ["2026-05-12"],
            "surface_summaries": {
                "selected": {"total_count": 2 if path == baseline_report else 3},
                "near_miss": {"total_count": 1},
                "tradeable": {"total_count": 2 if path == baseline_report else 3},
                "execution_eligible": {"total_count": 0 if path == baseline_report else 1},
            },
        },
    )

    rows = validation_script.analyze_btst_multi_window_profile_validation(
        report_pairs=[(baseline_report, variant_report)],
        baseline_profile="btst_precision_v2",
        variant_profile="trend_corrected_v1",
    )["rows"]

    attribution = rows[0]["runtime_activation_attribution"]
    assert attribution["execution_eligible_count_delta"] == 1
    assert "execution_eligible" in attribution["activation_change_labels"]
```

```python
def test_trend_continuation_candidate_profile_outweighs_reversal_in_runtime_threshold_payload() -> None:
    profile = SHORT_TRADE_TARGET_PROFILES["trend_continuation_strength_v2"]
    assert profile.short_term_reversal_weight == 0.0
    assert profile.reversal_2d_weight == 0.0
    assert profile.trend_continuation_weight > 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_analyze_btst_multi_window_profile_validation_script.py::test_analyze_btst_multi_window_profile_validation_flags_execution_eligible_activation_delta \
  tests/targets/test_trend_continuation_strength_v2.py -q
```

Expected:

1. the validation-script test fails because `execution_eligible_count_delta` is absent from runtime attribution, and/or
2. the trend-continuation test fails because the current profile/scoring path still leaves reversal-driven behavior effectively dominant.

- [ ] **Step 3: Write the minimal implementation**

```python
def _build_runtime_activation_attribution(...):
    execution_eligible_delta = (
        _resolve_surface_total_count(variant, "execution_eligible")
        - _resolve_surface_total_count(baseline, "execution_eligible")
    )
    ...
    if execution_eligible_delta:
        activation_change_labels.append("execution_eligible")
    return {
        ...
        "execution_eligible_count_delta": execution_eligible_delta,
    }
```

```python
SHORT_TRADE_TARGET_PROFILES["trend_continuation_strength_v2"] = replace(
    SHORT_TRADE_TARGET_PROFILES["trend_corrected_v1"],
    name="trend_continuation_strength_v2",
    short_term_reversal_weight=0.0,
    reversal_2d_weight=0.0,
    trend_continuation_weight=0.18,
)
```

```python
if trend_continuation_score is not None:
    score_components.append(("trend_continuation", trend_continuation_score * profile.trend_continuation_weight))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_analyze_btst_multi_window_profile_validation_script.py::test_analyze_btst_multi_window_profile_validation_flags_execution_eligible_activation_delta \
  tests/targets/test_trend_continuation_strength_v2.py -q
```

Expected:

1. the runtime-attribution test passes,
2. the trend-continuation profile/scoring test passes.

- [ ] **Step 5: Commit**

```bash
git add \
  src/targets/short_trade_target_profile_data.py \
  src/targets/short_trade_target_evaluation_helpers.py \
  src/targets/short_trade_metrics_payload_builders.py \
  scripts/analyze_btst_multi_window_profile_validation.py \
  tests/test_analyze_btst_multi_window_profile_validation_script.py \
  tests/targets/test_trend_continuation_strength_v2.py
git commit -m "feat: repair BTST runtime activation path"
```

---

### Task 2: Add bounded non-`halt` formal admission relief

**Files:**
- Modify: `src/targets/router_build_helpers.py`
- Modify: `src/paper_trading/runtime_observability_helpers.py`
- Modify: `src/research/review_renderer.py`
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
- Test: `tests/test_btst_execution_eligibility_contract.py`
- Test: `tests/research/test_selection_artifact_writer.py`
- Test: `tests/research/test_selection_review_renderer.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_reporting_target_summary_recovers_non_halt_selected_candidate_when_relief_applies() -> None:
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260512",
        execution_eligible=True,
        p2_execution_blocked=False,
        p3_execution_blocked=False,
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected",
            score_target=0.83,
        ),
        btst_regime_gate="shadow_only",
    )

    summary = build_reporting_target_summary(
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
    )

    assert summary.short_trade_selected_count == 1
    assert summary.short_trade_recovered_formal_selected_count == 1
    assert summary.short_trade_recovered_formal_reason_counts == {
        "non_halt_relief": 1,
    }
```

```python
def test_render_selection_review_shows_recovered_formal_selected_count() -> None:
    snapshot = SelectionSnapshot(
        ...,
        reporting_target_summary={
            "short_trade_selected_count": 1,
            "short_trade_recovered_formal_selected_count": 1,
            "short_trade_recovered_formal_reason_counts": {"non_halt_relief": 1},
        },
    )
    markdown = render_selection_review(snapshot)
    assert "short_trade_recovered_formal_selected_count: 1" in markdown
    assert "short_trade_recovered_formal_reason_counts: non_halt_relief=1" in markdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_btst_execution_eligibility_contract.py::test_build_reporting_target_summary_recovers_non_halt_selected_candidate_when_relief_applies \
  tests/research/test_selection_review_renderer.py::test_render_selection_review_shows_recovered_formal_selected_count \
  -q
```

Expected:

1. the reporting summary lacks the new recovery counters,
2. the review renderer lacks the new recovery lines.

- [ ] **Step 3: Write the minimal implementation**

```python
class DualTargetSummary(BaseModel):
    ...
    short_trade_recovered_formal_selected_count: int = 0
    short_trade_recovered_formal_reason_counts: dict[str, int] = Field(default_factory=dict)
```

```python
if raw_decision == "selected" and reporting_decision == "selected" and _non_halt_relief_applied(evaluation):
    summary.short_trade_recovered_formal_selected_count += 1
    summary.short_trade_recovered_formal_reason_counts["non_halt_relief"] = (
        int(summary.short_trade_recovered_formal_reason_counts.get("non_halt_relief") or 0) + 1
    )
```

```python
lines.append(
    f"- short_trade_recovered_formal_selected_count: {summary.get('short_trade_recovered_formal_selected_count', 0)}"
)
lines.append(
    f"- short_trade_recovered_formal_reason_counts: {_format_reason_counts(summary, 'short_trade_recovered_formal_reason_counts')}"
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_btst_execution_eligibility_contract.py \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_review_renderer.py \
  tests/test_generate_btst_next_day_trade_brief_script.py \
  -q
```

Expected:

1. the new recovery tests pass,
2. existing formal-block provenance coverage remains green.

- [ ] **Step 5: Commit**

```bash
git add \
  src/targets/router_build_helpers.py \
  src/paper_trading/runtime_observability_helpers.py \
  src/research/review_renderer.py \
  src/paper_trading/_btst_reporting/brief_builder.py \
  src/paper_trading/_btst_reporting/brief_rendering.py \
  tests/test_btst_execution_eligibility_contract.py \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_review_renderer.py \
  tests/test_generate_btst_next_day_trade_brief_script.py
git commit -m "feat: add BTST non-halt admission relief"
```

---

### Task 3: Align rollout and publication with execution-eligible edge

**Files:**
- Modify: `scripts/btst_admission_replay_validator.py`
- Modify: `scripts/btst_strict_objective_gate.py`
- Modify: `scripts/optimize_profile.py`
- Test: `tests/test_btst_admission_replay_validator.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_admission_replay_summary_flags_candidate_with_formal_recovery_but_no_payoff_improvement() -> None:
    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "A"}], "near_miss": []},
        candidate_payload={"selected": [{"ticker": "A"}, {"ticker": "B"}], "near_miss": []},
        regime_rows=[
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
            {"gate": "shadow_only", "execution_eligible": True, "decision": "selected"},
        ],
        baseline_metrics={"selected_payoff_ratio": 1.30, "post_fee_expectation_low": 0.02},
        prior_audit={},
        multi_window_validation={"report_dir_count": 1, "rows": []},
    )
    assert "execution_eligible_edge_not_confirmed" in summary["structural_guardrail"]["blockers"]
```

```python
def test_build_rollout_recommendation_payload_blocks_candidate_without_execution_eligible_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    comparison_summary = {
        "default": {
            "next_close_positive_rate_delta": 0.01,
            "next_high_hit_rate_delta": 0.01,
            "next_close_expectancy_delta": 0.002,
            "downside_p10_delta": 0.0,
            "window_coverage_delta": 0.0,
            "liquidity_capacity_raw_100_delta": 0.0,
            "crowding_risk_raw_100_delta": 0.0,
            "gap_risk_raw_100_delta": 0.0,
            "projected_theme_exposure_delta": 0.0,
            "incremental_theme_exposure_delta": 0.0,
        }
    }
    monkeypatch.setattr(
        optimize_profile,
        "_load_strict_btst_objective_gate",
        lambda: {
            "action": "hold",
            "blockers": ["execution_eligible_edge_not_confirmed"],
        },
    )
    payload = optimize_profile._build_rollout_recommendation_payload(comparison_summary)
    assert payload["action"] == "hold"
    assert "execution_eligible_edge_not_confirmed" in payload["blockers"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_btst_admission_replay_validator.py::test_build_admission_replay_summary_flags_candidate_with_formal_recovery_but_no_payoff_improvement \
  tests/test_optimize_profile_script.py::test_build_rollout_recommendation_payload_blocks_candidate_without_execution_eligible_edge \
  -q
```

Expected:

1. admission replay does not yet emit the new execution-eligible edge blocker,
2. rollout tests only cover the old blocker families.

- [ ] **Step 3: Write the minimal implementation**

```python
if execution_eligible_selected_count <= baseline_execution_eligible_selected_count:
    blockers.append("execution_eligible_edge_not_confirmed")
elif float(baseline_metrics.get("selected_payoff_ratio") or 0.0) >= float(candidate_payoff_ratio or 0.0):
    blockers.append("execution_eligible_edge_not_confirmed")
```

```python
for blocker in structural_guardrail_blockers:
    if blocker not in blockers:
        blockers.append(blocker)
```

```python
if optimized_profile_manifest_publication.get("status") == "published":
    assert "execution_eligible_edge_not_confirmed" not in rollout_recommendation_details["blockers"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/test_btst_admission_replay_validator.py \
  tests/test_optimize_profile_script.py \
  -q
```

Expected:

1. admission replay validator tests pass,
2. optimize-profile rollout tests pass,
3. manifest publication remains blocked when execution-eligible edge is not confirmed.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/btst_admission_replay_validator.py \
  scripts/btst_strict_objective_gate.py \
  scripts/optimize_profile.py \
  tests/test_btst_admission_replay_validator.py \
  tests/test_optimize_profile_script.py
git commit -m "feat: align BTST rollout with execution-eligible edge"
```

---

### Task 4: Run cross-surface BTST regression and finalize

**Files:**
- Modify: no new source files expected
- Test: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
- Test: `tests/test_btst_execution_eligibility_contract.py`
- Test: `tests/test_btst_admission_replay_validator.py`
- Test: `tests/research/test_selection_artifact_writer.py`
- Test: `tests/research/test_selection_review_renderer.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Run the focused regression slice**

Run:

```bash
uv run pytest \
  tests/test_analyze_btst_multi_window_profile_validation_script.py \
  tests/test_btst_execution_eligibility_contract.py \
  tests/test_btst_admission_replay_validator.py \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_review_renderer.py \
  tests/test_generate_btst_next_day_trade_brief_script.py \
  tests/test_optimize_profile_script.py \
  -q
```

Expected:

1. all targeted BTST runtime / admission / rollout surfaces pass,
2. no regression reopens the earlier provenance and strict-gate fixes.

- [ ] **Step 2: Run the broader runtime summary slice**

Run:

```bash
uv run pytest \
  tests/backtesting/test_paper_trading_runtime.py \
  -k 'dual_target_session_summary or reporting_target_session_summary or finalize_paper_trading_session_writes_summary' \
  -q
```

Expected:

1. reporting-target/session-summary paths still pass after the new counters and blockers.

- [ ] **Step 3: Inspect git status**

Run:

```bash
git --no-pager status --short
```

Expected:

1. only the intended BTST source, plan, and test files are modified,
2. no generated fixture files such as `optimize_profile_fixture.*` or `r.*` remain dirty.

- [ ] **Step 4: Commit the final verification or cleanup if needed**

```bash
git add \
  src/targets/short_trade_target_profile_data.py \
  src/targets/short_trade_target_evaluation_helpers.py \
  src/targets/short_trade_metrics_payload_builders.py \
  src/targets/router_build_helpers.py \
  src/paper_trading/runtime_observability_helpers.py \
  src/research/review_renderer.py \
  src/paper_trading/_btst_reporting/brief_builder.py \
  src/paper_trading/_btst_reporting/brief_rendering.py \
  scripts/analyze_btst_multi_window_profile_validation.py \
  scripts/btst_admission_replay_validator.py \
  scripts/btst_strict_objective_gate.py \
  scripts/optimize_profile.py \
  tests/test_analyze_btst_multi_window_profile_validation_script.py \
  tests/test_btst_execution_eligibility_contract.py \
  tests/test_btst_admission_replay_validator.py \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_review_renderer.py \
  tests/test_generate_btst_next_day_trade_brief_script.py \
  tests/test_optimize_profile_script.py
git commit -m "fix: complete BTST runtime-admission-rollout alignment"
```

- [ ] **Step 5: Merge and clean up**

```bash
git --no-pager branch --show-current
git --no-pager status --short
```

Expected:

1. branch is ready for merge or already on `main` after integration,
2. working tree is clean,
3. no extra worktree remains if an isolated worktree was used.
