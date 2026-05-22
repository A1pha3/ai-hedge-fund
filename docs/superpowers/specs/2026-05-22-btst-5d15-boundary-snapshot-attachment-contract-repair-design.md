# BTST 5D15 Boundary Snapshot Attachment Contract Repair Design

## Problem statement

The completed boundary source-contract repair closed the real upstream gap for `trend_continuation` and `short_term_reversal`, but it did **not** finish the broader boundary visibility problem.

The remaining diagnosis is now narrower:

- `breakout_freshness`
- `trend_acceleration`
- `volume_expansion_quality`
- `close_strength`

These four keys still show up as the remaining attachment-side visibility problem in the boundary trace. They are not missing conceptually:

- they already exist on `TargetEvaluationResult` top-level fields in `src/targets/models.py`
- they are populated by `build_short_trade_target_result()` in `src/targets/short_trade_target_evaluation_helpers.py`
- they are also present in nested `metrics_payload` built by `src/targets/short_trade_metrics_payload_builders.py`

That means the next subproject should stay narrow again: repair the **snapshot / attachment surface contract** so these four keys are explicitly visible on serialized `selection_targets[*].short_trade` surfaces inside `selection_snapshot.json` and `selection_target_replay_input.json`, then rerun the existing boundary trace unchanged.

This cycle remains strictly fail-closed:

- no promotion into `docs/prompt/find_actor/`
- no `ai-hedge-fund-btst` integration
- no alpha-improvement claim
- no rollout or gate relaxation

## Goal

Make `breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, and `close_strength` survive into the serialized short-trade target **surface contract** used by selection artifacts, then confirm the boundary trace no longer depends on nested-only visibility for those four keys.

## Non-goals

- Do **not** change factor computation in the short-trade evaluator.
- Do **not** widen scope to all selection-target fields.
- Do **not** reinterpret the trace by teaching it to flatten nested metrics instead of fixing the contract.
- Do **not** revisit the completed source-contract repair for `trend_continuation` / `short_term_reversal`.
- Do **not** change BTST target thresholds, committee logic, or execution gates.

## Current code surfaces

### Evaluator already computes and exposes the four keys

- `src/targets/models.py`
  - `TargetEvaluationResult` already has top-level fields for:
    - `breakout_freshness`
    - `trend_acceleration`
    - `volume_expansion_quality`
    - `close_strength`

- `src/targets/short_trade_target_evaluation_helpers.py`
  - `build_short_trade_target_result()` already assigns those fields directly onto the `short_trade` result.
  - The same function also attaches:
    - nested `metrics_payload` via `_build_short_trade_metrics_payload()`
    - nested `explainability_payload` via `_build_short_trade_explainability_payload()`

- `src/targets/short_trade_metrics_payload_builders.py`
  - `_build_short_trade_core_metrics_payload()` already includes the same four keys inside nested `metrics_payload`.

### Artifact builders persist selection targets

- `src/research/artifacts.py`
  - `build_selection_snapshot()` writes:
    - `selection_targets=dict(plan.selection_targets or {})`
  - `build_selection_target_replay_input()` also writes:
    - `selection_targets=dict(plan.selection_targets or {})`
  - `FileSelectionArtifactWriter.write_for_plan()` persists both models to:
    - `selection_snapshot.json`
    - `selection_target_replay_input.json`

- `src/research/models.py`
  - both `SelectionSnapshot` and `SelectionTargetReplayInput` declare:
    - `selection_targets: dict[str, DualTargetEvaluation]`

### The boundary verifier already defines the failing contract

- `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
  - `_extract_surface_payload()` only treats these layers as surface-visible:
    - `target`
    - `short_trade`
    - `short_trade.explainability_payload`
  - `_extract_nested_metrics_payload()` reads:
    - `short_trade.metrics_payload`

So if a key survives only in nested `metrics_payload`, the verifier is correct to classify it as an attachment/snapshot contract issue rather than a source-computation issue.

## Approaches considered

### 1. Recommended: narrow artifact-surface contract repair

Add a focused serialization / normalization step in `src/research/artifacts.py` so the four keys are guaranteed to appear on the serialized `short_trade` surface in both artifact families:

- `selection_snapshot.json`
- `selection_target_replay_input.json`

**Pros**

- smallest blast radius after the completed source repair
- directly matches the current governance diagnosis: `fix_snapshot_attachment_contract`
- keeps the existing trace script unchanged as the verifier
- avoids adding a second metric computation path

**Cons**

- leaves some duplication between top-level `short_trade` fields and nested `metrics_payload`

### 2. Broader result-model / router refactor

Refactor the short-trade result stack so all artifact consumers use one canonical flattened serializer for every target field.

**Pros**

- cleaner long-term architecture
- could eliminate future drift between top-level fields and nested payloads

**Cons**

- much larger scope
- harder to verify causally
- too much risk for the next narrow boundary cycle

### 3. Diagnostic workaround in the trace consumer

Change the boundary trace to treat nested `metrics_payload` as “surface enough” for these four keys.

**Pros**

- fastest change

**Cons**

- hides a real contract gap
- weakens fail-closed governance
- makes diagnostics optimistic instead of corrective

## Recommended design

Use **Approach 1**.

The next cycle should repair the serialized short-trade **surface contract**, not the evaluator math and not the trace consumer. The repair should guarantee that when these four keys are available on the in-memory `TargetEvaluationResult`, they are still visible on the persisted `selection_targets[*].short_trade` objects that downstream artifact consumers reconstruct.

That gives the cleanest verification path:

1. the evaluator stays unchanged
2. the artifact builder becomes the explicit repair surface
3. the boundary trace stays unchanged
4. any remaining nested-only diagnosis after this repair is real, not an artifact of incomplete serialization

## Component design

### 1. Add a focused selection-target surface serializer

Introduce a narrow helper in `src/research/artifacts.py` that normalizes `plan.selection_targets` for artifact writing.

Required behavior:

- preserve the existing structure of `DualTargetEvaluation`
- preserve `metrics_payload` and `explainability_payload`
- guarantee these four keys are present on serialized `short_trade` when they are available from either:
  - top-level `TargetEvaluationResult`
  - or, conservatively, nested `short_trade.metrics_payload`

Design rule:

- never invent values
- never compute new metrics here
- only lift already-existing values onto the serialized short-trade surface

### 2. Use the same serializer in both artifact builders

Apply the same normalization in:

- `build_selection_snapshot()`
- `build_selection_target_replay_input()`

This keeps `selection_snapshot.json` and `selection_target_replay_input.json` contract-aligned instead of fixing only one artifact family.

### 3. Keep evaluator logic unchanged

Do **not** change:

- `build_short_trade_target_result()`
- `_build_short_trade_core_metrics_payload()`
- committee / threshold / gate code

Those layers already provide the values. The problem is the surface contract observed by downstream artifact consumers.

### 4. Keep boundary trace logic unchanged

Do **not** change `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py` in this cycle unless the serialization format itself forces a field-name correction.

That script is the acceptance verifier for the contract repair.

## File-level plan boundary

### Expected code changes

- `src/research/artifacts.py`
  - add a small helper for serializing selection-target short-trade surfaces
  - apply it in both `build_selection_snapshot()` and `build_selection_target_replay_input()`

### Expected test changes

- `tests/research/test_selection_artifact_writer.py`
  - add focused artifact-writer regressions proving the four keys are visible on serialized `selection_targets[*].short_trade`
  - cover both artifact families or the shared helper path

- `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
  - extend the synthetic regression surface so a repaired serialized target no longer leaves the four keys as nested-only

### Expected verification artifacts

- rerun `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
- refresh local ignored reports under `data/reports/`
- if the outcome is clean enough, write a new Chinese diagnosis note under `docs/prompt/find_actor_methord/`

## Error handling and failure posture

- If any of the four keys is absent from both the top-level result and nested metrics payload, keep it absent and let the trace fail closed.
- If one artifact family is repaired but the other is not, treat the cycle as incomplete.
- If lifting these four keys unexpectedly changes unrelated serialized target fields, stop and narrow the serializer further.
- If the trace still shows nested-only after the repair, assume there is another downstream serialization or reconstruction step that still drops the surface fields.

## Testing strategy

### Artifact writer contract checks

- prove `FileSelectionArtifactWriter.write_for_plan()` persists the four keys on serialized `selection_targets[*].short_trade`
- verify both:
  - `selection_snapshot.json`
  - `selection_target_replay_input.json`

### Boundary regression checks

- keep the completed source-repair regression intact
- add a new repaired-surface regression proving these four keys are no longer nested-only once the artifact surface contract is fixed

### Focused verification bundle

- `tests/research/test_selection_artifact_writer.py`
- `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
- `tests/test_btst_boundary_missing_core_key_trace_helpers.py`
- any existing artifact-writer engine/runtime regression that directly covers `write_for_plan()`

### Live acceptance check

- rerun the boundary trace artifact builder
- accept the cycle only if these four keys no longer drive the attachment/snapshot repair diagnosis when present in the local artifact sample
- if the local sample remains zero-row, rely on focused synthetic regressions and keep the live note explicitly diagnostic-only

## Acceptance criteria

This design is successful only if all of the following are true:

1. `selection_snapshot.json` and `selection_target_replay_input.json` both expose the four keys on serialized `selection_targets[*].short_trade` surfaces.
2. The boundary trace no longer needs to classify those four keys as nested-only for repaired artifact rows.
3. The existing source-contract repair for `trend_continuation` / `short_term_reversal` remains intact.
4. No trace-consumer shortcut or gate relaxation is introduced.
5. The cycle remains diagnosis-only and does not qualify for BTST factor/runtime promotion.
