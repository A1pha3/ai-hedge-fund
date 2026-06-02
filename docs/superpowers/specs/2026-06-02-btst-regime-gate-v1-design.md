# BTST Regime Gate v1 — Design (2026-06-02)

## Goal
Make market regime gating **observable, replayable, and auditable** for BTST decisions, so “bad months” (e.g. 202604) can be explained and exposure can be reduced **before** execution—then apply gap overlay as a secondary execution-layer guardrail.

This spec is intentionally **low-risk**: v1 focuses on **field persistence + reporting semantics** and uses existing repo logic; enforcement changes are gated and rolled out gradually.

## Evidence (from 202604/202605 scorecards, high_confidence top5/day)
- 202604 baseline: n=65, win_rate(next_close>0)=41.5%, expectancy≈+0.03%, hit_5d_15=32.3%
- 202605 baseline: n=90, win_rate=54.4%, expectancy≈+0.87%, hit_5d_15=26.7%

**Gap overlay helps, but is not sufficient for bad months:**
- 202605 gap>=-0.5%: n=43, win≈72.1%, expectancy≈+3.38% (big improvement, but halves opportunities)
- 202604 gap>=-0.5%: n=34, win≈47.1%, expectancy≈+1.07% (improvement, but still weak)

Conclusion: gap overlay is an execution filter; v1 must add **regime-aware gating** so we can reduce exposure in weak/choppy regimes.

### Evidence appendix: observed gate distribution from truth-source snapshots
The rendered Markdown in `outputs/202605` is not a truth source; the auditable truth source is `data/reports/**/selection_artifacts/*/selection_snapshot.json`.

I scanned **681** `selection_snapshot.json` files in-repo and filtered by `trade_date` month (202604 vs 202605). Note these snapshots may include multiple experiment runs; the goal here is to verify that the gate is real, persisted, and sometimes affects execution.

**Gate counts**

| month | aggressive_trade | normal_trade | shadow_only | halt | other |
| --- | ---: | ---: | ---: | ---: | ---: |
| 202604 | 69 | 34 | 30 | 13 | 0 |
| 202605 | 8 | 5 | 19 | 13 | 0 |

**Execution surface aggregates** (from `universe_summary.buy_order_count` + target summaries)

| month | gate | snapshots | buy_orders_total | buy_orders_zero | buy_orders_nonzero | selected_total | near_miss_total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 202604 | aggressive_trade | 69 | 26 | 47 | 22 | 281 | 182 |
| 202604 | normal_trade | 34 | 37 | 7 | 27 | 117 | 141 |
| 202604 | shadow_only | 30 | 0 | 30 | 0 | 109 | 107 |
| 202604 | halt | 13 | 0 | 13 | 0 | 31 | 82 |
| 202605 | shadow_only | 19 | 2 | 18 | 1 | 148 | 92 |
| 202605 | halt | 13 | 8 | 9 | 4 | 40 | 112 |
| 202605 | aggressive_trade | 8 | 7 | 4 | 4 | 29 | 57 |
| 202605 | normal_trade | 5 | 10 | 0 | 5 | 22 | 60 |

Interpretation:
- Gate states `shadow_only/halt` exist and are persisted.
- In many cases (`shadow_only/halt` in 202604) `buy_order_count` is consistently cleared to 0, suggesting enforcement is wired.
- However, there are also `halt` snapshots with non-zero buy orders (e.g. 202605 aggregates). v1 rollout should treat this as a diagnosis target: enforcement may be conditional, derived-vs-explicit gate may differ, or older runs didn’t clear orders.

## Existing building blocks (reuse)
Already present in the repo:
- `src/screening/market_state.py`: builds `MarketState` from index + breadth + limits + flows.
- `src/screening/market_state_helpers.py`: derives BTST regime gate payload via `classify_btst_regime_gate_from_market_state(...)`.
- Paper-trading artifacts already persist `selection_snapshot.json` with `market_state` (breadth_ratio, daily_return, limit_up/down, position_scale, regime_gate_level, reasons).
- `scripts/generate_btst_doc_bundle.py` already renders market gate/control tower lines (regime_gate_level, breadth_ratio, daily_return, limits, position_scale).

So v1 should **not invent a new regime model**—it should **persist and surface** the existing one consistently across artifacts.

## Problem statement
For 202604/202605 monthly audits based on `data/reports/btst_full_report_YYYYMMDD.json` (rule-based high_confidence), we lack structured `market_state` fields, which blocks:
- regime stratification (risk_off/crisis vs normal)
- root-cause explanation for “bad months”
- repeatable rollout checks and regression tests

Meanwhile, paper-trading selection artifacts have market state, but it is not guaranteed to be attached to rule-based reports.

## Design (v1)
### 1) Define a **minimal persisted market_state contract**
Persist the following fields whenever we generate BTST daily artifacts (rule reports and paper-trading snapshots):
- `breadth_ratio`
- `daily_return`
- `limit_up_count`, `limit_down_count`
- `position_scale`
- `regime_gate_level` (e.g. normal / risk_off / crisis)
- `regime_gate_reasons` (reason codes)

Optional (nice-to-have, but not required for v1):
- `style_dispersion`, `regime_flip_risk`, `northbound_flow_days`

### 2) Persist a **derived btst_regime_gate payload**
Where `market_state` exists, derive and persist a gate payload:
- `gate`: one of `{normal_trade, aggressive_trade, shadow_only, halt}`
- `profile_hint`
- `reason_codes`
- `metrics` snapshot

Implementation should reuse:
- `classify_btst_regime_gate_from_market_state(market_state)`

### 3) Reporting semantics: make gate effects explicit
In premarket execution card / checklist:
- Render the control tower state (raw_trade_bias vs effective_trade_bias) and explicitly attribute veto/limit ownership (e.g. `market_gate`).
- Treat “gate says aggressive_trade but execution still confirmation_only” as **a feature**: execution bias may be more conservative than market gate.

### 4) Verification (offline-first)
Add a repeatable monthly analysis that:
- loads daily artifacts
- stratifies by `gate` / `regime_gate_level`
- reports win_rate, expectancy, 5D hit-rate

This is required for rollout: we should see whether weak regimes dominate loss months like 202604.

## Rollout plan
1) Shadow-only persistence: write the new fields into artifacts + docs, no enforcement change.
2) Backfill a small historical window (e.g. 202604/202605) if the truth source exists.
3) Only after stratified evidence: consider enforcement (shadow_only/halt) in paper trading.

## Success criteria
- Every BTST daily artifact that drives decisions includes `market_state` + derived `btst_regime_gate` OR a clear “not available” indicator.
- Monthly scorecards can be stratified by regime, and 202604 degradation can be attributed to weak regimes rather than unexplained noise.
- Report text never claims single-ticker certainty without a persisted, auditable basis.

## Out of scope
- Changing the underlying regime classifier thresholds.
- Adding new external data dependencies for v1.
- Hard enforcement in live execution (requires separate spec + test plan).
