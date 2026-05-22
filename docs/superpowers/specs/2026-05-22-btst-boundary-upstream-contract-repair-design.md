# BTST Boundary Upstream Contract Repair Design

## Problem statement

The just-merged quarantine cycle made the `boundary_without_explainability` cohort explicit and fail-closed, but it did not remove the upstream cause.

Current verified state:

- `scripts/analyze_btst_5d_15pct_boundary_quarantine.py`
  - still refreshes a local artifact with:
    - `boundary_row_count=121`
    - `governance_actions=inspect_candidate_source_contract`
- `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - still isolates rows where:
    - `root_cause == "boundary_without_explainability"`
    - `bucket == "missing_all_core_features"`
    - `candidate_source in {"short_trade_boundary", "layer_b_boundary"}`
- the quarantine cycle now keeps those rows out of the round1 research surface by default
  - but it intentionally does **not** repair upstream source contract gaps

That means the current system posture is:

1. governance is now explicit and fail-closed
2. research contamination is reduced
3. but the same upstream contract defect can keep generating the same 121-row cohort

So the next narrow subproject should repair the **source contract** that feeds `short_trade_boundary` / `layer_b_boundary`, rather than keep adding more downstream quarantine or repair layers.

## Goal

Repair the upstream short-trade boundary contract so the core explainability keys required by boundary inspection and round1 research are emitted consistently at the source, reducing or eliminating the current 121-row `boundary_without_explainability` cohort.

## Non-goals

- Do **not** add or tune BTST alpha factors.
- Do **not** widen scope to round2 consumption.
- Do **not** integrate anything into `ai-hedge-fund-btst` in this cycle.
- Do **not** promote anything into `docs/prompt/find_actor/`.
- Do **not** redesign quarantine governance; reuse the existing quarantine / inspection scripts as verifiers.
- Do **not** introduce synthetic fallback factor values when the source truly lacks evidence.

## Current code and artifact context

### Existing quarantine is containment, not repair

- `scripts/analyze_btst_5d_15pct_boundary_quarantine.py`
  - converts inspection rows into:
    - `decision_rows`
    - `disposition_summary_board`
    - `source_summary_board`
    - `governance_decision_board`
    - `research_surface_lists`
- `scripts/analyze_btst_5d_15pct_factor_research_round1.py`
  - now consumes the quarantine artifact
  - excludes `quarantine` and `separate_surface` tickers from round1 by default

This solved the research-surface hygiene problem, but intentionally left the source problem untouched.

### Inspection still points upstream

- `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - derives `boundary_context` from row-level visible fields
  - classifies the target cohort as `boundary_without_explainability`
  - recommends `inspect_candidate_source_contract`

This is the strongest current signal about the next task: not more quarantine, but a narrower source repair.

### The likely source path already carries the raw ingredients

- `src/targets/models.py`
  - `TargetEvaluationResult` already has top-level fields for:
    - `breakout_freshness`
    - `trend_acceleration`
    - `volume_expansion_quality`
    - `close_strength`
    - `trend_continuation`
    - `short_term_reversal`
- `src/targets/short_trade_target_evaluation_helpers.py`
  - already computes the short-trade evaluation result and explainability payload inputs
- `src/execution/daily_pipeline_candidate_helpers.py`
  - already builds `short_trade_boundary_metrics`
  - already decides which fields are emitted into the downstream boundary lane contract

This suggests the highest-value repair is **contract normalization and propagation**, not factor recomputation.

## Approaches considered

### 1. Recommended: upstream contract repair

Repair the source emitter and downstream contract normalizer so boundary lanes write the required core explainability keys onto a stable, downstream-consumable surface before inspection or quarantine ever see the rows.

**Pros**

- attacks the root cause instead of its symptoms
- keeps quarantine as a verifier rather than a permanent crutch
- stays narrow: source emission + contract normalization + regression verification
- improves both inspection and future research reuse without changing alpha math

**Cons**

- touches production-facing data flow instead of analysis-only scripts
- requires careful precedence / provenance handling

### 2. Continue with downstream repair layers

Keep source contract untouched and add another downstream mapping layer that converts `boundary_context` back into a research-consumable surface after the fact.

**Pros**

- smaller immediate blast radius
- faster to ship than source work

**Cons**

- entrenches the wrong architectural seam
- duplicates logic already present upstream
- makes future debugging harder because “real” and “repaired” surfaces diverge

### 3. Diagnostics-only expansion

Do not repair anything yet; instead add narrower boards, rollout tracking, and more diagnostics around the 121-row cohort.

**Pros**

- lowest implementation risk
- may expose finer-grained sub-buckets

**Cons**

- does not stop the cohort from regenerating
- adds more observability without changing system behavior
- poor leverage compared with a narrow source repair

## Recommended design

Use **Approach 1: upstream contract repair**.

This cycle should repair the **source emission contract** that feeds boundary lanes and selection-target downstream surfaces. Quarantine remains in place as a fail-closed backstop, but the implementation goal is to stop the current root cause from continuously manufacturing the same cohort.

## Design sections

### 1. Architecture

Treat this subproject as a **source-contract normalization** cycle.

The architecture should be:

1. emit required core explainability keys from the short-trade evaluation source
2. normalize how those keys propagate into boundary-lane / selection-target downstream surfaces
3. verify the repair using existing inspection, quarantine, and round1 scripts

This cycle should **not**:

- add a new repair artifact
- widen quarantine scope
- change factor formulas
- loosen runtime or research governance

### 2. Components

#### A. Source-core emitter

Purpose:

- make the required core explainability keys visible at the source layer in a stable, canonical structure

Likely implementation surface:

- `src/targets/short_trade_target_evaluation_helpers.py`
- adjacent short-trade metrics / explainability payload builders used there

Responsibilities:

- identify the minimum required keys for this cohort repair
- ensure those keys are emitted consistently from the short-trade evaluation result
- preserve provenance / precedence rather than silently fabricating values

#### B. Boundary contract normalizer

Purpose:

- ensure `short_trade_boundary` and `layer_b_boundary` consume the same normalized source contract

Likely implementation surface:

- `src/execution/daily_pipeline_candidate_helpers.py`

Responsibilities:

- map the source-core emitter output into downstream boundary metrics / selection-target surfaces
- keep precedence deterministic:
  - explicit downstream snapshot values win
  - canonical source-emitted values backfill only when the downstream slot is absent
- avoid lane-specific drift where one candidate source exposes keys and another does not

#### C. Verification surface

Purpose:

- prove that the source repair actually shrinks the current cohort

Implementation surface should reuse:

- `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
- `scripts/analyze_btst_5d_15pct_boundary_quarantine.py`
- `scripts/analyze_btst_5d_15pct_factor_research_round1.py`

Responsibilities:

- confirm repaired rows stop classifying into the current `boundary_without_explainability` bucket
- confirm quarantine now sees fewer target rows
- confirm round1 no longer excludes the repaired rows by default quarantine discovery

### 3. Data flow

The intended path is:

`short_trade_target_evaluation_helpers` -> `TargetEvaluationResult canonical explainability surface` -> `daily_pipeline_candidate_helpers` boundary / selection-target contract -> `selection snapshots` -> `boundary inspection` -> `quarantine` -> `round1 research`

Key design decision:

- repair the contract **before** the snapshot / inspection boundary, not after it

### 4. Error handling and fail-closed rules

- If a required core key is genuinely absent upstream, keep it absent; do **not** synthesize a default numeric factor value.
- If two possible sources disagree, keep explicit downstream values authoritative and only backfill missing keys from the canonical source emitter.
- If a repaired row still lands in `boundary_without_explainability`, quarantine behavior stays unchanged; the repair cycle must not weaken containment.
- Scope stays limited to the target boundary cohort; do not opportunistically broaden the contract repair to unrelated candidate lanes.

### 5. Testing strategy

#### Source-level checks

- targeted tests proving the source emitter writes the intended core keys onto the canonical surface
- regression tests for precedence / backfill behavior where explicit downstream values already exist

#### Pipeline-level checks

- targeted tests proving `daily_pipeline_candidate_helpers` carries the normalized keys into boundary / selection-target downstream contract surfaces
- regression tests proving no unrelated keys are widened or overwritten

#### Boundary verification checks

- regression proving repaired synthetic/live-style rows no longer reconstruct into the current boundary root cause
- quarantine regression proving the target cohort count shrinks under the same reports root

#### Round1 downstream safety checks

- regression proving a repaired custom `reports_root` no longer relies on quarantine exclusion for these rows
- regression preserving existing quarantine behavior for truly unrepaired rows

### 6. Acceptance criteria

This design is successful only if all of the following are true:

1. The source contract for `short_trade_boundary` / `layer_b_boundary` now exposes the required core explainability keys on a stable downstream-consumable surface.
2. The current 121-row `boundary_without_explainability` cohort materially shrinks, ideally to zero, under the same verification scripts.
3. Existing quarantine / round1 fail-closed behavior stays intact for any rows still unrepaired.
4. No round2, BTST skill integration, or factor promotion scope is added.
5. The cycle remains a contract repair, not an alpha optimization claim.

## Likely implementation surface

- `src/targets/short_trade_target_evaluation_helpers.py`
- nearby short-trade metrics / explainability payload builder helpers used by that source path
- `src/execution/daily_pipeline_candidate_helpers.py`
- focused tests under:
  - `tests/execution/`
  - `tests/targets/`
  - `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`
  - `tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py`
  - `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`

## Why this should happen before broader factor mining

The next big priority is still returning to 5D/+15% factor mining and backtest improvement. But the quarantine cycle showed one remaining narrow systems defect still distorts the research sample surface at the source. Repairing that source contract now is the cheapest remaining boundary cleanup step before returning to the main alpha / beta / gamma factor-improvement line.
