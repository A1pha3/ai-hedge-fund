# BTST Structural Promotion Guardrail Design

## Problem

The latest BTST cycle surfaced a governance gap:

1. replay artifacts can show T+1 instability caused by `selected` / `near_miss` structure expansion,
2. the current strict objective gate focuses on rejected-vs-tradeable quality and false negatives,
3. there is no explicit promotion blocker for candidates that widen the structure faster than they improve T+1 quality.

This leaves a blind spot between "the artifacts explain why the candidate feels unstable" and "the rollout gate formally blocks promotion or skill adoption."

## Goal

Design a dual-layer BTST structural guardrail that:

1. explains structural expansion clearly in admission / replay artifacts,
2. blocks promotion when the expansion is materially unstable,
3. prevents `ai-hedge-fund-btst` from adopting candidates that broaden `selected` / `near_miss` without clearing T+1 quality rules.

The deliverable of this cycle is governance logic and artifacts, not a broader rollout rule relaxation.

## Non-Goals

1. Do not replace the existing strict objective gate.
2. Do not let structure shrink alone justify promotion.
3. Do not block candidates based on raw absolute count changes alone across windows of very different sizes.
4. Do not change execution logic or report rendering beyond what is needed to expose the new guardrail.

## Recommended Approach

Use a **dual-layer structural promotion guardrail**:

1. **Admission / replay layer:** always report absolute and relative structure deltas for `selected`, `near_miss`, and `execution_eligible`.
2. **Strict gate layer:** treat repeated out-of-tolerance structure expansion as a hard blocker for promotion.

The hard blocker should use **ratio-based per-window expansion** plus a **multi-window count threshold**, because window sizes vary too much for absolute counts to be stable on their own.

## Structural Guardrail Rule

Define a window as structurally excessive when all of the following are true:

1. the window is not classified as `variant_supports_t1_edge`,
2. `selected` expands by more than **15%** relative to baseline **or**
3. `near_miss` expands by more than **20%** relative to baseline.

Define a candidate as structurally blocked when either of the following holds:

1. structurally excessive expansion appears in **2 or more** replay windows, or
2. the focused 20-day validation expands `selected` or `near_miss` by more than **10%** while the T+1 primary rule still fails.

## Alternative Approaches Considered

### 1. Absolute-count blocker only

Pros:

1. simple to understand.

Cons:

1. brittle across small and large windows,
2. easy to overreact to small absolute changes in short windows.

### 2. Relative-ratio blocker only

Pros:

1. normalizes across windows.

Cons:

1. a single noisy small window can dominate the verdict,
2. lacks a governance notion of repeatability.

### 3. Ratio + multi-window count blocker **(recommended)**

Pros:

1. normalizes by window size,
2. still requires repeatable evidence,
3. fits gamma's rollout-governance need best.

Cons:

1. slightly more logic to explain,
2. requires explicit artifact fields.

## Architecture

### Admission / replay surfaces

1. `scripts/btst_admission_replay_validator.py`
2. `scripts/analyze_btst_multi_window_profile_validation.py`
3. any helper used to summarize multi-window deltas

### Promotion / rollout surfaces

1. `scripts/btst_strict_objective_gate.py`
2. `scripts/optimize_profile.py`
3. `skills/ai-hedge-fund-btst/SKILL.md` only after the candidate clears the new blocker

### Tests

1. `tests/test_btst_admission_replay_validator.py`
2. `tests/test_btst_strict_objective_gate.py`
3. any focused optimize-profile integration tests already covering strict gate payloads

## Data Flow

The intended path is:

`20d / multi-window validation -> structural delta summary -> admission replay artifact -> strict gate blocker evaluation -> optimize_profile rollout decision -> skill adoption decision`

This keeps the explanatory layer separate from the hard governance layer while still sharing one consistent definition of "structurally excessive."

## Validation Rules

### Admission-layer requirements

The admission artifact must report:

1. absolute deltas for `selected`, `near_miss`, and `execution_eligible`,
2. ratio deltas for the same surfaces,
3. how many windows breached the structure-expansion tolerance,
4. whether the expansion coincided with T+1 support or with T+1 regression.

### Strict-gate requirements

The strict gate must add structural blockers when the rule above is triggered, for example:

1. `structural_selected_expansion_exceeded`
2. `structural_near_miss_expansion_exceeded`
3. `structural_expansion_repeated_across_windows`

### Promotion requirement

No candidate may be promoted or wired into `ai-hedge-fund-btst` if structural blockers remain active.

## Testing Strategy

Add or extend tests in this order:

1. admission-summary unit tests for ratio and changed-window counting,
2. strict-gate unit tests that turn the new structural conditions into blockers,
3. optimize-profile integration coverage proving the new blockers reach rollout decisions,
4. focused regression commands on the strict gate and optimizer surfaces.

## Failure Criteria

Stop and keep the baseline if any of the following remain true:

1. structure expansion is repeated across replay windows,
2. 20-day structure expands beyond tolerance without T+1 improvement,
3. the new guardrail can be bypassed by artifacts that still say `hold`,
4. the candidate needs the structure blocker disabled in order to look promotable.

## Expected Deliverables

1. admission artifacts that explicitly summarize structural expansion pressure,
2. strict gate artifacts with structural blockers,
3. optimize-profile rollout decisions that honor the new blocker,
4. unchanged skill/runtime adoption unless the blockers clear.

## Decision Rule

If a candidate avoids repeated ratio-based structure expansion, clears T+1 primary validation, and survives the strict gate with no structural blockers, it may proceed to rollout review. Otherwise it remains offline and the BTST skill must continue using the current baseline evidence chain.
