# Momentum Rollout Blocker Triage Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Triage the rollout blockers on the existing `momentum_optimized -> momentum_tuned` line before starting a new factor family

## 1. Problem statement

The trend-continuation activation-delta line was the highest-priority unresolved branch from the Round 89 correction, but the refreshed diagnostics, calibration, and rollout artifacts now show a clean `hold` conclusion:

1. `all_windows_zero_delta = true`
2. `execution_eligible_positive_window_count = 0`
3. no qualifying calibration best candidate
4. rollout blockers remain dominated by missing runtime activation

That means the next highest-value task is no longer “keep pushing the same dormant branch.” The next task is to return to the strongest line that already showed local uplift and determine why it still cannot clear rollout governance.

The current `btst_latest_optimized_profile.md` evidence points to the momentum / optimized-profile branch as that line:

1. retrospective evidence still calls out local uplift on the momentum-tuned family
2. the optimized-profile search already found a best candidate
3. publication was skipped because rollout stayed `hold`
4. the blocker set mixes missing observability, cross-window instability, and true downside/risk regressions

So the next design should not be a broad new factor search. It should be a blocker-focused triage cycle for the existing momentum line.

## 2. Goal and non-goals

### Goal

Design a governed research cycle that answers one narrow question:

> Is the `momentum_optimized -> momentum_tuned` line blocked mainly by missing measurement / attribution surfaces, or by real stability and downside regressions that should keep it out of production?

### Non-goals

- Do not create a new BTST factor family in this cycle.
- Do not directly publish a new optimized manifest in the design phase.
- Do not weaken rollout thresholds just to force a promotion.
- Do not update `skills/ai-hedge-fund-btst` or `docs/prompt/generate_file/` unless a later rollout artifact explicitly clears promotion.
- Do not merge this work with the trend-continuation activation-delta branch; that branch should remain a separate governed `hold`.

## 3. Approaches considered

### Approach A — blocker-focused momentum rollout triage (**recommended**)

Treat the momentum line as the best next release candidate and build a narrow triage surface around its current rollout blockers.

**Pros**

- stays on a branch that already has local uplift evidence
- attacks a concrete release blocker instead of inventing a new search space
- keeps the work tightly coupled to publication discipline
- can end in either a justified `hold` or a much narrower next implementation task

**Cons**

- may conclude the momentum line is not releaseable
- may produce a measurement / governance cleanup rather than an immediate win-rate uplift

### Approach B — retune the momentum profile immediately

Jump straight into threshold / rank-cap / relief retuning on the momentum line.

**Pros**

- potentially faster path to a better candidate
- stays on a promising existing profile family

**Cons**

- risks tuning against an unclear blocker set
- can hide whether the current failure is observability versus real regression
- higher overfitting risk

### Approach C — move to a brand-new factor family

Leave the current release candidates behind and start a fresh alpha search.

**Pros**

- could discover a larger upside path
- avoids spending more time on blocked candidates

**Cons**

- weakest governance efficiency
- ignores existing local uplift evidence
- expands the search surface before the current best candidate family is fully understood

## 4. Recommended design

The next cycle should focus on a single governed surface:

- **candidate branch:** `momentum_optimized -> momentum_tuned`
- **research objective:** separate missing observability from true rollout regressions
- **release posture:** fail-closed until a later rollout artifact explicitly clears promotion

This design assumes the current `hold` is valuable evidence. The point is not to rescue the candidate at all costs. The point is to turn a wide blocker list into a prioritized, explainable answer:

1. which blockers are measurement holes
2. which blockers are driven by a small number of windows
3. which blockers represent true downside / stability regressions
4. which blocker family is most worth attacking next

## 5. Design boundaries

This cycle should stay narrow:

1. it should only analyze the existing momentum / optimized-profile line
2. it should work from current rollout artifacts and window-level evidence
3. it may add attribution or triage artifacts
4. it may recommend a later retuning task, but should not combine triage and retuning into one implementation cycle

That keeps attribution clean and prevents the cycle from turning into another wide profile search.

## 6. Proposed component design

### 6.1 Rollout blocker dossier

Add a first-class dossier artifact for the optimized-profile rollout blockers.

Its job is to group the current blockers into three families:

1. **missing observability**
   - examples: `missing_projected_theme_exposure_delta_*`, `missing_incremental_theme_exposure_delta_*`
2. **cross-window stability / robustness regressions**
   - examples: `win_rate_window_trend`, `win_rate_window_volatility`, `win_rate_ci_width`, `win_rate_cv`, `param_drift_score`, `factor_drift_score`, `gate_above_threshold_cv`
3. **true risk / payoff regressions**
   - examples: `downside_p10`, `liquidity_capacity_raw_100`, `max_drawdown_simulated`, `t_plus_3_close_payoff_ratio`

The dossier should answer:

1. how many blockers fall into each family
2. which family dominates the current `hold`
3. which blockers appear to be missing data rather than negative data

### 6.2 Window-level attribution layer

Add a targeted replay / attribution artifact for the momentum line.

Its job is to connect the top-level blocker names to actual window behavior:

1. which windows drive `win_rate_window_trend` regression
2. whether the momentum line is failing broadly or only in a few windows
3. whether the missing theme-exposure deltas come from absent metrics, empty payloads, or non-comparable report shapes
4. whether downside and liquidity regressions co-occur with the same windows or appear independently

This layer should make it possible to say “the line is blocked because of X windows and Y missing metrics,” not just “the rollout report listed 20+ blockers.”

### 6.3 Governed next-action surface

The final output of this cycle should not be a new manifest. It should be a governed recommendation of one of three next actions:

1. **measurement fix next**
   - if the dominant blockers are missing observability
2. **parameter / runtime retune next**
   - if the dominant blockers are localized regressions that look plausibly recoverable
3. **retain hold**
   - if the dominant blockers are broad downside / robustness failures

That gives Alpha, Beta, and Gamma a single next move without mixing diagnosis and remediation.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- blocker taxonomy
- the distinction between missing evidence and negative evidence
- statistical interpretation of window-level regressions
- final Chinese documentation if and only if a later cycle validates promotion

### Beta

Beta owns:

- replay and attribution wiring
- execution / liquidity interpretation for the momentum blockers
- diagnosis of whether missing theme-exposure deltas are instrumentation gaps or real runtime omissions

### Gamma

Gamma owns:

- the hold / go decision boundary
- prioritization of blocker families
- determination of whether a later retuning task is warranted
- fail-closed release posture

## 8. Validation design

Validation should run in this order:

1. refresh or read the current optimized-profile rollout artifact
2. build a blocker dossier that groups and counts blocker families
3. build a window-level attribution artifact for the dominant blockers
4. classify the line into one of the three governed next-action outcomes
5. only if the outcome supports it, open a later implementation cycle for measurement repair or targeted retuning

The success ladder is:

1. replace a wide undifferentiated blocker list with a prioritized blocker family view
2. identify whether the dominant blockers are missing observability or true regressions
3. reduce the next engineering step to one narrow follow-up task

If the cycle cannot do that, it is still a valid research failure and should remain `hold`.

## 9. Artifact plan

If implementation is approved later, the cycle should produce:

1. a momentum rollout blocker dossier artifact
2. a momentum window-attribution artifact
3. a governed triage recommendation artifact
4. no BTST skill update and no Chinese validation note unless a later release cycle actually promotes

## 10. Promotion rules

This triage cycle itself does **not** promote a profile.

A later cycle may only promote if:

1. the missing-observability blockers are either repaired or proven irrelevant
2. the remaining blocker set no longer shows unacceptable downside / liquidity / drawdown regressions
3. cross-window stability metrics stop regressing materially
4. a refreshed rollout artifact switches from `hold` to `promote`

If these conditions are not met, the correct result remains `hold`.

## 11. Error handling and rollback stance

- Missing metrics are not treated as success.
- Mixed blocker families are not collapsed into a forced “retune next.”
- If the dossier cannot separate observability holes from real regressions, the result is still `hold`.
- No manifest, skill, or doc promotion should happen on partial or ambiguous evidence.

## 12. Likely implementation surfaces

If the user approves implementation later, the likely surfaces are:

- `scripts/` artifacts around optimized-profile rollout triage
- current optimized-profile / rollout reports under `data/reports/`
- targeted tests for blocker grouping, attribution, and fail-closed recommendation logic

## 13. Why this is the right next task

The trend-continuation line now has a clean explanation for why it is blocked: no runtime activation delta. The momentum line is more valuable because it still has local uplift evidence but lacks a clean explanation for why publication remains blocked. That makes momentum rollout triage the highest-information next step toward improving BTST win rate and payoff without abandoning governance discipline.
