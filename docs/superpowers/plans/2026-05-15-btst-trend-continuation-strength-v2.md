# BTST Trend Continuation Strength v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a narrow BTST factor candidate that improves T+1 win rate / payoff / downside by combining trend continuation with close-retention and volume-confirmation quality.

**Architecture:** Add a small, testable score-adjustment helper that can reward continuation only when close/volume support is present, wire it into the existing BTST score-target path, then introduce one offline candidate profile and validate it with the existing 20-day, multi-window, and strict-objective gates. Do not touch admission-edge, risk-budget, or manifest publication rules in this cycle.

**Tech Stack:** Python 3.12, pytest, existing BTST target helpers in `src/targets/`, existing replay tooling in `scripts/`

---

## File Structure

- Create: `src/targets/short_trade_target_factor_helpers.py` — focused helper for `trend_continuation_strength_v2` score adjustment logic
- Create: `tests/targets/test_trend_continuation_strength_v2.py` — unit tests for helper math and profile wiring
- Modify: `src/targets/profiles.py` — add profile fields for the new adjustment
- Modify: `src/targets/short_trade_target_profile_data.py` — register the offline candidate profile / override set
- Modify: `src/targets/short_trade_target_snapshot_relief_helpers.py` — apply the new adjustment inside `_build_snapshot_score_payload()`
- Modify: `src/targets/short_trade_metrics_payload_builders.py` — expose the new factor contribution in metrics payloads
- Modify: `tests/test_optimize_profile_script.py` — cover the validation / rollout interpretation if new artifacts are surfaced there
- Optional Modify (only if needed): `scripts/optimize_profile.py` — only if the existing payload shape cannot carry the new factor diagnostics cleanly

### Task 1: Add a testable trend-continuation-strength helper

**Files:**
- Create: `src/targets/short_trade_target_factor_helpers.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from src.targets.short_trade_target_factor_helpers import compute_trend_continuation_strength_adjustment


def test_trend_continuation_strength_rewards_supported_continuation() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.82,
        close_strength=0.74,
        volume_expansion_quality=0.68,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.08,
    )

    assert adjustment > 0.0


def test_trend_continuation_strength_penalizes_weak_close_retention() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.84,
        close_strength=0.28,
        volume_expansion_quality=0.63,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.5,
    )

    assert adjustment < 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing symbol errors for `short_trade_target_factor_helpers`

- [ ] **Step 3: Write the minimal helper implementation**

```python
from __future__ import annotations


def compute_trend_continuation_strength_adjustment(
    *,
    trend_continuation: float,
    close_strength: float,
    volume_expansion_quality: float,
    continuation_weight: float,
    close_support_floor: float,
    volume_support_floor: float,
    weak_close_penalty: float,
) -> float:
    base_uplift = max(0.0, trend_continuation) * max(0.0, continuation_weight)
    close_support = max(0.0, close_strength - close_support_floor)
    volume_support = max(0.0, volume_expansion_quality - volume_support_floor)
    weak_close_drag = max(0.0, close_support_floor - close_strength) * weak_close_penalty
    return round(base_uplift * (1.0 + close_support + volume_support) - weak_close_drag, 4)
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py -q`

Expected: PASS with 2 tests passing

- [ ] **Step 5: Commit**

```bash
git add src/targets/short_trade_target_factor_helpers.py tests/targets/test_trend_continuation_strength_v2.py
git commit -m "feat: add btst trend continuation strength helper"
```

### Task 2: Add profile fields and wire the candidate profile

**Files:**
- Modify: `src/targets/profiles.py`
- Modify: `src/targets/short_trade_target_profile_data.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`

- [ ] **Step 1: Extend the tests with profile expectations**

```python
from src.targets import build_short_trade_target_profile


def test_trend_continuation_strength_v2_profile_sets_new_factor_knobs() -> None:
    profile = build_short_trade_target_profile("trend_continuation_strength_v2")

    assert profile.trend_continuation_weight > 0.0
    assert profile.short_term_reversal_weight == 0.0
    assert profile.reversal_2d_weight == 0.0
    assert profile.selected_close_retention_penalty_weight > 0.0
    assert profile.trend_continuation_strength_weight > 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py::test_trend_continuation_strength_v2_profile_sets_new_factor_knobs -q`

Expected: FAIL because `trend_continuation_strength_v2` or the new profile fields do not exist yet

- [ ] **Step 3: Add the profile fields and candidate profile**

```python
# src/targets/profiles.py
trend_continuation_strength_weight: float = 0.0
trend_continuation_strength_close_support_floor: float = 0.0
trend_continuation_strength_volume_support_floor: float = 0.0
trend_continuation_strength_weak_close_penalty: float = 0.0
```

```python
# src/targets/short_trade_target_profile_data.py
SHORT_TRADE_TARGET_PROFILES["trend_continuation_strength_v2"] = replace(
    SHORT_TRADE_TARGET_PROFILES["trend_corrected_v1"],
    name="trend_continuation_strength_v2",
    trend_continuation_weight=0.18,
    trend_continuation_2d_weight=0.10,
    close_strength_weight=0.12,
    volume_expansion_quality_weight=0.18,
    selected_close_retention_penalty_weight=0.06,
    trend_continuation_strength_weight=0.12,
    trend_continuation_strength_close_support_floor=0.55,
    trend_continuation_strength_volume_support_floor=0.45,
    trend_continuation_strength_weak_close_penalty=0.08,
)
```

- [ ] **Step 4: Run the profile test to verify it passes**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py::test_trend_continuation_strength_v2_profile_sets_new_factor_knobs -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/targets/profiles.py src/targets/short_trade_target_profile_data.py tests/targets/test_trend_continuation_strength_v2.py
git commit -m "feat: add btst trend continuation strength candidate profile"
```

### Task 3: Apply the factor inside score_target and surface it in diagnostics

**Files:**
- Modify: `src/targets/short_trade_target_snapshot_relief_helpers.py`
- Modify: `src/targets/short_trade_metrics_payload_builders.py`
- Test: `tests/targets/test_trend_continuation_strength_v2.py`

- [ ] **Step 1: Add a failing integration-style test around the score payload**

```python
from src.targets.short_trade_target_factor_helpers import compute_trend_continuation_strength_adjustment


def test_trend_continuation_strength_adjustment_is_exposed_in_metrics_payload() -> None:
    adjustment = compute_trend_continuation_strength_adjustment(
        trend_continuation=0.81,
        close_strength=0.71,
        volume_expansion_quality=0.66,
        continuation_weight=0.12,
        close_support_floor=0.55,
        volume_support_floor=0.45,
        weak_close_penalty=0.08,
    )

    assert round(adjustment, 4) == 0.1233
```

- [ ] **Step 2: Run the test to verify it fails with the current math**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py::test_trend_continuation_strength_adjustment_is_exposed_in_metrics_payload -q`

Expected: FAIL until the helper math and score payload are aligned

- [ ] **Step 3: Wire the adjustment into `_build_snapshot_score_payload()` and metrics payloads**

```python
# src/targets/short_trade_target_snapshot_relief_helpers.py
trend_continuation_strength_adjustment = compute_trend_continuation_strength_adjustment(
    trend_continuation=state.trend_continuation,
    close_strength=state.close_strength,
    volume_expansion_quality=threshold_state.volume_expansion_quality,
    continuation_weight=float(getattr(profile, "trend_continuation_strength_weight", 0.0) or 0.0),
    close_support_floor=float(getattr(profile, "trend_continuation_strength_close_support_floor", 0.0) or 0.0),
    volume_support_floor=float(getattr(profile, "trend_continuation_strength_volume_support_floor", 0.0) or 0.0),
    weak_close_penalty=float(getattr(profile, "trend_continuation_strength_weak_close_penalty", 0.0) or 0.0),
)
```

```python
# add into the score_target formula
+ trend_continuation_strength_adjustment
```

```python
# add into returned payload
"trend_continuation_strength_adjustment": round(trend_continuation_strength_adjustment, 4),
```

```python
# src/targets/short_trade_metrics_payload_builders.py
"trend_continuation_strength_weight": round(float(getattr(profile, "trend_continuation_strength_weight", 0.0) or 0.0), 4),
"trend_continuation_strength_adjustment": round(float(snapshot.get("trend_continuation_strength_adjustment", 0.0) or 0.0), 4),
```

- [ ] **Step 4: Run the focused test file**

Run: `uv run pytest tests/targets/test_trend_continuation_strength_v2.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/targets/short_trade_target_snapshot_relief_helpers.py src/targets/short_trade_metrics_payload_builders.py tests/targets/test_trend_continuation_strength_v2.py
git commit -m "feat: apply btst trend continuation strength scoring"
```

### Task 4: Validate the candidate with existing BTST replay tooling

**Files:**
- Modify: `tests/test_optimize_profile_script.py` (only if a new rollout payload field is needed)
- Output: `data/reports/btst_trend_continuation_strength_v2_20d.json`
- Output: `data/reports/btst_trend_continuation_strength_v2_multi_window_validation.json`
- Output: `data/reports/btst_trend_continuation_strength_v2_rollout_assessment.md`

- [ ] **Step 1: Add a failing test only if rollout payload needs a new diagnostics field**

```python
def test_build_rollout_recommendation_payload_carries_trend_continuation_strength_context() -> None:
    payload = _build_rollout_recommendation_payload({"trend_continuation_strength_v2": {}})
    assert "strict_btst_objective_gate" in payload
```

- [ ] **Step 2: Run the targeted test if Step 1 was needed**

Run: `uv run pytest tests/test_optimize_profile_script.py -k trend_continuation_strength_context -q`

Expected: FAIL only if the existing payload shape is insufficient

- [ ] **Step 3: Run the focused 20-day validation**

Run:

```bash
uv run python scripts/btst_20day_backtest.py \
  --profiles btst_precision_v2,trend_continuation_strength_v2 \
  --output-json data/reports/btst_trend_continuation_strength_v2_20d.json
```

Expected: JSON artifact exists with baseline vs candidate deltas

- [ ] **Step 4: Run the multi-window replay validation**

Run:

```bash
PYTHONPATH="$(pwd)" uv run python scripts/analyze_btst_multi_window_profile_validation.py \
  --reports-root data/reports \
  --baseline-profile btst_precision_v2 \
  --variant-profile trend_continuation_strength_v2 \
  --output-json data/reports/btst_trend_continuation_strength_v2_multi_window_validation.json \
  --output-md data/reports/btst_trend_continuation_strength_v2_multi_window_validation.md
```

Expected: Markdown artifact classifies the candidate as promotable, mixed, or keep-baseline

- [ ] **Step 5: Refresh strict-objective context and summarize the result**

Run:

```bash
uv run python scripts/btst_strict_objective_gate.py \
  --input-md data/reports/btst_tplus1_tplus2_objective_monitor_latest.md \
  --output-json data/reports/btst_strict_objective_gate.json \
  --output-md data/reports/btst_strict_objective_gate.md
```

Then record the decision in a short note inside the session / PR summary:

```text
Primary metrics must show 2 improvements + 1 non-regression.
If strict-objective blockers or replay zero-delta persist, keep the candidate offline.
```

- [ ] **Step 6: Run the focused regression slice**

Run:

```bash
uv run pytest tests/targets/test_trend_continuation_strength_v2.py tests/test_optimize_profile_script.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/targets/test_trend_continuation_strength_v2.py tests/test_optimize_profile_script.py src/targets/profiles.py src/targets/short_trade_target_profile_data.py src/targets/short_trade_target_snapshot_relief_helpers.py src/targets/short_trade_metrics_payload_builders.py src/targets/short_trade_target_factor_helpers.py
git commit -m "feat: validate btst trend continuation strength v2"
```

## Self-Review

- Spec coverage: the tasks cover the new factor family, runtime wiring, diagnostics, and replay-based validation gates from the approved spec.
- Placeholder scan: no TBD/TODO markers or “figure it out later” steps remain.
- Type consistency: the same field names are used throughout the plan — `trend_continuation_strength_weight`, `trend_continuation_strength_close_support_floor`, `trend_continuation_strength_volume_support_floor`, and `trend_continuation_strength_weak_close_penalty`.
