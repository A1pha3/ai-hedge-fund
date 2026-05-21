# Trend Continuation Activation-Delta Governance Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Diagnose and govern the missing runtime activation delta for `trend_continuation_strength_v3`

## 1. Problem statement

The BTST 90-round retrospective still points to the Round 89 trend-continuation correction as the strongest unresolved structural alpha line:

1. `trend_corrected_v1` fixed a directionality mistake by stopping the reward of short-term reversal and introducing positive trend-continuation weights.
2. `trend_continuation_strength_v2` and `trend_continuation_strength_v3` were created to refine that line further.
3. The repository now already contains a dedicated rollout assessment for `trend_continuation_strength_v3`, but the result is still `hold`.

The key observation is that the current blocker is not “the candidate clearly underperformed the baseline.” The current blocker is that the candidate failed to create observable runtime activation delta across the validated windows:

1. `report_dir_count = 20`
2. `variant_supports_t1_count = 0`
3. `mixed_count = 20`
4. `positive_window_count = 0`
5. `non_halt_execution_eligible_count = 0`
6. `all_windows_zero_delta = true`
7. dominant zero-delta reason = `profile_variant_without_runtime_activation_delta`

That means the next highest-value task is not “promote the candidate anyway” and not “start an unrelated new factor family.” The highest-value task is to explain and repair why this candidate never produces activation delta under current runtime conditions.

## 2. Goal and non-goals

### Goal

Design a governed research cycle that answers one narrow question:

> Why does `trend_continuation_strength_v3` produce no runtime activation delta versus `trend_continuation_strength_v2`, and can we restore measurable, execution-eligible activation delta without degrading T+1 edge, payoff, downside, or rollout discipline?

### Non-goals

- Do not publish a new optimized manifest during this design phase.
- Do not mix this work with momentum-threshold revalidation.
- Do not introduce a broad new factor family before understanding the current activation gap.
- Do not weaken rollout standards just to create non-zero deltas.
- Do not update `ai-hedge-fund-btst` unless validation later clears the full governance gate.

## 3. Approaches considered

### Approach A — activation-delta diagnostics plus controlled calibration (**recommended**)

Keep the current trend-continuation candidate branch, but make the next cycle about explaining and fixing the zero-delta outcome. Add finer attribution for why windows stay unchanged, then run small, explainable calibrations around the existing `v3` shrink-gate settings.

**Pros**

- Directly attacks the current real blocker
- Keeps the work tightly scoped to the strongest unresolved alpha line
- Preserves evidence-first governance
- Makes later rollout decisions interpretable

**Cons**

- May conclude the candidate is structurally dormant
- Could end with a justified `hold` rather than a promotion

### Approach B — abandon the trend-continuation line and search for a new factor/tag family

Start a fresh offline factor cycle instead of debugging the current candidate branch.

**Pros**

- Potentially higher upside if a new factor family is discovered
- Avoids spending time on a dormant candidate

**Cons**

- Much farther from runtime impact
- Leaves the strongest unresolved structural correction unexplained
- Higher overfitting risk and longer validation cycle

### Approach C — shift focus to execution/cost/system optimization

Prioritize Beta/Gamma execution-quality improvements rather than alpha activation.

**Pros**

- Useful for production hygiene
- Can improve realized outcomes without changing score logic

**Cons**

- Less direct path to improving stock-selection win rate and payoff
- Does not answer whether the Round 89 correction can actually produce runtime uplift

## 4. Recommended design

The next cycle should target a single research surface:

- **candidate branch:** `trend_continuation_strength_v2 -> trend_continuation_strength_v3`
- **research objective:** explain and repair missing activation delta
- **release posture:** fail-closed until a later rollout artifact explicitly clears promotion

The design should treat the current `hold` result as useful evidence, not as a failure to work around. We are not trying to force a promotion. We are trying to produce a more informative answer than “all windows zero delta.”

## 5. Design boundaries

Only the `v3`-specific additive changes should be in scope first:

1. `watchlist_filter_diagnostics_selected_only_shrink_enabled=True`
2. `watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift=0.05`
3. `watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max=0.10`
4. `watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max=0.40`
5. `watchlist_filter_diagnostics_selected_only_shrink_close_strength_max=0.58`

Everything else should remain anchored to `trend_continuation_strength_v2` unless later evidence proves a second change is needed. This keeps attribution clean and avoids turning the task into a broad profile rewrite.

## 6. Proposed component design

### 6.1 Activation-delta attribution layer

The current rollout helper only summarizes:

- whether execution-eligible deltas were positive
- whether all windows had zero delta
- the dominant zero-delta reason

The next cycle should enrich this into a more actionable attribution surface. For each window, we should distinguish at least:

1. shrink gate never triggered
2. shrink gate triggered, but no selected/near-miss decision changed
3. decision changed only in non-execution-eligible buckets
4. decision changed, but guardrails neutralized the delta
5. candidate path remained dormant because the runtime state never reached the relevant watchlist-filter branch

The goal is to move from “zero delta” to “zero delta because of X,” where `X` can guide a specific calibration.

### 6.2 Controlled calibration layer

After attribution exists, the next cycle should run a small calibration grid around the existing `v3` shrink parameters. This must stay intentionally narrow:

1. start with threshold-lift sensitivity
2. then catalyst/trend/close max thresholds
3. avoid simultaneous large multi-parameter drift

Each calibration candidate should remain explainable as “a slightly looser or tighter version of the current shrink gate,” not a new profile family. The purpose is to test whether the current branch is too narrow to ever activate, not to search the whole universe.

### 6.3 Governance and rollout layer

The later rollout decision should still be driven by multi-window validation plus rollout assessment, but with stronger blockers:

1. no activation delta
2. activation delta only in non-execution-eligible rows
3. activation delta present, but no T+1 improvement
4. activation delta present, but payoff/downside regress

This makes Gamma’s rollout decision more diagnostic and less binary.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- zero-delta attribution taxonomy
- validation labels for “activation happened” vs “activation mattered”
- statistical robustness, drift, CI-width, and overfit checks
- final Chinese documentation when and only when validation passes

### Beta

Beta owns:

- analysis of whether activation deltas are execution-eligible
- microstructure and tradability implications of newly activated names
- code-path isolation and refactoring if implementation is approved
- ensuring the candidate does not merely create paper-only coverage inflation

### Gamma

Gamma owns:

- window selection and out-of-sample governance
- rollout blocker logic
- downside / drawdown / regime consistency review
- release decision and fail-closed publication posture

## 8. Validation design

Validation should run in this order:

1. baseline zero-delta attribution on the current `v2 -> v3` comparison
2. controlled calibration grid for the `v3` shrink gate
3. multi-window validation on the strongest calibration candidates
4. rollout assessment with explicit activation-delta blockers
5. release decision only if the candidate shows execution-eligible activation delta and preserves quality

The key success ladder is:

1. produce non-zero activation delta
2. produce execution-eligible activation delta
3. show T+1 and payoff are flat-to-up
4. show downside, drift, and rollout guardrails remain acceptable

If the cycle fails at any rung, the result remains research-only.

## 9. Artifact plan

If implementation is approved later, the cycle should produce:

1. an activation-delta diagnostics artifact for `v2 -> v3`
2. a controlled calibration artifact for the `v3` shrink parameters
3. refreshed multi-window validation artifacts
4. a refreshed rollout assessment artifact with richer blocker reasons
5. a dated Chinese note under `docs/prompt/generate_file/` only if the candidate is validated
6. a BTST skill update only if the candidate actually becomes a governed ready path

## 10. Promotion rules

The candidate may only move forward if all of the following are true:

1. activation delta becomes non-zero in a meaningful number of windows
2. activation delta is execution-eligible, not just cosmetic bucket movement
3. T+1 edge is flat-to-up versus `trend_continuation_strength_v2`
4. payoff is flat-to-up
5. downside, drawdown, drift, and regime blockers stay inside explicit tolerance
6. rollout assessment no longer reports hold-only blockers

If these conditions are not met, the correct result is still `hold`.

## 11. Error handling and rollback stance

- A zero-delta diagnosis is a valid research outcome.
- A calibrated candidate that activates but worsens payoff is rejected.
- A candidate that improves T+2 only without a T+1 upgrade is rejected.
- A candidate that changes counts but only in non-execution-eligible rows is rejected.
- No manifest or skill update should happen on “interesting but inconclusive” evidence.

## 12. Likely implementation surfaces

If the user approves implementation later, the likely surfaces are:

- `scripts/analyze_btst_multi_window_profile_validation.py`
- `scripts/btst_trend_continuation_rollout_helpers.py`
- a new activation-delta diagnostics helper / CLI under `scripts/`
- targeted tests around the attribution and calibration logic
- possibly `src/targets/short_trade_target_profile_data.py` only if a calibrated `v3` successor is justified
- `docs/prompt/generate_file/` and BTST skill content only after validation clears

## 13. Why this is the right next task

This design focuses on the strongest unresolved alpha branch that already has runtime profiles, tests, validation artifacts, and a concrete blocker. The missing piece is not “more ideas.” The missing piece is understanding why the candidate never activates in a way the runtime can feel. Solving that gives the team the highest-information next step toward improving BTST win rate and payoff without breaking the repository’s validation discipline.
