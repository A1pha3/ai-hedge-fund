# BTST Ignition Breakout Staged Calibration Design

## Problem

The previous BTST cycle completed three enabling changes:

1. routed validation and backtest entry points now follow the live short-trade profile route,
2. routed committee profiles now have a dedicated optimizer preset surface,
3. replay outputs now surface source-coverage guardrails.

That means the next bottleneck is no longer infrastructure trust. The next bottleneck is **actual calibration of the live routed aggressive BTST path**.

Right now, `ignition_breakout` still depends on hand-set committee thresholds and fragile-breakout knobs. The new routed optimizer preset exists, but it is still a broad brute-force surface. Without a staged, baseline-aware calibration workflow, the system risks either:

1. wasting search budget on large unstructured sweeps, or
2. promoting a high-scoring candidate that does not actually improve T+1 win rate / payoff relative to the current live baseline.

## Current Evidence

### The live routed path is now searchable

- `scripts/optimize_profile.py` now contains a routed BTST committee preset grid for `ignition_breakout`, `retention_follow`, and `shadow_research`.
- `src/backtesting/compare.py` and `src/backtesting/walk_forward.py` can now carry routed profile and preset controls through the validation path.
- `scripts/btst_profile_replay_utils.py` and `scripts/analyze_btst_multi_window_profile_validation.py` now expose source coverage summaries.

### The optimizer is not yet promotion-aware

- The optimizer can enumerate parameter combinations, but it still lacks an opinionated staged workflow for the highest-leverage routed profile.
- It does not yet enforce a promotion rule like:
  - beat current `ignition_breakout`,
  - do not regress relative to `default` on protected T+1 metrics,
  - and do not rely on weak source coverage.

### `ignition_breakout` is the right first target

- It is the routed aggressive path, so it is the most direct surface for improving BTST upside entries.
- It is also the highest-risk surface for overfitting if promotion rules are weak.
- A clean staged workflow here can later be reused for `retention_follow`, but the first cycle should stay narrow.

## Goals

1. Build a staged calibration workflow specifically for `ignition_breakout`.
2. Make the search baseline-aware, not score-only.
3. Require source-coverage guardrails before a candidate is considered promotable.
4. Keep the first calibration cycle narrow enough to be computationally usable and statistically interpretable.

## Non-Goals

1. Do not calibrate `retention_follow` in the same cycle.
2. Do not expand the optimizer into a generic auto-promotion framework for every profile.
3. Do not add new committee factors before the staged calibration workflow exists.
4. Do not treat source-coverage reporting as advisory-only; it must participate in the guardrail decision.

## Alternatives Considered

### 1. Full routed brute-force search

Run the existing routed preset grid as a large unconstrained sweep.

**Rejected for now** because the search space is still too broad and the ranking logic is not yet explicit about T+1 protection and source-coverage promotion safety.

### 2. Report-only cycle

Use the new validation and coverage artifacts, but do not change the optimizer workflow yet.

**Deferred** because the repo already has enough evidence plumbing. The missing value is not visibility alone — it is turning that visibility into a promotable search workflow.

### 3. Staged, baseline-aware ignition calibration

Build a narrow Stage 1 search mode for `ignition_breakout`, compare every candidate against the current baseline and `default`, and reject candidates that improve optimizer score while weakening protected T+1 behavior or source quality.

**Recommended** because it is the shortest path from infrastructure readiness to a live-meaningful BTST parameter upgrade.

## Recommended Approach

### Stage 1: Narrow coarse search for `ignition_breakout`

Start with a small, high-leverage subset of committee and fragile-breakout parameters.

This stage should answer only one question:

> Is there a clearly better `ignition_breakout` committee surface than the current one, under live-like T+1 and source-quality constraints?

It should not try to discover the final best profile in one pass.

### Stage 2: Baseline-aware candidate scoring

Each candidate should be evaluated against:

1. the current `ignition_breakout`,
2. the `default` BTST baseline.

The candidate ranking should privilege:

1. improved T+1 win rate,
2. improved or preserved T+1 payoff / expectancy,
3. no meaningful deterioration on downside guardrails,
4. acceptable source coverage.

### Stage 3: Promotion-ready shortlist

The workflow should end with a short list of candidates and a promotion verdict:

1. **promotable**
2. **promising but coverage-limited**
3. **score-only improvement, not promotable**
4. **keep current ignition_breakout**

## Architecture

The work should stay inside the current optimizer and replay stack:

1. `scripts/optimize_profile.py` — staged routed search entry point
2. `src/backtesting/param_search.py` — candidate ranking and guardrail-aware evaluation plumbing
3. `scripts/btst_profile_replay_utils.py` — replay metrics and source coverage inputs already exposed
4. `scripts/analyze_btst_multi_window_profile_validation.py` — baseline-vs-candidate comparison surface

No new standalone calibration framework is needed. The right move is to harden the existing optimizer into a staged routed-profile workflow.

## Data Flow

The intended path is:

`ignition_breakout staged grid -> replay evaluation -> baseline/default deltas -> source coverage guardrail check -> shortlist -> promotion verdict`

Required invariants:

1. every candidate must be compared on the same replay windows,
2. T+1 protection must outrank generic optimizer score,
3. source coverage must be part of candidate acceptance, not a post-hoc note.

## Metrics That Matter

### Primary

1. `next_close_positive_rate`
2. `next_close_payoff_ratio`
3. `next_close_expectancy`

### Secondary

1. `next_close_return_p10`
2. `next_high_hit_rate_at_threshold`
3. `closed_cycle_count`

### Promotion safety

1. source coverage mix for `flow_60_source`
2. source coverage mix for `persist_120_source`
3. source coverage mix for `close_support_30_source`
4. committee component source distribution

## Error Handling and Safe Defaults

1. If the staged search lacks enough replay windows, the result should be “insufficient evidence,” not a winner.
2. If a candidate beats baseline score but loses on protected T+1 metrics, it should be rejected explicitly.
3. If source coverage is too proxy-heavy, the candidate can be surfaced as “coverage-limited,” but not “promotable.”
4. If no candidate clears the guardrails, keep the current `ignition_breakout` settings.

## Validation Strategy

### 1. Optimizer entry-point validation

Add regression tests proving the staged ignition mode builds the intended narrow grid and routes through the existing evaluator stack.

### 2. Guardrail ranking validation

Add tests proving that a candidate with better raw score but worse protected T+1 metrics or weak source coverage is not ranked as promotable.

### 3. Output contract validation

Add tests proving the staged workflow emits a shortlist / verdict surface that can later be used to decide whether `src/targets/short_trade_target_profile_data.py` should change.

## Success Criteria

This cycle is successful if:

1. `ignition_breakout` gains a staged calibration workflow,
2. candidate ranking is explicitly baseline-aware,
3. source coverage participates in promotion gating,
4. the cycle ends with a credible shortlist or a defensible “keep current settings” verdict.

## Failure Criteria

This cycle should be considered unsuccessful if:

1. the optimizer still behaves like an unconstrained broad sweep,
2. the winner can be selected without checking T+1 protection against baseline,
3. source coverage remains visible but non-binding,
4. the workflow still cannot separate “score-only better” from “rollout-ready better.”

## Expected Implementation Surfaces

1. `scripts/optimize_profile.py`
2. `src/backtesting/param_search.py`
3. `tests/test_optimize_profile_script.py`
4. `tests/backtesting/test_param_search.py`
5. replay/report helpers only if the staged workflow needs one more structured output field

## Assumptions

Because the user was unavailable during brainstorming, this spec assumes approval for the following execution order:

1. build staged ignition calibration mode,
2. harden baseline-aware ranking and source guardrails,
3. only then decide whether any `ignition_breakout` profile constants should change.
