# BTST Win-Rate-First Medium-Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten BTST runtime precision for win-rate-first selection, re-validate trend-corrected promotion under bounded tradeoffs, and document any validated factor or governance uplift for later `ai-hedge-fund-btst` consumption.

**Architecture:** Keep the work inside the existing BTST runtime, replay, and rollout stack. First convert the new execution-eligible and prior-quality evidence into stricter selected-lane behavior, then evaluate `trend_corrected_v1` against win-rate-first replay / walk-forward gates, and only then emit dated Chinese factor documentation for validated improvements.

**Tech Stack:** Python 3.12, pytest, BTST replay/optimizer scripts, Pydantic target models, markdown docs

---

### File Map

**Task A — runtime precision tightening**
- Modify: `src/targets/short_trade_target_rank_helpers.py`
- Modify: `src/targets/short_trade_target_snapshot_relief_helpers.py`
- Modify: `src/targets/router_build_helpers.py`
- Test: `tests/test_btst_execution_eligibility_contract.py`
- Test: `tests/test_btst_prior_shrinkage.py`
- Test: `tests/test_btst_regime_gate_enforcement.py`

**Task B — trend-corrected win-rate validation**
- Modify: `scripts/optimize_profile.py`
- Modify: `scripts/btst_profile_compare.py`
- Modify: `src/targets/short_trade_target_profile_data.py` (only if validation proves a bounded runtime candidate is worth surfacing)
- Test: `tests/test_optimize_profile_script.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`
- Test: `tests/backtesting/test_walk_forward.py`

**Task C — validated factor/governance documentation**
- Create: `docs/prompt/generate_file/<factor-or-feature>-2026-05-17.md`
- Modify: `skills/ai-hedge-fund-btst` (only if a validated improvement changes the skill-facing explanation path)
- Test/verify: targeted BTST regression slice plus manual inspection of the generated markdown file

### Task 1: Tighten win-rate-first runtime precision

**Files:**
- Modify: `src/targets/short_trade_target_rank_helpers.py`
- Modify: `src/targets/short_trade_target_snapshot_relief_helpers.py`
- Modify: `src/targets/router_build_helpers.py`
- Test: `tests/test_btst_execution_eligibility_contract.py`
- Test: `tests/test_btst_prior_shrinkage.py`
- Test: `tests/test_btst_regime_gate_enforcement.py`

- [ ] **Step 1: Write the failing execution-eligibility precision test**

```python
def test_selected_candidates_without_positive_execution_edge_fall_to_near_miss() -> None:
    evaluation = build_short_trade_dual_target_evaluation(
        score_target=0.66,
        decision="selected",
        execution_eligible=False,
        p3_prior_quality_label="borderline",
        btst_regime_gate="shadow_only",
    )

    reporting_summary = build_reporting_target_summary(
        selection_targets={"AAA": evaluation},
        target_mode="short_trade_only",
    )

    assert reporting_summary.short_trade_selected_count == 0
    assert reporting_summary.short_trade_near_miss_count == 1
```

- [ ] **Step 2: Run the precision test to verify it fails**

Run: `uv run pytest tests/test_btst_execution_eligibility_contract.py::test_selected_candidates_without_positive_execution_edge_fall_to_near_miss -q`
Expected: `FAILED` because the current runtime still keeps the borderline candidate in `selected`.

- [ ] **Step 3: Write the failing prior-quality shrinkage test**

```python
def test_borderline_prior_quality_loses_selected_status_under_win_rate_first_shrinkage() -> None:
    payload = {
        "score_target": 0.64,
        "decision": "selected",
        "historical_prior_quality_level": "borderline",
        "execution_eligible": True,
    }

    result = apply_win_rate_first_prior_quality_shrinkage(payload, enabled=True)

    assert result["decision"] == "near_miss"
    assert "win_rate_first_prior_quality_shrinkage" in result["rejection_reasons"]
```

- [ ] **Step 4: Run the prior-quality shrinkage test to verify it fails**

Run: `uv run pytest tests/test_btst_prior_shrinkage.py::test_borderline_prior_quality_loses_selected_status_under_win_rate_first_shrinkage -q`
Expected: `FAILED` because the helper or routing rule does not exist yet.

- [ ] **Step 5: Write the minimal runtime implementation**

```python
def apply_win_rate_first_prior_quality_shrinkage(payload: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return payload
    if str(payload.get("decision") or "") != "selected":
        return payload
    if bool(payload.get("execution_eligible")):
        return payload
    if str(payload.get("historical_prior_quality_level") or "") not in {"borderline", "weak"}:
        return payload

    updated = dict(payload)
    updated["decision"] = "near_miss"
    reasons = list(updated.get("rejection_reasons") or [])
    if "win_rate_first_prior_quality_shrinkage" not in reasons:
        reasons.append("win_rate_first_prior_quality_shrinkage")
    updated["rejection_reasons"] = reasons
    return updated
```

- [ ] **Step 6: Thread the shrinkage through runtime routing**

```python
short_trade_payload = apply_win_rate_first_prior_quality_shrinkage(
    short_trade_payload,
    enabled=bool(effective_profile.get("win_rate_first_precision_mode")),
)
reporting_decision, formal_execution_block_flags = resolve_short_trade_reporting_decision(evaluation, short_trade_result)
```

- [ ] **Step 7: Run the focused Task 1 slice**

Run: `uv run pytest tests/test_btst_execution_eligibility_contract.py tests/test_btst_prior_shrinkage.py tests/test_btst_regime_gate_enforcement.py -q`
Expected: `PASS`

- [ ] **Step 8: Commit Task 1**

```bash
git add src/targets/short_trade_target_rank_helpers.py \
  src/targets/short_trade_target_snapshot_relief_helpers.py \
  src/targets/router_build_helpers.py \
  tests/test_btst_execution_eligibility_contract.py \
  tests/test_btst_prior_shrinkage.py \
  tests/test_btst_regime_gate_enforcement.py
git commit -m "feat: tighten BTST win-rate precision"
```

### Task 2: Re-validate trend-corrected promotion under win-rate-first gates

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `scripts/btst_profile_compare.py`
- Test: `tests/test_optimize_profile_script.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`
- Test: `tests/backtesting/test_walk_forward.py`

- [ ] **Step 1: Write the failing rollout payload test**

```python
def test_build_rollout_recommendation_payload_prefers_win_rate_uplift_for_trend_corrected_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(optimize_profile, "_load_strict_btst_objective_gate", lambda: None)

    payload = optimize_profile._build_rollout_recommendation_payload(
        {
            "default": {
                "selected_win_rate_delta": 0.04,
                "execution_eligible_win_rate_delta": 0.03,
                "selected_payoff_ratio_delta": -0.05,
                "window_coverage_delta": -0.02,
            }
        }
    )

    assert payload["action"] == "promote"
    assert payload["win_rate_first_decision"] == "pass"
```

- [ ] **Step 2: Run the rollout payload test to verify it fails**

Run: `uv run pytest tests/test_optimize_profile_script.py::test_build_rollout_recommendation_payload_prefers_win_rate_uplift_for_trend_corrected_candidate -q`
Expected: `FAILED` because win-rate-first deltas are not yet part of the rollout verdict.

- [ ] **Step 3: Write the failing walk-forward acceptance test**

```python
def test_walk_forward_summary_flags_trend_corrected_candidate_when_win_rate_improves_but_payoff_stays_bounded() -> None:
    summary = summarize_walk_forward_candidate(
        selected_win_rate_delta=0.05,
        execution_eligible_win_rate_delta=0.04,
        selected_payoff_ratio_delta=-0.04,
        window_coverage_delta=-0.03,
    )

    assert summary["win_rate_first_acceptance"] is True
```

- [ ] **Step 4: Run the walk-forward test to verify it fails**

Run: `uv run pytest tests/backtesting/test_walk_forward.py::test_walk_forward_summary_flags_trend_corrected_candidate_when_win_rate_improves_but_payoff_stays_bounded -q`
Expected: `FAILED` because the helper / summary field does not exist yet.

- [ ] **Step 5: Implement the minimal win-rate-first rollout logic**

```python
WIN_RATE_FIRST_METRICS = ("selected_win_rate", "execution_eligible_win_rate")
MODEST_TRADEOFF_LIMITS = {
    "selected_payoff_ratio": -0.08,
    "window_coverage": -0.05,
}

def _passes_win_rate_first_acceptance(entry: dict[str, Any]) -> bool:
    if any(_safe_float(entry.get(f"{metric}_delta")) in (None, 0.0) or float(entry[f"{metric}_delta"]) <= 0.0 for metric in WIN_RATE_FIRST_METRICS):
        return False
    for metric, floor in MODEST_TRADEOFF_LIMITS.items():
        delta = _safe_float(entry.get(f"{metric}_delta"))
        if delta is not None and delta < floor:
            return False
    return True
```

- [ ] **Step 6: Expose the win-rate-first verdict in comparison / rollout payloads**

```python
baseline_verdicts[baseline_name]["win_rate_first_acceptance"] = _passes_win_rate_first_acceptance(entry)
if all(verdict.get("win_rate_first_acceptance") for verdict in baseline_verdicts.values()):
    payload["win_rate_first_decision"] = "pass"
```

- [ ] **Step 7: Run the focused Task 2 slice**

Run: `uv run pytest tests/test_optimize_profile_script.py tests/targets/test_trend_continuation_strength_v2.py tests/backtesting/test_walk_forward.py -q`
Expected: `PASS`

- [ ] **Step 8: Commit Task 2**

```bash
git add scripts/optimize_profile.py \
  scripts/btst_profile_compare.py \
  tests/test_optimize_profile_script.py \
  tests/targets/test_trend_continuation_strength_v2.py \
  tests/backtesting/test_walk_forward.py
git commit -m "feat: add BTST win-rate-first trend validation"
```

### Task 3: Document validated factor or governance uplift for BTST skill consumption

**Files:**
- Create: `docs/prompt/generate_file/<factor-or-feature>-2026-05-17.md`
- Modify: `skills/ai-hedge-fund-btst` (only if the validated behavior changes the skill-facing explanation path)
- Test/verify: targeted regression slice from Tasks 1 and 2 plus markdown inspection

- [ ] **Step 1: Write the failing documentation contract test**

```python
def test_validated_btst_factor_doc_contains_principle_effect_validation_and_usage(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "prompt" / "generate_file" / "win-rate-first-prior-quality-shrinkage-2026-05-17.md"
    path.write_text(render_validated_btst_factor_doc(
        factor_name="win-rate-first-prior-quality-shrinkage",
        validation_summary="selected win rate +4.0ppt",
    ), encoding="utf-8")

    content = path.read_text(encoding="utf-8")
    assert "## 原理" in content
    assert "## 提升效果" in content
    assert "## 如何验证" in content
    assert "## 如何使用" in content
```

- [ ] **Step 2: Run the documentation contract test to verify it fails**

Run: `uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py::test_validated_btst_factor_doc_contains_principle_effect_validation_and_usage -q`
Expected: `FAILED` because the doc renderer/helper does not exist yet.

- [ ] **Step 3: Write the minimal documentation artifact**

```markdown
# win-rate-first-prior-quality-shrinkage-2026-05-17

## 原理
- ...

## 提升效果
- ...

## 如何验证
- ...

## 如何使用
- ...
```

- [ ] **Step 4: If needed, wire the validated doc into the BTST skill explanation path**

```python
doc_paths = sorted(Path("docs/prompt/generate_file").glob("*-2026-05-17.md"))
```

- [ ] **Step 5: Run the final regression slice**

Run: `uv run pytest tests/test_btst_execution_eligibility_contract.py tests/test_btst_prior_shrinkage.py tests/test_btst_regime_gate_enforcement.py tests/test_optimize_profile_script.py tests/targets/test_trend_continuation_strength_v2.py tests/backtesting/test_walk_forward.py tests/test_generate_btst_next_day_trade_brief_script.py -q`
Expected: `PASS`

- [ ] **Step 6: Commit Task 3**

```bash
git add docs/prompt/generate_file \
  skills/ai-hedge-fund-btst \
  tests/test_generate_btst_next_day_trade_brief_script.py
git commit -m "docs: record validated BTST win-rate uplift"
```

### Task 4: Merge and finish

**Files:**
- Modify: none required beyond prior tasks
- Test: rerun the focused BTST regression slice from Task 3

- [ ] **Step 1: Run the merged regression slice**

Run: `uv run pytest tests/test_btst_execution_eligibility_contract.py tests/test_btst_prior_shrinkage.py tests/test_btst_regime_gate_enforcement.py tests/test_optimize_profile_script.py tests/targets/test_trend_continuation_strength_v2.py tests/backtesting/test_walk_forward.py tests/test_generate_btst_next_day_trade_brief_script.py -q`
Expected: `PASS`

- [ ] **Step 2: Use the finishing workflow**

Required sub-skill: `superpowers:finishing-a-development-branch`

- [ ] **Step 3: Merge or clean up according to the finishing workflow**

```bash
git --no-pager status --short
git --no-pager log --oneline --decorate -5
```
