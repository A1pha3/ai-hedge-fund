# Momentum Rerun Rollout Check Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Run a narrow rerun-rollout validation cycle centered on `trial_index=602`, while preserving the current `hold` release posture

## 1. Problem statement

The momentum stability retune cycle is now complete and no longer needs more local search before the next move. The verified decision artifact shows:

1. `action = rerun_rollout_check`
2. `release_posture = hold`
3. `dominant_family = cross_window_stability`
4. the current best local candidate is `trial_index = 602`
5. the local shortlist contains `192` governed candidates, but only one candidate currently clears both blocker counts at zero

This changes the question. The next cycle is no longer "can a local retune reduce the blocker family?" That question has already been answered well enough to earn a rerun-rollout check. The next cycle is:

> Can the current winner (`trial_index=602`) hold up under a narrow rollout recheck, with a small challenger set nearby, without relaxing release governance or reopening broad parameter search?

## 2. Goal and non-goals

### Goal

Design a narrow rerun-rollout validation cycle that:

1. treats `trial_index=602` as the primary candidate
2. includes only the closest governed challengers as a comparison cohort
3. rechecks rollout readiness under the existing `hold` / no-publication guardrails
4. produces one governed post-check recommendation

### Non-goals

- Do not reopen a broad retune search.
- Do not add new factor families or widen the search space beyond the existing shortlist neighborhood.
- Do not publish a manifest or update `ai-hedge-fund-btst` in this cycle.
- Do not downgrade observability governance just because the current best candidate has zero blocker counts in the shortlist stage.
- Do not treat "rerun rollout check" as automatic promotion.

## 3. Approaches considered

### Approach A — single-winner rerun only

Only rerun the rollout check for `trial_index=602`.

**Pros**

- narrowest possible scope
- cheapest verification path
- least room for overfitting-through-selection

**Cons**

- gives no nearby challenger context if the winner degrades during rollout
- makes it harder to tell whether failure is candidate-specific or family-wide

### Approach B — tight winner-plus-neighbors rerun (**recommended**)

Treat `trial_index=602` as the primary candidate, but carry a tiny challenger cohort drawn from the nearest shortlist neighbors with low blocker counts.

**Pros**

- keeps the cycle narrow while preserving context
- allows the rollout recheck to distinguish "winner degraded" from "whole local family degraded"
- stays aligned with the retrospective lesson that reliable gains come from runtime governance, not broadening search

**Cons**

- slightly more artifact plumbing than a single-candidate rerun
- still may end in retained `hold`

### Approach C — reopen broader local search before rerun

Expand the shortlist neighborhood again before doing the rerun rollout check.

**Pros**

- increases the chance of finding another candidate

**Cons**

- directly contradicts the current `rerun_rollout_check` recommendation
- reintroduces search creep after the retune cycle already delivered a governed winner
- weakens the meaning of the current decision artifact

## 4. Recommended design

The next cycle should be a **tight winner-plus-neighbors rerun-rollout check**:

1. **primary candidate:** `trial_index=602`
2. **challenger set:** only the nearest low-blocker neighbors from the completed shortlist
3. **release posture:** remain `hold`
4. **governance posture:** no manifest publication, no BTST skill promotion

The winner should stay fixed as the lead candidate unless the rerun cycle proves it degrades materially relative to its immediate challengers. This preserves the meaning of the completed retune pipeline: the local search already selected a governed winner; the next phase exists to validate that winner under rollout-like evidence, not to resume search.

## 5. Design boundaries

This cycle stays narrow in four ways:

1. it starts from the completed shortlist output instead of the full param-search surface
2. it treats `trial_index=602` as fixed primary input
3. it only carries a very small challenger cohort for context
4. it ends in a governed rerun recommendation, not in publication

## 6. Proposed component design

### 6.1 Rerun cohort artifact

Build a small artifact that extracts:

1. the winning candidate (`trial_index=602`)
2. the nearest governed challengers from the shortlist
3. each candidate's params, blocker counts, and distance from the winner

The challenger cohort should be intentionally tiny. A good default is:

1. require the same fixed zero-weight params
2. prefer challengers with the lowest blocker counts
3. cap the cohort to the winner plus at most 3 challengers

This keeps the rerun artifact reviewable and prevents the rerun phase from becoming a disguised second optimization pass.

### 6.2 Rollout recheck input pack

Build a second artifact that translates the cohort into a rollout-check-ready input pack:

1. primary winner metadata
2. challenger metadata
3. current triage / retune governance state
4. required guardrails
5. explicit fail-closed assumptions about observability gaps

This pack should make the next rollout recheck reproducible without forcing a future worker to reverse-engineer the shortlist output.

### 6.3 Governed rerun recommendation

The cycle should again collapse to one narrow next-step decision:

1. **advance_rollout_recheck**
   - if the winner remains stable and the challenger set does not reveal a more governance-safe alternative
2. **retain_hold**
   - if the winner degrades or the cohort shows the local family is still unstable
3. **fallback_measurement_repair**
   - if observability gaps become dominant again during rerun preparation

`release_posture` must stay `hold` in every outcome of this design cycle.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- challenger-cohort selection rules
- statistical interpretation of whether the winner still meaningfully dominates its nearest neighbors
- documentation of why the rerun cycle does or does not strengthen confidence

### Beta

Beta owns:

- cohort extraction and rerun input-pack wiring
- ensuring the artifact chain stays aligned with the real shortlist / decision shapes
- preserving narrow-scope execution rather than allowing a new search to creep in

### Gamma

Gamma owns:

- preserving the `hold` / no-publication boundary
- deciding whether the rerun pack earns the right to an actual rollout recheck
- forcing fallback to measurement repair if observability risk becomes dominant again

## 8. Validation design

Validation for this cycle should run in this order:

1. start from the completed shortlist and decision artifacts
2. extract the winner and nearest governed challengers
3. emit a rerun input pack with the current guardrails
4. summarize whether the winner still dominates the local cohort
5. emit a governed rerun recommendation

The success ladder is:

1. convert the generic `rerun_rollout_check` action into a concrete rerun cohort
2. prove whether `trial_index=602` still deserves to lead the next rollout check
3. reduce the next step to either a prepared rollout recheck or a justified retained `hold`

## 9. Artifact plan

If implementation is approved later, the cycle should produce:

1. a rerun cohort artifact
2. a rollout recheck input-pack artifact
3. a governed rerun recommendation artifact
4. no BTST skill update and no Chinese promotion note unless a later rollout cycle actually clears promotion

## 10. Promotion rules

Promotion remains unchanged:

1. no factor or runtime improvement is promoted into `ai-hedge-fund-btst` without substantial historical validation
2. no `docs/prompt/generate_file/` note is written unless a later rollout decision actually clears promotion
3. any future promotion still needs evidence for both win-rate improvement and payoff improvement
