# Momentum Cross-Window Stability Retune Design

- **Date:** 2026-05-21
- **Topic:** BTST short-trade win-rate / payoff improvement
- **Recommended direction:** Run a narrow momentum retune cycle centered on cross-window stability regressions, while preserving the current `hold` release posture

## 1. Problem statement

The momentum rollout blocker triage cycle is now complete and no longer needs more diagnosis before the next move. The verified triage artifact shows:

1. `action = parameter_retune_next`
2. `release_posture = hold`
3. `dominant_family = cross_window_stability`
4. missing observability still exists, but it is not the dominant blocker family

The window-attribution artifact further narrows the problem:

1. family counts are `missing_observability = 4`, `cross_window_stability = 9`, `risk_payoff_regression = 4`
2. the dominant attribution surface is `momentum_optimized`
3. the remaining blocker set is concentrated in stability-style regressions such as `gate_above_threshold_cv`, `win_rate_window_trend`, `win_rate_ci_width`, `factor_drift_score`, and `win_rate_cv`
4. the current research posture remains fail-closed and does not justify manifest publication or BTST skill promotion

This means the highest-value next cycle is no longer "explain why the momentum line is blocked." We now have that explanation. The next cycle is to test whether a **small, governed retune** around the current momentum line can reduce the dominant cross-window stability blockers without weakening release governance or expanding into a broad new factor search.

## 2. Goal and non-goals

### Goal

Design a narrow retune cycle that answers one concrete question:

> Can we improve the `momentum_optimized -> momentum_tuned` line enough on cross-window stability metrics to justify a later rollout re-check, without relaxing release thresholds or broadening the search surface?

### Non-goals

- Do not create a new BTST factor family in this cycle.
- Do not weaken rollout thresholds, blocker semantics, or publication rules.
- Do not treat missing observability as "solved" just because it is no longer dominant.
- Do not publish a new manifest or update `skills/ai-hedge-fund-btst` in this cycle.
- Do not merge this work into PR #2; the momentum cycle remains stacked on the activation-delta branch.

## 3. Approaches considered

### Approach A — narrow cross-window stability retune (**recommended**)

Constrain the next cycle to a local retune around the current momentum candidate and optimize explicitly against the dominant stability regressions.

**Pros**

- directly follows the verified `parameter_retune_next` recommendation
- stays on the strongest existing candidate family instead of reopening the full search space
- reduces overfitting risk by using a small parameter neighborhood rather than a new wide search
- keeps missing-observability blockers visible while focusing engineering effort on the dominant failure mode

**Cons**

- may still end in `hold`
- could show that the current momentum line is inherently unstable rather than tunably unstable

### Approach B — measurement-first cleanup before any retune

Pause all retuning work and first repair the remaining projected / incremental theme-exposure observability gaps.

**Pros**

- simplifies attribution
- removes one source of rollout noise before retuning

**Cons**

- contradicts the current triage recommendation
- delays work on the dominant blocker family
- risks spending a full cycle on a secondary problem while stability blockers remain unchanged

### Approach C — broad momentum search refresh

Reopen a wide parameter search or add new factor knobs immediately.

**Pros**

- could discover a higher-upside candidate
- is operationally familiar because the repo already has large search/report tooling

**Cons**

- highest overfitting risk
- weakest connection to the newly produced triage evidence
- too easy to hide stability failures inside a larger search space

## 4. Recommended design

The next cycle should be a **governed local retune** of the momentum line:

- **candidate family:** `momentum_optimized -> momentum_tuned`
- **optimization target:** reduce dominant cross-window stability regressions
- **release posture:** stay fail-closed at `hold`
- **promotion posture:** none; only earn the right to a later rollout re-check

This cycle assumes the current momentum line is still worth testing because:

1. historical evidence already showed local uplift on the momentum family
2. the triage output no longer says "measurement fix first"
3. the dominant blockers are concentrated in stability-style metrics rather than broad downside alone

The design does **not** assume promotion is likely. The only intended outcome is a tighter answer:

1. either a narrowed retuned candidate clears enough stability pressure to justify a later rollout reassessment
2. or the retune proves that the current momentum family should remain `hold`

## 5. Design boundaries

This cycle stays narrow in four ways:

1. it only works on the existing momentum candidate family
2. it only explores a local parameter neighborhood around the current candidate
3. it explicitly scores stability regressions more heavily than generic score uplift
4. it ends in a governed decision artifact, not in manifest publication

That boundary matters because the retrospective document shows the project gets the most reliable gains when local uplift is converted into better runtime governance, not when each new cycle broadens into another unconstrained search.

## 6. Proposed component design

### 6.1 Local retune search surface

The retune should search a small neighborhood around the current best momentum parameters instead of reopening a full Cartesian grid.

The initial surface should bias toward knobs most likely to affect stability / churn behavior:

1. `select_threshold`
2. `recency_half_life_days`
3. `trend_acceleration_weight`
4. `close_strength_weight`
5. `volume_expansion_quality_weight`
6. `catalyst_freshness_weight`

Parameters already effectively disabled in the current candidate should stay fixed unless evidence shows they directly control the blocker family:

1. `momentum_strength_weight = 0.0`
2. `short_term_reversal_weight = 0.0`

This keeps the cycle local and makes "improvement" attributable to a small, understandable set of retune moves.

### 6.2 Stability-sensitive evaluation layer

The retune objective should not chase a better scalar score alone. It should explicitly account for the blocker family that actually stopped rollout.

The evaluation surface should treat these metrics as first-class retune targets:

1. `win_rate_window_trend`
2. `win_rate_window_volatility`
3. `win_rate_ci_width`
4. `win_rate_cv`
5. `factor_drift_score`
6. `param_drift_score`
7. `gate_above_threshold_cv`

The retune cycle should prefer candidates that:

1. reduce the count of cross-window stability blockers
2. do not worsen the risk/payoff blocker family
3. keep the release posture at `hold` until a later explicit rollout check says otherwise

### 6.3 Observability handling during retune

Missing projected / incremental theme-exposure deltas should remain visible in the cycle, but they are no longer the leading objective.

The cycle should:

1. carry the missing-observability state into reports
2. refuse to treat a candidate as releaseable while those gaps persist
3. avoid letting those gaps dominate the retune ranking unless they become the dominant blocker family again

This preserves the governance lesson from the triage cycle: non-dominant blockers still matter, but they should not displace the primary next move.

### 6.4 Governed retune decision surface

The final output of the cycle should again collapse to one narrow next-step decision:

1. **rerun rollout check**
   - if the retune clearly reduces cross-window blockers without worsening downside/risk blockers
2. **retain hold**
   - if stability regressions remain dominant or broaden
3. **fallback to measurement repair**
   - if missing observability unexpectedly becomes dominant again during retune

No outcome in this cycle directly publishes a manifest or updates BTST-facing report-generation skills.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- defining which stability regressions are the true retune objective
- protecting against overfitting in the narrowed retune surface
- documenting why a retune candidate is statistically more or less stable

### Beta

Beta owns:

- wiring the local retune search and comparison artifacts
- ensuring the candidate/source artifact chain stays aligned with real repo data shapes
- interpreting whether parameter moves reduce churn-related execution instability

### Gamma

Gamma owns:

- preserving the `hold` / no-publication decision boundary
- deciding whether any retuned candidate has earned a later rollout reassessment
- rejecting any "better score but worse governance" candidate

## 8. Validation design

Validation for the retune cycle should run in this order:

1. start from the current momentum triage outputs
2. generate local retune candidates around the current momentum line
3. compare each candidate against `momentum_optimized` and `default`
4. summarize whether cross-window blocker counts fall, hold flat, or worsen
5. emit a governed retune decision artifact

The success ladder is:

1. replace a generic "retune next" instruction with a specific local retune surface
2. prove whether the dominant stability blockers are reducible without harming risk/payoff governance
3. reduce the next step to either a later rollout re-check or a justified retained `hold`

If the cycle cannot do that, it is still a valid research failure and should remain `hold`.

## 9. Artifact plan

If implementation is approved later, the cycle should produce:

1. a local momentum retune candidate report
2. a stability-focused comparison / blocker delta artifact
3. a governed retune decision artifact
4. no BTST skill update and no Chinese validation note unless a later rollout cycle actually promotes

## 10. Promotion rules

Promotion remains unchanged:

1. no factor or runtime improvement is promoted into `ai-hedge-fund-btst` without substantial historical validation
2. no Chinese `docs/prompt/generate_file/` note is written unless a later rollout decision actually clears promotion
3. any future promotion still needs backtest evidence for both win-rate improvement and payoff improvement
