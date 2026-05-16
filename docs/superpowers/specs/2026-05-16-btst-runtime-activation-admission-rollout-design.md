# BTST Runtime Activation, Formal Admission, and Rollout Alignment Design

## Problem

The latest BTST cycle closed several important governance gaps:

1. multi-window validation can now explain when a profile variant produces **no runtime activation delta**,
2. reporting artifacts now expose when **raw `selected` names are rebucketed to `blocked` by formal execution gates**,
3. the strict rollout gate now blocks promotion when replay evidence shows structural instability or zero runtime activation.

Those fixes made the system safer, but they also clarified the next bottleneck:

1. Round 89 style trend-continuation corrections can still remain **offline improvements** rather than live BTST improvements,
2. the formal BTST main-pick lane still has no targeted recovery path for **non-`halt`** cases where strong candidates are blocked by softer governance rules,
3. rollout logic is safer than before, but it still needs to become more explicitly aligned with **execution-eligible BTST edge**, not just offline replay uplift.

If alpha, beta, and gamma optimize new factors or publish new manifests before fixing those three gaps, the next cycle risks repeating the same pattern:

1. offline uplift that does not materially change runtime surfaces,
2. raw selection that never becomes formal executable BTST action,
3. promotion logic that remains more conservative, but not yet fully aligned with executable short-trade edge.

## Current Evidence

### 1. Runtime activation is now measurable, and zero-delta variants are visible

- `scripts/analyze_btst_multi_window_profile_validation.py` now emits `runtime_activation_attribution`.
- Recent evidence showed a profile variant can change thresholds or profile identity while still producing **zero selected / near-miss / tradeable / guardrail delta** across replay windows.
- This means "better offline theory" is not enough; the next cycle must explain and fix **why runtime surfaces do not move**.

### 2. Formal BTST absence was traced to formal gate semantics, not silent selection loss

- The recent BTST report showed no formal BTST main picks.
- Investigation established that raw `selected` names did exist upstream, but reporting rewrote them to `blocked` because formal execution gates fired.
- Provenance is now exposed in reporting summaries and user-facing BTST documents, so the next step is no longer "find the bug"; it is "recover executable formal admission only where recovery is actually valid."

### 3. Promotion governance is stronger, but still needs execution-eligible alignment

- Structural blockers, zero-runtime-activation blockers, and runtime-selected-but-not-execution-eligible blockers now reach the strict rollout gate.
- That prevents unsafe promotion into manifest / skill adoption.
- However, the next cycle still needs a more direct positive standard for **what counts as promotable executable BTST improvement**, not just what counts as disqualifying regression.

## Goals

1. Make trend-continuation and similar post-Round-89 profile work produce **observable runtime activation deltas** when the factor truly improves BTST edge.
2. Recover **formal executable BTST main picks** in valid non-`halt` cases without weakening hard macro protection.
3. Align rollout / promotion decisions around **execution-eligible edge**, so only profiles that improve executable BTST behavior can move toward manifest publication and eventual `ai-hedge-fund-btst` adoption.

## Non-Goals

1. Do not bypass `halt` or other hard macro stop conditions just to force formal picks.
2. Do not promote a profile because it looks better in offline metrics while runtime activation remains unchanged.
3. Do not wire any new factor or profile into `ai-hedge-fund-btst` before replay, walk-forward, and rollout evidence all agree.
4. Do not broaden this cycle into a full-factor rewrite of the BTST stack.

## Alternatives Considered

### 1. Promotion-first cycle

Try to push the latest factor corrections through rollout faster by further relaxing blockers.

**Rejected** because the repo now has strong evidence that some candidates still fail on runtime activation or formal execution. Promotion-first would reintroduce false-positive adoption risk.

### 2. Formal-main-pick-first cycle

Focus first on restoring formal BTST main picks wherever the user-visible report looks too conservative.

**Deferred** because this treats the visible symptom before the deeper root cause. If the factor changes still do not activate runtime surfaces, formal-main-pick recovery can become cosmetic rather than real edge improvement.

### 3. Runtime-activation-first cycle **(recommended)**

First force factor/profile changes to prove they move runtime surfaces, then add targeted admission relief for valid non-`halt` cases, then tighten rollout criteria around execution-eligible evidence.

**Recommended** because it is the shortest path to real BTST improvement while preserving the newly improved governance chain.

## Recommended Approach

### Task 1: Repair runtime activation for trend-continuation-driven profile work

Alpha and gamma should first focus on the question:

> Why do trend-continuation-style profile corrections still fail to produce meaningful runtime activation deltas in replay windows?

This task should inspect:

1. effective profile resolution,
2. scoring payload construction,
3. threshold interactions,
4. rank-cap and relief interactions,
5. any upstream normalization that can neutralize the intended factor shift.

The outcome must be measurable in runtime artifacts:

1. `selected`,
2. `near_miss`,
3. `tradeable`,
4. `execution_eligible`,
5. and corresponding payoff / win-rate tradeoffs.

No profile may proceed toward rollout on the basis of theoretical factor superiority if those runtime surfaces remain unchanged.

### Task 2: Add non-`halt` formal admission relief for executable strong candidates

Once runtime activation is genuinely moving the surface, beta and gamma should add a narrow formal-admission recovery path for candidates that are:

1. strong enough to be raw `selected`,
2. not blocked by `halt`,
3. blocked by softer governance conditions where recovery can be explicitly bounded and validated.

This task is not a general relaxation. It must distinguish:

1. **hard-stop conditions** that remain absolute,
2. **recoverable non-`halt` constraints** where a stronger candidate can still become formal executable inventory under controlled rules.

Candidate examples include softer regime states, boundary cases in prior-quality enforcement, or rank-cap / relief interactions where the current pipeline is too conservative relative to measured replay results.

### Task 3: Upgrade rollout / promotion rules around execution-eligible edge

After Tasks 1 and 2, gamma should raise the rollout standard from:

> "candidate is not obviously unsafe"

to:

> "candidate improves executable BTST behavior and remains stable out of sample."

This task should make promotion logic explicitly account for:

1. `execution_eligible_selected_count`,
2. raw-selected-but-formal-blocked share,
3. cost-aware payoff,
4. downside stability,
5. replay / walk-forward consistency,
6. and any residual structural or activation blockers.

The goal is to publish manifests only when the improvement is both:

1. observable in runtime behavior, and
2. durable under rollout governance.

## Architecture

The work should stay inside the existing BTST stack:

1. **Runtime scoring / profile layer**  
   `src/targets/profiles.py`, `src/targets/short_trade_target_profile_data.py`, target evaluation helpers, metrics payload builders
2. **Execution and formal gating layer**  
   `src/execution/daily_pipeline.py`, execution-contract helpers, router/build helpers, runtime observability helpers
3. **Validation and replay layer**  
   `scripts/analyze_btst_multi_window_profile_validation.py`, `scripts/btst_admission_replay_validator.py`, backtesting / walk-forward tooling
4. **Promotion / publication layer**  
   `scripts/btst_strict_objective_gate.py`, `scripts/optimize_profile.py`, optimized-profile manifest publication helpers
5. **BTST report / skill-consumption layer**  
   selection review renderer, BTST brief builders/renderers, and finally `ai-hedge-fund-btst` only after promotion evidence clears

## Data Flow

The intended sequence is:

`factor/profile correction -> runtime activation attribution -> formal admission semantics -> execution-eligible replay evidence -> strict rollout gate -> manifest publication -> ai-hedge-fund-btst adoption`

Required invariants:

1. factor corrections must alter runtime surfaces before they count as real BTST progress,
2. formal admission recovery must never bypass hard macro stop logic,
3. rollout promotion must use execution-eligible evidence, not just offline uplift,
4. the BTST skill must continue consuming only approved manifest-backed runtime improvements.

## Error Handling and Safe Defaults

1. If a candidate profile still shows zero runtime activation delta across replay windows, the default action remains **hold / baseline**.
2. If raw `selected` names exist but all are blocked by `halt`, the system must explain that clearly and must not try to recover formal picks.
3. If a non-`halt` recovery rule creates more formal picks but harms cost-adjusted payoff or downside behavior, the recovery rule fails and stays offline.
4. If rollout evidence is mixed, the manifest must stay unchanged and the BTST skill must continue using the current approved chain.

## Validation Strategy

### 1. Runtime activation validation

Add focused red/green coverage proving that the chosen factor/profile corrections create measurable runtime deltas in replay windows, not just changed metadata or thresholds.

### 2. Formal admission validation

Add focused tests proving:

1. `halt` remains unrecoverable,
2. valid non-`halt` cases can recover into formal executable picks only under bounded rules,
3. reporting and runtime summaries preserve provenance for any recovery or continued block.

### 3. Rollout validation

Add optimizer / strict-gate / manifest-publication coverage proving that only candidates with improved execution-eligible evidence can advance toward publication.

### 4. Regression slice

Run the focused BTST replay, formal-admission, reporting, and optimize-profile regressions that already exist around these surfaces.

## Success Criteria

This cycle is successful only if all of the following hold:

1. the chosen factor/profile changes produce measurable runtime activation deltas,
2. at least some valid non-`halt` raw-selected candidates can become formal executable picks without weakening hard-stop governance,
3. rollout decisions explicitly prefer execution-eligible edge over purely offline uplift,
4. any resulting manifest candidate survives replay / walk-forward / strict-gate validation,
5. only then may the resulting improvement be considered for `ai-hedge-fund-btst`.

## Failure Criteria

Stop and keep the current approved baseline if any of the following remain true:

1. trend-continuation-style changes still produce zero runtime activation delta,
2. formal main-pick recovery depends on bypassing `halt` or similarly hard macro blocks,
3. additional formal picks improve optics but not executable edge,
4. rollout promotion still cannot distinguish runtime improvement from offline-only uplift.

## Expected Implementation Surfaces

Likely files and test surfaces:

1. `src/targets/short_trade_target_profile_data.py`
2. `src/targets/short_trade_target_evaluation_helpers.py`
3. `src/targets/router_build_helpers.py`
4. `src/paper_trading/runtime_observability_helpers.py`
5. `src/research/review_renderer.py`
6. `src/paper_trading/_btst_reporting/brief_builder.py`
7. `scripts/analyze_btst_multi_window_profile_validation.py`
8. `scripts/btst_admission_replay_validator.py`
9. `scripts/btst_strict_objective_gate.py`
10. `scripts/optimize_profile.py`
11. focused BTST tests across runtime attribution, admission replay, reporting, backtesting, and rollout publication

## Approved Execution Order

The approved order for the next BTST cycle is:

1. **Runtime activation repair first**
2. **Non-`halt` formal admission relief second**
3. **Execution-eligible rollout / promotion alignment third**

That order is intentional:

1. without Task 1, later admission or promotion changes risk optimizing a profile that still does not materially move runtime behavior,
2. without Task 2, improved runtime scoring may still fail to become actionable formal BTST inventory,
3. without Task 3, even real executable improvements could still be judged by incomplete promotion criteria.
