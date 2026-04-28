# BTST Formal Truth Next-Cycle Design

## Problem

The last BTST tightening cycle improved formal selection quality, but the system still has three unresolved gaps that directly limit win rate and payoff quality:

1. Formal execution truth does not yet propagate cleanly through all BTST-facing reports and cards.
2. Candidate-pool false negatives still cluster in the Layer-A liquidity corridor lane.
3. T+2/T+3 continuation quality has evidence, but not enough release discipline to safely expand default execution behavior.

Recent evidence shows the first issue is the highest-priority live risk. Weekly artifact replay now says 2026-04-23 and 2026-04-24 should become `conservative + halt` with zero formal executable names, and 2026-04-24 should demote weak-prior ticker `600522` from selected to rejected. Operator-facing BTST summaries must reflect that exact truth. If reports leak raw selected rows back into execution-facing output, later improvements to recall or continuation quality will be partially wasted.

## Goals

1. Make formal executable truth the single source of truth for all BTST followup briefs, priority boards, premarket cards, and control-tower summaries.
2. Preserve the recently tightened formal precision gains while preparing the next recall and continuation experiments.
3. Keep corridor recall and T+2/T+3 expansion tightly gated so they improve capture/payoff without reintroducing broad false positives.

## Non-Goals

1. Do not broadly widen formal thresholds again.
2. Do not turn Layer-A corridor work into a top300 cutoff tuning project.
3. Do not expand prepared-breakout or carryover continuation into the default execution surface without fresh closed-loop evidence.
4. Do not change unrelated UI, auth, or infrastructure concerns.

## Current Evidence

### Formal precision and reporting mismatch

- The latest weekly artifact replay confirms:
  - `2026-04-23` -> `conservative + halt`, zero formal executable names.
  - `2026-04-24` -> `conservative + halt`, zero formal executable names.
  - `2026-04-22` additionally demotes `002028` from `selected` to `near_miss`.
  - `2026-04-24` additionally demotes weak-prior `600522` from `selected` to `rejected`.
- `btst_nightly_control_tower_latest.json` still reflects operator-facing summaries that can mention names from older selected-style surfaces. This is the next highest-risk inconsistency to remove.

### Corridor recall remains the largest missed-opportunity bucket

- `btst_candidate_pool_recall_dossier_latest.json` still reports:
  - `dominant_stage = candidate_pool_truncated_after_filters`
  - `frontier_verdict = far_below_cutoff_not_boundary`
- The highest-priority recall names remain corridor / truncation names such as `300683`, `688796`, `688383`, `301188`, and rebucket challenger `301292`.
- The deepest-corridor probe reservation is already landed, so the next step is not more broad diagnostics; it is a strict release path.

### Continuation quality still needs stricter proof gates

- `btst_carryover_peer_promotion_gate_latest.json` shows:
  - `ready_tickers = []`
  - focus peer `300620` is still `await_peer_t_plus_2_close`
- `btst_prepared_breakout_cohort_latest.json` shows:
  - `stable_selected_relief_candidate_count = 0`
  - `selected_frontier_candidate_count = 0`
  - only `300505` acts as a reference anchor
- This means continuation expansion can matter for payoff, but it should stay behind a gate-first workflow.

## Recommended Approach

### Phase 1: Formal executable truth propagation (primary task)

Treat `selection_targets` plus execution blocking flags as the only truth for execution-facing BTST reporting. The followup brief, priority board, premarket execution card, opening watch card, and control-tower digest must derive their formal BTST rows from the same execution-eligible interpretation:

- `selected` is not enough by itself.
- Halt / shadow-only / blocked rows must not be rendered as formal executable BTST names.
- Weak-prior demotions and runtime-enforced gate outcomes must survive every reporting layer.

If a day resolves to zero formal executable BTST names, the reports must say exactly that. No success-shaped fallback is allowed.

### Phase 2: Corridor strict-release lane (secondary task)

Once reporting truth is fixed, turn Layer-A corridor false negatives into a strict release lane:

- only from the already-governed corridor validation pack
- only from the retained deepest-corridor / tractable focus rows
- never by broadening default pool size or cutoff thresholds

This phase is about catching names the current formal surface never sees, while keeping release scope small enough to preserve precision.

### Phase 3: Carryover payoff expansion behind peer-promotion gates (tertiary task)

After the first two phases are stable, continue improving payoff ratio by expanding only the T+2/T+3 names that pass the carryover peer gate:

- no promotion while `ready_tickers` remains empty
- no default expansion while anchors still show “observed without positive expectation”
- preference for closed-loop same-family or same-source proof that improves both next-close and T+2 close behavior

## Detailed Design

### Architecture boundaries

The next cycle should keep one mainline and two gated side lanes:

1. **Mainline**: formal executable reporting truth
2. **Gated lane A**: corridor strict-release
3. **Gated lane B**: carryover payoff expansion

The mainline owns correctness for operator-facing output. The gated lanes exist only to improve future capture and payoff after correctness is restored.

### Data flow

The authoritative path should be:

`daily_pipeline / runtime -> selection_targets + p2/p3/p5/p6 state -> BTST reporting builders -> followup brief / cards / control tower`

Required invariants:

1. Reporting builders never re-upgrade a row that runtime or target evaluation already downgraded.
2. Historical prior overlays may enrich explanation, but not overturn execution eligibility.
3. Upstream shadow or corridor rows can stay visible in research/shadow sections, but must not bleed into formal executable sections unless explicitly promoted by the same truth path.

### Error handling

1. Missing or empty formal executable rows should render explicit zero-state output, not implicit fallback rows.
2. Missing corridor evidence should keep the lane in validation/shadow mode.
3. Missing carryover closed-loop evidence should keep continuation expansion pending, not partially enabled.

### Validation model

The cycle should be considered successful only if all three conditions hold:

1. **Correctness**: report artifacts match execution truth for the known weekly replay days.
2. **Precision preservation**: the tightened formal-selected surface does not regress.
3. **Future upside preserved**: corridor and continuation work remain available as gated release surfaces instead of being abandoned or prematurely widened.

## Files and Surfaces Expected To Change

### Primary implementation surfaces

- `src/execution/daily_pipeline.py`
- `src/paper_trading/runtime_run_helpers.py`
- `src/paper_trading/runtime_session_helpers.py`
- `scripts/btst_latest_followup_utils.py`
- `src/paper_trading/_btst_reporting/entry_builders.py`
- `src/paper_trading/_btst_reporting/brief_builder.py`
- `src/paper_trading/_btst_reporting/priority_board.py`
- `src/paper_trading/_btst_reporting/premarket_card.py`
- `scripts/run_btst_nightly_control_tower.py`

### Secondary corridor surfaces

- `src/screening/candidate_pool_shadow_helpers.py`
- `src/screening/candidate_pool_shadow_payload_helpers.py`
- corridor governance scripts under `scripts/run_btst_candidate_pool_*` and `scripts/analyze_btst_candidate_pool_*`

### Tertiary continuation surfaces

- `scripts/analyze_btst_carryover_peer_promotion_gate.py`
- `scripts/analyze_btst_carryover_aligned_peer_harvest.py`
- `scripts/generate_btst_tplus2_continuation_promotion_gate.py`

## Test Strategy

Write or extend regression tests in this order:

1. Reporting correctness tests for halt / zero-executable days.
2. Reporting correctness tests for weak-prior demotion persistence.
3. Weekly artifact replay contract tests for `2026-04-20`, `2026-04-22`, `2026-04-23`, `2026-04-24`.
4. Corridor strict-release tests that prove only governed lane rows can advance.
5. Carryover gate tests that prove no expansion happens while readiness is still pending.

Expected verification shape:

- `2026-04-23` and `2026-04-24` report zero formal executable names.
- `002028` stays demoted on `2026-04-22`.
- `600522` stays demoted on `2026-04-24`.
- `2026-04-20` stays unchanged.
- corridor validation remains strict and does not widen default formal admission.
- carryover continuation stays gated until peer-proof status improves.

## Trade-Offs

### Why this order

This ordering intentionally favors **correctness before expansion**:

- Fixing reporting truth first improves real-world decision quality immediately.
- Corridor strict-release second targets the biggest missed-opportunity source without opening the whole funnel.
- Carryover expansion third focuses on payoff after precision and recall hygiene are under control.

### Alternatives rejected for now

1. **Broad threshold relaxation**: too likely to reopen weak names.
2. **Top300 cutoff tuning**: contradicted by current recall dossier evidence.
3. **Prepared-breakout expansion first**: current cohort evidence is too thin outside the `300505` anchor.

## Assumptions

Because the user was unavailable during brainstorming, this spec assumes approval for the recommended priority order:

1. formal executable reporting truth
2. corridor strict-release
3. T+2/T+3 carryover payoff expansion

If the user later changes that order, the implementation plan should be revised before work starts on phases 2 or 3.
