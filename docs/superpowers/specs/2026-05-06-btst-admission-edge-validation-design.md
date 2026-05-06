# BTST Admission Edge Validation Design

## Problem

The `btst_admission_edge_recovery` branch now contains three coordinated BTST improvements:

1. regime-aware admission recovery,
2. adaptive prior shrinkage,
3. entry-mode payoff calibration.

The code is implemented and regression-tested, but the branch still lacks **post-change replay evidence** proving that the combined profile improves BTST quality relative to the current baseline. Without that evidence, the next logic change would be premature and could re-open weak-regime losses or hide a trade-count recovery that does not actually improve payoff.

## Current Evidence

### The largest residual drag is still weak-regime sensitivity

- `data/reports/p0_btst_0422_baseline_freeze.json` shows:
  - `selected_expectation = -0.0448`
  - `post_fee_expectation_low = -0.16`
  - `post_fee_expectation_high = -0.12`
  - weak regime:
    - `day_count = 8`
    - `close_win_rate = 22.6`
    - `payoff_ratio = 0.93`
    - `relative_profit_contribution = -7502.0`
  - strong regime:
    - `day_count = 7`
    - `close_win_rate = 76.0`
    - `payoff_ratio = 1.66`
    - `relative_profit_contribution = 6749.0`

### The new profile exists, but no multi-window decision artifact exists yet

- `src/targets/short_trade_target_profile_data.py` now defines `btst_admission_edge_recovery`.
- The current branch validates the mechanics with targeted tests, but there is still no dedicated artifact showing whether this profile:
  1. improves T+1 edge,
  2. preserves downside,
  3. recovers formal trade count on normal/strong windows,
  4. avoids weak-regime regressions.

### Existing validation infrastructure is already sufficient

- `scripts/analyze_btst_multi_window_profile_validation.py` can compare a baseline vs variant profile across multiple replay windows.
- `scripts/analyze_btst_weekly_validation.py` can summarize week-level realized outcomes.
- `scripts/optimize_profile.py` already provides replay evaluators and checkpointable parameter search if the first pass shows mixed but promising results.

## Goals

1. Produce a clear go/no-go artifact for `btst_admission_edge_recovery` versus the current BTST baseline.
2. Measure whether the new profile improves T+1 edge while preserving downside and weak-regime containment.
3. Decide whether the next cycle should be:
   - rollout review,
   - targeted weak-regime retuning,
   - or additional diagnostics only.

## Non-Goals

1. Do not add new BTST selection logic before the validation verdict exists.
2. Do not run an open-ended parameter search before a fixed-profile comparison is completed.
3. Do not broaden candidate-pool size or change baseline profile defaults in this cycle.
4. Do not treat weekly validation alone as enough evidence if multi-window comparison is still mixed.

## Alternatives Considered

### 1. Tighten weak-regime logic immediately

Add another regime gate or stricter weak-regime suppression right away.

**Rejected for now** because the new recovery profile has not yet been measured. Without post-change evidence, a new gate could solve the wrong problem or bury a real trade-count improvement.

### 2. Build more diagnostics first

Add more reporting for relief activation, regime coverage, or profile transitions before running replay validation.

**Deferred** because existing scripts already surface enough outcome metrics to decide whether the profile deserves deeper investment. More diagnostics only matter if the current validation results are ambiguous.

### 3. Validation-first workflow

Use the existing multi-window and weekly validation tooling to compare `btst_admission_edge_recovery` against the current baseline, then decide the next logic move from measured evidence.

**Recommended** because it is the fastest path to separating real edge improvement from cosmetic trade-count recovery.

## Recommended Approach

### Phase 1: Multi-window profile comparison

Run the new profile against the baseline across all eligible `paper_trading_window` reports using:

1. `baseline_profile = btst_precision_v2`
2. `variant_profile = btst_admission_edge_recovery`

The primary outcome of this phase is a structured verdict per window:

- `variant_supports_t1_edge`
- `variant_improves_t2_but_not_t1`
- `keep_baseline_default`
- `mixed`

### Phase 2: Weekly validation on the most relevant live-like window

If the multi-window comparison is not clearly negative, run a week-level validation summary to confirm that the recovered admission surface behaves consistently across adjacent dates rather than only isolated windows.

### Phase 3: Decision gate

Interpret the validation outcomes in one of three ways:

1. **Promising** — the profile improves or preserves T+1 edge and downside across windows; move to rollout review.
2. **Mixed** — the profile helps some windows but still leaks weak-regime damage; next cycle should retune regime handling.
3. **Negative** — keep baseline default and stop new BTST admission logic changes until a narrower hypothesis is formed.

## Architecture

This cycle should stay entirely inside the existing validation stack:

1. **Replay comparison layer** — `scripts/analyze_btst_multi_window_profile_validation.py`
2. **Weekly aggregation layer** — `scripts/analyze_btst_weekly_validation.py`
3. **Escalation layer** — `scripts/optimize_profile.py` only if the fixed-profile comparison is promising but mixed

No new BTST strategy logic is required for the first pass. The deliverable is evidence, not a new scoring rule.

## Data Flow

The intended path is:

`existing replay windows -> baseline vs variant replay -> per-window metric deltas -> weekly validation follow-up -> rollout / retune / stop decision`

Required invariants:

1. The baseline and variant must be compared on the same replay windows.
2. T+1 edge metrics must remain primary; T+2/T+3 improvements cannot justify T+1 regression for a BTST-default profile.
3. Weak-regime protection must be treated as a guardrail, not just a secondary nice-to-have.

## Metrics That Matter

### Primary

1. `next_close_positive_rate`
2. `next_close_payoff_ratio`
3. `next_close_return_p10`

### Secondary

1. `next_high_hit_rate_at_threshold`
2. `t_plus_2_close_positive_rate`
3. `t_plus_2_close_return_median`

### Feasibility

1. `closed_cycle_count`
2. `next_day_available_count`
3. `tradeable total_count`

### New-profile behavior

1. whether formal trade count recovers on normal/strong windows,
2. whether weak-regime outcomes stay contained,
3. whether the profile behaves like a true T+1 improvement rather than a T+2 tradeoff.

## Error Handling and Safe Defaults

1. Missing replay windows should block interpretation and be reported explicitly.
2. Mixed results should keep the baseline default by default.
3. If weekly validation lacks closed-cycle samples, the outcome should remain “insufficient evidence,” not “promising.”
4. If the profile only improves T+2 while hurting T+1, it should be treated as a follow-through experiment, not a BTST-default candidate.

## Validation Strategy

### 1. Multi-window validation

Run the existing profile-validation script over `paper_trading_window` reports and store dedicated JSON/Markdown outputs for this profile.

### 2. Weekly validation

Run a week-level summary over the most relevant consecutive dates once multi-window output exists.

### 3. Decision memo

Summarize:

1. baseline vs variant verdict counts,
2. the strongest supporting windows,
3. any windows where weak-regime drag still dominates,
4. the recommended next step.

## Success Criteria

This cycle is successful if all of the following hold:

1. `btst_admission_edge_recovery` receives a clear replay verdict artifact.
2. The artifact shows whether the profile improves, regresses, or mixes T+1 edge.
3. The outcome clearly tells us whether to roll forward, retune weak-regime logic, or stop.
4. No new strategy logic is introduced without measured evidence.

## Failure Criteria

This cycle should be considered unsuccessful if:

1. the validation outputs are ambiguous because windows were mismatched or missing,
2. the workflow still cannot tell T+1 improvement apart from T+2 tradeoffs,
3. we finish the cycle without a concrete next-step decision.

## Expected Implementation Surfaces

Likely files and artifacts:

1. `scripts/analyze_btst_multi_window_profile_validation.py`
2. `scripts/analyze_btst_weekly_validation.py`
3. `scripts/optimize_profile.py`
4. `data/reports/btst_admission_edge_recovery_multi_window_validation.json`
5. `data/reports/btst_admission_edge_recovery_multi_window_validation.md`
6. `data/reports/btst_admission_edge_recovery_weekly_validation.json`
7. `data/reports/btst_admission_edge_recovery_weekly_validation.md`

## Assumptions

Because the user was unavailable during brainstorming, this spec assumes approval for the following priority order:

1. validate `btst_admission_edge_recovery` against baseline,
2. interpret weak-regime behavior from the outputs,
3. only then decide whether the next logic cycle should tighten regime handling or stop.
