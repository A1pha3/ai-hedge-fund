# BTST `layer_c_watchlist` Governed Rollout Design (2026-05-28)

## Background

The current BTST evidence stack is now consistent on two points:

1. `layer_c_watchlist` is the only source lane that still shows up as a **stable formal payoff drag lane** across the refreshed runner-payoff windows.
2. `short_trade_boundary` appears only as a **conditional** drag lane, so it should not be promoted into a stable rollout conclusion yet.

That means the next BTST optimization step should no longer be "find another ad-hoc source list." It should be: turn the current `layer_c_watchlist` conclusion into a reproducible governed-rollout decision path that can be replayed, audited, and cited in Chinese optimize-method docs.

## Goal

Design a reproducible BTST rollout-validation flow that:

1. resolves replay inputs directly from weekly-validation manifests instead of hand-curated source lists;
2. combines replay precision evidence with the existing runner-payoff diagnosis into a single rollout decision artifact;
3. emits a clear recommendation for `layer_c_watchlist` while keeping `short_trade_boundary` in the conditional / monitor bucket;
4. gives alpha, beta, and gamma one shared artifact to review before any live-default promotion discussion.

## Non-goals

1. Do not promote any profile to live default in this phase.
2. Do not reopen full 5D/+15% relabeling in this phase.
3. Do not make `short_trade_boundary` a stable rollout candidate without new evidence.
4. Do not rely on manually stitched Markdown conclusions as the source of truth.

## Approaches

### Approach A: Keep using runner-payoff artifacts only

Use `scripts/analyze_btst_runner_payoff_realignment.py` and the refreshed artifact files as the only evidence source, then restate the conclusion in docs.

**Pros**

1. Lowest engineering cost.
2. Reuses already-refreshed artifacts.

**Cons**

1. Still does not prove the rollout recommendation through replay deltas.
2. Leaves source-resolution and replay reproducibility outside the artifact chain.
3. Makes docs depend on a partial evidence stack.

### Approach B: Manual replay + manual doc stitching

Replay the relevant weekly window with manually selected frozen-plan sources, then hand-copy the result into Chinese docs.

**Pros**

1. Fast for one-off analysis.
2. Lets us inspect replay detail directly.

**Cons**

1. Not reproducible enough for repeated BTST governance work.
2. Fragile when weekly windows change.
3. Keeps too much operator knowledge outside versioned code.

### Approach C: Manifest-driven replay + governed rollout artifact (**recommended**)

Extend the shadow replay analyzer so it can resolve `daily_events.jsonl` inputs from weekly-validation manifests, then create one governed rollout script that combines:

1. runner-payoff diagnosis,
2. replay precision deltas,
3. lane-specific rollout rules.

**Why this is recommended**

1. It gives one reproducible artifact chain from weekly validation to rollout conclusion.
2. It keeps `layer_c_watchlist` and `short_trade_boundary` policy treatment explicit instead of implied.
3. It creates a durable base for later multi-lane governance without prematurely expanding scope.

## Recommended design

### 1. Manifest-driven replay source resolution

`scripts/analyze_btst_shadow_profile_replay.py` should accept a weekly-validation manifest path and resolve replayable `daily_events.jsonl` sources from the manifest's selected reports.

Expected behavior:

1. prefer manifest-driven source discovery when `weekly_validation_json` is provided;
2. preserve existing explicit `frozen_plan_source` behavior for backward compatibility;
3. fail loudly when the manifest does not resolve to any replayable daily event sources.

This moves replay source selection from "human remembered which files to pass" to "artifact already says which reports belong to this weekly window."

### 2. Governed rollout decision artifact

Add a focused script, tentatively `scripts/analyze_btst_layer_c_rollout_validation.py`, that consumes:

1. the runner-payoff artifact for a window;
2. replay analysis for the matching weekly manifest;
3. optional expanded-window replay / payoff artifacts for confirmation.

The script should emit one JSON artifact with:

1. `inputs` - exact upstream artifacts and windows used;
2. `runner_payoff_diagnosis` - selected vs near-miss payoff gap and source-lane verdict;
3. `replay_diagnosis` - formal selection count delta, hit-rate deltas, and any precision / recall trade-offs;
4. `rollout_recommendation` - one of:
   - `promote_layer_c_governed_rollout`
   - `keep_layer_c_shadow_only`
   - `monitor_more_windows`
5. `lane_policies` - explicit per-lane treatment:
   - `layer_c_watchlist = stable_formal_shrink_lane`
   - `short_trade_boundary = conditional_only`

### 3. Policy rules

The governed rollout recommendation should follow explicit rules:

1. `layer_c_watchlist` can move to `promote_layer_c_governed_rollout` only if payoff and replay evidence both support the shrink direction across the chosen windows.
2. `short_trade_boundary` must stay `conditional_only` unless replay-backed evidence also stabilizes across windows.
3. Any mismatch between payoff direction and replay direction should downgrade to `monitor_more_windows`.
4. Missing replay sources or incomplete artifacts should fail the analysis instead of silently producing a promotion-shaped output.

### 4. Documentation integration

Chinese optimize-method docs should cite the rollout artifact instead of manually narrating the conclusion from memory.

That means:

1. add one new dated Chinese doc for the `layer_c_watchlist` governed-rollout line;
2. update the existing runner-payoff doc so it points at the rollout artifact as the next governance layer;
3. keep the wording precise: `layer_c_watchlist` is the stable rollout candidate, while `short_trade_boundary` remains conditional.

## Data flow

The intended evidence path is:

`weekly validation manifest -> manifest-driven shadow replay -> runner-payoff artifact -> governed rollout artifact -> Chinese optimize-method doc`

This keeps each step independently inspectable:

1. weekly validation says which reports belong to the window;
2. replay shows what the shadow change does to formal precision behavior;
3. runner-payoff artifact shows whether the lane is dragging the 5D/+15% objective;
4. rollout artifact decides whether the lane graduates from shadow evidence to governed rollout recommendation.

## Error handling

The new flow should reject incomplete inputs explicitly:

1. no replayable reports in weekly manifest -> hard error;
2. missing runner-payoff artifact fields -> hard error;
3. missing lane policy evidence -> hard error;
4. mixed old/new artifact schemas -> hard error.

No fallback should silently synthesize rollout conclusions from partial data.

## Testing strategy

### Replay analyzer coverage

Add focused tests that prove:

1. weekly-validation manifests resolve the correct `daily_events.jsonl` inputs;
2. empty manifests fail clearly;
3. explicit `frozen_plan_source` behavior still works unchanged.

### Governed rollout artifact coverage

Add focused tests that prove:

1. aligned payoff + replay evidence promotes `layer_c_watchlist`;
2. mixed evidence downgrades to `monitor_more_windows`;
3. `short_trade_boundary` stays conditional when only payoff evidence is stable;
4. output payload includes exact input artifact paths and lane policies.

### Documentation coverage

Add or extend tests only where docs or report builders already assert artifact-backed wording, so the new rollout artifact references stay stable.

## Risks

1. Overstating rollout readiness from payoff evidence alone.
2. Treating manual replay success as governance evidence when the source resolution is not reproducible.
3. Accidentally broadening the project into a full target relabeling rewrite.

## Success criteria

This design is successful when:

1. a weekly-validation manifest is enough to reproduce the replay inputs;
2. the rollout recommendation is emitted as a machine-readable artifact;
3. `layer_c_watchlist` and `short_trade_boundary` are clearly separated into stable vs conditional policy treatment;
4. the Chinese docs cite the governed artifact rather than informal reasoning.

## Implementation boundary

The immediate implementation that should follow this spec is limited to:

1. manifest-driven replay source resolution;
2. a governed rollout analysis script plus tests;
3. one dated Chinese rollout doc update path.

Anything broader than that should be handled in a later spec.
