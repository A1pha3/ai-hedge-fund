# BTST Trend Gate Confirmation Mining Design

- **Date:** 2026-05-23
- **Topic:** BTST 5D/+15% factor mining inside the current best trend gate
- **Recommended direction:** keep the winning narrow catalyst gate fixed and mine second-layer confirmation conditions inside it

## 1. Problem statement

The latest BTST trend-gate work already established a strong boundary:

1. The best current narrow gate is `trend_acceleration_top_20pct + next_open_return <= 3% + candidate_source == catalyst_theme + close_strength < 0.90`.
2. That gate still has attractive payoff, but only `11` deduped closed cycles and `45.45%` 5D/+15% hit rate.
3. Widening the base gate already diluted quality, so broadening thresholds is not the right next move.

The highest-value actionable question is therefore:

> Inside the current best narrow gate, which second-layer confirmation conditions improve deduped hit rate and payoff without collapsing sample quality or violating beta tradability?

## 2. Approaches considered

### Approach A — keep collecting new trade dates only

Pros:

- lowest implementation risk
- consistent with the current intake-board conclusion

Cons:

- little code-side progress is available today
- does not answer whether a stronger confirmation rule already exists in the current sample

### Approach B — mine second-layer confirmation factors inside the fixed narrow gate (**recommended**)

Pros:

- directly targets the user goal of improving win rate and payoff
- stays inside the best-known alpha surface instead of restarting the search
- keeps attribution clean because the base gate is unchanged

Cons:

- current sample is still small, so results remain research-only until more closed cycles arrive

### Approach C — widen or rewrite the base gate

Pros:

- larger sample size immediately

Cons:

- the latest threshold-grid evidence already shows quality dilution
- mixes multiple changes and weakens attribution

## 3. Recommended design

Build a new analysis surface that:

1. reuses the existing trend-gate data collection pipeline
2. fixes the current best base gate as the input universe
3. evaluates a controlled list of confirmation predicates on top of that base gate
4. ranks candidates by deduped hit rate, mean 2-5D max return, closed-cycle count, and tradability
5. emits a conservative decision: keep collecting samples, hold the base gate, or escalate the strongest confirmation candidate to later OOS review

This design is intentionally narrow. It does not change runtime trading logic, rollout rules, or the BTST skill yet.

## 4. Component boundaries

### 4.1 New script

Create `scripts/analyze_btst_5d_15pct_trend_gate_confirmation_grid.py`.

Responsibilities:

- collect BTST rows using the same helper chain as current trend-gate scripts
- filter to the fixed base gate
- evaluate a small default confirmation catalog over `trend_continuation`, `volume_expansion_quality`, `breakout_freshness`, and `t0_tail_strength`
- summarize each candidate with deduped metrics
- choose the best research candidate and output JSON/Markdown artifacts

### 4.2 Tests

Create `tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py`.

Responsibilities:

- verify candidate comparison uses deduped metrics
- verify decision logic stays fail-closed when sample size or quality is insufficient
- verify the CLI writes artifact files successfully

## 5. Validation design

Validation must stay evidence-first:

1. run focused tests for the new confirmation-grid script
2. run the existing trend-gate regression tests to ensure the new script does not break neighboring tooling
3. treat any strong candidate as research-only unless later OOS and rollout checks pass

Success criteria for this phase:

1. the script produces stable, explainable rankings
2. the best candidate is selected from deduped metrics
3. output artifacts make it obvious whether the next step is `collect_samples`, `hold_base_gate`, or `promote_confirmation_candidate_to_oos_review`

## 6. Alpha / Beta / Gamma responsibilities

### Alpha

- define the confirmation catalog
- judge hit-rate/payoff uplift and overfit risk
- write future Chinese factor documentation only after validation passes

### Beta

- ensure confirmation candidates remain executable under the `next_open_return <= 3%` entry constraint
- prevent cosmetic hit-rate gains that rely on non-tradeable rows

### Gamma

- preserve fail-closed research posture
- require later OOS and rollout review before any promotion

## 7. Promotion rules

No BTST skill update and no `docs/prompt/find_actor/` promotion doc should be created in this phase unless a later cycle proves:

1. deduped hit rate reaches the research target line
2. mean 2-5D max return remains at or above the target
3. sample size is adequate
4. OOS and rollout gates pass

Until then, the new artifact remains a mining and triage tool.
