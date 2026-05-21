# Active Baseline Bridge Design

- **Date:** 2026-05-21
- **Topic:** BTST rollout evidence unblock
- **Recommended direction:** Build a governed active-baseline evidence bridge that compares winner `trial_index=602` against the recorded active runtime `btst_precision_v2` using existing validated BTST-v2 artifacts, without publishing a manifest or reopening broad search

## 1. Problem statement

The rollout recheck pipeline is implemented and the focused test suite passes, but live verification is blocked by a concrete evidence gap:

1. the active runtime baseline recorded in `session_summary.json` is `btst_precision_v2`
2. the historical source artifact used by the comparison stage only contains paired `comparison_summary` / `baseline_verdicts` for `momentum_optimized` and `default`
3. the pack stage can be fed an explicit non-published baseline snapshot, but the comparison stage still cannot compute a governed winner-versus-active-baseline result

This is not a plumbing failure. It is a missing evidence contract between two already-governed artifacts.

The next BTST question is therefore:

> How do we produce a trustworthy, fail-closed paired baseline comparison for the actual active runtime `btst_precision_v2` without violating the current `hold` / no-publication governance?

## 2. Goal and non-goals

### Goal

Design a narrow evidence-bridge cycle that:

1. makes the active runtime baseline explicit and reproducible
2. converts existing BTST-v2 research/runtime artifacts into the comparison contract required by the rollout recheck
3. lets Gamma decide whether the missing evidence is now sufficient for the blocked rollout task to resume

### Non-goals

- Do not publish `btst_latest_optimized_profile.json`.
- Do not update `ai-hedge-fund-btst`.
- Do not broaden candidate search beyond winner `602` and the existing challengers.
- Do not rerun a full new optimization cycle.
- Do not write a promotion note under `docs/prompt/generate_file/`.

## 3. Approaches considered

### Approach A - rerun a fresh paired historical backtest for `btst_precision_v2` versus `602`

Generate a brand-new paired historical comparison from scratch.

**Pros**

- strongest direct evidence path
- no need to bridge heterogeneous artifact shapes

**Cons**

- highest runtime cost
- widens scope from “bridge missing evidence” to “run a new validation program”
- unnecessary if existing BTST-v2 evidence is already sufficient

### Approach B - build an active-baseline evidence bridge from existing BTST-v2 artifacts (**recommended**)

Use the recorded active runtime metadata plus `btst_v2_objective_alignment_primary.json` to synthesize a governed baseline sidecar that matches the rollout recheck comparison contract.

**Pros**

- narrowest unblocking move
- preserves the current `hold` boundary
- reuses already validated runtime evidence instead of inventing a new search or rerun cycle
- fastest path back to the blocked rollout verification

**Cons**

- requires careful contract design so the bridge is not looser than the downstream comparison artifact
- only as good as the existing BTST-v2 evidence coverage

### Approach C - downgrade the rollout recheck to compare only against `momentum_optimized` / `default`

Ignore the actual active runtime and continue with the baselines already present in the source file.

**Pros**

- cheapest implementation path

**Cons**

- violates the intent of the rollout recheck design
- answers the wrong question
- could produce a misleading governance decision

## 4. Recommended design

The next cycle should be an **active-baseline evidence bridge**:

1. **winner under test:** `trial_index=602`
2. **baseline to bridge:** `btst_precision_v2`
3. **source of truth for active baseline identity:** `session_summary.json -> optimization_profile_resolution`
4. **source of truth for active baseline historical evidence:** `data/reports/btst_v2_objective_alignment_primary.json`
5. **governance posture:** remain `hold`, no manifest publication, no BTST skill promotion

The bridge exists only to answer the blocked rollout question with the correct baseline. It should not become a generic profile-conversion system or a hidden second optimization pipeline.

## 5. Design boundaries

This cycle stays narrow in four ways:

1. it adds only the missing active-baseline evidence layer
2. it does not change the winner/challenger selection logic
3. it does not change the rollout decision policy
4. it ends when the blocked rollout verification can resume with governed paired evidence

## 6. Proposed component design

### 6.1 Active baseline snapshot artifact

Build a compact snapshot from `optimization_profile_resolution` that records:

1. `profile_name = btst_precision_v2`
2. the exact `profile_overrides`
3. `source_type`, `source_path`, and `validated_by`
4. release posture and guardrails proving the snapshot is input-only, not publication

This artifact should replace the temporary ad hoc manifest workaround with a governed, reproducible baseline input.

### 6.2 Baseline metrics bridge artifact

Read `btst_v2_objective_alignment_primary.json` and normalize the relevant BTST-v2 metrics into the comparison contract expected by the rollout recheck:

1. candidate-side baseline metrics for win rate, payoff, expectancy, coverage, and risk
2. explicit provenance back to the BTST-v2 source file
3. an evidence-quality flag that says whether the bridge is strong enough for rollout governance

If the BTST-v2 source lacks a required metric, the bridge must fail closed instead of filling gaps with assumptions.

### 6.3 Winner-versus-active-baseline comparison merge

Merge:

1. winner `602` evidence from the param-search result
2. bridged `btst_precision_v2` baseline evidence
3. challenger context from the existing rerun pack

The merged artifact should look like a normal rollout comparison input so the existing decision stage can consume it without loosening validation.

## 7. Alpha / Beta / Gamma responsibilities

### Alpha

Alpha owns:

- deciding which BTST-v2 metrics are sufficient to represent win-rate and payoff behavior
- checking whether the bridge preserves statistical meaning instead of just matching field names
- documenting why the bridged baseline is or is not strong enough for rollout governance

### Beta

Beta owns:

- wiring the active-baseline snapshot and bridge artifacts
- keeping the bridge output contract compatible with the rollout comparison stage
- ensuring no manifest publication or runtime mutation happens during the bridge

### Gamma

Gamma owns:

- deciding whether the bridged evidence is good enough to unblock rollout verification
- forcing `fallback_measurement_repair` if the bridge still leaves unacceptable evidence gaps
- preserving the `hold` boundary unless later paired evidence truly clears it

## 8. Data flow

The bridge should flow in this order:

1. read the blocked rollout task context and current rerun pack
2. extract the active runtime identity from `session_summary.json`
3. normalize BTST-v2 baseline evidence from `btst_v2_objective_alignment_primary.json`
4. merge winner and baseline evidence into the rollout comparison contract
5. retry the rollout verification with the bridged active baseline

## 9. Error handling and fail-closed rules

The bridge must fail closed when:

1. the active runtime identity cannot be recovered from `session_summary.json`
2. the BTST-v2 source file is missing or malformed
3. required win-rate or payoff metrics are absent
4. the bridge cannot prove provenance from the active runtime source
5. the merged comparison would silently change the meaning of existing rollout fields

## 10. Validation design

Validation for this cycle should prove:

1. the active baseline snapshot exactly matches the recorded runtime identity
2. the bridge emits only metrics that can be traced to the BTST-v2 source file
3. the merged comparison artifact is accepted by the existing rollout decision stage
4. the blocked rollout task can either:
   - resume with real paired baseline evidence, or
   - fail closed with a clearer `fallback_measurement_repair` reason

## 11. Promotion rules

Promotion remains unchanged:

1. this bridge is an evidence-unblocking step, not a release
2. no BTST factor or runtime change is promoted without substantial historical validation
3. only after the rollout chain finishes with a governed release-ready result may anything be promoted into `ai-hedge-fund-btst`
4. only then may a dated Chinese note be written under `docs/prompt/generate_file/`

## 12. Expected artifacts

If implementation is approved later, this design should produce:

1. an active baseline snapshot artifact
2. a BTST-v2 baseline metrics bridge artifact
3. a merged rollout comparison artifact for `602` versus `btst_precision_v2`
4. either a resumed rollout decision or a narrower measurement-repair blocker
