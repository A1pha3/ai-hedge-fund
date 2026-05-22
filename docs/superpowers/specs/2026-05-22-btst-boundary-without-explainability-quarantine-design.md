# BTST Boundary-Without-Explainability Quarantine Design

## Problem statement

The current BTST 5D / +15% research surface still contains a known noise bucket:

- `boundary_without_explainability`

This bucket is already understood well enough to treat as a **system contract / research-surface hygiene** problem, not an alpha-discovery problem:

- `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`
  - identifies `boundary_without_explainability` as the highest-priority candidate-source contract issue
  - recommends `inspect_candidate_source_contract`
- `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-fill-path-2026-05-22.md`
  - shows 121 total rows
  - 0 fully repaired
  - 121 partially repaired
  - only `t0_tail_strength` recoverable in `boundary_context`

The key design conclusion is:

- this cohort should not remain implicitly mixed into the factor research surface
- but it should also not be treated as “fixed” or promoted into runtime / factor docs

So the next subproject should build a **fail-closed quarantine layer** for this cohort before the team returns to broader 5D/+15% factor mining.

## Goal

Create a narrow boundary-governance design that explicitly classifies and quarantines the 121-row `boundary_without_explainability` cohort, produces downstream-consumable research-surface decisions, and keeps alpha / backtest logic unchanged.

## Non-goals

- Do **not** add or change BTST alpha factors.
- Do **not** change backtest labels, score thresholds, or rollout gates.
- Do **not** modify `ai-hedge-fund-btst`.
- Do **not** write anything into `docs/prompt/find_actor/`.
- Do **not** repurpose fill-path into a repair mechanism for the research surface.
- Do **not** widen scope to all missing-core-feature buckets in the same cycle.

## Current code and artifact context

### Existing inspection already isolates the target cohort

- `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - builds `boundary_rows`
  - filters specifically to:
    - `root_cause == "boundary_without_explainability"`
    - `bucket == "missing_all_core_features"`
    - `candidate_source in {"short_trade_boundary", "layer_b_boundary"}`
  - already emits:
    - `source_comparison_board`
    - `governance_recommendation_board`

### Existing fill-path is a downstream verifier, not the right quarantine surface

- `scripts/btst_boundary_contract_fill_helpers.py`
  - only tries to recover `boundary_context`
  - marks rows as fully / partially / irrecoverably repaired
- `scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py`
  - summarizes fill-path outcomes
  - currently reaches `hold_boundary_repair_until_more_context`

This proves fill-path is useful as a **post-repair verification** tool, but not the right place to decide which rows remain eligible for factor research.

### Existing noise-compression guidance already defines the governance direction

- `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`
  - `watchlist_empty_payload` -> `ignore_observation_noise`
  - `boundary_without_explainability` -> `inspect_candidate_source_contract`
  - `diagnostic_probe_without_core_features` -> `exclude_from_factor_surface`
  - `unknown_missing_core_contract` -> `split_into_separate_research_surface`

The next spec should operationalize the `boundary_without_explainability` branch of that guidance.

## Approaches considered

### 1. Recommended: diagnose + quarantine

Build a small quarantine layer that consumes the existing boundary inspection rows, classifies only the 121-row `boundary_without_explainability` cohort, and emits explicit research-surface decisions.

**Pros**

- smallest fail-closed step
- keeps alpha math untouched
- directly follows the current governance recommendation
- makes downstream factor-research filtering explicit instead of implicit

**Cons**

- does not “fix” upstream contract gaps yet
- requires a second future cycle if the team later wants to release rows from quarantine

### 2. Repair-first

Skip quarantine and immediately trace upstream candidate-source contract paths to restore the six missing core keys for the full cohort.

**Pros**

- closer to ultimate data recovery
- may reduce a later cleanup step

**Cons**

- larger blast radius
- mixes diagnosis, repair, and research-surface governance in one cycle
- too easy to over-interpret partial recovery as alpha progress

### 3. Exclude-only

Remove the cohort from factor research outputs without adding a dedicated governance artifact or per-row classification layer.

**Pros**

- fastest possible containment
- very low implementation risk

**Cons**

- loses row-level traceability
- harder for alpha / beta / gamma to inspect why specific rows were quarantined
- weak handoff surface for future upstream repair work

## Recommended design

Use **Approach 1: diagnose + quarantine**.

This cycle should create a **quarantine decision surface**, not a repair surface. The output should be explicit enough that downstream research scripts can consume it directly, and strict enough that no one mistakes these rows for validated factor candidates.

## Design sections

### 1. Architecture

Treat the next subproject as a **quarantine layer** that sits after `boundary_contract_inspection` and before any downstream round1 / round2 factor-research filtering.

The layer should:

1. read the already-isolated `boundary_without_explainability` cohort
2. classify each row into a governance outcome
3. publish a dedicated decision artifact for downstream filters

It should **not** try to repair upstream data, recompute factors, or loosen any runtime gate.

### 2. Components

#### A. Boundary cohort classifier

Purpose:

- transform each inspection row into a row-level governance decision

Responsibilities:

- accept only rows from the target cohort
- classify each row into one of:
  - `inspect_candidate_source_contract`
  - `quarantine_from_factor_surface`
  - `split_into_separate_research_surface`

Likely shape:

- a small helper module, separate from fill-path helpers
- focused on row-level classification rules only

#### B. Governance board builder

Purpose:

- aggregate row-level decisions into alpha / beta / gamma review boards

Responsibilities:

- summarize row counts by `candidate_source`
- expose which sources remain inspect-first vs quarantine-first
- emit a compact board that future scripts and docs can reference

#### C. Research-surface decision artifact

Purpose:

- make downstream factor-research filters deterministic

Responsibilities:

- emit three explicit lists / sections:
  - `allow`
  - `quarantine`
  - `separate_surface`
- default the target 121-row cohort away from the normal factor surface

### 3. Data flow

The intended path is:

`boundary_contract_inspection` -> `boundary cohort classifier` -> `governance board builder` -> `research-surface decision artifact`

`fill-path` remains downstream and separate:

- only after future upstream contract repair
- only to verify whether quarantined rows can be re-evaluated

### 4. Error handling and fail-closed rules

- Any row outside the target 121-row `boundary_without_explainability` cohort must stay out of this quarantine artifact.
- Any row with conflicting or incomplete classification evidence must default to `split_into_separate_research_surface`.
- A zero-row result must still write stable empty artifacts and boards so downstream automation never infers state from missing files.
- No row from this cycle can enter `docs/prompt/find_actor/` or `ai-hedge-fund-btst`.

### 5. Testing strategy

#### Helper-level checks

- row-level classifier tests:
  - target cohort -> `inspect_candidate_source_contract`
  - ambiguous / incomplete row -> `split_into_separate_research_surface`
  - explicitly quarantined row -> `quarantine_from_factor_surface`

#### Script-level checks

- deterministic board output for a mixed sample from:
  - `short_trade_boundary`
  - `layer_b_boundary`
- empty-input regression:
  - still writes stable empty boards / artifacts

#### Downstream safety checks

- regression proving the resulting research-surface decision artifact can be consumed by future factor-research filtering without manual interpretation
- regression proving the quarantine layer does not alter fill-path logic or alpha calculations

### 6. Acceptance criteria

This design is successful only if all of the following are true:

1. The 121-row `boundary_without_explainability` cohort is explicitly surfaced as a governed quarantine bucket.
2. Downstream round1 / round2 research can consume a deterministic `allow / quarantine / separate_surface` artifact.
3. Alpha / backtest / runtime behavior remains unchanged.
4. Fill-path remains a post-repair verifier, not the research-surface cleaner.
5. The cycle stays fail-closed and does not qualify for BTST factor promotion.

## Likely implementation surface

- new quarantine helper script/module adjacent to:
  - `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - `scripts/btst_boundary_contract_fill_helpers.py`
- new analysis script producing the quarantine artifact and governance boards
- focused tests for:
  - row classification
  - board aggregation
  - empty artifact stability

## Why this should happen before returning to factor mining

The broader 5D/+15% mission still matters more than boundary work. But this one quarantine cycle is the cheapest remaining step to clean the research surface before more factor iterations. After this spec is implemented, the recommended next move is to return to the factor-mining / backtest mainline with a cleaner sample surface.
