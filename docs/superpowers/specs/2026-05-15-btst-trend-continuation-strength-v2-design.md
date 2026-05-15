# BTST Trend Continuation Strength v2 Design

## Problem

The latest BTST cycle closed three important gaps, but it also clarified the next bottleneck:

1. Round 89's `trend_corrected_v1` direction fix still does not clear rollout gates.
2. `btst_admission_edge_recovery` shows no observable replay delta across current validation windows.
3. Strict-objective gating now blocks promotion when rejected names outperform the tradeable surface or false-negative evidence accumulates.

This means the next cycle should not focus on trade-count recovery or looser rollout rules. It should focus on discovering a **new T+1 quality factor family** that improves next-close win rate and payoff together while preserving downside.

## Goal

Design a narrow BTST factor experiment named `trend_continuation_strength_v2` that strengthens T+1 selection quality by combining:

1. trend continuation,
2. close-retention strength,
3. volume confirmation quality.

The deliverable of this cycle is **validated factor evidence**, not a default-profile promotion.

## Non-Goals

1. Do not widen the BTST formal surface primarily to recover trade count.
2. Do not modify admission-edge, risk-budget, or manifest publication logic in this cycle.
3. Do not let T+2 or T+3 improvements justify T+1 regression.
4. Do not update the BTST skill/runtime release narrative unless the new factor clears replay and rollout gates.

## Recommended Approach

Create a new factor family that keeps the Round 89 direction-correction thesis but adds stronger T+1 quality discrimination:

1. reward continuation only when close-retention evidence is supportive,
2. reward volume-confirmed continuation more than raw continuation alone,
3. penalize "high intraday energy but weak close-retention" names.

The recommended workflow is:

1. define the new interaction or conditional weights inside the existing BTST profile system,
2. evaluate on focused 20-day BTST backtests for fast iteration,
3. promote only candidates that survive multi-window replay and strict-objective gating.

## Architecture

This cycle stays inside the existing BTST target stack and does not add a new execution path.

### Runtime surfaces

1. `src/targets/profiles.py`
2. `src/targets/short_trade_target_profile_data.py`
3. relevant `src/targets/short_trade_target_*helpers.py` files that already compute score-target decisions

### Validation surfaces

1. `scripts/optimize_profile.py`
2. existing BTST replay / profile-validation scripts
3. strict-objective gate artifacts and rollout recommendation payloads

### Reporting surfaces

1. only after the candidate clears gates, update downstream BTST reporting / skill provenance
2. before clearance, artifacts may mention the candidate only as offline validation evidence

## Data Flow

The intended path is:

`base breakout + trend features -> trend_continuation_strength_v2 interaction/condition factors -> score_target + explainability payload -> 20d BTST validation -> multi-window replay validation -> strict-objective gate -> rollout decision`

The new factor family must remain visible in explainability so the offline verdict can be tied back to concrete signal behavior rather than opaque threshold drift.

## Validation Rules

### Primary metrics

The candidate only remains viable if the following rule holds:

1. among `next_close_positive_rate`, `next_close_payoff_ratio`, and `next_close_return_p10`, at least **two improve** and the third does **not regress**

### Secondary metrics

These may support interpretation but never override primary failure:

1. `next_high_hit_rate_at_threshold`
2. `t_plus_2_close_positive_rate`
3. `t_plus_2_close_return_median`

### Guardrails

The candidate fails immediately if any of the following dominate:

1. downside worsens materially,
2. strict-objective blockers increase,
3. false-negative evidence worsens,
4. replay windows remain unchanged or effectively zero-delta,
5. the factor behaves like a T+2 follow-through tradeoff instead of a T+1 improvement.

## Testing Strategy

The cycle should add or extend tests in this order:

1. factor / scoring unit tests for the new interaction logic,
2. target-decision tests covering selected / near-miss / rejected boundary changes,
3. focused 20-day BTST validation for fast iteration,
4. multi-window replay validation,
5. strict-objective / rollout integration checks.

## Failure Criteria

Stop the cycle and keep the current baseline if any of these outcomes occur:

1. trade count rises but T+1 payoff or downside gets worse,
2. only T+2/T+3 metrics improve,
3. replay evidence still shows no meaningful delta,
4. strict-objective blockers increase or new false-negative cases appear.

## Expected Deliverables

1. a new offline candidate profile or override set for `trend_continuation_strength_v2`
2. focused validation artifacts showing T+1 metric deltas
3. multi-window replay artifacts
4. rollout verdict artifacts showing whether the factor is promotable, hold, or rejected

## Decision Rule

If the candidate clears the primary T+1 metrics, survives replay, and does not worsen strict-objective evidence, it can proceed to rollout review. Otherwise, it remains offline and the next BTST cycle should refine the factor hypothesis rather than broaden release scope.
