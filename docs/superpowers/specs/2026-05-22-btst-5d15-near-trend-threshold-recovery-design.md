# BTST 5D/+15% Near-Trend-Threshold Recovery Design

- **Date:** 2026-05-22
- **Topic:** BTST 5D/+15% next-step design after the unclassified split board
- **Recommended direction:** Run a narrowly scoped `near_trend_threshold` recovery-validation cycle before any broader trend/breakout refinement

## 1. Problem statement

The unclassified split board has now converted the broad round1 failure into a much narrower routing question.

The relevant evidence is:

1. `row_count = 856`
2. `unclassified_row_count = 454`
3. `missing_all_core_features = 347 rows` with `recoverability_verdict = ignore_noise`
4. `watchlist_only_low_signal = 52 rows` with `recoverability_verdict = ignore_noise`
5. `other_unclassified = 54 rows` with `recoverability_verdict = ignore_noise`
6. `near_trend_threshold = 1 row` with `recoverability_verdict = recover_threshold_near_miss`

This means the split board did not say "widen all thresholds." It said something much narrower:

> The only currently identified recoverable structural pocket is `near_trend_threshold`, while the dominant unclassified mass still behaves like noise.

That changes the next BTST question again. The priority is no longer "how do we rescue more unclassified rows?" and not "which broad trend family should we retune?" The next question is:

> Can a tightly governed recovery rule around `near_trend_threshold` create meaningful 5D/+15% uplift without opening the door to the large noisy buckets?

## 2. Goal and non-goals

### Goal

Design one narrow recovery-validation cycle that:

1. defines a deterministic `near_trend_threshold` recovery candidate
2. tests whether this candidate improves 5D/+15% objective support on structurally similar rows
3. keeps the noisy unclassified buckets out of scope
4. produces a governed answer about whether the recovery line deserves implementation or should be abandoned

### Non-goals

- Do not widen to `near_breakout_threshold` in the same cycle.
- Do not reopen broad trend/breakout refinement.
- Do not promote anything into `docs/prompt/find_actor/`.
- Do not update `ai-hedge-fund-btst`.
- Do not treat a single rescued row as enough evidence for runtime adoption.

## 3. Approaches considered

### Approach A - near-trend-threshold-only recovery validation (**recommended**)

Define a very small recovery rule around rows that barely miss trend classification, then evaluate whether similarly structured rows show better 5D/+15% objective support.

**Pros**

- most directly follows the split board recommendation
- keeps scope narrow and interpretable
- lowest risk of accidentally admitting noisy buckets
- best fit for Alpha/Beta/Gamma fail-closed governance

**Cons**

- may reveal the recoverable pocket is too small to matter
- may end with a justified "do not proceed" outcome

### Approach B - combine near-trend and near-breakout recovery in one cycle

Expand the next cycle to include both threshold-near buckets at once.

**Pros**

- broader search surface
- could uncover a second recoverable pocket faster

**Cons**

- mixes two hypotheses before the first one is proven
- weakens attribution if the cycle succeeds or fails
- increases risk of turning a narrow recovery into search creep

### Approach C - skip recovery and jump to broad trend/breakout refinement

Treat the split board as directional evidence only and move immediately to a wider factor-refinement cycle.

**Pros**

- fastest path to larger-surface experimentation
- might find a bigger alpha pocket if the current recovery signal is too small

**Cons**

- ignores the strongest routing signal we just generated
- likely reintroduces noise before current failure is understood
- less interpretable if later results improve or degrade

## 4. Recommended design

The next cycle should be a **near-trend-threshold recovery validation** with three strict boundaries:

1. recover only rows that are just below trend classification, not all unclassified rows
2. compare the recovered cohort against the current unclassified baseline and the round1 trend surface
3. fail closed unless the recovered cohort shows objective improvement that is both tradeable and repeatable

This is not a production-upgrade design. It is a narrow evidence-building design that answers whether the one recoverable pocket identified by the split board is real enough to deserve further investment.

## 5. Design boundaries

The cycle stays narrow in five ways:

1. `near_trend_threshold` is the only recovery bucket in scope
2. noisy buckets remain explicitly excluded
3. the recovery logic must be deterministic and documented
4. comparison must use the 5D/+15% objective, not generic win-rate proxies
5. the output is a governed recommendation, not a release action

## 6. Proposed component design

### 6.1 Recovery candidate definition

Define a deterministic recovery candidate for rows with:

1. `event_prototype == "unclassified"`
2. `bucket == "near_trend_threshold"`
3. trend and close values just below current round1 trend thresholds
4. no broad relaxation of unrelated breakout or volume requirements

The candidate rule should remain explainable as "recover structurally similar near-trend misses," not "lower thresholds until more rows pass."

### 6.2 Cohort replay / validation artifact

Build an artifact that compares:

1. the recovered `near_trend_threshold` cohort
2. the unrecovered bucket baseline
3. the current `trend_continuation` cohort

For each cohort, evaluate:

1. row count
2. closed-cycle count
3. 15% hit rate
4. mean 2-5d max return
5. beta tradeable rate
6. candidate-source / decision composition

This keeps the next decision grounded in comparable cohort evidence.

### 6.3 Governance verdict artifact

Collapse the cohort replay into one of three governed outcomes:

1. `advance_recovery_validation`
   - if the recovered cohort materially improves objective support and stays tradeable
2. `hold_recovery_too_small_or_noisy`
   - if evidence is too small, unstable, or not meaningfully better
3. `abandon_recovery_line`
   - if the narrow recovery does not justify more work

This makes Gamma's next decision explicit and fail-closed.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- the exact recovery definition
- judging whether uplift is meaningful on the 5D/+15% objective
- determining whether the cohort is still too small to trust

### Beta

Beta owns:

- rebuilding the narrow cohort deterministically
- checking whether recovered rows remain tradeable
- ensuring the rule does not silently expand into a broad threshold relaxation

### Gamma

Gamma owns:

- deciding whether evidence justifies another recovery cycle
- blocking promotion when the cohort is too small or too noisy
- preserving release posture at hold

## 8. Data flow

The next cycle should flow in this order:

1. read the unclassified split board artifact
2. isolate rows assigned to `near_trend_threshold`
3. define the narrow recovery candidate
4. compare recovered vs unrecovered vs current trend cohort
5. synthesize one governance verdict

## 9. Error handling and fail-closed rules

The recovery-validation cycle must fail closed when:

1. the `near_trend_threshold` bucket cannot be reconstructed
2. the recovered cohort drifts beyond the intended narrow definition
3. row counts are too small for meaningful comparison
4. tradeability metrics cannot be computed consistently
5. comparison artifacts disagree on the cohort contents

No fallback should silently treat "one rescued row exists" as sufficient evidence.

## 10. Validation design

Validation for this cycle should prove:

1. the recovered cohort is deterministic
2. the recovered cohort remains narrow
3. recovered rows are compared against both the unrecovered bucket and the trend baseline
4. the verdict artifact can distinguish:
   - meaningful objective improvement
   - too-small / too-noisy evidence
   - recovery-line abandonment

## 11. Promotion rules

This cycle still does **not** promote factors or runtime rules.

Promotion remains blocked until a later cycle demonstrates:

1. objective improvement is real
2. tradeability remains acceptable
3. evidence is large enough to survive Gamma governance

## 12. Expected outcome

If this design works, the next BTST decision becomes much cleaner:

1. either `near_trend_threshold` is a real recoverable alpha pocket and deserves another validation step
2. or it is too small / too weak, and we stop spending time on it

That is better than broadening the search surface before this narrow recovery question is answered.
