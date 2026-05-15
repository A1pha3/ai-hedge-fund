# BTST Watchlist Filter Diagnostics Selected-Only Shrink Design

## Problem

The latest `trend_continuation_strength_v2` replay pass exposed a repeatable structure-drift pattern:

1. the changed windows are driven mainly by `watchlist_filter_diagnostics`,
2. the dominant shift is `selected -> near_miss / rejected`, not broad source-family expansion,
3. the current repo only has `watchlist_filter_diagnostics_flat_trend_penalty`, which is a score penalty and cannot express a source-specific **selected-only** shrink.

This means the next BTST refinement should not start by tightening all watchlist-diagnostics names equally. It should introduce a narrower source-specific rule that shrinks unstable `selected` exposure while preserving `near_miss` observation.

## Goal

Design a narrow offline BTST variant that:

1. reduces unstable `selected` promotions from `watchlist_filter_diagnostics`,
2. preserves `near_miss` visibility for later validation,
3. improves T+1 quality without widening rollout scope.

The deliverable of this cycle is a validated offline candidate, not a rollout change.

## Non-Goals

1. Do not change `layer_c_watchlist` or `short_trade_boundary` behavior in this cycle.
2. Do not redesign the global promotion guardrail in this cycle.
3. Do not suppress all `watchlist_filter_diagnostics` names equally.
4. Do not update `ai-hedge-fund-btst` unless the resulting candidate later clears replay and rollout gates.

## Recommended Approach

Introduce a new source-specific **selected-only gate** for `watchlist_filter_diagnostics`.

The recommended behavior is:

1. if a row comes from `watchlist_filter_diagnostics` and matches a weak-continuation / weak-catalyst / weak-close-retention signature, it may no longer enter `selected`,
2. the same row may still remain `near_miss` if its broader surface is worth monitoring,
3. existing flat-trend penalty logic remains explainable, but no longer carries the full burden of controlling this source.

This is preferable to simply increasing the current flat-trend penalty because score-only penalties do not reliably enforce the structural outcome we want.

## Alternative Approaches Considered

### 1. Increase the existing flat-trend penalty only

Pros:

1. smallest code change,
2. reuses existing profile fields and explainability.

Cons:

1. still indirect,
2. does not guarantee selected-only shrink,
3. more likely to over-penalize rows that should stay visible as `near_miss`.

### 2. Add a selected-only source gate for `watchlist_filter_diagnostics` **(recommended)**

Pros:

1. directly targets the observed drift pattern,
2. preserves offline observation surface,
3. keeps the change local to one source family.

Cons:

1. introduces a new source-specific gate path,
2. needs careful replay validation to avoid hidden overfitting.

### 3. Add dual selected + near-miss gates for this source

Pros:

1. strongest structural control.

Cons:

1. highest overfit risk,
2. removes evidence too early,
3. too aggressive for the current replay signal.

## Architecture

This cycle should stay inside the BTST short-trade target stack.

### Runtime surfaces

1. `src/targets/profiles.py`
2. `src/targets/short_trade_target_profile_data.py`
3. `src/targets/short_trade_target_watchlist_helpers.py`
4. `src/targets/short_trade_target_snapshot_relief_helpers.py`
5. any existing evaluation / payload helpers needed to expose the new gate reason

### Validation surfaces

1. `tests/targets/` for source-specific selected / near-miss behavior
2. focused 20-day validation artifacts
3. multi-window replay validation
4. strict-objective gate artifacts

## Data Flow

The intended path is:

`watchlist_filter_diagnostics row -> selected-only source gate -> score / decision / explainability payload -> 20d validation -> multi-window replay -> strict-objective gate -> rollout decision`

The gate must remain explicit in explainability so we can distinguish:

1. score penalties,
2. selected-only structural downgrades,
3. ordinary threshold misses.

## Validation Rules

### Primary rule

The new variant remains viable only if:

1. `watchlist_filter_diagnostics` selected exposure shrinks in the problematic windows,
2. `near_miss` visibility is preserved rather than broadly deleted,
3. T+1 metrics improve on the tradeable surface.

### Guardrails

Fail the cycle immediately if:

1. the rule simply migrates rows from `selected` to `rejected`,
2. `near_miss` collapses instead of staying observable,
3. trade count shrink is achieved but T+1 quality does not improve,
4. the candidate still behaves like a T+2 tradeoff.

## Testing Strategy

Add or extend tests in this order:

1. source-specific unit tests proving `watchlist_filter_diagnostics` rows can be blocked from `selected` while still surviving as `near_miss`,
2. target-decision tests for explainability / payload exposure,
3. focused replay-window regression tests on the windows that previously changed,
4. 20-day BTST validation,
5. multi-window replay and strict-objective checks.

## Expected Deliverables

1. an offline candidate profile implementing `watchlist_filter_diagnostics` selected-only shrink
2. replay evidence showing reduced problematic selected drift
3. updated validation artifacts proving whether T+1 quality improves
4. a clear hold/promote verdict for the candidate

## Decision Rule

If the selected-only shrink reduces the unstable `watchlist_filter_diagnostics` selected surface, preserves meaningful `near_miss` evidence, and improves T+1 quality without worsening strict-objective evidence, it can proceed to rollout review. Otherwise, it remains offline and the next BTST cycle should refine the source gate rather than widen release scope.
