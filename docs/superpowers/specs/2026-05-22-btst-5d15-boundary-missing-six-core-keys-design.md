# BTST 5D/+15% Boundary Missing-Six-Core-Keys Design

- **Date:** 2026-05-22
- **Topic:** BTST 5D/+15% next-step design after the boundary contract fill-path cycle
- **Recommended direction:** Trace why `short_trade_boundary` and `layer_b_boundary` snapshots retain only `t0_tail_strength` while the other six round1 core keys are still `None` upstream

## 1. Problem statement

The fill-path cycle closed one uncertainty and exposed a narrower one.

Verified evidence from the live artifact is:

1. `boundary_row_count = 121`
2. `short_trade_boundary = 75 rows`
3. `layer_b_boundary = 46 rows`
4. `fully_repaired_boundary_contract = 0`
5. `partially_repaired_boundary_contract = 121`
6. `irrecoverable_boundary_contract = 0`
7. the only key entering `boundary_context` is `t0_tail_strength`
8. the other six required round1 keys remain `None` upstream:
   - `breakout_freshness`
   - `trend_acceleration`
   - `volume_expansion_quality`
   - `close_strength`
   - `trend_continuation`
   - `short_term_reversal`

That changes the next BTST question again.

It is no longer:

> Can the fill-path rebuild the missing boundary contract?

It is now:

> Why do `short_trade_boundary` and `layer_b_boundary` snapshots reach the offline research surface with six round1 core keys already `None`, while `t0_tail_strength` survives?

This is the most evidence-backed next step because the current cycle proved the repair layer is not the dominant bottleneck. The dominant bottleneck is the **upstream snapshot contract**.

## 2. Goal and non-goals

### Goal

Design one narrow tracing cycle that:

1. follows the six missing core keys from boundary source generation into `selection_snapshot`
2. identifies the exact handoff point where those keys are dropped, never computed, or never attached
3. distinguishes source-level omission from snapshot serialization omission
4. produces a governed decision about whether the next step should be:
   - source-contract fix
   - snapshot-contract fix
   - or continued fail-closed hold

### Non-goals

- Do not reopen fill-path logic itself.
- Do not broaden into general factor-computation refactoring.
- Do not promote any factor into `docs/prompt/find_actor/`.
- Do not update `ai-hedge-fund-btst`.
- Do not claim alpha improvement from tracing this gap.

## 3. Approaches considered

### Approach A - trace `boundary source -> selection_snapshot` only (**recommended**)

Follow the six missing keys across the narrowest proven path:

1. boundary candidate generation
2. selection target attachment
3. snapshot serialization

**Pros**

- matches the strongest live evidence
- keeps scope tightly coupled to the observed defect
- maximizes odds of finding one concrete contract break
- avoids dragging unrelated factor-computation layers into the same cycle

**Cons**

- may reveal the real root cause sits one layer deeper
- could end with another tracing cycle instead of a direct fix

### Approach B - trace boundary source plus factor-computation layer together

Treat the problem as one wider “why are these six keys absent?” investigation spanning generation and scoring layers.

**Pros**

- might find the root cause in one pass
- broader architectural picture

**Cons**

- scope widens immediately
- mixes absence-at-source with absence-in-snapshot
- weakens attribution if multiple omissions coexist

### Approach C - skip tracing and quarantine permanently

Accept that boundary rows are partial-only and keep them outside the factor surface indefinitely.

**Pros**

- smallest engineering cost
- preserves fail-closed posture

**Cons**

- leaves the upstream contract gap unexplained
- gives up on a 121-row structured defect without identifying its origin
- reduces the quality of future research-surface diagnostics

## 4. Recommended design

The next cycle should be a **boundary missing-six-core-keys trace** focused only on:

1. `short_trade_boundary`
2. `layer_b_boundary`
3. the six missing round1 keys
4. the `selection_snapshot` generation path

It should answer four questions:

1. are the six keys absent before `selection_targets` are attached, or only absent once the snapshot is serialized
2. do `short_trade_boundary` and `layer_b_boundary` lose the same keys for the same reason
3. why does `t0_tail_strength` survive while the other six do not
4. should Gamma classify the next action as:
   - `fix_boundary_source_contract`
   - `fix_snapshot_attachment_contract`
   - or `hold_boundary_until_more_context`

This remains a contract-quality and research-surface-integrity cycle, not a factor-promotion cycle.

## 5. Design boundaries

This cycle stays narrow in six ways:

1. only the two boundary sources are in scope
2. only the six missing keys are investigated
3. only the path into `selection_snapshot` is traced
4. the output is a source/attachment diagnosis board, not a runtime change
5. fail-closed remains the default posture
6. no promotion or skill integration can happen in this cycle

## 6. Proposed component design

### 6.1 Missing-key trace helper

Create one helper that, for a boundary row or boundary evaluation payload, reports for each of the six keys:

1. present in source payload
2. present in attached `selection_targets`
3. present in serialized snapshot
4. final trace status

Possible trace statuses:

1. `missing_at_source`
2. `dropped_before_snapshot`
3. `dropped_during_snapshot_serialization`
4. `present_end_to_end`

### 6.2 Boundary source trace board

Build one board comparing `short_trade_boundary` and `layer_b_boundary` across:

1. row count
2. per-key missing status counts
3. keys surviving end-to-end
4. keys missing before snapshot attachment
5. keys lost during snapshot writing

This should make the 75/46 split auditable at the key level, not only at the family level.

### 6.3 Survivor-key contrast board

Build one small contrast board explaining why `t0_tail_strength` survives:

1. where it is sourced from
2. how it differs from the other six keys in the same payload
3. whether its survival is intentional, accidental, or merely inherited from a different upstream field path

### 6.4 Governance diagnosis board

Collapse the trace into one governed recommendation:

1. `fix_boundary_source_contract`
2. `fix_snapshot_attachment_contract`
3. `hold_boundary_until_more_context`

This board should point to the earliest confirmed break, not the loudest downstream symptom.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- confirming the missing-six problem is a research-surface integrity issue, not alpha discovery
- preventing partial-only rows from being misread as latent signal recovery
- judging whether the missing keys are necessary for any future offline ranking reuse

### Beta

Beta owns:

- tracing where each of the six keys should have been attached
- comparing boundary source payloads against serialized snapshot payloads
- identifying whether the defect is source-local or snapshot-attachment-local

### Gamma

Gamma owns:

- deciding whether the next action is a source-contract fix, snapshot-contract fix, or continued hold
- keeping the cycle fail-closed
- preventing this tracing step from widening into general pipeline cleanup

## 8. Data flow

The cycle should run in this order:

1. read the live 121-row boundary cohort
2. reconstruct the corresponding `selection_targets` / snapshot payload slices
3. trace each of the six keys through source, attachment, and serialization
4. summarize by source and by key
5. contrast `t0_tail_strength` with the six missing keys
6. emit one governance diagnosis board

## 9. Error handling and fail-closed rules

This cycle must fail closed when:

1. the same row cannot be traced deterministically across source and snapshot layers
2. key presence differs run-to-run without code changes
3. the source payload cannot be distinguished from snapshot serialization output
4. the diagnosis would require speculative inference rather than concrete payload evidence
5. the result would tempt a runtime promotion without first fixing the upstream contract

If any of these conditions hold, the boundary family remains held outside the factor surface.

## 10. Validation design

Validation for this cycle should prove:

1. the trace helper can distinguish source-missing vs snapshot-dropped keys
2. the six-key trace is deterministic on fixture data
3. `t0_tail_strength` survival is explained by an explicit upstream path, not hand-waving
4. the final diagnosis board can separate:
   - source-contract break
   - snapshot-attachment break
   - unresolved hold

## 11. Promotion rules

This cycle still blocks:

1. runtime BTST profile changes
2. factor promotion into `docs/prompt/find_actor/`
3. `ai-hedge-fund-btst` integration

Only after a later cycle fixes the confirmed upstream break and then re-validates the boundary cohort with historical evidence should any broader promotion be reconsidered.

## 12. Expected outcome

If this design works, the next BTST decision becomes narrower again:

1. either the six missing keys are absent at the boundary source itself
2. or they are dropped when the snapshot is built
3. or the system still lacks enough evidence and should remain held

Any of those outcomes is more useful than continuing to rerun fill-path on rows that currently recover only `t0_tail_strength`.
