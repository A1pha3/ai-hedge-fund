# Momentum Rollout Recheck Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Run a governed rollout recheck for `trial_index=602` against the current active runtime, while keeping `release_posture=hold` until substantial historical validation proves both win-rate and payoff improvement

## 1. Problem statement

The rerun-rollout cycle converted the generic retune outcome into a concrete governed recommendation:

1. `winner.trial_index = 602`
2. `challenger_count = 3`
3. `action = advance_rollout_recheck`
4. `release_posture = hold`
5. guardrails remain `no_manifest_publication` and `no_btst_skill_promotion`

This changes the next BTST question again. The highest-value next step is no longer to keep polishing the rerun packaging layer, and it is not to reopen broad factor search. The current evidence chain already says the winner deserves a real rollout recheck. The unresolved question is:

> Does `trial_index=602` deliver enough historical win-rate and payoff improvement versus the current active runtime to justify moving from governed hold toward a release-ready decision?

The retrospective makes the priority clear. It says the strongest work has come from structural runtime governance and historically validated profile improvements, while broad search without activation evidence tends to create noise. It also says Round 89 style directional fixes matter, but they still need runtime-grade validation before promotion.

## 2. Goal and non-goals

### Goal

Design a governed rollout recheck cycle that:

1. evaluates `trial_index=602` against the current active runtime over substantial historical windows
2. uses challengers `1226`, `74`, and `361` only as comparison context, not as reopened search candidates
3. measures both **win rate** and **payoff** as first-class promotion criteria
4. preserves release governance until the recheck proves the winner is strong enough for later promotion

### Non-goals

- Do not reopen broad parameter search.
- Do not publish a manifest in this cycle.
- Do not update `ai-hedge-fund-btst` in this cycle.
- Do not write a `docs/prompt/generate_file/` promotion note in this cycle.
- Do not treat rerun success as equivalent to rollout success.

## 3. Approaches considered

### Approach A - immediate rollout recheck on winner only

Run the historical recheck only for `trial_index=602` versus the current runtime.

**Pros**

- smallest execution scope
- fastest route to a pass/fail answer
- minimizes distraction from the governed winner

**Cons**

- loses challenger context if the winner degrades
- makes it harder to tell whether weakness is candidate-specific or local-family-wide

### Approach B - winner-versus-runtime recheck with challenger context (**recommended**)

Run the historical recheck for `trial_index=602` versus the current active runtime, while carrying the 3 challengers as secondary comparison context.

**Pros**

- stays aligned with the current `advance_rollout_recheck` recommendation
- preserves local-family context without reopening search
- gives Gamma a stronger governance basis for deciding whether 602 is truly release-worthy
- best matches the retrospective lesson that validated runtime changes matter more than abstract offline wins

**Cons**

- requires more artifact plumbing than winner-only evaluation
- may still end in retained `hold`

### Approach C - divert to a fresh trend-activation or threshold-search cycle first

Pause the 602 rollout recheck and instead reopen a new factor or threshold optimization cycle.

**Pros**

- could expose another alpha path
- may find a cleaner candidate if 602 is mediocre

**Cons**

- ignores the current governed recommendation chain
- risks search creep before the active winner has been properly validated
- delays the shortest path to a release/no-release decision

## 4. Recommended design

The next cycle should be a **governed rollout recheck centered on winner 602**:

1. **primary candidate:** `trial_index=602`
2. **baseline:** the current active runtime profile used in production-facing BTST generation
3. **secondary context:** challengers `1226`, `74`, and `361`
4. **release posture:** remain `hold`
5. **promotion posture:** no manifest publication, no BTST skill promotion, no Chinese promotion note

The recheck should produce a historically grounded answer to one narrow question: whether the winner meaningfully improves BTST trading quality versus the active runtime without creating unacceptable stability, risk, or observability regressions.

## 5. Design boundaries

This cycle stays narrow in five ways:

1. it starts from the governed winner instead of the full search surface
2. it compares first against the active runtime, not against an expanding candidate pool
3. challengers are context only and cannot replace the winner unless a later governed decision says so
4. it measures promotion readiness through explicit win-rate / payoff / guardrail evidence
5. it ends in a governed rollout decision, not in a release action

## 6. Proposed component design

### 6.1 Rollout recheck input artifact

Build a compact input artifact that freezes:

1. winner `602`
2. current active runtime baseline
3. challenger context set
4. evaluation windows and backtest scope
5. guardrails and pass/fail thresholds

This artifact should prevent the recheck from silently drifting into a different comparison set or evaluation horizon.

### 6.2 Historical comparison artifact

Run substantial historical backtests that compare:

1. `602` versus active runtime
2. `602` versus challengers on the same windows
3. T+1, T+2, and T+3 outcome behavior
4. win rate, payoff, expectancy, drawdown, liquidity/capacity, and stability metrics

The comparison must be paired and window-aware. A single pooled uplift number is not enough for promotion.

### 6.3 Governance synthesis artifact

Collapse the recheck into one governed outcome:

1. **retain_hold**
   - if win rate or payoff does not improve enough
   - if downside, drawdown, drift, or stability regress materially
2. **ready_for_release_review**
   - if 602 beats active runtime on both win rate and payoff and stays inside governance bounds
3. **fallback_measurement_repair**
   - if observability gaps still prevent trustworthy comparison

`release_posture` should remain `hold` unless a later review explicitly promotes the outcome.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- defining the recheck label and pass/fail rubric
- interpreting whether uplift is statistically and economically meaningful
- documenting the factor and profile rationale if the result later clears promotion

### Beta

Beta owns:

- wiring the backtest and comparison pipeline
- preserving execution realism, costs, and artifact reproducibility
- ensuring challenger context does not silently become a new search cycle

### Gamma

Gamma owns:

- the rollout governance decision
- risk-budget and market-gate interpretation
- deciding whether evidence is strong enough to move from hold toward release review

## 8. Data flow

The recheck should flow in this order:

1. read the governed rerun recommendation and winner/challenger pack
2. resolve the current active runtime baseline
3. build a frozen rollout recheck input artifact
4. run paired historical comparisons across substantial windows
5. synthesize the result into one governed decision artifact

## 9. Error handling and fail-closed rules

The recheck must fail closed when:

1. the active baseline cannot be resolved
2. the winner or challenger payload is malformed
3. required windows or metrics are missing
4. win-rate and payoff comparisons cannot be computed consistently
5. observability gaps block trustworthy governance

No fallback should silently assume success-shaped results.

## 10. Validation design

Validation for this cycle should prove all of the following:

1. the active runtime baseline used in the recheck is explicit and reproducible
2. the recheck computes paired winner-versus-baseline results over substantial historical windows
3. the governance artifact can distinguish:
   - uplift strong enough for later release review
   - insufficient uplift that must retain hold
   - missing evidence that must trigger measurement repair
4. challenger context remains secondary and governed

The success ladder is:

1. prove the recheck is using the intended winner and baseline
2. prove the uplift is real on both win rate and payoff
3. prove the uplift is not bought by unacceptable risk or instability
4. earn the right to a later release-review cycle

## 11. Promotion rules

Promotion remains intentionally strict:

1. no profile or factor improvement is promoted into `ai-hedge-fund-btst` without substantial historical validation
2. promotion requires evidence of both **win-rate improvement** and **payoff improvement**
3. promotion also requires acceptable downside, drawdown, liquidity, and stability behavior
4. only after a governed release-ready outcome may we:
   - update the BTST runtime/manifest
   - add the improvement into `ai-hedge-fund-btst`
   - write a dated Chinese note under `docs/prompt/generate_file/`

## 12. Expected artifacts

If implementation is approved later, this design should produce:

1. a rollout recheck input artifact
2. a paired historical comparison artifact
3. a governed rollout decision artifact
4. no runtime promotion artifacts unless a later release-review stage clears them
