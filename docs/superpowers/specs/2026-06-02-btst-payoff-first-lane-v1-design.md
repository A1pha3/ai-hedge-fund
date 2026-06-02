# BTST — Payoff-first Review Lane v1 (Design)

Date: 2026-06-02

## Goal
Introduce a **parallel, non-executable review lane** that is explicitly optimized for the user’s BTST objective:

- Within 5 trading days after entry (from **T+1 open**), maximize the probability of exceeding **+15%** upside.

This lane must be:
- Low-risk (does not change current execution decisions by default)
- Auditable (inputs trace back to selection_snapshot + historical prior)
- Measurable (offline realized evaluation can prove uplift)

## Evidence / Motivation
Offline monthly diagnostics show the current system is primarily optimizing short-horizon continuation (T+1 close / T+2) rather than 5D payoff:

- 202605 selected: win_rate(next_close>0) ≈ 66.8% but hit_5d_15 ≈ 28.1%
- 202604 selected: hit_5d_15 ≈ 23.0%

These are far below the target ~55% for `5D/+15%`.

## Non-goals (v1)
- Do **not** change `selected` / `near_miss` decision boundaries.
- Do **not** auto-place orders or change position sizing.
- Do **not** introduce new live data dependencies.

## Definitions
### Primary objective metric (truth source)
We reuse the existing realized definition from:
- `scripts/generate_btst_realized_prices.py`

Key field:
- `max_high_t1_t5_from_open`: max(high(T+1..T+5)) / open(T+1) - 1

Define:
- `hit_5d_15 = (max_high_t1_t5_from_open >= 0.15)`

### Proxy priors available in current reporting
The BTST reporting stack already computes a **next-day** opportunity prior in:
- `src/paper_trading/_btst_reporting/historical_prior.py`

Notable fields:
- `next_high_hit_rate_at_threshold` using `OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD` (currently 0.02)
- reliability signals derived from `evaluable_count`, same-ticker samples, etc.

v1 uses these priors as *proxies* to build a payoff review lane, then validates the lane against the 5D realized metric offline.

## Proposed approaches
### Approach A (Recommended): Reporting-only payoff review lane
Add a new section to BTST brief / doc bundle:

- Name: **Payoff-first review (non-executable)**
- Input: current-day `selected_entries` + `near_miss_entries` (post history enrichment)
- Output: `payoff_review_entries` sorted by `payoff_score`

Key property:
- Every entry is explicitly tagged as **review-only** (not an order list).

### Approach B: Two-stage selection (selected split)
Keep selection logic, but split `selected` into:
- execution-primary (continuation)
- payoff-review (needs confirmation)

This is intentionally deferred until Approach A proves stable uplift.

### Approach C: Inject payoff into ranking/decision
High-risk and overfit-prone. Only consider after strong walk-forward evidence.

## Design (v1 details)
### Data flow (where it fits)
Integrate right after historical enrichment in the brief builder:

- `src/paper_trading/_btst_reporting/brief_builder.py`
  - after `_build_btst_brief_history_context(...)` returns enriched entries
  - compute `payoff_review_entries` and attach to the brief payload

Rendering surfaces (v1):
- next-day trade brief (`BTST-YYYYMMDD-TRADE-BRIEF.md`)
- doc bundle checklist should include a short semantic disclaimer linking to the payoff lane as **review-only**

### Payoff scoring (simple + explainable)
A lightweight, auditable score:

```
payoff_score =
  w_hit * prior_next_high_hit_rate
+ w_rel * reliability_score
- w_pen * penalty_score
```

Where:
- `prior_next_high_hit_rate` := `historical_prior.next_high_hit_rate_at_threshold` (0..1)
- `reliability_score` increases with `evaluable_count` and same-ticker samples
- `penalty_score` is a sum of boolean risk tags already produced by reporting classifiers (e.g. payoff_divergence_risk)

Notes:
- v1 deliberately avoids adding new model features or touching the target stack.
- Weights are *configuration* (defaults chosen conservatively), tuned only via offline walk-forward.

### Output contract (per entry)
Each payoff review entry should include:
- `payoff_score` (0..1)
- `payoff_components`: `{prior_hit_rate, evaluable_count, reliability_bucket, penalty_tags}`
- `review_semantics`: fixed string like `"review_only"`
- `promotion_hint`: optional text (e.g. "only promote after intraday confirmation")

### Default limits
- Keep small: `payoff_review_max_entries` default 3–5 (avoid flooding the operator)

## Validation plan (offline, required before rollout promotion)
1) Build month-scale evaluation for `payoff_review_entries` vs baseline `selected`:
   - win_rate(next_close>0)
   - hit_5d_15 (primary)
   - mean/max distributions for `max_high_t1_t5_from_open`
   - regime buckets (ensure uplift isn’t confined to a single regime)

2) Minimum acceptance criteria:
   - in ≥2 months, payoff_topN shows stable uplift in `hit_5d_15` (e.g. +5pp) vs baseline selected
   - no obvious explosion of risk tags / gap-down exposure

## Testing plan (when implementing)
- Unit tests for payoff scoring helper (deterministic inputs → score/components)
- Snapshot tests for brief rendering:
  - payoff lane appears
  - entries are explicitly labeled review-only
  - does not alter the existing formal selected list

## Rollout
- Start as report-only (always non-executable).
- Only after offline evidence: consider Approach B (selected split) behind an env gate.

## Open decision (needs explicit confirmation)
Which primary objective should the payoff lane optimize long-term?
- A) `hit_5d_15` (recommended; matches user’s stated objective)
- B) maximize expected `max_high_t1_t5_from_open`
- C) mixed constraint (hit-rate floor + maximize expected value)
