# Momentum Threshold Governance Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Governed re-validation of `momentum_tuned`-style threshold release on top of the current `momentum_optimized` runtime path

## 1. Problem statement

The 90-round BTST retrospective shows three different kinds of promising work:

1. **`momentum_tuned` / threshold tuning** already produced direct backtest uplift (`+0.20%` daily return, `48%` win rate, `1.39` payoff, `11/18` positive days) relative to the baseline comments recorded in `src/targets/short_trade_target_profile_data.py`.
2. **Round 89 trend-continuation correction** is an important structural fix, but the current rollout artifacts still say `hold` because runtime activation delta has not materialized across windows.
3. **candidate-entry weak-structure cleanup** has governance value and cleaner shadow behavior, but current evidence still describes it as shadow cleanup rather than direct actionable payoff uplift.

If the objective is to choose the **single next task most likely to improve short-term BTST win rate and payoff**, the strongest evidence currently points to the first bucket: reopen the `momentum_tuned` threshold release path, but do it through stricter rollout governance than the original round comments used.

## 2. Goal and non-goals

### Goal

Design a governed validation path that answers one narrow question:

> Can a `momentum_tuned`-style threshold release improve BTST selected-lane win rate and payoff against the current `momentum_optimized` runtime, without regressing drift, confidence interval stability, downside control, theme exposure, or rollout robustness?

### Non-goals

- Do not simultaneously redesign the entire BTST factor universe.
- Do not mix the work with Round 89 trend-continuation rollout promotion.
- Do not mix the work with candidate-entry shadow cleanup promotion.
- Do not promise runtime release before multi-window validation and rollout evidence pass.

## 3. Approaches considered

### Approach A — governed `momentum_tuned` re-validation (**recommended**)

Re-test the historically promising `momentum_tuned` settings (`select_threshold=0.38`, `near_miss_threshold=0.24`, `selected_rank_cap_ratio=0.50`) against the current `momentum_optimized` runtime and current guardrails.

**Pros**

- Best direct evidence for win-rate / payoff improvement from repository history
- Smallest conceptual change set
- Clear comparison target: current active `momentum_optimized`
- Easier to explain and document if validated

**Cons**

- Existing latest optimized-profile report is still `hold`
- Threshold release can reintroduce theme concentration, drift, and downside regressions if not constrained

### Approach B — finish Round 89 trend-continuation rollout first

Promote the reversal-to-trend-continuation correction into the active runtime path.

**Pros**

- Fixes a structurally important factor-direction issue
- Strong long-term architectural cleanliness

**Cons**

- Current rollout artifacts explicitly show `hold`
- Current blocker is not just “needs more test data”; it lacks runtime activation delta
- Lower chance of near-term win-rate / payoff improvement than Approach A

### Approach C — promote candidate-entry weak-structure cleanup

Push the weak-structure cleanup rule toward wider adoption.

**Pros**

- Promising shadow governance evidence
- Helps remove low-quality entry samples

**Cons**

- Current evidence says shadow cleanup, not direct payoff uplift
- Best framed as execution hygiene, not primary alpha uplift

## 4. Recommended design

We should design the next cycle around a **single governed release candidate**:

- **working name:** `momentum_tuned_governed_v1`
- **base profile:** `momentum_optimized`
- **core change set:** reintroduce the historical `momentum_tuned` threshold profile shape
- **governance twist:** require explicit multi-window, out-of-sample, and rollout guardrail passes before any runtime publication

This keeps the research surface small enough to attribute outcomes correctly. We are not asking “what if all promising ideas are combined?” We are asking “does the strongest historically positive threshold release still improve the live BTST objective under today’s stricter governance regime?”

## 5. Proposed profile boundary

The candidate profile should initially vary only these knobs relative to `momentum_optimized`:

1. `select_threshold`: `0.46 -> 0.38`
2. `near_miss_threshold`: `0.30 -> 0.24`
3. `selected_rank_cap_ratio`: keep the historical `0.50` experiment path visible as a tested variant

All other factor weights and runtime semantics should remain aligned with the current `momentum_optimized` baseline unless the validation artifacts prove that a second change is necessary. This isolates causality and reduces overfitting risk.

## 6. Validation design

Validation should be split into four layers owned by the three roles the user described:

### Alpha — factor / label / statistical robustness

Alpha owns:

- exact candidate definition and comparison cohorts
- shrinkage-aware win-rate / payoff comparisons
- confidence interval width, drift, redundancy, and overfit diagnostics
- documentation of assumptions and evidence quality

Alpha’s pass criteria:

- selected-lane win rate does not regress vs current runtime
- selected-lane payoff does not regress vs current runtime
- confidence interval width and drift metrics stay within explicit tolerance

### Beta — execution / microstructure / system effects

Beta owns:

- slippage-sensitive replay checks
- theme concentration and execution capacity review
- intraday survivability checks for newly admitted selected names
- code-path isolation if later implemented

Beta’s pass criteria:

- no material deterioration in execution-quality distribution
- no unacceptable increase in crowded / hard-to-enter names
- no evidence that the uplift is purely paper coverage without tradable quality

### Gamma — risk budget / rollout / sample-out validation

Gamma owns:

- window selection and out-of-sample splits
- rollout recommendation logic
- downside, drawdown, regime consistency, and publication gate
- release decision and fallback policy

Gamma’s pass criteria:

- no downside or drawdown regression beyond declared tolerance
- multi-window evidence remains positive enough for rollout
- publication state may change to `ready` only when blockers are cleared explicitly

## 7. Artifact plan

The design should produce or refresh these artifact classes before any release claim:

1. **profile comparison artifact** against current `momentum_optimized`
2. **multi-window validation artifact** with recent and older windows separated
3. **rollout decision artifact** that can say `ready` or `hold` with explicit blockers
4. **publication manifest evidence** only if rollout passes
5. **dated Chinese validation note** under `docs/prompt/generate_file/` if and only if the uplift is validated
6. **BTST skill integration update** only after the validated manifest or runtime path is actually active

## 8. Promotion rules

The candidate may be promoted only if all of the following are true:

1. selected-lane win rate is flat-to-up vs current runtime
2. selected-lane payoff is flat-to-up vs current runtime
3. downside / drawdown guardrails do not regress beyond explicit limits
4. theme exposure, drift, and CI-width blockers are cleared
5. out-of-sample evidence does not collapse relative to in-sample uplift
6. rollout artifact recommendation becomes `ready`

If any one of these fails, the candidate remains research-only and is not added to `ai-hedge-fund-btst`.

## 9. Expected code surfaces if implementation is approved later

This design intentionally delays implementation, but the likely code surfaces are already clear:

- `src/targets/short_trade_target_profile_data.py`
- `scripts/optimize_profile.py`
- rollout / validation scripts under `scripts/`
- optimized-profile resolution / publication path
- `docs/prompt/generate_file/`
- `skills/ai-hedge-fund-btst` or related BTST skill content only after validation

## 10. Error handling and rollback stance

- A failed validation is a successful research outcome, not a partial release.
- No runtime manifest should be updated on “mixed but interesting” evidence.
- If the candidate only improves coverage but worsens payoff, it is rejected.
- If the candidate improves payoff but materially worsens downside or drift, it is rejected.

## 11. Testing and verification strategy

When implementation is approved, verification should require:

1. targeted historical backtests across the same window families used in the retrospective
2. explicit comparison against `momentum_optimized` and current ready manifest behavior
3. rollout artifact regeneration
4. proof that any claimed improvement is reflected in repository artifacts, not only code comments

## 12. Why this is the right next task

This design chooses the smallest scope with the strongest existing evidence of direct BTST objective uplift. Round 89 trend-continuation work remains important, and candidate-entry cleanup remains useful, but neither currently has as strong a repository-backed case for immediate win-rate / payoff improvement as the `momentum_tuned` threshold-release path. The next best move is therefore not “invent a new factor family”; it is “re-open the best previously positive runtime profile candidate under stricter governance and see whether it still survives.”
