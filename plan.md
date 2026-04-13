# Execution Plan: Backtesting Optimization Follow-up

## Status Snapshot

### Completed
- Task 1 is already complete. Empty `strategy_signals` now emits a warning in `src/targets/short_trade_target_input_helpers.py`, so silent neutral-score fallback is observable.
- Task 2 is mostly complete.
	- `src/backtesting/walk_forward.py` already contains `WindowMode` and `WALK_FORWARD_PRESETS`.
	- `src/backtesting/cli_helpers.py` already exposes `--window-mode` and `--walk-forward-preset`.
	- `src/backtesting/cli.py` already applies preset and window-mode values when running walk-forward mode.

### Remaining Gaps
- `tests/backtesting/test_walk_forward.py` does not yet cover expanding windows or preset semantics.
- The `fast` preset still needs a clear contract. The current implementation models it as a trading-day-capped test window, but the builder still requires positive month lengths.
- `src/backtesting/compare.py` still uses raw month arguments only and does not yet support preset or window-mode propagation.
- No reusable parameter search runner exists yet.
- `momentum_optimized` has not yet been revalidated through an automated staged search.

### Existing Tools To Reuse
- `scripts/analyze_btst_profile_frontier.py` already compares profile outcomes on a replay input.
- `scripts/analyze_btst_multi_window_profile_validation.py` already compares a baseline and variant across multiple report windows.
- `src/targets/profiles.py` already supports profile injection through `use_short_trade_target_profile(...)`.

The remaining work should extend these capabilities rather than build a parallel framework from scratch.

---

## Task A: Finish Walk-Forward Rollout

### Goal
Close the remaining walk-forward gaps so the feature is fully specified, tested, and consistent across both direct walk-forward runs and A/B comparison runs.

### Scope
1. Add tests for expanding-window generation.
2. Add tests for preset behavior, including precedence over explicit month arguments.
3. Resolve the `fast` preset contract.
4. Decide whether A/B compare should accept `window_mode` and `walk_forward_preset` now, or be explicitly documented as rolling-only.

### Recommended Decision
- Keep `standard`, `extended`, and `seasonal` as stable presets.
- Treat `fast` as one of two explicit options:
	- Option A: keep it, but document it as `1m train + 1m test capped at 10 trading days`.
	- Option B: remove it until the window builder supports non-month test horizons directly.

### Files
- `tests/backtesting/test_walk_forward.py`
- `src/backtesting/compare.py`
- `src/backtesting/cli.py`
- `src/backtesting/cli_helpers.py`

### Acceptance Criteria
- Expanding-window behavior is covered by tests.
- Preset precedence is covered by tests.
- The `fast` preset behavior is no longer ambiguous.
- A/B compare is either aligned with walk-forward options or explicitly documented as intentionally narrower.

---

## Task B: Build A Minimal Parameter Search Runner

### Goal
Add a reusable search runner for profile tuning without duplicating the existing replay-analysis toolchain.

### Design Constraints
- Version 1 supports grid search only.
- Evaluation should reuse existing replay/profile-validation utilities wherever possible.
- The runner must support checkpointing and resume.
- Output must include structured JSON plus a readable Markdown summary.
- This is multi-window evaluation, not true model training. The implementation and docs should state that clearly.

### Recommended Shape
Create a thin orchestration layer that:
1. Enumerates parameter combinations.
2. Applies each combination through `use_short_trade_target_profile(...)` or explicit profile overrides.
3. Evaluates each trial against replay inputs or discovered report windows.
4. Scores each trial with a configurable objective plus guardrails.
5. Saves completed trials so long runs can resume safely.

### Candidate Files
- `src/backtesting/param_search.py`
- `scripts/optimize_profile.py`
- `tests/backtesting/test_param_search.py`

### Acceptance Criteria
- A stopped search can resume from checkpoint without rerunning completed trials.
- The runner can rank trials by an explicit objective.
- The runner can emit both JSON and Markdown outputs.
- Unit tests cover parameter enumeration, checkpoint resume, and ranking behavior.

---

## Task C: Optimize `momentum_optimized` With Staged Search

### Goal
Tune `SHORT_TRADE_TARGET_PROFILES["momentum_optimized"]` using a bounded search process that is actually executable.

### Why The Original Grid Is Not Acceptable
The original nine-parameter full grid would produce 640000 combinations before multiplying by replay windows. That is too expensive and too slow for routine iteration.

### Staged Search Plan
1. Stage 1: coarse search on a small set of threshold and penalty parameters.
2. Stage 2: narrow follow-up search around the top Stage 1 candidates.
3. Stage 3: compare the best candidate against both the current `momentum_optimized` profile and the `default` profile across multiple windows.
4. Update the shipped profile only if the candidate passes the defined guardrails.

### Suggested Search Budget
- Stage 1: at most 40 to 60 combinations.
- Stage 2: at most 20 to 30 combinations.
- Final comparison: top 1 to 3 candidates only.

### Guardrails
- Do not accept a candidate that regresses protected T+1 quality metrics on key windows.
- Do not accept a candidate solely because it expands tradeable surface while weakening downside or lower-quantile outcomes.
- Save all winning and rejected candidates with enough metadata to explain the decision later.

### Files
- `scripts/optimize_profile.py`
- `src/targets/profiles.py`
- Search outputs under `data/reports/`

### Acceptance Criteria
- The best candidate is supported by saved artifacts, not just a terminal summary.
- Baseline comparison includes both current `momentum_optimized` and `default`.
- If no candidate clearly passes guardrails, the profile remains unchanged and the report states that explicitly.

---

## Execution Order

1. Finish Task A and lock down tests plus preset semantics.
2. Implement Task B as a thin layer on top of existing replay-analysis utilities.
3. Run Stage 1 coarse search for `momentum_optimized`.
4. Run Stage 2 focused search around the best candidates.
5. Update the profile only if the final candidate passes the guardrails.

---

## Open Decisions

- Decide whether `fast` should remain as a capped monthly preset or be removed until non-month test horizons are supported natively.
- Decide whether `src/backtesting/compare.py` should gain full preset and window-mode support in the same change set.
- Decide whether the first implementation of parameter search should run on replay artifacts by default. Current recommendation: yes, because replay artifacts are cheaper, easier to inspect, and better aligned with the existing validation scripts.
