# BTST Candidate-Pool Frontier Design

## Problem

`btst_admission_edge_recovery` has now been validated on refreshed replay artifacts that restore `market_state` from `daily_events`, and the result is still behaviorally inert.

Observed evidence from the current validation cycle:

- The original March multi-window verdict was invalid because historical `selection_artifacts` lacked top-level `market_state`.
- Rebuilding the 17-window validation set with `scripts/refresh_selection_artifacts_from_daily_events.py` restored top-level `market_state` for every refreshed trade date.
- After refresh, the fixed-profile replay verdict remained `mixed` across all 17 reports, with zero row-level diffs between `btst_precision_v2` and `btst_admission_edge_recovery`.
- The refreshed validation set still covered meaningful BTST regimes (`normal_trade=106`, `aggressive_trade=11`, `shadow_only=11`), so the flat result is not explained by a missing regime surface.
- Snapshot-level activation scans showed no `rank_threshold_tightening` payloads, no adaptive `p4_prior_shrinkage_policy`, and only a tiny handful of non-default entry modes.
- Additional April activation probes on candidate-pool-rank-heavy reports were also completely inert.

The implication is that the current admission-edge branch is not losing on an active frontier. It is mostly not reaching a live frontier at all. Continuing with weekly validation or bounded search around the same branch would likely spend time on a profile family that is not touching the current replay surface.

## Goal

Shift the next BTST optimization cycle away from admission-edge relief and toward a frontier that can actually expand the actionable BTST sample surface without degrading closed-cycle quality.

The next design target is:

**Increase candidate-pool recall for BTST-relevant boundary/shadow names, then use current target logic to re-score and filter that wider frontier.**

This keeps the work aligned with the main objective:

- raise next-day hit rate by surfacing more credible BTST candidates,
- improve payoff by preserving only those widened-frontier candidates that survive downstream quality gates,
- avoid overfitting a profile family that current replay evidence does not activate.

## Approaches Considered

### 1. Keep pushing admission-edge relief

Increase regime admission recovery magnitudes, relax prior shrinkage further, and search more aggressively around the same profile family.

**Pros**

- Smallest conceptual change from the current branch.
- Reuses the already-implemented profile knobs.

**Cons**

- Current replay evidence shows the branch is inert even on refreshed March windows and additional April boundary-heavy probes.
- There is no sign yet that the current replay surface contains enough rank-tightening or adaptive-prior cases for this to matter.
- More search here risks optimizing noise around a dead frontier.

**Recommendation:** not the next primary task.

### 2. Expand candidate-pool frontier before profile evaluation

Broaden which upstream shadow/boundary candidates are admitted into the BTST replay universe, then let the existing scoring, historical prior, and entry-mode logic do the filtering.

**Pros**

- Attacks the observed bottleneck directly: too little live frontier for current admission-edge logic to act on.
- Uses already visible high-signal areas in historical artifacts: `upstream_liquidity_corridor_shadow` and `post_gate_liquidity_competition_shadow`.
- More likely to create measurable deltas in replay than further tweaking a branch that is currently inert.

**Cons**

- Broader recall can easily hurt quality if the release criteria are too loose.
- Needs explicit guardrails so sample growth does not just add weak names.

**Recommendation:** **choose this approach.**

### 3. Pivot to payoff-only optimization

Leave admission and recall unchanged, and optimize only preferred entry mode / hold posture / T+1-T+2 payoff controls.

**Pros**

- Can improve expectancy even without increasing selected count.
- Lower risk of flooding the book with weak names.

**Cons**

- Does not solve the more immediate problem that many windows still have a narrow or inert frontier.
- Harder to improve win rate materially if the candidate set itself is still too constrained.

**Recommendation:** keep as a later follow-up, not the next frontier.

## Recommended Design

### 1. Scope

Introduce a **candidate-pool frontier expansion layer** for BTST validation and eventual runtime use. This layer should widen the set of candidates that enter short-trade target evaluation, but only for specific upstream families that already show repeated boundary/shadow behavior in historical artifacts.

Initial focus:

- `upstream_liquidity_corridor_shadow`
- `post_gate_liquidity_competition_shadow`

Out of scope for this cycle:

- generic all-source threshold loosening,
- changes to portfolio sizing or exit execution,
- new LLM-driven signals,
- changing the BTST regime-gate classifier itself.

### 2. Behavioral intent

Instead of asking the target profile to rescue a nearly empty frontier, widen the frontier one step earlier:

1. admit more qualified corridor/post-gate shadow candidates into replay,
2. preserve their upstream provenance and reason codes,
3. let the existing BTST target evaluator decide selected / near_miss / blocked using current quality logic,
4. compare whether the widened frontier improves actionable sample coverage without breaking next-close quality.

The design should bias toward **controlled recall**, not blanket permissiveness.

### 3. Frontier expansion rules

The expansion layer should be source-aware and gated.

For each supported source family, evaluate candidates against:

- candidate-pool rank proximity,
- minimum close strength,
- minimum trend acceleration,
- minimum liquidity share / amount-share support,
- optional catalyst freshness or sector resonance floors when the source historically needs them,
- explicit exclusion of structurally weak or obviously stale names.

The released candidates should remain labeled as expanded-frontier entries so downstream diagnostics can distinguish them from baseline candidates.

### 4. Data flow

1. Read frozen `selection_artifacts` / `daily_events` report inputs.
2. Reconstruct or refresh candidate artifacts when historical reports lack current context.
3. Build an expanded replay universe from the selected source families.
4. Re-run BTST target evaluation with the existing target profile.
5. Compare:
   - selected / near-miss counts,
   - next-day hit rate,
   - next-close positive rate,
   - T+2 median / expectancy,
   - downside proxies.

The comparison should always preserve source-level attribution so we can answer:

- which source family added the new candidates,
- whether those candidates improved or degraded surface quality,
- whether any source should be enabled, narrowed, or dropped.

### 5. Output and diagnostics

Every replay / validation artifact generated by this frontier should surface:

- released frontier candidate count by source family,
- selected / near-miss outcomes by source family,
- closed-cycle quality by source family,
- reason codes for released-but-rejected names,
- whether the widened frontier produced new actionable rows or only more noise.

The design should explicitly avoid a success-shaped metric that only tracks higher candidate counts.

### 6. Error handling

- If a report lacks `daily_events.jsonl`, fail that report explicitly rather than silently treating it as a valid no-op.
- If a source family lacks the fields needed for gating, report the missing fields in diagnostics.
- If refreshed artifacts still produce no widened frontier, surface that as an explicit “no frontier activation” result.

### 7. Testing strategy

Add targeted tests around:

1. source-aware frontier admission rules,
2. release gating for corridor and post-gate shadow families,
3. preservation of provenance / reason-code metadata,
4. replay diagnostics that attribute results by source family,
5. regressions ensuring weak structural names are still blocked after expansion.

Validation after implementation should prioritize:

- candidate-pool-rank-heavy reports,
- short-trade-only April reports with repeated shadow/boundary entries,
- refreshed reports with valid `market_state`.

## Why this design

The current evidence no longer supports spending the next cycle on validating or lightly tuning `btst_admission_edge_recovery`.

What the evidence does support is:

- historical artifacts contain many boundary/shadow candidates,
- those candidates cluster in specific upstream families,
- the current profile family is not interacting with the replay frontier strongly enough to produce deltas,
- widening the frontier earlier is the most plausible way to create a live surface where downstream BTST quality logic can matter again.

So the next step should be **frontier expansion with hard source-aware guardrails**, not more validation of a branch that is already flat.
