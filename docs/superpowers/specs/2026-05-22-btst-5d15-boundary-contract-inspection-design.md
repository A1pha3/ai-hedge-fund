# BTST 5D/+15% Boundary Contract Inspection Design

- **Date:** 2026-05-22
- **Topic:** BTST 5D/+15% next-step design after missing-core-features noise compression
- **Recommended direction:** Run a narrow `boundary_without_explainability` contract-inspection cycle before any new alpha or recovery work

## 1. Problem statement

The missing-core-features compression artifact converted the broad noise bucket into a much narrower routing question.

The relevant evidence is:

1. `missing_core_row_count = 347`
2. `watchlist_empty_payload = 146 rows` with action `ignore_observation_noise`
3. `boundary_without_explainability = 121 rows` with action `inspect_candidate_source_contract`
4. `diagnostic_probe_without_core_features = 71 rows` with action `exclude_from_factor_surface`
5. `unknown_missing_core_contract = 9 rows` with action `split_into_separate_research_surface`

That changes the next BTST question again.

The priority is no longer:

> Which missing-core bucket should stay in the factor surface?

Instead it becomes:

> Why do `short_trade_boundary` and `layer_b_boundary` rows carry metadata-only explainability payloads but no round1 core factor keys, and can that contract gap be fixed or quarantined without widening scope?

This is the only current noise bucket that is both:

1. large enough to matter (`121` rows)
2. plausibly system-fixable rather than expected observation traffic

## 2. Goal and non-goals

### Goal

Design one narrow inspection cycle that:

1. isolates `boundary_without_explainability` rows only
2. explains how the boundary candidate-source contract differs from the expected round1 factor contract
3. distinguishes harmless metadata-only routing from missing-core contract pollution
4. produces a governed decision about whether the boundary surface should be fixed, quarantined, or kept outside factor mining

### Non-goals

- Do not reopen `watchlist_empty_payload` or `diagnostic_probe_without_core_features` in the same cycle.
- Do not include `unknown_missing_core_contract` in this design.
- Do not promote any factor into `docs/prompt/find_actor/`.
- Do not update `ai-hedge-fund-btst`.
- Do not broaden into general candidate-source refactoring across the whole pipeline.

## 3. Approaches considered

### Approach A - inspect `boundary_without_explainability` only (**recommended**)

Build a dedicated contract-inspection artifact for the two boundary sources currently producing metadata-only, core-empty rows.

**Pros**

- follows the strongest recommendation from the latest artifact
- keeps attribution clean
- isolates the most actionable system-quality problem
- avoids reintroducing unrelated noise buckets

**Cons**

- does not resolve every remaining missing-core bucket
- may conclude the boundary surface should simply be quarantined instead of fixed

### Approach B - inspect boundary plus unknown upstream contract rows

Add the 9 `unknown_missing_core_contract` rows into the same cycle.

**Pros**

- slightly broader coverage of contract issues
- could reveal a shared upstream cause

**Cons**

- mixes two very different source families
- weakens interpretation if the boundary issue and upstream-shadow issue behave differently
- increases scope without strong evidence it is needed now

### Approach C - refactor all candidate-source contracts at once

Treat the problem as a general explainability-contract cleanup across all sources.

**Pros**

- could improve long-term cleanliness broadly
- addresses architectural quality in one pass

**Cons**

- too wide for one evidence-backed cycle
- not justified by the current artifact
- risks turning a narrow research step into generalized refactoring

## 4. Recommended design

The next cycle should be a **boundary contract inspection board** focused only on:

1. `short_trade_boundary`
2. `layer_b_boundary`

It should answer four questions:

1. what metadata keys these rows currently carry
2. which round1 core keys are systematically absent
3. whether the absence is source-specific, decision-specific, or both
4. whether Gamma should classify this as:
   - `fix_candidate_source_contract`
   - `quarantine_boundary_surface`
   - or `hold_boundary_until_more_context`

This is not a factor-validation design. It is a narrow contract-quality design that protects the next alpha cycle from avoidable boundary pollution.

## 5. Design boundaries

This cycle stays narrow in five ways:

1. only `boundary_without_explainability` is in scope
2. only `short_trade_boundary` and `layer_b_boundary` are investigated
3. the cycle analyzes contract shape, not price alpha
4. the output is a governance recommendation, not a runtime rule
5. any proposed fix must remain local to the boundary contract surface

## 6. Proposed component design

### 6.1 Boundary row isolate

Reuse the latest missing-core compression rebuild path, then filter rows where:

1. `root_cause == "boundary_without_explainability"`
2. `candidate_source in {"short_trade_boundary", "layer_b_boundary"}`

This keeps the new cycle anchored to the same verified offline artifact surface.

### 6.2 Contract shape summary

For each boundary source, summarize:

1. row count
2. decision composition
3. explainability key inventory
4. count of missing round1 core keys
5. recurring metadata-only keys such as `breakout_stage`, `target_profile`, `replay_context`, and `layer_c_decision`

This should show the exact contract mismatch instead of only restating that core keys are absent.

### 6.3 Boundary contract comparison board

Generate one artifact comparing `short_trade_boundary` vs `layer_b_boundary` with:

1. row count
2. decision composition
3. top metadata-only key sets
4. missing-core-key rate
5. core-payload-empty count
6. contract verdict

Possible contract verdicts:

1. `metadata_only_boundary_contract`
2. `partial_factor_contract`
3. `mixed_boundary_contract`

### 6.4 Governance recommendation board

Collapse the comparison into one short action board:

1. `fix_candidate_source_contract`
2. `quarantine_boundary_surface`
3. `hold_boundary_until_more_context`

The board should recommend **one** primary next step for the boundary family.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- confirming that this cycle is about surface quality, not alpha generation
- judging whether boundary pollution is large enough to distort future factor-mining results
- preventing metadata-only boundary rows from being misread as latent alpha

### Beta

Beta owns:

- tracing the current boundary explainability shape
- comparing actual metadata keys against required round1 core keys
- identifying whether the issue is source-specific or decision-specific

### Gamma

Gamma owns:

- deciding whether to fix or quarantine the boundary surface
- preventing the process from widening into general contract cleanup
- maintaining hold posture on promotion

## 8. Data flow

The cycle should flow in this order:

1. read the current noise-compression artifact inputs
2. rebuild the `boundary_without_explainability` cohort
3. split rows by `short_trade_boundary` vs `layer_b_boundary`
4. summarize metadata keys and missing core keys per source
5. produce one contract comparison board
6. synthesize one governance recommendation board

## 9. Error handling and fail-closed rules

The boundary inspection cycle must fail closed when:

1. the `boundary_without_explainability` cohort cannot be reproduced
2. explainability key extraction is inconsistent across runs
3. source-specific contract differences cannot be summarized deterministically
4. the board cannot distinguish source differences from simple row-count noise
5. the result would require generalized pipeline refactoring to interpret

No boundary source should be silently classified as "fixable" without explicit evidence.

## 10. Validation design

Validation for this cycle should prove:

1. the script reproduces the `121` boundary rows seen in the compression artifact
2. source-level contract summaries are deterministic
3. metadata-only keys are separated from missing round1 core keys
4. the recommendation board can distinguish:
   - a fixable boundary contract gap
   - a boundary surface that should be quarantined
   - evidence that is still too noisy to act on

## 11. Promotion rules

This cycle still does **not** promote factors or runtime rules.

Promotion remains blocked until a later cycle demonstrates:

1. the boundary pollution is either fixed or quarantined
2. the next factor-validation cycle uses a cleaner research surface
3. Alpha/Beta/Gamma all still clear the 5D/+15% governance bar

## 12. Expected outcome

If this design works, the next BTST decision becomes cleaner again:

1. either `boundary_without_explainability` is a local contract bug worth fixing
2. or it is a boundary-only metadata surface that should stay outside factor mining

Either result is more valuable than restarting factor exploration while a 121-row boundary pollution pocket remains unresolved.
