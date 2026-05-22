# BTST 5D/+15% Boundary Contract Fill-Path Design

- **Date:** 2026-05-22
- **Topic:** BTST 5D/+15% next-step design after boundary contract inspection
- **Recommended direction:** Validate a narrow fill path that lets `short_trade_boundary` and `layer_b_boundary` emit the round1 core explainability keys required by the offline factor-research surface, while keeping quarantine as a fail-closed fallback

## 1. Problem statement

The boundary contract inspection cycle reduced the current question to one concrete system-quality gap.

The verified evidence is:

1. `boundary_row_count = 121`
2. `short_trade_boundary = 75 rows`
3. `layer_b_boundary = 46 rows`
4. both sources have `metadata_only_rate = 1.0`
5. both sources have verdict `metadata_only_boundary_contract`
6. both sources map to action `fix_candidate_source_contract`

The current problem is no longer "which missing-core bucket should stay in factor mining?"

It is now:

> Can the boundary sources produce the round1 core explainability contract expected by the offline 5D/+15% research stack, or must they stay quarantined outside the factor surface?

This is worth a dedicated cycle because the issue is:

1. large enough to matter (`121` rows)
2. concentrated in two named sources
3. system-fixable in principle
4. still fail-closed if the fill path cannot be validated

## 2. Goal and non-goals

### Goal

Design one narrow contract-fill cycle that:

1. identifies the minimum round1 core-key contract the boundary sources must satisfy
2. derives or forwards those keys through a local fill path
3. validates whether the repaired rows still remain coherent under the offline research surface
4. leaves quarantine in place automatically if the fill path cannot be justified or reproduced

### Non-goals

- Do not widen into general candidate-source refactoring.
- Do not reopen `watchlist_empty_payload`, `diagnostic_probe_without_core_features`, or `unknown_missing_core_contract`.
- Do not promote anything into `docs/prompt/find_actor/`.
- Do not update `ai-hedge-fund-btst`.
- Do not claim alpha improvement from the repair itself.

## 3. Approaches considered

### Approach A - local boundary fill path with explicit fallback (**recommended**)

Define the minimum round1 core explainability contract, add a narrow builder for the two boundary sources, and validate the repaired cohort separately before allowing it back into offline factor mining.

**Pros**

- follows the current governance recommendation directly
- keeps scope local to the two sources
- creates evidence for either repair or quarantine
- avoids treating repair as automatic promotion

**Cons**

- may show that the needed keys cannot be reconstructed reliably
- can still end with quarantine instead of reuse

### Approach B - quarantine only

Accept the inspection result and permanently keep the boundary family outside the factor surface for now.

**Pros**

- smallest implementation scope
- keeps the research surface clean immediately
- low risk of fabricating explainability fields

**Cons**

- leaves a concentrated source-family gap unexplained
- gives up on potentially valid rows without testing recoverability
- does not improve system understanding

### Approach C - general upstream explainability backfill

Build a broad explainability backfill mechanism for all candidate sources with missing core keys.

**Pros**

- could solve similar issues elsewhere later
- centralizes explainability normalization

**Cons**

- too wide for the current evidence
- mixes unrelated source families
- increases risk of speculative refactoring

## 4. Recommended design

The next cycle should be a **boundary contract fill-path validation** for:

1. `short_trade_boundary`
2. `layer_b_boundary`

The design should answer four questions:

1. which round1 core keys are truly required for these rows to enter the offline factor surface
2. whether those keys can be forwarded or derived from already-available boundary context without inventing new alpha
3. whether repaired boundary rows remain internally coherent after the fill path is applied
4. whether Gamma should allow repaired rows back into offline research, or keep the family quarantined

This remains a contract-quality and research-surface-integrity project, not a factor-promotion project.

## 5. Design boundaries

This cycle stays narrow in six ways:

1. only the `121` boundary rows are in scope
2. only two candidate sources are investigated
3. the fill path must be local to the boundary family
4. the cycle can only reuse already-available context or deterministic derived values
5. quarantine remains the default outcome if repair evidence is weak
6. no runtime BTST promotion is allowed in this cycle

## 6. Proposed component design

### 6.1 Required core-key contract map

Create a small helper that defines the minimum round1 keys required by the offline research stack:

1. `breakout_freshness`
2. `trend_acceleration`
3. `volume_expansion_quality`
4. `close_strength`
5. `t0_tail_strength`
6. `trend_continuation`
7. `short_term_reversal`

For each key, the design should state whether boundary rows can:

1. forward an existing upstream value
2. deterministically derive a value from existing boundary context
3. or mark the key as irrecoverable for this family

### 6.2 Boundary fill-path builder

Build one local repair helper that takes a boundary row and returns:

1. original metadata-only payload
2. recovered core-key payload
3. fill provenance per key
4. a row-level repair status

Possible repair statuses:

1. `fully_repaired_boundary_contract`
2. `partially_repaired_boundary_contract`
3. `irrecoverable_boundary_contract`

The helper must not invent values without deterministic provenance.

### 6.3 Repaired-cohort validation board

Generate one analysis board covering:

1. row counts by repair status
2. key-level fill coverage
3. source-level differences between `short_trade_boundary` and `layer_b_boundary`
4. rows that remain irrecoverable
5. evidence on whether the repaired cohort is structurally consistent enough for offline research reuse

### 6.4 Governance decision board

Collapse the validation board into one governed recommendation:

1. `allow_repaired_boundary_surface_for_offline_research`
2. `quarantine_boundary_surface`
3. `hold_boundary_repair_until_more_context`

Only the first outcome permits the repaired cohort back into the offline factor-research surface. It still does **not** imply runtime promotion.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- ensuring repaired keys represent structure, not fabricated alpha
- judging whether repaired rows are usable for offline ranking without distorting factor mining
- keeping this cycle separate from any claim of improved 5D/+15% payoff

### Beta

Beta owns:

- tracing where each required core key could come from
- implementing the local fill-path contract
- recording fill provenance and irrecoverable gaps explicitly

### Gamma

Gamma owns:

- deciding whether repaired rows may re-enter offline research
- enforcing quarantine when repair provenance is incomplete
- preventing this cycle from widening into general explainability cleanup

## 8. Data flow

The cycle should run in this order:

1. read the verified boundary cohort
2. define the required core-key contract
3. attempt deterministic key forwarding or derivation per boundary row
4. classify each row by repair status
5. summarize repaired vs irrecoverable cohorts
6. emit one governance decision board

## 9. Error handling and fail-closed rules

The cycle must fail closed when:

1. a required key has no deterministic source or derivation rule
2. the same row would produce different repaired values across runs
3. provenance cannot explain how a filled key was obtained
4. repaired rows mix incompatible structures across the two boundary sources
5. allowing repaired rows back into research would rely on assumed or guessed values

If any of these conditions hold, the family stays quarantined.

## 10. Validation design

Validation for this cycle should prove:

1. the repair helper distinguishes fully repaired, partially repaired, and irrecoverable rows
2. filled keys always include provenance
3. irrecoverable keys remain explicit rather than silently defaulted
4. the repaired-cohort board is deterministic on fixture data
5. the final decision board can separate:
   - boundary rows safe for offline research reuse
   - rows that must remain quarantined
   - rows that still need more context

## 11. Promotion rules

This cycle still blocks:

1. runtime BTST profile changes
2. factor promotion into `docs/prompt/find_actor/`
3. `ai-hedge-fund-btst` integration

Only after a later cycle shows that repaired boundary rows materially improve offline research quality and remain governance-safe should any broader promotion be considered.

## 12. Expected outcome

If this design works, the next BTST decision becomes materially cleaner:

1. either the boundary family can be deterministically repaired and safely restored to the offline research surface
2. or the family is conclusively quarantined with explicit evidence that repair is not justified yet

Either result is better than leaving a 121-row metadata-only pocket in an ambiguous state.
