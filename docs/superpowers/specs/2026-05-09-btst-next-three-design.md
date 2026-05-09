# BTST Routed Validation, Search, and Coverage Guardrails Design

## Problem

The BTST pipeline has just completed two important changes:

1. fragile-breakout committee risk is now part of routed BTST committee profiles,
2. the execution-layer routing bug is fixed, so prebuy selection targets now see the resolved effective profile instead of inheriting the outer `default` context.

That creates a new bottleneck: the **live decision path and the validation path are no longer guaranteed to be aligned everywhere**. Some replay and optimization surfaces still reflect older profile assumptions, and current rollout evidence still does not tell us how often the committee is making decisions on exact intraday inputs versus proxy substitutes.

If alpha, beta, and gamma start tuning thresholds immediately without first aligning validation and exposing data-source coverage, the next optimization cycle could overfit a validation path that is not identical to the live routed system.

## Current Evidence

### The live committee path has changed materially

- `src/targets/short_trade_target_profile_data.py` now contains routed BTST committee profiles such as `ignition_breakout`, `retention_follow`, and `shadow_research`.
- `src/targets/short_trade_target_committee_helpers.py` now includes fragile-breakout scoring and profile-level rollout knobs.
- `src/execution/daily_pipeline.py` now threads the effective short-trade target profile into `_build_post_market_order_context()`, so prebuy selection targets follow live routing correctly.

### Validation and optimization still lag the live routing model

- Replay and comparison scripts still need a clean path to the same routed profile and window preset logic used by the live system.
- Existing search workflows still focus on older default grids and legacy profile assumptions.
- Current replay/report outputs preserve raw-vs-proxy sources, but do not summarize whether routed committee decisions are primarily driven by exact microstructure inputs or fallbacks.

### Existing infrastructure is already close to sufficient

- The repository already has replay, walk-forward, and optimization tooling.
- The committee payload already preserves component sources and key raw metric source fields.
- The next cycle can therefore focus on **alignment, calibration, and rollout guardrails**, not on inventing another new strategy factor.

## Goals

1. Make the validation/backtest path use the same routed BTST profile logic that now drives live prebuy selection.
2. Calibrate the routed committee profiles with measured replay search instead of fixed hand-tuned constants.
3. Add rollout guardrails that explicitly report raw-vs-proxy committee coverage before profile promotion decisions.

## Non-Goals

1. Do not add another new BTST factor before routed validation and calibration are aligned.
2. Do not broaden the search space into a generic all-profile optimizer.
3. Do not treat proxy-backed committee outputs as equivalent to exact intraday-microstructure outputs without explicit coverage reporting.
4. Do not promote a routed committee profile purely on anecdotal single-window outcomes.

## Alternatives Considered

### 1. Search-first workflow

Start immediately by tuning `ignition_breakout` and `retention_follow` committee thresholds.

**Rejected for now** because the routing fix changed the real live execution path. Searching before the validation path is aligned risks optimizing the wrong system.

### 2. Coverage-first workflow

Build raw-vs-proxy reporting first, then unify validation, then search.

**Deferred** because coverage guardrails are important, but they do not replace the need to make replay/backtests use the same routed profiles as live execution. Alignment comes first.

### 3. Validation-first routed workflow

First unify validation/backtests around the routed BTST profiles, then run targeted committee search, then add rollout coverage guardrails.

**Recommended** because it gives the fastest reliable path to real BTST edge improvement while preventing the next cycle from overfitting stale or partially mismatched evaluation surfaces.

## Recommended Approach

### Task 1: Unify validation and backtests around routed BTST profiles

Gamma should first align the validation toolchain with the live routed committee path.

This means:

1. replay comparison flows must accept the same routed profile selection,
2. walk-forward entry points must expose the same window-mode / preset choices that determine what “live-like” means,
3. the default BTST profile sets in validation scripts must include the routed committee profiles that now matter in production.

This task does not change BTST alpha by itself, but it changes whether future alpha work is trustworthy.

### Task 2: Run staged committee threshold search for routed profiles

Once the validation path is aligned, alpha should add a routed-profile-specific search surface for:

1. `committee_alpha_min_*`,
2. `committee_beta_min_*`,
3. `committee_gamma_min_*`,
4. `committee_score_min_*`,
5. `committee_fragile_breakout_*`.

This search should be **narrow, staged, and replay-driven**. The first pass should operate on controlled replay windows rather than a broad open-ended walk-forward sweep. The purpose is to identify whether the newly routed committee profiles can improve next-day win rate and payoff once their thresholds are calibrated to real routed behavior.

### Task 3: Add raw-vs-proxy committee coverage guardrails

Beta and gamma should then add rollout guardrails that summarize:

1. `flow_60_source`,
2. `persist_120_source`,
3. `close_support_30_source`,
4. committee `component_sources`,
5. profile-level raw coverage rates per replay window.

This task protects against silent degradation. A routed committee profile should not be promoted based on attractive replay outcomes if most of those outcomes were produced by weaker proxy inputs rather than the exact microstructure feeds that the design assumes.

## Architecture

The cycle should stay inside the existing BTST execution and validation stack:

1. **Live routing layer** — `src/execution/daily_pipeline.py`, `src/targets/short_trade_target.py`, `src/targets/short_trade_target_profile_data.py`
2. **Replay and comparison layer** — `compare.py`, `scripts/btst_20day_backtest.py`, related replay/walk-forward entry points
3. **Search layer** — `scripts/optimize_profile.py`
4. **Rollout evidence layer** — replay/multi-window reporting artifacts that already preserve committee and metric sources

No new factor family is required in this cycle. The work is about making routed committee behavior measurable, calibratable, and promotable with confidence.

## Data Flow

The intended sequence is:

`routed live profiles -> aligned replay/backtest entry points -> routed committee search -> raw/proxy coverage summaries -> rollout verdict`

Required invariants:

1. the same routed profile identity must flow through live execution and validation,
2. search runs must operate on the routed profiles that are actually candidates for promotion,
3. rollout evidence must distinguish exact-input wins from proxy-backed wins.

## Metrics That Matter

### Primary

1. next-day close win rate,
2. next-day payoff ratio,
3. post-fee expectation / realized edge proxy on replay windows.

### Secondary

1. tradeable count,
2. hit rate at next-high thresholds,
3. continuation behavior beyond T+1 when it does not damage the BTST objective.

### Rollout safety

1. raw-input coverage rate by metric,
2. committee component source mix,
3. window-level share of routed decisions backed by exact versus proxy data.

## Error Handling and Safe Defaults

1. If a validation surface cannot honor routed profile identity, it should fail explicitly rather than silently falling back to a legacy default.
2. If a replay window lacks sufficient raw metric coverage, the output should surface that as a promotion warning rather than hiding it.
3. If routed search results are mixed, the default action should be to keep the current promoted profile settings unchanged.
4. If a metric source mix is mostly proxy-backed, that window can still be analyzed, but it should not count as strong rollout evidence.

## Validation Strategy

### 1. Validation-path alignment checks

Add focused tests and/or script-level assertions proving that replay/backtest flows use the routed profile and chosen window preset instead of legacy defaults.

### 2. Routed committee search checks

Add focused optimizer coverage proving the new routed-profile grid is reachable and produces checkpointable evaluation outputs.

### 3. Coverage guardrail checks

Add regression coverage and artifact assertions showing that committee source coverage is summarized in replay outputs.

## Success Criteria

This cycle is successful if all of the following hold:

1. routed BTST validation/backtests use the same effective profiles as live execution,
2. routed committee search exists for the real promoted profiles,
3. rollout artifacts explicitly summarize raw-vs-proxy coverage before promotion decisions,
4. the next BTST tuning cycle can rely on measured routed behavior instead of stale or partially mismatched defaults.

## Failure Criteria

This cycle should be considered unsuccessful if:

1. replay/search tooling still optimizes a legacy or mismatched profile surface,
2. search results exist but cannot be tied to the live routed decision path,
3. rollout evidence still hides whether committee behavior depends on exact or proxy inputs.

## Expected Implementation Surfaces

Likely files and artifacts:

1. `compare.py`
2. `scripts/btst_20day_backtest.py`
3. `scripts/optimize_profile.py`
4. routed replay / multi-window report writers that already emit committee payloads
5. test files covering execution, optimizer, and reporting surfaces

## Assumptions

Because the user was unavailable during brainstorming, this spec assumes approval for the following execution order:

1. align routed validation/backtests first,
2. search routed committee thresholds second,
3. enforce raw-vs-proxy rollout guardrails third.
