# BTST 20% Runner Objective Design

## Problem

The current BTST optimization path is still centered on **T+1 precision and downside control**:

1. candidate evaluation still leans on `next_close_positive_rate`, `next_close_expectancy`, and low-threshold `next_high_hit_rate_at_threshold`,
2. recent optimized outputs improve watchlist quality and risk filtering, but still frequently produce `primary_count = 0`,
3. the current label and validation surfaces are not explicitly aligned with the user goal:
   - buy on the next trading day,
   - then maximize the chance of seeing **more than 20% return within the next 2-5 trading days**.

That creates a mismatch between what the optimizer protects and what the user actually wants. If the system keeps optimizing for “small positive next-day outcomes,” it will continue to over-prefer stable-but-moderate names and under-select true short-window runners.

## Current Evidence

### The current BTST stack is precise, but not yet runner-aligned

- `outputs/202605/20260513/` shows the latest optimized configuration improved ranking, removed weak names, and strengthened guardrails.
- However, the optimized run still produced:
  - `primary_count = 0`
  - `near_miss_count = 2`
  - `opportunity_pool_count = 3`
- This is evidence that the current optimization cycle is improving **precision and risk control**, not necessarily **tail-winner capture**.

### The current metric surface is too short and too mild for a 20% goal

- Existing BTST analysis surfaces already track `next_high_return`, `next_close_return`, `t_plus_2_close_return`, and related metrics.
- But the repo does not yet treat **2-5 day 20% winner capture** as a first-class optimization target.
- Existing thresholds such as `next_high>=2%` are useful for near-term follow-through quality, but they are too weak to distinguish “good next-day continuation” from “true 20% runner potential.”

### Current committee/rank-cap logic is designed to prevent mistakes, not promote tail bets

- The live BTST path already has strong gating through:
  - committee logic,
  - rank-cap controls,
  - profile-level admission boundaries,
  - shadow / research / blocked lane separation.
- Those mechanisms are valuable and should not be removed wholesale.
- But if every promising tail candidate must pass the same surface optimized for T+1 conservatism, the system will keep suppressing many high-upside names before they can surface as formal candidates.

## Goals

1. Align BTST optimization with the explicit target:
   - next-day entry,
   - then **2-5 trading day >20% upside capture**.
2. Preserve T+1 execution realism and downside protection as hard guardrails.
3. Improve the system’s ability to surface rare, high-upside candidates without turning the book into a noisy broad sweep.
4. Keep rollout statistically disciplined and comparable to the current BTST baseline.

## Non-Goals

1. Do not turn the system into a high-frequency broad-coverage momentum screener.
2. Do not discard current liquidity, gap-risk, and confirmation guardrails.
3. Do not treat “more candidates” as success if 20% tail-hit quality does not improve.
4. Do not promote a new runner profile purely from a small number of cherry-picked windows.

## Alternatives Considered

### 1. Loosen thresholds on the current precision profile

Increase coverage by relaxing current rank caps, score thresholds, or blocked rules.

**Rejected** because this would likely increase noise faster than it improves 20% runner capture. It changes coverage, not the underlying objective.

### 2. Keep the current objective and only reweight existing factors

Shift more weight toward breakout freshness, momentum, or catalyst factors while keeping current T+1-oriented evaluation.

**Deferred** because factor reweighting alone still leaves the wrong primary objective in place. It may produce prettier rankings without solving the target mismatch.

### 3. Introduce a dedicated runner objective with hard BTST guardrails

Treat 2-5 day 20% tail capture as the primary optimization objective, while preserving T+1 execution safety and downside constraints.

**Recommended** because it changes the system at the level that matters most: the label, the ranking target, and the rollout decision criteria.

## Recommended Approach

### Phase 1: Introduce a runner-aligned evaluation objective

Define a new BTST runner target that measures whether a candidate, when bought on the next trading day, reaches a high-return outcome within 2-5 trading days.

The core label should be:

- `max_future_high_return_2_5d >= 0.20`

Supporting fields should include:

1. `time_to_hit_20pct`
2. `t_plus_2_close_return`
3. `t_plus_3_close_return`
4. `t_plus_5_close_return`
5. `next_open_return`
6. `next_open_to_close_return`

This keeps the primary goal aligned with runner capture while still allowing the system to reason about entry realism and holding-path quality.

### Phase 2: Build a two-stage BTST runner ranking model

The live path should continue to protect quality in two stages:

1. **Stage A: BTST eligibility filter**
   - liquidity floor,
   - weak-close rejection,
   - extreme gap / crowding protections,
   - minimum confirmation quality.

2. **Stage B: runner-priority ranking**
   - prioritize breakout freshness,
   - trend acceleration,
   - volume expansion quality,
   - catalyst freshness,
   - sector/theme resonance,
   - T+2 continuation support.

This preserves the existing discipline of the BTST stack while allowing a small number of high-upside names to outrank “safe but limited” continuations.

### Phase 3: Add a controlled escape path for high-upside candidates

The design should not simply loosen all committee rules. Instead, it should add a narrow path where a candidate may survive strict rank competition if it shows a sufficiently strong runner signature.

This escape path must remain gated by:

1. entry feasibility,
2. gap-risk constraints,
3. liquidity quality,
4. downside floor behavior.

The goal is to let strong runner candidates surface without letting weak speculative names flood the formal list.

### Phase 4: Validate with dual-objective rollout criteria

A runner-oriented profile should not be promoted on tail-hit gain alone.

Promotion should require:

1. improved `2_5d_20pct_hit_rate`,
2. acceptable T+1 entry realism,
3. no severe degradation in downside / gap-risk behavior,
4. evidence across multiple windows rather than one lucky burst period.

## Architecture

The design should stay inside the existing BTST optimization and replay stack:

1. `scripts/btst_analysis_utils.py`
   - extend outcome surfaces to support 2-5 day runner-oriented metrics
2. `scripts/optimize_profile.py`
   - add a runner-oriented BTST objective / preset path
3. `src/backtesting/compare.py`
   - compare baseline vs runner candidate using both tail-hit and protected T+1 metrics
4. `src/backtesting/walk_forward.py`
   - validate the runner objective on repeated windows
5. `src/targets/short_trade_target_committee_helpers.py`
   - support a bounded high-upside escape path if the candidate surface proves valid
6. `src/targets/short_trade_target_profile_data.py`
   - define runner-oriented profile constants only after validation evidence exists

No separate framework is needed. The correct move is to extend the current BTST optimization surfaces rather than creating a parallel research-only pipeline.

## Data Flow

The intended flow is:

`selection artifacts -> runner outcome labeling (2-5d) -> candidate scoring / ranking -> baseline-vs-runner comparison -> walk-forward validation -> rollout verdict`

Required invariants:

1. runner metrics and baseline metrics must be computed on the same candidate windows,
2. T+1 execution realism must remain a hard constraint,
3. candidate ranking must not silently merge blocked, shadow, research, and formal lanes,
4. the runner profile must remain low-frequency by design rather than broad-coverage by accident.

## Metrics That Matter

### Primary objective metrics

1. `max_future_high_return_2_5d_hit_rate_at_20pct`
2. `median_max_future_high_return_2_5d`
3. `runner_capture_count`
4. `time_to_hit_20pct_median`

### Protected BTST metrics

1. `next_open_return`
2. `next_open_to_close_return`
3. `next_close_positive_rate`
4. `next_close_return_p10`
5. `gap_risk_raw_100`

### Feasibility and sample quality

1. `closed_cycle_count`
2. `next_day_available_count`
3. `tradeable_total_count`
4. source coverage mix for key intraday-derived metrics when available

## Error Handling and Safe Defaults

1. If 2-5 day outcome fields are missing for a replay window, the result should be “insufficient runner evidence,” not a winner.
2. If a candidate improves 20% hit rate but materially worsens T+1 entry realism or downside floors, it should not be promotable.
3. If the runner objective only works on a tiny sample count, the result should be flagged as sample-limited rather than rollout-ready.
4. If no candidate clears both tail-hit and BTST-protection criteria, keep the current precision-oriented live profile.

## Validation Strategy

### 1. Label-surface validation

Add tests proving the runner objective correctly computes:

1. 2-5 day max-high outcome,
2. time-to-hit fields,
3. protected T+1 companion metrics.

### 2. Baseline-vs-runner comparison validation

Add tests proving that:

1. a runner candidate with better tail-hit but unacceptable T+1 regression is rejected,
2. a candidate with higher coverage but no tail-hit improvement is not promoted,
3. a candidate with better tail-hit and acceptable guardrails can be shortlisted.

### 3. Walk-forward validation

Evaluate the runner profile against the current BTST baseline across repeated windows and produce a verdict such as:

1. `promotable_runner_profile`
2. `tail_hit_better_but_t1_risky`
3. `coverage_only_not_runner_better`
4. `keep_precision_baseline`

## Success Criteria

This cycle is successful if:

1. the repo can evaluate BTST candidates against a real 2-5 day 20% runner objective,
2. the ranking logic can surface high-upside names without collapsing execution discipline,
3. rollout decisions become explicitly aware of tail-hit improvement and T+1 protection together,
4. the final output can distinguish “true runner improvement” from “more names, more noise.”

## Failure Criteria

This cycle should be considered unsuccessful if:

1. the system still optimizes primarily for small next-day wins,
2. the runner objective increases candidate count without improving 20% hit quality,
3. the rollout path accepts a tail-hit gain that depends on poor T+1 entry quality,
4. the profile cannot outperform baseline except in isolated lucky windows.

## Expected Implementation Surfaces

1. `scripts/btst_analysis_utils.py`
2. `scripts/optimize_profile.py`
3. `src/backtesting/compare.py`
4. `src/backtesting/walk_forward.py`
5. `src/targets/short_trade_target_committee_helpers.py`
6. `src/targets/short_trade_target_profile_data.py`
7. targeted BTST tests under `tests/`

## Assumptions

This design assumes the desired default direction is:

1. **high-precision, low-frequency runner capture** rather than broad candidate expansion,
2. next-day buy feasibility remains a hard requirement,
3. the first rollout target is better 20% tail-hit quality, not higher formal trade count.
