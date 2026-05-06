# BTST Admission Edge Recovery Design

## Problem

Recent BTST work improved reporting correctness, corridor governance, and event-catalyst explainability, but the live edge is still constrained by three linked issues:

1. The baseline BTST surface is still negative after fees, with weak-regime performance dragging the whole system down.
2. Admission is now so tight that normal-strength days often produce zero formal executable BTST names.
3. A subset of names can still hit intraday follow-through while failing to hold into the close, which hurts payoff quality even when direction is partially right.

This means the next cycle should not broadly widen the funnel. It should recover a **small, higher-conviction formal surface on normal or strong days**, stay strict in weak regimes, and reduce cases where the system recommends hold-friendly posture for names that only support intraday extraction.

## Current Evidence

### Baseline edge is still negative

- `data/reports/p0_btst_0422_baseline_freeze.json` shows:
  - `selected_close_win_rate = 47.27`
  - `selected_expectation = -0.0448`
  - `post_fee_expectation_low = -0.16`
  - `post_fee_expectation_high = -0.12`
- The same report shows weak-regime breakdown is the largest drag:
  - `close_win_rate = 22.6`
  - `payoff_ratio = 0.93`
  - `relative_profit_contribution = -7502.0`

### Admission is collapsing to zero formal trades

- `outputs/202604/20260430/BTST-LLM-20260429.md` shows:
  - `short_trade_target_count = 21`
  - `short_trade_selected_count = 0`
  - `short_trade_near_miss_count = 0`
  - `short_trade_blocked_count = 3`
  - `execution_eligible_count = 0`
- `data/reports/btst_react_20260426_regime_gate_window3_longrun_stop_summary.md` shows both key gate days (`2026-03-23`, `2026-03-26`) ended with `BTST 择日门控 = none` and `buy_order_count = 0`.

### Prior shrinkage and holding posture can be too punitive or mismatched

- `data/reports/p3_btst_historical_prior_quality_audit.json` shows downgrade reasons dominated by:
  - `sample_small_n4_lt_5`
  - `sample_small_n3_lt_5`
  - `sample_too_small_n2_lt_3`
  - `low_close_positive_rate`
- `data/reports/p4_btst_prior_shrinkage_eval.json` shows average prior compression:
  - `avg_raw_high_hit_rate = 0.923333 -> avg_shrunk_high_hit_rate = 0.756667`
  - `avg_raw_close_positive_rate = 0.886667 -> avg_shrunk_close_positive_rate = 0.693333`
- `data/reports/btst_selected_outcome_proof_latest.md` shows a selected path with:
  - `next_high_hit_rate_at_threshold = 1.0`
  - `next_close_positive_rate = 0.0`
  - recommendation to expand carryover cohort rather than keep relaxing the selected frontier

## Goals

1. Recover a small but real formal BTST execution surface on normal or strong days without reopening weak-regime losses.
2. Make historical-prior shrinkage more adaptive so genuinely strong low-sample names are not over-flattened.
3. Align preferred entry mode and holding posture with realized close-retention quality so payoff ratio improves alongside win rate.

## Non-Goals

1. Do not broadly lower default thresholds or widen candidate-pool size.
2. Do not re-open weak or risk-off regimes for formal BTST execution.
3. Do not roll out multi-day continuation expansion as the primary fix in this cycle.
4. Do not replace recent event-catalyst work; this cycle should complement it.

## Alternatives Considered

### 1. Broad threshold relaxation

Lower select and near-miss thresholds across the board to restore trade count.

**Rejected** because current evidence says the weak regime is already loss-making, and broad relaxation would likely increase false positives faster than it restores edge.

### 2. Carryover-first continuation expansion

Focus the whole cycle on T+2/T+4 follow-through expansion and let selected admission stay tight.

**Deferred** because the latest carryover and selected-outcome evidence still says the system first needs better next-day admission and holding alignment before expanding continuation.

### 3. Focused admission-edge recovery

Use a bounded three-part fix:

1. regime-aware admission recovery,
2. adaptive prior shrinkage,
3. holding-posture calibration.

**Recommended** because it attacks the three evidence-backed bottlenecks directly without broadening the whole BTST surface.

## Recommended Approach

### Phase 1: Regime-aware admission recovery

Keep weak and risk-off days tight, but stop letting normal-strength days collapse into zero executable names solely because static rank tightening or caps become too punitive.

This phase should:

1. keep `shadow_only` / `halt` behavior conservative,
2. allow limited relief on `normal_trade` / `aggressive_trade`,
3. reuse the already computed BTST regime payload instead of re-deriving regime decisions per candidate.

### Phase 2: Adaptive prior shrinkage

Keep shrinkage conservative for weak-quality names, but reduce over-compression for low-sample names that already show strong close-continuation evidence under favorable regimes.

This phase should:

1. preserve strict handling for poor or weak-regime priors,
2. add adaptive shrinkage strength by evidence count, execution quality, and regime,
3. expose the chosen shrinkage policy clearly in explainability and metrics payloads.

### Phase 3: Entry-mode payoff calibration

Only keep `confirm_then_hold_breakout` for names whose prior evidence supports close retention, not just intraday highs.

This phase should:

1. demote hold-friendly posture to `intraday_confirmation_only` or `next_day_breakout_confirmation` when close retention is weak,
2. enrich reporting notes so the execution contract matches the new posture,
3. keep carryover-style hold bias behind explicit evidence rather than implicit optimism.

## Architecture

This cycle should stay inside the existing BTST target-evaluation stack:

1. **Regime admission layer** — use the BTST regime gate payload plus profile knobs to control rank tightening and rank-cap relief by regime.
2. **Prior calibration layer** — compute adaptive shrinkage and effective prior metrics once, then thread that result through target evaluation.
3. **Execution posture layer** — map calibrated prior metrics to preferred entry mode and reporting notes.

The pipeline should remain profile-based and replay-testable. No hidden widening of the formal execution surface is allowed.

## Data Flow

The intended path is:

`market_state -> btst_regime_gate payload -> rank tightening / cap policy -> calibrated historical prior -> selected/near-miss decision -> preferred_entry_mode -> reporting / validation artifacts`

Required invariants:

1. Weak and risk-off regimes must remain conservative even if prior evidence looks strong.
2. Adaptive shrinkage must never increase trust in names with poor close-retention evidence.
3. Hold-oriented entry modes must require close-retention support, not just intraday hit rate.

## Error Handling and Safe Defaults

1. Missing regime payload defaults to the current conservative behavior.
2. Missing historical prior keeps the current neutral/no-relief path.
3. Missing close-retention evidence must downgrade holding posture rather than silently preserving `confirm_then_hold_breakout`.
4. Any adaptive uplift must remain profile-gated and explainable in payloads.

## Validation Strategy

Validation should happen in four steps:

### 1. Unit and decision-path regression

Cover:

1. weak-regime admission stays strict,
2. normal/aggressive regime can preserve a small formal surface,
3. adaptive shrinkage relaxes only the intended low-sample strong priors,
4. poor close-retention priors lose hold-friendly posture.

### 2. Replay-window comparison

Compare baseline vs recovery profile on complete BTST windows, focusing on:

1. `selected_close_win_rate`
2. `selected_payoff_ratio`
3. `next_close_positive_rate`
4. `next_high_hit_rate`
5. count of formal execution-eligible names

### 3. Regime-sliced audit

Any improvement must hold with:

1. no weak-regime regression,
2. improved or preserved normal/strong-day formal trade count,
3. no material payoff deterioration from posture changes.

### 4. Rollout gate

No default profile change should ship until:

1. weak-regime contribution is less negative or unchanged under strict gating,
2. normal/strong-day formal trade count recovers from repeated zero-executable outcomes,
3. payoff ratio does not deteriorate while win rate improves or remains stable.

## Success Criteria

This cycle is successful if all of the following hold:

1. BTST still blocks weak regimes appropriately.
2. Normal or strong days stop collapsing so frequently to zero formal executable names.
3. Shrinkage no longer over-flattens strong low-sample close-continuation cases.
4. Hold-oriented execution notes appear only when prior evidence supports them.
5. Replay evidence shows non-regressive win rate with stable or better payoff.

## Failure Criteria

This cycle should be considered unsuccessful if any of the following dominate:

1. formal trade count improves only because weak-regime names leak back in,
2. shrinkage relaxation increases false positives without improving payoff,
3. hold-oriented posture remains attached to names with poor close retention,
4. improvements appear only in isolated windows with no regime stability.

## Expected Implementation Surfaces

Likely code areas:

1. `src/screening/market_state_helpers.py`
2. `src/execution/daily_pipeline.py`
3. `src/targets/profiles.py`
4. `src/targets/short_trade_target_profile_data.py`
5. `src/targets/short_trade_target_rank_helpers.py`
6. `src/targets/short_trade_target_prior_helpers.py`
7. `src/targets/short_trade_target.py`
8. `src/targets/short_trade_target_evaluation_helpers.py`
9. `src/paper_trading/_btst_reporting/entry_mode_utils.py`
10. `scripts/analyze_btst_selected_outcome_proof.py`
11. `tests/test_btst_prior_shrinkage.py`
12. `tests/targets/test_target_models.py`
13. `tests/execution/test_phase4_execution.py`
14. `tests/test_analyze_btst_selected_outcome_proof_script.py`

## Assumptions

Because the user was unavailable during brainstorming, this spec assumes approval for the following priority order:

1. regime-aware admission recovery,
2. adaptive prior shrinkage,
3. entry-mode payoff calibration.
