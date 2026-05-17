# BTST Win-Rate-First Medium-Route Design

## Problem

The latest BTST cycle closed the runtime-activation, reporting-provenance, and execution-evidence rollout gaps, but it still left the next optimization question open:

1. how to raise **selected / execution-eligible win rate** rather than merely improve offline diagnostics,
2. how to use the newly exposed execution-eligible and formal-block evidence to make runtime selection stricter where it matters,
3. how to decide whether `trend_continuation` / `trend_corrected_v1` should move closer to runtime without weakening rollout governance,
4. and how to ensure any validated improvement is documented in a form that can later feed `ai-hedge-fund-btst`.

The user has now set the primary objective for the next cycle:

> prioritize **win rate first**, while accepting only a modest tradeoff in payoff ratio and coverage.

This rules out both extremes:

1. a purely conservative cycle that only adds more blockers without re-testing profile evolution,
2. and an aggressive profile-promotion cycle that might improve upside but dilute hit rate or bypass the newly tightened governance chain.

## Current Evidence

### 1. Runtime governance is stronger, but still mostly observational

- Runtime activation attribution now exposes whether profile changes actually move `selected`, `near_miss`, `tradeable`, and `execution_eligible` surfaces.
- Reporting artifacts now explain when raw `selected` names are formally blocked, including the non-`halt` subset.
- Rollout promotion now blocks candidates that lack positive non-`halt` execution-eligible evidence.

These changes make the system safer, but they do not yet guarantee that runtime selection is stricter in a way that measurably improves win rate.

### 2. The retrospective still points at trend correction as the main structural candidate

- The retrospective identifies Round 89 style trend correction as a structural direction fix, not a minor threshold tweak.
- It also makes clear that not every offline factor improvement has reached runtime or manifest-backed BTST outputs.
- That makes `trend_continuation` / `trend_corrected_v1` the clearest candidate for the next win-rate-first runtime challenge, but only if replay and walk-forward evidence support it.

### 3. Win-rate-first work must respect the current skill-consumption boundary

- `ai-hedge-fund-btst` consumes manifest-backed runtime outputs, not speculative offline metrics.
- Therefore the next cycle must keep the sequence:

`validated runtime improvement -> manifest-ready evidence -> report/skill adoption`

and must not shortcut from promising offline uplift straight into skill-facing behavior.

## Goals

1. Increase BTST win rate by tightening runtime precision around execution-eligible and prior-quality evidence.
2. Re-test trend-corrected profile work with explicit win-rate-first acceptance criteria.
3. Keep payoff ratio and coverage degradation bounded rather than unconstrained.
4. Require validated improvements to be documented in `docs/prompt/generate_file/` with factor-or-feature plus date naming.
5. Preserve the rule that only manifest-backed, validated improvements may influence `ai-hedge-fund-btst`.

## Non-Goals

1. Do not bypass `halt` or other hard macro stop conditions.
2. Do not optimize for broader coverage if it weakens BTST hit rate.
3. Do not push `trend_corrected_v1` into runtime or manifest publication without replay and walk-forward support.
4. Do not document speculative factors as if they were already approved runtime improvements.

## Alternatives Considered

### 1. Conservative precision-only tightening

Tighten execution-eligible, prior-quality, and non-`halt` recovery rules without re-opening profile evolution.

**Rejected** because it likely improves safety and maybe precision, but it leaves the main structural factor candidate (`trend_continuation`) offline and misses a high-value chance to raise win rate more materially.

### 2. Win-rate-first medium route **(recommended)**

Combine two linked efforts:

1. tighten runtime precision using the new governance signals,
2. re-test trend-corrected profile promotion under stricter win-rate-first gates.

**Recommended** because it balances near-term precision gains with the highest-leverage structural candidate, while still respecting rollout safety and modest downside tolerance.

### 3. Aggressive narrow-book route

Sharply raise selection thresholds and shrink rank caps to force a much smaller BTST opportunity set.

**Deferred** because it may raise hit rate, but it risks excessive coverage collapse and can hide whether the real uplift came from better factor structure or just from taking far fewer shots.

## Recommended Approach

### Task A: Turn execution evidence into stricter runtime precision

Use the newly exposed runtime signals to make the selected lane more selective for win-rate purposes.

This task should focus on:

1. execution-eligible evidence,
2. historical prior-quality enforcement,
3. non-`halt` formal-block recovery semantics,
4. and any rank / relief interaction that currently lets borderline names stay in the main lane.

The intent is not to block more names by default. It is to separate:

1. names that still deserve main selected status under a win-rate-first objective,
2. names that should move down to near-miss / watchlist / offline analysis,
3. names that should remain formally blocked even if they look interesting upstream.

### Task B: Re-validate `trend_continuation` / `trend_corrected_v1` for win-rate-first promotion

Run the current trend-corrected candidate through replay, compare, and walk-forward views with explicit win-rate-first criteria:

1. selected or execution-eligible win rate must improve,
2. payoff ratio may soften only modestly,
3. rollout governance must remain promotable,
4. no new structural blocker may appear.

This task should answer a concrete release question:

> Is the trend-corrected profile good enough to replace or augment the current active BTST profile under a win-rate-first objective?

If not, the candidate remains offline and the cycle records why.

### Task C: Close the evidence-to-documentation-to-skill loop

When Task A or Task B produces a validated improvement, write a Chinese factor/feature document to:

`docs/prompt/generate_file/<factor-or-feature>-YYYY-MM-DD.md`

Each document must include:

1. the factor or governance feature principle,
2. what changed and why it should improve win rate,
3. what replay / backtest / walk-forward evidence validated it,
4. what tradeoffs were observed,
5. and how the BTST pipeline or skill should use it.

This documentation is required before the validated improvement is considered ready for broader BTST report consumption.

## Architecture

The work stays inside the existing BTST stack:

1. **Runtime decision layer**  
   `src/targets/short_trade_target_*helpers.py`, `src/targets/router_build_helpers.py`, related reporting summaries
2. **Profile and scoring layer**  
   `src/targets/profiles.py`, `src/targets/short_trade_target_profile_data.py`, score payload builders
3. **Validation and promotion layer**  
   `scripts/btst_admission_replay_validator.py`, `scripts/btst_strict_objective_gate.py`, `scripts/optimize_profile.py`, compare and walk-forward tooling
4. **Documentation and skill-consumption layer**  
   `docs/prompt/generate_file/`, manifest-backed BTST reporting, and only then `ai-hedge-fund-btst`

## Data Flow

The intended sequence is:

`precision tightening and/or trend-corrected candidate -> replay / walk-forward validation -> execution-eligible and win-rate evidence -> strict rollout gate -> manifest-ready decision -> factor/feature documentation -> ai-hedge-fund-btst consumption`

Required invariants:

1. win-rate improvement must be measured on runtime-relevant surfaces, not only offline metrics,
2. hard stops remain hard stops,
3. modest payoff/coverage degradation is acceptable only if win-rate uplift is clear and governance remains stable,
4. documentation follows validated changes, not speculative ideas.

## Error Handling and Safe Defaults

1. If precision tightening reduces coverage but does not improve win rate, revert the change and keep it offline.
2. If `trend_corrected_v1` improves offline metrics but fails win-rate-first replay or walk-forward evidence, keep the current active profile.
3. If a candidate only works by bypassing formal hard-stop logic, reject it.
4. If documentation has not been written for a validated factor or feature, it is not considered ready for downstream BTST skill adoption.

## Validation Strategy

### 1. Task A validation

Use red/green tests plus replay-oriented regressions to prove that precision tightening changes actual runtime routing and improves win-rate-relevant evidence rather than just changing labels.

### 2. Task B validation

Use compare, replay, and walk-forward surfaces to evaluate whether trend correction improves win rate with acceptable tradeoffs in payoff and coverage.

### 3. Task C validation

Verify that every promoted factor or governance feature has:

1. a concrete validation record,
2. a dated documentation artifact in `docs/prompt/generate_file/`,
3. and a clear path for later skill consumption.

### 4. Regression slice

Run the focused BTST tests around:

1. optimize-profile rollout logic,
2. replay validation,
3. profile comparison and walk-forward,
4. runtime reporting and target summaries,
5. and any new doc-generation or skill-facing glue added by the cycle.

## Success Criteria

This cycle succeeds only if all of the following hold:

1. runtime precision tightening measurably improves win-rate-relevant evidence,
2. trend-corrected profile validation clearly answers whether it is promotable under a win-rate-first objective,
3. any payoff/coverage degradation stays within the accepted modest range,
4. validated improvements are documented in `docs/prompt/generate_file/`,
5. and only then can the change be considered for manifest-backed BTST reporting and future `ai-hedge-fund-btst` use.

## Failure Criteria

Stop and keep the current approved baseline if any of the following remain true:

1. win-rate uplift appears only in offline metrics and not in runtime-relevant evidence,
2. precision tightening improves optics but does not improve actual selected / execution-eligible outcomes,
3. trend-corrected validation needs materially worse payoff or coverage to look good,
4. governance remains unstable or produces new rollout blockers,
5. or the validated-change documentation loop is incomplete.
