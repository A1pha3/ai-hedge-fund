# BTST Early Runner Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the current early_runner_v1 from a research/shadow artifact into a v4-aligned staged lane with theme radar, real T+1 confirmation, formal runtime integration, shared walk-forward calibration, and daily production artifacts.

**Architecture:** Keep `scripts/analyze_btst_early_runner_v1.py` as the artifact entrypoint, but stop growing it as a monolith. Reuse existing catalyst-theme diagnostics, intraday metric builders, short-trade candidate diagnostics, and shared walk-forward helpers under `src/` so early runner becomes an extension of the current BTST chain rather than a parallel system.

**Tech Stack:** Python 3.11+, pandas, existing BTST selection snapshots, `src/screening/market_state_helpers.py`, `src/screening/strategy_scorer.py`, `src/execution/daily_pipeline*.py`, `src/targets/router.py`, `src/backtesting/walk_forward.py`, `pytest`.

---

## Current State Snapshot

Implemented now:

- `scripts/analyze_btst_early_runner_v1.py` already builds `feature_time_map`, `universe_filter`, `limit_rule_profile`, `early_runner_pre_score`, proxy `confirm_score`, ledgers, failure log, validation payload, and acceptance checklist.
- `scripts/generate_reports_manifest.py` already refreshes `btst_early_runner_v1_latest.{json,md}` and exposes `early_runner_summary`.
- `scripts/run_btst_nightly_control_tower.py` and related helpers already surface `early_runner_summary` into nightly payload, delta, and markdown.
- Focused regression tests already exist in `tests/test_analyze_btst_early_runner_v1_script.py`, `tests/test_generate_reports_manifest_script.py`, and `tests/test_btst_control_tower_scripts.py`.

Still missing relative to the v4 docs:

- Theme / industry radar layer (`hot_theme_board`, `theme_breadth_score`, `theme_leader_count`, `theme_midfield_candidates`).
- Real T+1 30-60 minute confirmation from intraday bars and ticks.
- Formal promotion path into runtime short-trade execution under `src/execution/` and `src/targets/`.
- Shared walk-forward calibration using `src/backtesting/walk_forward.py` instead of the current script-local month grid.
- Board-specific limit rules beyond the current minimal hardcoded profile.
- Standalone daily watchlist / priority / second-entry artifacts.
- Evidence that first-entry lane is actually viable; current latest artifact is still `shadow_only` with zero first-entry samples.

## File Map

Existing files to modify:

- `scripts/analyze_btst_early_runner_v1.py` — current research/shadow artifact builder; should become orchestration-only over time.
- `scripts/generate_reports_manifest.py` — refresh and manifest summary integration.
- `scripts/run_btst_nightly_control_tower.py` — nightly payload and delta visibility.
- `src/execution/daily_pipeline.py` — current short-trade runtime orchestration and post-market payload assembly.
- `src/execution/daily_pipeline_short_trade_diagnostics_helpers.py` — current short-trade candidate diagnostics builder and the most direct formal integration seam.
- `src/execution/daily_pipeline_catalyst_diagnostics_helpers.py` — existing catalyst theme candidate generation; likely theme-radar anchor.
- `src/targets/router.py` — current `selection_targets` assembly and short-trade-only promotion path.
- `src/screening/strategy_scorer.py` — existing intraday bars / ticks metric builder that can power early-runner confirmation.
- `src/backtesting/walk_forward.py` — shared rolling / expanding window builder and promotion summary helpers.
- `tests/test_analyze_btst_early_runner_v1_script.py` — current early-runner research tests.
- `tests/test_generate_reports_manifest_script.py` — manifest integration tests.
- `tests/test_btst_control_tower_scripts.py` — nightly control-tower integration tests.

New files to create:

- `src/targets/early_runner_theme_radar.py` — theme / industry radar computations and summaries.
- `src/targets/early_runner_intraday_confirmation.py` — real T+1 confirmation inputs and confirm-score builder.
- `src/targets/early_runner_runtime_adapter.py` — convert confirmed early-runner entries into a runtime-consumable short-trade supplemental input.
- `src/backtesting/early_runner_walk_forward.py` — adapter over shared walk-forward windows for early-runner parameter evaluation.
- `scripts/generate_btst_early_runner_daily_tables.py` — emit standalone daily watchlist / priority / second-entry artifacts.
- `tests/test_btst_early_runner_theme_radar.py`
- `tests/test_btst_early_runner_intraday_confirmation.py`
- `tests/test_btst_early_runner_runtime_adapter.py`
- `tests/test_btst_early_runner_walk_forward.py`
- `tests/test_generate_btst_early_runner_daily_tables.py`

## Priority Order

Execution rule for this plan:

- Do not start formal runtime promotion before the theme radar, intraday confirmation, and board-rule expansion are in place.
- Do not claim rollout progress until fresh artifacts are regenerated and acceptance blockers are reevaluated.
- Keep every new capability fail-closed: missing intraday data, missing theme context, or non-tradeable market gate must keep entries in research / shadow visibility.

### P0: Stabilize the Early Runner Contract

**Why first:** The current logic lives mostly in one script. Extending theme radar, intraday confirmation, runtime promotion, and walk-forward calibration directly inside that script will make the later phases brittle.

**Files:**

- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Create: `src/targets/early_runner_theme_radar.py`
- Create: `src/targets/early_runner_intraday_confirmation.py`
- Create: `src/targets/early_runner_runtime_adapter.py`
- Create: `src/backtesting/early_runner_walk_forward.py`
- Test: `tests/test_analyze_btst_early_runner_v1_script.py`

- [ ] Extract script-local theme, confirmation, runtime-adapter, and walk-forward helper seams into dedicated `src/` modules without changing current artifact output.
- [ ] Keep `scripts/analyze_btst_early_runner_v1.py` responsible only for report discovery, row orchestration, artifact assembly, and file output.
- [ ] Preserve existing field names, ledger labels, acceptance checklist keys, and manifest-facing schema so downstream consumers do not break.
- [ ] Add regression assertions that the current latest-path output contract is unchanged before any new feature fields are turned on.
- [ ] Verify with `uv run pytest tests/test_analyze_btst_early_runner_v1_script.py -q`.

**Done when:** The current research/shadow behavior still passes existing tests, but new feature work can be added in small isolated modules instead of the script body.

### P1: Add Theme / Industry Radar Before Stock-Level Scoring

**Why second:** This is the largest conceptual gap versus the v4 design. Right now early runner starts from stock rows; v4 requires a market-first theme radar to tell the system where momentum is broad enough to matter.

**Files:**

- Create: `src/targets/early_runner_theme_radar.py`
- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Modify: `src/execution/daily_pipeline_catalyst_diagnostics_helpers.py`
- Modify: `scripts/generate_reports_manifest.py`
- Test: `tests/test_btst_early_runner_theme_radar.py`
- Test: `tests/test_analyze_btst_early_runner_v1_script.py`

- [ ] Build a theme-radar summary from existing catalyst theme candidates, selection snapshots, and per-row industry/theme fields.
- [ ] Emit `hot_theme_board`, `theme_breadth_score`, `theme_leader_count`, and `theme_midfield_candidates` into the early-runner analysis payload.
- [ ] Thread theme-radar outputs into `early_runner_pre_score` only through T-close-safe fields; missing radar data must reduce confidence instead of silently defaulting bullish.
- [ ] Extend manifest summary so the latest early-runner snapshot exposes theme-radar health and top active themes alongside current watchlist / priority / second-entry counts.
- [ ] Add tests that verify a single isolated leader does not qualify as a hot theme board and that multi-name theme breadth can promote a theme into radar output.
- [ ] Verify with `uv run pytest tests/test_btst_early_runner_theme_radar.py tests/test_analyze_btst_early_runner_v1_script.py -q`.

**Done when:** The analysis artifact contains a real theme-first layer, and stock-level early-runner rows can explain which theme / industry context they came from.

### P2: Replace Proxy Confirm Score with Real T+1 Intraday Confirmation

**Why third:** The current `confirm_score` is based on next-day daily outcome proxies. That is useful for research triage but not enough for a production-grade confirmation lane.

**Files:**

- Create: `src/targets/early_runner_intraday_confirmation.py`
- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Modify: `src/screening/strategy_scorer.py`
- Test: `tests/test_btst_early_runner_intraday_confirmation.py`
- Test: `tests/test_analyze_btst_early_runner_v1_script.py`

- [ ] Reuse existing intraday bars / ticks access from `src/screening/strategy_scorer.py` to compute early-runner-specific confirmation inputs: open-gap quality, 30-minute VWAP hold / reclaim, volume rhythm, and first-hour tradable liquidity.
- [ ] Keep `feature_time_map` authoritative by marking every new confirmation feature as `t_plus_1_open` or `t_plus_1_30m` and blocking them from `pre_score`.
- [ ] Replace the current proxy `confirm_score` path with a two-stage implementation: real intraday confirmation when data is available, proxy fallback only for historical research backfill, and explicit provenance for which path was used.
- [ ] Add failure-reason classification for `vwap_reclaim_failed`, `intraday_volume_exhaustion`, and `theme_continuation_failed` so postmortems are specific.
- [ ] Add tests for minute-data missing, VWAP hold pass, over-gap rejection, and low-liquidity intraday rejection.
- [ ] Verify with `uv run pytest tests/test_btst_early_runner_intraday_confirmation.py tests/test_analyze_btst_early_runner_v1_script.py -q`.

**Done when:** `confirm_score` is no longer a pure next-day daily proxy, and the artifact can distinguish between pre-score, intraday confirm, and outcome evaluation fields.

### P3: Expand Universe and Limit-Rule Fidelity to Execution Grade

**Why now:** Formal promotion is unsafe while the board / risk-warning / new-listing handling is still the MVP version.

**Files:**

- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Create: `src/targets/early_runner_runtime_adapter.py`
- Modify: `src/backtesting/trading_constraints.py`
- Test: `tests/test_analyze_btst_early_runner_v1_script.py`
- Test: `tests/test_btst_early_runner_runtime_adapter.py`

- [ ] Expand `limit_rule_profile` to distinguish main board, ChiNext, STAR market, risk-warning names, and IPO no-limit days instead of treating non-standard regimes as a generic exclusion.
- [ ] Keep `universe_filter` reason-coded so artifacts can explain whether a row was excluded by ST/risk warning, suspension, board mismatch, listing-age rule, or liquidity.
- [ ] Align cost profile logging with actual trading-constraint defaults and make stamp-duty assumptions explicit instead of inheriting an old silent default.
- [ ] Add tests that verify risk-warning names receive the correct limit profile, IPO no-limit windows do not pass the first-entry lane by accident, and board-specific gap-to-limit handling remains deterministic.
- [ ] Verify with `uv run pytest tests/test_btst_early_runner_runtime_adapter.py tests/test_analyze_btst_early_runner_v1_script.py -q`.

**Done when:** The artifact can support execution-grade tradeability decisions without relying on a simplified board model.

### P4: Wire Confirmed Early Runner Entries into the Formal Short-Trade Runtime

**Why fourth:** This is the highest-value missing feature, but it should only happen after the signal contract is trustworthy. The correct integration seam is the existing short-trade candidate diagnostics path, not a sidecar output.

**Files:**

- Create: `src/targets/early_runner_runtime_adapter.py`
- Modify: `src/execution/daily_pipeline_short_trade_diagnostics_helpers.py`
- Modify: `src/execution/daily_pipeline.py`
- Modify: `src/targets/router.py`
- Modify: `src/research/artifacts.py`
- Test: `tests/test_btst_early_runner_runtime_adapter.py`
- Test: `tests/test_btst_control_tower_scripts.py`

- [ ] Convert confirmed early-runner entries into a runtime-consumable supplemental short-trade input instead of leaving them as analysis-only rows.
- [ ] Feed that adapter output into `build_short_trade_candidate_diagnostics(...)` through the same candidate path the system already uses for short-trade boundary / shadow release decisions.
- [ ] Gate runtime promotion on `btst_regime_gate`, theme-radar readiness, intraday confirm score threshold, and tradeability checks; any failed gate must keep the row in shadow or research visibility.
- [ ] Extend `src/targets/router.py` so a confirmed early-runner promotion lands inside `selection_targets` with explicit candidate source and reason codes rather than bypassing the normal routing model.
- [ ] Update research artifact rendering so promoted early-runner entries can be audited alongside other short-trade candidates and not disappear into a runtime-only path.
- [ ] Add end-to-end tests for: no promotion under `halt`, no promotion under `shadow_only`, successful promotion under `normal_trade`, and reason-code preservation into `selection_targets`.
- [ ] Verify with `uv run pytest tests/test_btst_early_runner_runtime_adapter.py tests/test_btst_control_tower_scripts.py -q`.

**Done when:** Early runner is part of the formal BTST runtime path under explicit gates, rather than being visible only in control-tower reporting.

### P5: Replace Script-Local Month Grid with Shared Walk-Forward Calibration

**Why fifth:** The current month-level grid summary is useful as a placeholder, but rollout decisions should use the same shared walk-forward framework the rest of the repo already trusts.

**Files:**

- Create: `src/backtesting/early_runner_walk_forward.py`
- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Modify: `src/backtesting/walk_forward.py`
- Test: `tests/test_btst_early_runner_walk_forward.py`

- [ ] Build an early-runner evaluator over `build_walk_forward_windows(...)`, `run_walk_forward(...)`, and `summarize_walk_forward(...)` rather than maintaining a parallel month-only selector.
- [ ] Evaluate the current early-runner parameters across rolling and expanding windows, including after-cost expectancy, unfilled rate, drawdown floor, and regime-split stability.
- [ ] Persist the chosen parameter set, selection frequency, and rollout blockers in the early-runner artifact so promotion gates use the shared summary instead of a script-private payload.
- [ ] Keep the old month-grid output only as a temporary backward-compatibility field during migration; remove it after consumers switch to the shared walk-forward summary.
- [ ] Add tests for no-window coverage, stable multi-window selection, and blocker propagation into the acceptance checklist.
- [ ] Verify with `uv run pytest tests/test_btst_early_runner_walk_forward.py tests/test_analyze_btst_early_runner_v1_script.py -q`.

**Done when:** Walk-forward evidence for early runner is produced by the shared backtesting framework and can be compared directly with other BTST rollout surfaces.

### P6: Emit Standalone Daily Tables and Keep Manifest / Control Tower in Sync

**Why sixth:** The docs ask for daily watchlist / priority / second-entry tables. Right now those exist only inside the aggregate latest artifact.

**Files:**

- Create: `scripts/generate_btst_early_runner_daily_tables.py`
- Modify: `scripts/generate_reports_manifest.py`
- Modify: `scripts/run_btst_nightly_control_tower.py`
- Test: `tests/test_generate_btst_early_runner_daily_tables.py`
- Test: `tests/test_generate_reports_manifest_script.py`

- [ ] Emit per-day `early_runner_watchlist`, `early_runner_priority`, and `second_entry_reentry` JSON / Markdown tables from the same source analysis payload used for the latest artifact.
- [ ] Register these daily tables in the report manifest so downstream tooling can find them by trade date instead of parsing one aggregate file.
- [ ] Extend control-tower summary and delta helpers so they can point operators to the latest daily table paths, not just to ticker lists embedded in the summary.
- [ ] Add tests that verify daily-table filenames are deterministic, manifest entries are created, and the latest summary still stays backward-compatible.
- [ ] Verify with `uv run pytest tests/test_generate_btst_early_runner_daily_tables.py tests/test_generate_reports_manifest_script.py -q`.

**Done when:** Operators can inspect daily standalone early-runner outputs without reverse-engineering them from the aggregate artifact.

### P7: Refresh Evidence, Rerun Acceptance, and Decide Rollout Stage

**Why last:** After the code work, the repo still needs fresh evidence. The current latest artifact is not rollout-ready, and no amount of code change matters if the rerun still produces zero first-entry samples.

**Files:**

- Modify: `scripts/generate_reports_manifest.py`
- Modify: `scripts/analyze_btst_early_runner_v1.py`
- Test: existing focused early-runner tests

- [ ] Regenerate `btst_early_runner_v1_latest.{json,md}` and the new daily tables from a refreshed report window after the prior phases land.
- [ ] Rerun manifest and nightly control-tower generation so `early_runner_summary` and deltas reflect the new signal contract.
- [ ] Inspect whether first-entry ledger sample count, after-cost expectancy, and month-level walk-forward blockers actually improve; if not, treat that as a signal-quality blocker, not an implementation failure.
- [ ] Split rollout decision into three explicit states: `research_only`, `shadow_only`, and `formal_runtime_pilot_ready`.
- [ ] Verify with `uv run pytest tests/test_analyze_btst_early_runner_v1_script.py tests/test_generate_reports_manifest_script.py tests/test_btst_control_tower_scripts.py -k early_runner -q`.

**Done when:** The code path is complete and the artifact truthfully says whether the lane is still shadow-only or eligible for a guarded formal pilot.

## Recommended Implementation Sequence

1. P0 contract stabilization
2. P1 theme radar
3. P2 real intraday confirmation
4. P3 board-rule and tradeability fidelity
5. P4 formal runtime integration
6. P5 shared walk-forward calibration
7. P6 standalone daily artifacts
8. P7 rerun evidence and rollout decision

## Stop Conditions

Pause the implementation and reassess if any of the following becomes true:

- Theme radar cannot be built from current snapshot data without introducing new unsupported upstream contracts.
- Intraday confirmation cannot reuse current bars / ticks access and would require a separate data plane not yet available in the repo.
- Runtime promotion creates duplicate or conflicting entries inside `selection_targets` instead of extending the existing routing contract.
- Walk-forward integration proves the first-entry lane remains empty after refreshed evidence runs; in that case the next task is signal redesign, not more plumbing.

## Definition of Success

The plan is complete only when all of the following are true:

- Early runner has a theme-first pre-layer instead of stock-only scoring.
- Real T+1 confirmation is built from intraday data, not only from next-day daily proxies.
- Confirmed early-runner rows can enter the existing short-trade runtime path through explicit gates.
- Walk-forward evidence is produced by shared backtesting helpers.
- Daily watchlist / priority / second-entry artifacts exist as standalone files.
- Fresh reruns either promote the lane to a guarded runtime pilot or produce an explicit evidence-based blocker list.
