# Upstream Shadow FNFP Dossier Design

- **Date:** 2026-05-24
- **Topic:** BTST upstream-shadow mainline follow-up after zero decision-impact rollout
- **Recommended direction:** Build a dedicated upstream-shadow false-negative / false-positive dossier before any new rollout or target-rule changes

## 1. Problem statement

The latest upstream-shadow rollout cycle answered an important question: relaxing the current rollout switches does **not** create meaningful decision uplift.

The key evidence is:

1. `report_dir_count = 194`
2. `best_variant = relief_free_shadow_caps`
3. `selected_count_delta = 0`
4. `near_miss_count_delta = 0`
5. `tradeable_count_delta = 0`
6. `execution_eligible_count_delta = 0`
7. aggregate T+1 / T+2 tradeable deltas are also `0`

That changes the next question. The strongest unresolved uncertainty is no longer "which rollout switch should be loosened?" The stronger question is:

> Which `upstream_liquidity_corridor_shadow` samples are being wrongly suppressed despite later strength, and which weak samples are still being allowed to consume attention or score budget?

If we do not answer that first, the next cycle risks repeating the same pattern: more rollout variation, but no improvement in real BTST win rate or payoff.

## 2. Goal and non-goals

### Goal

Design one narrow analysis cycle that:

1. isolates upstream-shadow false negatives and false positives at row level
2. explains how those rows split across `close_continuation` vs `balanced_confirmation`
3. surfaces the blocker / score-gap / repeated-ticker clusters that matter most
4. produces a ranked recommendation for the next alpha-refinement pass

### Non-goals

- Do not change target thresholds during this design phase.
- Do not weaken rollout governance just to create more activated names.
- Do not publish a new BTST optimized profile.
- Do not update `ai-hedge-fund-btst`.
- Do not reopen a broad new factor-family search before upstream-shadow sample quality is understood.

## 3. Approaches considered

### Approach A - create a thin dedicated FN/FP orchestrator (**recommended**)

Create one new analysis script that composes existing replay, blocker, and dossier helpers, but stays explicitly scoped to `upstream_liquidity_corridor_shadow` and nearby upstream-shadow observation rows.

**Pros**

- Keeps the new work tightly aligned to the real mainline blocker
- Reuses existing validated loaders and row-normalization paths
- Preserves clean responsibility boundaries in the existing generic analyzers
- Produces a BTST-specific artifact that directly informs Alpha next steps

**Cons**

- Adds one more script to the research surface
- Still depends on the quality of existing row-level replay artifacts

### Approach B - extend `analyze_short_trade_blockers.py` directly

Push upstream-shadow FN/FP logic into the existing blocker analyzer.

**Pros**

- Reuses an existing analysis surface
- Already has access to blocker and gate information

**Cons**

- Mixes a narrow upstream-shadow research question into a broader generic blocker tool
- Raises the risk that the script becomes too wide and harder to reason about
- Makes output harder to keep focused on Alpha refinement

### Approach C - extend multi-window validation again

Continue to add upstream-shadow sample decomposition into `analyze_btst_multi_window_profile_validation.py`.

**Pros**

- Reuses an established baseline-vs-variant framework
- Stays close to the rollout artifacts already produced

**Cons**

- The tool is optimized for profile comparisons, not row-level FN/FP diagnosis
- Less natural place to rank repeated tickers, blocker clusters, or quality-label splits
- Risks blurring the line between rollout evaluation and sample-structure diagnosis

## 4. Recommended design

The next cycle should create a dedicated **upstream-shadow FN/FP dossier**.

It should answer four questions:

1. which upstream-shadow rows were not selected, but later showed strong continuation or payoff evidence
2. which upstream-shadow rows reached `selected` or `near_miss`, but later underperformed
3. whether the stronger rows already correlate with `close_continuation`, higher `trend_acceleration`, and higher `close_strength`
4. which specific row clusters should drive the next Alpha factor split instead of another rollout tweak

The output of this cycle should not be "promote a new profile." It should be a governed diagnosis artifact that says where the real upstream-shadow alpha mistake currently sits.

## 5. Design boundaries

This design stays narrow in five ways:

1. it only studies upstream-shadow cohorts, not the whole BTST population
2. it diagnoses sample quality rather than modifying runtime scoring rules
3. it reuses existing replay / blocker / historical-prior loaders where possible
4. it ends in a recommendation artifact, not a rollout promotion
5. it treats rollout as already answered for now: no decision uplift means the next cycle must focus on sample structure

## 6. Proposed component design

### 6.1 Cohort extraction layer

The dossier should primarily filter rows where:

1. `candidate_source == "upstream_liquidity_corridor_shadow"`
2. or the row can be normalized from `upstream_shadow_observation_entries` back into the same upstream-shadow family

This allows the analysis to cover both already-materialized short-trade rows and upstream-shadow observation rows that still carry useful blocker or prior evidence.

### 6.2 FN/FP classification layer

The analysis should define:

1. **false negative** — a row that was not `selected`, but later realized strong continuation / payoff evidence
2. **false positive** — a row that reached `selected` or `near_miss`, but later realized weak follow-through, weak payoff, or quality signatures consistent with `balanced_confirmation`

The exact thresholds should be deterministic and derived from existing outcome fields instead of freeform narrative.

### 6.3 Row payload layer

Each retained row should keep the fields needed to explain *why* it belongs in the dossier:

1. `trade_date`
2. `ticker`
3. `decision`
4. `candidate_source`
5. `score_target`
6. `gap_to_select`
7. `gap_to_near_miss`
8. `top_reasons`
9. `blockers`
10. historical quality label and historical sample counts
11. `trend_acceleration` / `close_strength` clues when available

This keeps the artifact directly actionable for Alpha without forcing a second lookup pass.

### 6.4 Aggregate summary layer

The dossier should emit at least these aggregate sections:

1. `false_negative_rows`
2. `false_positive_rows`
3. `blocker_clusters`
4. `quality_label_split`
5. `trend_acceleration_band_split`
6. `close_strength_band_split`
7. `repeat_ticker_board`
8. one explicit `recommendation`

The point is not to maximize metrics. The point is to collapse the upstream-shadow ambiguity into a short set of ranked next actions.

### 6.5 Ranking layer

The false-negative ranking should prefer rows that:

1. realized stronger forward outcomes
2. missed `selected` by a smaller score gap
3. already showed stronger continuation-like historical signatures
4. repeat across multiple trade dates or tickers often enough to matter

The false-positive ranking should prefer rows that:

1. were given more decision privilege (`selected` above `near_miss`)
2. realized worse forward outcomes
3. show weaker historical quality signatures such as `balanced_confirmation`
4. appear in blocker / penalty regimes that should probably have been stricter

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- the FN/FP taxonomy
- the `close_continuation` vs `balanced_confirmation` interpretation
- the split between meaningful continuation evidence and noise
- the final recommendation about which sample family to refine next

### Beta

Beta owns:

- composing the new dossier script out of existing helpers
- keeping row normalization deterministic and reproducible
- ensuring the artifact exposes enough blocker / score-gap detail to be useful
- avoiding unnecessary duplication of existing replay logic

### Gamma

Gamma owns:

- preventing this cycle from turning into a hidden rollout loosening exercise
- reviewing whether the inferred next step really improves risk-adjusted selection quality
- keeping the post-dossier release posture fail-closed until later validation exists

## 8. Data flow

The next cycle should flow in this order:

1. resolve report directories or input artifacts
2. load or rebuild upstream-shadow candidate rows from existing snapshot / replay sources
3. normalize rows into a common FN/FP analysis shape
4. classify each row as false negative, false positive, or neither
5. compute band splits, blocker clusters, and repeat-ticker summaries
6. rank the strongest FN and FP examples
7. emit JSON + Markdown artifacts plus one explicit recommendation

## 9. Error handling and fail-closed rules

The dossier must fail closed when:

1. required report artifacts cannot be resolved
2. row normalization cannot determine a stable ticker/trade-date identity
3. outcome fields are malformed enough to prevent deterministic FN/FP classification
4. duplicate rows cannot be resolved consistently
5. required aggregate sections cannot be computed

When only a single row is incomplete, the row may degrade to explicit `unknown` fields, but the script must not silently swallow whole cohorts.

## 10. Validation design

Validation should run in this order:

1. classification tests for false negative / false positive / neither
2. deduplication tests for repeated `trade_date + ticker` rows
3. markdown rendering tests
4. missing-data tests for absent historical prior or absent outcome data
5. compatibility tests covering both snapshot rows and observation rows

The minimum success bar for implementation is not "the recommendation looks plausible." The minimum bar is that the dossier deterministically classifies, ranks, and summarizes upstream-shadow cohorts in a way that can be re-run and trusted.

## 11. Artifact plan

If implementation is approved later, the cycle should produce:

1. a JSON dossier artifact for machine-readable row analysis
2. a Markdown dossier artifact for Alpha/Beta/Gamma discussion
3. one clear recommendation naming the next highest-value upstream-shadow refinement target
4. no BTST skill update and no rollout change unless a later validation cycle earns it

## 12. Exit criteria

This design phase is successful when the implementation can answer:

1. which upstream-shadow rows are strongest false negatives
2. which upstream-shadow rows are strongest false positives
3. whether `close_continuation` vs `balanced_confirmation` is the decisive split
4. whether the next step should focus on factor refinement, blocker repair, or candidate-definition cleanup

Until those questions are answered, the upstream-shadow mainline should remain in diagnosis mode rather than rollout-expansion mode.
