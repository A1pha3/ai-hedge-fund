# BTST 5D15 Boundary Source Contract Repair Design

## Problem statement

The completed `boundary missing-six-core-keys` trace cycle shows a split contract failure inside the boundary cohort:

- `breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, and `close_strength` are not dead. They appear in `short_trade_boundary` source-side nested metrics (`short_trade_boundary_metrics`) for 75 rows and in attached / snapshot `short_trade.metrics_payload` for all 121 rows, but they are never surfaced into the current round1 row-builder layers.
- `trend_continuation` and `short_term_reversal` are the real upstream gap. Across all 121 traced boundary rows they are absent from:
  - boundary source payloads,
  - attached `short_trade.metrics_payload`,
  - snapshot `short_trade.metrics_payload`.

This means the next subproject should stay narrow: repair the boundary **source contract** for those two genuinely missing keys, rerun the same trace, and only then decide whether a second cycle should lift the already-surviving four nested-only keys into the row-builder surface.

This cycle remains strictly fail-closed:

- no promotion into `docs/prompt/find_actor/`
- no `ai-hedge-fund-btst` integration
- no alpha-improvement claim until a later validated backtest cycle

## Goal

Make `trend_continuation` and `short_term_reversal` available in the boundary source contract used by `short_trade_boundary` / `layer_b_boundary` replay artifacts, then re-run the existing boundary trace to confirm `missing_everywhere` for those two keys drops to zero.

## Non-goals

- Do **not** lift the four existing nested-only keys into the row-builder surface in this cycle.
- Do **not** widen scope to selection snapshot / explainability / research-row extraction changes.
- Do **not** change rollout gates or selection thresholds.
- Do **not** treat this as a factor-promotion cycle.

## Current code surfaces

### Factor generation

- `src/targets/short_trade_target_signal_snapshot_helpers.py`
  - `_resolve_snapshot_scores()` already computes:
    - `short_term_reversal`
    - `trend_continuation`
  - These keys exist conceptually in the target-signal layer today.

### Snapshot payload shaping

- `src/targets/short_trade_target_snapshot_payload_helpers.py`
  - `build_short_trade_target_snapshot_payload()` currently surfaces the familiar boundary metrics (`breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, `close_strength`, `sector_resonance`, `catalyst_freshness`) but not the two missing keys.

### Boundary source entry construction

- `src/execution/daily_pipeline_candidate_helpers.py`
  - `build_short_trade_boundary_metrics_payload()` currently serializes:
    - `breakout_freshness`
    - `trend_acceleration`
    - `volume_expansion_quality`
    - `catalyst_freshness`
    - `close_strength`
    - `sector_resonance`
  - It does not intentionally surface `trend_continuation` / `short_term_reversal`.

- `src/execution/daily_pipeline_short_trade_diagnostics_helpers.py`
  - qualified boundary entries are written with `short_trade_boundary_metrics`.

### Downstream verification already exists

- `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
  - already traces source / attached / snapshot availability and can be reused unchanged as the verifier for this cycle.

## Approaches considered

### 1. Recommended: narrow source-contract repair

Add `trend_continuation` and `short_term_reversal` to the source-side boundary metrics payload where `short_trade_boundary_metrics` is built, using the same signal/snapshot contract that already computes them upstream.

**Pros**
- Smallest blast radius
- Directly targets the only keys still marked `missing_everywhere`
- Keeps the trace artifact meaningful as a before/after verifier
- Preserves fail-closed governance

**Cons**
- Does not make the four nested-only keys visible to the round1 row-builder surface yet

### 2. Broader “source + surface” repair

Repair the two source-missing keys and simultaneously lift all six keys into the row-builder surface / explainability contract.

**Pros**
- One larger cycle could make the whole six-key family visible end to end

**Cons**
- Harder to attribute what actually fixed the contract
- Larger risk surface across source, attachment, snapshot, and row extraction
- Violates the current recommendation to keep the next cycle narrow

### 3. Diagnostic reinterpretation only

Change the trace or governance interpretation without repairing the source contract, e.g. treat nested metrics as “good enough” and move on to surface lifting.

**Pros**
- Fastest to implement

**Cons**
- Leaves `trend_continuation` / `short_term_reversal` genuinely absent
- Produces optimistic diagnostics without closing the real upstream gap
- Not acceptable for fail-closed BTST governance

## Recommended design

Use **Approach 1**.

The next cycle should repair only the boundary source contract for `trend_continuation` and `short_term_reversal`, then rerun the existing trace script unchanged. That gives the cleanest causal read:

1. If `missing_everywhere` for those two keys falls to zero, the source-contract repair worked.
2. The trace will then show whether they become:
   - nested-only,
   - surfaced,
   - or lost later.
3. Only after that should a separate design decide whether to lift the four pre-existing nested-only keys into the row-builder surface.

## Component design

### 1. Extend short-trade snapshot payload to expose the two keys

Update `src/targets/short_trade_target_snapshot_payload_helpers.py` so the target snapshot payload includes:

- `trend_continuation`
- `short_term_reversal`

These values already exist in `signal_snapshot`, so this should be a contract extension, not a new factor computation.

### 2. Extend boundary metrics payload builder

Update `src/execution/daily_pipeline_candidate_helpers.py` so `build_short_trade_boundary_metrics_payload()` explicitly includes:

- `trend_continuation`
- `short_term_reversal`

The source of truth should remain the existing snapshot / raw-candidate metric inputs already passed into the builder.

Design rule:

- Prefer direct values already present on `snapshot`
- Then preserve any equivalent values arriving via `raw_candidate_metrics`
- Do not synthesize new fallback math inside the boundary builder

This keeps the source contract aligned with the existing target stack instead of creating a second calculation path.

### 3. Leave downstream trace logic unchanged

Do **not** change `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py` as part of the source-contract repair unless the payload field names themselves must change.

That script is the verifier, not the repair surface.

### 4. Verification loop

After the source-contract repair:

1. run the focused regression suite for the touched builders and the boundary trace script
2. rerun `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
3. confirm:
   - `missing_everywhere` for `trend_continuation` and `short_term_reversal` becomes `0`
   - governance no longer depends on those two keys being absent at source
   - any remaining failure is now cleanly attributable to later layers

## File-level plan boundary

### Expected code changes

- `src/targets/short_trade_target_snapshot_payload_helpers.py`
  - expose the two keys in the snapshot payload
- `src/execution/daily_pipeline_candidate_helpers.py`
  - extend `build_short_trade_boundary_metrics_payload()`

### Expected test changes

- existing target / boundary metrics payload tests near the touched builders
- `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
  - use as the regression proof that `missing_everywhere` for the two keys is removed after the repair

### Expected live verification artifact

- refresh `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json`
- refresh `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- if the repair behaves as expected, write a new Chinese interpretation note in `docs/prompt/find_actor_methord/`

## Error handling and failure posture

- If the two keys are still absent after the repair attempt, keep governance fail-closed.
- If the keys appear only in nested metrics and not on the surface, that is acceptable for this cycle; the goal of this cycle is to eliminate `missing_everywhere`, not to promote surface visibility.
- If payload field names differ between source families, prefer explicit contract normalization over silent fallbacks.

## Testing strategy

### Unit / contract checks

- assert the boundary metrics payload builder emits both keys when present upstream
- assert the builder preserves explicit upstream values instead of recomputing them

### Regression checks

- rerun the focused trace bundle:
  - `tests/test_btst_boundary_missing_core_key_trace_helpers.py`
  - `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
  - `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`

### Live acceptance check

- rerun the live boundary trace
- accept the cycle only if `trend_continuation` and `short_term_reversal` no longer contribute to `missing_everywhere`

## Acceptance criteria

This design is successful only if all of the following are true:

1. `trend_continuation` and `short_term_reversal` are present in the repaired boundary source contract.
2. The live trace no longer reports those two keys as `missing_everywhere`.
3. No BTST runtime promotion occurs from this cycle alone.
4. The next design decision is cleaner: either stop after source repair, or start a separate surface-lift cycle for the remaining nested-only keys.
