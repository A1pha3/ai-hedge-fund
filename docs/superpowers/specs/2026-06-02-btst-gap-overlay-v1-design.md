# BTST 0422 P7 — Gap Overlay v1 (Design)

Date: 2026-06-02

## Goal
Reduce BTST T+1 execution risk from **gap-down opens** (negative opening gap vs prior close) in a **low-risk, auditable** way.

v1 is intentionally **report-only** (soft policy surfaced to execution) and **env-gated**, so we can shadow/rollout without breaking existing behavior.

## Evidence (offline scorecards, high_confidence top5/day)
- 202605 baseline: win_rate(next_close>0)≈54.4%, expectancy≈+0.87%
- 202605 counterfactual (gap>=-0.5%): win≈72.1%, expectancy≈+3.38% (sample ~halved)
- 202604 baseline is materially worse; gap filter improves only marginally ⇒ gap overlay cannot replace **regime gate**.

Conclusion: gap overlay is a **Phase-4 execution overlay**, best paired with market regime gating.

## Non-goals (v1)
- Do **not** enforce order deletion / position sizing automatically (needs T+1 open price source + e2e tests).
- Do **not** introduce new external market data dependencies.

## Design
### Policy semantics
Given `gap = open / prev_close - 1` (T+1 open vs T close):
- If `gap <= -halt_threshold`: **no-trade** (halt)
- Else if `gap <= -warn_threshold`: **reduced / confirmation-only**
- Else: proceed with existing confirmation logic

### Configuration (env)
Implemented as env-gated modes:
- `BTST_0422_P7_GAP_OVERLAY_MODE` = `off` | `report` | `enforce`
  - `off`: no policy rendered (default)
  - `report`: render policy text (v1 default rollout mode)
  - `enforce`: reserved for future execution-layer enforcement
- `BTST_0422_P7_GAP_WARN_THRESHOLD` default `0.005` (0.5%)
- `BTST_0422_P7_GAP_HALT_THRESHOLD` default `0.01` (1.0%)

Thresholds are stored as absolute positive values; trigger uses `gap <= -threshold`.

## Implementation status (already in repo)
### Reporting surface
- `src/paper_trading/_btst_reporting/premarket_card.py`
  - Adds a `Gap overlay (BTST 0422 P7/<mode>)...` guardrail line into `global_guardrails` when mode != off.

### Replayability / persistence
- `src/paper_trading/runtime_session_helpers.py`
- `src/research/artifacts.py`

Both persist into `btst_0422_flags`:
- `p7_gap_overlay_mode`
- `p7_gap_warn_threshold`
- `p7_gap_halt_threshold`

This ensures later replays and audits can reconstruct exactly what policy was in effect.

### Tests
- `tests/test_generate_btst_premarket_execution_card_script.py::test_analyze_btst_premarket_execution_card_p7_gap_overlay_guardrail_toggle`
  - Asserts mode=off hides the guardrail
  - Asserts mode=report renders the guardrail with injected thresholds

## Rollout / verification
1) Start with `BTST_0422_P7_GAP_OVERLAY_MODE=report` only.
2) Track trigger frequency and counterfactual benefit using realized tooling / monthly scorecards.
3) Only after stable data source + tests: consider `enforce` behavior in paper trading.

