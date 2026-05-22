# BTST 5D/+15% Missing-Core-Features Noise Compression Design

- **Date:** 2026-05-22
- **Topic:** BTST 5D/+15% next-step design after the near-trend recovery line was held
- **Recommended direction:** Build a narrow `missing_all_core_features` noise-compression analysis layer before reopening any new recovery or factor-expansion work

## 1. Problem statement

The latest recovery cycle answered an important routing question:

1. `near_trend_threshold` did **not** graduate into a valid next-step alpha line
2. the recovery artifact found only `1` recovered row (`600392`)
3. that row had `hit_rate_15pct = 0.0` and `mean_max_future_high_return_2_5d = 0.0688`
4. the governance verdict was `hold_recovery_too_small_or_noisy`

That pushes the process back to the larger structural evidence from the unclassified split board:

1. `row_count = 856`
2. `unclassified_row_count = 454`
3. `missing_all_core_features = 347 rows`
4. `watchlist_only_low_signal = 52 rows`
5. `other_unclassified = 54 rows`
6. `near_trend_threshold = 1 row`

After the recovery hold, the biggest unresolved question is no longer:

> Can we rescue the near-threshold pocket?

It becomes:

> Why does such a large share of the research surface arrive with no usable round1 core structure at all, and how much can we improve the 5D/+15% research surface by compressing that noise before the next factor search?

If we do not answer that, the next research cycle will keep mixing genuine structure with rows that have no round1 factor payload.

## 2. Goal and non-goals

### Goal

Design one narrow analysis cycle that:

1. isolates the `missing_all_core_features` population
2. explains which candidate sources, decisions, and payload states create that population
3. separates benign observation noise from research-surface contamination
4. produces a governed compression board telling us which upstream row families should be excluded, down-weighted, or kept out of the next factor-mining surface

### Non-goals

- Do not promote any factor into `docs/prompt/find_actor/`.
- Do not update `ai-hedge-fund-btst`.
- Do not reopen broad threshold widening.
- Do not claim that noise compression itself is alpha.
- Do not loosen beta/execution gates just to preserve more rows.

## 3. Approaches considered

### Approach A - compress `missing_all_core_features` first (**recommended**)

Design a dedicated source-audit and compression board for rows that arrive without any usable round1 core inputs.

**Pros**

- targets the largest unresolved bucket directly
- best fit with the latest recovery-hold verdict
- reduces future research-surface dilution before more factor work
- gives Alpha/Beta/Gamma a concrete governance handle instead of broad intuition

**Cons**

- does not immediately search for a new alpha factor
- may conclude that much of the bucket is expected observation noise rather than a bug

### Approach B - decompose `other_unclassified` first

Prioritize the smaller but more promising mixed bucket because it already shows better raw returns than the main noise bucket.

**Pros**

- closer to a potential alpha lead
- could reveal hidden structure faster

**Cons**

- leaves the largest source of dilution unresolved
- risks optimizing while the research surface is still polluted by structurally empty rows

### Approach C - reopen adjacent boundary recovery ladders

Expand from the failed near-trend recovery into neighboring boundary bands and search for a denser recovery cohort.

**Pros**

- stays close to the previous cycle
- could grow sample size faster

**Cons**

- the previous recovery line already failed closed
- likely reintroduces scope creep before the main noise source is understood
- weaker attribution than fixing the dominant noise bucket first

## 4. Recommended design

The next cycle should be a **missing-core-features noise compression board**.

It should answer four questions:

1. which upstream candidate-source families are producing rows with completely empty round1 inputs
2. which of those rows are expected low-signal observation traffic versus contract or routing pollution
3. which row families should be excluded from future factor-mining surfaces
4. whether compressing this bucket is likely to materially improve the interpretability of the next round1/round2 alpha search

This is a routing-and-surface-quality design, not a factor-promotion design.

## 5. Design boundaries

This cycle stays narrow in five ways:

1. it only investigates `missing_all_core_features`
2. it does not change the current factor definitions
3. it does not rescue rows into a new alpha cohort
4. it produces compression recommendations, not runtime trading rules
5. it remains subordinate to the 5D/+15% objective by improving the research surface rather than forcing weak rows back into it

## 6. Proposed component design

### 6.1 Missing-core-features row rebuild

Rebuild the same round1 rows already used by the split board and recovery cycle, then filter:

1. `event_prototype == "unclassified"`
2. `bucket == "missing_all_core_features"`

This preserves a single row contract across the full 5D/+15% offline chain.

### 6.2 Root-cause classifier

Create a deterministic classifier that groups each missing-core row into interpretable root-cause families such as:

1. `watchlist_empty_payload`
2. `boundary_without_explainability`
3. `diagnostic_probe_without_core_features`
4. `blocked_before_factor_evaluation`
5. `unknown_missing_core_contract`

The exact names should be derived from existing fields already present in row rebuilds, especially:

1. `candidate_source`
2. `decision`
3. `short_trade.explainability_payload`
4. any consistent blocker or contract markers exposed by the snapshot

### 6.3 Compression board artifact

Generate one artifact that summarizes each root-cause family with:

1. row count
2. candidate-source composition
3. decision composition
4. closed-cycle count
5. 15% hit rate
6. mean 2-5d max return
7. payload-emptiness pattern
8. compression recommendation

This board should make it clear which families are simply noise that should stay out of factor research and which ones may indicate an upstream routing/contract issue.

### 6.4 Compression recommendation board

Collapse the artifact into a short governance board with actions such as:

1. `ignore_observation_noise`
2. `exclude_from_factor_surface`
3. `inspect_candidate_source_contract`
4. `split_into_separate_research_surface`
5. `hold_until_more_context`

The board should recommend **one** primary next action for the dominant families instead of producing a vague list.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- deciding whether compressing this bucket is likely to improve research-surface signal purity
- checking whether any root-cause family still contains objective-relevant structure
- preventing "noise compression" from being misread as alpha generation

### Beta

Beta owns:

- rebuilding the missing-core cohort deterministically
- mapping source/decision/payload combinations into root-cause families
- ensuring the compression board can be reproduced from current report artifacts

### Gamma

Gamma owns:

- deciding which families should be excluded or quarantined from later factor cycles
- blocking premature widening or recovery work while the dominant noise bucket is unresolved
- keeping promotion posture at hold

## 8. Data flow

The cycle should flow in this order:

1. read the current report corpus
2. rebuild round1 rows with the existing helper path
3. filter `missing_all_core_features`
4. assign each row to one deterministic root-cause family
5. compute per-family surface-quality and objective-support summaries
6. synthesize one compression recommendation board

## 9. Error handling and fail-closed rules

The noise-compression cycle must fail closed when:

1. row rebuild cannot reproduce the expected `missing_all_core_features` population
2. required source/decision/payload fields are missing or malformed
3. a root-cause family cannot be assigned deterministically
4. the board cannot distinguish empty-payload observation noise from contract issues
5. summary metrics disagree across repeated rebuilds

No family should silently default to "exclude" or "recoverable" without explicit evidence.

## 10. Validation design

Validation for this cycle should prove:

1. the script reproduces the expected `missing_all_core_features` population
2. each root-cause family assignment is deterministic
3. empty-payload rows are not mixed with rows that actually have hidden structure
4. the recommendation board can distinguish:
   - benign observation noise
   - surface contamination worth excluding
   - candidate-source contract issues worth deeper inspection

## 11. Promotion rules

This cycle still does **not** promote factors or runtime rules.

Promotion remains blocked until a later cycle demonstrates:

1. the research surface is cleaner
2. the next factor/recovery candidate actually improves the 5D/+15% objective
3. the evidence survives Beta tradeability and Gamma governance

## 12. Expected outcome

If this design works, the next BTST decision becomes clearer again:

1. either the dominant empty-payload bucket is mostly harmless observation noise and can be quarantined from factor mining
2. or it reveals specific source-contract pollution that should be fixed before the next alpha cycle

Either outcome is more valuable than reopening broader factor or recovery work while the largest structural noise bucket is still unexplained.
